# SPDX-License-Identifier: GPL-3.0-or-later
"""Encoding tool — convert text to/from hex and binary."""

import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class EncodingTool(Tool):
    """Encode or decode text to Hex or Binary."""

    name = "encoding"
    description = "Convert text to/from Hexadecimal or Binary."
    parameters_schema = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["hex", "binary"],
                "description": "The target format.",
            },
            "action": {
                "type": "string",
                "enum": ["encode", "decode"],
                "description": "Encode text to format, or decode format to text.",
            },
            "text": {
                "type": "string",
                "description": "The text to encode or decode.",
            },
        },
        "required": ["format", "action", "text"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        fmt = args.get("format", "").lower().strip()
        action = args.get("action", "").lower().strip()
        text = args.get("text", "")

        if fmt not in ("hex", "binary"):
            return ToolResult(
                tool_name=self.name, error="Format must be 'hex' or 'binary'."
            )
        if action not in ("encode", "decode"):
            return ToolResult(
                tool_name=self.name, error="Action must be 'encode' or 'decode'."
            )
        if not text:
            return ToolResult(tool_name=self.name, error="'text' is required.")

        try:
            if fmt == "hex":
                if action == "encode":
                    result = text.encode("utf-8").hex()
                else:
                    # Strip spaces if user provided formatted hex
                    clean_hex = text.replace(" ", "").replace("\n", "")
                    result = bytes.fromhex(clean_hex).decode("utf-8")
            else:  # binary
                if action == "encode":
                    result = " ".join(format(b, "08b") for b in text.encode("utf-8"))
                else:
                    clean_bin = text.replace(" ", "").replace("\n", "")
                    if len(clean_bin) % 8 != 0:
                        return ToolResult(
                            tool_name=self.name,
                            error="Binary text length must be a multiple of 8.",
                        )
                    byte_vals = [
                        int(clean_bin[i : i + 8], 2)
                        for i in range(0, len(clean_bin), 8)
                    ]
                    result = bytes(byte_vals).decode("utf-8")

            snippet = f"{action.capitalize()}d {fmt}:\n{result}"
            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path=f"encode:{fmt}", snippet=snippet)],
            )
        except ValueError as exc:
            logger.debug("Encoding error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Invalid input data for decoding: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Encoding error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Encoding operation failed: {exc}",
            )
