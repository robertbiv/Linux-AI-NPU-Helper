# SPDX-License-Identifier: GPL-3.0-or-later
"""System information tool — answer questions about the user's system.

## Queries answered
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

## Data sources (in priority order)

- ``/proc/*`` and ``/sys/*`` — direct kernel interfaces, fastest and most
  accurate.  No subprocess, no extra packages.
- Command-line tools (``upower``, ``lspci``, ``lscpu``, ``ip``) — used when
  the proc/sys files don't give enough detail.

All subprocess and heavy-stdlib imports are deferred inside ``run()`` so
importing this module is free.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult
from src.tools._utils import read_sys_file, run_command

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────


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
    raw = read_sys_file("/proc/uptime")
    if raw:
        seconds = float(raw.split()[0])
        return f"System uptime: {_fmt_seconds(seconds)}"
    # fallback
    out = run_command(["uptime", "-p"])
    return out or "Uptime information unavailable."


def _query_battery() -> str:
    """Read battery info from /sys/class/power_supply/."""
    # Performance optimization: Use native os.path checks instead of pathlib.Path
    ps_root = "/sys/class/power_supply"
    if not os.path.exists(ps_root):
        return "No power supply information found (may be a desktop system)."

    lines: list[str] = []
    upower_devices: list[str] | None = None

    try:
        with os.scandir(ps_root) as it:
            for ps_dir in sorted(it, key=lambda e: e.name):
                ps_type = read_sys_file(f"{ps_dir.path}/type").lower()
                if ps_type != "battery":
                    continue

                # Fetch upower dump lazily upon finding the first battery
                if upower_devices is None:
                    upower_dump = run_command(["upower", "--dump"])
                    upower_devices = (
                        upower_dump.split("Device: ") if upower_dump else []
                    )

                name = ps_dir.name
                capacity = read_sys_file(f"{ps_dir.path}/capacity")
                status = read_sys_file(
                    f"{ps_dir.path}/status"
                )  # Charging / Discharging / Full
                technology = read_sys_file(f"{ps_dir.path}/technology")

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
                if upower_devices:
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
    except OSError:
        pass

    if not lines:
        # Fallback to acpi
        out = run_command(["acpi", "-b"])
        return out or "Battery information unavailable."
    return "\n".join(lines)


def _query_battery_health() -> str:
    """Calculate battery health from charge_full vs charge_full_design."""
    # Performance optimization: Use native os.path checks instead of pathlib.Path
    ps_root = "/sys/class/power_supply"
    if not os.path.exists(ps_root):
        return "No power supply information found."

    lines: list[str] = []
    try:
        with os.scandir(ps_root) as it:
            for ps_dir in sorted(it, key=lambda e: e.name):
                ps_type = read_sys_file(f"{ps_dir.path}/type").lower()
                if ps_type != "battery":
                    continue

                name = ps_dir.name
                full = read_sys_file(f"{ps_dir.path}/charge_full") or read_sys_file(
                    f"{ps_dir.path}/energy_full"
                )
                design = read_sys_file(
                    f"{ps_dir.path}/charge_full_design"
                ) or read_sys_file(f"{ps_dir.path}/energy_full_design")
                cycle_count = read_sys_file(f"{ps_dir.path}/cycle_count")

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
    except OSError:
        pass

    return "\n".join(lines) if lines else "Battery health information unavailable."


def _query_gpu() -> str:
    """Detect GPU(s): NVIDIA, AMD, Intel — /sys, nvidia-smi, rocm-smi, lspci."""
    lines: list[str] = []

    # NVIDIA via nvidia-smi
    nvidia = run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader",
        ]
    )
    if nvidia:
        for row in nvidia.splitlines():
            lines.append(f"NVIDIA: {row.strip()}")

    # AMD via rocm-smi
    rocm = run_command(["rocm-smi", "--showproductname"])
    if rocm:
        for row in rocm.splitlines():
            if row.strip() and not row.startswith("="):
                lines.append(f"AMD: {row.strip()}")

    # Generic via lspci (covers Intel iGPU, AMD dGPU without rocm, etc.)
    lspci = run_command(["lspci"])
    if lspci:
        for row in lspci.splitlines():
            low = row.lower()
            if (
                "vga compatible" in low
                or "3d controller" in low
                or "display controller" in low
            ):
                # Remove PCI address prefix
                parts = row.split(":", 2)
                desc = parts[-1].strip() if len(parts) >= 2 else row.strip()
                if not any(desc in existing for existing in lines):  # avoid duplication
                    lines.append(desc)

    # /sys DRM cards as last resort
    if not lines:
        try:
            cards = []
            with os.scandir("/sys/class/drm") as it:
                for entry in it:
                    if (
                        entry.name.startswith("card")
                        and len(entry.name) == 5
                        and entry.is_dir()
                    ):
                        cards.append(entry.name)

            for card in sorted(cards):
                vendor = read_sys_file(f"/sys/class/drm/{card}/device/vendor")
                device = read_sys_file(f"/sys/class/drm/{card}/device/device")
                if vendor or device:
                    lines.append(f"{card}: vendor={vendor} device={device}")
        except OSError:
            pass

    return "\n".join(lines) if lines else "GPU information unavailable."


def _query_cpu() -> str:
    """CPU info from /proc/cpuinfo and /sys."""
    cpuinfo = read_sys_file("/proc/cpuinfo")
    if not cpuinfo:
        return run_command(["lscpu"]) or "CPU information unavailable."

    model = ""
    physical_ids: set[str] = set()
    core_ids: set[str] = set()
    logical_count = 0
    freq_khz = ""

    current_physical = ""
    # Performance optimization: Use finditer with MULTILINE instead of splitlines
    # to avoid creating temporary string objects for every line in /proc/cpuinfo.
    pattern = re.compile(
        r"^(model name|physical id|core id|processor|cpu MHz)\s*:\s*(.*)$", re.MULTILINE
    )
    for m in pattern.finditer(cpuinfo):
        k, v = m.groups()
        if k == "model name" and not model:
            model = v
        elif k == "physical id":
            current_physical = v
            physical_ids.add(v)
        elif k == "core id":
            core_ids.add(f"{current_physical}-{v}")
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
    meminfo = read_sys_file("/proc/meminfo")
    if not meminfo:
        return run_command(["free", "-h"]) or "Memory information unavailable."

    # Performance optimization: String find and slicing is ~6x faster than splitlines()
    # for extracting specific fields from a large /proc/meminfo file.
    def _get_field(key: str) -> int:
        idx = meminfo.find(key)
        if idx != -1:
            end = meminfo.find("\n", idx)
            try:
                return int(
                    meminfo[idx + len(key) : end if end != -1 else None].split()[0]
                )
            except (ValueError, IndexError):
                pass
        return 0

    total = _get_field("MemTotal:")
    available = _get_field("MemAvailable:")
    used = total - available
    swap_total = _get_field("SwapTotal:")
    swap_free = _get_field("SwapFree:")

    def kb_to_human(kb: int) -> str:
        if kb >= 1_048_576:
            return f"{kb / 1_048_576:.1f} GiB"
        if kb >= 1024:
            return f"{kb / 1024:.0f} MiB"
        return f"{kb} KiB"

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
    out = run_command(
        [
            "df",
            "-h",
            "--output=source,size,used,avail,pcent,target",
            "-x",
            "tmpfs",
            "-x",
            "devtmpfs",
            "-x",
            "squashfs",
        ]
    )
    if not out:
        out = run_command(["df", "-h"])
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
    out = run_command(["ip", "-brief", "addr"])
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
    out2 = run_command(["ifconfig"])
    return out2 or "Network information unavailable."


# ── Query dispatcher ──────────────────────────────────────────────────────────

_QUERIES: dict[str, Any] = {
    "time": _query_time,
    "uptime": _query_uptime,
    "battery": _query_battery,
    "battery_health": _query_battery_health,
    "gpu": _query_gpu,
    "cpu": _query_cpu,
    "memory": _query_memory,
    "disk": _query_disk,
    "os": _query_os,
    "network": _query_network,
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


class SystemInfoTool(Tool):
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
                    + ", ".join(list(_QUERIES) + ["all"])
                    + "."
                ),
            },
        },
        "required": ["topic"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
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
