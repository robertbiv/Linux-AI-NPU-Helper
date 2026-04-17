# SPDX-License-Identifier: GPL-3.0-or-later
"""Text stats tool — count words, lines, and characters."""

import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class TextStatsTool(Tool):
    """Count words, lines, and characters in a given text."""

    name = "text_stats"
    description = "Count the number of characters, words, and lines in a text."
    parameters_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to analyze.",
            },
        },
        "required": ["text"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        text = args.get("text", "")

        if not text:
            return ToolResult(tool_name=self.name, error="'text' is required.")

        try:
            chars = len(text)
            words = len(text.split())
            lines = len(text.splitlines())

            snippet = f"Characters: {chars}\nWords: {words}\nLines: {lines}"
            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path="text_stats", snippet=snippet)],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("TextStats error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Text stats calculation failed: {exc}",
            )
