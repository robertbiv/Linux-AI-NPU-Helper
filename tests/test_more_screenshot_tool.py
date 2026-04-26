import pytest
from unittest.mock import patch, MagicMock
from src.tools.screenshot_tool import ScreenshotTool

def test_screenshot_tool_success():
    tool = ScreenshotTool()
    with patch('src.tools.screenshot_tool.ScreenshotTool._capture', return_value=b"fake_jpeg"):
        with patch('src.tools.screenshot_tool.ScreenshotTool._save', return_value="/tmp/test.jpg"):
            res = tool.run({"monitor": 1, "jpeg_quality": 80, "save": True})
            assert not res.error
            assert res.results[0].snippet == "ZmFrZV9qcGVn" # base64 of fake_jpeg
            assert res.results[0].path == "/tmp/test.jpg"

def test_screenshot_tool_no_save():
    tool = ScreenshotTool()
    with patch('src.tools.screenshot_tool.ScreenshotTool._capture', return_value=b"fake_jpeg"):
        res = tool.run({"save": False})
        assert not res.error
        assert res.results[0].path == "(memory only)"

def test_screenshot_tool_opacity():
    mock_opacity = MagicMock()
    tool = ScreenshotTool(hide_opacity_fn=mock_opacity)
    with patch('src.tools.screenshot_tool.ScreenshotTool._capture', return_value=b"fake_jpeg"):
        res = tool.run({})
        assert not res.error
        mock_opacity.assert_any_call(0.0)
        mock_opacity.assert_any_call(1.0)

def test_screenshot_tool_opacity_exception():
    def throw_opacity(val):
        raise Exception("Opacity Error")
    tool = ScreenshotTool(hide_opacity_fn=throw_opacity)
    with patch('src.tools.screenshot_tool.ScreenshotTool._capture', return_value=b"fake_jpeg"):
        res = tool.run({})
        assert not res.error

def test_screenshot_tool_capture_exception():
    tool = ScreenshotTool()
    with patch('src.tools.screenshot_tool.ScreenshotTool._capture', side_effect=Exception("Capture Error")):
        res = tool.run({})
        assert "Capture Error" in res.error

def test_screenshot_capture_for_send_success():
    from src.tools.screenshot_tool import ScreenshotTool
    import sys
    with patch.dict('sys.modules', {'PyQt5.QtWidgets': MagicMock()}):
        with patch('src.screen_capture.capture', return_value=b"fake_jpeg"):
            res = ScreenshotTool.capture_for_send()
            assert res == b"fake_jpeg"

def test_screenshot_capture_for_send_window():
    from src.tools.screenshot_tool import ScreenshotTool
    mock_window = MagicMock()
    import sys
    with patch.dict('sys.modules', {'PyQt5.QtWidgets': MagicMock()}):
        with patch('src.screen_capture.capture', return_value=b"fake_jpeg"):
            res = ScreenshotTool.capture_for_send(window=mock_window)
            assert res == b"fake_jpeg"
            mock_window.setWindowOpacity.assert_any_call(0.0)
            mock_window.setWindowOpacity.assert_any_call(1.0)

def test_screenshot_capture_for_send_exception():
    from src.tools.screenshot_tool import ScreenshotTool
    import sys
    with patch.dict('sys.modules', {'PyQt5.QtWidgets': MagicMock()}):
        with patch('src.screen_capture.capture', side_effect=Exception("Error")):
            res = ScreenshotTool.capture_for_send()
            assert res is None


def test_screenshot_tool_opacity_fail():
    def throw_opacity(val):
        raise Exception("Error")
    tool = ScreenshotTool(hide_opacity_fn=throw_opacity)
    tool._apply_opacity(0.5)
