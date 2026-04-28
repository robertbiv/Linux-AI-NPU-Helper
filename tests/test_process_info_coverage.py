import pytest
import os
import time
from src.tools.process_info import ProcessInfoTool, _proc_name, _proc_cmdline, _proc_mem_kb, _all_pids, _top_cpu, _top_mem, _fmt_table, _battery_rate, _load_summary
from unittest.mock import patch, mock_open, MagicMock

def test_process_info_tool_invalid():
    tool = ProcessInfoTool()
    res = tool.run({"topic": "invalid"})
    assert "Unknown topic" in res.error

def test_proc_mem_kb():
    # Valid
    with patch("src.tools.process_info.read_sys_file", return_value="Name:\tbash\nVmRSS:\t   10000 kB\n"):
        assert _proc_mem_kb(1) == 10000

    # Missing VmRSS
    with patch("src.tools.process_info.read_sys_file", return_value="Name:\tbash\n"):
        assert _proc_mem_kb(1) == 0

    # Invalid VmRSS
    with patch("src.tools.process_info.read_sys_file", return_value="Name:\tbash\nVmRSS:\t   invalid kB\n"):
        assert _proc_mem_kb(1) == 0

def test_all_pids():
    mock_entry1 = MagicMock()
    mock_entry1.name = "1"
    mock_entry1.is_dir.return_value = True
    mock_entry1.path = "/proc/1"

    mock_entry2 = MagicMock()
    mock_entry2.name = "a"

    class MockScandirContext:
        def __init__(self, entries):
            self.entries = entries
        def __enter__(self):
            return self.entries
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("os.scandir", return_value=MockScandirContext([mock_entry1, mock_entry2])):
        with patch("os.stat"):
            assert _all_pids() == [1]

def test_all_pids_exceptions():
    with patch("os.scandir", side_effect=OSError):
        assert _all_pids() == []

    mock_entry1 = MagicMock()
    mock_entry1.name = "1"
    mock_entry1.is_dir.return_value = True

    class MockScandirContext:
        def __init__(self, entries):
            self.entries = entries
        def __enter__(self):
            return self.entries
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("os.scandir", return_value=MockScandirContext([mock_entry1])):
        with patch("os.stat", side_effect=OSError):
            assert _all_pids() == []

def test_top_cpu():
    import src.tools.process_info
    src.tools.process_info._top_cpu_cache = None
    src.tools.process_info._top_cpu_time = None

    with patch("src.tools.process_info._all_pids", return_value=[1]):
        def mock_read(path):
            if "stat" in path:
                if not hasattr(mock_read, "called"):
                    mock_read.called = True
                    return "0 0 0 0 0 0 0 0 0 0 0 0 0 100 200"
                else:
                    return "0 0 0 0 0 0 0 0 0 0 0 0 0 500 600"
            if "comm" in path: return "name"
            if "cmdline" in path: return "cmdline"
            if "status" in path: return "VmRSS: 2000 kB\n"
            return ""

        with patch("src.tools.process_info.read_sys_file", side_effect=mock_read):
            with patch("time.sleep"):
                with patch("time.time", side_effect=[100.0, 100.5, 100.5, 100.5, 100.5]):
                    res = _top_cpu()
                    assert len(res) > 0
                    assert res[0]["pid"] == 1
                    assert res[0]["name"] == "name"

def test_top_cpu_fast_diff():
    import src.tools.process_info
    src.tools.process_info._top_cpu_cache = None
    src.tools.process_info._top_cpu_time = None

    with patch("src.tools.process_info._all_pids", return_value=[1]):
        def mock_read(path):
            if "stat" in path:
                if not hasattr(mock_read, "called"):
                    mock_read.called = True
                    return "0 0 0 0 0 0 0 0 0 0 0 0 0 100 200"
                elif not hasattr(mock_read, "called2"):
                    mock_read.called2 = True
                    return "0 0 0 0 0 0 0 0 0 0 0 0 0 500 600"
                else:
                    return "0 0 0 0 0 0 0 0 0 0 0 0 0 900 1000"
            if "comm" in path: return "name"
            if "cmdline" in path: return "cmdline"
            if "status" in path: return "VmRSS: 2000 kB\n"
            return ""

        with patch("src.tools.process_info.read_sys_file", side_effect=mock_read):
            with patch("time.sleep"):
                with patch("time.time", side_effect=[100.0, 100.05, 100.5, 100.5, 100.5]): # Second time is <0.1 diff
                    res = _top_cpu()
                    assert len(res) > 0

