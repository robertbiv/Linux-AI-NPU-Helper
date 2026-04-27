"""Tests for src/model_selector.py."""

from __future__ import annotations
import sys
from unittest.mock import MagicMock, patch

# Mock missing dependencies
if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock()
if "yaml" not in sys.modules:
    sys.modules["yaml"] = MagicMock()

import pytest
from src.model_selector import ModelInfo, ModelSelector, _parse_model_info


class TestModelInfo:
    def test_size_gb_zero(self):
        m = ModelInfo(name="test")
        assert m.size_gb == 0.0

    def test_size_gb_conversion(self):
        m = ModelInfo(name="test", size_bytes=2 * 1024**3)
        assert abs(m.size_gb - 2.0) < 0.01

    def test_str_includes_name(self):
        m = ModelInfo(name="llama3:8b")
        assert "llama3:8b" in str(m)

    def test_str_includes_size(self):
        m = ModelInfo(name="llama3:8b", size_bytes=4 * 1024**3)
        s = str(m)
        assert "4.0 GB" in s

    def test_str_vision_flag(self):
        m = ModelInfo(name="llava:7b", is_vision=True)
        assert "vision" in str(m)

    def test_str_quantization(self):
        m = ModelInfo(name="llama3:8b-q4_K_M", quantization="q4_k_m")
        assert "q4_k_m" in str(m)


class TestParseModelInfo:
    def test_detects_quantization_q4(self):
        m = _parse_model_info("llama3:8b-q4_K_M", {})
        assert "q4" in m.quantization.lower()

    def test_detects_vision_llava(self):
        m = _parse_model_info("llava:13b", {})
        assert m.is_vision is True

    def test_non_vision(self):
        m = _parse_model_info("llama3:8b", {})
        assert m.is_vision is False

    def test_family_from_name(self):
        m = _parse_model_info("llama3:8b", {})
        assert m.family == "llama"

    def test_family_mistral(self):
        m = _parse_model_info("mistral:7b", {})
        assert m.family == "mistral"

    def test_size_from_raw(self):
        m = _parse_model_info("model", {"size": 1024**3})
        assert abs(m.size_gb - 1.0) < 0.01

    def test_family_from_ollama_details(self):
        m = _parse_model_info("model", {"details": {"family": "gemma"}})
        assert m.family == "gemma"

    def test_quantization_from_details(self):
        m = _parse_model_info("model", {"details": {"quantization_level": "Q8_0"}})
        # If not in name, uses details
        assert m.quantization == "Q8_0"

    def test_f16_detected(self):
        m = _parse_model_info("llama3:8b-f16", {})
        assert "f16" in m.quantization.lower()

    def test_parse_malformed_raw(self):
        """Verify that _parse_model_info handles missing/None fields gracefully."""
        # Case 1: 'details' is None (crashes original code)
        m = _parse_model_info("test", {"details": None})
        assert m.name == "test"
        assert m.family == ""

        # Case 2: 'details' is missing entirely
        m = _parse_model_info("test", {})
        assert m.name == "test"
        assert m.family == ""


class TestNpuWarning:
    def _make_config(self, backend="ollama", model="llava"):
        cfg = MagicMock()
        cfg.backend = backend
        cfg.ollama = {"base_url": "http://localhost:11434", "model": model}
        cfg.openai = {"base_url": "http://localhost:1234/v1", "model": model}
        cfg.npu = {"model_path": ""}
        cfg.network = {"allow_external": False}
        cfg.get = MagicMock(return_value={})
        return cfg

    def test_llava_warns(self):
        sel = ModelSelector(self._make_config())
        w = sel.npu_warning(ModelInfo(name="llava:13b", is_vision=True))
        assert w is not None
        assert "⚠" in w or "⛔" in w

    def test_70b_blocked(self):
        sel = ModelSelector(self._make_config())
        w = sel.npu_warning(ModelInfo(name="llama3:70b"))
        assert w is not None
        assert "⛔" in w

    def test_small_quantized_ok(self):
        sel = ModelSelector(self._make_config())
        w = sel.npu_warning(ModelInfo(name="llama3:3b-q4_K_M", quantization="q4_k_m"))
        # Should be ok (None) or at least not ⛔
        if w is not None:
            assert "⛔" not in w

    def test_onnx_ok(self):
        sel = ModelSelector(self._make_config())
        w = sel.npu_warning(ModelInfo(name="/path/to/model.onnx"))
        assert w is None

    def test_f16_warns(self):
        sel = ModelSelector(self._make_config())
        w = sel.npu_warning(ModelInfo(name="llama3:8b-f16"))
        assert w is not None

    def test_embed_warns(self):
        sel = ModelSelector(self._make_config())
        w = sel.npu_warning(ModelInfo(name="nomic-embed-text"))
        assert w is not None

    def test_string_input(self):
        sel = ModelSelector(self._make_config())
        w = sel.npu_warning("llava:7b")
        assert w is not None

    def test_large_model_size_warning(self):
        sel = ModelSelector(self._make_config())
        big = ModelInfo(name="some-model", size_bytes=20 * 1024**3)
        w = sel.npu_warning(big)
        assert w is not None
        assert "GB" in w

    def test_small_model_no_size_warning(self):
        sel = ModelSelector(self._make_config())
        small = ModelInfo(name="phi3:mini", size_bytes=2 * 1024**3)
        w = sel.npu_warning(small)
        # No size-based warning for 2 GB model
        # (rule-based might still match, just check it doesn't mention "GB")
        # Only check if it passes all rules without generic size warning
        if w is not None and "GB" in w:
            pytest.fail(f"Unexpected size warning for small model: {w}")

    def test_npu_tops_limits_size(self):
        sel = ModelSelector(self._make_config())
        mid_model = ModelInfo(name="phi3:medium", size_bytes=6 * 1024**3)

        with patch("src.npu_benchmark.probe_hardware") as mock_probe:
            hw = MagicMock()
            hw.ram_gb = 32.0  # Lots of ram, normally ok up to 16gb

            # Low NPU TOPS (<10), limit 3.0 GB
            hw.npu_tops = 5.0
            mock_probe.return_value = hw
            w = sel.npu_warning(mid_model)
            assert w is not None and "capabilities" in w

            # Mid NPU TOPS (<30), limit 8.0 GB
            hw.npu_tops = 20.0
            mock_probe.return_value = hw
            w = sel.npu_warning(mid_model)
            assert w is None or "capabilities" not in w  # Should be fine now


