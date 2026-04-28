import pytest
from src.tools.time_tool import TimeTool
from unittest.mock import patch
import datetime

def test_time_tool_invalid_args():
    tool = TimeTool()

    # Missing action
    res = tool.run({})
    assert "Action must be 'current' or 'convert'." in res.error

    # Convert without ts
    res = tool.run({"action": "convert"})
    assert "'timestamp' is required" in res.error

def test_time_tool_current():
    tool = TimeTool()

    # Local
    res = tool.run({"action": "current"})
    assert "Current Local Time" in res.results[0].snippet
    assert "ISO" in res.results[0].snippet

    # UTC
    res = tool.run({"action": "current", "timezone": "utc"})
    assert "Current UTC Time" in res.results[0].snippet

def test_time_tool_convert():
    tool = TimeTool()

    # Local
    res = tool.run({"action": "convert", "timestamp": 1600000000})
    assert "Timestamp 1600000000" in res.results[0].snippet
    assert "Local" in res.results[0].snippet

    # UTC
    res = tool.run({"action": "convert", "timestamp": 1600000000, "timezone": "utc"})
    assert "Timestamp 1600000000" in res.results[0].snippet
    assert "UTC" in res.results[0].snippet

def test_time_tool_exceptions():
    tool = TimeTool()

    # ValueError
    res = tool.run({"action": "convert", "timestamp": "invalid"})
    assert "Invalid timestamp or input" in res.error

    # Generic
    with patch("src.tools.time_tool.datetime.datetime") as mock_dt:
        mock_dt.now.side_effect = Exception("Generic Error")
        res = tool.run({"action": "current"})
        assert "Time calculation failed: Generic Error" in res.error
