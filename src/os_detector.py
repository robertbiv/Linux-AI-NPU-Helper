# SPDX-License-Identifier: GPL-3.0-or-later
"""OS detection for the Linux AI NPU Assistant.

Detects the running Linux distribution and environment so the AI assistant
can generate distro-accurate commands (e.g. ``apt`` on Ubuntu/Debian,
``dnf`` on Fedora, ``pacman`` on Arch, etc.).

## Detection sources (in priority order)

1. ``/etc/os-release``  — machine-readable, present on all modern distros.
2. ``platform.freedesktop_os_release()``  — Python 3.10+ stdlib wrapper for
   the same file (used when available).
3. ``/etc/lsb-release``, ``/etc/redhat-release``, ``/etc/arch-release``,
   ``/etc/alpine-release``  — legacy fallbacks for older systems.

All detection is read-only, uses no network, and runs in < 5 ms.  Results are
cached after the first call so repeated access is free.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Package manager detection ─────────────────────────────────────────────────

# Ordered list of (executable, package_manager_name) pairs.
# Placed in rough order of specificity so niche managers are found before
# generic ones that may also be installed alongside them.
_PKG_MANAGERS: list[tuple[str, str]] = [
    ("pacman", "pacman"),  # Arch, Manjaro, EndeavourOS …
    ("paru", "paru"),  # Arch AUR helper (wraps pacman)
    ("yay", "yay"),  # Arch AUR helper (wraps pacman)
    ("dnf", "dnf"),  # Fedora 22+, RHEL 8+, CentOS Stream
    ("dnf5", "dnf5"),  # Fedora 41+
    ("yum", "yum"),  # RHEL/CentOS 7 and older
    ("zypper", "zypper"),  # openSUSE, SLES
    ("apt", "apt"),  # Debian, Ubuntu, Mint, Pop!_OS …
    ("apt-get", "apt-get"),  # older Debian/Ubuntu scripts
    ("apk", "apk"),  # Alpine Linux
    ("emerge", "emerge"),  # Gentoo, Calculate Linux
    ("xbps-install", "xbps"),  # Void Linux
    ("nix-env", "nix"),  # NixOS / Nix on other distros
    ("guix", "guix"),  # GNU Guix System
    ("eopkg", "eopkg"),  # Solus
    ("pkg", "pkg"),  # FreeBSD (non-Linux but handled gracefully)
]

# Map distro ID (from os-release) → canonical package manager name when the
# executable alone isn't enough to distinguish (e.g. ID=ubuntu → apt).
_ID_TO_PKG: dict[str, str] = {
    "ubuntu": "apt",
    "debian": "apt",
    "linuxmint": "apt",
    "pop": "apt",
    "elementary": "apt",
    "kali": "apt",
    "raspbian": "apt",
    "fedora": "dnf",
    "rhel": "dnf",
    "centos": "dnf",
    "almalinux": "dnf",
    "rocky": "dnf",
    "ol": "dnf",  # Oracle Linux
    "opensuse-leap": "zypper",
    "opensuse-tumbleweed": "zypper",
    "sles": "zypper",
    "arch": "pacman",
    "manjaro": "pacman",
    "endeavouros": "pacman",
    "garuda": "pacman",
    "artix": "pacman",
    "alpine": "apk",
    "gentoo": "emerge",
    "void": "xbps",
    "nixos": "nix",
    "guix": "guix",
    "solus": "eopkg",
}

# Map package manager → human-readable install command template
_INSTALL_CMD: dict[str, str] = {
    "apt": "sudo apt install {package}",
    "apt-get": "sudo apt-get install {package}",
    "dnf": "sudo dnf install {package}",
    "dnf5": "sudo dnf5 install {package}",
    "yum": "sudo yum install {package}",
    "zypper": "sudo zypper install {package}",
    "pacman": "sudo pacman -S {package}",
    "paru": "paru -S {package}",
    "yay": "yay -S {package}",
    "apk": "sudo apk add {package}",
    "emerge": "sudo emerge {package}",
    "xbps": "sudo xbps-install {package}",
    "nix": "nix-env -iA nixpkgs.{package}",
    "guix": "guix install {package}",
    "eopkg": "sudo eopkg install {package}",
    "pkg": "sudo pkg install {package}",
}

# ── Init system detection ─────────────────────────────────────────────────────


def _detect_init() -> str:
    """Return the init system name: 'systemd', 'openrc', 'runit', 'sysv', or 'unknown'."""
    # systemd: PID 1 is /lib/systemd/systemd or similar
    try:
        exe = Path("/proc/1/exe").resolve()
        name = exe.name.lower()
        if "systemd" in name:
            return "systemd"
        if "runit" in name:
            return "runit"
        if "openrc" in name:
            return "openrc"
        if "init" in name:
            # Could be sysv or busybox
            return "sysv"
    except (OSError, PermissionError):
        pass

    # Fallback: check for well-known paths
    if Path("/run/systemd/system").exists():
        return "systemd"
    if Path("/run/openrc").exists():
        return "openrc"
    if shutil.which("runit"):
        return "runit"
    return "unknown"


# ── Desktop environment detection ─────────────────────────────────────────────


def _detect_desktop() -> str:
    """Return the desktop environment name or 'none' if running headless."""
    de = (
        os.environ.get("XDG_CURRENT_DESKTOP", "")
        or os.environ.get("DESKTOP_SESSION", "")
        or os.environ.get("GDMSESSION", "")
    ).lower()
    if de:
        return de
    # Headless / TTY
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return "none"
    return "unknown"


# ── OSInfo dataclass ──────────────────────────────────────────────────────────


@dataclass
class OSInfo:
    """Detected operating-system information.

    All fields are strings so they can be safely embedded in prompts.
    Unknown values are represented as empty strings.
    """

    # Distro identity
    id: str = ""
    """Machine-readable distro ID, e.g. ``ubuntu``, ``fedora``, ``arch``."""

    name: str = ""
    """Human-friendly distro name, e.g. ``Ubuntu``, ``Fedora Linux``."""

    pretty_name: str = ""
    """Full name + version, e.g. ``Ubuntu 24.04.4 LTS (Noble Numbat)``."""

    version: str = ""
    """Version string, e.g. ``24.04``, ``39``, ``rolling``."""

    codename: str = ""
    """Release codename, e.g. ``noble``, ``bookworm`` (empty if not set)."""

    id_like: str = ""
    """Space-separated parent distro IDs, e.g. ``debian`` or ``rhel fedora``."""

    # Package management
    package_manager: str = ""
    """Primary package manager: ``apt``, ``dnf``, ``pacman``, etc."""

    install_command: str = ""
    """Template install command, e.g. ``sudo apt install {package}``."""

    # System environment
    architecture: str = ""
    """CPU architecture, e.g. ``x86_64``, ``aarch64``."""

    kernel: str = ""
    """Kernel version string, e.g. ``6.8.0-57-generic``."""

    init_system: str = ""
    """Init system: ``systemd``, ``openrc``, ``runit``, ``sysv``, or ``unknown``."""

    desktop: str = ""
    """Current desktop environment or ``none`` (headless)."""

    hostname: str = ""
    """Machine hostname."""

    extra: dict = field(default_factory=dict)
    """Any additional keys from ``/etc/os-release`` not captured above."""

    # ── Formatted output ──────────────────────────────────────────────────────

    def to_system_prompt_block(self) -> str:
        """Return a concise block suitable for injection into the system prompt.

        The block tells the AI exactly which distro, version, and package
        manager are active so every command suggestion is accurate.
        """
        lines = ["## System information"]
        if self.pretty_name:
            lines.append(f"- Distribution: {self.pretty_name}")
        elif self.name:
            lines.append(f"- Distribution: {self.name} {self.version}".strip())
        if self.codename:
            lines.append(f"- Release codename: {self.codename}")
        if self.package_manager:
            lines.append(f"- Package manager: {self.package_manager}")
            if self.install_command:
                lines.append(f"- Install command: {self.install_command}")
        if self.architecture:
            lines.append(f"- Architecture: {self.architecture}")
        if self.kernel:
            lines.append(f"- Kernel: {self.kernel}")
        if self.init_system and self.init_system != "unknown":
            lines.append(f"- Init system: {self.init_system}")
        if self.desktop and self.desktop != "unknown":
            lines.append(f"- Desktop environment: {self.desktop}")
        lines.append(
            "\nAlways use the correct package manager and command syntax "
            "for this specific distribution when suggesting commands."
        )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "pretty_name": self.pretty_name,
            "version": self.version,
            "codename": self.codename,
            "id_like": self.id_like,
            "package_manager": self.package_manager,
            "install_command": self.install_command,
            "architecture": self.architecture,
            "kernel": self.kernel,
            "init_system": self.init_system,
            "desktop": self.desktop,
            "hostname": self.hostname,
        }

    def __str__(self) -> str:
        return self.pretty_name or self.name or self.id or "Unknown Linux"


# ── Detection logic ───────────────────────────────────────────────────────────


def _read_os_release() -> dict[str, str]:
    """Parse /etc/os-release and return a dict of key→value pairs."""
    # Prefer the stdlib helper (Python 3.10+)
    try:
        return platform.freedesktop_os_release()
    except (AttributeError, OSError):
        pass

    # Manual parse as fallback
    result: dict[str, str] = {}
    for candidate in ("/etc/os-release", "/usr/lib/os-release"):
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            for line in path.read_text(errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                # Strip surrounding quotes
                val = val.strip().strip('"').strip("'")
                result[key] = val
            if result:
                return result
        except OSError:
            continue
    return result


def _read_legacy_release() -> dict[str, str]:
    """Try legacy distro-specific release files when os-release is absent."""
    checks: list[tuple[str, str, str]] = [
        # (file, id, name_template)
        ("/etc/arch-release", "arch", "Arch Linux"),
        ("/etc/alpine-release", "alpine", "Alpine Linux"),
        ("/etc/gentoo-release", "gentoo", "Gentoo Linux"),
        ("/etc/void-release", "void", "Void Linux"),
    ]
    for path_str, distro_id, distro_name in checks:
        if Path(path_str).exists():
            version = Path(path_str).read_text(errors="replace").strip()
            return {"ID": distro_id, "NAME": distro_name, "VERSION_ID": version}

    # Red Hat / CentOS style
    rh = Path("/etc/redhat-release")
    if rh.exists():
        text = rh.read_text(errors="replace").strip()
        m = re.search(r"release\s+([\d.]+)", text, re.IGNORECASE)
        version = m.group(1) if m else ""
        distro_id = "rhel"
        if "centos" in text.lower():
            distro_id = "centos"
        elif "fedora" in text.lower():
            distro_id = "fedora"
        return {"ID": distro_id, "NAME": text, "VERSION_ID": version}

    # Debian legacy
    deb = Path("/etc/debian_version")
    if deb.exists():
        version = deb.read_text(errors="replace").strip()
        return {"ID": "debian", "NAME": "Debian GNU/Linux", "VERSION_ID": version}

    return {}


def _detect_package_manager(distro_id: str, id_like: str) -> str:
    """Return the best package manager name for the detected distro."""
    # 1. Look up by exact distro ID
    pm = _ID_TO_PKG.get(distro_id.lower(), "")
    if pm:
        return pm

    # 2. Try each id_like parent
    for parent in id_like.lower().split():
        pm = _ID_TO_PKG.get(parent, "")
        if pm:
            return pm

    # 3. Fall back to whichever executable is present on PATH
    for exe, name in _PKG_MANAGERS:
        if shutil.which(exe):
            return name

    return ""


@lru_cache(maxsize=1)
def detect() -> OSInfo:
    """Detect the current OS and return an :class:`OSInfo` instance.

    Results are cached after the first call (``lru_cache``) so subsequent
    accesses are free.  Call :func:`detect.cache_clear` in tests to reset.
    """
    raw = _read_os_release()
    if not raw:
        raw = _read_legacy_release()

    distro_id = raw.get("ID", "").lower()
    name = raw.get("NAME", "")
    pretty_name = raw.get("PRETTY_NAME", "")
    version = raw.get("VERSION_ID", raw.get("VERSION", ""))
    codename = raw.get("VERSION_CODENAME", raw.get("UBUNTU_CODENAME", ""))
    id_like = raw.get("ID_LIKE", "")

    # Strip keys already captured from the "extra" bucket
    _known = {
        "ID",
        "NAME",
        "PRETTY_NAME",
        "VERSION_ID",
        "VERSION",
        "VERSION_CODENAME",
        "UBUNTU_CODENAME",
        "ID_LIKE",
        "HOME_URL",
        "SUPPORT_URL",
        "BUG_REPORT_URL",
        "PRIVACY_POLICY_URL",
        "LOGO",
    }
    extra = {k: v for k, v in raw.items() if k not in _known}

    pm = _detect_package_manager(distro_id, id_like)
    install_cmd = _INSTALL_CMD.get(pm, "")

    info = OSInfo(
        id=distro_id,
        name=name,
        pretty_name=pretty_name,
        version=version,
        codename=codename,
        id_like=id_like,
        package_manager=pm,
        install_command=install_cmd,
        architecture=platform.machine(),
        kernel=platform.release(),
        init_system=_detect_init(),
        desktop=_detect_desktop(),
        hostname=platform.node(),
        extra=extra,
    )

    logger.debug("Detected OS: %s", info)
    return info
