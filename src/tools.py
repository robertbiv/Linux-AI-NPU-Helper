"""Built-in tools for the Linux AI NPU Helper.

Each tool is a self-contained unit that can be:
- Called directly from the UI (e.g. the user types "find my resume")
- Called by the AI when it decides a search is needed, via the tool-call
  protocol parsed by :mod:`tool_runner`.

Built-in tools
--------------
``find_files``
    Search for files by name / glob pattern.  Uses ``plocate`` or ``locate``
    (pre-built OS index, very fast) and falls back to ``find`` when those
    are unavailable.

``search_in_files``
    Search for text inside files.  Uses ``ripgrep`` (``rg``) for speed and
    falls back to ``grep -r``.  Blocked paths (e.g. ``~/.ssh``) are never
    read.

``web_search``
    Opens the user's **default browser** with their preferred search engine.
    The assistant itself makes **zero HTTP requests** to search engines —
    it only calls ``xdg-open`` with a URL.  All data stays on-device.

``man_reader`` (``read_man_page``)
    Read the Linux manual page for any command.  Runs ``man`` locally with
    plain-text output, strips bold/underline formatting, and can extract
    specific named sections (SYNOPSIS, OPTIONS, EXAMPLES, …) so the AI gets
    just what it needs to craft an accurate command without flooding the
    context window.  All data stays on-device — no network access.

Privacy & security
------------------
- ``SearchInFilesTool`` refuses to read paths that match the configured
  ``blocked_paths`` list (``~/.ssh``, ``~/.gnupg``, ``/etc/shadow``, etc.).
- ``WebSearchTool`` never contacts any server itself; it delegates entirely
  to the user's browser.
- No tool sends any data off-device.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class SearchResult:
    """A single hit returned by a tool."""

    path: str
    """Absolute (or relative) path of the matching file."""

    line_number: int | None = None
    """Line number of the match inside the file (content searches only)."""

    snippet: str = ""
    """Matching text excerpt (content searches only)."""

    score: float = 0.0
    """Optional relevance score (higher = more relevant)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line_number": self.line_number,
            "snippet": self.snippet,
            "score": self.score,
        }

    def __str__(self) -> str:
        if self.line_number is not None:
            return f"{self.path}:{self.line_number}: {self.snippet}"
        return self.path


@dataclass
class ToolResult:
    """Aggregated output from a single tool invocation."""

    tool_name: str
    results: list[SearchResult] = field(default_factory=list)
    error: str = ""
    truncated: bool = False
    """True when the result list was clipped to ``max_results``."""

    def to_text(self, max_display: int = 20) -> str:
        """Format the result as a human-readable string for the AI/UI."""
        if self.error:
            return f"[{self.tool_name}] Error: {self.error}"
        if not self.results:
            return f"[{self.tool_name}] No results found."
        lines = [f"[{self.tool_name}] {len(self.results)} result(s)"
                 + (" (truncated)" if self.truncated else "") + ":"]
        for r in self.results[:max_display]:
            lines.append(f"  {r}")
        if len(self.results) > max_display:
            lines.append(f"  … and {len(self.results) - max_display} more")
        return "\n".join(lines)


# ── Base Tool ─────────────────────────────────────────────────────────────────


class Tool:
    """Abstract base for all built-in tools."""

    #: Short identifier used in tool-call markers: ``[TOOL: name {...}]``
    name: str = ""

    #: One-line description shown to the AI in the system prompt.
    description: str = ""

    #: JSON schema of the arguments this tool accepts.
    parameters_schema: dict[str, Any] = {}

    def run(self, args: dict[str, Any]) -> ToolResult:  # noqa: ANN001
        raise NotImplementedError

    def schema_text(self) -> str:
        """Return a compact description for inclusion in the system prompt."""
        params = ", ".join(
            f"{k}: {v.get('type', 'string')}"
            for k, v in self.parameters_schema.get("properties", {}).items()
        )
        return f"  {self.name}({params}) — {self.description}"


