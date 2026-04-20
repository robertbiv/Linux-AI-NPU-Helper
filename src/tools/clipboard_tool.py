# SPDX-License-Identifier: GPL-3.0-or-later
"""Clipboard tool — read and write to the system clipboard."""

import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class ClipboardTool(Tool):
    """Read or write text to the system clipboard."""

    name = "clipboard"
    description = (
        "Read or write text to the system clipboard. "
        "Useful for grabbing text the user has copied or putting a command in the clipboard for them."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "write"],
                "description": "Whether to read from or write to the clipboard.",
            },
            "text": {
                "type": "string",
                "description": "The text to write (required if action is 'write').",
            },
        },
        "required": ["action"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = args.get("action", "").lower().strip()
        text = args.get("text", "")

        if action not in ("read", "write"):
            return ToolResult(
                tool_name=self.name, error="Action must be 'read' or 'write'."
            )

        if action == "write" and not args.get("text"):
            # Empty text is allowed if they explicitly want to clear it, but usually it's an error.
            # We'll allow it if 'text' is explicitly passed as empty string, but check if it's not present.
            if "text" not in args:
                return ToolResult(
                    tool_name=self.name, error="'text' is required for write action."
                )

        try:
            from PyQt5.QtWidgets import QApplication

            app = QApplication.instance()
            if not app:
                # If running headless without a Qt App instance, we can't use PyQt5 clipboard reliably.
                # Try fallback to xclip or wl-clipboard.
                return self._fallback_clipboard(action, text)

            clipboard = app.clipboard()

            if action == "read":
                content = clipboard.text()
                snippet = content if content else "(clipboard is empty)"
                return ToolResult(
                    tool_name=self.name,
                    results=[SearchResult(path="clipboard", snippet=snippet)],
                )

            # Write
            clipboard.setText(text)
            return ToolResult(
                tool_name=self.name,
                results=[
                    SearchResult(path="clipboard", snippet="Text written to clipboard.")
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Qt Clipboard failed, trying fallback: %s", exc)
            return self._fallback_clipboard(action, text)

    def _fallback_clipboard(self, action: str, text: str) -> ToolResult:
        """Fallback to xclip or wl-clipboard if Qt is not available."""
        import shutil
        import subprocess

        # Detect Wayland vs X11
        has_wl = bool(shutil.which("wl-copy"))
        has_xclip = bool(shutil.which("xclip"))

        if not has_wl and not has_xclip:
            return ToolResult(
                tool_name=self.name,
                error="Neither Qt, wl-clipboard, nor xclip are available to access the clipboard.",
            )

        try:
            if action == "read":
                if has_wl:
                    cmd = ["wl-paste"]
                else:
                    cmd = ["xclip", "-selection", "clipboard", "-o"]

                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if proc.returncode != 0:
                    return ToolResult(
                        tool_name=self.name,
                        error=f"Failed to read clipboard: {proc.stderr}",
                    )
                content = proc.stdout
                snippet = content if content else "(clipboard is empty)"
                return ToolResult(
                    tool_name=self.name,
                    results=[SearchResult(path="clipboard", snippet=snippet)],
                )
            else:
                if has_wl:
                    cmd = ["wl-copy"]
                else:
                    cmd = ["xclip", "-selection", "clipboard", "-i"]

                proc = subprocess.run(
                    cmd, input=text, capture_output=True, text=True, timeout=5
                )
                if proc.returncode != 0:
                    return ToolResult(
                        tool_name=self.name,
                        error=f"Failed to write clipboard: {proc.stderr}",
                    )
                return ToolResult(
                    tool_name=self.name,
                    results=[
                        SearchResult(
                            path="clipboard", snippet="Text written to clipboard."
                        )
                    ],
                )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name=self.name,
                error=f"Clipboard operation failed: {exc}",
            )
