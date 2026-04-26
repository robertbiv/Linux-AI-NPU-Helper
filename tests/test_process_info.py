from unittest.mock import patch
from src.tools.process_info import (
    ProcessInfoTool,
    _proc_name,
    _proc_cmdline,
    _proc_mem_kb,
    _all_pids,
    _top_cpu,
    _top_mem,
    _battery_rate,
    _load_summary,
    _fmt_table,
)
import os


@patch("src.tools.process_info.read_sys_file")
def test_proc_name(mock_read):
    mock_read.return_value = "firefox"
    assert _proc_name(123) == "firefox"


@patch("src.tools.process_info.read_sys_file")
def test_proc_cmdline(mock_read):
    mock_read.return_value = "firefox\x00--new-window"
    assert _proc_cmdline(123) == "firefox --new-window"


@patch("src.tools.process_info.read_sys_file")
def test_proc_mem_kb(mock_read):
    mock_read.return_value = "Name:\tfirefox\nVmRSS:\t   102400 kB\n"
    assert _proc_mem_kb(123) == 102400
    mock_read.return_value = "Name:\tfirefox\n"
    assert _proc_mem_kb(123) == 0


def test_all_pids(tmp_path):
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()
    (proc_dir / "123").mkdir()
    (proc_dir / "123" / "stat").write_text("")
    (proc_dir / "abc").mkdir()

    with patch("os.scandir", return_value=os.scandir(proc_dir)):
        pids = _all_pids()
        assert pids == [123]


@patch("os.sysconf", return_value=100)
@patch("src.tools.process_info._all_pids", return_value=[123])
@patch("src.tools.process_info.read_sys_file")
@patch("time.sleep")
@patch("time.time")
@patch("src.tools.process_info._proc_name", return_value="test")
@patch("src.tools.process_info._proc_cmdline", return_value="test --arg")
@patch("src.tools.process_info._proc_mem_kb", return_value=1024)
def test_top_cpu(m_mem, m_cmd, m_name, m_time, m_sleep, m_read, m_pids, m_sysconf):
    m_read.side_effect = [
        "1 2 3 4 5 6 7 8 9 10 11 12 13 100 200",
        "1 2 3 4 5 6 7 8 9 10 11 12 13 150 250",
    ]
    m_time.side_effect = [100.0, 100.5]

    import src.tools.process_info as pi

    pi._top_cpu_cache = None
    pi._top_cpu_time = None

    res = _top_cpu(1)

    assert len(res) == 1
    assert res[0]["pid"] == 123
    assert res[0]["cpu_pct"] > 0


@patch("src.tools.process_info._all_pids", return_value=[123, 456])
@patch("src.tools.process_info._proc_mem_kb")
@patch("src.tools.process_info._proc_name", return_value="test")
@patch("src.tools.process_info._proc_cmdline", return_value="test")
def test_top_mem(m_cmd, m_name, m_mem, m_pids):
    m_mem.side_effect = lambda pid: 20480 if pid == 123 else 500
    res = _top_mem()
    assert len(res) == 1
    assert res[0]["pid"] == 123
    assert res[0]["mem_mb"] == 20.0


def test_fmt_table():
    assert "No significant processes" in _fmt_table([], "cpu_pct")
    res = _fmt_table(
        [{"pid": 1, "name": "bash", "cmdline": "-bash", "cpu_pct": 5.5}], "cpu_pct"
    )
    assert "bash" in res
    assert "5.5%" in res


def test_battery_rate_fallback():
    with (
        patch("os.scandir", side_effect=OSError),
        patch("src.tools.process_info.run_command") as m_run,
    ):
        m_run.return_value = "  energy-rate:         15.5 W\n"
        res = _battery_rate()
        assert "energy-rate" in res


@patch("src.tools.process_info.read_sys_file")
def test_battery_rate(m_read, tmp_path):
    ps_dir = tmp_path / "ps"
    ps_dir.mkdir()
    bat = ps_dir / "BAT0"
    bat.mkdir()

    class DummyContext:
        def __enter__(self): return [type("entry", (), {"name": "BAT0", "path": str(bat)})()]
        def __exit__(self, *args): pass

    with patch("src.tools.process_info.os.scandir", return_value=DummyContext()):
        m_read.side_effect = lambda path: "battery" if "type" in path else "10000000"

        res = _battery_rate()
        assert "BAT0: 10.00 W" in res


@patch("src.tools.process_info.read_sys_file")
def test_load_summary(m_read):
    m_read.side_effect = [
        "1.00 2.00 3.00 1/100 123",
        "MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\n",
    ]
    res = _load_summary()
    assert "1.00  2.00  3.00" in res
    assert "Memory:" in res


def test_process_info_tool_run_invalid_topic():
    tool = ProcessInfoTool()
    res = tool.run({"topic": "invalid"})
    assert res.error
    assert "Unknown topic" in res.error


@patch(
    "src.tools.process_info._top_cpu",
    return_value=[{"pid": 1, "name": "n", "cmdline": "c", "cpu_pct": 1, "mem_mb": 1}],
)
@patch(
    "src.tools.process_info._top_mem",
    return_value=[{"pid": 1, "name": "n", "cmdline": "c", "cpu_pct": 1, "mem_mb": 1}],
)
@patch("src.tools.process_info._battery_rate", return_value="10W")
@patch("src.tools.process_info._load_summary", return_value="load")
def test_process_info_tool_run_all(m_load, m_bat, m_mem, m_cpu):
    tool = ProcessInfoTool()
    res = tool.run({"topic": "all"})
    assert not res.error
    assert "Top by CPU" in res.results[0].snippet
    assert "Top by Memory" in res.results[0].snippet
    assert "Battery discharge" in res.results[0].snippet
    assert "System load" in res.results[0].snippet


@patch("src.tools.process_info._top_cpu", side_effect=Exception("error"))
def test_process_info_tool_run_exception(m_cpu):
    tool = ProcessInfoTool()
    res = tool.run({"topic": "cpu"})
    assert "error" in res.error