class TestGetCurrentModel:
    def _make_config(self, backend, model):
        cfg = MagicMock()
        cfg.backend = backend
        cfg.ollama = {"model": model}
        cfg.openai = {"model": model}
        cfg.npu = {"model_path": model}
        return cfg

    def test_ollama(self):
        sel = ModelSelector(self._make_config("ollama", "llava"))
        assert sel.get_current_model() == "llava"

    def test_openai(self):
        sel = ModelSelector(self._make_config("openai", "local-model"))
        assert sel.get_current_model() == "local-model"

    def test_npu(self):
        sel = ModelSelector(self._make_config("npu", "/path/to/model.onnx"))
        assert sel.get_current_model() == "/path/to/model.onnx"

    def test_unknown_backend_returns_empty(self):
        cfg = MagicMock()
        cfg.backend = "unknown"
        sel = ModelSelector(cfg)
        assert sel.get_current_model() == ""


class TestSetModel:
    def _make_config(self, backend):
        cfg = MagicMock()
        cfg.backend = backend
        cfg._data = {
            "ollama": {"model": "old"},
            "openai": {"model": "old"},
            "npu": {"model_path": "old"},
        }
        return cfg

    def test_set_ollama(self):
        cfg = self._make_config("ollama")
        ModelSelector(cfg).set_model("llama3:8b")
        assert cfg._data["ollama"]["model"] == "llama3:8b"

    def test_set_openai(self):
        cfg = self._make_config("openai")
        ModelSelector(cfg).set_model("new-model")
        assert cfg._data["openai"]["model"] == "new-model"

    def test_set_npu(self):
        cfg = self._make_config("npu")
        ModelSelector(cfg).set_model("/new/path.onnx")
        assert cfg._data["npu"]["model_path"] == "/new/path.onnx"


class TestListModels:
    def _make_config(self, backend="ollama"):
        cfg = MagicMock()
        cfg.backend = backend
        cfg.ollama = {"base_url": "http://localhost:11434", "model": "llava"}
        cfg.openai = {
            "base_url": "http://localhost:1234/v1",
            "model": "x",
            "api_key": "",
        }
        cfg.npu = {"model_path": "/path/to/model.onnx"}
        cfg.network = {"allow_external": False}
        return cfg

    def test_npu_returns_model_path(self):
        sel = ModelSelector(self._make_config("npu"))
        models = sel.list_models().result()
        assert len(models) == 1
        assert models[0].name == "/path/to/model.onnx"

    def test_npu_empty_path_returns_empty(self):
        cfg = self._make_config("npu")
        cfg.npu = {"model_path": ""}
        sel = ModelSelector(cfg)
        assert sel.list_models().result() == []

    def test_ollama_returns_sorted(self):
        cfg = self._make_config("ollama")
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "models": [
                {"name": "zzz:7b", "size": 0},
                {"name": "aaa:3b", "size": 0},
            ]
        }
        fake_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=fake_resp):
            models = ModelSelector(cfg).list_models().result()
        assert models[0].name == "aaa:3b"
        assert models[1].name == "zzz:7b"

    def test_unreachable_backend_returns_empty(self):
        cfg = self._make_config("ollama")
        with patch("requests.get", side_effect=Exception("Connection refused")):
            models = ModelSelector(cfg).list_models().result()
        assert models == []

    def test_unknown_backend_returns_empty(self):
        cfg = self._make_config("unknown_backend")
        sel = ModelSelector(cfg)
        assert sel.list_models().result() == []


class TestModelSummary:
    def _make_config(self):
        cfg = MagicMock()
        cfg.backend = "ollama"
        cfg.ollama = {"base_url": "http://localhost:11434", "model": "llava"}
        cfg.network = {"allow_external": False}
        cfg.get = MagicMock(return_value={})
        return cfg

    def test_summary_keys(self):
        sel = ModelSelector(self._make_config())
        m = ModelInfo(
            name="llama3:8b",
            size_bytes=4 * 1024**3,
            family="llama",
            quantization="q4_k_m",
        )
        s = sel.model_summary(m)
        for key in (
            "name",
            "size_gb",
            "family",
            "quantization",
            "is_vision",
            "npu_ok",
            "npu_warning",
        ):
            assert key in s, f"Missing key {key!r}"

    def test_summary_npu_ok_for_onnx(self):
        sel = ModelSelector(self._make_config())
        m = ModelInfo(name="/path/model.onnx")
        s = sel.model_summary(m)
        assert s["npu_ok"] is True
        assert s["npu_warning"] == ""
