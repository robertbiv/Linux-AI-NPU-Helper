import pytest
from src.tools.json_tool import JSONTool
from unittest.mock import patch

def test_json_tool_invalid_args():
    tool = JSONTool()

    # Missing action
    res = tool.run({"action": "invalid", "text": "{}"})
    assert "Action must be 'format' or 'minify'." in res.error

    # Missing text
    res = tool.run({"action": "format", "text": ""})
    assert "'text' is required" in res.error

def test_json_tool_format_minify():
    tool = JSONTool()

    # Format
    res = tool.run({"action": "format", "text": '{"a":1,"b":2}'})
    assert "{\n    \"a\": 1,\n    \"b\": 2\n}" in res.results[0].snippet

    # Minify
    res = tool.run({"action": "minify", "text": '{\n    "a": 1,\n    "b": 2\n}'})
    assert '{"a":1,"b":2}' in res.results[0].snippet

def test_json_tool_exceptions():
    tool = JSONTool()

    # JSONDecodeError
    res = tool.run({"action": "format", "text": "invalid"})
    assert "Invalid JSON provided" in res.error

    # Generic
    with patch("json.loads", side_effect=Exception("Generic Error")):
        res = tool.run({"action": "format", "text": "{}"})
        assert "JSON format failed: Generic Error" in res.error
