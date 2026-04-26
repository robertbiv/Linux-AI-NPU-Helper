# SPDX-License-Identifier: GPL-3.0-or-later
"""Command execution with mandatory user confirmation.

## Safety model
1. Every shell command extracted from an AI response is shown to the user
   before anything runs.
2. The user must explicitly type ``y`` / ``yes`` (or click Confirm in the UI)
   for each command.
3. A configurable blocklist of regex patterns prevents certain destructive
   commands from being executed at all, regardless of user confirmation.
4. Commands run in a short-lived subprocess that is reaped immediately;
   no process handles are kept open after the command finishes.

## Resource efficiency
- Subprocesses are created only when the user confirms — never speculatively.
- ``subprocess.run`` (blocking) is used so the subprocess is reaped before
  the function returns, leaving no zombie or orphan processes.
- The module holds no global state.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
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

    Args:
        safety_config: The ``safety`` section from the application config.
        confirm_callback: A callable that receives a command string and returns ``True`` if the
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

        Args:
            command: Raw shell command string.

        Returns:
            Contains the exit code, stdout, and stderr.  The subprocess is
            fully reaped before this method returns.
        """
        if self.is_blocked(command):
            return CommandResult(
                command=command,
                approved=False,
                blocked=True,
                output=CommandOutput(
                    returncode=-1, stdout="", stderr="Command blocked by safety policy."
                ),
            )

        if self._safety.get("confirm_commands", True):
            approved = self._confirm(command)
            if not approved:
                logger.info("User declined command: %s", command)
                return CommandResult(
                    command=command,
                    approved=False,
                    blocked=False,
                    output=CommandOutput(returncode=-1, stdout="", stderr=""),
                )
        else:
            approved = True

        logger.info("Executing command: %s", command)
        try:
            result = self._execute_pipeline(command, timeout=120)
            logger.debug("Command finished (rc=%d): %s", result.returncode, command)
            return CommandResult(
                command=command,
                approved=True,
                blocked=False,
                output=CommandOutput(
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                ),
            )
        except subprocess.TimeoutExpired:
            logger.error("Command timed out: %s", command)
            return CommandResult(
                command=command,
                approved=True,
                blocked=False,
                output=CommandOutput(
                    returncode=-1,
                    stdout="",
                    stderr="Command timed out after 120 seconds.",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Command execution error: %s", exc)
            return CommandResult(
                command=command,
                approved=True,
                blocked=False,
                output=CommandOutput(returncode=-1, stdout="", stderr=str(exc)),
            )

    def _execute_pipeline(
        self, command_str: str, timeout: int = 120
    ) -> subprocess.CompletedProcess:
        """Execute a shell pipeline safely without shell=True."""
        import shlex

        try:
            tokens = shlex.split(command_str)
        except ValueError as e:
            raise ValueError(f"Failed to parse command: {e}") from e

        if not tokens:
            raise ValueError("Empty command")

        pipelines = []
        current_cmd = []
        in_file = None
        out_file = None
        append_out = False

        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t == "|":
                if not current_cmd:
                    raise ValueError("Syntax error: unexpected '|'")
                pipelines.append(
                    {
                        "args": current_cmd,
                        "in": in_file,
                        "out": out_file,
                        "append": append_out,
                    }
                )
                current_cmd = []
                in_file = None
                out_file = None
                append_out = False
            elif t == ">":
                if i + 1 >= len(tokens):
                    raise ValueError("Syntax error: expected file after '>'")
                out_file = tokens[i + 1]
                append_out = False
                i += 1
            elif t == ">>":
                if i + 1 >= len(tokens):
                    raise ValueError("Syntax error: expected file after '>>'")
                out_file = tokens[i + 1]
                append_out = True
                i += 1
            elif t == "<":
                if i + 1 >= len(tokens):
                    raise ValueError("Syntax error: expected file after '<'")
                in_file = tokens[i + 1]
                i += 1
            elif t in ("&&", "||", ";"):
                raise ValueError(
                    f"Shell operator '{t}' is not supported for security reasons."
                )
            else:
                current_cmd.append(t)
            i += 1

        if current_cmd:
            pipelines.append(
                {
                    "args": current_cmd,
                    "in": in_file,
                    "out": out_file,
                    "append": append_out,
                }
            )
        elif pipelines:
            raise ValueError("Syntax error: unexpected end of command after '|'")

        processes = []
        opened_files = []
        prev_stdout = None

        import tempfile
        import os

        try:
            for idx, step in enumerate(pipelines):
                is_first = idx == 0
                is_last = idx == len(pipelines) - 1

                cmd_args = step["args"]
                stdin_f = step["in"]
                stdout_f = step["out"]
                append = step["append"]

                if stdin_f:
                    if not is_first:
                        raise ValueError(
                            "Input redirection '<' is only supported for the first command in a pipeline."
                        )
                    f = open(stdin_f, "r")  # noqa: SIM115
                    opened_files.append(f)
                    stdin_dest = f
                else:
                    stdin_dest = prev_stdout

                if stdout_f:
                    mode = "a" if append else "w"
                    f = open(stdout_f, mode)  # noqa: SIM115
                    opened_files.append(f)
                    stdout_dest = f
                elif not is_last:
                    stdout_dest = subprocess.PIPE
                else:
                    stdout_dest = subprocess.PIPE

                # Use a temporary file for stderr of all processes to prevent pipe deadlocks
                # and allow us to gather all errors at the end.
                fd, stderr_path = tempfile.mkstemp(prefix="ai_cmd_stderr_")
                stderr_f = os.fdopen(fd, "w+")
                opened_files.append(stderr_f)

                try:
                    p = subprocess.Popen(
                        cmd_args,
                        stdin=stdin_dest,
                        stdout=stdout_dest,
                        stderr=stderr_f,
                        text=True,
                    )
                except FileNotFoundError as e:
                    raise ValueError(f"Command not found: {cmd_args[0]}") from e

                if prev_stdout:
                    prev_stdout.close()

                if not is_last and not stdout_f:
                    prev_stdout = p.stdout

                # Store the process and its stderr file
                processes.append((p, stderr_f, stderr_path))

            # Wait for the last process to finish and read its stdout
            last_p, _, _ = processes[-1]
            out, _ = last_p.communicate(timeout=timeout)
            returncode = last_p.returncode

            # Gather all stderr outputs from all processes
            all_stderr = []
            for p, stderr_f, stderr_path in processes:
                # Ensure the process is dead
                if p.poll() is None:
                    try:
                        p.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        p.kill()
                # Read the temp file
                stderr_f.seek(0)
                err_content = stderr_f.read().strip()
                if err_content:
                    all_stderr.append(err_content)
                # We'll close and remove the file in the finally block

            final_err = "\n".join(all_stderr)

            return subprocess.CompletedProcess(
                args=command_str,
                returncode=returncode,
                stdout=out or "",
                stderr=final_err,
            )

        finally:
            for item in processes:
                p = item[0] if isinstance(item, tuple) else item
                if p.poll() is None:
                    p.kill()
            for f in opened_files:
                try:
                    f.close()
                    if hasattr(f, "name") and "ai_cmd_stderr_" in f.name:
                        import os

                        if os.path.exists(f.name):
                            os.remove(f.name)
                except Exception:
                    pass

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


@dataclass(slots=True)
class CommandOutput:
    """Standard output streams and return code from a process."""

    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class CommandResult:
    """Outcome of a single command execution attempt."""

    command: str
    approved: bool
    blocked: bool
    output: CommandOutput | None = None

    @property
    def returncode(self) -> int:
        return self.output.returncode if self.output else -1

    @property
    def stdout(self) -> str:
        return self.output.stdout if self.output else ""

    @property
    def stderr(self) -> str:
        return self.output.stderr if self.output else ""

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
