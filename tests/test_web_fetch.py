import pytest
from unittest.mock import patch, MagicMock
from src.tools.web_fetch import (
    WebFetchTool,
    WebFetchConfig,
    _is_private_ip,
    _html_to_text,
)



def test_is_private_ip():
    assert _is_private_ip("localhost") is True
    assert _is_private_ip("127.0.0.1") is True
    assert _is_private_ip("192.168.1.1") is True
    assert _is_private_ip("10.0.0.1") is True
    assert _is_private_ip("172.16.0.1") is True
    assert _is_private_ip("8.8.8.8") is False
    assert _is_private_ip("example.com") is False


def test_html_to_text():
    html = "<html><head><title>Title</title><script>js</script></head><body><p>Hello <b>world</b>!</p></body></html>"
    text = _html_to_text(html)
    assert "Hello world!" in text
    assert "js" not in text
    assert "Title" not in text


def test_web_fetch_tool_run_missing_url():
    tool = WebFetchTool()
    res = tool.run({})
    assert res.error
    assert "required" in res.error


def test_web_fetch_tool_run_invalid_url():
    tool = WebFetchTool()
    res = tool.run({"url": "ftp://example.com"})
    assert res.error
    assert "Only http:// and https://" in res.error


def test_web_fetch_tool_run_private_ip():
    tool = WebFetchTool()
    res = tool.run({"url": "http://127.0.0.1/test"})
    assert res.error
    assert "blocked for security" in res.error


def test_web_fetch_tool_allowlist():
    tool = WebFetchTool(config=WebFetchConfig(domain_allowlist=["allowed.com"]))
    res = tool.run({"url": "http://blocked.com"})
    assert res.error
    assert "not in the allowed list" in res.error


def test_web_fetch_tool_blocklist():
    tool = WebFetchTool(config=WebFetchConfig(domain_blocklist=["blocked.com"]))
    res = tool.run({"url": "http://blocked.com"})
    assert res.error
    assert "blocked by configuration" in res.error


@patch("requests.Session")
def test_web_fetch_tool_run_success(mock_session_cls):
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_resp.encoding = "utf-8"
    mock_resp.raw.read.return_value = b"<html><body>hello world</body></html>"
    mock_session.get.return_value = mock_resp
    mock_session_cls.return_value = mock_session

    tool = WebFetchTool()
    res = tool.run({"url": "http://example.com"})
    assert not res.error
    assert "hello world" in res.results[0].snippet


@patch("requests.Session")
def test_web_fetch_tool_run_unsupported_type(mock_session_cls):
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Type": "application/octet-stream"}
    mock_session.get.return_value = mock_resp
    mock_session_cls.return_value = mock_session

    tool = WebFetchTool()
    res = tool.run({"url": "http://example.com/file.bin"})
    assert res.error
    assert "not in the allowed list" in res.error


@patch("requests.Session")
def test_web_fetch_tool_run_exception(mock_session_cls):
    import requests

    mock_session = MagicMock()
    mock_session.get.side_effect = requests.exceptions.RequestException("network error")
    mock_session_cls.return_value = mock_session

    tool = WebFetchTool()
    res = tool.run({"url": "http://example.com"})
    assert res.error
    assert "Request failed: network error" in res.error
