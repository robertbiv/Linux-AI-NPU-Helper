# SPDX-License-Identifier: GPL-3.0-or-later
"""Command execution with mandatory user confirmation.

Safety model
------------
1. Every shell command extracted from an AI response is shown to the user
   before anything runs.
2. The user must explicitly type ``y`` / ``yes`` (or click Confirm in the UI)
   for each command.
3. A configurable blocklist of regex patterns prevents certain destructive
   commands from being executed at all, regardless of user confirmation.
4. Commands run in a short-lived subprocess that is reaped immediately;
   no process handles are kept open after the command finishes.

Resource efficiency
-------------------
- Subprocesses are created only when the user confirms — never speculatively.
- ``subprocess.run`` (blocking) is used so the subprocess is reaped before
  the function returns, leaving no zombie or orphan processes.
- The module holds no global state.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Callable

logger = logging.getLogger(__name__)

# Regex used to extract shell commands from an AI response.
# Matches both fenced code blocks (```shell ... ```) and lines starting with $
_CODE_FENCE_RE = re.compile(
    r"```(?:bash|sh|shell|zsh|console)?\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_DOLLAR_LINE_RE = re.compile(r"^\$\s+(.+)$", re.MULTILINE)


class CommandExecutor:
    """Extracts and safely executes shell commands from AI responses.

    Parameters
    ----------
    safety_config:
        The ``safety`` section from the application config.
    confirm_callback:
        A callable that receives a command string and returns ``True`` if the
        user approves execution, ``False`` otherwise.  Defaults to a
        terminal-based confirmation prompt.
    """

    def __init__(
        self,
        safety_config: dict,
        confirm_callback: Callable[[str], bool] | None = None,
    ) -> None:
        self._safety = safety_config
        self._confirm = confirm_callback or _terminal_confirm
        self._blocked_patterns: list[re.Pattern] = [
            re.compile(p) for p in safety_config.get("blocked_commands", [])
        ]

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_commands(self, text: str) -> list[str]:
        """Return all shell commands found in *text*.

        Searches for fenced code blocks first, then ``$``-prefixed lines.
        """
        commands: list[str] = []

        for match in _CODE_FENCE_RE.finditer(text):
            block = match.group(1).strip()
            # Each non-empty, non-comment line in the block is a candidate
            for line in block.splitlines():
                line = line.strip()
                # Strip leading $ if present
                if line.startswith("$ "):
                    line = line[2:]
                if line and not line.startswith("#"):
                    commands.append(line)

        # Fall back to $-prefixed lines when no fenced blocks are present
        if not commands:
            for match in _DOLLAR_LINE_RE.finditer(text):
                commands.append(match.group(1).strip())

        return commands

    def is_blocked(self, command: str) -> bool:
        """Return *True* if *command* matches a blocklist pattern."""
        for pattern in self._blocked_patterns:
            if pattern.search(command):
                logger.warning(
                    "Command blocked by safety pattern %r: %s",
                    pattern.pattern,
                    command,
                )
                return True
        return False

    def run_command(self, command: str) -> "CommandResult":
        """Ask for confirmation and run *command* if approved.

        Parameters
        ----------
        command:
            Raw shell command string.

        Returns
        -------
        CommandResult
            Contains the exit code, stdout, and stderr.  The subprocess is
            fully reaped before this method returns.
        """
        if self.is_blocked(command):
            return CommandResult(
                command=command,
                approved=False,
                blocked=True,
                returncode=-1,
                stdout="",
                stderr="Command blocked by safety policy.",
            )

        if self._safety.get("confirm_commands", True):
            approved = self._confirm(command)
            if not approved:
                logger.info("User declined command: %s", command)
                return CommandResult(
                    command=command,
                    approved=False,
                    blocked=False,
                    returncode=-1,
                    stdout="",
                    stderr="",
                )
        else:
            approved = True

        logger.info("Executing command: %s", command)
        try:
            # Use shell=True so the command string is interpreted by /bin/sh.
            # The process is reaped by subprocess.run before we return.
            result = subprocess.run(
                command,
                shell=True,  # noqa: S602
                capture_output=True,
                text=True,
                timeout=120,
            )
            logger.debug(
                "Command finished (rc=%d): %s", result.returncode, command
            )
            return CommandResult(
                command=command,
                approved=True,
                blocked=False,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except subprocess.TimeoutExpired:
            logger.error("Command timed out: %s", command)
            return CommandResult(
                command=command,
                approved=True,
                blocked=False,
                returncode=-1,
                stdout="",
                stderr="Command timed out after 120 seconds.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Command execution error: %s", exc)
            return CommandResult(
                command=command,
                approved=True,
                blocked=False,
                returncode=-1,
                stdout="",
                stderr=str(exc),
            )

    def process_response(self, ai_response: str) -> list["CommandResult"]:
        """Extract all commands from *ai_response* and execute them in order.

        Each command is confirmed individually before execution.
        """
        commands = self.extract_commands(ai_response)
        results: list[CommandResult] = []
        for cmd in commands:
            result = self.run_command(cmd)
            results.append(result)
            if result.returncode not in (0, -1) and result.approved:
                logger.warning(
                    "Command exited with non-zero status %d: %s",
                    result.returncode,
                    cmd,
                )
        return results


# ── Result dataclass ──────────────────────────────────────────────────────────

class CommandResult:
    """Outcome of a single command execution attempt."""

    __slots__ = (
        "command", "approved", "blocked",
        "returncode", "stdout", "stderr",
    )

    def __init__(
        self,
        command: str,
        approved: bool,
        blocked: bool,
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        self.command = command
        self.approved = approved
        self.blocked = blocked
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    @property
    def succeeded(self) -> bool:
        return self.approved and not self.blocked and self.returncode == 0

    def __repr__(self) -> str:
        return (
            f"CommandResult(command={self.command!r}, "
            f"approved={self.approved}, blocked={self.blocked}, "
            f"returncode={self.returncode})"
        )


# ── Terminal confirmation helper ──────────────────────────────────────────────

def _terminal_confirm(command: str) -> bool:
    """Ask the user on the terminal whether to run *command*.

    Returns ``True`` only if the user types ``y`` or ``yes``.
    """
    try:
        print(f"\n⚠  The AI wants to run the following command:\n\n  {command}\n")
        answer = input("Allow? [y/N] ").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False
