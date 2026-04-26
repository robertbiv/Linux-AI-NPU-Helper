import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from src.tools.app import AppTool, _launch_app
import src.tools.app as app_mod
from src.tools._base import ToolResult


@pytest.fixture
def mock_desktop_dir(tmp_path):
    d = tmp_path / "applications"
    d.mkdir()
    return d


def test_launch_app_safe(mock_desktop_dir, monkeypatch):
    # Setup a safe desktop file
    safe_file = mock_desktop_dir / "safe.desktop"
    safe_file.write_text("[Desktop Entry]\nName=SafeApp\nExec=ls -l\n")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    # Mock shutil.which to return None for gtk-launch to reach the vulnerable code
    with patch("shutil.which", return_value=None):
        with patch("subprocess.Popen") as mock_popen:
            success, msg = _launch_app("SafeApp")
            assert success
            assert "Launched 'SafeApp'" in msg

            # Verify Popen call
            args, kwargs = mock_popen.call_args
            # Before fix: args[0] is "ls -l", shell=True
            # After fix: args[0] is ["ls", "-l"], shell=False (or omitted, default False)
            assert args[0] == ["ls", "-l"]
            assert kwargs.get("shell") in (False, None)
            assert kwargs.get("start_new_session") is True


def test_launch_app_injection_prevention(mock_desktop_dir, monkeypatch):
    # Setup a malicious desktop file
    malicious_file = mock_desktop_dir / "malicious.desktop"
    malicious_file.write_text(
        "[Desktop Entry]\nName=MaliciousApp\nExec=ls; touch /tmp/pwned\n"
    )

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    with patch("shutil.which", return_value=None):
        with patch("subprocess.Popen") as mock_popen:
            success, msg = _launch_app("MaliciousApp")
            assert success

            args, kwargs = mock_popen.call_args
            # If shell=False, "ls; touch /tmp/pwned" will be treated as a single command name if not split,
            # or if split, ["ls;", "touch", "/tmp/pwned"] which will fail to find "ls;".
            # Either way, it won't execute the second command via shell.
            # We will verify the exact behavior after the fix.
            assert args[0] == ["ls;", "touch", "/tmp/pwned"]
            assert kwargs.get("shell") in (False, None)


def test_app_tool_open(mock_desktop_dir, monkeypatch):
    safe_file = mock_desktop_dir / "safe.desktop"
    safe_file.write_text("[Desktop Entry]\nName=SafeApp\nExec=ls -l\n")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    tool = AppTool()
    with patch("shutil.which", return_value=None):
        with patch("subprocess.Popen"):
            result = tool.run({"action": "open", "name": "SafeApp"})
            assert isinstance(result, ToolResult)
            assert not result.error
            assert "Launched 'SafeApp'" in result.results[0].snippet


def test_app_tool_search(mock_desktop_dir, monkeypatch):
    safe_file = mock_desktop_dir / "safe.desktop"
    safe_file.write_text(
        "[Desktop Entry]\nName=SafeApp\nComment=A safe application\nExec=ls -l\n"
    )

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    tool = AppTool()
    with patch("src.tools.app._find_pkg_manager", return_value=None):
        result = tool.run({"action": "search", "name": "Safe"})
        assert not result.error
        assert len(result.results) > 0
        assert "SafeApp" in result.results[0].snippet


def test_app_tool_install(monkeypatch):
    tool = AppTool()
    with patch(
        "src.terminal_launcher.open_with_command", return_value=(True, "Success")
    ):
        result = tool.run({"action": "install", "name": "firefox"})
        assert not result.error
        assert "firefox" in result.results[0].snippet


