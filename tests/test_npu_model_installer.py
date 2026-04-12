"""Extensive tests for src/npu_model_installer.py."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

from src.npu_model_installer import (
    NPUModelInstaller,
    InstallError,
    ensure_default_model,
    DEFAULT_INSTALL_DIR,
    ONNX_FILENAME,
    _MIN_ONNX_SIZE_BYTES,
    _cb,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fake_onnx(path: Path, size: int = _MIN_ONNX_SIZE_BYTES + 1) -> Path:
    """Write a dummy file large enough to pass the size check."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return path


# ── NPUModelInstaller ─────────────────────────────────────────────────────────

class TestInstallDir:
    def test_default_install_dir(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        assert inst.install_dir == tmp_path

    def test_default_dir_constant(self):
        inst = NPUModelInstaller()
        assert "linux-ai-npu-helper" in str(inst.install_dir)
        assert "phi-3-mini" in str(inst.install_dir)

    def test_model_path_in_install_dir(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        assert inst.model_path().parent == tmp_path
        assert inst.model_path().name == ONNX_FILENAME


class TestIsInstalled:
    def test_not_installed_no_file(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        assert inst.is_installed() is False

    def test_not_installed_empty_file(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        inst.model_path().parent.mkdir(parents=True, exist_ok=True)
        inst.model_path().write_bytes(b"")
        assert inst.is_installed() is False

    def test_not_installed_file_too_small(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        inst.model_path().parent.mkdir(parents=True, exist_ok=True)
        inst.model_path().write_bytes(b"\x00" * 100)
        assert inst.is_installed() is False

    def test_installed_when_file_large_enough(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        _make_fake_onnx(inst.model_path())
        assert inst.is_installed() is True

    def test_boundary_size_not_installed(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        _make_fake_onnx(inst.model_path(), size=_MIN_ONNX_SIZE_BYTES)
        # Exactly at the minimum — not installed (strictly less check)
        assert inst.is_installed() is False

    def test_just_above_boundary_installed(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        _make_fake_onnx(inst.model_path(), size=_MIN_ONNX_SIZE_BYTES + 1)
        assert inst.is_installed() is True


class TestInstall:
    def test_already_installed_skips_download(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        _make_fake_onnx(inst.model_path())
        messages = []
        result = inst.install(progress_callback=messages.append)
        assert result == inst.model_path()
        assert any("already installed" in m for m in messages)

    def test_allow_external_false_raises(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        with pytest.raises(InstallError, match="external network access"):
            inst.install(allow_external=False)

    def test_download_called_for_each_file(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)

        def fake_download(url, dest, cb):
            # Simulate writing the ONNX file at the right size
            if dest.name == ONNX_FILENAME:
                dest.write_bytes(b"\x00" * (_MIN_ONNX_SIZE_BYTES + 1))
            else:
                dest.write_bytes(b"fake")

        with patch.object(NPUModelInstaller, "_download_file", side_effect=fake_download):
            result = inst.install()

        assert result == inst.model_path()
        assert inst.is_installed()

    def test_progress_callback_called(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        messages = []

        def fake_download(url, dest, cb):
            if dest.name == ONNX_FILENAME:
                dest.write_bytes(b"\x00" * (_MIN_ONNX_SIZE_BYTES + 1))
            else:
                dest.write_bytes(b"fake")

        with patch.object(NPUModelInstaller, "_download_file", side_effect=fake_download):
            inst.install(progress_callback=messages.append)

        assert len(messages) > 0

    def test_existing_files_skipped(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        _make_fake_onnx(inst.model_path())
        # Pre-create one data file
        (tmp_path / "tokenizer.json").write_text("{}")

        download_calls = []

        def fake_download(url, dest, cb):
            download_calls.append(dest.name)
            dest.write_bytes(b"fake")

        with patch.object(NPUModelInstaller, "_download_file", side_effect=fake_download):
            inst.install()

        # ONNX already large enough, tokenizer.json also present
        assert ONNX_FILENAME not in download_calls
        assert "tokenizer.json" not in download_calls

    def test_small_onnx_after_download_raises(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)

        def fake_download(url, dest, cb):
            dest.write_bytes(b"\x00" * 10)  # Too small

        with patch.object(NPUModelInstaller, "_download_file", side_effect=fake_download):
            with pytest.raises(InstallError, match="too small"):
                inst.install()

    def test_dir_created_on_install(self, tmp_path):
        install_dir = tmp_path / "nested" / "new"
        inst = NPUModelInstaller(install_dir)

        def fake_download(url, dest, cb):
            if dest.name == ONNX_FILENAME:
                dest.write_bytes(b"\x00" * (_MIN_ONNX_SIZE_BYTES + 1))
            else:
                dest.write_bytes(b"fake")

        with patch.object(NPUModelInstaller, "_download_file", side_effect=fake_download):
            inst.install()

        assert install_dir.exists()


class TestUninstall:
    def test_uninstall_removes_dir(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        _make_fake_onnx(inst.model_path())
        assert tmp_path.exists()
        inst.uninstall()
        assert not tmp_path.exists()

    def test_uninstall_idempotent(self, tmp_path):
        inst = NPUModelInstaller(tmp_path / "notexist")
        inst.uninstall()  # Should not raise


class TestModelInfo:
    def test_returns_dict_with_required_keys(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        info = inst.model_info()
        for key in ("name", "variant", "publisher", "license", "source_url",
                    "npu_optimized", "install_dir", "onnx_file", "is_installed",
                    "size_bytes", "size_gb", "description"):
            assert key in info, f"Missing key: {key!r}"

    def test_not_installed_reflects_state(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        info = inst.model_info()
        assert info["is_installed"] is False
        assert info["size_bytes"] == 0
        assert info["size_gb"] == 0.0

    def test_installed_reflects_state(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        _make_fake_onnx(inst.model_path())
        info = inst.model_info()
        assert info["is_installed"] is True
        assert info["size_bytes"] > 0
        assert info["size_gb"] > 0.0

    def test_publisher_is_microsoft(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        assert inst.model_info()["publisher"] == "Microsoft"

    def test_license_is_mit(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        assert inst.model_info()["license"] == "MIT"

    def test_npu_optimized_true(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        assert inst.model_info()["npu_optimized"] is True

    def test_source_url_huggingface(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        assert "huggingface.co" in inst.model_info()["source_url"]

    def test_description_not_empty(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        assert len(inst.model_info()["description"]) > 20


class TestVerifySha256:
    def test_correct_hash_passes(self, tmp_path):
        f = tmp_path / "test.bin"
        content = b"hello world"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        NPUModelInstaller._verify_sha256(f, expected)  # Should not raise

    def test_wrong_hash_raises(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        with pytest.raises(InstallError, match="SHA-256 mismatch"):
            NPUModelInstaller._verify_sha256(f, "deadbeef" * 8)

    def test_wrong_hash_deletes_file(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        try:
            NPUModelInstaller._verify_sha256(f, "deadbeef" * 8)
        except InstallError:
            pass
        assert not f.exists()

    def test_case_insensitive_match(self, tmp_path):
        content = b"data"
        f = tmp_path / "test.bin"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest().upper()
        NPUModelInstaller._verify_sha256(f, expected)  # Should not raise


class TestDownloadFile:
    def _make_fake_response(self, content: bytes) -> MagicMock:
        resp = MagicMock()
        resp.headers = {"content-length": str(len(content))}
        resp.iter_content.return_value = [content]
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.raise_for_status = MagicMock()
        return resp

    def test_writes_content(self, tmp_path):
        dest = tmp_path / "model.onnx"
        content = b"fake onnx content"
        resp = self._make_fake_response(content)
        with patch("requests.get", return_value=resp):
            NPUModelInstaller._download_file("http://localhost/model.onnx", dest, None)
        assert dest.read_bytes() == content

    def test_progress_callback_called(self, tmp_path):
        dest = tmp_path / "model.onnx"
        content = b"x" * 1024
        resp = self._make_fake_response(content)
        messages = []
        with patch("requests.get", return_value=resp):
            NPUModelInstaller._download_file(
                "http://localhost/model.onnx", dest, messages.append
            )
        assert len(messages) > 0

    def test_raises_install_error_on_http_error(self, tmp_path):
        dest = tmp_path / "model.onnx"
        with patch("requests.get", side_effect=Exception("Connection refused")):
            with pytest.raises(InstallError):
                NPUModelInstaller._download_file("http://localhost/x", dest, None)

    def test_cleans_up_tmp_on_error(self, tmp_path):
        dest = tmp_path / "model.onnx"
        with patch("requests.get", side_effect=Exception("fail")):
            try:
                NPUModelInstaller._download_file("http://localhost/x", dest, None)
            except InstallError:
                pass
        # tmp files should be cleaned up
        tmp_files = list(tmp_path.glob(".*.tmp.*"))
        assert len(tmp_files) == 0

    def test_raises_if_requests_not_installed(self, tmp_path):
        dest = tmp_path / "model.onnx"
        with patch.dict("sys.modules", {"requests": None}):
            with pytest.raises((InstallError, ImportError)):
                NPUModelInstaller._download_file("http://localhost/x", dest, None)


class TestSetDirPermissions:
    def test_sets_owner_only(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        inst._set_dir_permissions()
        mode = stat.S_IMODE(tmp_path.stat().st_mode)
        assert mode == 0o700


# ── ensure_default_model ──────────────────────────────────────────────────────

class TestEnsureDefaultModel:
    def test_returns_path_when_installed(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        _make_fake_onnx(inst.model_path())

        with patch("src.npu_model_installer.NPUModelInstaller") as MockClass:
            mock_inst = MagicMock()
            mock_inst.install.return_value = inst.model_path()
            MockClass.return_value = mock_inst

            result = ensure_default_model(install_dir=tmp_path)
            assert result is not None

    def test_returns_none_on_install_error(self, tmp_path):
        with patch("src.npu_model_installer.NPUModelInstaller") as MockClass:
            mock_inst = MagicMock()
            mock_inst.install.side_effect = InstallError("download failed")
            MockClass.return_value = mock_inst

            result = ensure_default_model(install_dir=tmp_path)
            assert result is None

    def test_passes_progress_callback(self, tmp_path):
        messages = []

        with patch("src.npu_model_installer.NPUModelInstaller") as MockClass:
            mock_inst = MagicMock()
            mock_inst.install.return_value = tmp_path / ONNX_FILENAME
            MockClass.return_value = mock_inst

            ensure_default_model(
                install_dir=tmp_path,
                progress_callback=messages.append,
            )

            _, kwargs = mock_inst.install.call_args
            assert kwargs.get("progress_callback") == messages.append

    def test_passes_allow_external(self, tmp_path):
        with patch("src.npu_model_installer.NPUModelInstaller") as MockClass:
            mock_inst = MagicMock()
            mock_inst.install.return_value = tmp_path / ONNX_FILENAME
            MockClass.return_value = mock_inst

            ensure_default_model(install_dir=tmp_path, allow_external=False)

            _, kwargs = mock_inst.install.call_args
            assert kwargs.get("allow_external") is False


# ── _cb helper ────────────────────────────────────────────────────────────────

class TestCbHelper:
    def test_calls_callback(self):
        messages = []
        _cb(messages.append, "hello")
        assert messages == ["hello"]

    def test_none_callback_no_error(self):
        _cb(None, "hello")  # Should not raise

    def test_callback_exception_swallowed(self):
        def bad_cb(msg):
            raise RuntimeError("boom")
        _cb(bad_cb, "test")  # Should not raise


# ── DEFAULT_INSTALL_DIR constant ──────────────────────────────────────────────

class TestConstants:
    def test_default_install_dir_is_path(self):
        assert isinstance(DEFAULT_INSTALL_DIR, Path)

    def test_default_install_dir_home_relative(self):
        assert DEFAULT_INSTALL_DIR.is_absolute()

    def test_onnx_filename_ends_with_onnx(self):
        assert ONNX_FILENAME.endswith(".onnx")

    def test_min_size_reasonable(self):
        assert _MIN_ONNX_SIZE_BYTES >= 100 * 1024 * 1024  # At least 100 MB
