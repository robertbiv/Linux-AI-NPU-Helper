import pytest
from src.tools.encoding_tool import EncodingTool
from unittest.mock import patch

def test_encoding_tool_hex():
    tool = EncodingTool()

    # encode
    res = tool.run({"format": "hex", "action": "encode", "text": "hello"})
    assert "Encoded hex:" in res.results[0].snippet
    assert "68656c6c6f" in res.results[0].snippet

    # decode
    res = tool.run({"format": "hex", "action": "decode", "text": "68 65 6c 6c 6f"})
    assert "hello" in res.results[0].snippet

    # decode invalid hex
    res = tool.run({"format": "hex", "action": "decode", "text": "68656c6c6z"})
    assert "Invalid input data for decoding" in res.error

def test_encoding_tool_binary():
    tool = EncodingTool()

    # encode
    res = tool.run({"format": "binary", "action": "encode", "text": "A"})
    assert "Encoded binary:" in res.results[0].snippet
    assert "01000001" in res.results[0].snippet

    # decode
    res = tool.run({"format": "binary", "action": "decode", "text": "01000001"})
    assert "A" in res.results[0].snippet

    # decode invalid length
    res = tool.run({"format": "binary", "action": "decode", "text": "010"})
    assert "Binary text length must be a multiple of 8." in res.error

def test_encoding_tool_invalid_args():
    tool = EncodingTool()

    # missing fmt
    res = tool.run({"format": "invalid", "action": "encode", "text": "A"})
    assert "Format must be 'hex' or 'binary'." in res.error

    # invalid action
    res = tool.run({"format": "hex", "action": "invalid", "text": "A"})
    assert "Action must be 'encode' or 'decode'." in res.error

    # missing text
    res = tool.run({"format": "hex", "action": "encode", "text": ""})
    assert "'text' is required" in res.error

def test_encoding_tool_exception():
    tool = EncodingTool()
    # Mock format instead of str.encode
    with patch("src.tools.encoding_tool.format", side_effect=Exception("Generic Error")):
        res = tool.run({"format": "binary", "action": "encode", "text": "A"})
        assert "Encoding operation failed: Generic Error" in res.error
