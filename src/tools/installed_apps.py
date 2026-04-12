"""Installed applications detector.

Scans .desktop files, Flatpak, Snap, system packages, and PATH binaries.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)

_DESKTOP_DIRS = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local" / "share" / "applications",
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
    Path("/var/lib/snapd/desktop/applications"),
]


def _run(cmd: list[str], timeout: int = 15) -> str:
    import shutil
    import subprocess
    if not shutil.which(cmd[0]):
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _desktop_field(text: str, key: str, default: str = "") -> str:
    m = re.search(rf"^{re.escape(key)}=(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else default


def _scan_desktop(query: str = "") -> list[dict]:
    q = query.lower()
    results: list[dict] = []
    seen: set[str] = set()
    for d in _DESKTOP_DIRS:
        if not d.is_dir():
            continue
        for f in d.glob("*.desktop"):
            if f.name in seen:
                continue
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            name = _desktop_field(text, "Name") or f.stem
            comment = _desktop_field(text, "Comment")
            if _desktop_field(text, "NoDisplay", "false").lower() == "true":
                continue
            if q and q not in name.lower() and q not in comment.lower():
                continue
            seen.add(f.name)
            results.append({"source": "desktop", "name": name,
                            "comment": comment, "file": str(f)})
    return results


def _scan_flatpak(query: str = "") -> list[dict]:
    out = _run(["flatpak", "list", "--app",
                "--columns=application,name,version"])
    results: list[dict] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        app_id = parts[0].strip()
        name   = parts[1].strip() if len(parts) > 1 else app_id
        version = parts[2].strip() if len(parts) > 2 else ""
        if query and query.lower() not in name.lower() and query.lower() not in app_id.lower():
            continue
        results.append({"source": "flatpak", "name": name,
                        "id": app_id, "version": version})
    return results


def _scan_snap(query: str = "") -> list[dict]:
    out = _run(["snap", "list"])
    results: list[dict] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        version = parts[1] if len(parts) > 1 else ""
        if query and query.lower() not in name.lower():
            continue
        results.append({"source": "snap", "name": name, "version": version})
    return results


def _scan_packages(query: str = "") -> list[dict]:
    out = _run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Status}\n"])
    if out:
        results: list[dict] = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 3 or "installed" not in parts[2]:
                continue
            if query and query.lower() not in parts[0].lower():
                continue
            results.append({"source": "deb", "name": parts[0], "version": parts[1]})
        return results
    out = _run(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}\n"])
    results = []
    for line in out.splitlines():
        parts = line.split("\t")
        if query and query.lower() not in parts[0].lower():
            continue
        results.append({"source": "rpm", "name": parts[0],
                        "version": parts[1] if len(parts) > 1 else ""})
    return results


def _scan_path(query: str = "") -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    for d in os.environ.get("PATH", "").split(":"):
        p = Path(d)
        if not p.is_dir():
            continue
        try:
            for entry in p.iterdir():
                if entry.name in seen:
                    continue
                if query and query.lower() not in entry.name.lower():
                    continue
                if entry.is_file() and os.access(entry, os.X_OK):
                    seen.add(entry.name)
                    results.append({"source": "path", "name": entry.name,
                                    "path": str(entry)})
        except PermissionError:
            continue
    return results[:200]


class InstalledAppsTool(Tool):
    """List or search installed applications and CLI tools."""

    name = "installed_apps"
    description = (
        "List or search installed applications (GUI apps, Flatpak, Snap, "
        "system packages, CLI tools in PATH). Use to check if a program is "
        "installed before suggesting it."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term. Empty = list all (may be large).",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string",
                          "enum": ["desktop", "flatpak", "snap",
                                   "packages", "path", "all"]},
                "description": "Sources to scan. Default: ['desktop','flatpak','snap'].",
            },
        },
        "required": [],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        query: str = args.get("query", "").strip()
        sources: list[str] = args.get("sources", ["desktop", "flatpak", "snap"])
        if "all" in sources:
            sources = ["desktop", "flatpak", "snap", "packages", "path"]

        all_hits: list[dict] = []
        if "desktop"  in sources: all_hits.extend(_scan_desktop(query))
        if "flatpak"  in sources: all_hits.extend(_scan_flatpak(query))
        if "snap"     in sources: all_hits.extend(_scan_snap(query))
        if "packages" in sources: all_hits.extend(_scan_packages(query))
        if "path"     in sources: all_hits.extend(_scan_path(query))

        if not all_hits:
            msg = (f"No apps found matching '{query}'." if query
                   else "No installed apps found.")
            return ToolResult(tool_name=self.name, error=msg)

        results = [
            SearchResult(
                path=r.get("file") or r.get("path") or r.get("source", ""),
                snippet=(
                    f"[{r['source']}] {r['name']}"
                    + (f" {r.get('version','')}" if r.get("version") else "")
                    + (f" — {r['comment']}" if r.get("comment") else "")
                ),
            )
            for r in all_hits[:100]
        ]
        return ToolResult(tool_name=self.name, results=results,
                          truncated=len(all_hits) > 100)
