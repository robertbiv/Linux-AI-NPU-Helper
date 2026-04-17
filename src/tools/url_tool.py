# SPDX-License-Identifier: GPL-3.0-or-later
"""URL tool — encode or decode URL text."""

import logging
import urllib.parse
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class URLEncoderTool(Tool):
    """Encode or decode URL components."""

    name = "url_encode"
    description = "URL encode or decode a string locally."
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["encode", "decode"],
                "description": "Whether to encode or decode the URL string.",
            },
            "text": {
                "type": "string",
                "description": "The string to process.",
            },
        },
        "required": ["action", "text"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = args.get("action", "").lower().strip()
        text = args.get("text", "")

        if action not in ("encode", "decode"):
            return ToolResult(
                tool_name=self.name, error="Action must be 'encode' or 'decode'."
            )

        if not text:
            return ToolResult(tool_name=self.name, error="'text' is required.")

        try:
            if action == "encode":
                # Use quote_plus to handle spaces as '+'
                result_text = urllib.parse.quote_plus(text)
            else:
                result_text = urllib.parse.unquote_plus(text)

            snippet = result_text
            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path=f"url:{action}", snippet=snippet)],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("URLEncoder error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"URL {action} failed: {exc}",
            )
