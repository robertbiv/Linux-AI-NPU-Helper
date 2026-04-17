# SPDX-License-Identifier: GPL-3.0-or-later
"""QR code tool — generate text-based QR codes."""

import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)

class QRCodeTool(Tool):
    """Generate ASCII QR codes from text."""

    name = "qrcode"
    description = "Generate a text-based ASCII QR code from a string."
    parameters_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to encode in a QR code.",
            },
        },
        "required": ["text"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        text = args.get("text", "")
        if not text:
            return ToolResult(tool_name=self.name, error="'text' is required.")

        try:
            import qrcode
            qr = qrcode.QRCode(border=2)
            qr.add_data(text)
            qr.make(fit=True)

            import io
            f = io.StringIO()
            qr.print_ascii(out=f)
            result = f.getvalue()

            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path="qrcode", snippet=result)]
            )
        except ImportError:
            return ToolResult(tool_name=self.name, error="qrcode library not installed.")
        except Exception as exc:
            return ToolResult(tool_name=self.name, error=f"QR generation failed: {exc}")
