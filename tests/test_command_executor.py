"""Tests for src/command_executor.py."""

from __future__ import annotations
from unittest.mock import patch
from src.command_executor import CommandExecutor, CommandResult, CommandOutput


_SAFETY = {
    "confirm_commands": False,  # auto-approve in tests
    "blocked_commands": [
        r"rm\s+-rf\s+/",
        r"mkfs",
        r"dd\s+.*of=/dev/",
    ],
}


class TestExtractCommands:
    def test_fenced_bash_block(self):
        text = "```bash\nls -la\n```"
        cmds = CommandExecutor(_SAFETY).extract_commands(text)
        assert cmds == ["ls -la"]

    def test_fenced_sh_block(self):
        text = "```sh\npwd\n```"
        cmds = CommandExecutor(_SAFETY).extract_commands(text)
        assert cmds == ["pwd"]

    def test_multiple_commands_in_block(self):
        text = "```bash\ncd /tmp\nls\n```"
        cmds = CommandExecutor(_SAFETY).extract_commands(text)
        assert "cd /tmp" in cmds
        assert "ls" in cmds

    def test_dollar_prefix_fallback(self):
        text = "Run:\n$ echo hello\n$ pwd"
        cmds = CommandExecutor(_SAFETY).extract_commands(text)
        assert "echo hello" in cmds
        assert "pwd" in cmds

    def test_comments_excluded(self):
        text = "```bash\n# this is a comment\nls\n```"
        cmds = CommandExecutor(_SAFETY).extract_commands(text)
        assert "# this is a comment" not in cmds
        assert "ls" in cmds

    def test_no_commands(self):
        cmds = CommandExecutor(_SAFETY).extract_commands("Just a normal sentence.")
        assert cmds == []

    def test_dollar_prefix_stripped(self):
        text = "```bash\n$ ls -la\n```"
        cmds = CommandExecutor(_SAFETY).extract_commands(text)
        assert "ls -la" in cmds


class TestIsBlocked:
    def test_rm_rf_blocked(self):
        ex = CommandExecutor(_SAFETY)
        assert ex.is_blocked("rm -rf /") is True

    def test_mkfs_blocked(self):
        ex = CommandExecutor(_SAFETY)
        assert ex.is_blocked("mkfs.ext4 /dev/sda") is True

    def test_dd_blocked(self):
        ex = CommandExecutor(_SAFETY)
        assert ex.is_blocked("dd if=/dev/zero of=/dev/sda") is True

    def test_safe_command_not_blocked(self):
        ex = CommandExecutor(_SAFETY)
        assert ex.is_blocked("ls -la") is False

    def test_echo_not_blocked(self):
        ex = CommandExecutor(_SAFETY)
        assert ex.is_blocked("echo hello") is False


class TestRunCommand:
    def test_blocked_command_not_executed(self):
        ex = CommandExecutor(_SAFETY)
        result = ex.run_command("rm -rf /")
        assert result.blocked is True
        assert result.approved is False

    def test_successful_command(self):
        import subprocess as _sp

        ex = CommandExecutor(_SAFETY)
        with patch.object(
            ex,
            "_execute_pipeline",
            return_value=_sp.CompletedProcess(
                args="echo ok", returncode=0, stdout="ok\n", stderr=""
            ),
        ):
            result = ex.run_command("echo ok")
        assert result.approved is True
        assert result.blocked is False
        assert result.returncode == 0
        assert result.stdout == "ok\n"

    def test_command_requiring_confirm_denied(self):
        safety = {**_SAFETY, "confirm_commands": True}
        ex = CommandExecutor(safety, confirm_callback=lambda cmd: False)
        result = ex.run_command("ls")
        assert result.approved is False

    def test_command_requiring_confirm_approved(self):
        import subprocess as _sp

        safety = {**_SAFETY, "confirm_commands": True}
        ex = CommandExecutor(safety, confirm_callback=lambda cmd: True)
        with patch.object(
            ex,
            "_execute_pipeline",
            return_value=_sp.CompletedProcess(
                args="ls", returncode=0, stdout="", stderr=""
            ),
        ):
            result = ex.run_command("ls")
        assert result.approved is True

    def test_timeout(self):
        import subprocess

        ex = CommandExecutor(_SAFETY)
        with patch.object(
            ex, "_execute_pipeline", side_effect=subprocess.TimeoutExpired("ls", 120)
        ):
            result = ex.run_command("ls")
        assert result.returncode == -1
        assert "timed out" in result.stderr.lower()

    def test_succeeded_property(self):
        r = CommandResult(
            "ls",
            approved=True,
            blocked=False,
            output=CommandOutput(returncode=0, stdout="", stderr=""),
        )
        assert r.succeeded is True

    def test_not_succeeded_when_blocked(self):
        r = CommandResult(
            "rm -rf /",
            approved=False,
            blocked=True,
            output=CommandOutput(returncode=-1, stdout="", stderr=""),
        )
        assert r.succeeded is False


class TestProcessResponse:
    def test_processes_all_commands(self):
        ex = CommandExecutor(_SAFETY)
        called = []
        with patch.object(
            ex,
            "run_command",
            side_effect=lambda cmd: (
                called.append(cmd)
                or CommandResult(cmd, True, False, CommandOutput(0, "", ""))
            ),
        ):
            ex.process_response("```bash\nls\npwd\n```")
        assert "ls" in called
        assert "pwd" in called
