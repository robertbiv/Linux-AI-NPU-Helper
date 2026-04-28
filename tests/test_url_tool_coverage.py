import pytest
from src.tools.url_tool import URLEncoderTool
from unittest.mock import patch

def test_url_tool_invalid_args():
    tool = URLEncoderTool()
    res = tool.run({})
    assert "Action must be 'encode' or 'decode'." in res.error

    res = tool.run({"action": "encode"})
    assert "'text' is required" in res.error

def test_url_tool_encode_decode():
    tool = URLEncoderTool()

    # encode
    res = tool.run({"action": "encode", "text": "hello world"})
    assert "hello+world" in res.results[0].snippet

    # decode
    res = tool.run({"action": "decode", "text": "hello+world"})
    assert "hello world" in res.results[0].snippet

def test_url_tool_exception():
    tool = URLEncoderTool()
    with patch("urllib.parse.quote_plus", side_effect=Exception("Generic Error")):
        res = tool.run({"action": "encode", "text": "hello world"})
        assert "URL encode failed: Generic Error" in res.error