# ── FindFilesTool ─────────────────────────────────────────────────────────────


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
        args = [cmd, "--basename", "-l", str(limit * 2), pattern]
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
        # Filter to paths that start with the requested search_path
        prefix = str(search_path)
        return [l for l in lines if l.startswith(prefix)]

    @staticmethod
    def _run_find(
        pattern: str, search_path: Path, limit: int, include_hidden: bool
    ) -> list[str]:
        """Run find(1) to search by name."""
        cmd = ["find", str(search_path), "-name", pattern]
        if not include_hidden:
            # Skip directories starting with '.'
            cmd = (
                ["find", str(search_path)]
                + ["-not", "-path", "*/.*"]
                + ["-name", pattern]
            )
        # Limit via head to avoid blocking for too long on huge trees
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return [l.strip() for l in proc.stdout.splitlines() if l.strip()][:limit]
        except subprocess.TimeoutExpired:
            logger.warning("find timed out after 30 s; returning partial results.")
            return []


# ── SearchInFilesTool ─────────────────────────────────────────────────────────


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


# ── Helpers ───────────────────────────────────────────────────────────────────

# grep/rg output line: /path/to/file:42:matching text
_GREP_LINE_RE = re.compile(r"^(.+?):(\d+):(.*)$")


def _parse_grep_output(text: str, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for line in text.splitlines():
        m = _GREP_LINE_RE.match(line)
        if m:
            results.append(SearchResult(
                path=m.group(1),
                line_number=int(m.group(2)),
                snippet=m.group(3).strip(),
            ))
        if len(results) >= limit:
            break
    return results


def _has_hidden_component(path: str) -> bool:
    """Return True if any path component starts with a dot."""
    return any(part.startswith(".") for part in Path(path).parts)


# ── WebSearchTool ─────────────────────────────────────────────────────────────

# Built-in engine URL templates (query placeholder: {query})
_DEFAULT_ENGINES: dict[str, str] = {
    "duckduckgo": "https://duckduckgo.com/?q={query}",
    "startpage":  "https://www.startpage.com/search?q={query}",
    "brave":      "https://search.brave.com/search?q={query}",
    "ecosia":     "https://www.ecosia.org/search?q={query}",
    "google":     "https://www.google.com/search?q={query}",
    "bing":       "https://www.bing.com/search?q={query}",
}


class WebSearchTool(Tool):
    """Open the user's default browser to search the web.

    Privacy model
    -------------
    This tool **never makes any HTTP request itself**.  It builds a search URL
    and hands it to ``xdg-open``, which opens the URL in whatever browser the
    user has set as their default.  The assistant has no visibility into what
    the browser does after that point.

    The tool is useful for:
    - Letting the AI suggest search queries based on conversation context.
    - Giving the user a one-click way to look something up without the
      assistant having to access the internet itself.
    """

    name = "web_search"
    description = (
        "Open the user's default browser with a search query. "
        "The assistant does NOT access the internet — it only opens a browser tab."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up.",
            },
            "engine": {
                "type": "string",
                "description": (
                    "Search engine to use. One of: "
                    + ", ".join(_DEFAULT_ENGINES)
                    + ". Defaults to the configured engine."
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        default_engine: str = "duckduckgo",
        engines: dict[str, str] | None = None,
    ) -> None:
        self._default_engine = default_engine
        # Merge user-defined engines over the built-in set
        self._engines: dict[str, str] = {**_DEFAULT_ENGINES, **(engines or {})}

    def run(self, args: dict[str, Any]) -> ToolResult:
        query: str = args.get("query", "").strip()
        if not query:
            return ToolResult(tool_name=self.name, error="'query' is required.")

        engine_key = args.get("engine", self._default_engine).lower()
        template = self._engines.get(engine_key)
        if template is None:
            available = ", ".join(self._engines)
            return ToolResult(
                tool_name=self.name,
                error=f"Unknown engine {engine_key!r}. Available: {available}",
            )

        encoded = urllib.parse.quote_plus(query)
        url = template.format(query=encoded)

        logger.info("WebSearchTool: opening %s with query %r", engine_key, query)
        try:
            # Non-blocking: spawn xdg-open and return immediately.
            # The subprocess is fully detached — we do not wait for it.
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except FileNotFoundError:
            return ToolResult(
                tool_name=self.name,
                error=(
                    "xdg-open not found. Install xdg-utils or open your browser "
                    f"manually and search for: {query}"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("WebSearchTool error: %s", exc)
            return ToolResult(tool_name=self.name, error=str(exc))

        return ToolResult(
            tool_name=self.name,
            results=[
                SearchResult(
                    path=url,
                    snippet=f'Opened {engine_key} search for "{query}" in your browser.',
                )
            ],
        )





# ── ManPageTool ───────────────────────────────────────────────────────────────

# ANSI escape sequences (colour codes, cursor moves, etc.)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# Backspace-based bold/underline: "c\bc" → "c",  "_\bc" → "c"
_BACKSPACE_RE = re.compile(r".\x08")
# Section headers in man pages: an all-caps word at the start of a line,
# optionally followed by more words.  Examples: "OPTIONS", "RETURN VALUE".
_SECTION_HEADER_RE = re.compile(r"^([A-Z][A-Z0-9 _-]+)$", re.MULTILINE)

# Man-page sections the AI most benefits from when crafting commands
_USEFUL_SECTIONS = ("SYNOPSIS", "OPTIONS", "DESCRIPTION", "EXAMPLES", "NOTES")

# Hard cap: no matter what the user configures, never return more than this
# many characters from a single man page to avoid context overflow.
_ABSOLUTE_MAX_CHARS = 32_000


def _strip_man_formatting(text: str) -> str:
    """Remove ANSI codes and backspace-based bold/underline from man output."""
    text = _ANSI_RE.sub("", text)
    text = _BACKSPACE_RE.sub("", text)
    return text


def _extract_sections(text: str, sections: list[str]) -> str:
    """Extract named sections from plain-text man page output.

    Each section begins at a header line (all-caps) and ends at the next
    header line.  Returns only the requested sections concatenated together.
    If *sections* is empty all text is returned.
    """
    if not sections:
        return text

    wanted = {s.upper() for s in sections}
    result_parts: list[str] = []
    current_header: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        if current_header in wanted and current_lines:
            result_parts.append(current_header)
            result_parts.extend(current_lines)

    for line in text.splitlines():
        header_match = _SECTION_HEADER_RE.match(line.rstrip())
        if header_match:
            _flush()
            current_header = header_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    _flush()
    return "\n".join(result_parts)


class ManPageTool(Tool):
    """Read the Linux manual page for a command.

    The tool runs ``man <command>`` locally with plain-text output (no pager,
    no ANSI codes), optionally extracts specific sections, and truncates the
    result to keep it within the model's context window.

    This lets the AI look up the exact flags, syntax, and examples for any
    installed command before crafting a shell instruction — ensuring accuracy
    especially across distros where option names differ.

    The tool is entirely offline: it reads man pages from the local system
    and never contacts any network resource.

    Parameters
    ----------
    max_chars:
        Maximum characters returned per call.  Defaults to 8 000, which is
        enough for SYNOPSIS + OPTIONS of most commands.
    default_sections:
        Section names to extract when the caller doesn't specify any.  Use
        ``[]`` to return the full man page (up to *max_chars*).
    """

    name = "read_man_page"
    description = (
        "Read the local manual page for a command so you can craft an accurate "
        "command with the correct flags and syntax for this system. "
        "Offline — reads from the local man database only."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The command to look up, e.g. 'find', 'tar', 'systemctl'.",
            },
            "sections": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of man-page section names to extract, e.g. "
                    "['SYNOPSIS', 'OPTIONS', 'EXAMPLES']. "
                    "Omit or pass [] to use the configured default sections."
                ),
            },
            "man_section": {
                "type": "string",
                "description": (
                    "Optional manual section number, e.g. '1' (user commands), "
                    "'5' (file formats), '8' (admin commands). "
                    "Leave empty to let man choose."
                ),
            },
        },
        "required": ["command"],
    }

    def __init__(
        self,
        max_chars: int = 8_000,
        default_sections: list[str] | None = None,
    ) -> None:
        self._max_chars = min(max_chars, _ABSOLUTE_MAX_CHARS)
        self._default_sections: list[str] = (
            default_sections
            if default_sections is not None
            else list(_USEFUL_SECTIONS)
        )

    def run(self, args: dict[str, Any]) -> ToolResult:
        command: str = args.get("command", "").strip()
        if not command:
            return ToolResult(tool_name=self.name, error="'command' is required.")

        # Basic safety: reject anything that isn't a plain command name
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", command):
            return ToolResult(
                tool_name=self.name,
                error=f"Invalid command name: {command!r}. "
                      "Only alphanumeric characters, hyphens, underscores, and dots are allowed.",
            )

        man_section: str = args.get("man_section", "").strip()
        requested_sections: list[str] = args.get("sections") or []
        extract_sections = requested_sections or self._default_sections

        # Check man is available
        if not shutil.which("man"):
            return ToolResult(
                tool_name=self.name,
                error="'man' is not installed on this system.",
            )

        # Build the man command — MANPAGER=cat gives plain text, MANWIDTH
        # limits line length to something readable in a chat context.
        cmd = ["man"]
        if man_section:
            cmd.append(man_section)
        cmd.append(command)

        env = os.environ.copy()
        env["MANPAGER"] = "cat"
        env["MANWIDTH"] = "100"
        # Disable colour from groff/man-db
        env["GROFF_NO_SGR"] = "1"
        env.pop("LESS", None)
        env.pop("MORE", None)

        logger.info("ManPageTool: reading man page for %r", command)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name=self.name,
                error=f"man page lookup for '{command}' timed out.",
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(tool_name=self.name, error=str(exc))

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            return ToolResult(
                tool_name=self.name,
                error=f"No man page found for '{command}'"
                      + (f": {stderr}" if stderr else "."),
            )

        raw = _strip_man_formatting(proc.stdout)
        text = _extract_sections(raw, extract_sections) if extract_sections else raw

        # If section extraction yielded nothing, fall back to the full page
        if not text.strip() and extract_sections:
            logger.debug(
                "ManPageTool: requested sections %s not found; returning full page.",
                extract_sections,
            )
            text = raw

        truncated = len(text) > self._max_chars
        text = text[: self._max_chars]

        if not text.strip():
            return ToolResult(
                tool_name=self.name,
                error=f"man page for '{command}' is empty.",
            )

        return ToolResult(
            tool_name=self.name,
            results=[
                SearchResult(
                    path=f"man:{command}",
                    snippet=text,
                )
            ],
            truncated=truncated,
        )

    def schema_text(self) -> str:
        return (
            f"  {self.name}(command: string, sections?: string[], "
            f"man_section?: string) — {self.description}"
        )


