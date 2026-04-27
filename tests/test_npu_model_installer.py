"""Extensive tests for src/npu_model_installer.py."""

from __future__ import annotations

import hashlib
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Mock missing dependencies
if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock()
if "yaml" not in sys.modules:
    sys.modules["yaml"] = MagicMock()

import pytest

from src.npu_model_installer import (
    NPUModelInstaller,
    ModelCatalogEntry,
    MODEL_CATALOG,
    InstallError,
    ensure_default_model,
    install_model_from_catalog,
    get_default_entry,
    get_vision_models,
    get_npu_suggestions,
    DEFAULT_INSTALL_DIR,
    MODELS_ROOT,
    ONNX_FILENAME,
    _MIN_ONNX_SIZE_BYTES,
    _cb,
    install_dir_for,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fake_onnx(path: Path, size: int | None = None) -> Path:
    """Write a dummy file larger than min_size_bytes for the default entry."""
    if size is None:
        size = get_default_entry().min_size_bytes + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return path


def _make_entry(**kwargs) -> ModelCatalogEntry:
    defaults = dict(
        key="test-model",
        name="Test Model",
        publisher="Test",
        description="A test model",
        hf_repo="test/repo",
        hf_variant="cpu-int4",
        onnx_filename="model.onnx",
        min_size_bytes=100,
        is_vision=True,
        npu_fit="excellent",
        size_description="~1 GB",
    )
    defaults.update(kwargs)
    return ModelCatalogEntry(**defaults)


# ── MODEL_CATALOG ─────────────────────────────────────────────────────────────


class TestModelCatalog:
    def test_catalog_non_empty(self):
        assert len(MODEL_CATALOG) >= 4

    def test_exactly_one_default(self):
        defaults = [e for e in MODEL_CATALOG if e.is_default]
        assert len(defaults) == 1

    def test_default_is_vision(self):
        assert get_default_entry().is_vision is True

    def test_all_entries_have_key(self):
        for e in MODEL_CATALOG:
            assert e.key, f"Entry {e.name!r} has empty key"

    def test_all_entries_have_onnx_filename(self):
        for e in MODEL_CATALOG:
            assert e.onnx_filename.endswith(".onnx"), (
                f"{e.name!r} onnx_filename={e.onnx_filename!r}"
            )

    # ── TOS fields ────────────────────────────────────────────────────────────

    def test_tos_entries_have_tos_url(self):
        for e in MODEL_CATALOG:
            if e.requires_tos:
                assert e.tos_url, f"{e.name!r} requires_tos=True but tos_url is empty"

    def test_tos_entries_have_tos_summary(self):
        for e in MODEL_CATALOG:
            if e.requires_tos:
                assert len(e.tos_summary) >= 20, (
                    f"{e.name!r} requires_tos=True but tos_summary too short"
                )

    def test_non_tos_entries_no_requires_flag(self):
        mit_entries = [e for e in MODEL_CATALOG if e.license_spdx == "MIT"]
        for e in mit_entries:
            assert not e.requires_tos, (
                f"MIT-licensed entry {e.name!r} should not require TOS"
            )

    def test_gemma_entries_require_tos(self):
        gemma_entries = [e for e in MODEL_CATALOG if e.license_spdx == "Gemma"]
        assert len(gemma_entries) >= 1, "Expected at least one Gemma-licensed entry"
        for e in gemma_entries:
            assert e.requires_tos, f"{e.name!r} is Gemma but requires_tos is False"
            assert "ai.google.dev/gemma/terms" in e.tos_url

    # ── Gemma vision entries ──────────────────────────────────────────────────

    def test_paligemma_in_catalog(self):
        keys = [e.key for e in MODEL_CATALOG]
        assert "paligemma-3b-int4" in keys

    def test_gemma3_vision_in_catalog(self):
        keys = [e.key for e in MODEL_CATALOG]
        assert "gemma3-4b-vision-int4" in keys

    def test_paligemma_is_vision(self):
        entry = next(e for e in MODEL_CATALOG if e.key == "paligemma-3b-int4")
        assert entry.is_vision is True

    def test_gemma3_vision_is_vision(self):
        entry = next(e for e in MODEL_CATALOG if e.key == "gemma3-4b-vision-int4")
        assert entry.is_vision is True

    def test_paligemma_npu_fit(self):
        entry = next(e for e in MODEL_CATALOG if e.key == "paligemma-3b-int4")
        assert entry.npu_fit in ("excellent", "good")

    def test_gemma_vision_in_vision_models_list(self):
        vision_keys = [e.key for e in get_vision_models()]
        assert "paligemma-3b-int4" in vision_keys
        assert "gemma3-4b-vision-int4" in vision_keys

    # ── requires_tos field defaults ───────────────────────────────────────────

    def test_requires_tos_defaults_false(self):
        e = _make_entry()
        assert e.requires_tos is False

    def test_tos_url_defaults_empty(self):
        e = _make_entry()
        assert e.tos_url == ""

    def test_tos_summary_defaults_empty(self):
        e = _make_entry()
        assert e.tos_summary == ""

    def test_all_npu_fit_valid(self):
        valid = {"excellent", "good", "fair", "not_recommended"}
        for e in MODEL_CATALOG:
            assert e.npu_fit in valid, f"{e.name!r} npu_fit={e.npu_fit!r}"

    def test_vision_models_present(self):
        assert any(e.is_vision for e in MODEL_CATALOG)

    def test_text_models_present(self):
        assert any(not e.is_vision for e in MODEL_CATALOG)

    def test_hf_base_url_contains_repo(self):
        for e in MODEL_CATALOG:
            assert e.hf_repo in e.hf_base_url

    def test_hf_repo_url_format(self):
        for e in MODEL_CATALOG:
            assert e.hf_repo_url.startswith("https://huggingface.co/")

    def test_npu_fit_label_format(self):
        for e in MODEL_CATALOG:
            label = e.npu_fit_label
            assert label  # Non-empty


class TestGetDefaultEntry:
    def test_returns_entry(self):
        e = get_default_entry()
        assert isinstance(e, ModelCatalogEntry)

    def test_is_vision(self):
        assert get_default_entry().is_vision is True

    def test_npu_fit_excellent_or_good(self):
        assert get_default_entry().npu_fit in ("excellent", "good")

    def test_phi3_vision_is_default(self):
        e = get_default_entry()
        assert "vision" in e.name.lower() or "vision" in e.key.lower()


class TestGetVisionModels:
    def test_all_vision(self):
        for e in get_vision_models():
            assert e.is_vision

    def test_sorted_by_fit(self):
        entries = get_vision_models()
        _order = {"excellent": 0, "good": 1, "fair": 2, "not_recommended": 3}
        for i in range(len(entries) - 1):
            assert _order.get(entries[i].npu_fit, 99) <= _order.get(
                entries[i + 1].npu_fit, 99
            )


class TestGetNpuSuggestions:
    def test_all_excellent_or_good(self):
        for e in get_npu_suggestions():
            assert e.npu_fit in ("excellent", "good")

    def test_non_empty(self):
        assert len(get_npu_suggestions()) >= 2

    def test_vision_before_text_in_same_tier(self):
        entries = get_npu_suggestions()
        excellent = [e for e in entries if e.npu_fit == "excellent"]
        if len(excellent) >= 2:
            first_text_idx = next(
                (i for i, e in enumerate(excellent) if not e.is_vision), None
            )
            first_vision_idx = next(
                (i for i, e in enumerate(excellent) if e.is_vision), None
            )
            if first_text_idx is not None and first_vision_idx is not None:
                assert first_vision_idx <= first_text_idx


# ── ModelCatalogEntry ─────────────────────────────────────────────────────────


class TestModelCatalogEntry:
    def test_hf_base_url_construction(self):
        e = _make_entry(hf_repo="org/repo", hf_variant="cpu-int4")
        assert "org/repo" in e.hf_base_url
        assert "cpu-int4" in e.hf_base_url

    def test_npu_fit_label_excellent(self):
        e = _make_entry(npu_fit="excellent")
        assert "Excellent" in e.npu_fit_label

    def test_npu_fit_label_good(self):
        e = _make_entry(npu_fit="good")
        assert "Good" in e.npu_fit_label

    def test_npu_fit_label_fair(self):
        e = _make_entry(npu_fit="fair")
        assert "Fair" in e.npu_fit_label

    def test_npu_fit_label_not_recommended(self):
        e = _make_entry(npu_fit="not_recommended")
        assert "Not recommended" in e.npu_fit_label

    def test_npu_fit_label_unknown(self):
        e = _make_entry(npu_fit="unknown_level")
        assert e.npu_fit_label == "unknown_level"


# ── install_dir_for ───────────────────────────────────────────────────────────


class TestInstallDirFor:
    def test_uses_models_root(self):
        e = _make_entry(key="my-key")
        d = install_dir_for(e)
        assert d.parent == MODELS_ROOT

    def test_uses_entry_key(self):
        e = _make_entry(key="my-key")
        d = install_dir_for(e)
        assert d.name == "my-key"


# ── NPUModelInstaller ─────────────────────────────────────────────────────────


class TestInstallDir:
    def test_custom_install_dir(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        assert inst.install_dir == tmp_path

    def test_default_dir_from_entry(self):
        inst = NPUModelInstaller()
        assert inst.install_dir == install_dir_for(get_default_entry())

    def test_model_path_uses_entry_filename(self, tmp_path):
        entry = _make_entry(onnx_filename="custom.onnx")
        inst = NPUModelInstaller(tmp_path, entry=entry)
        assert inst.model_path().name == "custom.onnx"

    def test_entry_property(self, tmp_path):
        entry = _make_entry()
        inst = NPUModelInstaller(tmp_path, entry=entry)
        assert inst.entry is entry


class TestIsInstalled:
    def test_not_installed_no_file(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        assert inst.is_installed() is False

    def test_not_installed_empty_file(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)
        inst = NPUModelInstaller(tmp_path, entry=entry)
        inst.model_path().parent.mkdir(parents=True, exist_ok=True)
        inst.model_path().write_bytes(b"")
        assert inst.is_installed() is False

    def test_not_installed_file_exactly_at_min(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)
        inst = NPUModelInstaller(tmp_path, entry=entry)
        inst.model_path().parent.mkdir(parents=True, exist_ok=True)
        inst.model_path().write_bytes(b"\x00" * 100)
        # Exactly at min — strictly greater required → False
        assert inst.is_installed() is False

    def test_installed_above_min(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)
        inst = NPUModelInstaller(tmp_path, entry=entry)
        inst.model_path().parent.mkdir(parents=True, exist_ok=True)
        inst.model_path().write_bytes(b"\x00" * 101)
        assert inst.is_installed() is True

    def test_installed_when_file_large_enough_default(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        _make_fake_onnx(inst.model_path())
        assert inst.is_installed() is True


class TestInstall:
    def test_already_installed_skips_download(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)
        inst = NPUModelInstaller(tmp_path, entry=entry)
        _make_fake_onnx(inst.model_path(), size=101)
        messages = []
        result = inst.install(progress_callback=messages.append)
        assert result == inst.model_path()
        assert any("already installed" in m for m in messages)

    def test_allow_external_false_raises(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        with pytest.raises(InstallError, match="external network access"):
            inst.install(allow_external=False)

    def test_download_called_for_each_file(self, tmp_path):
        entry = _make_entry(
            min_size_bytes=100,
            extra_files=[("tokenizer.json", None)],
        )
        inst = NPUModelInstaller(tmp_path, entry=entry)

        def fake_download(url, dest, cb):
            if dest.name == entry.onnx_filename:
                dest.write_bytes(b"\x00" * 200)
            else:
                dest.write_bytes(b"fake")

        with patch.object(
            NPUModelInstaller, "_download_file", side_effect=fake_download
        ):
            result = inst.install()

        assert result == inst.model_path()
        assert inst.is_installed()

    def test_progress_callback_called(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)
        inst = NPUModelInstaller(tmp_path, entry=entry)
        messages = []

        def fake_download(url, dest, cb):
            dest.write_bytes(b"\x00" * 200)

        with patch.object(
            NPUModelInstaller, "_download_file", side_effect=fake_download
        ):
            inst.install(progress_callback=messages.append)

        assert len(messages) > 0

    def test_existing_files_skipped(self, tmp_path):
        entry = _make_entry(
            min_size_bytes=100,
            extra_files=[("tokenizer.json", None)],
        )
        inst = NPUModelInstaller(tmp_path, entry=entry)
        # Pre-create ONNX large enough
        _make_fake_onnx(inst.model_path(), size=200)
        (tmp_path / "tokenizer.json").write_text("{}")

        download_calls = []

        def fake_download(url, dest, cb):
            download_calls.append(dest.name)
            dest.write_bytes(b"fake")

        with patch.object(
            NPUModelInstaller, "_download_file", side_effect=fake_download
        ):
            inst.install()

        assert entry.onnx_filename not in download_calls
        assert "tokenizer.json" not in download_calls

    def test_onnx_not_created_raises(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)
        inst = NPUModelInstaller(tmp_path, entry=entry)

        # Download writes nothing
        def fake_download(url, dest, cb):
            pass  # Don't create the file

        with patch.object(
            NPUModelInstaller, "_download_file", side_effect=fake_download
        ):
            with pytest.raises(InstallError, match="not created|too small"):
                inst.install()

    def test_small_onnx_after_download_raises(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)
        inst = NPUModelInstaller(tmp_path, entry=entry)

        def fake_download(url, dest, cb):
            dest.write_bytes(b"\x00" * 10)  # Too small (≤ 100)

        with patch.object(
            NPUModelInstaller, "_download_file", side_effect=fake_download
        ):
            with pytest.raises(InstallError):
                inst.install()

    def test_dir_created_on_install(self, tmp_path):
        install_dir = tmp_path / "nested" / "new"
        entry = _make_entry(min_size_bytes=100)
        inst = NPUModelInstaller(install_dir, entry=entry)

        def fake_download(url, dest, cb):
            dest.write_bytes(b"\x00" * 200)

        with patch.object(
            NPUModelInstaller, "_download_file", side_effect=fake_download
        ):
            inst.install()

        assert install_dir.exists()


class TestUninstall:
    def test_uninstall_removes_dir(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)
        inst = NPUModelInstaller(tmp_path, entry=entry)
        _make_fake_onnx(inst.model_path(), size=200)
        assert tmp_path.exists()
        inst.uninstall()
        assert not tmp_path.exists()

    def test_uninstall_idempotent(self, tmp_path):
        inst = NPUModelInstaller(tmp_path / "notexist")
        inst.uninstall()  # Should not raise


class TestModelInfo:
    def test_returns_dict_with_required_keys(self, tmp_path):
        entry = _make_entry()
        inst = NPUModelInstaller(tmp_path, entry=entry)
        info = inst.model_info()
        for key in (
            "key",
            "name",
            "publisher",
            "description",
            "is_vision",
            "npu_fit",
            "npu_fit_label",
            "size_description",
            "license_spdx",
            "license_url",
            "hf_repo_url",
            "notes",
            "install_dir",
            "onnx_file",
            "is_installed",
            "size_bytes",
            "size_gb",
            "is_default",
        ):
            assert key in info, f"Missing key: {key!r}"

    def test_not_installed_reflects_state(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        info = inst.model_info()
        assert info["is_installed"] is False
        assert info["size_bytes"] == 0
        assert info["size_gb"] == 0.0

    def test_installed_reflects_state(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)
        inst = NPUModelInstaller(tmp_path, entry=entry)
        _make_fake_onnx(inst.model_path(), size=200)
        info = inst.model_info()
        assert info["is_installed"] is True
        assert info["size_bytes"] > 0

    def test_is_vision_from_entry(self, tmp_path):
        entry = _make_entry(is_vision=True)
        assert (
            NPUModelInstaller(tmp_path, entry=entry).model_info()["is_vision"] is True
        )

    def test_npu_fit_from_entry(self, tmp_path):
        entry = _make_entry(npu_fit="excellent")
        info = NPUModelInstaller(tmp_path, entry=entry).model_info()
        assert info["npu_fit"] == "excellent"
        assert "Excellent" in info["npu_fit_label"]


class TestVerifySha256:
    def test_correct_hash_passes(self, tmp_path):
        f = tmp_path / "test.bin"
        content = b"hello world"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        NPUModelInstaller._verify_sha256(f, expected)

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
        NPUModelInstaller._verify_sha256(f, expected)


class TestInstallError:
    def test_install_error_serialization(self):
        """Verify InstallError can be instantiated with a message."""
        err = InstallError("Failed to download")
        assert str(err) == "Failed to download"


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
        tmp_files = list(tmp_path.glob(".*.tmp.*"))
        assert len(tmp_files) == 0


class TestSetDirPermissions:
    def test_sets_owner_only(self, tmp_path):
        inst = NPUModelInstaller(tmp_path)
        inst._set_dir_permissions()
        mode = stat.S_IMODE(tmp_path.stat().st_mode)
        assert mode == 0o700


# ── install_model_from_catalog ────────────────────────────────────────────────


class TestInstallModelFromCatalog:
    def test_calls_install_on_entry(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)

        def fake_download(url, dest, cb):
            dest.write_bytes(b"\x00" * 200)

        with patch.object(
            NPUModelInstaller, "_download_file", side_effect=fake_download
        ):
            result = install_model_from_catalog(entry)

        assert result.name == entry.onnx_filename

    def test_raises_when_no_external(self, tmp_path):
        entry = _make_entry(min_size_bytes=100)
        # Force is_installed() to return False so allow_external is checked
        with patch.object(NPUModelInstaller, "is_installed", return_value=False):
            with pytest.raises(InstallError, match="external network access"):
                install_model_from_catalog(entry, allow_external=False)


# ── ensure_default_model ──────────────────────────────────────────────────────


class TestEnsureDefaultModel:
    @patch("src.npu_model_installer.install_model_from_catalog")
    @patch("src.npu_model_installer.get_default_entry")
    def test_returns_none_on_install_error(
        self, mock_get_entry, mock_install, tmp_path
    ):
        mock_install.side_effect = InstallError("download failed")
        result = ensure_default_model(install_dir=tmp_path)
        assert result is None
        mock_install.assert_called_once_with(
            mock_get_entry.return_value,
            install_dir=tmp_path,
            progress_callback=None,
            allow_external=True,
        )

    @patch("src.npu_model_installer.install_model_from_catalog")
    @patch("src.npu_model_installer.get_default_entry")
    def test_returns_path_on_success(self, mock_get_entry, mock_install, tmp_path):
        expected = tmp_path / "model.onnx"
        mock_install.return_value = expected
        result = ensure_default_model(install_dir=tmp_path)
        assert result == expected
        mock_install.assert_called_once_with(
            mock_get_entry.return_value,
            install_dir=tmp_path,
            progress_callback=None,
            allow_external=True,
        )

    @patch("src.npu_model_installer.install_model_from_catalog")
    @patch("src.npu_model_installer.get_default_entry")
    def test_passes_allow_external(self, mock_get_entry, mock_install, tmp_path):
        mock_install.return_value = tmp_path / "m.onnx"
        ensure_default_model(install_dir=tmp_path, allow_external=False)
        mock_install.assert_called_once_with(
            mock_get_entry.return_value,
            install_dir=tmp_path,
            progress_callback=None,
            allow_external=False,
        )

    @patch("src.npu_model_installer.install_model_from_catalog")
    @patch("src.npu_model_installer.get_default_entry")
    def test_passes_progress_callback(self, mock_get_entry, mock_install, tmp_path):
        messages = []
        mock_install.return_value = tmp_path / "m.onnx"
        ensure_default_model(
            install_dir=tmp_path,
            progress_callback=messages.append,
        )
        mock_install.assert_called_once_with(
            mock_get_entry.return_value,
            install_dir=tmp_path,
            progress_callback=messages.append,
            allow_external=True,
        )


# ── _cb helper ────────────────────────────────────────────────────────────────


class TestCbHelper:
    def test_calls_callback(self):
        messages = []
        _cb(messages.append, "hello")
        assert messages == ["hello"]

    def test_none_callback_no_error(self):
        _cb(None, "hello")

    def test_callback_exception_swallowed(self):
        def bad_cb(msg):
            raise RuntimeError("boom")

        _cb(bad_cb, "test")


# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_default_install_dir_is_path(self):
        assert isinstance(DEFAULT_INSTALL_DIR, Path)

    def test_default_install_dir_absolute(self):
        assert DEFAULT_INSTALL_DIR.is_absolute()

    def test_onnx_filename_ends_with_onnx(self):
        assert ONNX_FILENAME.endswith(".onnx")

    def test_min_size_reasonable(self):
        assert _MIN_ONNX_SIZE_BYTES >= 1 * 1024 * 1024  # At least 1 MB

    def test_models_root_under_home(self):
        assert MODELS_ROOT.is_absolute()
        assert ".local" in str(MODELS_ROOT) or "share" in str(MODELS_ROOT)


# ── ModelCatalogEntry TOS fields ──────────────────────────────────────────────


class TestRequiresTos:
    def test_entry_with_tos(self):
        e = _make_entry(
            requires_tos=True,
            tos_url="https://example.com/tos",
            tos_summary="You must agree to our terms.",
        )
        assert e.requires_tos is True
        assert e.tos_url == "https://example.com/tos"
        assert "agree" in e.tos_summary

    def test_entry_without_tos(self):
        e = _make_entry(requires_tos=False)
        assert e.requires_tos is False

    def test_tos_url_in_hf_base_url_independent(self):
        e = _make_entry(
            requires_tos=True,
            tos_url="https://ai.google.dev/gemma/terms",
        )
        # tos_url is separate from hf_base_url
        assert "ai.google.dev" in e.tos_url
        assert "ai.google.dev" not in e.hf_base_url

    def test_paligemma_tos_fields(self):
        pali = next(e for e in MODEL_CATALOG if e.key == "paligemma-3b-int4")
        assert pali.requires_tos is True
        assert pali.tos_url.startswith("https://")
        assert len(pali.tos_summary) > 50

    def test_gemma3_tos_fields(self):
        g3 = next(e for e in MODEL_CATALOG if e.key == "gemma3-4b-vision-int4")
        assert g3.requires_tos is True
        assert "gemma" in g3.tos_url.lower()
        assert len(g3.tos_summary) > 50

    def test_phi3_vision_no_tos(self):
        phi = next(e for e in MODEL_CATALOG if e.key == "phi3-vision-128k-int4")
        assert phi.requires_tos is False

    def test_florence_no_tos(self):
        fl = next(e for e in MODEL_CATALOG if e.key == "florence2-base")
        assert fl.requires_tos is False


# ── No preinstall — model_path default ────────────────────────────────────────


class TestNoPreinstall:
    def test_default_model_path_is_empty(self):
        """Config default must be '' (no auto-install) not 'auto'."""
        from src.config import _DEFAULTS

        npu_cfg = _DEFAULTS.get("npu", {})
        assert npu_cfg.get("model_path") == "", (
            "npu.model_path default should be '' (no preinstall); "
            f"got {npu_cfg.get('model_path')!r}"
        )

    def test_auto_install_disabled_by_default(self):
        from src.config import _DEFAULTS

        npu_cfg = _DEFAULTS.get("npu", {})
        assert npu_cfg.get("auto_install_default_model") is False, (
            "auto_install_default_model should default to False"
        )
