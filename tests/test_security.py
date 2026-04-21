"""Tests for src/security.py — URL guard, sanitization, file I/O, rate limit,
tool-arg validation, secret masking."""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.security import (
    ExternalNetworkBlockedError,
    RateLimitExceededError,
    RateLimiter,
    assert_local_url,
    check_path_permissions,
    get_api_key_from_env,
    is_local_url,
    mask_secret,
    sanitize_ai_response,
    secure_write,
    validate_tool_args,
)


# ── is_local_url ──────────────────────────────────────────────────────────────


class TestIsLocalUrl:
    def test_localhost(self):
        assert is_local_url("http://localhost:11434") is True

    def test_127(self):
        assert is_local_url("http://127.0.0.1:8080/v1") is True

    def test_ipv6_loopback(self):
        assert is_local_url("http://[::1]:8080") is True

    def test_private_192(self):
        assert is_local_url("http://192.168.1.100:1234") is True

    def test_private_10(self):
        assert is_local_url("http://10.0.0.5:8080") is True

    def test_private_172(self):
        assert is_local_url("http://172.16.0.1:8080") is True

    def test_external_google(self):
        assert is_local_url("https://api.openai.com/v1") is False

    def test_external_hostname(self):
        assert is_local_url("http://my-server.lan:1234") is False

    def test_external_ip(self):
        assert is_local_url("http://8.8.8.8/v1") is False


# ── assert_local_url ──────────────────────────────────────────────────────────


class TestAssertLocalUrl:
    def test_local_passes(self):
        assert_local_url("http://localhost:11434", allow_external=False)  # no raise

    def test_external_blocked(self):
        with pytest.raises(ExternalNetworkBlockedError):
            assert_local_url("https://api.openai.com", allow_external=False)

    def test_external_allowed_when_opt_in(self):
        # Should not raise when allow_external=True
        assert_local_url("https://api.openai.com", allow_external=True)


# ── sanitize_ai_response ──────────────────────────────────────────────────────


class TestSanitizeAiResponse:
    def test_strips_null_bytes(self):
        assert sanitize_ai_response("hello\x00world") == "helloworld"

    def test_strips_ansi_sequences(self):
        assert sanitize_ai_response("\x1b[1mBold\x1b[0m") == "Bold"

    def test_preserves_newlines_and_tabs(self):
        text = "line1\n\tindented\r\nline2"
        assert sanitize_ai_response(text) == text

    def test_preserves_unicode(self):
        text = "こんにちは 🎉"
        assert sanitize_ai_response(text) == text

    def test_truncates_oversized(self):
        big = "a" * 200_001
        result = sanitize_ai_response(big, max_chars=100)
        assert len(result) == 100

    def test_empty_string(self):
        assert sanitize_ai_response("") == ""

    def test_strips_c0_control_chars(self):
        # \x07 (BEL) should be stripped; \t, \n, \r should be kept
        assert sanitize_ai_response("a\x07b") == "ab"
        assert sanitize_ai_response("a\tb") == "a\tb"


# ── secure_write ──────────────────────────────────────────────────────────────


class TestSecureWrite:
    def test_creates_file_with_content(self, tmp_path):
        p = tmp_path / "out.txt"
        secure_write(p, "hello")
        assert p.read_text() == "hello"

    def test_mode_is_owner_only(self, tmp_path):
        p = tmp_path / "secret.json"
        secure_write(p, "{}")
        file_mode = p.stat().st_mode & 0o777
        assert file_mode == 0o600

    def test_custom_mode(self, tmp_path):
        p = tmp_path / "data.txt"
        secure_write(p, "x", mode=0o400)
        assert (p.stat().st_mode & 0o777) == 0o400

    def test_atomic_no_partial_file(self, tmp_path):
        p = tmp_path / "atom.txt"
        secure_write(p, "first")
        secure_write(p, "second")
        assert p.read_text() == "second"
        # Temp file should be gone
        assert not (tmp_path / "atom.tmp").exists()

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "a" / "b" / "c.txt"
        secure_write(p, "nested")
        assert p.read_text() == "nested"

    def test_cleanup_unlink_oserror(self, tmp_path):
        p = tmp_path / "fail.txt"
        with (
            patch.object(Path, "replace", side_effect=OSError("Mock replace error")),
            patch.object(Path, "unlink", side_effect=OSError("Mock unlink error")),
        ):
            with pytest.raises(OSError, match="Mock replace error"):
                secure_write(p, "data")


# ── check_path_permissions ────────────────────────────────────────────────────


