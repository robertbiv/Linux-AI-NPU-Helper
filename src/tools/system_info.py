# SPDX-License-Identifier: GPL-3.0-or-later
"""System information tool — answer questions about the user's system.

Queries answered
----------------
``time``        Current local date and time.
``uptime``      How long the system has been running.
``battery``     Battery percentage, charging status, and time remaining.
``battery_health``  Battery health (design capacity vs actual capacity).
``gpu``         Graphics card model(s).
``cpu``         CPU model, core/thread count, current frequency.
``memory``      RAM total, used, available.
``disk``        Disk usage for mounted filesystems.
``os``          Distro name, version, kernel, package manager.
``network``     Active network interfaces and their IP addresses.
``all``         A concise summary covering every topic above.

Data sources (in priority order)
---------------------------------
- ``/proc/*`` and ``/sys/*`` — direct kernel interfaces, fastest and most
  accurate.  No subprocess, no extra packages.
- Command-line tools (``upower``, ``lspci``, ``lscpu``, ``ip``) — used when
  the proc/sys files don't give enough detail.

All subprocess and heavy-stdlib imports are deferred inside ``run()`` so
importing this module is free.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.tools._base import SearchResult, ToolResult

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _read(path: str, default: str = "") -> str:
    """Read a single-line file from /proc or /sys, stripping whitespace."""
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return default


def _run_cmd(cmd: list[str], timeout: int = 6) -> str:
    """Run a command and return stdout, or empty string on failure."""
    import shutil
    import subprocess
    if not shutil.which(cmd[0]):
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _fmt_seconds(total: float) -> str:
    """Format a seconds value as 'X days Y hours Z minutes'."""
    total = int(total)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return ", ".join(parts)


# ── Individual queries ────────────────────────────────────────────────────────


def _query_time() -> str:
    now = datetime.now()
    utc = datetime.now(timezone.utc)
    return (
        f"Local time : {now.strftime('%A, %B %d %Y  %H:%M:%S')}\n"
        f"UTC time   : {utc.strftime('%H:%M:%S UTC')}"
    )


def _query_uptime() -> str:
    raw = _read("/proc/uptime")
    if raw:
        seconds = float(raw.split()[0])
        return f"System uptime: {_fmt_seconds(seconds)}"
    # fallback
    out = _run_cmd(["uptime", "-p"])
    return out or "Uptime information unavailable."


def _query_battery() -> str:
    """Read battery info from /sys/class/power_supply/."""
    ps_root = Path("/sys/class/power_supply")
    if not ps_root.exists():
        return "No power supply information found (may be a desktop system)."

    lines: list[str] = []
    upower_devices: list[str] | None = None

    for ps_dir in sorted(ps_root.iterdir()):
        ps_type = _read(str(ps_dir / "type")).lower()
        if ps_type != "battery":
            continue

        # Fetch upower dump lazily upon finding the first battery
        if upower_devices is None:
            upower_dump = _run_cmd(["upower", "--dump"])
            upower_devices = upower_dump.split("Device: ") if upower_dump else []

        name = ps_dir.name
        capacity = _read(str(ps_dir / "capacity"))
        status = _read(str(ps_dir / "status"))        # Charging / Discharging / Full
        technology = _read(str(ps_dir / "technology"))

        line = f"{name}: "
        if capacity:
            line += f"{capacity}% "
        if status:
            line += f"({status})"
        if technology:
            line += f" [{technology}]"

        # Time remaining from upower if available
        eta = ""
        device_path = f"/org/freedesktop/UPower/devices/battery_{name}"
        for device_block in upower_devices:
            # Ensure exact path match (up to newline or exact end of string)
            block_lines = device_block.splitlines()
            if block_lines and block_lines[0].strip() == device_path:
                for line_str in block_lines[1:]:
                    if "time to" in line_str.lower():
                        eta = line_str.strip()
                        break
                break

        if eta:
            line += f"  {eta}"

        lines.append(line)

    if not lines:
        # Fallback to acpi
        out = _run_cmd(["acpi", "-b"])
        return out or "Battery information unavailable."
    return "\n".join(lines)


def _query_battery_health() -> str:
    """Calculate battery health from charge_full vs charge_full_design."""
    ps_root = Path("/sys/class/power_supply")
    if not ps_root.exists():
        return "No power supply information found."

    lines: list[str] = []
    for ps_dir in sorted(ps_root.iterdir()):
        ps_type = _read(str(ps_dir / "type")).lower()
        if ps_type != "battery":
            continue

        name = ps_dir.name
        full = _read(str(ps_dir / "charge_full")) or _read(str(ps_dir / "energy_full"))
        design = (
            _read(str(ps_dir / "charge_full_design"))
            or _read(str(ps_dir / "energy_full_design"))
        )
        cycle_count = _read(str(ps_dir / "cycle_count"))

        if full and design:
            try:
                health_pct = round(int(full) / int(design) * 100, 1)
                line = f"{name}: {health_pct}% health"
                if cycle_count and cycle_count != "0":
                    line += f"  ({cycle_count} charge cycles)"
                lines.append(line)
            except (ValueError, ZeroDivisionError):
                lines.append(f"{name}: health data unreadable.")
        else:
            lines.append(f"{name}: charge capacity data unavailable.")

    return "\n".join(lines) if lines else "Battery health information unavailable."


def _query_gpu() -> str:
    """Detect GPU(s): NVIDIA, AMD, Intel — /sys, nvidia-smi, rocm-smi, lspci."""
    lines: list[str] = []

    # NVIDIA via nvidia-smi
    nvidia = _run_cmd(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                       "--format=csv,noheader"])
    if nvidia:
        for row in nvidia.splitlines():
            lines.append(f"NVIDIA: {row.strip()}")

    # AMD via rocm-smi
    rocm = _run_cmd(["rocm-smi", "--showproductname"])
    if rocm:
        for row in rocm.splitlines():
            if row.strip() and not row.startswith("="):
                lines.append(f"AMD: {row.strip()}")

    # Generic via lspci (covers Intel iGPU, AMD dGPU without rocm, etc.)
    lspci = _run_cmd(["lspci"])
    if lspci:
        for row in lspci.splitlines():
            low = row.lower()
            if any(k in low for k in ("vga compatible", "3d controller", "display controller")):
                # Remove PCI address prefix
                parts = row.split(":", 2)
                desc = parts[-1].strip() if len(parts) >= 2 else row.strip()
                if not any(desc in existing for existing in lines):  # avoid duplication
                    lines.append(desc)

    # /sys DRM cards as last resort
    if not lines:
        for card in sorted(Path("/sys/class/drm").glob("card?")) :
            vendor_path = card / "device" / "vendor"
            device_path = card / "device" / "device"
            vendor = _read(str(vendor_path))
            device = _read(str(device_path))
            if vendor or device:
                lines.append(f"{card.name}: vendor={vendor} device={device}")

    return "\n".join(lines) if lines else "GPU information unavailable."


def _query_cpu() -> str:
    """CPU info from /proc/cpuinfo and /sys."""
    cpuinfo = _read("/proc/cpuinfo")
    if not cpuinfo:
        return _run_cmd(["lscpu"]) or "CPU information unavailable."

    model = ""
    physical_ids: set[str] = set()
    core_ids: set[str] = set()
    logical_count = 0
    freq_khz = ""

    current_physical = ""
    current_core = ""
    for line in cpuinfo.splitlines():
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k == "model name" and not model:
            model = v
        elif k == "physical id":
            current_physical = v
            physical_ids.add(v)
        elif k == "core id":
            current_core = v
            core_ids.add(f"{current_physical}-{current_core}")
        elif k == "processor":
            logical_count += 1
        elif k == "cpu MHz" and not freq_khz:
            freq_khz = v

    sockets = len(physical_ids) or 1
    cores = len(core_ids) or (logical_count // 2 or logical_count)
    threads = logical_count

    parts = [f"Model   : {model}"] if model else []
    parts.append(f"Sockets : {sockets}   Cores: {cores}   Threads: {threads}")
    if freq_khz:
        try:
            ghz = round(float(freq_khz) / 1000, 2)
            parts.append(f"Current : {ghz} GHz")
        except ValueError:
            pass
    return "\n".join(parts)


def _query_memory() -> str:
    """Memory info from /proc/meminfo."""
    meminfo = _read("/proc/meminfo")
    if not meminfo:
        return _run_cmd(["free", "-h"]) or "Memory information unavailable."

    fields: dict[str, int] = {}
    for line in meminfo.splitlines():
        k, _, v = line.partition(":")
        try:
            fields[k.strip()] = int(v.strip().split()[0])  # kB
        except (ValueError, IndexError):
            pass

    def kb_to_human(kb: int) -> str:
        if kb >= 1_048_576:
            return f"{kb / 1_048_576:.1f} GiB"
        if kb >= 1024:
            return f"{kb / 1024:.0f} MiB"
        return f"{kb} KiB"

    total     = fields.get("MemTotal", 0)
    available = fields.get("MemAvailable", 0)
    used      = total - available
    swap_total = fields.get("SwapTotal", 0)
    swap_free  = fields.get("SwapFree", 0)

    lines = [
        f"RAM   total={kb_to_human(total)}  used={kb_to_human(used)}  "
        f"available={kb_to_human(available)}",
    ]
    if swap_total:
        swap_used = swap_total - swap_free
        lines.append(
            f"Swap  total={kb_to_human(swap_total)}  used={kb_to_human(swap_used)}"
        )
    return "\n".join(lines)


def _query_disk() -> str:
    """Disk usage from df."""
    out = _run_cmd(["df", "-h", "--output=source,size,used,avail,pcent,target",
                    "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs"])
    if not out:
        out = _run_cmd(["df", "-h"])
    return out or "Disk information unavailable."


def _query_os() -> str:
    """OS info from os_detector."""
    try:
        from src.os_detector import detect
        info = detect()
        parts = [f"Distribution : {info.pretty_name or info.name}"]
        if info.kernel:
            parts.append(f"Kernel       : {info.kernel}")
        if info.architecture:
            parts.append(f"Architecture : {info.architecture}")
        if info.package_manager:
            parts.append(f"Pkg manager  : {info.package_manager}")
        if info.init_system and info.init_system != "unknown":
            parts.append(f"Init system  : {info.init_system}")
        if info.desktop and info.desktop not in ("none", "unknown"):
            parts.append(f"Desktop      : {info.desktop}")
        if info.hostname:
            parts.append(f"Hostname     : {info.hostname}")
        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        return f"OS info unavailable: {exc}"


def _query_network() -> str:
    """Network interfaces and IPs from /proc/net and ip command."""
    lines: list[str] = []

    # Try `ip -brief addr` first — clean tabular output
    out = _run_cmd(["ip", "-brief", "addr"])
    if out:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                iface = parts[0]
                state = parts[1]
                addrs = parts[2:] if len(parts) > 2 else ["(no address)"]
                lines.append(f"{iface:20s} {state:10s} {' '.join(addrs)}")
        return "\n".join(lines) if lines else "No network interfaces found."

    # Fallback: /proc/net/if_inet6 for IPv6 + /proc/net/fib_trie for IPv4
    out2 = _run_cmd(["ifconfig"])
    return out2 or "Network information unavailable."


# ── Query dispatcher ──────────────────────────────────────────────────────────

_QUERIES: dict[str, Any] = {
    "time":           _query_time,
    "uptime":         _query_uptime,
    "battery":        _query_battery,
    "battery_health": _query_battery_health,
    "gpu":            _query_gpu,
    "cpu":            _query_cpu,
    "memory":         _query_memory,
    "disk":           _query_disk,
    "os":             _query_os,
    "network":        _query_network,
}


def _query_all() -> str:
    """Return a concise multi-section system summary."""
    sections: list[str] = []
    for topic, fn in _QUERIES.items():
        try:
            result = fn()
            sections.append(f"### {topic.upper().replace('_', ' ')}\n{result}")
        except Exception as exc:  # noqa: BLE001
            sections.append(f"### {topic.upper()}\n(error: {exc})")
    return "\n\n".join(sections)


# ── Tool class ────────────────────────────────────────────────────────────────


class SystemInfoTool:
    """Answer questions about the user's system hardware and software.

    Reads from ``/proc`` and ``/sys`` wherever possible (no subprocess
    overhead) and falls back to CLI tools for richer detail.
    """

    name = "system_info"
    description = (
        "Query system information: time, uptime, battery level and health, "
        "GPU, CPU, memory, disk, OS details, network interfaces. "
        "Use topic='all' for a full summary."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "enum": list(_QUERIES) + ["all"],
                "description": (
                    "What to query. One of: "
                    + ", ".join(list(_QUERIES) + ["all"]) + "."
                ),
            },
        },
        "required": ["topic"],
    }

    def run(self, args: dict[str, Any]):  # noqa: ANN201
        topic: str = args.get("topic", "").strip().lower()
        valid = set(_QUERIES) | {"all"}
        if topic not in valid:
            return ToolResult(
                tool_name=self.name,
                error=(
                    f"Unknown topic '{topic}'. "
                    f"Valid topics: {', '.join(sorted(valid))}."
                ),
            )

        try:
            if topic == "all":
                text = _query_all()
            else:
                text = _QUERIES[topic]()
        except Exception as exc:  # noqa: BLE001
            logger.exception("SystemInfoTool error for topic '%s'", topic)
            return ToolResult(tool_name=self.name, error=str(exc))

        return ToolResult(
            tool_name=self.name,
            results=[SearchResult(path=f"sysinfo:{topic}", snippet=text)],
        )

    def schema_text(self) -> str:
        topics = ", ".join(list(_QUERIES) + ["all"])
        return f"  {self.name}(topic: {topics}) — {self.description}"
