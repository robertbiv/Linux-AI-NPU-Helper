import pytest
from src.tools.clipboard_tool import ClipboardTool
from unittest.mock import patch, MagicMock

def test_clipboard_tool_invalid_args():
    tool = ClipboardTool()

    # Missing action
    res = tool.run({"action": ""})
    assert "Action must be 'read' or 'write'." in res.error

    # Write without text key
    res = tool.run({"action": "write"})
    assert "'text' is required for write action." in res.error

def test_clipboard_tool_qt_read_write(qtbot):
    tool = ClipboardTool()
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()

    # Write
    res = tool.run({"action": "write", "text": "hello qt"})
    assert not res.error
    assert "Text written to clipboard." in res.results[0].snippet
    assert app.clipboard().text() == "hello qt"

    # Read
    res = tool.run({"action": "read"})
    assert not res.error
    assert "hello qt" in res.results[0].snippet

    # Read empty
    app.clipboard().setText("")
    res = tool.run({"action": "read"})
    assert "(clipboard is empty)" in res.results[0].snippet

def test_clipboard_tool_qt_exception(qtbot):
    tool = ClipboardTool()
    with patch("PyQt5.QtWidgets.QApplication.instance") as mock_instance:
        mock_instance.return_value.clipboard.side_effect = Exception("Qt Error")

        # Should fallback. We'll mock fallback to succeed so we know it got called.
        with patch.object(tool, "_fallback_clipboard") as mock_fallback:
            mock_fallback.return_value = MagicMock(error=None)
            res = tool.run({"action": "read"})
            mock_fallback.assert_called_once()

def test_clipboard_tool_fallback_no_tools():
    tool = ClipboardTool()
    with patch("shutil.which", return_value=None):
        res = tool._fallback_clipboard("read", "")
        assert "Neither Qt, wl-clipboard, nor xclip" in res.error

def test_clipboard_tool_fallback_wl(monkeypatch):
    tool = ClipboardTool()

    def mock_which(cmd):
        if cmd == "wl-copy" or cmd == "wl-paste":
            return "/usr/bin/" + cmd
        return None

    with patch("shutil.which", side_effect=mock_which):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="hello wl")

            # Read
            res = tool._fallback_clipboard("read", "")
            assert not res.error
            assert "hello wl" in res.results[0].snippet
            mock_run.assert_called_with(["wl-paste"], shell=False, capture_output=True, text=True, timeout=5)

            # Write
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            res = tool._fallback_clipboard("write", "test")
            assert not res.error
            assert "Text written" in res.results[0].snippet
            mock_run.assert_called_with(["wl-copy"], shell=False, input="test", capture_output=True, text=True, timeout=5)

            # Error read
            mock_run.return_value = MagicMock(returncode=1, stderr="wl error")
            res = tool._fallback_clipboard("read", "")
            assert "Failed to read clipboard: wl error" in res.error

            # Error write
            mock_run.return_value = MagicMock(returncode=1, stderr="wl error")
            res = tool._fallback_clipboard("write", "test")
            assert "Failed to write clipboard: wl error" in res.error

def test_clipboard_tool_fallback_xclip(monkeypatch):
    tool = ClipboardTool()

    def mock_which(cmd):
        if cmd == "xclip":
            return "/usr/bin/xclip"
        return None

    with patch("shutil.which", side_effect=mock_which):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="hello xclip")

            # Read
            res = tool._fallback_clipboard("read", "")
            assert not res.error
            assert "hello xclip" in res.results[0].snippet
            mock_run.assert_called_with(["xclip", "-selection", "clipboard", "-o"], shell=False, capture_output=True, text=True, timeout=5)

            # Write
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            res = tool._fallback_clipboard("write", "test")
            assert not res.error
            assert "Text written" in res.results[0].snippet
            mock_run.assert_called_with(["xclip", "-selection", "clipboard", "-i"], shell=False, input="test", capture_output=True, text=True, timeout=5)

def test_clipboard_tool_fallback_exception():
    tool = ClipboardTool()
    with patch("shutil.which", return_value="/usr/bin/xclip"):
        with patch("subprocess.run", side_effect=Exception("Subprocess error")):
            res = tool._fallback_clipboard("read", "")
            assert "Clipboard operation failed: Subprocess error" in res.error

def test_clipboard_tool_no_qt_app():
    tool = ClipboardTool()
    with patch("PyQt5.QtWidgets.QApplication.instance", return_value=None):
        with patch.object(tool, "_fallback_clipboard") as mock_fallback:
            mock_fallback.return_value = MagicMock(error=None)
            res = tool.run({"action": "read"})
            mock_fallback.assert_called_once()