def test_top_cpu_exception():
    import src.tools.process_info
    src.tools.process_info._top_cpu_cache = None
    src.tools.process_info._top_cpu_time = None

    with patch("src.tools.process_info._all_pids", return_value=[1]):
        def mock_read(path):
            if "stat" in path:
                return "0" # Will cause IndexError
            if "comm" in path: return "name"
            if "cmdline" in path: return "cmdline"
            if "status" in path: return "VmRSS: 2000 kB\n"
            return ""

        with patch("src.tools.process_info.read_sys_file", side_effect=mock_read):
            with patch("time.sleep"):
                with patch("time.time", side_effect=[100.0, 100.5, 100.5, 100.5, 100.5]):
                    res = _top_cpu()
                    assert len(res) == 0

def test_top_mem():
    with patch("src.tools.process_info._all_pids", return_value=[1]):
        with patch("src.tools.process_info._proc_mem_kb", return_value=2048):
            with patch("src.tools.process_info._proc_name", return_value="name"):
                with patch("src.tools.process_info._proc_cmdline", return_value="cmdline"):
                    res = _top_mem()
                    assert len(res) == 1
                    assert res[0]["pid"] == 1

def test_fmt_table():
    assert _fmt_table([], "cpu_pct") == "No significant processes found."
    procs = [{"pid": 1, "name": "test", "cmdline": "test cmd", "cpu_pct": 10.5}]
    res = _fmt_table(procs, "cpu_pct")
    assert "test" in res
    assert "10.5%" in res

def test_battery_rate():
    mock_power_supply = MagicMock()
    mock_power_supply.name = "BAT0"
    mock_power_supply.is_dir.return_value = True
    mock_power_supply.path = "/sys/class/power_supply/BAT0"

    class MockScandirContext:
        def __init__(self, entries):
            self.entries = entries
        def __enter__(self):
            return self.entries
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("os.scandir", return_value=MockScandirContext([mock_power_supply])):
        def mock_read(path):
            if "type" in path: return "Battery"
            if "power_now" in path: return "15000000"
            return ""
        with patch("src.tools.process_info.read_sys_file", mock_read):
            res = _battery_rate()
            assert "15.00 W" in res

def test_battery_rate_fallback():
    with patch("os.scandir", side_effect=OSError):
        with patch("src.tools.process_info.run_command", return_value="energy-rate: 10.0 W"):
            res = _battery_rate()
            assert "energy-rate: 10.0 W" in res

def test_battery_rate_value_error():
    mock_power_supply = MagicMock()
    mock_power_supply.name = "BAT0"
    mock_power_supply.path = "/sys/class/power_supply/BAT0"

    class MockScandirContext:
        def __init__(self, entries):
            self.entries = entries
        def __enter__(self):
            return self.entries
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("os.scandir", return_value=MockScandirContext([mock_power_supply])):
        def mock_read(path):
            if "type" in path: return "Battery"
            if "power_now" in path: return "invalid"
            return ""
        with patch("src.tools.process_info.read_sys_file", mock_read):
            with patch("src.tools.process_info.run_command", return_value=""):
                res = _battery_rate()
                assert "Battery rate unavailable." in res

def test_load_summary():
    with patch("src.tools.process_info.read_sys_file", side_effect=["0.10 0.15 0.20", "MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\n"]):
        res = _load_summary()
        assert "0.10  0.15  0.20" in res
        assert "used" in res

def test_load_summary_exceptions():
    with patch("src.tools.process_info.read_sys_file", side_effect=["", "MemTotal: invalid kB\nMemAvailable: invalid kB\n"]):
        res = _load_summary()
        assert res == ""

def test_process_info_tool_all():
    tool = ProcessInfoTool()
    with patch("src.tools.process_info._top_cpu", return_value=[]):
        with patch("src.tools.process_info._top_mem", return_value=[]):
            with patch("src.tools.process_info._battery_rate", return_value=""):
                with patch("src.tools.process_info._load_summary", return_value=""):
                    res = tool.run({"topic": "all"})
                    assert "Top by CPU" in res.results[0].snippet

def test_process_info_tool_exception():
    tool = ProcessInfoTool()
    with patch("src.tools.process_info._top_cpu", side_effect=Exception("Tool error")):
        res = tool.run({"topic": "cpu"})
        assert "Tool error" in res.error
