import pytest
from src.tools.regex_tool import RegexTool
from unittest.mock import patch

def test_regex_tool_invalid_args():
    tool = RegexTool()

    # invalid action
    res = tool.run({"action": "invalid", "pattern": ".*", "text": "a"})
    assert "Action must be 'search' or 'replace'." in res.error

    # missing pattern
    res = tool.run({"action": "search", "pattern": "", "text": "a"})
    assert "'pattern' is required." in res.error

    # missing text
    res = tool.run({"action": "search", "pattern": ".*", "text": ""})
    assert "'text' is required." in res.error

    # missing replacement
    res = tool.run({"action": "replace", "pattern": "a", "text": "a"})
    assert "'replacement' is required for the 'replace' action." in res.error

def test_regex_tool_search():
    tool = RegexTool()

    # No matches
    res = tool.run({"action": "search", "pattern": "z", "text": "a"})
    assert "No matches found." in res.results[0].snippet

    # Some matches
    res = tool.run({"action": "search", "pattern": "a", "text": "abcabc"})
    assert "Found 2 matches" in res.results[0].snippet
    assert "a" in res.results[0].snippet

    # Many matches
    res = tool.run({"action": "search", "pattern": "a", "text": "a" * 55})
    assert "Found 55 matches" in res.results[0].snippet
    assert "... (truncated)" in res.results[0].snippet

def test_regex_tool_replace():
    tool = RegexTool()

    # Replace
    res = tool.run({"action": "replace", "pattern": "a", "text": "abcabc", "replacement": "z"})
    assert "zbczbc" in res.results[0].snippet

def test_regex_tool_exceptions():
    tool = RegexTool()

    # re.error
    res = tool.run({"action": "search", "pattern": "[a-", "text": "a"})
    assert "Invalid regular expression" in res.error

    # Generic exception
    with patch("re.compile", side_effect=Exception("Generic Error")):
        res = tool.run({"action": "search", "pattern": "a", "text": "a"})
        assert "Regex operation failed: Generic Error" in res.error
