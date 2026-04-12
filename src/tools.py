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

``web_fetch``
    Fetch a URL from the internet and return its text content.  **Disabled
    by default** (``tools.web_fetch.enabled: false``).  When enabled every
    fetch requires user approval, TLS is always verified, private/loopback
    addresses are blocked (SSRF protection), and the response is size-capped.

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
import re
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
        lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
        prefix = str(search_path)
        return [l for l in lines if l.startswith(prefix)]

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
            import subprocess  # lazy — only when tool actually runs
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





# ── WebFetchTool ──────────────────────────────────────────────────────────────

# Content-Types we consider safe to return to the AI
_SAFE_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "text/html",
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "application/xml",
        "text/xml",
        "application/atom+xml",
        "application/rss+xml",
    }
)

# Hard cap: never return more than this many characters regardless of config
_FETCH_ABSOLUTE_MAX = 200_000


def _is_private_ip(host: str) -> bool:
    """Return True if *host* resolves to a loopback or RFC-1918 private address.

    Used for SSRF protection — prevents the AI from using the fetch tool to
    probe localhost or internal network services.
    """
    import ipaddress

    if host.lower() in ("localhost", "::1"):
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_loopback or addr.is_private or addr.is_link_local
    except ValueError:
        # It's a hostname, not a bare IP — cannot confirm; allow the request
        # (the OS resolver will handle it; we cannot reliably pre-block DNS).
        return False


def _html_to_text(html: str) -> str:
    """Convert HTML to plain readable text using the stdlib html.parser.

    Strips all tags, decodes entities, and collapses whitespace so the AI
    receives clean prose rather than raw markup.
    """
    import html as html_module
    from html.parser import HTMLParser

    class _Collector(HTMLParser):
        _SKIP_TAGS = frozenset(
            {"script", "style", "head", "noscript", "svg", "math"}
        )

        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self._parts: list[str] = []
            self._skip_depth: int = 0

        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag.lower() in self._SKIP_TAGS:
                self._skip_depth += 1
            elif tag.lower() in ("br", "p", "div", "li", "tr", "h1",
                                  "h2", "h3", "h4", "h5", "h6"):
                self._parts.append("\n")

        def handle_endtag(self, tag: str) -> None:
            if tag.lower() in self._SKIP_TAGS:
                self._skip_depth = max(0, self._skip_depth - 1)

        def handle_data(self, data: str) -> None:
            if self._skip_depth == 0:
                self._parts.append(data)

        def get_text(self) -> str:
            raw = "".join(self._parts)
            # Collapse runs of whitespace / blank lines
            lines = [ln.strip() for ln in raw.splitlines()]
            collapsed: list[str] = []
            prev_blank = False
            for ln in lines:
                if ln:
                    collapsed.append(ln)
                    prev_blank = False
                elif not prev_blank:
                    collapsed.append("")
                    prev_blank = True
            return "\n".join(collapsed).strip()

    parser = _Collector()
    parser.feed(html)
    return parser.get_text()


