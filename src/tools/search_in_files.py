# SPDX-License-Identifier: GPL-3.0-or-later
"""Search in files tool — find text patterns inside files."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)

# grep/rg output line: /path/to/file:42:matching text
_GREP_LINE_RE = re.compile(r"^(.+?):(\d+):(.*)$", re.MULTILINE)


def _parse_grep_output(text: str, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    # Performance optimization: Use finditer with MULTILINE instead of splitlines
    # to avoid creating millions of temporary string objects.
    for m in _GREP_LINE_RE.finditer(text):
        results.append(SearchResult(
            path=m.group(1),
            line_number=int(m.group(2)),
            snippet=m.group(3).strip(),
        ))
        if len(results) >= limit:
            break
    return results


class SearchInFilesTool(Tool):
    """Search for text inside files.

    Backend priority
    ----------------
    1. ``rg`` (ripgrep) – fastest; respects ``.gitignore``; written in Rust.
    2. ``grep -r``      – always available; slower on large trees.
    """

    name = "search_in_files"
    description = (
        "Search for a text pattern inside files. "
        "Uses ripgrep for speed, falls back to grep. "
        "Great for finding a specific piece of content across many files."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text or regex pattern to search for inside files.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to home directory.",
            },
            "file_pattern": {
                "type": "string",
                "description": (
                    "Optional glob to restrict which files are searched "
                    "(e.g. '*.py', '*.md', '*.txt')."
                ),
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether the search is case-sensitive (default false).",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matches to return (default 30).",
            },
        },
        "required": ["query"],
    }

    def __init__(self, default_search_path: str | Path | None = None,
                 blocked_paths: list[str] | None = None) -> None:
        self._default_path = Path(default_search_path or Path.home())
        self._backend: str | None = None
        # Expand and resolve blocked paths at init time so the check is fast
        self._blocked: list[Path] = [
            Path(p).expanduser().resolve()
            for p in (blocked_paths or [])
        ]

    def _is_blocked(self, path: Path) -> bool:
        """Return True if *path* is inside a blocked directory."""
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return any(
            resolved == b or b in resolved.parents
            for b in self._blocked
        )

    def _detect_backend(self) -> str:
        if self._backend is None:
            import shutil  # lazy — only when tool actually runs
            self._backend = "rg" if shutil.which("rg") else "grep"
            logger.debug("SearchInFilesTool backend: %s", self._backend)
        return self._backend

    def run(self, args: dict[str, Any]) -> ToolResult:
        query: str = args.get("query", "")
        if not query:
            return ToolResult(tool_name=self.name, error="'query' is required.")

        search_path = Path(args.get("path") or self._default_path).expanduser()

        # Security: refuse to search inside blocked paths
        if self._is_blocked(search_path):
            logger.warning(
                "SearchInFilesTool: search path %s is blocked.", search_path
            )
            return ToolResult(
                tool_name=self.name,
                error=f"Searching in {search_path} is not permitted for security reasons.",
            )

        file_pattern: str | None = args.get("file_pattern")
        case_sensitive: bool = bool(args.get("case_sensitive", False))
        max_results: int = int(args.get("max_results", 30))

        backend = self._detect_backend()
        try:
            if backend == "rg":
                hits = self._run_rg(
                    query, search_path, file_pattern, case_sensitive, max_results
                )
            else:
                hits = self._run_grep(
                    query, search_path, file_pattern, case_sensitive, max_results
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SearchInFilesTool error: %s", exc)
            return ToolResult(tool_name=self.name, error=str(exc))

        # Filter out any results that landed inside a blocked path
        hits = [h for h in hits if not self._is_blocked(Path(h.path))]

        truncated = len(hits) > max_results
        return ToolResult(
            tool_name=self.name,
            results=hits[:max_results],
            truncated=truncated,
        )

    # ── Backends ──────────────────────────────────────────────────────────────

    @staticmethod
    def _run_rg(
        query: str,
        search_path: Path,
        file_pattern: str | None,
        case_sensitive: bool,
        limit: int,
    ) -> list[SearchResult]:
        import subprocess  # lazy
        cmd = ["rg", "--line-number", "--no-heading", "--max-count", "1",
               "--max-filesize", "10M"]
        if not case_sensitive:
            cmd.append("--ignore-case")
        if file_pattern:
            cmd += ["--glob", file_pattern]
        cmd += ["--", query, str(search_path)]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20
        )
        return _parse_grep_output(proc.stdout, limit)

    @staticmethod
    def _run_grep(
        query: str,
        search_path: Path,
        file_pattern: str | None,
        case_sensitive: bool,
        limit: int,
    ) -> list[SearchResult]:
        import subprocess  # lazy
        cmd = ["grep", "-r", "-n", "--binary-files=without-match",
               "--max-count=1"]
        if not case_sensitive:
            cmd.append("-i")
        if file_pattern:
            cmd += ["--include", file_pattern]
        cmd += ["--", query, str(search_path)]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            logger.warning("grep timed out; returning partial results.")
            return []
        return _parse_grep_output(proc.stdout, limit)
