# SPDX-License-Identifier: GPL-3.0-or-later
"""Internal utilities for the tools package."""

from __future__ import annotations


def read_sys_file(path: str, default: str = "") -> str:
    """Read a single-line file from /proc or /sys, stripping whitespace."""
    try:
        # Performance optimization: using open() is faster than Path().read_text()
        with open(path, "r", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def run_command(cmd: list[str], timeout: int = 8) -> str:
    """Run a command and return stdout, or empty string on failure.

    Includes lazy imports and error handling consistent with existing tools.
    """
    import shutil
    import subprocess

    if not shutil.which(cmd[0]):
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""
