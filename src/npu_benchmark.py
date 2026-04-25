# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware capability probe — drives dynamic NPU suitability labels.

Reads CPU, RAM, and NPU specifications from ``/proc`` and ``/sys`` without
subprocess calls wherever possible, then maps the results to a
:class:`HardwareCapabilities` dataclass that the rest of the application uses
to adjust which AI models are marked "excellent", "good", "fair", or
"not_recommended" for this specific machine.

## NPU TOPS estimation heuristics
AMD Ryzen AI 300 series (Strix Point)  →  50 TOPS
AMD Ryzen AI 200 series (Hawk Point)   →  16 TOPS
AMD Ryzen AI (Phoenix / Rembrandt)     →  10–12 TOPS
Intel Core Ultra (Meteor Lake)         →  34 TOPS
Intel Core Ultra 200V (Lunar Lake)     →  48 TOPS
Qualcomm Snapdragon X Elite            →  45 TOPS
No recognised NPU                      →   0 TOPS
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class HardwareCapabilities:
    """Measured / estimated capabilities of the host hardware."""

    npu_tops: float = 0.0
    """Estimated NPU throughput in Tera-Operations Per Second.
    ``0`` means no NPU was detected."""

    ram_gb: float = 0.0
    """Total system RAM in gigabytes."""

    cpu_cores: int = 0
    """Number of physical CPU cores."""

    cpu_freq_ghz: float = 0.0
    """Maximum CPU frequency in GHz."""

    npu_available: bool = False
    """``True`` when a usable NPU execution provider is detected."""

    npu_vendor: str = "unknown"
    """One of ``'amd_ryzen_ai'``, ``'intel_arc'``, ``'qualcomm'``,
    ``'unknown'``."""

    npu_memory_mb: int = 0
    """Dedicated NPU memory in MB (0 = shared with system RAM)."""

    cpu_model: str = ""
    """Human-readable CPU model string."""

    gpu_model: str = ""
    """Human-readable GPU/iGPU model string (empty if unavailable)."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Miscellaneous key-value pairs for future expansion."""

    # ── Derived properties ────────────────────────────────────────────────

    @property
    def tier(self) -> str:
        """Return a simple performance tier label.

        ``'high'``    — 30+ TOPS
        ``'mid'``     — 10–29 TOPS
        ``'low'``     — < 10 TOPS (incl. no NPU)
        """
        if self.npu_tops >= 30:
            return "high"
        if self.npu_tops >= 10:
            return "mid"
        return "low"

    @property
    def suitability_description(self) -> str:
        """Short human-readable sentence shown in the UI."""
        if not self.npu_available:
            if self.ram_gb >= 16:
                return (
                    f"No NPU detected — models will run on CPU "
                    f"({self.cpu_cores} cores, {self.ram_gb:.0f} GB RAM). "
                    "Performance depends on CPU speed."
                )
            return (
                "No NPU detected and limited RAM. "
                "Only small quantized models (≤3 B) are recommended."
            )
        tops_str = f"{self.npu_tops:.0f} TOPS" if self.npu_tops else "NPU"
        tier_map = {
            "high": f"High-performance NPU ({tops_str}) — all catalog models supported.",
            "mid": f"Mid-range NPU ({tops_str}) — quantized models up to ~8 B recommended.",
            "low": f"Entry-level NPU ({tops_str}) — small quantized models (≤3 B) recommended.",
        }
        return tier_map[self.tier]


# ── Probe helpers ─────────────────────────────────────────────────────────────


