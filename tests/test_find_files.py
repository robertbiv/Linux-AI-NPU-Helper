import pytest
from unittest.mock import patch, MagicMock
from src.tools.find_files import FindFilesTool, _has_hidden_component
from pathlib import Path


def test_has_hidden_component():
    assert _has_hidden_component("/home/user/.hidden/file.txt")
    assert _has_hidden_component("/home/user/dir/.hidden")
    assert not _has_hidden_component("/home/user/dir/file.txt")


@patch("shutil.which")
def test_detect_backend(mock_which):
    tool = FindFilesTool()

    mock_which.side_effect = lambda cmd: cmd == "plocate"
    assert tool._detect_backend() == "plocate"

    tool._backend = None
    mock_which.side_effect = lambda cmd: cmd == "locate"
    assert tool._detect_backend() == "locate"

    tool._backend = None
    mock_which.side_effect = lambda cmd: False
    assert tool._detect_backend() == "find"


@patch("src.tools.find_files.FindFilesTool._run_locate")
@patch("src.tools.find_files.FindFilesTool._detect_backend", return_value="locate")
def test_run_locate_backend(mock_detect, mock_run_locate):
    tool = FindFilesTool(default_search_path="/default")
    mock_run_locate.return_value = ["/default/file1.txt", "/default/file2.txt"]

    result = tool.run({"pattern": "*.txt", "max_results": 1})

    assert not result.error
    assert len(result.results) == 1
    assert result.truncated is True
    assert result.results[0].path == "/default/file1.txt"


@patch("src.tools.find_files.FindFilesTool._run_find")
@patch("src.tools.find_files.FindFilesTool._detect_backend", return_value="find")
def test_run_find_backend(mock_detect, mock_run_find):
    tool = FindFilesTool(default_search_path="/default")
    mock_run_find.return_value = ["/default/file1.txt"]

    result = tool.run({"pattern": "*.txt"})

    assert not result.error
    assert len(result.results) == 1


def test_run_missing_pattern():
    tool = FindFilesTool()
    result = tool.run({})
    assert result.error == "'pattern' is required."


@patch("src.tools.find_files.FindFilesTool._detect_backend", return_value="locate")
@patch(
    "src.tools.find_files.FindFilesTool._run_locate",
    side_effect=Exception("locate failed"),
)
def test_run_exception(mock_run, mock_detect):
    tool = FindFilesTool()
    result = tool.run({"pattern": "*.txt"})
    assert "locate failed" in result.error


@patch("subprocess.run")
def test_run_locate_impl(mock_run):
    mock_proc = MagicMock()
    mock_proc.stdout = "/test/file1.txt\n/other/file2.txt\n"
    mock_run.return_value = mock_proc

    result = FindFilesTool._run_locate("locate", "*.txt", Path("/test"), 10)
    assert result == ["/test/file1.txt"]


@patch("subprocess.run")
def test_run_find_impl(mock_run):
    mock_proc = MagicMock()
    mock_proc.stdout = "/test/file1.txt\n"
    mock_run.return_value = mock_proc

    result = FindFilesTool._run_find("*.txt", Path("/test"), 10, False)
    assert result == ["/test/file1.txt"]


@patch(
    "subprocess.run",
    side_effect=__import__("subprocess").TimeoutExpired(cmd="find", timeout=30),
)
def test_run_find_impl_timeout(mock_run):
    result = FindFilesTool._run_find("*.txt", Path("/test"), 10, False)
    assert result == []
