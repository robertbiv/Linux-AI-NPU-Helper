# SPDX-License-Identifier: GPL-3.0-or-later
"""Regex tool — regular expression search and replace."""

import logging
import re
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class RegexTool(Tool):
    """Evaluate regular expressions locally."""

    name = "regex"
    description = (
        "Test regular expression matches or perform search/replace on text locally."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "replace"],
                "description": "Whether to 'search' for matches or 'replace' text.",
            },
            "pattern": {
                "type": "string",
                "description": "The regular expression pattern.",
            },
            "text": {
                "type": "string",
                "description": "The text to evaluate against.",
            },
            "replacement": {
                "type": "string",
                "description": "The replacement string (required if action is 'replace').",
            },
        },
        "required": ["action", "pattern", "text"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = args.get("action", "").lower().strip()
        pattern = args.get("pattern", "")
        text = args.get("text", "")
        replacement = args.get("replacement", "")

        if action not in ("search", "replace"):
            return ToolResult(
                tool_name=self.name, error="Action must be 'search' or 'replace'."
            )

        if not pattern:
            return ToolResult(tool_name=self.name, error="'pattern' is required.")
        if not text:
            return ToolResult(tool_name=self.name, error="'text' is required.")

        try:
            compiled = re.compile(pattern)

            if action == "search":
                matches = compiled.findall(text)
                if not matches:
                    snippet = "No matches found."
                else:
                    snippet = f"Found {len(matches)} matches:\n" + "\n".join(
                        str(m) for m in matches[:50]
                    )
                    if len(matches) > 50:
                        snippet += "\n... (truncated)"
            else:
                if "replacement" not in args:
                    return ToolResult(
                        tool_name=self.name,
                        error="'replacement' is required for the 'replace' action.",
                    )
                result_text = compiled.sub(replacement, text)
                snippet = f"Replaced text:\n{result_text}"

            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path=f"regex:{action}", snippet=snippet)],
            )
        except re.error as exc:
            logger.debug("Regex compile error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Invalid regular expression: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Regex error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Regex operation failed: {exc}",
            )
