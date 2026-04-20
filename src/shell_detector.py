# SPDX-License-Identifier: GPL-3.0-or-later
"""Shell detection — find the user's login/interactive shell.

## Detection order
1. ``$SHELL`` environment variable (set by login daemons on every modern distro).
2. ``/proc/<ppid>/exe`` — resolve the parent process executable.
3. ``/etc/passwd`` entry for the current user.
4. Fallback: ``/bin/sh``.

Results are cached after the first call (``lru_cache``).
"""

from __future__ import annotations

import logging
import os
import pwd
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Map shell executable stem → family name
_SHELL_FAMILIES: dict[str, str] = {
    "bash": "bash",
    "zsh": "zsh",
    "fish": "fish",
    "ksh": "ksh",
    "ksh93": "ksh",
    "mksh": "ksh",
    "pdksh": "ksh",
    "dash": "sh",
    "sh": "sh",
    "ash": "sh",
    "busybox": "sh",
    "tcsh": "csh",
    "csh": "csh",
    "elvish": "elvish",
    "nushell": "nushell",
    "nu": "nushell",
    "xonsh": "xonsh",
}


@dataclass
class ShellInfo:
    """Information about the user's shell."""

    path: str
    """Absolute path, e.g. ``/usr/bin/zsh``."""

    name: str
    """Executable name without path, e.g. ``zsh``."""

    family: str
    """Normalised shell family: ``bash``, ``zsh``, ``fish``, ``ksh``,
    ``sh``, ``csh``, ``elvish``, ``nushell``, ``xonsh``, or ``unknown``."""

    version: str = ""
    """Version string if detectable, otherwise empty."""

    def supports_readline_prefill(self) -> bool:
        """Return True if this shell supports pre-filling the command line."""
        return self.family in ("bash", "zsh", "fish", "ksh")

    def __str__(self) -> str:
        v = f" {self.version}" if self.version else ""
        return f"{self.name}{v} ({self.path})"


def _stem(path: str) -> str:
    """Return the executable stem, stripping version suffixes like bash-5.2."""
    name = Path(path).name
    return re.split(r"[-_]\d", name)[0].lower()


def _family(stem: str) -> str:
    return _SHELL_FAMILIES.get(stem, "unknown")


def _version(shell_path: str) -> str:
    """Try to get the shell version string."""
    import shutil
    import subprocess

    if not shutil.which(shell_path):
        return ""
    try:
        r = subprocess.run(
            [shell_path, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        first = (r.stdout or r.stderr).splitlines()
        return first[0].strip() if first else ""
    except Exception:  # noqa: BLE001
        return ""


def _from_path(path: str) -> ShellInfo:
    stem = _stem(path)
    return ShellInfo(
        path=path,
        name=Path(path).name,
        family=_family(stem),
        version=_version(path),
    )


def _from_user_db() -> str | None:
    """Return the login shell from /etc/passwd for the current user."""
    try:
        entry = pwd.getpwuid(os.getuid())
        shell = entry.pw_shell
        return shell if shell else None
    except Exception:  # noqa: BLE001
        return None


def _from_parent_proc() -> str | None:
    """Try to detect shell from /proc/<ppid>/exe."""
    try:
        ppid = os.getppid()
        exe = Path(f"/proc/{ppid}/exe").resolve()
        name = exe.name.lower()
        # Only accept it if it looks like a known shell
        if any(name.startswith(s) for s in _SHELL_FAMILIES):
            return str(exe)
    except Exception:  # noqa: BLE001
        pass
    return None


@lru_cache(maxsize=1)
def detect() -> ShellInfo:
    """Detect the user's shell and return a :class:`ShellInfo`.

    Results are cached; call ``detect.cache_clear()`` in tests.
    """
    # 1. $SHELL env var
    env_shell = os.environ.get("SHELL", "").strip()
    if env_shell and Path(env_shell).exists():
        logger.debug("shell_detector: using $SHELL=%s", env_shell)
        return _from_path(env_shell)

    # 2. Parent process
    parent = _from_parent_proc()
    if parent:
        logger.debug("shell_detector: detected from parent proc: %s", parent)
        return _from_path(parent)

    # 3. System user database
    etc_shell = _from_user_db()
    if etc_shell and Path(etc_shell).exists():
        logger.debug("shell_detector: using system login shell: %s", etc_shell)
        return _from_path(etc_shell)

    # 4. Fallback
    logger.debug("shell_detector: falling back to /bin/sh")
    return _from_path("/bin/sh")
