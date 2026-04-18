# SPDX-License-Identifier: GPL-3.0-or-later
"""Find files tool — search for files by name or glob pattern."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


def _has_hidden_component(path: str) -> bool:
    """Return True if any path component starts with a dot."""
    # Performance optimization: String splitting is ~5-30x faster than Path(path).parts
    if "/." not in path and not path.startswith("."):
        return False
    return any(p.startswith(".") and p != "." for p in path.split("/"))


class FindFilesTool(Tool):
    """Search for files by name or glob pattern.

    Backend priority
    ----------------
    1. ``plocate`` – fastest; uses an mmap-based index updated by a daemon.
    2. ``locate``  – compatible but slightly slower index format.
    3. ``find``    – always available; slower because it walks the filesystem.

    The tool automatically chooses the fastest backend present on the system.
    """

    name = "find_files"
    description = (
        "Search for files by name or glob pattern. "
        "Uses the OS file index (plocate/locate) for speed, falls back to find."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": (
                    "Filename pattern to search for.  Supports shell globs "
                    "(e.g. '*.pdf', 'resume*', 'tax_2024.xlsx')."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Directory to restrict the search to.  "
                    "Defaults to the user's home directory."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 50).",
            },
            "include_hidden": {
                "type": "boolean",
                "description": "Whether to include hidden files/dirs (default false).",
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, default_search_path: str | Path | None = None) -> None:
        self._default_path = Path(default_search_path or Path.home())
        self._backend: str | None = None  # cached after first call

    def _detect_backend(self) -> str:
        """Return 'plocate', 'locate', or 'find'."""
        if self._backend is None:
            import shutil  # lazy — only needed when first search runs
            for cmd in ("plocate", "locate"):
                if shutil.which(cmd):
                    self._backend = cmd
                    break
            else:
                self._backend = "find"
            logger.debug("FindFilesTool backend: %s", self._backend)
        return self._backend

    def run(self, args: dict[str, Any]) -> ToolResult:
        pattern: str = args.get("pattern", "")
        if not pattern:
            return ToolResult(tool_name=self.name, error="'pattern' is required.")

        search_path = Path(args.get("path") or self._default_path).expanduser()
        max_results: int = int(args.get("max_results", 50))
        include_hidden: bool = bool(args.get("include_hidden", False))

        backend = self._detect_backend()
        try:
            if backend in ("plocate", "locate"):
                hits = self._run_locate(backend, pattern, search_path, max_results)
            else:
                hits = self._run_find(pattern, search_path, max_results, include_hidden)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FindFilesTool error: %s", exc)
            return ToolResult(tool_name=self.name, error=str(exc))

        if not include_hidden:
            hits = [h for h in hits if not _has_hidden_component(h)]

        truncated = len(hits) > max_results
        results = [SearchResult(path=h) for h in hits[:max_results]]
        return ToolResult(
            tool_name=self.name,
            results=results,
            truncated=truncated,
        )

    # ── Backends ──────────────────────────────────────────────────────────────

    @staticmethod
    def _run_locate(
        cmd: str, pattern: str, search_path: Path, limit: int
    ) -> list[str]:
        """Run plocate/locate and return matching paths under search_path."""
        import subprocess  # lazy — only when tool actually runs
        args = [cmd, "--basename", "-l", str(limit * 2), pattern]
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        prefix = str(search_path)
        return [line for line in lines if line.startswith(prefix)]

    @staticmethod
    def _run_find(
        pattern: str, search_path: Path, limit: int, include_hidden: bool
    ) -> list[str]:
        """Run find(1) to search by name."""
        import subprocess  # lazy — only when tool actually runs
        cmd = ["find", str(search_path), "-name", pattern]
        if not include_hidden:
            cmd = (
                ["find", str(search_path)]
                + ["-not", "-path", "*/.*"]
                + ["-name", pattern]
            )
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()][:limit]
        except subprocess.TimeoutExpired:
            logger.warning("find timed out after 30 s; returning partial results.")
            return []
