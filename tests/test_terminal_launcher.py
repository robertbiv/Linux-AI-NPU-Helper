"""Tests for src/terminal_launcher.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.terminal_launcher import (
    _build_launch_cmd,
    _find_terminal,
    _pick_script,
    open_with_command,
)


class TestTerminalLauncherHelpers:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _find_terminal.cache_clear()
        yield
        _find_terminal.cache_clear()

    @patch("shutil.which")
    def test_find_terminal(self, mock_which):
        # Test finding a terminal
        mock_which.side_effect = lambda x: "/usr/bin/gnome-terminal" if x == "gnome-terminal" else None

        result = _find_terminal()
        assert result == ("/usr/bin/gnome-terminal", "dashdash")

        # Test caching
        mock_which.reset_mock()
        result2 = _find_terminal()
        assert result2 == ("/usr/bin/gnome-terminal", "dashdash")
        mock_which.assert_not_called()

        _find_terminal.cache_clear()

        # Test finding no terminal
        mock_which.side_effect = lambda x: None
        assert _find_terminal() is None

    def test_build_launch_cmd(self):
        assert _build_launch_cmd("gnome-terminal", "dashdash", "/tmp/script.sh", "/bin/bash") == [
            "gnome-terminal", "--", "/bin/bash", "/tmp/script.sh"
        ]

        assert _build_launch_cmd("konsole", "execute", "/tmp/script.sh", "/bin/bash") == [
            "konsole", "--command=/bin/bash /tmp/script.sh"
        ]

        assert _build_launch_cmd("xterm", "dashe", "/tmp/script.sh", "/bin/bash") == [
            "xterm", "-e", "/bin/bash /tmp/script.sh"
        ]

    def test_pick_script(self):
        body, runner = _pick_script("bash")
        assert 'LINUX_AI_COMMAND' in body
        assert runner == "sh"


class TestOpenWithCommand:
    @patch("src.terminal_launcher._find_terminal")
    def test_no_terminal_found(self, mock_find_terminal):
        mock_find_terminal.return_value = None
        success, msg = open_with_command("ls")
        assert success is False
        assert "No supported terminal emulator found" in msg

    @patch("src.terminal_launcher._find_terminal")
    @patch("src.terminal_launcher.tempfile.mkstemp")
    @patch("src.terminal_launcher.os.write")
    @patch("src.terminal_launcher.os.close")
    @patch("src.terminal_launcher.os.chmod")
    @patch("src.terminal_launcher._schedule_delete")
    @patch("subprocess.Popen")
    @patch("src.shell_detector.detect")
    def test_successful_launch(
        self,
        mock_detect,
        mock_popen,
        mock_schedule_delete,
        mock_chmod,
        mock_close,
        mock_write,
        mock_mkstemp,
        mock_find_terminal,
    ):
        mock_find_terminal.return_value = ("/usr/bin/gnome-terminal", "dashdash")

        mock_shell_info = MagicMock()
        mock_shell_info.family = "bash"
        mock_shell_info.path = "/bin/bash"
        mock_shell_info.name = "bash"
        mock_detect.return_value = mock_shell_info

        mock_mkstemp.return_value = (123, "/tmp/ai_helper_test.sh")

        success, msg = open_with_command("echo 'hello world'")

        assert success is True
        assert "Opened terminal (bash)" in msg
        mock_popen.assert_called_once()

        launch_cmd = mock_popen.call_args[0][0]
        assert launch_cmd == ["/usr/bin/gnome-terminal", "--", "/bin/bash", "/tmp/ai_helper_test.sh"]
        mock_schedule_delete.assert_called_once_with("/tmp/ai_helper_test.sh", delay=5.0)

    @patch("src.terminal_launcher._find_terminal")
    @patch("src.terminal_launcher.tempfile.mkstemp")
    @patch("src.terminal_launcher.os.write")
    @patch("src.terminal_launcher.os.close")
    @patch("src.terminal_launcher.os.chmod")
    @patch("src.terminal_launcher._schedule_delete")
    @patch("subprocess.Popen")
    def test_shell_detector_fallback(
        self,
        mock_popen,
        mock_schedule_delete,
        mock_chmod,
        mock_close,
        mock_write,
        mock_mkstemp,
        mock_find_terminal,
    ):
        mock_find_terminal.return_value = ("/usr/bin/xterm", "dashe")
        mock_mkstemp.return_value = (123, "/tmp/ai_helper_test.sh")

        with patch("src.shell_detector.detect", side_effect=Exception("Detection failed")):
            success, msg = open_with_command("ls")

        assert success is True

        launch_cmd = mock_popen.call_args[0][0]
        assert launch_cmd == ["/usr/bin/xterm", "-e", "/bin/sh /tmp/ai_helper_test.sh"]

    @patch("src.terminal_launcher._find_terminal")
    @patch("src.terminal_launcher.tempfile.mkstemp")
    @patch("src.terminal_launcher.os.write")
    @patch("src.terminal_launcher.os.close")
    @patch("src.terminal_launcher.os.chmod")
    @patch("src.terminal_launcher._schedule_delete")
    @patch("subprocess.Popen")
    @patch("src.shell_detector.detect")
    def test_popen_failure(
        self,
        mock_detect,
        mock_popen,
        mock_schedule_delete,
        mock_chmod,
        mock_close,
        mock_write,
        mock_mkstemp,
        mock_find_terminal,
    ):
        mock_find_terminal.return_value = ("/usr/bin/gnome-terminal", "dashdash")

        mock_shell_info = MagicMock()
        mock_shell_info.family = "bash"
        mock_shell_info.path = "/bin/bash"
        mock_shell_info.name = "bash"
        mock_detect.return_value = mock_shell_info

        mock_mkstemp.return_value = (123, "/tmp/ai_helper_test.sh")
        mock_popen.side_effect = OSError("Permission denied")

        success, msg = open_with_command("ls")
        assert success is False
        assert "Permission denied" in msg

    @patch("src.terminal_launcher._find_terminal")
    @patch("src.terminal_launcher.tempfile.mkstemp")
    @patch("src.terminal_launcher.os.write")
    @patch("src.terminal_launcher.os.close")
    @patch("src.terminal_launcher.os.chmod")
    @patch("src.terminal_launcher._schedule_delete")
    @patch("subprocess.Popen")
    @patch("src.shell_detector.detect")
    def test_fish_shell_wrapper(
        self,
        mock_detect,
        mock_popen,
        mock_schedule_delete,
        mock_chmod,
        mock_close,
        mock_write,
        mock_mkstemp,
        mock_find_terminal,
    ):
        mock_find_terminal.return_value = ("/usr/bin/gnome-terminal", "dashdash")

        mock_shell_info = MagicMock()
        mock_shell_info.family = "fish"
        mock_shell_info.path = "/bin/fish"
        mock_shell_info.name = "fish"
        mock_detect.return_value = mock_shell_info

        mock_mkstemp.return_value = (123, "/tmp/ai_helper_test.sh")

        success, msg = open_with_command("ls")
        assert success is True

        launch_cmd = mock_popen.call_args[0][0]
        # Fish shell uses /bin/sh to run its wrapper
        assert launch_cmd == ["/usr/bin/gnome-terminal", "--", "/bin/sh", "/tmp/ai_helper_test.sh"]

    @patch("src.terminal_launcher._find_terminal")
    @patch("src.terminal_launcher.tempfile.mkstemp")
    @patch("src.terminal_launcher.os.write")
    @patch("src.terminal_launcher.os.close")
    @patch("src.terminal_launcher.os.chmod")
    @patch("src.terminal_launcher._schedule_delete")
    @patch("subprocess.Popen")
    @patch("src.shell_detector.detect")
    def test_command_injection_mitigation(
        self,
        mock_detect,
        mock_popen,
        mock_schedule_delete,
        mock_chmod,
        mock_close,
        mock_write,
        mock_mkstemp,
        mock_find_terminal,
    ):
        mock_find_terminal.return_value = ("/usr/bin/gnome-terminal", "dashdash")

        mock_shell_info = MagicMock()
        mock_shell_info.family = "fish"
        mock_shell_info.path = "/bin/fish"
        mock_shell_info.name = "fish"
        mock_detect.return_value = mock_shell_info

        mock_mkstemp.return_value = (123, "/tmp/ai_helper_test.sh")

        # Malicious command that would have exploited the old version
        malicious_cmd = "'; touch /tmp/pwned; #"
        success, msg = open_with_command(malicious_cmd)

        assert success is True

        # Check that the environment variable was passed correctly
        env = mock_popen.call_args[1]["env"]
        assert env["LINUX_AI_COMMAND"] == malicious_cmd

        # Verify script body doesn't contain the raw malicious command (it's in the env now)
        # We need to see what was written to the script.
        # mock_write.call_args[0][1] is the script body.
        script_body = mock_write.call_args[0][1].decode()
        assert malicious_cmd not in script_body
        assert "LINUX_AI_COMMAND" in script_body
