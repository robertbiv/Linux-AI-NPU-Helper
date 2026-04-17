# SPDX-License-Identifier: GPL-3.0-or-later
"""Format converter tool — convert between JSON and YAML."""

import json
import logging
import yaml
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)

class FormatConverterTool(Tool):
    """Convert text between JSON and YAML."""

    name = "format_converter"
    description = "Convert structured data between JSON and YAML formats."
    parameters_schema = {
        "type": "object",
        "properties": {
            "source_format": {
                "type": "string",
                "enum": ["json", "yaml"],
                "description": "The format of the input text.",
            },
            "target_format": {
                "type": "string",
                "enum": ["json", "yaml"],
                "description": "The format to convert to.",
            },
            "text": {
                "type": "string",
                "description": "The input text to convert.",
            },
        },
        "required": ["source_format", "target_format", "text"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        src = args.get("source_format", "").lower()
        tgt = args.get("target_format", "").lower()
        text = args.get("text", "")

        if src not in ("json", "yaml") or tgt not in ("json", "yaml"):
            return ToolResult(tool_name=self.name, error="Formats must be 'json' or 'yaml'.")

        if not text:
            return ToolResult(tool_name=self.name, error="'text' is required.")

        try:
            # Parse
            if src == "json":
                data = json.loads(text)
            else:
                data = yaml.safe_load(text)

            # Serialize
            if tgt == "json":
                result = json.dumps(data, indent=4)
            else:
                result = yaml.dump(data, default_flow_style=False, sort_keys=False)

            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path=f"convert:{src}_to_{tgt}", snippet=result)]
            )
        except Exception as exc:
            logger.debug("Format conversion error: %s", exc)
            return ToolResult(tool_name=self.name, error=f"Conversion failed: {exc}")
