# SPDX-License-Identifier: GPL-3.0-or-later
"""Web search tool — open the user's browser with a search query."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)

# Built-in engine URL templates (query placeholder: {query})
_DEFAULT_ENGINES: dict[str, str] = {
    "duckduckgo": "https://duckduckgo.com/?q={query}",
    "startpage": "https://www.startpage.com/search?q={query}",
    "brave": "https://search.brave.com/search?q={query}",
    "ecosia": "https://www.ecosia.org/search?q={query}",
    "google": "https://www.google.com/search?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
}


class WebSearchTool(Tool):
    """Open the user's default browser to search the web.

    ## Privacy model

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
                shell=False,
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
