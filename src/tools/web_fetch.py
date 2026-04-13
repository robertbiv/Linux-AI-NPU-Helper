# SPDX-License-Identifier: GPL-3.0-or-later
"""Web fetch tool — retrieve text content from a URL."""

from __future__ import annotations

import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)

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
