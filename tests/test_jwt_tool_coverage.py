import pytest
import base64
import json
from src.tools.jwt_tool import JWTDecoderTool
from unittest.mock import patch

def _encode_jwt(header, payload, sig=""):
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    if sig:
        return f"{h}.{p}.{sig}"
    return f"{h}.{p}"

def test_jwt_tool_invalid_args():
    tool = JWTDecoderTool()

    # Missing token
    res = tool.run({})
    assert "'token' is required" in res.error

    # Invalid format
    res = tool.run({"token": "invalid"})
    assert "Invalid JWT format" in res.error

def test_jwt_tool_decode():
    tool = JWTDecoderTool()

    header = {"alg": "HS256"}
    payload = {"sub": "123"}
    token = _encode_jwt(header, payload, "signature_here")

    res = tool.run({"token": token})
    assert '"alg": "HS256"' in res.results[0].snippet
    assert '"sub": "123"' in res.results[0].snippet
    assert "signature_here" in res.results[0].snippet

def test_jwt_tool_decode_no_sig():
    tool = JWTDecoderTool()

    header = {"alg": "none"}
    payload = {"sub": "123"}
    token = _encode_jwt(header, payload)

    res = tool.run({"token": token})
    assert '"alg": "none"' in res.results[0].snippet
    assert "Signature" not in res.results[0].snippet

def test_jwt_tool_decode_not_json():
    tool = JWTDecoderTool()
    h = base64.urlsafe_b64encode(b"not_json").decode().rstrip("=")
    p = base64.urlsafe_b64encode(b"also_not_json").decode().rstrip("=")
    token = f"{h}.{p}"

    res = tool.run({"token": token})
    assert "not_json" in res.results[0].snippet
    assert "also_not_json" in res.results[0].snippet

def test_jwt_tool_exception():
    tool = JWTDecoderTool()
    with patch("src.tools.jwt_tool._decode_base64url", side_effect=Exception("Generic Error")):
        res = tool.run({"token": "a.b.c"})
        assert "JWT decoding failed" in res.error
