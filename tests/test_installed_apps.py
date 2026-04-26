from unittest.mock import patch
from src.tools.installed_apps import (
    InstalledAppsTool,
    _scan_desktop,
    _scan_flatpak,
    _scan_snap,
    _scan_packages,
    _scan_path,
)


@patch("src.tools.app._load_desktop_cache")
def test_scan_desktop(mock_load):
    mock_load.return_value = [
        {
            "name": "Firefox",
            "comment": "Web Browser",
            "file": "/usr/share/applications/firefox.desktop",
        },
        {
            "name": "Vim",
            "comment": "Text Editor",
            "file": "/usr/share/applications/vim.desktop",
        },
    ]

    res_all = _scan_desktop()
    assert len(res_all) == 2

    res_q = _scan_desktop("fire")
    assert len(res_q) == 1
    assert res_q[0]["name"] == "Firefox"

    res_q2 = _scan_desktop("editor")
    assert len(res_q2) == 1
    assert res_q2[0]["name"] == "Vim"

    res_q3 = _scan_desktop("nonexistent")
    assert len(res_q3) == 0


@patch("src.tools.installed_apps.run_command")
def test_scan_flatpak(mock_run):
    mock_run.return_value = (
        "org.mozilla.firefox\tFirefox\t123.0\norg.gnome.Terminal\tTerminal\t3.38\n"
    )

    res_all = _scan_flatpak()
    assert len(res_all) == 2

    res_q = _scan_flatpak("fire")
    assert len(res_q) == 1
    assert res_q[0]["name"] == "Firefox"


@patch("src.tools.installed_apps.run_command")
def test_scan_snap(mock_run):
    mock_run.return_value = "Name  Version  Rev  Tracking  Publisher  Notes\nfirefox  123.0  1  latest/stable  mozilla  -\nchromium  122.0  2  latest/stable  canonical  -\n"

    res_all = _scan_snap()
    assert len(res_all) == 2

    res_q = _scan_snap("fire")
    assert len(res_q) == 1
    assert res_q[0]["name"] == "firefox"


@patch("src.tools.installed_apps.run_command")
def test_scan_packages_dpkg(mock_run):
    mock_run.side_effect = [
        "bash\t5.1-6ubuntu1\tinstall ok installed\ncurl\t7.81.0\tinstall ok installed\nbroken\t1.0\tdeinstall ok config-files\n",
        "",
    ]

    res_all = _scan_packages()
    assert len(res_all) == 2

    # reset side effect since _scan_packages calls run_command twice if dpkg returns nothing
    mock_run.side_effect = [
        "bash\t5.1-6ubuntu1\tinstall ok installed\ncurl\t7.81.0\tinstall ok installed\n",
        "",
    ]
    res_q = _scan_packages("bash")
    assert len(res_q) == 1
    assert res_q[0]["name"] == "bash"


@patch("src.tools.installed_apps.run_command")
def test_scan_packages_rpm(mock_run):
    mock_run.side_effect = ["", "bash\t5.1\ncurl\t7.81.0\n"]

    res_all = _scan_packages()
    assert len(res_all) == 2

    mock_run.side_effect = ["", "bash\t5.1\ncurl\t7.81.0\n"]
    res_q = _scan_packages("bash")
    assert len(res_q) == 1
    assert res_q[0]["name"] == "bash"


def test_scan_path(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    f1 = bin_dir / "my_app"
    f1.write_text("")
    f1.chmod(0o755)

    f2 = bin_dir / "other_app"
    f2.write_text("")
    f2.chmod(0o644)  # not executable

    dir1 = bin_dir / "my_dir"
    dir1.mkdir()

    monkeypatch.setenv("PATH", str(bin_dir))

    res_all = _scan_path()
    assert len(res_all) == 1
    assert res_all[0]["name"] == "my_app"

    res_q = _scan_path("my")
    assert len(res_q) == 1

    res_q2 = _scan_path("other")
    assert len(res_q2) == 0


@patch(
    "src.tools.installed_apps._scan_desktop",
    return_value=[{"source": "desktop", "name": "App1"}],
)
@patch(
    "src.tools.installed_apps._scan_flatpak",
    return_value=[{"source": "flatpak", "name": "App2"}],
)
@patch(
    "src.tools.installed_apps._scan_snap",
    return_value=[{"source": "snap", "name": "App3"}],
)
@patch(
    "src.tools.installed_apps._scan_packages",
    return_value=[{"source": "deb", "name": "App4"}],
)
@patch(
    "src.tools.installed_apps._scan_path",
    return_value=[{"source": "path", "name": "App5"}],
)
def test_run_all_sources(m1, m2, m3, m4, m5):
    tool = InstalledAppsTool()
    res = tool.run({"sources": ["all"]})
    assert not res.error
    assert len(res.results) == 5


@patch("src.tools.installed_apps._scan_desktop", return_value=[])
def test_run_no_results(mock_desktop):
    tool = InstalledAppsTool()
    res = tool.run({"sources": ["desktop"]})
    assert res.error == "No installed apps found."

    res2 = tool.run({"query": "fake", "sources": ["desktop"]})
    assert res2.error == "No apps found matching 'fake'."
