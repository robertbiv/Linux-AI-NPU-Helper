# SPDX-License-Identifier: GPL-3.0-or-later
"""Diff tool — compare two strings and output a unified diff."""

import difflib
import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class DiffTool(Tool):
    """Compare two text strings and generate a unified diff locally."""

    name = "diff_text"
    description = "Compare two text strings and output a standard unified diff to see what changed."
    parameters_schema = {
        "type": "object",
        "properties": {
            "text_a": {
                "type": "string",
                "description": "The original or left-hand text.",
            },
            "text_b": {
                "type": "string",
                "description": "The modified or right-hand text.",
            },
        },
        "required": ["text_a", "text_b"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        text_a = args.get("text_a", "")
        text_b = args.get("text_b", "")

        try:
            lines_a = text_a.splitlines(keepends=True)
            lines_b = text_b.splitlines(keepends=True)

            diff = list(
                difflib.unified_diff(
                    lines_a, lines_b, fromfile="original", tofile="modified", n=3
                )
            )

            if not diff:
                snippet = "Texts are identical."
            else:
                snippet = "".join(diff)

            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path="diff", snippet=snippet)],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("DiffTool error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Diff generation failed: {exc}",
            )
