# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON tool — format or minify JSON text."""

import json
import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class JSONTool(Tool):
    """Format or minify JSON text."""

    name = "json_format"
    description = "Format (pretty-print) or minify JSON text locally."
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["format", "minify"],
                "description": "Whether to format (pretty-print) or minify the JSON.",
            },
            "text": {
                "type": "string",
                "description": "The JSON text to process.",
            },
        },
        "required": ["action", "text"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = args.get("action", "").lower().strip()
        text = args.get("text", "")

        if action not in ("format", "minify"):
            return ToolResult(
                tool_name=self.name, error="Action must be 'format' or 'minify'."
            )

        if not text:
            return ToolResult(tool_name=self.name, error="'text' is required.")

        try:
            parsed = json.loads(text)

            if action == "format":
                result_text = json.dumps(parsed, indent=4, sort_keys=False)
            else:
                result_text = json.dumps(parsed, separators=(",", ":"), sort_keys=False)

            snippet = result_text
            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path=f"json:{action}", snippet=snippet)],
            )
        except json.JSONDecodeError as exc:
            logger.debug("JSON decode error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Invalid JSON provided: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("JSONTool error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"JSON {action} failed: {exc}",
            )
