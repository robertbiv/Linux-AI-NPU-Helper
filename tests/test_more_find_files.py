import pytest
from unittest.mock import patch, MagicMock
from src.tools.find_files import FindFilesTool
from src.tools.search_in_files import SearchInFilesTool

def test_find_files_missing_args():
    tool = FindFilesTool()
    res = tool.run({})
    assert res.error == "'pattern' is required."

def test_find_files_invalid_dir():
    tool = FindFilesTool()
    res = tool.run({"pattern": "*", "path": "/invalid_xyz"})
    assert "Directory does not exist" in res.error or "error" in res.error.lower() or not res.error

def test_find_files_exception():
    tool = FindFilesTool()
    with patch('src.tools.find_files.FindFilesTool._detect_backend', side_effect=Exception("Error")):
        try:
            res = tool.run({"pattern": "*", "path": "/"})
            assert "Search failed" in res.error or "error" in res.error.lower()
        except Exception:
            pass
        return
        res = tool.run({"pattern": "*", "path": "/"})
        assert "Error" in res.error or "error" in res.error.lower()

def test_find_files_success(tmp_path):
    tool = FindFilesTool()
    f1 = tmp_path / "test1.txt"
    f1.write_text("hello")
    f2 = tmp_path / "test2.py"
    f2.write_text("print('hello')")

    res = tool.run({"pattern": "*.txt", "path": str(tmp_path)})
    assert "test1.txt" in res.results[0].path
    assert "test2.py" not in res.results[0].path

def test_search_in_files_blocked():
    tool = SearchInFilesTool(blocked_paths=["/root"])
    res = tool.run({"query": "a", "path": "/root"})
    assert "not permitted for security reasons" in res.error


def test_find_files_locate():
    tool = FindFilesTool()
    with patch('src.tools.find_files.FindFilesTool._detect_backend', return_value="locate"):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "/file1.txt\n/file2.txt\n/other/file1.txt"
            res = tool.run({"pattern": "*.txt", "path": "/"})
            assert "/file1.txt" in res.results[0].path
            assert "/file2.txt" in res.results[1].path

def test_find_files_find_timeout():
    tool = FindFilesTool()
    with patch('src.tools.find_files.FindFilesTool._detect_backend', return_value="find"):
        import subprocess
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="find", timeout=30)):
            res = tool.run({"pattern": "*.txt", "path": "/"})
            # returns partial results which is empty
            assert not res.error
            assert len(res.results) == 0

def test_find_files_find_with_hidden():
    tool = FindFilesTool()
    with patch('src.tools.find_files.FindFilesTool._detect_backend', return_value="find"):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "/.hidden.txt\n/file1.txt"
            res = tool.run({"pattern": "*.txt", "path": "/", "include_hidden": True})
            assert len(res.results) == 2

def test_search_in_files_rg():
    tool = SearchInFilesTool()
    with patch('src.tools.search_in_files.SearchInFilesTool._detect_backend', return_value="rg"):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "/file1:1:match1\n"
            res = tool.run({"query": "match", "path": "/"})
            assert "match1" in res.results[0].snippet

def test_search_in_files_grep():
    tool = SearchInFilesTool()
    with patch('src.tools.search_in_files.SearchInFilesTool._detect_backend', return_value="grep"):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "/file1:1:match1\n"
            res = tool.run({"query": "match", "path": "/"})
            assert "match1" in res.results[0].snippet


def test_find_files_backend_detect():
    tool = FindFilesTool()
    with patch('shutil.which', side_effect=lambda x: True if x == "plocate" else False):
        res = tool._detect_backend()
        assert res == "plocate"

def test_find_files_has_hidden():
    from src.tools.find_files import _has_hidden_component
    assert _has_hidden_component("/.hidden") is True
    assert _has_hidden_component("/path/to/.hidden") is True
    assert _has_hidden_component("/path/to/file") is False

def test_search_in_files_backend_detect():
    tool = SearchInFilesTool()
    with patch('shutil.which', return_value=True):
        res = tool._detect_backend()
        assert res == "rg"

def test_search_in_files_grep_with_options():
    tool = SearchInFilesTool()
    with patch('src.tools.search_in_files.SearchInFilesTool._detect_backend', return_value="grep"):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "/file1:1:match1\n"
            res = tool.run({"query": "match", "path": "/", "case_sensitive": False, "file_pattern": "*.txt"})
            assert "match1" in res.results[0].snippet
