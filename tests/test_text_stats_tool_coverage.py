import pytest
from src.tools.text_stats_tool import TextStatsTool
from unittest.mock import patch

def test_text_stats_tool_invalid_args():
    tool = TextStatsTool()
    res = tool.run({})
    assert "'text' is required" in res.error

def test_text_stats_tool_normal():
    tool = TextStatsTool()
    res = tool.run({"text": "hello world\nthis is a test"})

    assert "Characters: 26" in res.results[0].snippet
    assert "Words: 6" in res.results[0].snippet
    assert "Lines: 2" in res.results[0].snippet

def test_text_stats_tool_exception():
    tool = TextStatsTool()
    with patch("builtins.len", side_effect=Exception("Generic Error")):
        res = tool.run({"text": "a"})
        assert "Text stats calculation failed" in res.error