def _read_sys(path: str) -> str:
    try:
        # Performance optimization: using open() is faster than Path().read_text()
        with open(path, "r", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _read_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into a {key: kB} dict."""
    result: dict[str, int] = {}
    raw = _read_sys("/proc/meminfo")
    # Performance optimization: Use finditer with MULTILINE instead of splitlines
    # to avoid creating temporary string objects for every line in /proc/meminfo.
    pattern = re.compile(r"^([^:]+):\s*(\d+)", re.MULTILINE)
    for m in pattern.finditer(raw):
        key, val = m.groups()
        try:
            result[key] = int(val)
        except ValueError:
            pass
    return result


def _read_cpuinfo() -> list[dict[str, str]]:
    """Parse /proc/cpuinfo into a list of per-processor dicts."""
    procs: list[dict[str, str]] = []
    current: dict[str, str] = {}
    raw = _read_sys("/proc/cpuinfo")

    # Fast path: split by \n\n to isolate processors
    # This avoids .splitlines() overhead per-line and cleanly separates CPU blocks
    blocks = raw.split("\n\n")
    for block in blocks:
        if not block.strip():
            continue

        current = {}
        # We can safely use splitlines() here since block sizes are very small
        for line in block.split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                current[k.strip()] = v.strip()

        if current:
            procs.append(current)

    return procs


# Known CPU model → NPU TOPS mappings (heuristic, lowercase substring match)
_CPU_TOPS: list[tuple[str, float, str]] = [
    # pattern, TOPS, vendor
    ("ryzen ai 9 hx", 50.0, "amd_ryzen_ai"),  # Strix Point
    ("ryzen ai 7", 16.0, "amd_ryzen_ai"),  # Hawk Point
    ("ryzen ai 5", 16.0, "amd_ryzen_ai"),  # Hawk Point
    ("ryzen ai", 10.0, "amd_ryzen_ai"),  # Phoenix generic
    ("core ultra 200v", 48.0, "intel_arc"),  # Lunar Lake
    ("core ultra 2", 34.0, "intel_arc"),  # Arrow Lake
    ("core ultra", 34.0, "intel_arc"),  # Meteor Lake
    ("snapdragon x elite", 45.0, "qualcomm"),
    ("snapdragon x plus", 45.0, "qualcomm"),
    ("snapdragon x", 45.0, "qualcomm"),
]

# /sys paths that indicate AMD Ryzen AI NPU presence
_AMD_NPU_SYS_PATHS = [
    "/sys/class/misc/xdna0",
    "/sys/bus/platform/drivers/amdxdna",
    "/sys/bus/pci/drivers/amdxdna",
]

# /sys paths that indicate Intel NPU presence
_INTEL_NPU_SYS_PATHS = [
    "/sys/bus/pci/drivers/intel_vpu",
    "/sys/class/misc/intel_vpu0",
]


def _detect_npu_from_sys() -> tuple[bool, str, float]:
    """Return (available, vendor, tops_estimate) from /sys."""
    for p in _AMD_NPU_SYS_PATHS:
        if os.path.exists(p):
            return True, "amd_ryzen_ai", 10.0  # conservative; refined below
    for p in _INTEL_NPU_SYS_PATHS:
        if os.path.exists(p):
            return True, "intel_arc", 34.0
    return False, "unknown", 0.0


def _detect_npu_from_onnx() -> bool:
    """Return True when a usable NPU execution provider is available."""
    try:
        import onnxruntime as ort  # type: ignore[import]

        available = ort.get_available_providers()
        return any(
            p in available
            for p in (
                "VitisAIExecutionProvider",
                "OpenVINOExecutionProvider",
                "QNNExecutionProvider",
            )
        )
    except ImportError:
        return False


def _gpu_model_from_sys() -> str:
    drm = "/sys/class/drm"
    if not os.path.exists(drm):
        return ""
    try:
        with os.scandir(drm) as it:
            for d in sorted(it, key=lambda e: e.name):
                if not d.name.startswith("card") or not d.name[-1].isdigit():
                    continue
                label = _read_sys(f"{d.path}/device/label")
                if label:
                    return label
                product = _read_sys(f"{d.path}/device/product_name")
                if product:
                    return product
    except OSError:
        pass
    return ""


# ── Public API ────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def probe_hardware() -> HardwareCapabilities:
    """Probe the host hardware and return a :class:`HardwareCapabilities`.

    Results are cached after the first call (``lru_cache``).  Call
    :func:`probe_hardware.cache_clear` in tests to force re-probing.
    """
    hw = HardwareCapabilities()

    # ── RAM ──────────────────────────────────────────────────────────────
    meminfo = _read_meminfo()
    hw.ram_gb = meminfo.get("MemTotal", 0) / (1024 * 1024)

    # ── CPU ──────────────────────────────────────────────────────────────
    cpuinfo = _read_cpuinfo()
    if cpuinfo:
        hw.cpu_model = cpuinfo[0].get("model name", "")
        # Count physical cores
        physical_ids: set[str] = set()
        core_ids: set[tuple[str, str]] = set()
        for proc in cpuinfo:
            pid = proc.get("physical id", "0")
            cid = proc.get("core id", proc.get("processor", "0"))
            physical_ids.add(pid)
            core_ids.add((pid, cid))
        hw.cpu_cores = len(core_ids) or len(cpuinfo)

        # Max frequency
        freq_str = cpuinfo[0].get("cpu MHz", "0")
        try:
            hw.cpu_freq_ghz = float(freq_str) / 1000
        except ValueError:
            pass
        # Try /sys for boost frequency
        max_freq = _read_sys("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
        if max_freq:
            try:
                hw.cpu_freq_ghz = int(max_freq) / 1_000_000
            except ValueError:
                pass

    # ── NPU from /sys ────────────────────────────────────────────────────
    sys_npu_ok, sys_vendor, sys_tops = _detect_npu_from_sys()
    onnx_npu_ok = _detect_npu_from_onnx()
    hw.npu_available = sys_npu_ok or onnx_npu_ok
    if hw.npu_available:
        hw.npu_vendor = sys_vendor

    # ── Refine TOPS from CPU model name ──────────────────────────────────
    cpu_lower = hw.cpu_model.lower()
    for pattern, tops, vendor in _CPU_TOPS:
        if pattern in cpu_lower:
            hw.npu_tops = tops
            if hw.npu_available:
                hw.npu_vendor = vendor
            elif tops > 0:
                # CPU model suggests NPU but sys didn't find it — mark available
                hw.npu_available = True
                hw.npu_vendor = vendor
            break

    # If /sys confirmed NPU but no TOPS estimate from CPU name, keep sys estimate
    if hw.npu_available and hw.npu_tops == 0:
        hw.npu_tops = sys_tops if sys_tops > 0 else 10.0

    # ── GPU ──────────────────────────────────────────────────────────────
    hw.gpu_model = _gpu_model_from_sys()

    logger.info(
        "Hardware probe: CPU=%r cores=%d RAM=%.1f GB NPU=%s TOPS=%.0f tier=%s",
        hw.cpu_model,
        hw.cpu_cores,
        hw.ram_gb,
        hw.npu_vendor if hw.npu_available else "none",
        hw.npu_tops,
        hw.tier,
    )
    return hw


# ── Suitability adjustment ────────────────────────────────────────────────────

_FIT_ORDER = {"excellent": 0, "good": 1, "fair": 2, "not_recommended": 3}
_FIT_LABELS = ["excellent", "good", "fair", "not_recommended"]


def _bump_fit(fit: str, delta: int) -> str:
    """Shift *fit* by *delta* steps (positive = worse, negative = better)."""
    idx = _FIT_ORDER.get(fit, 1)
    new_idx = max(0, min(len(_FIT_LABELS) - 1, idx + delta))
    return _FIT_LABELS[new_idx]


def adjust_npu_fit(static_fit: str, hw: HardwareCapabilities) -> str:
    """Return a hardware-adjusted NPU fit rating.

    Args:
        static_fit:
            The pre-defined catalog rating (``"excellent"`` / ``"good"`` /
            ``"fair"`` / ``"not_recommended"``).
        hw:
            :class:`HardwareCapabilities` for the current machine.

    Returns:
        Adjusted fit rating — may be better or worse than *static_fit*.
    """
    fit = static_fit

    # No NPU at all — everything needs a CPU/GPU fallback
    if not hw.npu_available or hw.npu_tops == 0:
        fit = _bump_fit(fit, +2)  # demote by 2 levels

    # Very low TOPS (< 8) — demote by 1
    elif hw.npu_tops < 8:
        fit = _bump_fit(fit, +1)

    # High-end NPU (≥ 30 TOPS) — promote by 1
    elif hw.npu_tops >= 30:
        fit = _bump_fit(fit, -1)

    # Insufficient RAM for most models
    if hw.ram_gb < 8:
        fit = _bump_fit(fit, +1)

    # Plenty of RAM helps even without a strong NPU
    elif hw.ram_gb >= 32:
        fit = _bump_fit(fit, -1)

    return fit