def test_launch_app_posix_args_fix(mock_desktop_dir, monkeypatch):
    """Verify the fix for subprocess args splitting on POSIX systems."""
    if os.name != "posix":
        pytest.skip("This test only applies to POSIX systems")

    # Setup a desktop file with arguments
    args_file = mock_desktop_dir / "args.desktop"
    args_file.write_text("[Desktop Entry]\nName=ArgsApp\nExec=ls -l\n")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    # Mock gtk-launch as unavailable
    with patch("shutil.which", return_value=None):
        # We need to mock Popen to verify arguments
        with patch("subprocess.Popen") as mock_popen:
            # Setup mock to return immediately
            mock_popen.return_value = MagicMock()

            tool = AppTool()
            # Simulate the 'run ls -l' or 'open ArgsApp' behavior
            # In our current tool, it's called via action='open', name='ArgsApp'
            result = tool.run({"action": "open", "name": "ArgsApp"})

            assert not result.error

            # Verify Popen call
            args, kwargs = mock_popen.call_args
            # After fix: args[0] is ["ls", "-l"], shell=False
            assert args[0] == ["ls", "-l"]
            assert kwargs.get("shell") is False


def test_launch_app_plain_binary_args(monkeypatch):
    """Verify that plain binary execution also splits arguments."""

    def mock_which(cmd):
        if cmd == "ls":
            return "/usr/bin/ls"
        return None

    with patch("shutil.which", side_effect=mock_which):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()

            success, msg = _launch_app("ls -l")
            assert success
            assert "Launched 'ls -l'" in msg

            args, kwargs = mock_popen.call_args
            assert args[0] == ["/usr/bin/ls", "-l"]
            assert kwargs.get("shell") is False

def test_app_tool_invalid_action():
    tool = AppTool()
    result = tool.run({"action": "destroy", "name": "firefox"})
    assert result.error
    assert "Unknown action" in result.error

def test_app_tool_missing_name():
    tool = AppTool()
    result = tool.run({"action": "open"})
    assert result.error
    assert "'name' is required" in result.error

def test_launch_app_gtk_launch(mock_desktop_dir, monkeypatch):
    safe_file = mock_desktop_dir / "testapp.desktop"
    safe_file.write_text("[Desktop Entry]\nName=TestApp\nExec=ls\n")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    # Mock gtk-launch available and returns 0
    with patch("shutil.which", return_value="/usr/bin/gtk-launch"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success, msg = _launch_app("TestApp")
            assert success
            assert "via gtk-launch" in msg
            args, kwargs = mock_run.call_args
            assert args[0] == ["gtk-launch", "testapp"]

def test_launch_app_gtk_launch_fail_fallback(mock_desktop_dir, monkeypatch):
    safe_file = mock_desktop_dir / "testapp.desktop"
    safe_file.write_text("[Desktop Entry]\nName=TestApp\nExec=ls\n")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    with patch("shutil.which", return_value="/usr/bin/gtk-launch"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1) # Fails
            with patch("subprocess.Popen") as mock_popen: # Fallbacks to Popen
                success, msg = _launch_app("TestApp")
                assert success
                assert "via testapp.desktop" in msg
                mock_popen.assert_called_once()

def test_launch_app_plain_binary_not_found(monkeypatch):
    monkeypatch.setattr(app_mod, "_desktop_cache", [])

    with patch("shutil.which", return_value=None):
        success, msg = _launch_app("nonexistent_binary")
        assert not success
        assert "Could not find application" in msg

def test_search_package_manager_found(monkeypatch):
    tool = AppTool()
    with patch("src.tools.app._find_pkg_manager", return_value=("apt", ["apt", "search"])):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="pkg1\npkg2", returncode=0)
            result = tool.run({"action": "search", "name": "pkg"})
            assert not result.error
            assert len(result.results) == 2
            assert result.results[0].snippet == "pkg1"

def test_search_package_manager_timeout(monkeypatch):
    tool = AppTool()
    with patch("src.tools.app._find_pkg_manager", return_value=("apt", ["apt", "search"])):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("apt", 20)):
            result = tool.run({"action": "search", "name": "pkg"})
            assert not result.error
            assert "timed out" in result.results[0].snippet

def test_search_no_results(monkeypatch):
    tool = AppTool()
    monkeypatch.setattr(app_mod, "_desktop_cache", [])
    with patch("src.tools.app._find_pkg_manager", return_value=None):
        result = tool.run({"action": "search", "name": "does_not_exist"})
        assert result.error
        assert "No applications" in result.error