class TestCheckPathPermissions:
    def test_no_warning_on_owner_only(self, tmp_path, caplog):
        import logging

        p = tmp_path / "safe.txt"
        p.write_text("x")
        p.chmod(0o600)
        with caplog.at_level(logging.WARNING):
            check_path_permissions(p, label="test file")
        assert "readable by group or world" not in caplog.text

    def test_warns_on_world_readable(self, tmp_path, caplog):
        import logging

        p = tmp_path / "unsafe.txt"
        p.write_text("x")
        p.chmod(0o644)
        with caplog.at_level(logging.WARNING):
            check_path_permissions(p, label="test file")
        assert "readable by group or world" in caplog.text

    def test_nonexistent_file_no_error(self, tmp_path):
        check_path_permissions(tmp_path / "missing.txt")  # should not raise

    def test_oserror_on_stat(self, tmp_path, caplog):
        import logging

        p = tmp_path / "dummy.txt"
        p.write_text("x")
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "stat", side_effect=OSError("Mocked error")),
        ):
            with caplog.at_level(logging.DEBUG):
                check_path_permissions(p, label="test file")
        assert "Could not check permissions of" in caplog.text


# ── RateLimiter ───────────────────────────────────────────────────────────────


class TestRateLimiter:
    def test_disabled_never_raises(self):
        limiter = RateLimiter(calls_per_minute=0)
        for _ in range(1000):
            limiter.check()  # should never raise

    def test_allows_up_to_limit(self):
        limiter = RateLimiter(calls_per_minute=5)
        for _ in range(5):
            limiter.check()  # should not raise

    def test_raises_when_over_limit(self):
        limiter = RateLimiter(calls_per_minute=3)
        for _ in range(3):
            limiter.check()
        with pytest.raises(RateLimitExceededError):
            limiter.check()

    def test_refills_over_time(self):
        limiter = RateLimiter(calls_per_minute=60)
        # Drain all tokens
        for _ in range(60):
            limiter.check()
        # Should be over limit now
        with pytest.raises(RateLimitExceededError):
            limiter.check()
        # Simulate 1 second passing — should add 1 token
        limiter._last_refill -= 1.0
        limiter.check()  # should succeed now

    def test_thread_safety(self):
        limiter = RateLimiter(calls_per_minute=100)
        errors = []

        def call():
            try:
                limiter.check()
            except RateLimitExceededError:
                errors.append(True)

        threads = [threading.Thread(target=call) for _ in range(150)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Some calls should have been rate-limited
        assert len(errors) >= 50


# ── validate_tool_args ────────────────────────────────────────────────────────


class TestValidateToolArgs:
    def test_strips_null_bytes_from_strings(self):
        result = validate_tool_args({"query": "hello\x00world"})
        assert result["query"] == "helloworld"

    def test_truncates_long_strings(self):
        long_val = "x" * 5000
        result = validate_tool_args({"q": long_val})
        assert len(result["q"]) == 4096

    def test_strips_null_bytes_in_list(self):
        result = validate_tool_args({"items": ["a\x00b", "c"]})
        assert result["items"] == ["ab", "c"]

    def test_passes_through_int_and_bool(self):
        result = validate_tool_args({"count": 5, "flag": True})
        assert result["count"] == 5
        assert result["flag"] is True

    def test_schema_required_field_missing(self):
        schema = {"required": ["name"], "properties": {"name": {"type": "string"}}}
        with pytest.raises(ValueError, match="required argument"):
            validate_tool_args({}, schema=schema)

    def test_schema_type_mismatch(self):
        schema = {"properties": {"count": {"type": "integer"}}}
        with pytest.raises(TypeError):
            validate_tool_args({"count": "not-an-int"}, schema=schema)

    def test_schema_boolean_not_integer(self):
        schema = {"properties": {"n": {"type": "integer"}}}
        with pytest.raises(TypeError):
            validate_tool_args({"n": True}, schema=schema)

    def test_valid_args_pass_through(self):
        schema = {
            "required": ["q"],
            "properties": {
                "q": {"type": "string"},
                "max": {"type": "integer"},
            },
        }
        result = validate_tool_args({"q": "hello", "max": 10}, schema=schema)
        assert result == {"q": "hello", "max": 10}


# ── mask_secret ───────────────────────────────────────────────────────────────


class TestMaskSecret:
    def test_masks_long_key(self):
        masked = mask_secret("sk-abc123xyz")
        assert "sk" in masked
        assert "yz" in masked
        assert "***" in masked
        assert "abc123x" not in masked

    def test_short_secret_fully_masked(self):
        assert mask_secret("short") == "***"
        assert mask_secret("ab") == "***"

    def test_empty_string(self):
        assert mask_secret("") == "***"

    def test_eight_chars_is_masked(self):
        masked = mask_secret("12345678")
        assert "***" in masked


# ── get_api_key_from_env ──────────────────────────────────────────────────────


class TestGetApiKeyFromEnv:
    def test_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("MY_API_KEY", "secret-value")
        from src.security import get_api_key_from_env

        assert get_api_key_from_env("MY_API_KEY") == "secret-value"

    def test_returns_empty_when_unset(self):
        from src.security import get_api_key_from_env

        # Use a name that is definitely not set
        assert get_api_key_from_env("__DEFINITELY_NOT_SET_XYZ__") == ""

    def test_empty_env_var_name(self):
        from src.security import get_api_key_from_env

        assert get_api_key_from_env("") == ""
