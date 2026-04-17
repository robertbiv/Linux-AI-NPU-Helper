import pytest
from unittest.mock import patch, MagicMock
from src.tools.calculator import CalculatorTool
from src.tools.hash_tool import HashTool
from src.tools.clipboard_tool import ClipboardTool
from src.tools import build_default_registry

def test_calculator_tool_success():
    tool = CalculatorTool()
    res = tool.run({"expression": "2 + 2"})
    assert not res.error
    assert "4" in res.results[0].snippet

def test_calculator_tool_math():
    tool = CalculatorTool()
    res = tool.run({"expression": "math.sin(math.pi/2)"})
    assert not res.error
    assert "1" in res.results[0].snippet

def test_calculator_tool_error():
    tool = CalculatorTool()
    res = tool.run({"expression": "invalid syntax"})
    assert res.error
    assert "Error evaluating expression" in res.error

def test_hash_tool_text():
    tool = HashTool()
    res = tool.run({"algorithm": "sha256", "text": "hello"})
    assert not res.error
    assert "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824" in res.results[0].snippet

def test_hash_tool_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    tool = HashTool()
    res = tool.run({"algorithm": "sha256", "file_path": str(f)})
    assert not res.error
    assert "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824" in res.results[0].snippet

def test_hash_tool_unsupported_algo():
    tool = HashTool()
    res = tool.run({"algorithm": "unknown", "text": "test"})
    assert res.error
    assert "Unsupported algorithm" in res.error

@patch("subprocess.run")
@patch("shutil.which")
def test_clipboard_tool_fallback_read(mock_which, mock_run):
    mock_which.return_value = "/usr/bin/xclip"
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "copied text"
    mock_run.return_value = mock_proc

    tool = ClipboardTool()
    res = tool.run({"action": "read"})
    assert not res.error
    assert "copied text" in res.results[0].snippet

@patch("subprocess.run")
@patch("shutil.which")
def test_clipboard_tool_fallback_write(mock_which, mock_run):
    mock_which.return_value = "/usr/bin/xclip"
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_run.return_value = mock_proc

    tool = ClipboardTool()
    res = tool.run({"action": "write", "text": "new text"})
    assert not res.error
    assert "Text written" in res.results[0].snippet

def test_utility_tools_registered():
    registry = build_default_registry()
    names = registry.names()
    assert "calculate" in names
    assert "hash" in names
    assert "clipboard" in names

from src.tools.password_tool import PasswordGeneratorTool
from src.tools.base64_tool import Base64Tool
from src.tools.uuid_tool import UUIDTool

def test_password_tool():
    tool = PasswordGeneratorTool()
    res = tool.run({"length": 20, "include_symbols": False})
    assert not res.error
    assert "Generated password (20 chars)" in res.results[0].snippet

def test_base64_tool_encode():
    tool = Base64Tool()
    res = tool.run({"action": "encode", "text": "hello"})
    assert not res.error
    assert "aGVsbG8=" in res.results[0].snippet

def test_base64_tool_decode():
    tool = Base64Tool()
    res = tool.run({"action": "decode", "text": "aGVsbG8="})
    assert not res.error
    assert "hello" in res.results[0].snippet

def test_uuid_tool():
    tool = UUIDTool()
    res = tool.run({"count": 2})
    assert not res.error
    assert len(res.results[0].snippet.splitlines()) == 2
    assert "-" in res.results[0].snippet

def test_new_tools_registered():
    registry = build_default_registry()
    names = registry.names()
    assert "generate_password" in names
    assert "base64" in names
    assert "generate_uuid" in names

from src.tools.json_tool import JSONTool
from src.tools.url_tool import URLEncoderTool
from src.tools.text_stats_tool import TextStatsTool

def test_json_tool_format():
    tool = JSONTool()
    res = tool.run({"action": "format", "text": '{"a": 1}'})
    assert not res.error
    assert '    "a": 1' in res.results[0].snippet

def test_json_tool_minify():
    tool = JSONTool()
    res = tool.run({"action": "minify", "text": '{\n  "a": 1\n}'})
    assert not res.error
    assert '{"a":1}' in res.results[0].snippet

def test_url_tool_encode():
    tool = URLEncoderTool()
    res = tool.run({"action": "encode", "text": "hello world!"})
    assert not res.error
    assert "hello+world%21" in res.results[0].snippet

def test_url_tool_decode():
    tool = URLEncoderTool()
    res = tool.run({"action": "decode", "text": "hello+world%21"})
    assert not res.error
    assert "hello world!" in res.results[0].snippet

def test_text_stats_tool():
    tool = TextStatsTool()
    res = tool.run({"text": "hello world\nthis is a test"})
    assert not res.error
    assert "Characters: 26" in res.results[0].snippet
    assert "Words: 6" in res.results[0].snippet
    assert "Lines: 2" in res.results[0].snippet

def test_newest_tools_registered():
    registry = build_default_registry()
    names = registry.names()
    assert "json_format" in names
    assert "url_encode" in names
    assert "text_stats" in names
