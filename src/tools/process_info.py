"""Process and power information tool.

Answers: what is slowing my computer, what is draining the battery,
which process uses the most CPU/RAM.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


def _read(path: str, default: str = "") -> str:
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return default


def _run(cmd: list[str], timeout: int = 8) -> str:
    import shutil
    import subprocess
    if not shutil.which(cmd[0]):
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _proc_name(pid: int) -> str:
    return _read(f"/proc/{pid}/comm")


def _proc_cmdline(pid: int) -> str:
    return _read(f"/proc/{pid}/cmdline").replace("\x00", " ").strip()[:60]


def _proc_mem_kb(pid: int) -> int:
    for line in _read(f"/proc/{pid}/status").splitlines():
        if line.startswith("VmRSS:"):
            try:
                return int(line.split()[1])
            except (ValueError, IndexError):
                pass
    return 0


def _all_pids() -> list[int]:
    return [int(p.name) for p in Path("/proc").iterdir()
            if p.name.isdigit() and (p / "stat").exists()]


def _top_cpu(n: int = 10) -> list[dict]:
    clk = os.sysconf("SC_CLK_TCK")
    pids = _all_pids()

    def _jiffies(pid: int) -> int:
        s = _read(f"/proc/{pid}/stat").split()
        try:
            return int(s[13]) + int(s[14])
        except (IndexError, ValueError):
            return 0

    snap1 = {pid: _jiffies(pid) for pid in pids}
    time.sleep(0.4)
    snap2 = {pid: _jiffies(pid) for pid in pids}

    results = []
    for pid in snap1:
        if pid not in snap2:
            continue
        pct = (snap2[pid] - snap1[pid]) / clk / 0.4 * 100
        if pct < 0.1:
            continue
        results.append({
            "pid": pid, "name": _proc_name(pid),
            "cmdline": _proc_cmdline(pid),
            "cpu_pct": round(pct, 1),
            "mem_mb": round(_proc_mem_kb(pid) / 1024, 1),
        })
    results.sort(key=lambda x: x["cpu_pct"], reverse=True)
    return results[:n]


def _top_mem(n: int = 10) -> list[dict]:
    results = []
    for pid in _all_pids():
        kb = _proc_mem_kb(pid)
        if kb < 1024:
            continue
        results.append({
            "pid": pid, "name": _proc_name(pid),
            "cmdline": _proc_cmdline(pid),
            "mem_mb": round(kb / 1024, 1),
        })
    results.sort(key=lambda x: x["mem_mb"], reverse=True)
    return results[:n]


def _fmt_table(procs: list[dict], sort_key: str) -> str:
    if not procs:
        return "No significant processes found."
    unit = "%" if "cpu" in sort_key else "MB"
    lines = [f"{'PID':>7}  {'NAME':<20}  {'VALUE':>8}  COMMAND"]
    for p in procs:
        lines.append(
            f"{p['pid']:>7}  {p['name']:<20}  "
            f"{p.get(sort_key, 0):>7.1f}{unit}  {p['cmdline']}"
        )
    return "\n".join(lines)


def _battery_rate() -> str:
    ps_root = Path("/sys/class/power_supply")
    lines: list[str] = []
    if ps_root.exists():
        for ps in sorted(ps_root.iterdir()):
            if _read(str(ps / "type")).lower() != "battery":
                continue
            pwr = _read(str(ps / "power_now"))
            if pwr:
                try:
                    lines.append(f"{ps.name}: {int(pwr)/1_000_000:.2f} W")
                except ValueError:
                    pass
    if not lines:
        out = _run(["upower", "-i",
                    "/org/freedesktop/UPower/devices/battery_BAT0"])
        for line in out.splitlines():
            if "energy-rate" in line.lower():
                lines.append(line.strip())
                break
    return "\n".join(lines) if lines else "Battery rate unavailable."


def _load_summary() -> str:
    raw = _read("/proc/loadavg").split()
    mem: dict[str, int] = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        try:
            mem[k.strip()] = int(v.strip().split()[0])
        except (ValueError, IndexError):
            pass

    def fmt(kb: int) -> str:
        return f"{kb/1024:.0f}MB" if kb < 1_048_576 else f"{kb/1_048_576:.1f}GB"

    lines = []
    if raw:
        lines.append(f"Load average (1/5/15 min): {raw[0]}  {raw[1]}  {raw[2]}")
    total = mem.get("MemTotal", 0)
    avail = mem.get("MemAvailable", 0)
    if total:
        lines.append(
            f"Memory: {fmt(total - avail)} used / {fmt(total)} total"
            f"  ({fmt(avail)} free)"
        )
    return "\n".join(lines)


_TOPICS = {"cpu", "memory", "battery", "load", "all"}


class ProcessInfoTool(Tool):
    """Show running processes and resource/power usage."""

    name = "process_info"
    description = (
        "Show processes by CPU/memory usage, battery discharge rate, and "
        "system load. Use to answer 'what is slowing my computer' or "
        "'what is draining my battery'."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "enum": sorted(_TOPICS),
                "description": "cpu | memory | battery | load | all",
            },
        },
        "required": ["topic"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        topic = args.get("topic", "all").strip().lower()
        if topic not in _TOPICS:
            return ToolResult(
                tool_name=self.name,
                error=f"Unknown topic '{topic}'. Valid: {', '.join(sorted(_TOPICS))}.",
            )

        sections: list[str] = []
        try:
            if topic in ("cpu", "all"):
                sections.append("### Top by CPU\n" + _fmt_table(_top_cpu(), "cpu_pct"))
            if topic in ("memory", "all"):
                sections.append("### Top by Memory\n" + _fmt_table(_top_mem(), "mem_mb"))
            if topic in ("battery", "all"):
                sections.append("### Battery discharge\n" + _battery_rate())
            if topic in ("load", "all"):
                sections.append("### System load\n" + _load_summary())
        except Exception as exc:  # noqa: BLE001
            logger.exception("ProcessInfoTool error")
            return ToolResult(tool_name=self.name, error=str(exc))

        text = "\n\n".join(sections)
        return ToolResult(
            tool_name=self.name,
            results=[SearchResult(path=f"proc:{topic}", snippet=text)],
        )
