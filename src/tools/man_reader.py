# SPDX-License-Identifier: GPL-3.0-or-later
"""Man page reader tool — read Linux manual pages."""

from __future__ import annotations

import logging
import re
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)

# ANSI escape sequences (colour codes, cursor moves, etc.)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# Backspace-based bold/underline: "c\bc" → "c",  "_\bc" → "c"
_BACKSPACE_RE = re.compile(r".\x08")
# Section headers in man pages: an all-caps word at the start of a line,
# optionally followed by more words.  Examples: "OPTIONS", "RETURN VALUE".
_SECTION_HEADER_RE = re.compile(r"^([A-Z][A-Z0-9 _-]+)$", re.MULTILINE)

# Man-page sections the AI most benefits from when crafting commands
_USEFUL_SECTIONS = ("SYNOPSIS", "OPTIONS", "DESCRIPTION", "EXAMPLES", "NOTES")

# Hard cap: no matter what the user configures, never return more than this
# many characters from a single man page to avoid context overflow.
_ABSOLUTE_MAX_CHARS = 32_000


def _strip_man_formatting(text: str) -> str:
    """Remove ANSI codes and backspace-based bold/underline from man output."""
    text = _ANSI_RE.sub("", text)
    text = _BACKSPACE_RE.sub("", text)
    return text


def _extract_sections(text: str, sections: list[str]) -> str:
    """Extract named sections from plain-text man page output.

    Each section begins at a header line (all-caps) and ends at the next
    header line.  Returns only the requested sections concatenated together.
    If *sections* is empty all text is returned.
    """
    if not sections:
        return text

    wanted = {s.upper() for s in sections}
    result_parts: list[str] = []
    current_header: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        if current_header in wanted and current_lines:
            result_parts.append(current_header)
            result_parts.extend(current_lines)

    for line in text.splitlines():
        header_match = _SECTION_HEADER_RE.match(line.rstrip())
        if header_match:
            _flush()
            current_header = header_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    _flush()
    return "\n".join(result_parts)


class ManPageTool(Tool):
    """Read the Linux manual page for a command.

    The tool runs ``man <command>`` locally with plain-text output (no pager,
    no ANSI codes), optionally extracts specific sections, and truncates the
    result to keep it within the model's context window.

    This lets the AI look up the exact flags, syntax, and examples for any
    installed command before crafting a shell instruction — ensuring accuracy
    especially across distros where option names differ.

    The tool is entirely offline: it reads man pages from the local system
    and never contacts any network resource.

    Args:
        max_chars: Maximum characters returned per call.  Defaults to 8 000, which is
            enough for SYNOPSIS + OPTIONS of most commands.
        default_sections: Section names to extract when the caller doesn't specify any.  Use
            ``[]`` to return the full man page (up to *max_chars*).
    """

    name = "read_man_page"
    description = (
        "Read the local manual page for a command so you can craft an accurate "
        "command with the correct flags and syntax for this system. "
        "Offline — reads from the local man database only."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The command to look up, e.g. 'find', 'tar', 'systemctl'.",
            },
            "sections": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of man-page section names to extract, e.g. "
                    "['SYNOPSIS', 'OPTIONS', 'EXAMPLES']. "
                    "Omit or pass [] to use the configured default sections."
                ),
            },
            "man_section": {
                "type": "string",
                "description": (
                    "Optional manual section number, e.g. '1' (user commands), "
                    "'5' (file formats), '8' (admin commands). "
                    "Leave empty to let man choose."
                ),
            },
        },
        "required": ["command"],
    }

    def __init__(
        self,
        max_chars: int = 8_000,
        default_sections: list[str] | None = None,
    ) -> None:
        self._max_chars = min(max_chars, _ABSOLUTE_MAX_CHARS)
        self._default_sections: list[str] = (
            default_sections if default_sections is not None else list(_USEFUL_SECTIONS)
        )

    def run(self, args: dict[str, Any]) -> ToolResult:
        command: str = args.get("command", "").strip()
        if not command:
            return ToolResult(tool_name=self.name, error="'command' is required.")

        # Basic safety: reject anything that isn't a plain command name
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", command):
            return ToolResult(
                tool_name=self.name,
                error=f"Invalid command name: {command!r}. "
                "Only alphanumeric characters, hyphens, underscores, and dots are allowed.",
            )

        man_section: str = args.get("man_section", "").strip()
        requested_sections: list[str] = args.get("sections") or []
        extract_sections = requested_sections or self._default_sections

        # Check man is available (lazy import shutil — only on first run)
        import shutil  # lazy

        if not shutil.which("man"):
            return ToolResult(
                tool_name=self.name,
                error="'man' is not installed on this system.",
            )

        cmd = ["man"]
        if man_section:
            cmd.append(man_section)
        cmd.append(command)

        import os  # lazy
        import subprocess  # lazy

        env = os.environ.copy()
        env["MANPAGER"] = "cat"
        env["MANWIDTH"] = "100"
        env["GROFF_NO_SGR"] = "1"
        env.pop("LESS", None)
        env.pop("MORE", None)

        logger.info("ManPageTool: reading man page for %r", command)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name=self.name,
                error=f"man page lookup for '{command}' timed out.",
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(tool_name=self.name, error=str(exc))

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            return ToolResult(
                tool_name=self.name,
                error=f"No man page found for '{command}'"
                + (f": {stderr}" if stderr else "."),
            )

        raw = _strip_man_formatting(proc.stdout)
        text = _extract_sections(raw, extract_sections) if extract_sections else raw

        # If section extraction yielded nothing, fall back to the full page
        if not text.strip() and extract_sections:
            logger.debug(
                "ManPageTool: requested sections %s not found; returning full page.",
                extract_sections,
            )
            text = raw

        truncated = len(text) > self._max_chars
        text = text[: self._max_chars]

        if not text.strip():
            return ToolResult(
                tool_name=self.name,
                error=f"man page for '{command}' is empty.",
            )

        return ToolResult(
            tool_name=self.name,
            results=[
                SearchResult(
                    path=f"man:{command}",
                    snippet=text,
                )
            ],
            truncated=truncated,
        )

    def schema_text(self) -> str:
        return (
            f"  {self.name}(command: string, sections?: string[], "
            f"man_section?: string) — {self.description}"
        )
