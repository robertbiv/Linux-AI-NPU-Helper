"""Tests for src/gui/diagnostic_reporter.py."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from src.gui.diagnostic_reporter import (
    DiagnosticReporter,
    STATUS_OK, STATUS_WARN, STATUS_FAIL, STATUS_SKIP,
)


def _make_config(backend="ollama", allow_external=False):
    cfg = MagicMock()
    cfg.backend = backend
    cfg.ollama  = {"base_url": "http://localhost:11434", "model": "llava"}
    cfg.openai  = {"base_url": "http://localhost:1234/v1", "model": "x", "api_key": ""}
    cfg.npu     = {"model_path": ""}
    cfg.network = {"allow_external": allow_external}
    cfg.get     = MagicMock(return_value={})
    return cfg


class TestCheckBackend:
    def test_npu_ok_without_http(self):
        cfg = _make_config("npu")
        r   = DiagnosticReporter(cfg).check_backend()
        assert r["status"] == STATUS_OK
        assert r["url"] == "in-process"

    def test_unknown_backend_fail(self):
        cfg = _make_config("unknown_backend")
        r   = DiagnosticReporter(cfg).check_backend()
        assert r["status"] == STATUS_FAIL

    def test_ollama_ok_on_200(self):
        cfg      = _make_config("ollama")
        fake_req = MagicMock()
        fake_req.status_code = 200
        with patch("requests.get", return_value=fake_req):
            r = DiagnosticReporter(cfg).check_backend(timeout=1)
        assert r["status"] == STATUS_OK
        assert r["latency_ms"] is not None

    def test_ollama_fail_on_connection_error(self):
        cfg = _make_config("ollama")
        with patch("requests.get", side_effect=Exception("refused")):
            r = DiagnosticReporter(cfg).check_backend(timeout=1)
        assert r["status"] == STATUS_FAIL
        assert "refused" in r["error"]

    def test_no_requests_module(self):
        cfg = _make_config("ollama")
        with patch.dict("sys.modules", {"requests": None}):
            r = DiagnosticReporter(cfg).check_backend(timeout=1)
        assert r["status"] in (STATUS_WARN, STATUS_FAIL, STATUS_SKIP)


class TestCheckNpu:
    def test_no_onnxruntime(self):
        with patch.dict("sys.modules", {"onnxruntime": None}):
            r = DiagnosticReporter(_make_config()).check_npu()
        assert r["status"] == STATUS_WARN
        assert "not installed" in r["error"]

    def test_vitis_available(self):
        mock_ort = MagicMock()
        mock_ort.__version__ = "1.18.0"
        mock_ort.get_available_providers.return_value = [
            "VitisAIExecutionProvider", "CPUExecutionProvider"
        ]
        with patch.dict("sys.modules", {"onnxruntime": mock_ort}):
            r = DiagnosticReporter(_make_config()).check_npu()
        assert r["available"] is True
        assert r["status"] == STATUS_OK

    def test_cpu_only(self):
        mock_ort = MagicMock()
        mock_ort.__version__ = "1.18.0"
        mock_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": mock_ort}):
            r = DiagnosticReporter(_make_config()).check_npu()
        assert r["available"] is False
        assert r["status"] == STATUS_WARN


class TestCheckTools:
    def test_no_registry(self):
        r = DiagnosticReporter(_make_config()).check_tools()
        assert isinstance(r, list)
        assert r[0]["status"] == STATUS_SKIP

    def test_with_registry(self):
        mock_desc = MagicMock()
        mock_desc.is_loaded      = False
        mock_desc.unload_after_use = True
        mock_desc.description    = "Test tool"
        mock_reg = MagicMock()
        mock_reg._descriptors    = {"my_tool": mock_desc}
        r = DiagnosticReporter(_make_config(), registry=mock_reg).check_tools()
        assert len(r) == 1
        assert r[0]["name"]   == "my_tool"
        assert r[0]["status"] == STATUS_OK
        assert r[0]["loaded"] is False


class TestCheckSecurity:
    def test_allow_external_warns(self):
        cfg = _make_config(allow_external=True)
        r   = DiagnosticReporter(cfg).check_security()
        assert r["issues"] > 0
        assert r["status"] == STATUS_WARN

    def test_no_external_ok(self):
        cfg = _make_config(allow_external=False)
        r   = DiagnosticReporter(cfg).check_security()
        network_check = next(c for c in r["checks"] if "network" in c["label"].lower())
        assert network_check["status"] == STATUS_OK

    def test_rate_limiter_present(self):
        cfg = _make_config()
        cfg.get = MagicMock(return_value={"rate_limit_per_minute": 60})
        r = DiagnosticReporter(cfg).check_security()
        rate_check = next(c for c in r["checks"] if "rate" in c["label"].lower())
        assert rate_check["status"] == STATUS_OK


class TestCheckNetwork:
    def test_local_url_ok(self):
        r = DiagnosticReporter(_make_config("ollama")).check_network()
        assert r["backend_url_is_local"] is True
        assert r["status"] == STATUS_OK

    def test_external_url_fail_when_not_allowed(self):
        cfg = _make_config("openai")
        cfg.openai = {"base_url": "https://api.openai.com/v1", "model": "x", "api_key": ""}
        r = DiagnosticReporter(cfg).check_network()
        assert r["status"] == STATUS_FAIL

    def test_npu_inprocess_ok(self):
        r = DiagnosticReporter(_make_config("npu")).check_network()
        assert r["backend_url"] == "in-process"
        assert r["backend_url_is_local"] is True


class TestCheckSettings:
    def test_basic_keys_present(self):
        r = DiagnosticReporter(_make_config()).check_settings()
        for key in ("status", "path", "exists", "backend", "model"):
            assert key in r, f"Missing key {key!r}"

    def test_with_settings_manager(self):
        mock_sm = MagicMock()
        mock_sm._listeners = [1, 2, 3]
        r = DiagnosticReporter(_make_config(), settings_manager=mock_sm).check_settings()
        assert r["listener_count"] == 3


class TestCheckSystem:
    def test_returns_dict_with_keys(self):
        r = DiagnosticReporter(_make_config()).check_system()
        for key in ("status", "python_version", "app_version", "is_immutable"):
            assert key in r

    @patch("src.os_detector.detect")
    def test_shell_detection_exception_handled(self, mock_os_detect):
        # Prevent OS detection from failing and changing the status to WARN
        mock_info = MagicMock()
        mock_info.name = "TestOS"
        mock_info.version = "1.0"
        mock_info.id = "test"
        mock_info.package_manager = "apt"
        mock_info.desktop_environment = "gnome"
        mock_info.kernel = "test-kernel"
        mock_info.architecture = "x86_64"
        mock_info.is_immutable = False
        mock_os_detect.return_value = mock_info

        with patch("src.shell_detector.detect", side_effect=Exception("Mock shell error")):
            r = DiagnosticReporter(_make_config()).check_system()

        assert r["shell"] == ""
        assert r["status"] == STATUS_OK


class TestCheckDependencies:
    def test_returns_list(self):
        deps = DiagnosticReporter(_make_config()).check_dependencies()
        assert isinstance(deps, list)
        assert len(deps) > 0

    def test_each_dep_has_keys(self):
        deps = DiagnosticReporter(_make_config()).check_dependencies()
        for d in deps:
            for k in ("name", "status", "version", "required", "detail"):
                assert k in d

    def test_yaml_is_required(self):
        deps = DiagnosticReporter(_make_config()).check_dependencies()
        yaml_entry = next((d for d in deps if d["name"] == "yaml"), None)
        assert yaml_entry is not None
        assert yaml_entry["required"] is True


class TestFullReport:
    def test_structure(self):
        with patch("requests.get", side_effect=Exception("offline")):
            r = DiagnosticReporter(_make_config()).full_report()
        for key in ("timestamp","app_version","overall_status","backend",
                    "npu","tools","security","settings","system","network","dependencies"):
            assert key in r

    def test_overall_fail_when_backend_fails(self):
        with patch("requests.get", side_effect=Exception("refused")):
            r = DiagnosticReporter(_make_config()).full_report()
        assert r["backend"]["status"] == STATUS_FAIL
        assert r["overall_status"] in (STATUS_FAIL, STATUS_WARN)

    def test_timestamp_is_iso(self):
        with patch("requests.get", side_effect=Exception("offline")):
            r = DiagnosticReporter(_make_config()).full_report()
        import datetime
        # Should parse without error
        datetime.datetime.fromisoformat(r["timestamp"])
