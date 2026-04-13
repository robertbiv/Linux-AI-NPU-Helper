"""Tests for src/config.py."""
from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch
from src.config import load, Config, _deep_merge, _DEFAULTS


class TestDeepMerge:
    def test_flat(self):
        r = _deep_merge({"a": 1}, {"a": 2})
        assert r["a"] == 2

    def test_nested(self):
        r = _deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 99}})
        assert r["a"] == {"x": 1, "y": 99}

    def test_adds_missing(self):
        r = _deep_merge({"a": 1}, {"b": 2})
        assert r["b"] == 2

    def test_does_not_mutate_base(self):
        base = {"a": {"x": 1}}
        _deep_merge(base, {"a": {"x": 2}})
        assert base["a"]["x"] == 1


class TestLoadDefaults:
    def test_backend_default(self):
        cfg = load(path=None)
        assert cfg.backend == "ollama"

    def test_hotkey_default(self):
        cfg = load(path=None)
        assert cfg.hotkey == "copilot"

    def test_network_default(self):
        cfg = load(path=None)
        assert cfg.network["allow_external"] is False

    def test_security_section_exists(self):
        cfg = load(path=None)
        assert isinstance(cfg.security, dict)
        assert "rate_limit_per_minute" in cfg.security

    def test_ollama_section(self):
        cfg = load(path=None)
        assert "base_url" in cfg.ollama
        assert "model" in cfg.ollama

    def test_openai_section(self):
        cfg = load(path=None)
        assert "base_url" in cfg.openai

    def test_tools_section(self):
        cfg = load(path=None)
        assert "search_path" in cfg.tools
        assert "allowed" in cfg.tools
        assert "disallowed" in cfg.tools
        assert "requires_approval" in cfg.tools


class TestLoadFromFile:
    def test_file_overrides_backend(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("backend: openai\n")
        cfg = load(path=p)
        assert cfg.backend == "openai"

    def test_file_deep_merges_ollama(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("ollama:\n  model: llama3\n")
        cfg = load(path=p)
        assert cfg.ollama["model"] == "llama3"
        # base_url should still have the default
        assert "base_url" in cfg.ollama

    def test_missing_file_uses_defaults(self, tmp_path):
        cfg = load(path=tmp_path / "nonexistent.yaml")
        assert cfg.backend == "ollama"

    def test_empty_file_uses_defaults(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("")
        cfg = load(path=p)
        assert cfg.backend == "ollama"

    def test_openai_api_key_env_override(self, tmp_path, monkeypatch):
        p = tmp_path / "config.yaml"
        p.write_text("openai:\n  api_key_env: MY_CUSTOM_API_KEY\n")
        monkeypatch.setenv("MY_CUSTOM_API_KEY", "test-key-123")
        cfg = load(path=p)
        assert cfg.openai["api_key"] == "test-key-123"

    def test_openai_api_key_env_override_missing_env(self, tmp_path, monkeypatch):
        p = tmp_path / "config.yaml"
        p.write_text("openai:\n  api_key_env: MY_CUSTOM_API_KEY\n")
        monkeypatch.delenv("MY_CUSTOM_API_KEY", raising=False)
        cfg = load(path=p)
        assert cfg.openai["api_key"] == ""


class TestConfigProperties:
    def test_repr(self):
        cfg = load(path=None)
        r   = repr(cfg)
        assert "Config" in r
        assert "backend" in r

    def test_contains(self):
        cfg = load(path=None)
        assert "backend" in cfg
        assert "nonexistent_xyz" not in cfg

    def test_getitem(self):
        cfg = load(path=None)
        assert cfg["backend"] == "ollama"

    def test_get_with_default(self):
        cfg = load(path=None)
        assert cfg.get("nonexistent_xyz", "default") == "default"

    def test_resources_section(self):
        cfg = load(path=None)
        assert "stream_response" in cfg.resources

    def test_safety_section(self):
        cfg = load(path=None)
        assert "confirm_commands" in cfg.safety
        assert "blocked_commands" in cfg.safety

    def test_log_level(self):
        cfg = load(path=None)
        assert cfg.log_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

    def test_log_file_default_empty(self):
        cfg = load(path=None)
        assert cfg.log_file == ""
