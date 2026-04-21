import pytest
from unittest.mock import patch, MagicMock
from src.tools.system_control import SystemControlTool, _run_first_available


@patch("shutil.which")
@patch("subprocess.run")
def test__run_first_available_success(mock_run, mock_which):
    mock_which.side_effect = lambda cmd: cmd in ["goodcmd"]

    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = " success \n"
    mock_run.return_value = proc

    success, out = _run_first_available([["badcmd"], ["goodcmd", "arg"]])
    assert success is True
    assert out == "success"


@patch("shutil.which")
@patch("subprocess.run")
def test__run_first_available_fail(mock_run, mock_which):
    mock_which.side_effect = lambda cmd: cmd in ["cmd1"]

    proc = MagicMock()
    proc.returncode = 1
    proc.stderr = " error msg \n"
    mock_run.return_value = proc

    success, out = _run_first_available([["cmd1"]])
    assert success is False
    assert out == "error msg"


def test__run_first_available_not_found():
    with patch("shutil.which", return_value=False):
        success, out = _run_first_available([["cmd"]])
        assert success is False
        assert "No suitable backend" in out


def test_system_control_tool_run_invalid_resource():
    tool = SystemControlTool()
    res = tool.run({"resource": "invalid", "action": "get"})
    assert res.error
    assert "Unknown resource" in res.error


def test_system_control_tool_run_invalid_action():
    tool = SystemControlTool()
    res = tool.run({"resource": "audio", "action": "invalid"})
    assert res.error
    assert "Invalid action" in res.error


@patch("src.tools.system_control._run_first_available")
def test_system_control_tool_run_success(mock_run_first):
    mock_run_first.return_value = (True, "output")
    tool = SystemControlTool()
    res = tool.run({"resource": "audio", "action": "get"})
    assert not res.error
    assert "output" in res.results[0].snippet


@patch("src.tools.system_control._run_first_available")
def test_system_control_tool_run_fail(mock_run_first):
    mock_run_first.return_value = (False, "error")
    tool = SystemControlTool()
    res = tool.run({"resource": "audio", "action": "mute"})
    assert res.error
    assert "error" in res.error


@patch("src.tools.system_control._run_first_available")
def test_system_control_tool_brightness_set(mock_run_first):
    mock_run_first.return_value = (True, "set")
    tool = SystemControlTool()
    res = tool.run({"resource": "brightness", "action": "set", "value": "50%"})
    assert not res.error
    assert "50%" in res.results[0].snippet


def test_system_control_tool_brightness_set_missing_value():
    tool = SystemControlTool()
    res = tool.run({"resource": "brightness", "action": "set"})
    assert res.error
    assert "requires a 'value'" in res.error