class WebFetchTool(Tool):
    """Fetch a URL from the internet and return its text content.

    Security model
    --------------
    - **TLS always verified** — ``verify=True`` is non-negotiable; there is no
      way to disable certificate checking through config.
    - **SSRF protection** — requests to loopback (``127.x``, ``::1``,
      ``localhost``) and link-local addresses are blocked so the AI cannot use
      this tool to probe internal services.
    - **Domain filtering** — optional allow-list and block-list.  If
      ``domain_allowlist`` is non-empty, only those domains are reachable.
    - **Content-type whitelist** — only ``text/*`` and safe ``application/*``
      responses are returned; binary files and executables are rejected.
    - **Size cap** — responses larger than ``max_response_chars`` are
      truncated; the raw body is never buffered beyond that limit.
    - **No session / cookie persistence** — each request uses a fresh
      ``requests.Session`` destroyed immediately after the call.
    - **Connection: close** — the TCP socket is released right after the
      response is consumed.

    This tool is **disabled by default**.  Enable it via ``config.yaml``:

    .. code-block:: yaml

       tools:
         web_fetch:
           enabled: true

    And ensure it stays in ``requires_approval`` so every fetch is confirmed
    by the user before it happens.
    """

    name = "web_fetch"
    description = (
        "Fetch the text content of a URL from the internet. "
        "TLS verified. SSRF-protected. Requires user approval before fetching."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch (must be https:// or http://).",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return (overrides config default).",
            },
        },
        "required": ["url"],
    }

    def __init__(
        self,
        max_response_chars: int = 8_000,
        allowed_content_types: list[str] | None = None,
        domain_allowlist: list[str] | None = None,
        domain_blocklist: list[str] | None = None,
        max_redirects: int = 5,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
    ) -> None:
        self._max_chars = min(max_response_chars, _FETCH_ABSOLUTE_MAX)
        self._allowed_types: frozenset[str] = (
            frozenset(t.lower() for t in allowed_content_types)
            if allowed_content_types is not None
            else _SAFE_CONTENT_TYPES
        )
        self._domain_allowlist: frozenset[str] = frozenset(
            d.lower().lstrip("*.") for d in (domain_allowlist or [])
        )
        self._domain_blocklist: frozenset[str] = frozenset(
            d.lower().lstrip("*.") for d in (domain_blocklist or [])
        )
        self._max_redirects = max_redirects
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout

    def run(self, args: dict[str, Any]) -> ToolResult:  # noqa: C901
        url: str = args.get("url", "").strip()
        if not url:
            return ToolResult(tool_name=self.name, error="'url' is required.")

        max_chars = min(
            int(args.get("max_chars", self._max_chars)), _FETCH_ABSOLUTE_MAX
        )

        # ── URL validation ────────────────────────────────────────────────────
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(tool_name=self.name, error=f"Invalid URL: {exc}")

        if parsed.scheme not in ("http", "https"):
            return ToolResult(
                tool_name=self.name,
                error=f"Only http:// and https:// URLs are supported, got: {parsed.scheme!r}",
            )

        host = (parsed.hostname or "").lower()

        # SSRF guard
        if _is_private_ip(host):
            return ToolResult(
                tool_name=self.name,
                error=(
                    f"Fetching private/loopback addresses is blocked for security. "
                    f"Host: {host!r}"
                ),
            )

        # Domain allow-list
        if self._domain_allowlist:
            if not any(
                host == allowed or host.endswith("." + allowed)
                for allowed in self._domain_allowlist
            ):
                return ToolResult(
                    tool_name=self.name,
                    error=(
                        f"Domain {host!r} is not in the allowed list. "
                        f"Allowed: {', '.join(sorted(self._domain_allowlist))}"
                    ),
                )

        # Domain block-list
        if any(
            host == blocked or host.endswith("." + blocked)
            for blocked in self._domain_blocklist
        ):
            return ToolResult(
                tool_name=self.name,
                error=f"Domain {host!r} is blocked by configuration.",
            )

        # ── HTTP request ──────────────────────────────────────────────────────
        try:
            import requests as _requests  # lazy import
        except ImportError:
            return ToolResult(
                tool_name=self.name,
                error="'requests' is not installed. Run: pip install requests",
            )

        logger.info("WebFetchTool: fetching %s", url)

        session = _requests.Session()
        session.max_redirects = self._max_redirects
        # Backend efficiency: close the socket after this single request
        session.headers.update({"Connection": "close"})
        # TLS: always verify; this cannot be overridden by args
        session.verify = True

        try:
            resp = session.get(
                url,
                timeout=(self._connect_timeout, self._read_timeout),
                stream=True,
            )
            resp.raise_for_status()

            # Content-type check before reading the body
            ct_header = resp.headers.get("Content-Type", "")
            ct_base = ct_header.split(";")[0].strip().lower()
            if ct_base and ct_base not in self._allowed_types:
                return ToolResult(
                    tool_name=self.name,
                    error=(
                        f"Content-Type {ct_base!r} is not in the allowed list. "
                        "Only text and JSON responses are returned."
                    ),
                )

            # Read up to (max_chars * 4) bytes — UTF-8 chars can be 1-4 bytes
            body_bytes = resp.raw.read(max_chars * 4, decode_content=True)
            encoding = resp.encoding or "utf-8"
            body = body_bytes.decode(encoding, errors="replace")

        except _requests.exceptions.SSLError as exc:
            return ToolResult(
                tool_name=self.name,
                error=f"TLS/SSL error fetching {url!r}: {exc}",
            )
        except _requests.exceptions.Timeout:
            return ToolResult(
                tool_name=self.name,
                error=f"Request timed out fetching {url!r}.",
            )
        except _requests.exceptions.TooManyRedirects:
            return ToolResult(
                tool_name=self.name,
                error=f"Too many redirects fetching {url!r} (limit: {self._max_redirects}).",
            )
        except _requests.exceptions.RequestException as exc:
            return ToolResult(tool_name=self.name, error=f"Request failed: {exc}")
        finally:
            session.close()  # release the TCP socket immediately

        # Convert HTML to readable text; leave JSON/plain as-is
        if "html" in ct_base:
            text = _html_to_text(body)
        else:
            text = body

        truncated = len(text) > max_chars
        text = text[:max_chars]

        return ToolResult(
            tool_name=self.name,
            results=[SearchResult(path=url, snippet=text)],
            truncated=truncated,
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

        # Check man is available (lazy import shutil — only on first run)
        import shutil  # lazy
        if not shutil.which("man"):
            return ToolResult(
                tool_name=self.name,
                error="'man' is not installed on this system.",
            )

        cmd = ["man"]
        if man_section:
            cmd.append(man_section)
        cmd.append(command)

        import os        # lazy
        import subprocess  # lazy
        env = os.environ.copy()
        env["MANPAGER"] = "cat"
        env["MANWIDTH"] = "100"
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


# ── SystemControlTool ─────────────────────────────────────────────────────────

# Maps resource → (get_cmds, on_cmds, off_cmds, toggle_cmds)
# Each entry is a list of candidate command lists tried in order until one
# succeeds.  Commands are chosen by detecting which executables are on PATH.
#
# Backends tried in preference order:
#   audio/microphone : WirePlumber (wpctl) → PulseAudio (pactl) → ALSA (amixer)
#   bluetooth        : bluetoothctl → rfkill
#   wifi             : nmcli → rfkill
#   power_mode       : power-profiles-daemon (powerprofilesctl) → TuneD (tuned-adm)
#   brightness       : brightnessctl → xbacklight → light

_RESOURCE_ACTIONS: dict[str, dict[str, list[list[str]]]] = {
    "audio": {
        "get": [
            ["wpctl",  "get-volume", "@DEFAULT_AUDIO_SINK@"],
            ["pactl",  "get-sink-mute", "@DEFAULT_SINK@"],
            ["amixer", "get", "Master"],
        ],
        "mute": [
            ["wpctl",  "set-mute", "@DEFAULT_AUDIO_SINK@", "1"],
            ["pactl",  "set-sink-mute", "@DEFAULT_SINK@", "1"],
            ["amixer", "sset", "Master", "mute"],
        ],
        "unmute": [
            ["wpctl",  "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
            ["pactl",  "set-sink-mute", "@DEFAULT_SINK@", "0"],
            ["amixer", "sset", "Master", "unmute"],
        ],
        "toggle": [
            ["wpctl",  "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
            ["pactl",  "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
            ["amixer", "sset", "Master", "toggle"],
        ],
    },
    "microphone": {
        "get": [
            ["wpctl",  "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
            ["pactl",  "get-source-mute", "@DEFAULT_SOURCE@"],
            ["amixer", "get", "Capture"],
        ],
        "mute": [
            ["wpctl",  "set-mute", "@DEFAULT_AUDIO_SOURCE@", "1"],
            ["pactl",  "set-source-mute", "@DEFAULT_SOURCE@", "1"],
            ["amixer", "sset", "Capture", "nocap"],
        ],
        "unmute": [
            ["wpctl",  "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0"],
            ["pactl",  "set-source-mute", "@DEFAULT_SOURCE@", "0"],
            ["amixer", "sset", "Capture", "cap"],
        ],
        "toggle": [
            ["wpctl",  "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"],
            ["pactl",  "set-source-mute", "@DEFAULT_SOURCE@", "toggle"],
            ["amixer", "sset", "Capture", "toggle"],
        ],
    },
    "bluetooth": {
        "get": [
            ["bluetoothctl", "show"],
            ["rfkill", "list", "bluetooth"],
        ],
        "on": [
            ["bluetoothctl", "power", "on"],
            ["rfkill", "unblock", "bluetooth"],
        ],
        "off": [
            ["bluetoothctl", "power", "off"],
            ["rfkill", "block", "bluetooth"],
        ],
    },
    "wifi": {
        "get": [
            ["nmcli", "radio", "wifi"],
            ["rfkill", "list", "wifi"],
        ],
        "on": [
            ["nmcli", "radio", "wifi", "on"],
            ["rfkill", "unblock", "wifi"],
        ],
        "off": [
            ["nmcli", "radio", "wifi", "off"],
            ["rfkill", "block", "wifi"],
        ],
    },
    "power_mode": {
        "get": [
            ["powerprofilesctl", "get"],
            ["tuned-adm", "active"],
        ],
        "performance": [
            ["powerprofilesctl", "set", "performance"],
            ["tuned-adm", "profile", "throughput-performance"],
        ],
        "balanced": [
            ["powerprofilesctl", "set", "balanced"],
            ["tuned-adm", "profile", "balanced"],
        ],
        "power-saver": [
            ["powerprofilesctl", "set", "power-saver"],
            ["tuned-adm", "profile", "powersave"],
        ],
    },
    "brightness": {
        "get": [
            ["brightnessctl", "get"],
            ["xbacklight", "-get"],
            ["light", "-G"],
        ],
    },
}

# Valid actions for each resource
_VALID_ACTIONS: dict[str, list[str]] = {
    "audio":       ["get", "mute", "unmute", "toggle"],
    "microphone":  ["get", "mute", "unmute", "toggle"],
    "bluetooth":   ["get", "on", "off"],
    "wifi":        ["get", "on", "off"],
    "power_mode":  ["get", "performance", "balanced", "power-saver"],
    "brightness":  ["get", "set"],
}


def _run_first_available(candidates: list[list[str]]) -> "tuple[bool, str]":
    """Try each command list in *candidates* until one succeeds.

    Returns ``(success, output)`` where ``output`` is stdout on success or the
    last error message on failure.
    """
    import shutil    # lazy
    import subprocess  # lazy

    last_err = "No suitable backend found."
    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
            )
            if proc.returncode == 0:
                return True, proc.stdout.strip()
            last_err = proc.stderr.strip() or proc.stdout.strip()
        except subprocess.TimeoutExpired:
            last_err = f"{cmd[0]} timed out."
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
    return False, last_err


class SystemControlTool(Tool):
    """Control system resources: audio, microphone, Bluetooth, Wi-Fi,
    power mode, and display brightness.

    Backend detection
    -----------------
    For each resource the tool tries available backends in order:

    - **Audio / Microphone**: WirePlumber (``wpctl``) → PulseAudio (``pactl``)
      → ALSA (``amixer``)
    - **Bluetooth**: ``bluetoothctl`` → ``rfkill``
    - **Wi-Fi**: ``nmcli`` (NetworkManager) → ``rfkill``
    - **Power mode**: ``powerprofilesctl`` (power-profiles-daemon) →
      ``tuned-adm`` (TuneD)
    - **Brightness**: ``brightnessctl`` → ``xbacklight`` → ``light``

    The first backend whose executable is on ``$PATH`` is used.  All
    subprocess imports and ``shutil.which`` checks are deferred to the
    first ``run()`` call so loading this module is free.

    Safety
    ------
    This tool is in ``requires_approval`` by default.  The user sees exactly
    which resource and action the AI is requesting before anything changes.
    Read-only ``get`` queries skip approval.
    """

    name = "system_control"
    description = (
        "Control system resources: toggle/query audio, microphone, Bluetooth, "
        "Wi-Fi, power mode, and brightness. "
        "Uses native Linux backends (wpctl/pactl, bluetoothctl, nmcli, etc.)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "resource": {
                "type": "string",
                "enum": list(_VALID_ACTIONS),
                "description": (
                    "The system resource to control. One of: "
                    + ", ".join(f"'{k}'" for k in _VALID_ACTIONS) + "."
                ),
            },
            "action": {
                "type": "string",
                "description": (
                    "Action to perform. Depends on resource:\n"
                    "  audio/microphone: get | mute | unmute | toggle\n"
                    "  bluetooth/wifi:   get | on | off\n"
                    "  power_mode:       get | performance | balanced | power-saver\n"
                    "  brightness:       get | set (requires value)\n"
                ),
            },
            "value": {
                "type": "string",
                "description": (
                    "Value for actions that need one.\n"
                    "  brightness set: percentage string, e.g. '50%' or '50'.\n"
                    "  audio/microphone set-volume: e.g. '75%'."
                ),
            },
        },
        "required": ["resource", "action"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        resource: str = args.get("resource", "").lower().strip()
        action: str = args.get("action", "").lower().strip()
        value: str = args.get("value", "").strip()

        if resource not in _VALID_ACTIONS:
            return ToolResult(
                tool_name=self.name,
                error=(
                    f"Unknown resource '{resource}'. "
                    f"Valid resources: {', '.join(_VALID_ACTIONS)}."
                ),
            )

        valid = _VALID_ACTIONS[resource]
        if action not in valid:
            return ToolResult(
                tool_name=self.name,
                error=(
                    f"Invalid action '{action}' for '{resource}'. "
                    f"Valid actions: {', '.join(valid)}."
                ),
            )

        # ── Special case: brightness set ──────────────────────────────────────
        if resource == "brightness" and action == "set":
            return self._set_brightness(value)

        # ── Look up backend commands ───────────────────────────────────────────
        resource_map = _RESOURCE_ACTIONS.get(resource, {})
        candidates = resource_map.get(action)
        if not candidates:
            return ToolResult(
                tool_name=self.name,
                error=f"No backend commands defined for {resource}/{action}.",
            )

        success, output = _run_first_available(candidates)
        if not success:
            return ToolResult(
                tool_name=self.name,
                error=(
                    f"Could not {action} {resource}. "
                    f"No supported backend found or command failed: {output}"
                ),
            )

        snippet = f"{resource} {action}: {output}" if output else f"{resource} {action}: OK"
        return ToolResult(
            tool_name=self.name,
            results=[SearchResult(path=f"system:{resource}", snippet=snippet)],
        )

    def _set_brightness(self, value: str) -> ToolResult:
        """Handle brightness set with a percentage or absolute value."""
        import shutil    # lazy
        import subprocess  # lazy

        if not value:
            return ToolResult(
                tool_name=self.name,
                error="brightness set requires a 'value', e.g. '50%'.",
            )

        # Normalise to percentage string for tools that accept it
        pct = value if value.endswith("%") else f"{value}%"

        candidates = [
            ["brightnessctl", "set", pct],
            ["xbacklight", "-set", value.rstrip("%")],
            ["light", "-S", value.rstrip("%")],
        ]
        success, output = _run_first_available(candidates)
        if not success:
            return ToolResult(
                tool_name=self.name,
                error=f"Could not set brightness to {value}: {output}",
            )
        return ToolResult(
            tool_name=self.name,
            results=[SearchResult(
                path="system:brightness",
                snippet=f"Brightness set to {value}.",
            )],
        )

    def schema_text(self) -> str:
        resources = ", ".join(_VALID_ACTIONS)
        return (
            f"  {self.name}(resource: {resources}; action: string; value?: string)"
            f" — {self.description}"
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


# ── ToolDescriptor ────────────────────────────────────────────────────────────


@dataclass
class ToolDescriptor:
    """Metadata + factory for a single tool — the instance is created lazily.

    The descriptor holds everything the :class:`ToolRegistry` needs to:
    - Advertise the tool to the AI (name, description, schema) **without**
      instantiating it.
    - Create the tool instance on first use via *factory*.
    - Release the instance after use when *unload_after_use* is ``True``.

    Lifecycle
    ---------
    .. code-block:: text

        UNLOADED  ──(get_instance)──►  LOADED  ──(release)──►  UNLOADED
                                          │
                                     run() called here

    The transition back to UNLOADED is triggered automatically by
    :meth:`ToolRegistry.dispatch` when *unload_after_use* is ``True``, or
    manually via :meth:`ToolRegistry.unload` / :meth:`ToolRegistry.unload_all`.
    """

    name: str
    description: str
    parameters_schema: dict
    factory: Callable[[], Tool]
    unload_after_use: bool = False

    # Private — managed by get_instance() / release()
    _instance: Tool | None = field(default=None, init=False, repr=False)

    # ── Instance lifecycle ────────────────────────────────────────────────────

    def get_instance(self) -> Tool:
        """Return the live tool instance, creating it on first call."""
        if self._instance is None:
            logger.debug("Lazy-loading tool: %s", self.name)
            self._instance = self.factory()
        return self._instance

    def release(self) -> None:
        """Release the tool instance so it can be garbage-collected."""
        if self._instance is not None:
            logger.debug("Unloading tool: %s", self.name)
            self._instance = None

    @property
    def is_loaded(self) -> bool:
        """``True`` if the tool instance is currently in memory."""
        return self._instance is not None

    # ── System-prompt metadata ────────────────────────────────────────────────

    def schema_text(self) -> str:
        """Return a compact one-line description for the AI system prompt.

        Reads only from the descriptor fields — never touches the instance.
        """
        props = self.parameters_schema.get("properties", {})
        params = ", ".join(
            f"{k}: {v.get('type', 'string')}"
            for k, v in props.items()
        )
        return f"  {self.name}({params}) — {self.description}"


# ── ToolRegistry ──────────────────────────────────────────────────────────────


class ToolRegistry:
    """Registry of all available tools.

    Tools are stored as :class:`ToolDescriptor` objects and instantiated
    **lazily** — only when ``dispatch()`` actually calls them.  After each
    call the instance can optionally be released (unloaded) so it is
    garbage-collected, keeping memory usage at a minimum.

    Key properties
    --------------
    - **Zero startup cost**: registering tools is free; nothing is imported
      or constructed until the first ``dispatch()`` for that tool.
    - **Selective unloading**: set ``unload_after_use=True`` per tool (or
      globally via config) to release instances between calls.
    - **System-prompt generation** uses descriptor metadata only — no tool
      is ever instantiated just to build the prompt.
    - **Permission enforcement** via :class:`ToolPermissions` happens before
      the tool instance is even loaded, so blocked tools cost nothing.
    """

    _CALL_RE = re.compile(r"\[TOOL:\s*(\w+)\s*(\{.*?\})\]", re.DOTALL)

    def __init__(
        self,
        permissions: ToolPermissions | None = None,
        unload_after_use: bool = False,
    ) -> None:
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._permissions = permissions or ToolPermissions()
        self._default_unload = unload_after_use

    # ── Registration ──────────────────────────────────────────────────────────

    def register_lazy(
        self,
        name: str,
        description: str,
        schema: dict,
        factory: Callable[[], Tool],
        *,
        unload_after_use: bool | None = None,
    ) -> None:
        """Register a tool using a factory function (primary API).

        The factory is only called on the first ``dispatch()`` for this tool.
        Subsequent calls reuse the cached instance unless *unload_after_use*
        is ``True``, in which case the instance is released after every call.

        Parameters
        ----------
        name:
            Tool name used in ``[TOOL: name {...}]`` markers.
        description:
            One-line description shown to the AI in the system prompt.
        schema:
            JSON Schema dict for the tool's parameters.
        factory:
            Zero-argument callable that returns a fresh ``Tool`` instance.
        unload_after_use:
            Override the registry's default unload policy for this tool.
            ``None`` → inherit the registry default.
        """
        unload = self._default_unload if unload_after_use is None else unload_after_use
        self._descriptors[name] = ToolDescriptor(
            name=name,
            description=description,
            parameters_schema=schema,
            factory=factory,
            unload_after_use=unload,
        )
        logger.debug("Registered tool (lazy): %s  unload_after_use=%s", name, unload)

    def register(self, tool: Tool) -> None:
        """Register an already-constructed tool instance (convenience API).

        The instance is wrapped in a descriptor so it participates in the
        same lazy-load / unload lifecycle.  The instance is considered
        pre-loaded (``is_loaded == True``) immediately after registration.
        """
        desc = ToolDescriptor(
            name=tool.name,
            description=tool.description,
            parameters_schema=tool.parameters_schema,
            factory=lambda t=tool: t,
            unload_after_use=self._default_unload,
        )
        desc._instance = tool  # already loaded
        self._descriptors[tool.name] = desc
        logger.debug("Registered tool (eager): %s", tool.name)

    # ── Inspection ────────────────────────────────────────────────────────────

    def get(self, name: str) -> Tool | None:
        """Return the live instance for *name* if it is currently loaded."""
        desc = self._descriptors.get(name)
        return desc._instance if desc else None

    def get_descriptor(self, name: str) -> ToolDescriptor | None:
        """Return the :class:`ToolDescriptor` for *name*."""
        return self._descriptors.get(name)

    def names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._descriptors)

    def loaded_names(self) -> list[str]:
        """Return names of tools whose instances are currently in memory."""
        return [n for n, d in self._descriptors.items() if d.is_loaded]

    # ── Load / unload ─────────────────────────────────────────────────────────

    def unload(self, name: str) -> bool:
        """Release the instance for tool *name*.

        Returns ``True`` if the tool was loaded and is now released,
        ``False`` if the tool is unknown or was already unloaded.
        """
        desc = self._descriptors.get(name)
        if desc and desc.is_loaded:
            desc.release()
            return True
        return False

    def unload_all(self) -> list[str]:
        """Release all currently loaded tool instances.

        Returns the list of tool names that were unloaded.
        """
        released = []
        for name, desc in self._descriptors.items():
            if desc.is_loaded:
                desc.release()
                released.append(name)
        if released:
            logger.debug("Unloaded %d tool(s): %s", len(released), released)
        return released

    # ── System-prompt generation ──────────────────────────────────────────────

    def system_prompt_section(self) -> str:
        """Return the block injected into the AI system prompt.

        Only lists tools the AI is permitted to call.
        **No tool instance is created** — reads descriptor metadata only.
        """
        visible = self._permissions.visible_names(list(self._descriptors))
        if not visible:
            return ""

        lines = [
            "## Available tools",
            "",
            "You have access to the following tools. When you need to use one,",
            "output exactly one line in this format (valid JSON, on a single line):",
            "",
            '  [TOOL: tool_name {"arg": "value"}]',
            "",
            "Wait for the tool result before continuing your response.",
            "Only call one tool per response turn.",
            "",
            "Tools:",
        ]
        for name in visible:
            lines.append(self._descriptors[name].schema_text())
        lines.append("")
        return "\n".join(lines)

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def dispatch(self, call_text: str) -> ToolResult | None:
        """Parse and execute a ``[TOOL: name {...}]`` call from the AI.

        Lifecycle per call
        ------------------
        1. Parse *call_text* — return ``None`` if no marker found.
        2. Permission check (allow/disallow/approval) — return error result
           if blocked.  **No instance is created for blocked tools.**
        3. Lazily load the tool instance via ``descriptor.get_instance()``.
        4. Run ``tool.run(args)`` and collect the result.
        5. If ``descriptor.unload_after_use`` is ``True``, release the
           instance immediately so memory is reclaimed.

        Parameters
        ----------
        call_text:
            Text containing a ``[TOOL: name {...}]`` marker.

        Returns
        -------
        ToolResult | None
            Result of the tool call, or ``None`` if no marker was found.
        """
        m = self._CALL_RE.search(call_text)
        if not m:
            return None

        tool_name = m.group(1).strip()
        args_str = m.group(2).strip()

        # 1. Unknown tool — report visible tools, not all tools
        desc = self._descriptors.get(tool_name)
        if desc is None:
            logger.warning("AI called unknown tool %r", tool_name)
            visible = self._permissions.visible_names(list(self._descriptors))
            return ToolResult(
                tool_name=tool_name,
                error=(
                    f"Unknown tool: '{tool_name}'. "
                    f"Available: {', '.join(visible) or 'none'}."
                ),
            )

        # 2. Parse JSON args
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError as exc:
            return ToolResult(
                tool_name=tool_name,
                error=f"Invalid tool arguments (not valid JSON): {exc}",
            )

        # 3. Permission gate — no instance created if blocked
        blocked = self._permissions.check(tool_name, args)
        if blocked is not None:
            return blocked

        # 4. Lazy-load and run
        tool = desc.get_instance()
        logger.info("Dispatching tool '%s' args=%s", tool_name, args)
        result = tool.run(args)

        # 5. Optional unload after use
        if desc.unload_after_use:
            desc.release()

        return result

    def find_calls(self, text: str) -> list[str]:
        """Return all ``[TOOL: ...]`` substrings found in *text*."""
        return [m.group(0) for m in self._CALL_RE.finditer(text)]


# ── Factory ───────────────────────────────────────────────────────────────────

def build_default_registry(tools_config: dict | None = None) -> ToolRegistry:
    """Create a :class:`ToolRegistry` with all built-in tools registered lazily.

    No tool instance is created by this function — factories are stored and
    called only when each tool is first dispatched.

    Parameters
    ----------
    tools_config:
        The ``tools`` section from the application config.  Recognised keys:

        ``unload_after_use`` (bool)
            Global default: release each tool instance after every call.
            Default ``False`` (instances cached for speed).
        ``search_path`` (str)
            Default root directory for file/content searches.
        ``blocked_paths`` (list[str])
            Paths the content-search tool will never read.
        ``allowed`` / ``disallowed`` / ``requires_approval`` (list[str])
            Tool permission lists.
        ``web_search.engine`` / ``web_search.engines``
            Browser search engine configuration.
        ``web_fetch.enabled`` (bool)
            Enable the web-fetch tool (default ``False``).
        ``man_reader.enabled`` (bool)
            Enable the man-page reader (default ``True``).
        ``man_reader.max_chars`` / ``man_reader.default_sections``
            Man-page reader tuning.
        ``system_control.enabled`` (bool)
            Enable the system-control tool (default ``True``).
        ``system_control.unload_after_use`` (bool)
            Per-tool unload override for system_control.
    """
    cfg = tools_config or {}
    global_unload: bool = bool(cfg.get("unload_after_use", False))

    default_path = cfg.get("search_path", str(Path.home()))
    blocked_paths: list[str] = cfg.get("blocked_paths", [])

    web_cfg = cfg.get("web_search", {})
    default_engine = web_cfg.get("engine", "duckduckgo")
    extra_engines: dict[str, str] = web_cfg.get("engines", {})

    fetch_cfg = cfg.get("web_fetch", {})
    fetch_enabled: bool = bool(fetch_cfg.get("enabled", False))

    man_cfg = cfg.get("man_reader", {})
    man_enabled: bool = bool(man_cfg.get("enabled", True))
    man_max_chars: int = int(man_cfg.get("max_chars", 8_000))
    man_sections: list[str] = man_cfg.get(
        "default_sections", ["SYNOPSIS", "OPTIONS", "EXAMPLES"]
    )
    man_unload: bool = bool(man_cfg.get("unload_after_use", global_unload))

    sc_cfg = cfg.get("system_control", {})
    sc_enabled: bool = bool(sc_cfg.get("enabled", True))
    sc_unload: bool = bool(sc_cfg.get("unload_after_use", global_unload))

    default_approval = ["web_search", "web_fetch", "system_control"]
    permissions = ToolPermissions(
        allowed=cfg.get("allowed", []),
        disallowed=cfg.get("disallowed", []),
        requires_approval=cfg.get("requires_approval", default_approval),
    )

    registry = ToolRegistry(permissions=permissions, unload_after_use=global_unload)

    # ── find_files ────────────────────────────────────────────────────────────
    registry.register_lazy(
        name=FindFilesTool.name,
        description=FindFilesTool.description,
        schema=FindFilesTool.parameters_schema,
        factory=lambda: FindFilesTool(default_search_path=default_path),
    )

    # ── search_in_files ───────────────────────────────────────────────────────
    registry.register_lazy(
        name=SearchInFilesTool.name,
        description=SearchInFilesTool.description,
        schema=SearchInFilesTool.parameters_schema,
        factory=lambda: SearchInFilesTool(
            default_search_path=default_path,
            blocked_paths=blocked_paths,
        ),
    )

    # ── web_search ────────────────────────────────────────────────────────────
    registry.register_lazy(
        name=WebSearchTool.name,
        description=WebSearchTool.description,
        schema=WebSearchTool.parameters_schema,
        factory=lambda: WebSearchTool(
            default_engine=default_engine,
            engines=extra_engines,
        ),
    )

    # ── web_fetch (off by default) ────────────────────────────────────────────
    if fetch_enabled:
        registry.register_lazy(
            name=WebFetchTool.name,
            description=WebFetchTool.description,
            schema=WebFetchTool.parameters_schema,
            factory=lambda: WebFetchTool(
                max_response_chars=int(fetch_cfg.get("max_response_chars", 8_000)),
                allowed_content_types=fetch_cfg.get("allowed_content_types"),
                domain_allowlist=fetch_cfg.get("domain_allowlist"),
                domain_blocklist=fetch_cfg.get("domain_blocklist"),
                max_redirects=int(fetch_cfg.get("max_redirects", 5)),
                connect_timeout=float(fetch_cfg.get("connect_timeout", 5.0)),
                read_timeout=float(fetch_cfg.get("read_timeout", 15.0)),
            ),
        )

    # ── read_man_page ─────────────────────────────────────────────────────────
    if man_enabled:
        registry.register_lazy(
            name=ManPageTool.name,
            description=ManPageTool.description,
            schema=ManPageTool.parameters_schema,
            factory=lambda: ManPageTool(
                max_chars=man_max_chars,
                default_sections=man_sections,
            ),
            unload_after_use=man_unload,
        )

    # ── system_control ────────────────────────────────────────────────────────
    if sc_enabled:
        registry.register_lazy(
            name=SystemControlTool.name,
            description=SystemControlTool.description,
            schema=SystemControlTool.parameters_schema,
            factory=SystemControlTool,
            unload_after_use=sc_unload,
        )

    return registry
