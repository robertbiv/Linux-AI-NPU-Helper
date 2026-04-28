import pytest
import subprocess
from unittest.mock import patch, MagicMock
from src.tools.system_control import SystemControlTool, _run_first_available

def test_run_first_available_timeout():
    with patch("shutil.which", return_value="cmd"):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="cmd", timeout=8)):
            success, output = _run_first_available([["cmd"]])
            assert success is False
            assert "timed out" in output

def test_run_first_available_exception():
    with patch("shutil.which", return_value="cmd"):
        with patch("subprocess.run", side_effect=Exception("Generic Error")):
            success, output = _run_first_available([["cmd"]])
            assert success is False
            assert "Generic Error" in output

def test_system_control_invalid_args():
    tool = SystemControlTool()
    res = tool.run({"resource": "invalid", "action": "get"})
    assert "Unknown resource" in res.error

    res = tool.run({"resource": "audio", "action": "invalid"})
    assert "Invalid action" in res.error

def test_system_control_no_candidates():
    tool = SystemControlTool()
    with patch("src.tools.system_control._RESOURCE_ACTIONS", {"audio": {}}):
        res = tool.run({"resource": "audio", "action": "get"})
        assert "No backend commands defined" in res.error

def test_system_control_set_brightness():
    tool = SystemControlTool()

    # Empty value
    res = tool.run({"resource": "brightness", "action": "set", "value": ""})
    assert "requires a 'value'" in res.error

    # Set percentage success
    with patch("src.tools.system_control._run_first_available", return_value=(True, "")):
        res = tool.run({"resource": "brightness", "action": "set", "value": "50"})
        assert "Brightness set to 50" in res.results[0].snippet

    # Set percentage fail
    with patch("src.tools.system_control._run_first_available", return_value=(False, "Failed")):
        res = tool.run({"resource": "brightness", "action": "set", "value": "50%"})
        assert "Could not set brightness" in res.error

def test_system_control_schema_text():
    tool = SystemControlTool()
    res = tool.schema_text()
    assert "system_control" in res