# ── Tool permissions ──────────────────────────────────────────────────────────


class ToolPermissions:
    """Encapsulates the allow/disallow/approval rules for tool dispatch.

    Resolution order (highest to lowest precedence):
    1. ``disallowed`` — tool is **always blocked**, no override.
    2. ``allowed``    — if non-empty, only tools in this set may run.
    3. ``requires_approval`` — tool may run, but only after the user confirms.

    Parameters
    ----------
    allowed:
        Whitelist of tool names the AI may call.  An empty set means *all*
        registered tools are allowed (subject to the disallowed list).
    disallowed:
        Blacklist of tool names that are completely blocked.  Takes precedence
        over ``allowed``.
    requires_approval:
        Tool names that need explicit user confirmation before executing.
        The approval callback receives the tool name and the argument dict and
        must return ``True`` to proceed.
    approve_callback:
        Called as ``approve_callback(tool_name, args) -> bool`` when a tool
        in ``requires_approval`` is invoked.  Defaults to a terminal prompt.
    """

    def __init__(
        self,
        allowed: list[str] | None = None,
        disallowed: list[str] | None = None,
        requires_approval: list[str] | None = None,
        approve_callback: "Callable[[str, dict], bool] | None" = None,
    ) -> None:
        self._allowed: frozenset[str] = frozenset(allowed or [])
        self._disallowed: frozenset[str] = frozenset(disallowed or [])
        self._requires_approval: frozenset[str] = frozenset(requires_approval or [])
        self._approve = approve_callback or _terminal_approve

    # ── Inspection helpers ────────────────────────────────────────────────────

    def is_disallowed(self, name: str) -> bool:
        return name in self._disallowed

    def is_allowed(self, name: str) -> bool:
        """Return True if *name* passes the whitelist check.

        If no whitelist is configured (empty set) every tool passes.
        """
        if self._allowed:
            return name in self._allowed
        return True

    def needs_approval(self, name: str) -> bool:
        return name in self._requires_approval

    # ── Gate ──────────────────────────────────────────────────────────────────

    def check(self, tool_name: str, args: dict) -> "ToolResult | None":
        """Enforce permissions for *tool_name* with *args*.

        Returns
        -------
        ToolResult | None
            A ``ToolResult`` with an error message if the tool is blocked or
            the user declines.  ``None`` means the tool **may proceed**.
        """
        if self.is_disallowed(tool_name):
            logger.info("Tool %r is disallowed by configuration.", tool_name)
            return ToolResult(
                tool_name=tool_name,
                error=f"Tool '{tool_name}' is disabled.",
            )

        if not self.is_allowed(tool_name):
            logger.info(
                "Tool %r is not in the allowed list %s.",
                tool_name,
                sorted(self._allowed),
            )
            return ToolResult(
                tool_name=tool_name,
                error=(
                    f"Tool '{tool_name}' is not permitted. "
                    f"Allowed tools: {', '.join(sorted(self._allowed)) or 'none'}."
                ),
            )

        if self.needs_approval(tool_name):
            if not self._approve(tool_name, args):
                logger.info("User declined approval for tool %r.", tool_name)
                return ToolResult(
                    tool_name=tool_name,
                    error=f"Tool '{tool_name}' was not approved by the user.",
                )

        return None  # all checks passed — proceed

    # ── Visible tools (for system prompt) ────────────────────────────────────

    def visible_names(self, all_names: list[str]) -> list[str]:
        """Return the subset of *all_names* that are advertised to the AI.

        Disallowed tools and tools outside the whitelist are hidden from the
        system prompt so the AI doesn't even try to call them.
        """
        return [
            n for n in all_names
            if not self.is_disallowed(n) and self.is_allowed(n)
        ]


