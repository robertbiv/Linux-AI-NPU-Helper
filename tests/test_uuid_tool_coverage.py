import pytest
from src.tools.uuid_tool import UUIDTool

def test_uuid_tool_normal():
    tool = UUIDTool()

    res = tool.run({})
    assert len(res.results[0].snippet.split("\n")) == 1

    res = tool.run({"count": 5})
    assert len(res.results[0].snippet.split("\n")) == 5

def test_uuid_tool_bounds():
    tool = UUIDTool()

    res = tool.run({"count": -10})
    assert len(res.results[0].snippet.split("\n")) == 1

    res = tool.run({"count": 1000})
    assert len(res.results[0].snippet.split("\n")) == 100

def test_uuid_tool_invalid():
    tool = UUIDTool()
    res = tool.run({"count": "invalid"})
    assert len(res.results[0].snippet.split("\n")) == 1
