"""Tests for src/os_detector.py."""

from __future__ import annotations

from unittest.mock import patch

from pathlib import Path
from src.os_detector import (
    OSInfo,
    _detect_package_manager,
    _read_os_release,
    detect,
)


# ── _detect_package_manager ───────────────────────────────────────────────────


class TestDetectPackageManager:
    def test_ubuntu_returns_apt(self):
        assert _detect_package_manager("ubuntu", "debian") == "apt"

    def test_fedora_returns_dnf(self):
        assert _detect_package_manager("fedora", "") == "dnf"

    def test_arch_returns_pacman(self):
        assert _detect_package_manager("arch", "") == "pacman"

    def test_opensuse_returns_zypper(self):
        assert _detect_package_manager("opensuse-leap", "") == "zypper"

    def test_alpine_returns_apk(self):
        assert _detect_package_manager("alpine", "") == "apk"

    def test_void_returns_xbps(self):
        assert _detect_package_manager("void", "") == "xbps"

    def test_gentoo_returns_emerge(self):
        assert _detect_package_manager("gentoo", "") == "emerge"

    def test_id_like_fallback(self):
        # An unknown distro that declares itself like debian should get apt
        assert _detect_package_manager("mymint", "ubuntu debian") == "apt"

    def test_unknown_distro_falls_back_to_path(self):
        import shutil
        with patch.object(shutil, "which", side_effect=lambda x: "/usr/bin/apt" if x == "apt" else None):
            pm = _detect_package_manager("unknown", "")
            assert pm == "apt"

    def test_completely_unknown_returns_empty(self):
        import shutil
        with patch.object(shutil, "which", return_value=None):
            pm = _detect_package_manager("unknowndistro", "")
            assert pm == ""


# ── OSInfo.to_system_prompt_block ─────────────────────────────────────────────


class TestOSInfoSystemPromptBlock:
    def _make_info(self, **kwargs) -> OSInfo:
        defaults = dict(
            id="ubuntu",
            name="Ubuntu",
            pretty_name="Ubuntu 24.04 LTS",
            version="24.04",
            codename="noble",
            id_like="debian",
            package_manager="apt",
            install_command="sudo apt install {package}",
            architecture="x86_64",
            kernel="6.8.0-57-generic",
            init_system="systemd",
            desktop="gnome",
            hostname="mypc",
        )
        defaults.update(kwargs)
        return OSInfo(**defaults)

    def test_contains_distro_name(self):
        info = self._make_info()
        block = info.to_system_prompt_block()
        assert "Ubuntu 24.04 LTS" in block

    def test_contains_package_manager(self):
        info = self._make_info()
        block = info.to_system_prompt_block()
        assert "apt" in block

    def test_contains_install_command(self):
        info = self._make_info()
        block = info.to_system_prompt_block()
        assert "sudo apt install" in block

    def test_contains_architecture(self):
        info = self._make_info()
        block = info.to_system_prompt_block()
        assert "x86_64" in block

    def test_contains_accuracy_reminder(self):
        info = self._make_info()
        block = info.to_system_prompt_block()
        assert "package manager" in block.lower()

    def test_unknown_init_omitted(self):
        info = self._make_info(init_system="unknown")
        block = info.to_system_prompt_block()
        assert "unknown" not in block

    def test_str_returns_pretty_name(self):
        info = self._make_info()
        assert str(info) == "Ubuntu 24.04 LTS"

    def test_str_fallback_to_name(self):
        info = self._make_info(pretty_name="")
        assert str(info) == "Ubuntu"

    def test_str_fallback_to_id(self):
        info = self._make_info(pretty_name="", name="")
        assert str(info) == "ubuntu"


# ── detect() caching ──────────────────────────────────────────────────────────


class TestDetect:
    def test_detect_returns_osinfo(self):
        # Clear cache in case previous test ran
        detect.cache_clear()
        info = detect()
        assert isinstance(info, OSInfo)
        # On the CI/test machine we're on Ubuntu; id should be set
        assert info.id != ""

    def test_detect_is_cached(self):
        detect.cache_clear()
        first = detect()
        second = detect()
        assert first is second  # same object from cache

    def test_detect_architecture_set(self):
        detect.cache_clear()
        info = detect()
        assert info.architecture != ""

    def test_detect_kernel_set(self):
        detect.cache_clear()
        info = detect()
        assert info.kernel != ""


    def test_read_os_release_manual_fallback_and_malformed_lines(self):
        detect.cache_clear()
        malformed_content = """
# This is a comment

INVALID_LINE_NO_EQUALS
VALID_KEY="valid_value"
"""
        with patch("platform.freedesktop_os_release", side_effect=OSError), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "read_text", return_value=malformed_content):
            result = _read_os_release()

        assert result == {"VALID_KEY": "valid_value"}

    def test_read_os_release_returns_dict(self):
        result = _read_os_release()
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_detect_with_mocked_os_release(self):
        detect.cache_clear()
        mock_release = {
            "ID": "fedora",
            "NAME": "Fedora Linux",
            "PRETTY_NAME": "Fedora Linux 39 (Workstation Edition)",
            "VERSION_ID": "39",
        }
        with patch("src.os_detector._read_os_release", return_value=mock_release):
            detect.cache_clear()
            info = detect()
        assert info.id == "fedora"
        assert info.package_manager == "dnf"
        assert "Fedora" in info.pretty_name
        detect.cache_clear()  # clean up for other tests

    def test_detect_with_arch_mock(self):
        detect.cache_clear()
        mock_release = {
            "ID": "arch",
            "NAME": "Arch Linux",
            "PRETTY_NAME": "Arch Linux",
        }
        with patch("src.os_detector._read_os_release", return_value=mock_release):
            detect.cache_clear()
            info = detect()
        assert info.package_manager == "pacman"
        detect.cache_clear()

    def test_detect_falls_back_to_legacy_release(self):
        detect.cache_clear()
        mock_legacy = {
            "ID": "centos",
            "NAME": "CentOS",
            "VERSION_ID": "7",
        }
        with patch("src.os_detector._read_os_release", return_value={}), \
             patch("src.os_detector._read_legacy_release", return_value=mock_legacy):
            detect.cache_clear()
            info = detect()
        assert info.id == "centos"
        assert info.name == "CentOS"
        assert info.version == "7"
        # Since it falls back to centos, and centos is matched in _ID_TO_PKG to dnf.
        assert info.package_manager == "dnf"
        detect.cache_clear()
