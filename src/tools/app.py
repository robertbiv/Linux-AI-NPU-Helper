# SPDX-License-Identifier: GPL-3.0-or-later
"""Application tool — open, search, and install apps.

Actions
-------
``open``
    Launch an installed application by name.  Tries (in order):
    ``gtk-launch`` → desktop file ``Exec=`` field → plain binary exec.

``search``
    Search for packages matching a query using the distro's package manager
    (apt, dnf, pacman, …).  Also searches local ``.desktop`` files for
    installed applications.

``install``
    Open the user's terminal pre-filled with the correct install command for
    this distro (e.g. ``sudo apt install <pkg>``).  The user must press Enter
    to confirm — the assistant never runs installs itself.

All subprocess imports are deferred to the first ``run()`` call (lazy loading).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from src.tools._base import SearchResult, ToolResult

logger = logging.getLogger(__name__)

# Standard locations for .desktop files
_DESKTOP_DIRS: list[Path] = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local" / "share" / "applications",
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
]

# Package manager search commands keyed by executable name
_PKG_SEARCH_CMDS: dict[str, list[str]] = {
    "apt":      ["apt", "search", "--names-only"],
    "apt-get":  ["apt-cache", "search"],
    "dnf":      ["dnf", "search"],
    "dnf5":     ["dnf5", "search"],
    "yum":      ["yum", "search"],
    "pacman":   ["pacman", "-Ss"],
    "zypper":   ["zypper", "search"],
    "apk":      ["apk", "search"],
    "emerge":   ["emerge", "--search"],
    "xbps-install": ["xbps-query", "-Rs"],
    "nix-env":  ["nix-env", "-qaP", "--description"],
    "eopkg":    ["eopkg", "search"],
}


_desktop_cache: list[dict[str, Any]] | None = None


def _load_desktop_cache() -> list[dict[str, Any]]:
    """Load and parse all .desktop files into a global cache."""
    global _desktop_cache
    if _desktop_cache is not None:
        return _desktop_cache

    _desktop_cache = []
    seen: set[str] = set()

    for d in _DESKTOP_DIRS:
        if not d.is_dir():
            continue
        for desktop in d.glob("*.desktop"):
            if desktop.name in seen:
                continue
            try:
                text = desktop.read_text(errors="replace")
            except OSError:
                continue

            name = _desktop_field(text, "Name") or desktop.stem
            comment = _desktop_field(text, "Comment") or ""
            exec_val = _desktop_field(text, "Exec") or ""
            no_display = _desktop_field(text, "NoDisplay", "false").lower()

            seen.add(desktop.name)
            if no_display == "true":
                continue

            _desktop_cache.append({
                "name":    name,
                "comment": comment,
                "exec":    exec_val,
                "file":    str(desktop),
                "stem":    desktop.stem,
            })
    return _desktop_cache


def _read_desktop_files(query: str) -> list[dict[str, Any]]:
    """Search installed .desktop files for *query* (name/comment match)."""
    query_lower = query.lower()
    results: list[dict[str, Any]] = []

    for hit in _load_desktop_cache():
        if query_lower in hit["name"].lower() or query_lower in hit["comment"].lower():
            results.append(hit)
    return results[:20]


def _desktop_field(text: str, key: str, default: str = "") -> str:
    """Extract a field value from a .desktop file text."""
    m = re.search(rf"^{re.escape(key)}=(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else default


def _find_pkg_manager() -> tuple[str, list[str]] | None:
    """Return (executable, search_cmd_prefix) for the first available PM."""
    import shutil  # lazy
    for exe, cmd in _PKG_SEARCH_CMDS.items():
        if shutil.which(exe):
            return exe, cmd
    return None


def _launch_app(name: str) -> tuple[bool, str]:
    """Try to open an application by name.  Returns (success, message)."""
    import shutil     # lazy
    import subprocess  # lazy

    # 1. gtk-launch (searches .desktop by desktop-id)
    if shutil.which("gtk-launch"):
        # gtk-launch wants the desktop-id (filename without .desktop)
        desktop_ids = _find_desktop_ids(name)
        for did in desktop_ids:
            try:
                r = subprocess.run(
                    ["gtk-launch", did],
                    capture_output=True, timeout=5,
                )
                if r.returncode == 0:
                    return True, f"Launched '{name}' via gtk-launch."
            except Exception:  # noqa: BLE001
                pass

    # 2. Exec= field from .desktop file
    for hit in _load_desktop_cache():
        if hit["name"].lower() != name.lower():
            continue
        exec_val = hit["exec"]
        if not exec_val:
            continue
        # Strip field codes like %U %f %F
        exec_clean = re.sub(r"%[a-zA-Z]", "", exec_val).strip()
        try:
            subprocess.Popen(
                exec_clean,
                shell=True,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True, f"Launched '{name}' via {Path(hit['file']).name}."
        except Exception as exc:  # noqa: BLE001
            logger.debug("Exec launch failed: %s", exc)

    # 3. Plain binary
    binary = shutil.which(name)
    if binary:
        try:
            subprocess.Popen(
                [binary],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True, f"Launched '{name}'."
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    return False, (
        f"Could not find application '{name}'. "
        "Try 'search' to find the correct package name."
    )


def _find_desktop_ids(name: str) -> list[str]:
    """Return .desktop IDs (stem) matching *name*."""
    ids = []
    name_lower = name.lower()
    for hit in _load_desktop_cache():
        stem_lower = hit["stem"].lower()
        if name_lower in stem_lower or stem_lower in name_lower:
            ids.append(hit["stem"])
    return ids


class AppTool:
    """Open, search, and install applications."""

    name = "app"
    description = (
        "Open installed applications, search for packages, or get the correct "
        "install command for this distro (opened in terminal for user confirmation)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["open", "search", "install"],
                "description": (
                    "open: launch an installed application. "
                    "search: search for packages by name/keyword. "
                    "install: open terminal pre-filled with the install command."
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "Application name (for open/search) or package name (for install). "
                    "Examples: 'firefox', 'vlc', 'python3-pip'."
                ),
            },
        },
        "required": ["action", "name"],
    }

    def run(self, args: dict[str, Any]):  # noqa: ANN201
        action: str = args.get("action", "").strip().lower()
        name: str = args.get("name", "").strip()

        if not name:
            return ToolResult(tool_name=self.name, error="'name' is required.")
        if action not in ("open", "search", "install"):
            return ToolResult(
                tool_name=self.name,
                error=f"Unknown action '{action}'. Use: open, search, install.",
            )

        if action == "open":
            return self._open(name, ToolResult, SearchResult)
        if action == "search":
            return self._search(name, ToolResult, SearchResult)
        return self._install(name, ToolResult, SearchResult)

    # ── open ──────────────────────────────────────────────────────────────────

    def _open(self, name: str, ToolResult, SearchResult):  # noqa: ANN001,ANN201
        success, msg = _launch_app(name)
        if success:
            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path=f"app:{name}", snippet=msg)],
            )
        return ToolResult(tool_name=self.name, error=msg)

    # ── search ────────────────────────────────────────────────────────────────

    def _search(self, query: str, ToolResult, SearchResult):  # noqa: ANN001,ANN201
        import subprocess  # lazy

        results = []

        # 1. Installed .desktop files (instant — no subprocess)
        desktop_hits = _read_desktop_files(query)
        for hit in desktop_hits:
            snippet = hit["name"]
            if hit["comment"]:
                snippet += f" — {hit['comment']}"
            results.append(SearchResult(path=hit["file"], snippet=f"[installed] {snippet}"))

        # 2. Package manager search
        pm_info = _find_pkg_manager()
        if pm_info:
            _exe, cmd = pm_info
            try:
                proc = subprocess.run(
                    cmd + [query],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()][:30]
                for line in lines:
                    results.append(SearchResult(path="pkg_manager", snippet=line))
            except subprocess.TimeoutExpired:
                results.append(SearchResult(
                    path="pkg_manager",
                    snippet="Package manager search timed out.",
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Package search error: %s", exc)

        if not results:
            return ToolResult(
                tool_name=self.name,
                error=f"No applications or packages found matching '{query}'.",
            )
        return ToolResult(tool_name=self.name, results=results)

    # ── install ───────────────────────────────────────────────────────────────

    def _install(self, package: str, ToolResult, SearchResult):  # noqa: ANN001,ANN201
        from src import terminal_launcher  # lazy

        # Build install command using os_detector
        try:
            from src.os_detector import detect
            os_info = detect()
            if os_info.install_command:
                cmd = os_info.install_command.format(package=package)
            else:
                cmd = f"sudo apt install {package}"  # safe fallback
        except Exception:  # noqa: BLE001
            cmd = f"sudo apt install {package}"

        success, msg = terminal_launcher.open_with_command(cmd)
        snippet = (
            f"Opened terminal with: {cmd}"
            if success
            else f"Could not open terminal. Run manually: {cmd}"
        )
        return ToolResult(
            tool_name=self.name,
            results=[SearchResult(path=f"pkg:{package}", snippet=snippet)],
            error="" if success else msg,
        )

    def schema_text(self) -> str:
        return (
            f"  {self.name}(action: open|search|install, name: string)"
            f" — {self.description}"
        )
