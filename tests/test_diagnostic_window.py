import pytest
from unittest.mock import MagicMock, patch
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
import sys

from src.gui.diagnostic_window import DiagnosticWindow

@pytest.fixture
def mock_reporter():
    reporter = MagicMock()
    reporter.full_report.return_value = {
        "timestamp": "2024-01-01T12:00:00",
        "app_version": "1.0",
        "overall_status": "ok",
        "backend": {"status": "ok", "latency_ms": 100, "backend": "openai", "url": "http://localhost", "error": ""},
        "npu": {"status": "warn", "providers": ["CPUExecutionProvider"], "onnxruntime_version": "1.18", "error": ""},
        "security": {"status": "ok", "issues": 0, "checks": [{"label": "net", "status": "ok", "detail": ""}]},
        "settings": {"status": "ok", "path": "/path", "exists": True, "listener_count": 0},
        "system": {"status": "ok", "os_name": "Linux", "os_version": "1", "desktop_environment": "gnome", "shell": "bash"},
        "network": {"status": "ok", "backend_url": "http://localhost", "backend_url_is_local": True, "error": ""},
        "dependencies": [{"name": "yaml", "status": "ok", "version": "1", "required": True}],
        "tools": [{"name": "tool1", "status": "ok", "loaded": True, "description": "desc"}],
    }
    reporter.check_security.return_value = {"status": "ok", "issues": 0, "checks": []}
    return reporter

def test_diagnostic_window_safe(qtbot, mock_reporter):
    with patch("src.gui.diagnostic_window._RefreshThread.start"):
        window = DiagnosticWindow(mock_reporter, parent=None)
        qtbot.addWidget(window)
        assert "Diagnostics" in window.windowTitle()

        window.refresh()
        window._on_report(mock_reporter.full_report.return_value)
        assert "OK" in window._overall_label.text().upper()

        with patch("src.gui.diagnostic_window._TestRunThread.start"):
            window._run_tests()
            window._on_tests_done({"passed": 1, "failed": 0, "total": 1, "duration_s": 0.5, "status": "ok"})
            assert "1/1 passed" in window._test_summary.text()

        with patch("src.gui.diagnostic_window.QApplication.clipboard") as mock_clip:
            mock_obj = MagicMock()
            mock_clip.return_value = mock_obj
            window._copy_report()
            mock_obj.setText.assert_called_once()

def test_diagnostic_window_theme_error(qtbot, mock_reporter):
    with patch("src.gui.diagnostic_window._RefreshThread.start"):
        with patch("src.gui.theme.apply_to_app", side_effect=Exception("theme error")):
            window = DiagnosticWindow(mock_reporter, parent=None)
            qtbot.addWidget(window)

def test_no_qt():
    import sys
    with patch.dict(sys.modules, {'PyQt5.QtWidgets': None, 'PyQt5.QtCore': None, 'PyQt5.QtGui': None}):
        import importlib
        import src.gui.diagnostic_window
        importlib.reload(src.gui.diagnostic_window)
        assert src.gui.diagnostic_window._HAS_QT is False

    import importlib
    import src.gui.diagnostic_window
    importlib.reload(src.gui.diagnostic_window)
