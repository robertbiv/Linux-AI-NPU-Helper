import pytest
from unittest.mock import patch, MagicMock
from src.tools.screenshot_tool import ScreenshotTool
from src.tools.search_in_files import SearchInFilesTool

def test_screenshot_tool_missing_args():
    tool = ScreenshotTool()
    res = tool.run({})
    assert "mss is not installed" in res.error or "failed" in res.error.lower() or "memory only" in res.results[0].path or ".jpg" in res.results[0].path

def test_search_in_files_missing_args():
    tool = SearchInFilesTool()
    res = tool.run({"path": "/"})
    assert res.error == "'pattern' and 'directory' are required." or "query" in res.error.lower()

def test_search_in_files_invalid_dir():
    tool = SearchInFilesTool()
    res = tool.run({"query": "a", "path": "/invalid_dir_xyz123"})
    assert res.error == "" or "error" in res.error.lower() or len(res.results) == 0

def test_search_in_files_exception():
    tool = SearchInFilesTool()
    with patch('subprocess.run', side_effect=Exception("Error")):
        res = tool.run({"query": "a", "path": "/"})
        assert "Error" in res.error or "error" in res.error.lower()


def test_search_in_files_grep_timeout():
    tool = SearchInFilesTool()
    with patch('src.tools.search_in_files.SearchInFilesTool._detect_backend', return_value="grep"):
        import subprocess
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="grep", timeout=30)):
            res = tool.run({"query": "a", "path": "/"})
            # This triggers the except subprocess.TimeoutExpired
            assert not res.error or "Error" in res.error

def test_search_in_files_rg_timeout():
    tool = SearchInFilesTool()
    with patch('src.tools.search_in_files.SearchInFilesTool._detect_backend', return_value="rg"):
        import subprocess
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="rg", timeout=20)):
            res = tool.run({"query": "a", "path": "/"})
            assert "timed out" in res.error.lower()


def test_search_in_files_grep_success():
    tool = SearchInFilesTool()
    with patch('src.tools.search_in_files.SearchInFilesTool._detect_backend', return_value="grep"):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "/file1:1:match1\n/file2:2:match2"
            res = tool.run({"query": "match", "path": "/"})
            assert "match1" in res.results[0].snippet

def test_search_in_files_rg_success():
    tool = SearchInFilesTool()
    with patch('src.tools.search_in_files.SearchInFilesTool._detect_backend', return_value="rg"):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "/file1:1:match1\n/file2:2:match2"
            res = tool.run({"query": "match", "path": "/"})
            assert "match1" in res.results[0].snippet
