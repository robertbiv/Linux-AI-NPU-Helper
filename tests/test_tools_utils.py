from unittest.mock import patch, mock_open
from src.tools._utils import read_sys_file, run_command


def test_read_sys_file_success():
    with patch("builtins.open", mock_open(read_data="  content  \n")):
        assert read_sys_file("/fake/path") == "content"


def test_read_sys_file_failure():
    with patch("builtins.open", side_effect=OSError):
        assert read_sys_file("/fake/path", "default") == "default"


@patch("shutil.which", return_value="/bin/ls")
@patch("subprocess.run")
def test_run_command_success(mock_run, mock_which):
    mock_run.return_value.stdout = "  output  \n"
    assert run_command(["ls"]) == "output"
    mock_run.assert_called_once()


@patch("shutil.which", return_value=None)
def test_run_command_not_found(mock_which):
    assert run_command(["nonexistent"]) == ""


@patch("shutil.which", return_value="/bin/ls")
@patch("subprocess.run", side_effect=Exception("error"))
def test_run_command_exception(mock_run, mock_which):
    assert run_command(["ls"]) == ""
