"""Tests for src/settings.py — SettingsManager."""
from __future__ import annotations
import json
import threading
import pytest
from src.settings import SettingsManager, _get_nested, _set_nested
from src.utils import _deep_merge


class TestDeepMerge:
    def test_flat_override(self):
        result = _deep_merge({"a": 1, "b": 2}, {"b": 99})
        assert result == {"a": 1, "b": 99}

    def test_nested_override(self):
        base     = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 99}}
        result   = _deep_merge(base, override)
        assert result["a"] == {"x": 1, "y": 99}

    def test_adds_new_key(self):
        result = _deep_merge({"a": 1}, {"b": 2})
        assert result["b"] == 2

    def test_does_not_mutate_base(self):
        base = {"a": {"x": 1}}
        _deep_merge(base, {"a": {"x": 99}})
        assert base["a"]["x"] == 1

    def test_non_dict_override_replaces(self):
        result = _deep_merge({"a": {"x": 1}}, {"a": "string"})
        assert result["a"] == "string"


class TestGetSetNested:
    def test_get_top_level(self):
        assert _get_nested({"a": 1}, "a") == 1

    def test_get_nested(self):
        d = {"a": {"b": {"c": 42}}}
        assert _get_nested(d, "a.b.c") == 42

    def test_get_missing_raises(self):
        with pytest.raises(KeyError):
            _get_nested({}, "missing")

    def test_set_top_level(self):
        d = {}
        _set_nested(d, "x", 10)
        assert d["x"] == 10

    def test_set_nested_creates_dicts(self):
        d = {}
        _set_nested(d, "a.b.c", 42)
        assert d["a"]["b"]["c"] == 42

    def test_set_overwrites(self):
        d = {"a": {"b": 1}}
        _set_nested(d, "a.b", 99)
        assert d["a"]["b"] == 99


class TestSettingsManager:
    def test_get_default(self, tmp_path):
        sm = SettingsManager(path=None)
        # backend defaults to "ollama"
        assert sm.get("backend") == "ollama"

    def test_get_missing_returns_default(self, tmp_path):
        sm = SettingsManager(path=None)
        assert sm.get("nonexistent.key", "fallback") == "fallback"

    def test_set_and_get(self, tmp_path):
        sm = SettingsManager(path=None)
        sm.set("backend", "openai", save=False)
        assert sm.get("backend") == "openai"

    def test_set_nested(self, tmp_path):
        sm = SettingsManager(path=None)
        sm.set("ollama.model", "llama3", save=False)
        assert sm.get("ollama.model") == "llama3"

    def test_set_many(self, tmp_path):
        sm = SettingsManager(path=None)
        sm.set_many({"backend": "openai", "ollama.model": "llama3"})
        assert sm.get("backend") == "openai"
        assert sm.get("ollama.model") == "llama3"

    def test_update_section(self, tmp_path):
        sm = SettingsManager(path=None)
        sm.update_section("ollama", {"model": "new-model", "timeout": 60})
        assert sm.get("ollama.model") == "new-model"
        assert sm.get("ollama.timeout") == 60

    def test_get_section(self, tmp_path):
        sm = SettingsManager(path=None)
        section = sm.get_section("ollama")
        assert isinstance(section, dict)
        assert "model" in section

    def test_all_returns_deep_copy(self, tmp_path):
        sm   = SettingsManager(path=None)
        data = sm.all()
        data["backend"] = "modified"
        assert sm.get("backend") == "ollama"  # original unchanged

    def test_persistence(self, tmp_path):
        p  = tmp_path / "settings.json"
        sm = SettingsManager(path=p)
        sm.set("backend", "openai")
        assert p.exists()
        sm2 = SettingsManager(path=p)
        assert sm2.get("backend") == "openai"

    def test_file_mode_is_600(self, tmp_path):
        p  = tmp_path / "settings.json"
        sm = SettingsManager(path=p)
        sm.set("backend", "openai")
        assert (p.stat().st_mode & 0o777) == 0o600

    def test_reload(self, tmp_path):
        p  = tmp_path / "settings.json"
        sm = SettingsManager(path=p)
        sm.set("backend", "openai")
        # Overwrite file externally
        data = json.loads(p.read_text())
        data["backend"] = "ollama"
        p.write_text(json.dumps(data))
        sm.reload()
        assert sm.get("backend") == "ollama"

    def test_listener_called_on_set(self, tmp_path):
        sm      = SettingsManager(path=None)
        calls   = []
        sm.add_listener(lambda k, v: calls.append((k, v)))
        sm.set("backend", "openai", save=False)
        assert calls == [("backend", "openai")]

    def test_listener_called_on_set_many(self, tmp_path):
        sm    = SettingsManager(path=None)
        calls = []
        sm.add_listener(lambda k, v: calls.append(k))
        sm.set_many({"backend": "openai", "ollama.model": "x"})
        assert "backend" in calls
        assert "ollama.model" in calls

    def test_remove_listener(self, tmp_path):
        sm    = SettingsManager(path=None)
        calls = []
        fn    = lambda k, v: calls.append(k)
        sm.add_listener(fn)
        sm.remove_listener(fn)
        sm.set("backend", "openai", save=False)
        assert calls == []

    def test_remove_listener_not_found(self, tmp_path):
        sm = SettingsManager(path=None)
        fn = lambda k, v: None
        # Removing an unregistered listener shouldn't raise ValueError
        sm.remove_listener(fn)

    def test_listener_error_does_not_propagate(self, tmp_path):
        sm = SettingsManager(path=None)

        def faulty_listener(k, v):
            raise RuntimeError("boom")

        sm.add_listener(faulty_listener)
        sm.set("backend", "openai", save=False)  # should not raise

    def test_listener_error_logs_warning(self, tmp_path, mocker, caplog):
        sm = SettingsManager(path=None)

        def faulty_listener(k, v):
            raise RuntimeError("boom")

        mock_logger = mocker.patch("src.settings.logger")
        sm.add_listener(faulty_listener)
        sm.set("backend", "openai", save=False)
        mock_logger.warning.assert_called_once()
        args = mock_logger.warning.call_args[0]
        assert args[0] == "Settings listener raised an error: %s"
        assert isinstance(args[1], RuntimeError)
        assert str(args[1]) == "boom"

    def test_to_config(self, tmp_path):
        sm = SettingsManager(path=None)
        sm.set("backend", "openai", save=False)
        cfg = sm.to_config()
        assert cfg.backend == "openai"

    def test_thread_safety(self, tmp_path):
        sm     = SettingsManager(path=None)
        errors = []
        def writer(n):
            try:
                sm.set("ollama.timeout", n, save=False)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors

    def test_bad_json_file_ignored(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text("NOT JSON")
        sm = SettingsManager(path=p)
        # Should not raise; just use defaults
        assert sm.get("backend") == "ollama"

    def test_path_permission_error_ignored(self, tmp_path, mocker):
        p = tmp_path / "settings.json"
        p.write_text("{}")
        mock_check = mocker.patch("src.settings.check_path_permissions")
        mock_check.side_effect = OSError("Permission denied")

        sm = SettingsManager(path=p)
        # Should not raise; defaults used
        assert sm.get("backend") == "ollama"
