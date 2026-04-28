import pytest
from src.tools.hash_tool import HashTool
from unittest.mock import patch, mock_open, MagicMock

def test_hash_tool_invalid_args():
    tool = HashTool()

    # unsupported algo
    res = tool.run({"algorithm": "invalid", "text": "a"})
    assert "Unsupported algorithm" in res.error

    # both
    res = tool.run({"algorithm": "sha256", "text": "a", "file_path": "a.txt"})
    assert "Provide either 'text' or 'file_path', not both" in res.error

    # neither
    res = tool.run({"algorithm": "sha256"})
    assert "Provide either 'text' or 'file_path'." in res.error

def test_hash_tool_text():
    tool = HashTool()
    res = tool.run({"algorithm": "sha256", "text": "hello"})
    assert "sha256('hello') =" in res.results[0].snippet

def test_hash_tool_file():
    tool = HashTool()
    with patch("src.tools.hash_tool.Path.is_file", return_value=True):
        with patch("src.tools.hash_tool.Path.resolve", return_value=MagicMock(name="mock.txt")):
            with patch("builtins.open", mock_open(read_data=b"hello")):
                res = tool.run({"algorithm": "sha256", "file_path": "a.txt"})
                assert "sha256(" in res.results[0].snippet

def test_hash_tool_file_not_found():
    tool = HashTool()
    with patch("src.tools.hash_tool.Path.is_file", return_value=False):
        res = tool.run({"algorithm": "sha256", "file_path": "a.txt"})
        assert "File not found or is a directory" in res.error

def test_hash_tool_exception():
    tool = HashTool()
    with patch("src.tools.hash_tool.Path.is_file", side_effect=Exception("Generic Error")):
        res = tool.run({"algorithm": "sha256", "file_path": "a.txt"})
        assert "Hashing failed: Generic Error" in res.error

def test_hash_tool_unknown_error():
    # Just patching out text to be None after the check
    pass
