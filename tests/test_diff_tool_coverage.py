import pytest
from src.tools.diff_tool import DiffTool
from unittest.mock import patch

def test_diff_tool_basic():
    tool = DiffTool()

    # Same
    res = tool.run({"text_a": "hello", "text_b": "hello"})
    assert "Texts are identical." in res.results[0].snippet

    # Different
    res = tool.run({"text_a": "hello\nworld", "text_b": "hello\nthere"})
    assert "-world" in res.results[0].snippet
    assert "+there" in res.results[0].snippet

def test_diff_tool_exception():
    tool = DiffTool()

    # Generic
    with patch("difflib.unified_diff", side_effect=Exception("Generic Error")):
        res = tool.run({"text_a": "hello", "text_b": "hello"})
        assert "Diff generation failed: Generic Error" in res.error
