# SPDX-License-Identifier: GPL-3.0-or-later
"""Web fetch tool — retrieve text content from a URL."""

from __future__ import annotations

import logging
from dataclasses import dataclass
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


def _resolve_and_check_ip(host: str) -> tuple[bool, str | None]:
    """Resolve *host* to an IP and return (is_private, resolved_ip).

    Returns (True, None) if the host is private, loopback, or cannot be resolved.
    Returns (False, ip) if the host is public and safe to fetch.
    """
    import ipaddress
    import socket

    if host.lower() in ("localhost", "::1"):
        return True, None

    # First, try to parse it directly as an IP address
    try:
        addr = ipaddress.ip_address(host)
        is_priv = addr.is_loopback or addr.is_private or addr.is_link_local
        return is_priv, host
    except ValueError:
        pass

    # If it's a hostname, resolve it to an IP and check the resolved IP
    try:
        resolved_ip = socket.gethostbyname(host)
        addr = ipaddress.ip_address(resolved_ip)
        is_priv = addr.is_loopback or addr.is_private or addr.is_link_local
        return is_priv, resolved_ip
    except Exception:
        # If DNS resolution fails, fail closed to prevent SSRF bypass
        return True, None


import socket
import threading

# Use thread-local to safely override DNS resolution for this specific request
_dns_local = threading.local()
_original_getaddrinfo = socket.getaddrinfo

def _custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if hasattr(_dns_local, "mapping") and host in _dns_local.mapping:
        return _original_getaddrinfo(
            _dns_local.mapping[host], port, family, type, proto, flags
        )
    return _original_getaddrinfo(host, port, family, type, proto, flags)

# Apply global monkey patch exactly once at module load time.
socket.getaddrinfo = _custom_getaddrinfo


def _html_to_text(html: str) -> str:
    """Convert HTML to plain readable text using the stdlib html.parser.

    Strips all tags, decodes entities, and collapses whitespace so the AI
    receives clean prose rather than raw markup.
    """
    from html.parser import HTMLParser

    class _Collector(HTMLParser):
        _SKIP_TAGS = frozenset({"script", "style", "head", "noscript", "svg", "math"})

        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self._parts: list[str] = []
            self._skip_depth: int = 0

        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag.lower() in self._SKIP_TAGS:
                self._skip_depth += 1
            elif tag.lower() in (
                "br",
                "p",
                "div",
                "li",
                "tr",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
            ):
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


@dataclass
class WebFetchConfig:
    max_response_chars: int = 8_000
    allowed_content_types: list[str] | None = None
    domain_allowlist: list[str] | None = None
    domain_blocklist: list[str] | None = None
    max_redirects: int = 5
    connect_timeout: float = 5.0
    read_timeout: float = 15.0


