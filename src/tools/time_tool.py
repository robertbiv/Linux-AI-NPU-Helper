# SPDX-License-Identifier: GPL-3.0-or-later
"""Time tool — get current time and convert timestamps."""

import datetime
import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class TimeTool(Tool):
    """Get current time and format timestamps."""

    name = "time_tool"
    description = "Get the current local or UTC time, or convert a Unix timestamp to human-readable format."
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["current", "convert"],
                "description": "'current' to get the current time, 'convert' to parse a Unix timestamp.",
            },
            "timestamp": {
                "type": "number",
                "description": "The Unix timestamp to convert (required if action is 'convert').",
            },
            "timezone": {
                "type": "string",
                "enum": ["local", "utc"],
                "description": "Whether to return 'local' or 'utc' time (default 'local').",
                "default": "local",
            },
        },
        "required": ["action"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = args.get("action", "").lower().strip()
        tz = args.get("timezone", "local").lower().strip()

        if action not in ("current", "convert"):
            return ToolResult(
                tool_name=self.name, error="Action must be 'current' or 'convert'."
            )

        try:
            if action == "current":
                if tz == "utc":
                    dt = datetime.datetime.now(datetime.timezone.utc)
                    tz_str = "UTC"
                else:
                    dt = datetime.datetime.now()
                    tz_str = "Local"

                snippet = f"Current {tz_str} Time: {dt.strftime('%Y-%m-%d %H:%M:%S %Z').strip()}\nISO: {dt.isoformat()}"
            else:
                ts = args.get("timestamp")
                if ts is None:
                    return ToolResult(
                        tool_name=self.name,
                        error="'timestamp' is required for the 'convert' action.",
                    )

                ts_float = float(ts)
                if tz == "utc":
                    dt = datetime.datetime.fromtimestamp(ts_float, datetime.timezone.utc)
                    tz_str = "UTC"
                else:
                    dt = datetime.datetime.fromtimestamp(ts_float)
                    tz_str = "Local"

                snippet = f"Timestamp {ts} -> {tz_str}: {dt.strftime('%Y-%m-%d %H:%M:%S %Z').strip()}"

            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path=f"time:{action}", snippet=snippet)],
            )
        except (ValueError, TypeError) as exc:
            return ToolResult(
                tool_name=self.name,
                error=f"Invalid timestamp or input: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("TimeTool error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Time calculation failed: {exc}",
            )
