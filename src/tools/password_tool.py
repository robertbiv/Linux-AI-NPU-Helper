# SPDX-License-Identifier: GPL-3.0-or-later
"""Password tool — locally generate secure random passwords."""

import logging
import secrets
import string
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class PasswordGeneratorTool(Tool):
    """Generate a secure random password locally."""

    name = "generate_password"
    description = (
        "Generate a cryptographically secure random password locally. "
        "Does not upload or send the password anywhere."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "length": {
                "type": "integer",
                "description": "Length of the password (default 16, max 128).",
                "default": 16,
            },
            "include_symbols": {
                "type": "boolean",
                "description": "Include special characters like !@#$ (default true).",
                "default": True,
            },
        },
        "required": [],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            length = int(args.get("length", 16))
        except (ValueError, TypeError):
            length = 16

        length = max(4, min(128, length))

        include_symbols = bool(args.get("include_symbols", True))

        alphabet = string.ascii_letters + string.digits
        if include_symbols:
            alphabet += "!@#$%^&*()-_=+[]{}|;:,.<>?"

        password = "".join(secrets.choice(alphabet) for _ in range(length))

        # Ensure it contains at least one of each required type if symbols are included
        if include_symbols and length >= 4:
            while True:
                if (
                    any(c.islower() for c in password)
                    and any(c.isupper() for c in password)
                    and any(c.isdigit() for c in password)
                    and any(c in "!@#$%^&*()-_=+[]{}|;:,.<>?" for c in password)
                ):
                    break
                password = "".join(secrets.choice(alphabet) for _ in range(length))

        snippet = f"Generated password ({length} chars): {password}"
        return ToolResult(
            tool_name=self.name,
            results=[SearchResult(path="password_generator", snippet=snippet)],
        )
