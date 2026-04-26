import pytest
from unittest.mock import MagicMock, patch

from PyQt5.QtWidgets import QWidget, QDialogButtonBox
from src.gui.model_manager import _TosDialog, ModelManagerWidget, NPUCatalogWidget, _BackendModelPanel

# Mock settings manager
@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.get.return_value = {"base_url": "http://localhost"}
    return settings

class DummyEntry:
    def __init__(self, name, tos_url, publisher="Test Publisher", license_spdx="MIT", tos_summary="Summ", key="test_model", is_vision=False):
        self.name = name
        self.tos_url = tos_url
        self.publisher = publisher
        self.license_spdx = license_spdx
        self.tos_summary = tos_summary
        self.key = key
        self.is_vision = is_vision

def test_tos_dialog_accept(qtbot):
    mock_entry = DummyEntry("Test Model", "https://example.com")
    dialog = _TosDialog(mock_entry)
    qtbot.addWidget(dialog)
    ok_btn = dialog._buttons.button(QDialogButtonBox.Ok)
    assert not ok_btn.isEnabled()

    # Checkbox check enables download
    dialog._chk.setChecked(True)
    assert ok_btn.isEnabled()

    # Pressing accept calls accept
    dialog.accept()

def test_tos_dialog_open_link(qtbot):
    mock_entry = DummyEntry("Test Model", "https://example.com")
    dialog = _TosDialog(mock_entry)
    with patch("webbrowser.open") as mock_open:
        from PyQt5.QtWidgets import QPushButton
        btns = dialog.findChildren(QPushButton)
        read_btn = next((b for b in btns if "Read full terms" in b.text()), None)
        assert read_btn is not None
        read_btn.click()
        mock_open.assert_called_once_with("https://example.com")

class DummyWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__()
    def refresh_all(self):
        pass
    def refresh(self):
        pass

def test_model_manager_init(qtbot, mock_settings):
    with patch("src.gui.model_manager.NPUCatalogWidget", DummyWidget):
        with patch("src.gui.model_manager._BackendModelPanel", DummyWidget):
            widget = ModelManagerWidget(mock_settings)
            qtbot.addWidget(widget)
            assert widget._manager == mock_settings
            from PyQt5.QtWidgets import QTabWidget
            tabs = widget.findChild(QTabWidget)
            assert tabs is not None

def test_model_manager_refresh(qtbot, mock_settings):
    with patch("src.gui.model_manager.NPUCatalogWidget", DummyWidget):
        with patch("src.gui.model_manager._BackendModelPanel", DummyWidget):
            widget = ModelManagerWidget(mock_settings)
            qtbot.addWidget(widget)
            with patch.object(widget._catalog, "refresh_all") as mock_cat_refresh:
                with patch.object(widget._backend, "refresh") as mock_back_refresh:
                    widget.refresh()
                    mock_cat_refresh.assert_called_once()
                    mock_back_refresh.assert_called_once()

def test_npu_catalog_widget_init(qtbot, mock_settings):
    with patch("src.npu_model_installer.get_vision_models", return_value=[DummyEntry("v1", "", is_vision=True)]):
        with patch("src.npu_model_installer.MODEL_CATALOG", [DummyEntry("t1", "")]):
            with patch("src.gui.model_manager.NPUCatalogWidget._add_card"):
                widget = NPUCatalogWidget(mock_settings)
                qtbot.addWidget(widget)
                assert widget._manager == mock_settings

def test_npu_catalog_widget_refresh_all(qtbot, mock_settings):
    with patch("src.gui.model_manager.NPUCatalogWidget._build_ui"):
        widget = NPUCatalogWidget(mock_settings)
        qtbot.addWidget(widget)

        card1 = MagicMock()
        card2 = MagicMock()
        widget._cards = {"m1": card1, "m2": card2}

        widget.refresh_all()

        card1.refresh_state.assert_called_once()
        card2.refresh_state.assert_called_once()

def test_npu_catalog_download_requested(qtbot, mock_settings):
    with patch("src.gui.model_manager.NPUCatalogWidget._build_ui"):
        widget = NPUCatalogWidget(mock_settings)

        entry = DummyEntry("Test Model", "")
        card = MagicMock()
        widget._cards["test_model"] = card

        with patch("src.gui.model_manager._DownloadThread") as MockThread:
            mock_thread_inst = MagicMock()
            MockThread.return_value = mock_thread_inst

            widget._on_download_requested(entry)

            MockThread.assert_called_once_with(entry, parent=widget)
            mock_thread_inst.progress.connect.assert_called()
            mock_thread_inst.finished.connect.assert_called()
            mock_thread_inst.error.connect.assert_called()
            mock_thread_inst.start.assert_called_once()

            card.start_download.assert_called_once()
            assert "test_model" in widget._dl_threads