def test_install_os_detect_fallback(monkeypatch):
    tool = AppTool()
    with patch("src.os_detector.detect", side_effect=Exception("detect fail")):
        with patch("src.terminal_launcher.open_with_command", return_value=(False, "Terminal error")) as mock_open:
            result = tool.run({"action": "install", "name": "curl"})
            assert result.error == "Terminal error"
            mock_open.assert_called_once_with("sudo apt install curl")

def test_desktop_field_no_display(mock_desktop_dir, monkeypatch):
    f = mock_desktop_dir / "hidden.desktop"
    f.write_text("[Desktop Entry]\nName=Hidden\nNoDisplay=true\nExec=ls")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    # Should not be loaded into cache
    cache = app_mod._load_desktop_cache()
    assert len(cache) == 0


def test_load_desktop_cache_oserror_dir(monkeypatch):
    # Pass a path that raises OSError on scandir
    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [Path("/root/nonexistent_restricted")])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    with patch("os.scandir", side_effect=OSError):
        cache = app_mod._load_desktop_cache()
        assert cache == []

def test_load_desktop_cache_oserror_file(mock_desktop_dir, monkeypatch):
    f = mock_desktop_dir / "error.desktop"
    f.write_text("[Desktop Entry]\nName=Err\nExec=ls")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    def mock_open(*args, **kwargs):
        raise OSError("Permission denied")

    with patch("builtins.open", side_effect=mock_open):
        cache = app_mod._load_desktop_cache()
        assert cache == []

def test_load_desktop_cache_seen_file(mock_desktop_dir, monkeypatch):
    f1 = mock_desktop_dir / "duplicate.desktop"
    f1.write_text("[Desktop Entry]\nName=Dup\nExec=ls")

    dir2 = mock_desktop_dir / "other_dir"
    dir2.mkdir()
    f2 = dir2 / "duplicate.desktop"
    f2.write_text("[Desktop Entry]\nName=Dup2\nExec=ls")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir, dir2])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    cache = app_mod._load_desktop_cache()
    # It should only load the first one it sees (from mock_desktop_dir)
    assert len(cache) == 1
    assert cache[0]["name"] == "Dup"

def test_load_desktop_cache_skip_non_desktop(mock_desktop_dir, monkeypatch):
    f = mock_desktop_dir / "not_a_desktop.txt"
    f.write_text("Hello")

    # create a directory too
    d = mock_desktop_dir / "subdir"
    d.mkdir()

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    cache = app_mod._load_desktop_cache()
    assert len(cache) == 0


def test_find_pkg_manager_success():
    import src.tools.app as app_mod
    # Need to clear lru_cache first
    app_mod._find_pkg_manager.cache_clear()

    def mock_which(exe):
        if exe == "dnf":
            return "/usr/bin/dnf"
        return None

    with patch("shutil.which", side_effect=mock_which):
        pm = app_mod._find_pkg_manager()
        assert pm is not None
        assert pm[0] == "dnf"

    app_mod._find_pkg_manager.cache_clear()

def test_find_pkg_manager_none():
    import src.tools.app as app_mod
    app_mod._find_pkg_manager.cache_clear()

    with patch("shutil.which", return_value=None):
        pm = app_mod._find_pkg_manager()
        assert pm is None

    app_mod._find_pkg_manager.cache_clear()

def test_launch_app_exec_fail(mock_desktop_dir, monkeypatch):
    f = mock_desktop_dir / "bad.desktop"
    f.write_text("[Desktop Entry]\nName=Bad\nExec=invalid_cmd_123")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    # We want Popen to fail to hit the "except Exception as exc:" block
    with patch("shutil.which", return_value=None):
        with patch("subprocess.Popen", side_effect=OSError("Test error")):
            success, msg = _launch_app("Bad")
            assert not success

def test_launch_app_plain_binary_shlex_fail(monkeypatch):
    monkeypatch.setattr(app_mod, "_desktop_cache", [])

    # We want shlex.split to fail with ValueError
    # A single quote without a closing quote will cause ValueError
    with patch("shutil.which", return_value="/bin/ls"):
        with patch("subprocess.Popen"):
            success, msg = _launch_app("ls 'unterminated")
            assert success
            assert "Launched" in msg