class WebFetchTool(Tool):
    """Fetch a URL from the internet and return its text content.

    ## Security model

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

    def __init__(self, config: WebFetchConfig | None = None) -> None:
        cfg = config or WebFetchConfig()
        self._max_chars = min(cfg.max_response_chars, _FETCH_ABSOLUTE_MAX)
        self._allowed_types: frozenset[str] = (
            frozenset(t.lower() for t in cfg.allowed_content_types)
            if cfg.allowed_content_types is not None
            else _SAFE_CONTENT_TYPES
        )
        self._domain_allowlist: frozenset[str] = frozenset(
            d.lower().lstrip("*.") for d in (cfg.domain_allowlist or [])
        )
        self._domain_blocklist: frozenset[str] = frozenset(
            d.lower().lstrip("*.") for d in (cfg.domain_blocklist or [])
        )
        self._max_redirects = cfg.max_redirects
        self._connect_timeout = cfg.connect_timeout
        self._read_timeout = cfg.read_timeout

    def _validate_url(self, url: str) -> tuple[ToolResult | None, str | None, str | None]:
        """Validate URL to ensure it is safe and allowed.

        Returns:
            (ToolResult, None, None) on validation error.
            (None, host, resolved_ip) on success.
        """
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(tool_name=self.name, error=f"Invalid URL: {exc}"), None, None

        if parsed.scheme not in ("http", "https"):
            return ToolResult(
                tool_name=self.name,
                error=f"Only http:// and https:// URLs are supported, got: {parsed.scheme!r}",
            ), None, None

        host = (parsed.hostname or "").lower()

        # SSRF guard with DNS resolution
        is_private, resolved_ip = _resolve_and_check_ip(host)
        if is_private or not resolved_ip:
            return ToolResult(
                tool_name=self.name,
                error=(
                    f"Fetching private/loopback addresses (or unresolvable hosts) "
                    f"is blocked for security. Host: {host!r}"
                ),
            ), None, None

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
                ), None, None

        # Domain block-list
        if any(
            host == blocked or host.endswith("." + blocked)
            for blocked in self._domain_blocklist
        ):
            return ToolResult(
                tool_name=self.name,
                error=f"Domain {host!r} is blocked by configuration.",
            ), None, None

        return None, host, resolved_ip

    def run(self, args: dict[str, Any]) -> ToolResult:
        url: str = args.get("url", "").strip()
        if not url:
            return ToolResult(tool_name=self.name, error="'url' is required.")

        max_chars = min(
            int(args.get("max_chars", self._max_chars)), _FETCH_ABSOLUTE_MAX
        )

        validation_result, initial_host, initial_ip = self._validate_url(url)
        if validation_result:
            return validation_result

        return self._execute_request(url, max_chars, initial_host, initial_ip)

    def _execute_request(self, url: str, max_chars: int, initial_host: str, initial_ip: str) -> ToolResult:
        """Execute the HTTP request and return the result."""
        try:
            import requests as _requests  # lazy import
        except ImportError:
            return ToolResult(
                tool_name=self.name,
                error="'requests' is not installed. Run: pip install requests",
            )

        logger.info("WebFetchTool: fetching %s", url)

        # Set thread-local mapping to safely override DNS resolution for this specific request
        _dns_local.mapping = {initial_host: initial_ip}

        session = _requests.Session()
        # Backend efficiency: close the socket after this single request
        session.headers.update({"Connection": "close"})
        # TLS: always verify; this cannot be overridden by args
        session.verify = True

        redirects = 0
        current_url = url

        try:
            while True:
                resp = session.get(
                    current_url,
                    timeout=(self._connect_timeout, self._read_timeout),
                    stream=True,
                    allow_redirects=False,
                )

                if resp.is_redirect:
                    redirects += 1
                    if redirects > self._max_redirects:
                        return ToolResult(
                            tool_name=self.name,
                            error=f"Too many redirects fetching {url!r} (limit: {self._max_redirects}).",
                        )

                    next_url = resp.headers.get("location")
                    if not next_url:
                        return ToolResult(
                            tool_name=self.name,
                            error=f"Redirect missing location header for {current_url!r}.",
                        )

                    # Resolve relative URLs
                    from urllib.parse import urljoin
                    current_url = urljoin(current_url, next_url)

                    # Validate the new URL against SSRF and block/allow lists
                    validation_result, next_host, next_ip = self._validate_url(current_url)
                    if validation_result:
                        return ToolResult(
                            tool_name=self.name,
                            error=f"Redirect to {current_url!r} blocked: {validation_result.error}",
                        )

                    # Update the DNS mapping to enforce the resolved IP for the redirect
                    if next_host and next_ip:
                        _dns_local.mapping[next_host] = next_ip

                    # Consume body to release connection back to pool if needed
                    resp.raw.read(1024)
                    resp.close()
                    continue

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
                break

        except _requests.exceptions.SSLError as exc:
            return ToolResult(
                tool_name=self.name,
                error=f"TLS/SSL error fetching {current_url!r}: {exc}",
            )
        except _requests.exceptions.Timeout:
            return ToolResult(
                tool_name=self.name,
                error=f"Request timed out fetching {current_url!r}.",
            )
        except _requests.exceptions.RequestException as exc:
            return ToolResult(tool_name=self.name, error=f"Request failed: {exc}")
        finally:
            if hasattr(_dns_local, "mapping"):
                _dns_local.mapping.clear()  # Clear thread-local mapping
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