def test_npu_catalog_download_progress(qtbot, mock_settings):
    with patch("src.gui.model_manager.NPUCatalogWidget._build_ui"):
        widget = NPUCatalogWidget(mock_settings)
        card = MagicMock()
        widget._cards["test_model"] = card

        widget._on_dl_progress("test_model", "Downloading 50%")
        card.on_download_progress.assert_called_once_with("Downloading 50%")

def test_npu_catalog_dl_finished_and_error(qtbot, mock_settings):
    with patch("src.gui.model_manager.NPUCatalogWidget._build_ui"):
        widget = NPUCatalogWidget(mock_settings)
        card = MagicMock()
        widget._cards["test_model"] = card
        widget._dl_threads["test_model"] = MagicMock()

        widget._on_dl_finished("test_model", "/some/path")
        card.on_download_finished.assert_called_once_with("/some/path")
        assert "test_model" not in widget._dl_threads

        widget._dl_threads["test_model"] = MagicMock()
        widget._on_dl_error("test_model", "Err")
        card.on_download_error.assert_called_once_with("Err")
        assert "test_model" not in widget._dl_threads

def test_npu_catalog_remove_requested(qtbot, mock_settings):
    with patch("src.gui.model_manager.NPUCatalogWidget._build_ui"):
        widget = NPUCatalogWidget(mock_settings)
        entry = DummyEntry("Test Model", "")
        card = MagicMock()
        widget._cards["test_model"] = card

        with patch("src.gui.model_manager.QMessageBox.question", return_value=True):
            with patch("src.gui.model_manager._RemoveThread") as MockThread:
                mock_thread = MagicMock()
                MockThread.return_value = mock_thread

                widget._on_remove_requested(entry)

                MockThread.assert_called_once_with(entry, parent=widget)
                mock_thread.start.assert_called_once()
                assert "test_model" in widget._rm_threads

def test_npu_catalog_rm_finished_and_error(qtbot, mock_settings):
    with patch("src.gui.model_manager.NPUCatalogWidget._build_ui"):
        widget = NPUCatalogWidget(mock_settings)
        card = MagicMock()
        widget._cards["test_model"] = card
        widget._rm_threads["test_model"] = MagicMock()

        widget._on_rm_finished("test_model")
        card.on_remove_finished.assert_called_once()
        assert "test_model" not in widget._rm_threads

        widget._rm_threads["test_model"] = MagicMock()
        widget._on_rm_error("test_model", "Err")
        card.on_remove_error.assert_called_once_with("Err")
        assert "test_model" not in widget._rm_threads

def test_npu_catalog_use_requested(qtbot, mock_settings):
    with patch("src.gui.model_manager.NPUCatalogWidget._build_ui"):
        widget = NPUCatalogWidget(mock_settings)
        entry = DummyEntry("Test Model", "")

        with qtbot.waitSignal(widget.model_activated, timeout=100) as blocker:
            widget._on_use_requested(entry, "/path/to/model")

        assert blocker.args == ["/path/to/model"]
        mock_settings.set.assert_any_call("backend", "npu")
        mock_settings.set.assert_any_call("npu.model_path", "/path/to/model")

def test_backend_model_panel_init_refresh(qtbot, mock_settings):
    with patch("src.gui.model_manager._BackendModelPanel._build_ui"):
        with patch("src.gui.model_manager._BackendModelPanel.refresh") as mock_refresh:
            with patch("src.model_selector.ModelSelector"):
                panel = _BackendModelPanel(mock_settings)
                qtbot.addWidget(panel)
                assert panel._manager == mock_settings
                mock_refresh.assert_called_once()

def test_backend_model_panel_selector_fail(qtbot, mock_settings):
    with patch("src.gui.model_manager._BackendModelPanel._build_ui"):
        with patch("src.gui.model_manager._BackendModelPanel.refresh"):
            with patch("src.model_selector.ModelSelector", side_effect=Exception("Selector err")):
                with patch("src.gui.model_manager.logger.warning") as mock_warn:
                    panel = _BackendModelPanel(mock_settings)
                    qtbot.addWidget(panel)
                    mock_warn.assert_called_once()
                    assert panel._selector is None

def test_backend_model_panel_refresh_thread(qtbot, mock_settings):
    with patch("src.gui.model_manager._BackendModelPanel._build_ui"), patch("src.gui.model_manager._BackendModelPanel.refresh"):
        panel = _BackendModelPanel(mock_settings)

    panel._btn_refresh = MagicMock()
    panel._set_status = MagicMock()
    panel._selector = MagicMock()

    with patch("src.gui.model_manager._FetchThread") as MockThread:
        mock_inst = MagicMock()
        MockThread.return_value = mock_inst
        _BackendModelPanel.refresh(panel)
        MockThread.assert_called_once_with(panel._selector, parent=panel)
        mock_inst.start.assert_called_once()
