# SPDX-License-Identifier: GPL-3.0-or-later
"""Installed applications detector.

Scans .desktop files, Flatpak, Snap, system packages, and PATH binaries.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult
from src.tools._utils import run_command

logger = logging.getLogger(__name__)


def _scan_desktop(query: str = "") -> list[dict]:
    from src.tools.app import _load_desktop_cache

    q = query.lower()
    results: list[dict] = []

    for hit in _load_desktop_cache():
        if q and q not in hit["name"].lower() and q not in hit["comment"].lower():
            continue
        results.append(
            {
                "source": "desktop",
                "name": hit["name"],
                "comment": hit["comment"],
                "file": hit["file"],
            }
        )
    return results


def _scan_flatpak(query: str = "") -> list[dict]:
    out = run_command(
        ["flatpak", "list", "--app", "--columns=application,name,version"]
    )
    q = query.lower()
    results: list[dict] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        app_id = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else app_id
        version = parts[2].strip() if len(parts) > 2 else ""
        if q and q not in name.lower() and q not in app_id.lower():
            continue
        results.append(
            {"source": "flatpak", "name": name, "id": app_id, "version": version}
        )
    return results


def _scan_snap(query: str = "") -> list[dict]:
    out = run_command(["snap", "list"])
    q = query.lower()
    results: list[dict] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        version = parts[1] if len(parts) > 1 else ""
        if q and q not in name.lower():
            continue
        results.append({"source": "snap", "name": name, "version": version})
    return results


def _scan_packages(query: str = "") -> list[dict]:
    q = query.lower()
    out = run_command(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Status}\n"])
    if out:
        results: list[dict] = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 3 or "installed" not in parts[2]:
                continue
            if q and q not in parts[0].lower():
                continue
            results.append({"source": "deb", "name": parts[0], "version": parts[1]})
        return results
    out = run_command(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}\n"])
    results = []
    for line in out.splitlines():
        parts = line.split("\t")
        if q and q not in parts[0].lower():
            continue
        results.append(
            {
                "source": "rpm",
                "name": parts[0],
                "version": parts[1] if len(parts) > 1 else "",
            }
        )
    return results


def _scan_path(query: str = "") -> list[dict]:
    q = query.lower()
    results: list[dict] = []
    seen: set[str] = set()
    for d in os.environ.get("PATH", "").split(":"):
        p = Path(d)
        if not p.is_dir():
            continue
        try:
            with os.scandir(p) as it:
                for entry in it:
                    if entry.name in seen:
                        continue
                    if q and q not in entry.name.lower():
                        continue
                    if entry.is_file() and os.access(entry.path, os.X_OK):
                        seen.add(entry.name)
                        results.append(
                            {"source": "path", "name": entry.name, "path": entry.path}
                        )
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
                "items": {
                    "type": "string",
                    "enum": ["desktop", "flatpak", "snap", "packages", "path", "all"],
                },
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
        if "desktop" in sources:
            all_hits.extend(_scan_desktop(query))
        if "flatpak" in sources:
            all_hits.extend(_scan_flatpak(query))
        if "snap" in sources:
            all_hits.extend(_scan_snap(query))
        if "packages" in sources:
            all_hits.extend(_scan_packages(query))
        if "path" in sources:
            all_hits.extend(_scan_path(query))

        if not all_hits:
            msg = (
                f"No apps found matching '{query}'."
                if query
                else "No installed apps found."
            )
            return ToolResult(tool_name=self.name, error=msg)

        results = [
            SearchResult(
                path=r.get("file") or r.get("path") or r.get("source", ""),
                snippet=(
                    f"[{r['source']}] {r['name']}"
                    + (f" {r.get('version', '')}" if r.get("version") else "")
                    + (f" — {r['comment']}" if r.get("comment") else "")
                ),
            )
            for r in all_hits[:100]
        ]
        return ToolResult(
            tool_name=self.name, results=results, truncated=len(all_hits) > 100
        )
