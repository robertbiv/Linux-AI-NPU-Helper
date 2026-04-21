
import os
import subprocess
import shutil
import shlex
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from src.tools.app import AppTool, _launch_app
import src.tools.app as app_mod
from src.tools._base import ToolResult, SearchResult

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
    malicious_file.write_text("[Desktop Entry]\nName=MaliciousApp\nExec=ls; touch /tmp/pwned\n")

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
    safe_file.write_text("[Desktop Entry]\nName=SafeApp\nComment=A safe application\nExec=ls -l\n")

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
    with patch("src.terminal_launcher.open_with_command", return_value=(True, "Success")):
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
