import pytest
from unittest.mock import patch, MagicMock
from src.tools.system_info import (
    SystemInfoTool,
    _fmt_seconds,
    _query_time,
    _query_uptime,
    _query_battery,
    _query_battery_health,
    _query_gpu,
    _query_cpu,
    _query_memory,
    _query_disk,
    _query_os,
    _query_network,
    _query_all,
    _QUERIES,
)
import os


def test_fmt_seconds():
    assert "1 hour" in _fmt_seconds(3600)
    assert "1 hour" in _fmt_seconds(3660)


@patch("src.tools.system_info.run_command")
def test_query_time(m_run):
    m_run.return_value = "timezone"
    res = _query_time()
    assert len(res) > 0


@patch("src.tools.system_info.read_sys_file")
@patch("src.tools.system_info.run_command")
def test_query_uptime(m_run, m_read):
    m_read.return_value = "3600.00 1234.56"
    assert "1 hour" in _query_uptime()

    m_read.return_value = ""
    m_run.return_value = "uptime"
    assert "uptime" in _query_uptime()


@patch("os.scandir")
@patch("src.tools.system_info.read_sys_file")
@patch("src.tools.system_info.Path")
def test_query_battery(m_path, m_read, m_scan, tmp_path):
    ps_dir = tmp_path / "ps"
    ps_dir.mkdir()
    bat = ps_dir / "BAT0"
    bat.mkdir()

    m_path_obj = MagicMock()
    m_path_obj.exists.return_value = True
    m_path.return_value = m_path_obj

    class DummyDirEntry:
        def __init__(self, name, path):
            self.name = name
            self.path = path

    m_scan.return_value = __import__("contextlib").nullcontext(
        [DummyDirEntry("BAT0", str(bat))]
    )

    def side_effect(path):
        if "type" in path:
            return "Battery"
        if "capacity" in path:
            return "80"
        if "status" in path:
            return "Discharging"
        return ""

    m_read.side_effect = side_effect

    res = _query_battery()
    assert "BAT0: 80% (Discharging)" in res


@patch("src.tools.system_info.run_command")
def test_query_gpu(m_run):
    m_run.side_effect = ["NVIDIA", "AMD", "Intel"]
    res = _query_gpu()
    assert "NVIDIA" in res


@patch("src.tools.system_info.read_sys_file")
def test_query_cpu(m_read):
    m_read.return_value = "model name : Intel(R) Core(TM) i7\nphysical id: 0\ncore id: 0\nprocessor: 0\ncpu MHz: 2400.0\n"
    res = _query_cpu()
    assert "Intel(R) Core(TM) i7" in res


@patch("src.tools.system_info.read_sys_file")
def test_query_memory(m_read):
    m_read.return_value = "MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\n"
    res = _query_memory()
    assert "RAM" in res


@patch("src.tools.system_info.run_command")
def test_query_disk(m_run):
    m_run.return_value = "disk space"
    res = _query_disk()
    assert "disk space" in res


@patch("src.os_detector.detect")
def test_query_os(m_detect):
    m_os = MagicMock()
    m_os.pretty_name = "Ubuntu"
    m_detect.return_value = m_os
    res = _query_os()
    assert "Ubuntu" in res


@patch("src.tools.system_info.run_command")
def test_query_network(m_run):
    m_run.return_value = "eth0 UP 192.168.1.2\n"
    res = _query_network()
    assert "eth0" in res


@patch.dict(
    _QUERIES, {"cpu": lambda: "cpu info", "memory": lambda: "mem info"}, clear=True
)
def test_query_all():
    res = _query_all()
    assert "cpu info" in res
    assert "mem info" in res


def test_system_info_tool_run_invalid_topic():
    tool = SystemInfoTool()
    res = tool.run({"topic": "invalid"})
    assert res.error
    assert "Unknown topic" in res.error


@patch("src.tools.system_info._query_all", return_value="all info")
def test_system_info_tool_run_all(m_all):
    tool = SystemInfoTool()
    res = tool.run({"topic": "all"})
    assert not res.error
    assert "all info" in res.results[0].snippet


@patch.dict(_QUERIES, {"cpu": lambda: "cpu info"}, clear=True)
def test_system_info_tool_run_topic():
    tool = SystemInfoTool()
    res = tool.run({"topic": "cpu"})
    assert not res.error
    assert "cpu info" in res.results[0].snippet
