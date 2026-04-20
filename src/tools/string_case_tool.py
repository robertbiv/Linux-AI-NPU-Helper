# SPDX-License-Identifier: GPL-3.0-or-later
"""String case tool — convert text between different naming conventions."""

import re
import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class StringCaseTool(Tool):
    """Convert text between different string case styles."""

    name = "string_case"
    description = "Convert strings to camelCase, snake_case, PascalCase, kebab-case, or CONSTANT_CASE."
    parameters_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to convert.",
            },
            "to_case": {
                "type": "string",
                "enum": ["camel", "snake", "pascal", "kebab", "constant"],
                "description": "The target case style.",
            },
        },
        "required": ["text", "to_case"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        text = args.get("text", "")
        to_case = args.get("to_case", "").lower()

        if not text:
            return ToolResult(tool_name=self.name, error="'text' is required.")

        if to_case not in ("camel", "snake", "pascal", "kebab", "constant"):
            return ToolResult(tool_name=self.name, error="Invalid target case.")

        try:
            # Normalize to words
            # First split by non-alphanumeric
            words = re.split(r"[^a-zA-Z0-9]+", text)
            # Then handle existing camelCase/PascalCase
            processed_words = []
            for w in words:
                if w:
                    split_camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", w).split()
                    processed_words.extend(split_camel)

            words = [w.lower() for w in processed_words if w]

            if not words:
                return ToolResult(
                    tool_name=self.name, error="No alphanumeric characters found."
                )

            if to_case == "camel":
                result = words[0] + "".join(w.capitalize() for w in words[1:])
            elif to_case == "pascal":
                result = "".join(w.capitalize() for w in words)
            elif to_case == "snake":
                result = "_".join(words)
            elif to_case == "kebab":
                result = "-".join(words)
            elif to_case == "constant":
                result = "_".join(w.upper() for w in words)
            else:
                result = ""

            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path=f"case:{to_case}", snippet=result)],
            )
        except Exception as exc:
            logger.debug("String case conversion error: %s", exc)
            return ToolResult(tool_name=self.name, error=f"Conversion failed: {exc}")
