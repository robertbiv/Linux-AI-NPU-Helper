"""Tests for src/shell_detector.py."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.shell_detector import (
    ShellInfo,
    _family,
    _from_path,
    _from_user_db,
    _from_parent_proc,
    _stem,
    _version,
    detect,
)


class TestShellInfo:
    def test_supports_readline_prefill(self):
        assert (
            ShellInfo("/bin/bash", "bash", "bash").supports_readline_prefill() is True
        )
        assert ShellInfo("/bin/zsh", "zsh", "zsh").supports_readline_prefill() is True
        assert (
            ShellInfo("/bin/fish", "fish", "fish").supports_readline_prefill() is True
        )
        assert ShellInfo("/bin/ksh", "ksh", "ksh").supports_readline_prefill() is True
        assert ShellInfo("/bin/sh", "sh", "sh").supports_readline_prefill() is False
        assert (
            ShellInfo("/usr/bin/nu", "nu", "nushell").supports_readline_prefill()
            is False
        )

    def test_str_representation(self):
        info = ShellInfo("/bin/bash", "bash", "bash", "5.2.26")
        assert str(info) == "bash 5.2.26 (/bin/bash)"

        info_no_version = ShellInfo("/bin/bash", "bash", "bash")
        assert str(info_no_version) == "bash (/bin/bash)"


class TestHelpers:
    def test_stem(self):
        assert _stem("/bin/bash") == "bash"
        assert _stem("/usr/bin/bash-5.2") == "bash"
        assert _stem("/usr/local/bin/zsh_5.8") == "zsh"
        assert _stem("nu") == "nu"

    def test_family(self):
        assert _family("bash") == "bash"
        assert _family("zsh") == "zsh"
        assert _family("nu") == "nushell"
        assert _family("unknown-shell") == "unknown"

    def test_version(self):
        with (
            patch("shutil.which", return_value="/bin/bash"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                stdout="GNU bash, version 5.2.26(1)-release (x86_64-pc-linux-gnu)\n",
                stderr="",
                returncode=0,
            )
            assert (
                _version("/bin/bash")
                == "GNU bash, version 5.2.26(1)-release (x86_64-pc-linux-gnu)"
            )

    def test_version_not_found(self):
        with patch("shutil.which", return_value=None):
            assert _version("/nonexistent/shell") == ""

    def test_version_error(self):
        with (
            patch("shutil.which", return_value="/bin/bash"),
            patch("subprocess.run", side_effect=subprocess.SubprocessError),
        ):
            assert _version("/bin/bash") == ""

    def test_from_path(self):
        with patch("src.shell_detector._version", return_value="5.2"):
            info = _from_path("/bin/bash")
            assert info.path == "/bin/bash"
            assert info.name == "bash"
            assert info.family == "bash"
            assert info.version == "5.2"


class TestDetect:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        detect.cache_clear()
        yield
        detect.cache_clear()

    def test_detect_from_env(self):
        with (
            patch.dict(os.environ, {"SHELL": "/usr/bin/zsh"}),
            patch("src.shell_detector.Path.exists", return_value=True),
            patch("src.shell_detector._version", return_value="5.9"),
        ):
            info = detect()
            assert info.path == "/usr/bin/zsh"
            assert info.family == "zsh"

    def test_detect_from_env_empty(self):
        with (
            patch.dict(os.environ, {"SHELL": "   "}),
            patch("src.shell_detector._from_parent_proc", return_value=None),
            patch("src.shell_detector._from_user_db", return_value=None),
            patch("src.shell_detector._version", return_value=""),
        ):
            info = detect()
            assert info.path == "/bin/sh"
            assert info.family == "sh"

    def test_detect_from_env_not_exists(self):
        with (
            patch.dict(os.environ, {"SHELL": "/nonexistent/shell"}),
            patch("src.shell_detector.Path.exists", return_value=False),
            patch("src.shell_detector._from_parent_proc", return_value=None),
            patch("src.shell_detector._from_user_db", return_value=None),
            patch("src.shell_detector._version", return_value=""),
        ):
            info = detect()
            assert info.path == "/bin/sh"
            assert info.family == "sh"

    def test_detect_from_parent_proc(self):
        with (
            patch.dict(os.environ, {"SHELL": ""}),
            patch("src.shell_detector._from_parent_proc", return_value="/usr/bin/fish"),
            patch("src.shell_detector._version", return_value="3.6.0"),
        ):
            info = detect()
            assert info.path == "/usr/bin/fish"
            assert info.family == "fish"

    def test_detect_from_user_db(self):
        with (
            patch.dict(os.environ, {"SHELL": ""}),
            patch("src.shell_detector._from_parent_proc", return_value=None),
            patch("src.shell_detector._from_user_db", return_value="/usr/bin/bash"),
            patch("src.shell_detector.Path.exists", return_value=True),
            patch("src.shell_detector._version", return_value="5.2"),
        ):
            info = detect()
            assert info.path == "/usr/bin/bash"
            assert info.family == "bash"

    def test_detect_fallback(self):
        with (
            patch.dict(os.environ, {"SHELL": ""}),
            patch("src.shell_detector._from_parent_proc", return_value=None),
            patch("src.shell_detector._from_user_db", return_value=None),
            patch("src.shell_detector._version", return_value=""),
        ):
            info = detect()
            assert info.path == "/bin/sh"
            assert info.family == "sh"

    def test_detect_is_cached(self):
        with (
            patch.dict(os.environ, {"SHELL": "/bin/bash"}),
            patch.object(Path, "exists", return_value=True),
            patch("src.shell_detector._version", return_value="5.2") as mock_version,
        ):
            first = detect()
            second = detect()

            assert first is second
            assert mock_version.call_count == 1

    def test_from_user_db_success(self):
        mock_entry = MagicMock()
        mock_entry.pw_shell = "/bin/zsh"
        with (
            patch("os.getuid", return_value=1000),
            patch("pwd.getpwuid", return_value=mock_entry),
        ):
            assert _from_user_db() == "/bin/zsh"

    def test_from_user_db_empty(self):
        mock_entry = MagicMock()
        mock_entry.pw_shell = ""
        with (
            patch("os.getuid", return_value=1000),
            patch("pwd.getpwuid", return_value=mock_entry),
        ):
            assert _from_user_db() is None

    def test_from_user_db_exception(self):
        with patch("pwd.getpwuid", side_effect=KeyError):
            assert _from_user_db() is None

    def test_from_parent_proc_exception(self):
        with patch("os.getppid", side_effect=OSError):
            assert _from_parent_proc() is None

    def test_from_parent_proc(self):
        with (
            patch("os.getppid", return_value=123),
            patch("src.shell_detector.Path") as mock_path,
        ):
            # mock_path(f"/proc/123/exe") returns mock_exe
            mock_exe = MagicMock()
            # mock_exe.resolve() returns resolved_path
            resolved_path = MagicMock()
            resolved_path.name = "zsh"
            resolved_path.__str__.return_value = "/usr/bin/zsh"

            mock_exe.resolve.return_value = resolved_path
            mock_path.return_value = mock_exe

            assert _from_parent_proc() == "/usr/bin/zsh"

    def test_from_parent_proc_unknown_shell(self):
        with (
            patch("os.getppid", return_value=123),
            patch("src.shell_detector.Path") as mock_path,
        ):
            mock_exe = MagicMock()
            resolved_path = MagicMock()
            resolved_path.name = "not-a-shell"

            mock_exe.resolve.return_value = resolved_path
            mock_path.return_value = mock_exe

            assert _from_parent_proc() is None
