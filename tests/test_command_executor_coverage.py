import pytest
import subprocess
from unittest.mock import MagicMock, patch
from src.command_executor import CommandExecutor

def test_command_executor_process_response_blocked():
    executor = CommandExecutor({"blocked_commands": [r"^rm "]}, confirm_callback=lambda cmd: True)

    res = executor.process_response("```bash\nrm -rf /\n```")
    assert len(res) == 1
    assert res[0].blocked

def test_command_executor_process_response_deny():
    executor = CommandExecutor({}, confirm_callback=lambda cmd: False)

    res = executor.process_response("```bash\necho test\n```")
    assert len(res) == 1
    assert not res[0].approved

def test_command_executor_pipeline_error():
    executor = CommandExecutor({}, confirm_callback=lambda cmd: True)

    with patch("subprocess.run", side_effect=Exception("Execution Error")):
        # We need to mock _execute_pipeline because it delegates to subprocess internally in some way
        # Actually let's just patch _execute_pipeline
        with patch.object(executor, "_execute_pipeline", side_effect=Exception("Execution Error")):
            res = executor.run_command("echo test")
            assert "Execution Error" in res.stderr
            assert not res.succeeded

def test_command_executor_pipeline_timeout():
    executor = CommandExecutor({}, confirm_callback=lambda cmd: True)

    with patch.object(executor, "_execute_pipeline", side_effect=subprocess.TimeoutExpired(cmd="echo test", timeout=120)):
        res = executor.run_command("echo test")
        assert "timed out" in res.stderr
        assert not res.succeeded