def test_launch_app_plain_binary_fail(monkeypatch):
    monkeypatch.setattr(app_mod, "_desktop_cache", [])

    with patch("shutil.which", return_value="/bin/ls"):
        with patch("subprocess.Popen", side_effect=OSError("Test Popen Error")):
            success, msg = _launch_app("ls")
            assert not success
            assert "Test Popen Error" in msg

def test_launch_app_exec_empty(mock_desktop_dir, monkeypatch):
    f = mock_desktop_dir / "empty.desktop"
    f.write_text("[Desktop Entry]\nName=Empty\nExec=\n")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    with patch("shutil.which", return_value=None):
        success, msg = _launch_app("Empty")
        assert not success

def test_desktop_field_regex_no_match():
    assert app_mod._desktop_field("Name", "Name") == ""


def test_search_package_manager_exception(monkeypatch):
    tool = AppTool()
    monkeypatch.setattr(app_mod, "_desktop_cache", [])

    with patch("src.tools.app._find_pkg_manager", return_value=("apt", ["apt", "search"])):
        with patch("subprocess.run", side_effect=Exception("mock err")):
            with patch("src.tools.app.logger.warning") as mock_warn:
                result = tool.run({"action": "search", "name": "pkg"})
                mock_warn.assert_called_once()
                assert result.error
                assert "No applications" in result.error

def test_load_desktop_cache_oserror_outer_dir(monkeypatch):
    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [Path("/root/restricted_desktop_dir")])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)
    with patch("os.scandir", side_effect=OSError):
        cache = app_mod._load_desktop_cache()
        assert cache == []

def test_install_os_detect_no_install_command(monkeypatch):
    tool = AppTool()
    mock_os_info = MagicMock()
    mock_os_info.install_command = None
    with patch("src.os_detector.detect", return_value=mock_os_info):
        with patch("src.terminal_launcher.open_with_command", return_value=(True, "OK")) as mock_open:
            result = tool.run({"action": "install", "name": "curl"})
            assert not result.error
            mock_open.assert_called_once_with("sudo apt install curl")

def test_app_tool_open_fail():
    tool = AppTool()
    with patch("src.tools.app._launch_app", return_value=(False, "Failed to open")):
        result = tool.run({"action": "open", "name": "test"})
        assert result.error == "Failed to open"

def test_schema_text():
    tool = AppTool()
    schema = tool.schema_text()
    assert "app(action: open|search|install, name: string)" in schema

def test_launch_app_gtk_launch_exception(mock_desktop_dir, monkeypatch):
    safe_file = mock_desktop_dir / "testapp.desktop"
    safe_file.write_text("[Desktop Entry]\nName=TestApp\nExec=ls\n")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    # Force gtk-launch to raise an exception
    with patch("shutil.which", return_value="/usr/bin/gtk-launch"):
        with patch("subprocess.run", side_effect=Exception("gtk-launch error")):
            # Should catch the exception and fall back to Popen
            with patch("subprocess.Popen") as mock_popen:
                success, msg = _launch_app("TestApp")
                assert success
                assert "via testapp.desktop" in msg

def test_load_desktop_cache_oserror_read(mock_desktop_dir, monkeypatch):
    f = mock_desktop_dir / "err.desktop"
    f.write_text("dummy")

    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    # Force OSError when reading file inside the valid dir
    original_open = open
    def mock_open(path, *args, **kwargs):
        if path.endswith("err.desktop"):
            raise OSError("read err")
        return original_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open):
        cache = app_mod._load_desktop_cache()
        assert cache == []

def test_load_desktop_cache_oserror_on_scandir(mock_desktop_dir, monkeypatch):
    monkeypatch.setattr(app_mod, "_DESKTOP_DIRS", [mock_desktop_dir])
    monkeypatch.setattr(app_mod, "_desktop_cache", None)

    # Force OSError specifically when scandir context manager tries to iterate
    # The current code:
    # try:
    #     with os.scandir(d) as it: ...
    # except OSError: continue

    with patch("os.scandir", side_effect=OSError("scandir err")):
        cache = app_mod._load_desktop_cache()
        assert cache == []