def _terminal_approve(tool_name: str, args: dict) -> bool:
    """Default approval callback: asks the user on the terminal."""
    args_preview = json.dumps(args, ensure_ascii=False)
    try:
        print(f"\n⚙  The AI wants to use tool '{tool_name}':")
        print(f"   Arguments: {args_preview}\n")
        answer = input("Allow? [y/N] ").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


# ── ToolRegistry ──────────────────────────────────────────────────────────────


class ToolRegistry:
    """Registry of all available tools.

    The registry:
    - Stores tool instances by name.
    - Enforces allow / disallow / approval rules via :class:`ToolPermissions`.
    - Generates a system-prompt snippet that only advertises tools the AI is
      permitted to call.
    - Dispatches ``[TOOL: name {...}]`` call markers to the right tool.
    """

    # Pattern that the AI uses to call a tool in its response.
    # Example: [TOOL: find_files {"pattern": "*.pdf", "path": "~/Documents"}]
    _CALL_RE = re.compile(
        r"\[TOOL:\s*(\w+)\s*(\{.*?\})\]",
        re.DOTALL,
    )

    def __init__(self, permissions: ToolPermissions | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._permissions = permissions or ToolPermissions()

    def register(self, tool: Tool) -> None:
        """Add a tool to the registry."""
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    # ── System-prompt generation ──────────────────────────────────────────────

    def system_prompt_section(self) -> str:
        """Return the block of text to inject into the system prompt.

        Only advertises tools the AI is permitted to call (respects the
        allow/disallow lists so the model doesn't attempt blocked tools).
        """
        visible = self._permissions.visible_names(list(self._tools.keys()))
        if not visible:
            return ""

        lines = [
            "## Available tools",
            "",
            "You have access to the following tools. Call a tool by outputting a",
            "line in this exact format (valid JSON arguments, all on one line):",
            "",
            "  [TOOL: tool_name {\"arg\": \"value\"}]",
            "",
            "After the tool result is shown to you, continue your response",
            "using that information. Only call one tool per response turn.",
            "",
            "Tools:",
        ]
        for name in visible:
            lines.append(self._tools[name].schema_text())
        lines.append("")
        return "\n".join(lines)

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def dispatch(self, call_text: str) -> "ToolResult | None":
        """Parse and execute a single ``[TOOL: ...]`` call string.

        Enforces all three permission tiers before running the tool:

        1. **Disallowed** — returns an error result immediately.
        2. **Not in allowed list** — returns an error result immediately.
        3. **Requires approval** — calls the approval callback; returns an
           error result if the user declines.

        Parameters
        ----------
        call_text:
            The full ``[TOOL: name {...}]`` string as emitted by the AI.

        Returns
        -------
        ToolResult | None
            The result, or ``None`` if the string doesn't match the format.
        """
        m = self._CALL_RE.search(call_text)
        if not m:
            return None

        tool_name = m.group(1).strip()
        args_str = m.group(2).strip()

        # Unknown tool check (before permission check so the error is accurate)
        tool = self._tools.get(tool_name)
        if tool is None:
            logger.warning("AI called unknown tool %r", tool_name)
            return ToolResult(
                tool_name=tool_name,
                error=f"Unknown tool: {tool_name!r}. "
                      f"Available: {', '.join(self._permissions.visible_names(list(self._tools)))}",
            )

        try:
            args = json.loads(args_str)
        except json.JSONDecodeError as exc:
            return ToolResult(
                tool_name=tool_name,
                error=f"Invalid tool arguments (not valid JSON): {exc}",
            )

        # Permission gate — returns a ToolResult on failure, None on success
        blocked = self._permissions.check(tool_name, args)
        if blocked is not None:
            return blocked

        logger.info("Running tool %r with args %s", tool_name, args)
        return tool.run(args)

    def find_calls(self, text: str) -> list[str]:
        """Return all ``[TOOL: ...]`` substrings found in *text*."""
        return [m.group(0) for m in self._CALL_RE.finditer(text)]


# ── Factory ───────────────────────────────────────────────────────────────────

def build_default_registry(tools_config: dict | None = None) -> ToolRegistry:
    """Create and return a :class:`ToolRegistry` with all built-in tools.

    Parameters
    ----------
    tools_config:
        The ``tools`` section from the application config.  Recognised keys:

        ``search_path`` (str)
            Default root directory for file searches.  Defaults to ``~``.
        ``blocked_paths`` (list[str])
            Paths the content-search tool will never read.
        ``allowed`` (list[str])
            Whitelist of tool names the AI may call.  Empty = all allowed.
        ``disallowed`` (list[str])
            Blacklist of tool names that are always blocked.
        ``requires_approval`` (list[str])
            Tools that need user confirmation before running.
        ``web_search.engine`` (str)
            Default search engine name (e.g. ``"duckduckgo"``).
        ``web_search.engines`` (dict)
            Additional or override engine URL templates.
        ``man_reader.enabled`` (bool)
            Whether to register the ``read_man_page`` tool.  Default ``True``.
        ``man_reader.max_chars`` (int)
            Max characters per man-page result.  Default ``8000``.
        ``man_reader.default_sections`` (list[str])
            Man-page sections extracted by default.
    """
    cfg = tools_config or {}
    default_path = cfg.get("search_path", str(Path.home()))
    blocked_paths: list[str] = cfg.get("blocked_paths", [])

    web_cfg = cfg.get("web_search", {})
    default_engine = web_cfg.get("engine", "duckduckgo")
    extra_engines: dict[str, str] = web_cfg.get("engines", {})

    man_cfg = cfg.get("man_reader", {})
    man_enabled: bool = man_cfg.get("enabled", True)
    man_max_chars: int = int(man_cfg.get("max_chars", 8_000))
    man_default_sections: list[str] = man_cfg.get(
        "default_sections", ["SYNOPSIS", "OPTIONS", "EXAMPLES"]
    )

    permissions = ToolPermissions(
        allowed=cfg.get("allowed", []),
        disallowed=cfg.get("disallowed", []),
        requires_approval=cfg.get("requires_approval", ["web_search"]),
    )

    registry = ToolRegistry(permissions=permissions)
    registry.register(FindFilesTool(default_search_path=default_path))
    registry.register(SearchInFilesTool(
        default_search_path=default_path,
        blocked_paths=blocked_paths,
    ))
    registry.register(WebSearchTool(
        default_engine=default_engine,
        engines=extra_engines,
    ))
    if man_enabled:
        registry.register(ManPageTool(
            max_chars=man_max_chars,
            default_sections=man_default_sections,
        ))
    return registry
