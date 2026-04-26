import pytest
import subprocess
from unittest.mock import patch, MagicMock
from src.command_executor import CommandExecutor

_SAFETY = {
    "confirm_commands": False,
    "blocked_commands": [r"rm\s+-rf\s+/"],
}


def test_execute_pipeline_simple():
    ex = CommandExecutor(_SAFETY)
    with (
        patch("subprocess.Popen") as mock_popen,
        patch("tempfile.mkstemp") as mock_temp,
    ):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("output\n", b"")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        mock_temp.return_value = (123, "/tmp/fake")
        with patch("os.fdopen") as mock_fdopen:
            mock_fd = MagicMock()
            mock_fd.read.return_value = ""
            mock_fdopen.return_value = mock_fd

            res = ex._execute_pipeline("echo hello")
            assert res.stdout == "output\n"
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            assert args[0] == ["echo", "hello"]


def test_execute_pipeline_pipe():
    ex = CommandExecutor(_SAFETY)
    with (
        patch("subprocess.Popen") as mock_popen,
        patch("tempfile.mkstemp") as mock_temp,
    ):
        mock_proc1 = MagicMock()
        mock_proc1.stdout = MagicMock()
        mock_proc1.poll.return_value = 0

        mock_proc2 = MagicMock()
        mock_proc2.returncode = 0
        mock_proc2.communicate.return_value = ("output2\n", b"")
        mock_proc2.poll.return_value = 0

        mock_popen.side_effect = [mock_proc1, mock_proc2]

        mock_temp.return_value = (123, "/tmp/fake")
        with patch("os.fdopen") as mock_fdopen:
            mock_fd = MagicMock()
            mock_fd.read.return_value = ""
            mock_fdopen.return_value = mock_fd

            res = ex._execute_pipeline("echo hello | grep h")
            assert res.stdout == "output2\n"
            assert mock_popen.call_count == 2
            args1, _ = mock_popen.call_args_list[0]
            args2, _ = mock_popen.call_args_list[1]
            assert args1[0] == ["echo", "hello"]
            assert args2[0] == ["grep", "h"]


def test_execute_pipeline_invalid_operator():
    ex = CommandExecutor(_SAFETY)
    with pytest.raises(ValueError, match="is not supported for security"):
        ex._execute_pipeline("echo hello && echo world")


def test_execute_pipeline_syntax_error():
    ex = CommandExecutor(_SAFETY)
    with pytest.raises(ValueError, match="unexpected end of command"):
        ex._execute_pipeline("echo hello |")

    with pytest.raises(ValueError, match="unexpected"):
        ex._execute_pipeline("| echo hello")

    with pytest.raises(ValueError, match="expected file"):
        ex._execute_pipeline("echo hello >")


def test_execute_pipeline_io_redirection():
    ex = CommandExecutor(_SAFETY)
    with (
        patch("subprocess.Popen") as mock_popen,
        patch("tempfile.mkstemp") as mock_temp,
        patch("os.fdopen") as mock_fdopen,
        patch("builtins.open") as mock_open,
    ):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", b"")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        mock_temp.return_value = (123, "/tmp/fake")
        mock_fd = MagicMock()
        mock_fd.read.return_value = ""
        mock_fdopen.return_value = mock_fd

        mock_file = MagicMock()
        mock_open.return_value = mock_file

        ex._execute_pipeline("cat < in.txt > out.txt")

        mock_open.assert_any_call("in.txt", "r")
        mock_open.assert_any_call("out.txt", "w")
        mock_popen.assert_called_once()


def test_execute_pipeline_timeout():
    ex = CommandExecutor(_SAFETY)
    with (
        patch("subprocess.Popen") as mock_popen,
        patch("tempfile.mkstemp") as mock_temp,
        patch("os.fdopen") as mock_fdopen,
    ):
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired("cmd", 1)
        mock_popen.return_value = mock_proc

        mock_temp.return_value = (123, "/tmp/fake")
        mock_fd = MagicMock()
        mock_fdopen.return_value = mock_fd

        with pytest.raises(subprocess.TimeoutExpired):
            ex._execute_pipeline("sleep 10", timeout=1)


def test_execute_pipeline_not_found():
    ex = CommandExecutor(_SAFETY)
    with (
        patch("subprocess.Popen") as mock_popen,
        patch("tempfile.mkstemp") as mock_temp,
        patch("os.fdopen") as mock_fdopen,
    ):
        mock_popen.side_effect = FileNotFoundError()

        mock_temp.return_value = (123, "/tmp/fake")
        mock_fd = MagicMock()
        mock_fdopen.return_value = mock_fd

        with pytest.raises(ValueError, match="Command not found"):
            ex._execute_pipeline("nonexistentcmd")


def test_execute_pipeline_shlex_error():
    ex = CommandExecutor(_SAFETY)
    with pytest.raises(ValueError, match="Failed to parse"):
        ex._execute_pipeline("echo 'unterminated")


def test_execute_pipeline_empty():
    ex = CommandExecutor(_SAFETY)
    with pytest.raises(ValueError, match="Empty command"):
        ex._execute_pipeline("   ")
