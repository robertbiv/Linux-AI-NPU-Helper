"""Extensive tests for src/npu_manager.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from src.npu_manager import NPUSession, NPUManager


# ── NPUSession ────────────────────────────────────────────────────────────────


class TestNPUSession:
    """Test NPUSession with a mocked onnxruntime."""

    def _mock_ort(self, available_providers=None):
        """Return a mock onnxruntime module."""
        ort = MagicMock()
        ort.get_available_providers.return_value = available_providers or [
            "VitisAIExecutionProvider",
            "OpenVINOExecutionProvider",
            "QNNExecutionProvider",
            "CPUExecutionProvider",
        ]
        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "input_ids"
        mock_output = MagicMock()
        mock_output.name = "logits"
        mock_session.get_inputs.return_value = [mock_input]
        mock_session.get_outputs.return_value = [mock_output]
        mock_session.run.return_value = [[1, 2, 3]]
        ort.InferenceSession.return_value = mock_session
        ort.SessionOptions.return_value = MagicMock()
        return ort, mock_session

    def test_raises_if_onnxruntime_not_installed(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        with patch.dict("sys.modules", {"onnxruntime": None}):
            with pytest.raises((RuntimeError, ImportError)):
                NPUSession(model)

    def test_raises_if_model_not_found(self):
        ort, _ = self._mock_ort()
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            with pytest.raises(FileNotFoundError):
                NPUSession("/nonexistent/model.onnx")

    def test_creates_session_with_cpu_provider(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        ort, mock_session = self._mock_ort(["CPUExecutionProvider"])
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            sess = NPUSession(model, providers=["CPUExecutionProvider"])
        assert sess.is_open

    def test_run_returns_output(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        ort, mock_session = self._mock_ort()
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            sess = NPUSession(model, providers=["CPUExecutionProvider"])
            outputs = sess.run({"input_ids": [1, 2, 3]})
        assert outputs == [[1, 2, 3]]

    def test_close_marks_session_closed(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        ort, mock_session = self._mock_ort()
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            sess = NPUSession(model, providers=["CPUExecutionProvider"])
            assert sess.is_open
            sess.close()
            assert not sess.is_open

    def test_run_after_close_raises(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        ort, _ = self._mock_ort()
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            sess = NPUSession(model, providers=["CPUExecutionProvider"])
            sess.close()
            with pytest.raises(RuntimeError, match="closed"):
                sess.run({})

    def test_context_manager_closes_on_exit(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        ort, _ = self._mock_ort()
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            with NPUSession(model, providers=["CPUExecutionProvider"]) as sess:
                assert sess.is_open
            assert not sess.is_open

    def test_input_names_exposed(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        ort, _ = self._mock_ort()
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            sess = NPUSession(model, providers=["CPUExecutionProvider"])
            assert sess.input_names == ["input_ids"]

    def test_output_names_exposed(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        ort, _ = self._mock_ort()
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            sess = NPUSession(model, providers=["CPUExecutionProvider"])
            assert sess.output_names == ["logits"]

    def test_vitisai_config_used_when_available(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        cfg = tmp_path / "vitisai.json"
        cfg.write_text("{}")
        ort, _ = self._mock_ort()
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            sess = NPUSession(
                model,
                providers=["VitisAIExecutionProvider"],
                vitisai_config=cfg,
            )
        # VitisAI provider should have been passed with config dict
        call_args = ort.InferenceSession.call_args
        providers_arg = call_args[1]["providers"]
        assert any(
            isinstance(p, tuple) and p[0] == "VitisAIExecutionProvider"
            for p in providers_arg
        )

    def test_unavailable_provider_skipped(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        ort, _ = self._mock_ort(available_providers=["CPUExecutionProvider"])
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            # Request VitisAI + CPU; only CPU is available
            sess = NPUSession(
                model,
                providers=["VitisAIExecutionProvider", "CPUExecutionProvider"],
            )
        call_args = ort.InferenceSession.call_args
        providers_arg = call_args[1]["providers"]
        # VitisAI should have been dropped
        assert "CPUExecutionProvider" in providers_arg or any(
            isinstance(p, str) and "CPU" in p for p in providers_arg
        )

    def test_fallback_to_cpu_when_all_unavailable(self, tmp_path):
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake")
        ort, _ = self._mock_ort(available_providers=["CPUExecutionProvider"])
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            sess = NPUSession(model, providers=["VitisAIExecutionProvider"])
        # Should not raise — falls back to CPU
        assert sess.is_open


# ── NPUManager ────────────────────────────────────────────────────────────────


class TestNPUManager:
    def _cfg(self, model_path="", auto_install=False):
        return {
            "model_path": model_path,
            "providers": ["CPUExecutionProvider"],
            "vitisai_config": None,
            "auto_install_default_model": auto_install,
        }

    def test_is_npu_available_true(self):
        mgr = NPUManager(self._cfg())
        ort = MagicMock()
        ort.get_available_providers.return_value = ["VitisAIExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            assert mgr.is_npu_available() is True

    def test_is_npu_available_openvino(self):
        mgr = NPUManager(self._cfg())
        ort = MagicMock()
        ort.get_available_providers.return_value = ["OpenVINOExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            assert mgr.is_npu_available() is True

    def test_is_npu_available_qnn(self):
        mgr = NPUManager(self._cfg())
        ort = MagicMock()
        ort.get_available_providers.return_value = ["QNNExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            assert mgr.is_npu_available() is True

    def test_is_npu_available_openvino(self):
        mgr = NPUManager(self._cfg())
        ort = MagicMock()
        ort.get_available_providers.return_value = ["OpenVINOExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            assert mgr.is_npu_available() is True

    def test_is_npu_available_qnn(self):
        mgr = NPUManager(self._cfg())
        ort = MagicMock()
        ort.get_available_providers.return_value = ["QNNExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            assert mgr.is_npu_available() is True

    def test_is_npu_available_false(self):
        mgr = NPUManager(self._cfg())
        ort = MagicMock()
        ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            assert mgr.is_npu_available() is False

    def test_is_npu_available_no_onnxruntime(self):
        mgr = NPUManager(self._cfg())
        with patch.dict("sys.modules", {"onnxruntime": None}):
            assert mgr.is_npu_available() is False

    def test_is_npu_available_cached(self):
        mgr = NPUManager(self._cfg())
        ort = MagicMock()
        ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            mgr.is_npu_available()
            mgr.is_npu_available()  # Second call should use cache
        # get_available_providers called only once due to caching
        assert ort.get_available_providers.call_count == 1

    def test_load_model_no_path_returns_none(self):
        mgr = NPUManager(self._cfg(model_path=""))
        assert mgr.load_model() is None

    def test_load_model_auto_calls_installer(self):
        mgr = NPUManager(self._cfg(model_path="auto", auto_install=True))
        with patch.object(mgr, "_resolve_auto_model", return_value="") as mock_resolve:
            result = mgr.load_model()
        mock_resolve.assert_called_once()
        assert result is None

    def test_load_model_auto_path_installs(self, tmp_path):
        from src.npu_model_installer import _MIN_ONNX_SIZE_BYTES, ONNX_FILENAME

        onnx_file = tmp_path / ONNX_FILENAME
        onnx_file.write_bytes(b"\x00" * (_MIN_ONNX_SIZE_BYTES + 1))

        mgr = NPUManager(self._cfg(model_path="auto", auto_install=True))

        with patch("src.npu_model_installer.NPUModelInstaller") as MockInst:
            mock_i = MagicMock()
            mock_i.is_installed.return_value = True
            mock_i.model_path.return_value = onnx_file
            MockInst.return_value = mock_i
            with patch("src.npu_manager.NPUSession") as MockSess:
                mock_s = MagicMock()
                mock_s.is_open = True
                MockSess.return_value = mock_s
                sess = mgr.load_model()

        assert sess is not None

    def test_load_model_caches_session(self, tmp_path):
        onnx = tmp_path / "m.onnx"
        onnx.write_bytes(b"x")
        mgr = NPUManager(self._cfg(model_path=str(onnx)))
        with patch("src.npu_manager.NPUSession") as MockSess:
            mock_s = MagicMock()
            MockSess.return_value = mock_s
            sess1 = mgr.load_model()
            sess2 = mgr.load_model()
        assert sess1 is sess2
        assert MockSess.call_count == 1

    def test_unload_clears_session(self, tmp_path):
        onnx = tmp_path / "m.onnx"
        onnx.write_bytes(b"x")
        mgr = NPUManager(self._cfg(model_path=str(onnx)))
        with patch("src.npu_manager.NPUSession") as MockSess:
            MockSess.return_value = MagicMock()
            mgr.load_model()
            assert mgr._session is not None
            mgr.unload()
            assert mgr._session is None

    def test_run_inference_calls_session_run(self, tmp_path):
        onnx = tmp_path / "m.onnx"
        onnx.write_bytes(b"x")
        mgr = NPUManager(self._cfg(model_path=str(onnx)))
        feeds = {"input_ids": [1, 2]}
        with patch("src.npu_manager.NPUSession") as MockSess:
            mock_s = MagicMock()
            mock_s.run.return_value = ["output"]
            MockSess.return_value = mock_s
            outputs = mgr.run_inference(feeds)
        assert outputs == ["output"]
        # run_inference calls NPUSession.run(feeds) — the NPUSession mock is mock_s
        mock_s.run.assert_called_once_with(feeds)

    def test_run_inference_unloads_by_default(self, tmp_path):
        onnx = tmp_path / "m.onnx"
        onnx.write_bytes(b"x")
        resource_cfg = {"unload_model_after_inference": True}
        mgr = NPUManager(self._cfg(model_path=str(onnx)), resource_cfg)
        with patch("src.npu_manager.NPUSession") as MockSess:
            MockSess.return_value = MagicMock()
            mgr.run_inference({"input_ids": []})
        assert mgr._session is None

    def test_run_inference_unloads_on_error(self, tmp_path):
        onnx = tmp_path / "m.onnx"
        onnx.write_bytes(b"x")
        resource_cfg = {"unload_model_after_inference": True}
        mgr = NPUManager(self._cfg(model_path=str(onnx)), resource_cfg)
        with patch("src.npu_manager.NPUSession") as MockSess:
            mock_s = MagicMock()
            mock_s.run.side_effect = RuntimeError("Mock error")
            MockSess.return_value = mock_s
            with pytest.raises(RuntimeError, match="Mock error"):
                mgr.run_inference({"input_ids": []})
        assert mgr._session is None

    def test_run_inference_no_model_raises(self):
        mgr = NPUManager(self._cfg(model_path=""))
        with pytest.raises(RuntimeError, match="No NPU model_path"):
            mgr.run_inference({})

    def test_get_device_info_no_onnxruntime(self):
        mgr = NPUManager(self._cfg())
        with patch.dict("sys.modules", {"onnxruntime": None}):
            info = mgr.get_device_info()
        assert info["npu_available"] is False
        assert info["onnxruntime_version"] == "not installed"

    def test_get_device_info_with_onnxruntime(self):
        mgr = NPUManager(self._cfg())
        ort = MagicMock()
        ort.__version__ = "1.18.0"
        ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": ort}):
            info = mgr.get_device_info()
        assert info["onnxruntime_version"] == "1.18.0"

    def test_get_session_loads_on_first_call(self, tmp_path):
        onnx = tmp_path / "m.onnx"
        onnx.write_bytes(b"x")
        mgr = NPUManager(self._cfg(model_path=str(onnx)))
        with patch("src.npu_manager.NPUSession") as MockSess:
            MockSess.return_value = MagicMock()
            sess = mgr.get_session()
        assert sess is not None

    def test_resolve_auto_model_no_install_when_disabled(self):
        mgr = NPUManager(self._cfg(model_path="auto", auto_install=False))
        result = mgr._resolve_auto_model()
        assert result == ""


# ── Integration: load_model path resolution ────────────────────────────────────


class TestNPUManagerAutoResolve:
    def test_auto_resolve_already_installed(self, tmp_path):
        from src.npu_model_installer import _MIN_ONNX_SIZE_BYTES, ONNX_FILENAME

        onnx = tmp_path / ONNX_FILENAME
        onnx.write_bytes(b"\x00" * (_MIN_ONNX_SIZE_BYTES + 1))

        mgr = NPUManager({"model_path": "auto", "auto_install_default_model": True})

        # Patch at the source — NPUModelInstaller is imported inside _resolve_auto_model
        with patch("src.npu_model_installer.NPUModelInstaller") as MockInst:
            mock_i = MagicMock()
            mock_i.is_installed.return_value = True
            mock_i.model_path.return_value = onnx
            MockInst.return_value = mock_i

            result = mgr._resolve_auto_model()

        assert result == str(onnx)

    def test_auto_resolve_install_failure_returns_empty(self):
        from src.npu_model_installer import InstallError

        mgr = NPUManager({"model_path": "auto", "auto_install_default_model": True})

        with patch("src.npu_model_installer.NPUModelInstaller") as MockInst:
            mock_i = MagicMock()
            mock_i.is_installed.return_value = False
            mock_i.install.side_effect = InstallError("fail")
            MockInst.return_value = mock_i

            result = mgr._resolve_auto_model()

        assert result == ""
