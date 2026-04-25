import pytest
from unittest.mock import patch, MagicMock
from src.tools.web_fetch import (
    WebFetchTool,
    WebFetchConfig,
    _resolve_and_check_ip,
    _html_to_text,
)



def test_is_private_ip():
    assert _resolve_and_check_ip("localhost")[0] is True
    assert _resolve_and_check_ip("127.0.0.1")[0] is True
    assert _resolve_and_check_ip("192.168.1.1")[0] is True
    assert _resolve_and_check_ip("10.0.0.1")[0] is True
    assert _resolve_and_check_ip("172.16.0.1")[0] is True
    assert _resolve_and_check_ip("8.8.8.8")[0] is False
    assert _resolve_and_check_ip("example.com")[0] is False

@patch("socket.gethostbyname")
def test_is_private_ip_dns_resolution(mock_gethostbyname):
    # Test that a domain resolving to a private IP is blocked
    mock_gethostbyname.return_value = "127.0.0.1"
    assert _resolve_and_check_ip("attacker.com")[0] is True

    mock_gethostbyname.return_value = "192.168.1.100"
    assert _resolve_and_check_ip("internal.network")[0] is True

    mock_gethostbyname.return_value = "8.8.8.8"
    assert _resolve_and_check_ip("public.domain")[0] is False

    mock_gethostbyname.side_effect = Exception("DNS failure")
    assert _resolve_and_check_ip("unknown.domain")[0] is True


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
def test_web_fetch_tool_run_redirect_blocked(mock_session_cls):
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.is_redirect = True
    mock_resp.headers = {"location": "http://127.0.0.1/admin"}
    mock_session.get.return_value = mock_resp
    mock_session_cls.return_value = mock_session

    tool = WebFetchTool()
    res = tool.run({"url": "http://example.com"})
    assert res.error
    assert "blocked" in res.error


@patch("requests.Session")
def test_web_fetch_tool_run_redirect_success(mock_session_cls):
    mock_session = MagicMock()

    mock_resp_1 = MagicMock()
    mock_resp_1.is_redirect = True
    mock_resp_1.headers = {"location": "http://example.com/page2"}

    mock_resp_2 = MagicMock()
    mock_resp_2.is_redirect = False
    mock_resp_2.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_resp_2.encoding = "utf-8"
    mock_resp_2.raw.read.return_value = b"<html><body>redirect success</body></html>"

    mock_session.get.side_effect = [mock_resp_1, mock_resp_2]
    mock_session_cls.return_value = mock_session

    tool = WebFetchTool()
    res = tool.run({"url": "http://example.com"})
    assert not res.error
    assert "redirect success" in res.results[0].snippet


@patch("requests.Session")
def test_web_fetch_tool_run_too_many_redirects(mock_session_cls):
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.is_redirect = True
    mock_resp.headers = {"location": "http://example.com/loop"}
    mock_session.get.return_value = mock_resp
    mock_session_cls.return_value = mock_session

    tool = WebFetchTool(config=WebFetchConfig(max_redirects=2))
    res = tool.run({"url": "http://example.com"})
    assert res.error
    assert "Too many redirects" in res.error


@patch("requests.Session")
def test_web_fetch_tool_run_success(mock_session_cls):
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.is_redirect = False
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
    mock_resp.is_redirect = False
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
