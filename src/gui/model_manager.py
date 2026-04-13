# SPDX-License-Identifier: GPL-3.0-or-later
"""Model manager widget — backend model browser + NPU catalog with Download/Remove.

Embedded in the **Models** tab of :class:`~src.gui.settings_window.SettingsWindow`.
Can also be used as a standalone dialog.

Features
--------
Backend models (Ollama / OpenAI-compat)
    - Live list of models fetched from the active backend
    - Per-model NPU compatibility badge (✅ OK / ⚠ Warn / ⛔ No)
    - **Browse ONNX…** — opens a file dialog filtered to ``*.onnx``
    - **Drag-and-drop** — drop ``.onnx`` or ``.gguf`` files from any file manager
    - **Set as current model** — updates ``settings.json`` immediately
    - **Delete** — removes Ollama model or deregisters ONNX path

NPU Model Catalog
    - Card-per-entry showing name, publisher, size, NPU fit, vision flag
    - **⬇ Download** — downloads the model with a live progress bar;
      greyed out when already installed
    - **🗑 Remove** — deletes the installed model files with confirmation;
      greyed out when not installed
    - **✔ Use** — sets the model as active in settings; greyed out when not installed
    - **TOS dialog** — required before downloading any model marked
      ``requires_tos=True``; user must tick an acceptance checkbox
"""

from __future__ import annotations

import logging
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtCore import QSize, Qt, QThread, pyqtSignal
    from PyQt5.QtGui import QColor, QFont
    from PyQt5.QtWidgets import (
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    logger.warning("PyQt5 not installed — ModelManagerWidget unavailable.")

if _HAS_QT:

    # ── Colours ───────────────────────────────────────────────────────────────

    _BADGE_OK   = "#27ae60"
    _BADGE_WARN = "#e67e22"
    _BADGE_FAIL = "#c0392b"
    _BADGE_SKIP = "#7f8c8d"
    _COLOR_VISION = "#1a6fa8"

    # ── Background threads ────────────────────────────────────────────────────

    class _FetchThread(QThread):
        """Fetches the backend model list in the background."""
        finished = pyqtSignal(list)
        error    = pyqtSignal(str)

        def __init__(self, selector: Any, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._selector = selector

        def run(self) -> None:
            try:
                self.finished.emit(self._selector.list_models(timeout=5).result())
            except Exception as exc:  # noqa: BLE001
                self.error.emit(str(exc))

    class _DownloadThread(QThread):
        """Downloads a catalog model in the background."""
        progress  = pyqtSignal(str)   # progress message
        finished  = pyqtSignal(str)   # path to installed ONNX
        error     = pyqtSignal(str)   # error message

        def __init__(
            self,
            entry: Any,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._entry = entry

        def run(self) -> None:
            from src.npu_model_installer import install_model_from_catalog, InstallError
            try:
                path = install_model_from_catalog(
                    self._entry,
                    progress_callback=self.progress.emit,
                    allow_external=True,
                )
                self.finished.emit(str(path))
            except InstallError as exc:
                self.error.emit(str(exc))
            except Exception as exc:  # noqa: BLE001
                self.error.emit(f"Unexpected error: {exc}")

    class _RemoveThread(QThread):
        """Removes a catalog model in the background."""
        finished = pyqtSignal()
        error    = pyqtSignal(str)

        def __init__(self, entry: Any, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._entry = entry

        def run(self) -> None:
            from src.npu_model_installer import NPUModelInstaller
            try:
                NPUModelInstaller(entry=self._entry).uninstall()
                self.finished.emit()
            except Exception as exc:  # noqa: BLE001
                self.error.emit(str(exc))

    # ── TOS dialog ────────────────────────────────────────────────────────────

    class _TosDialog(QDialog):
        """Terms-of-Service acceptance dialog shown before restricted downloads.

        The user must tick the acceptance checkbox before the OK button is
        enabled.  Clicking 'Read full terms' opens the TOS URL in the browser.

        Parameters
        ----------
        entry:
            The catalog entry whose TOS should be displayed.
        parent:
            Optional parent widget.
        """

        def __init__(self, entry: Any, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setWindowTitle(f"Terms of Use — {entry.name}")
            self.setMinimumWidth(520)
            self.setMinimumHeight(340)
            self._entry = entry
            self._build_ui()

        def _build_ui(self) -> None:
            layout = QVBoxLayout(self)
            layout.setSpacing(10)

            # Header
            header = QLabel(
                f"<b>{self._entry.name}</b> is published by "
                f"<b>{self._entry.publisher}</b> under the "
                f"<b>{self._entry.license_spdx}</b> license, "
                "which requires your explicit acceptance before downloading."
            )
            header.setWordWrap(True)
            layout.addWidget(header)

            # TOS summary
            summary_box = QTextEdit()
            summary_box.setReadOnly(True)
            summary_box.setPlainText(
                self._entry.tos_summary or
                "Please read the full terms before downloading."
            )
            summary_box.setMaximumHeight(130)
            layout.addWidget(summary_box)

            # Read full terms button
            if self._entry.tos_url:
                btn_read = QPushButton("🌐 Read full terms online…")
                btn_read.clicked.connect(
                    lambda: webbrowser.open(self._entry.tos_url)
                )
                layout.addWidget(btn_read)

            # Acceptance checkbox
            self._chk = QCheckBox(
                "I have read and accept the Terms of Use for this model"
            )
            self._chk.stateChanged.connect(self._on_check_changed)
            layout.addWidget(self._chk)

            # Dialog buttons
            self._buttons = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel
            )
            ok_btn = self._buttons.button(QDialogButtonBox.Ok)
            ok_btn.setText("⬇ Download")
            ok_btn.setEnabled(False)
            self._buttons.accepted.connect(self.accept)
            self._buttons.rejected.connect(self.reject)
            layout.addWidget(self._buttons)

        def _on_check_changed(self, state: int) -> None:
            ok_btn = self._buttons.button(QDialogButtonBox.Ok)
            ok_btn.setEnabled(state == Qt.Checked)

    # ── Catalog card ──────────────────────────────────────────────────────────

    class _CatalogCard(QFrame):
        """A single model entry card in the NPU catalog panel.

        Signals
        -------
        download_requested(entry)
        remove_requested(entry)
        use_requested(entry, path)
        """

        download_requested = pyqtSignal(object)
        remove_requested   = pyqtSignal(object)
        use_requested      = pyqtSignal(object, str)

        def __init__(self, entry: Any, settings_manager: Any,
                     parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._entry   = entry
            self._manager = settings_manager
            self._installer = None
            self._build_ui()
            self.refresh_state()

        def _build_ui(self) -> None:
            from src.npu_model_installer import NPUModelInstaller
            self._installer = NPUModelInstaller(entry=self._entry)

            self.setFrameShape(QFrame.StyledPanel)
            self.setFrameShadow(QFrame.Raised)
            self.setLineWidth(1)

            outer = QVBoxLayout(self)
            outer.setContentsMargins(8, 6, 8, 6)
            outer.setSpacing(4)

            # ── Row 1: name + badges ──────────────────────────────────────
            row1 = QHBoxLayout()

            name_lbl = QLabel(f"<b>{self._entry.name}</b>")
            name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            row1.addWidget(name_lbl)

            # Vision badge
            if self._entry.is_vision:
                vis_lbl = QLabel("👁 Vision")
                vis_lbl.setStyleSheet(
                    f"color: white; background: {_COLOR_VISION}; "
                    "padding: 1px 5px; border-radius: 3px; font-size: 10px;"
                )
                row1.addWidget(vis_lbl)

            # NPU fit badge
            fit_colors = {
                "excellent":       ("#155724", "#d4edda"),
                "good":            ("#155724", "#d4edda"),
                "fair":            ("#856404", "#fff3cd"),
                "not_recommended": ("#721c24", "#f8d7da"),
            }
            fg, bg = fit_colors.get(self._entry.npu_fit, ("#333", "#eee"))
            npu_lbl = QLabel(self._entry.npu_fit_label)
            npu_lbl.setStyleSheet(
                f"color: {fg}; background: {bg}; "
                "padding: 1px 5px; border-radius: 3px; font-size: 10px;"
            )
            row1.addWidget(npu_lbl)

            # TOS badge
            if self._entry.requires_tos:
                tos_lbl = QLabel("📜 TOS required")
                tos_lbl.setStyleSheet(
                    "color: #856404; background: #fff3cd; "
                    "padding: 1px 5px; border-radius: 3px; font-size: 10px;"
                )
                row1.addWidget(tos_lbl)

            outer.addLayout(row1)

            # ── Row 2: publisher + size ───────────────────────────────────
            meta = QLabel(
                f"<span style='color:grey'>{self._entry.publisher} · "
                f"{self._entry.size_description} · "
                f"{self._entry.license_spdx}</span>"
            )
            meta.setTextFormat(Qt.RichText)
            outer.addWidget(meta)

            # ── Row 3: description ────────────────────────────────────────
            desc = QLabel(self._entry.description)
            desc.setWordWrap(True)
            desc.setStyleSheet("font-size: 11px;")
            outer.addWidget(desc)

            # ── Row 4: notes (if any) ─────────────────────────────────────
            if self._entry.notes:
                notes = QLabel(f"ℹ {self._entry.notes}")
                notes.setWordWrap(True)
                notes.setStyleSheet("font-size: 10px; color: grey;")
                outer.addWidget(notes)

            # ── Row 5: action buttons + progress ─────────────────────────
            btn_row = QHBoxLayout()

            self._btn_download = QPushButton("⬇ Download")
            self._btn_download.setToolTip("Download this model to your computer")
            self._btn_download.clicked.connect(self._on_download)
            btn_row.addWidget(self._btn_download)

            self._btn_remove = QPushButton("🗑 Remove")
            self._btn_remove.setToolTip("Delete the installed model files from disk")
            self._btn_remove.clicked.connect(self._on_remove)
            btn_row.addWidget(self._btn_remove)

            self._btn_use = QPushButton("✔ Use")
            self._btn_use.setToolTip("Set this model as the active NPU model")
            self._btn_use.clicked.connect(self._on_use)
            btn_row.addWidget(self._btn_use)

            btn_row.addStretch()
            outer.addLayout(btn_row)

            # Progress bar (hidden when idle)
            self._progress_bar = QProgressBar()
            self._progress_bar.setTextVisible(False)
            self._progress_bar.setMaximum(0)   # indeterminate
            self._progress_bar.setFixedHeight(6)
            self._progress_bar.hide()
            outer.addWidget(self._progress_bar)

            # Status line
            self._status = QLabel("")
            self._status.setStyleSheet("font-size: 10px;")
            outer.addWidget(self._status)

        def refresh_state(self) -> None:
            """Update button states to match current install status."""
            if self._installer is None:
                return
            installed = self._installer.is_installed()
            self._btn_download.setEnabled(not installed)
            self._btn_remove.setEnabled(installed)
            self._btn_use.setEnabled(installed)
            if installed:
                self._status.setText(
                    f"<span style='color:{_BADGE_OK}'>✅ Installed at "
                    f"{self._installer.model_path()}</span>"
                )
                self._status.setTextFormat(Qt.RichText)
            else:
                self._status.setText("")

        # ── Button handlers ───────────────────────────────────────────────

        def _on_download(self) -> None:
            """Handle Download button click — show TOS dialog if required."""
            if self._entry.requires_tos:
                dlg = _TosDialog(self._entry, parent=self)
                if dlg.exec_() != QDialog.Accepted:
                    return
            self.download_requested.emit(self._entry)

        def _on_remove(self) -> None:
            reply = QMessageBox.question(
                self,
                "Remove model",
                f"Delete <b>{self._entry.name}</b> from disk?<br><br>"
                f"<small>This will remove all files in:<br>"
                f"{self._installer.install_dir}</small>",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.remove_requested.emit(self._entry)

        def _on_use(self) -> None:
            if self._installer is not None:
                path = str(self._installer.model_path())
                self.use_requested.emit(self._entry, path)

        # ── Download lifecycle ─────────────────────────────────────────────

        def start_download(self) -> None:
            """Called by the catalog panel when download starts."""
            self._btn_download.setEnabled(False)
            self._btn_remove.setEnabled(False)
            self._btn_use.setEnabled(False)
            self._progress_bar.show()
            self._status.setText("Downloading…")

        def on_download_progress(self, msg: str) -> None:
            self._status.setText(msg)

        def on_download_finished(self, path: str) -> None:
            self._progress_bar.hide()
            self._status.setText(
                f"<span style='color:{_BADGE_OK}'>✅ Downloaded → {path}</span>"
            )
            self._status.setTextFormat(Qt.RichText)
            self.refresh_state()

        def on_download_error(self, msg: str) -> None:
            self._progress_bar.hide()
            self._status.setText(
                f"<span style='color:{_BADGE_FAIL}'>⛔ {msg}</span>"
            )
            self._status.setTextFormat(Qt.RichText)
            self.refresh_state()

        def on_remove_finished(self) -> None:
            self._status.setText("")
            self.refresh_state()

        def on_remove_error(self, msg: str) -> None:
            self._status.setText(
                f"<span style='color:{_BADGE_FAIL}'>⛔ Remove failed: {msg}</span>"
            )
            self._status.setTextFormat(Qt.RichText)
            self.refresh_state()

    # ── NPU Catalog panel ─────────────────────────────────────────────────────

    class NPUCatalogWidget(QWidget):
        """Scrollable panel showing all catalog models with Download/Remove/Use buttons.

        Parameters
        ----------
        settings_manager:
            The application :class:`~src.settings.SettingsManager`.
        parent:
            Optional parent widget.
        """

        model_activated = pyqtSignal(str)  # ONNX path chosen as active

        def __init__(self, settings_manager: Any, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._manager = settings_manager
            self._cards: dict[str, _CatalogCard] = {}   # key → card
            self._dl_threads: dict[str, _DownloadThread] = {}
            self._rm_threads: dict[str, _RemoveThread]   = {}
            self._build_ui()

        def _build_ui(self) -> None:
            from src.npu_model_installer import MODEL_CATALOG, get_vision_models

            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)

            # Header strip
            hdr = QLabel(
                "<b>NPU Model Catalog</b> — download vision and text models "
                "optimised for AMD Ryzen AI NPUs.  No model is preinstalled."
            )
            hdr.setWordWrap(True)
            hdr.setStyleSheet("padding: 4px;")
            outer.addWidget(hdr)

            # Scrollable card area
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)

            container = QWidget()
            vbox = QVBoxLayout(container)
            vbox.setSpacing(8)
            vbox.setContentsMargins(4, 4, 4, 4)

            # Vision section
            vision_models = get_vision_models()
            if vision_models:
                sec = QLabel("<b>👁 Vision models (can see screenshots)</b>")
                sec.setStyleSheet("font-size: 12px; margin-top: 4px;")
                vbox.addWidget(sec)
                for entry in vision_models:
                    self._add_card(entry, vbox)

            # Text-only section
            text_models = [e for e in MODEL_CATALOG if not e.is_vision]
            if text_models:
                sec = QLabel("<b>💬 Text-only models</b>")
                sec.setStyleSheet("font-size: 12px; margin-top: 8px;")
                vbox.addWidget(sec)
                for entry in text_models:
                    self._add_card(entry, vbox)

            vbox.addStretch()
            scroll.setWidget(container)
            outer.addWidget(scroll)

        def _add_card(self, entry: Any, layout: QVBoxLayout) -> None:
            card = _CatalogCard(entry, self._manager, parent=self)
            card.download_requested.connect(self._on_download_requested)
            card.remove_requested.connect(self._on_remove_requested)
            card.use_requested.connect(self._on_use_requested)
            self._cards[entry.key] = card
            layout.addWidget(card)

        def refresh_all(self) -> None:
            """Refresh install-state of every card (e.g. after external change)."""
            for card in self._cards.values():
                card.refresh_state()

        # ── Download ──────────────────────────────────────────────────────────

        def _on_download_requested(self, entry: Any) -> None:
            if entry.key in self._dl_threads:
                return  # Already downloading
            card = self._cards.get(entry.key)
            if card:
                card.start_download()
            thread = _DownloadThread(entry, parent=self)
            thread.progress.connect(
                lambda msg, k=entry.key: self._on_dl_progress(k, msg)
            )
            thread.finished.connect(
                lambda path, k=entry.key: self._on_dl_finished(k, path)
            )
            thread.error.connect(
                lambda msg, k=entry.key: self._on_dl_error(k, msg)
            )
            self._dl_threads[entry.key] = thread
            thread.start()

        def _on_dl_progress(self, key: str, msg: str) -> None:
            card = self._cards.get(key)
            if card:
                card.on_download_progress(msg)

        def _on_dl_finished(self, key: str, path: str) -> None:
            card = self._cards.get(key)
            if card:
                card.on_download_finished(path)
            self._dl_threads.pop(key, None)

        def _on_dl_error(self, key: str, msg: str) -> None:
            card = self._cards.get(key)
            if card:
                card.on_download_error(msg)
            self._dl_threads.pop(key, None)

        # ── Remove ────────────────────────────────────────────────────────────

        def _on_remove_requested(self, entry: Any) -> None:
            if entry.key in self._rm_threads:
                return
            thread = _RemoveThread(entry, parent=self)
            thread.finished.connect(
                lambda k=entry.key: self._on_rm_finished(k)
            )
            thread.error.connect(
                lambda msg, k=entry.key: self._on_rm_error(k, msg)
            )
            self._rm_threads[entry.key] = thread
            thread.start()

        def _on_rm_finished(self, key: str) -> None:
            card = self._cards.get(key)
            if card:
                card.on_remove_finished()
            self._rm_threads.pop(key, None)

        def _on_rm_error(self, key: str, msg: str) -> None:
            card = self._cards.get(key)
            if card:
                card.on_remove_error(msg)
            self._rm_threads.pop(key, None)

        # ── Use ───────────────────────────────────────────────────────────────

        def _on_use_requested(self, entry: Any, path: str) -> None:
            self._manager.set("backend", "npu")
            self._manager.set("npu.model_path", path)
            self.model_activated.emit(path)
            logger.info(
                "NPU model set to %r (key=%r)", path, entry.key
            )

    # ── Backend model list ────────────────────────────────────────────────────

    class _BackendModelPanel(QWidget):
        """Panel showing models from the active Ollama/OpenAI backend."""

        def __init__(self, settings_manager: Any,
                     parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._manager  = settings_manager
            self._selector = None
            self._models: list[Any] = []
            self._build_ui()
            self._build_selector()
            self.refresh()

        def _build_selector(self) -> None:
            try:
                from src.model_selector import ModelSelector
                cfg = self._manager.to_config()
                self._selector = ModelSelector(cfg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not build ModelSelector: %s", exc)

        def _build_ui(self) -> None:
            layout = QVBoxLayout(self)

            self._list = QListWidget()
            self._list.setAlternatingRowColors(True)
            self._list.setSelectionMode(QListWidget.SingleSelection)
            self._list.currentItemChanged.connect(self._on_selection_changed)
            self._list.setAcceptDrops(True)
            self._list.dragEnterEvent = self._drag_enter
            self._list.dragMoveEvent  = self._drag_move
            self._list.dropEvent      = self._drop_event
            layout.addWidget(self._list)

            hint = QLabel("💡 Drop .onnx or .gguf files here to add a model")
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet("color: grey; font-size: 11px;")
            layout.addWidget(hint)

            btn_row = QHBoxLayout()

            self._btn_refresh = QPushButton("🔄 Refresh")
            self._btn_refresh.setToolTip("Fetch the model list from the backend")
            self._btn_refresh.clicked.connect(self.refresh)
            btn_row.addWidget(self._btn_refresh)

            self._btn_browse = QPushButton("📂 Browse ONNX…")
            self._btn_browse.setToolTip("Open a file dialog to add an ONNX model file")
            self._btn_browse.clicked.connect(self._browse_onnx)
            btn_row.addWidget(self._btn_browse)

            self._btn_use = QPushButton("✔ Use this model")
            self._btn_use.setEnabled(False)
            self._btn_use.clicked.connect(self._use_model)
            btn_row.addWidget(self._btn_use)

            self._btn_delete = QPushButton("🗑 Delete")
            self._btn_delete.setEnabled(False)
            self._btn_delete.clicked.connect(self._delete_model)
            btn_row.addWidget(self._btn_delete)

            layout.addLayout(btn_row)

            self._status = QLabel("")
            layout.addWidget(self._status)

        def refresh(self) -> None:
            if self._selector is None:
                self._build_selector()
            if self._selector is None:
                self._set_status("⚠ Backend not configured.", error=True)
                return
            self._btn_refresh.setEnabled(False)
            self._set_status("Fetching models…")
            self._thread = _FetchThread(self._selector, parent=self)
            self._thread.finished.connect(self._on_models_fetched)
            self._thread.error.connect(self._on_fetch_error)
            self._thread.start()

        def _on_models_fetched(self, models: list) -> None:
            self._models = models
            self._list.clear()
            for m in models:
                self._add_list_item(m)
            self._btn_refresh.setEnabled(True)
            self._set_status(f"{len(models)} model(s) available.")

        def _on_fetch_error(self, msg: str) -> None:
            self._btn_refresh.setEnabled(True)
            self._set_status(f"⚠ Could not fetch models: {msg}", error=True)

        def _add_list_item(self, model: Any) -> None:
            if self._selector is not None:
                warning = self._selector.npu_warning(model)
            else:
                warning = None
            if warning is None:
                badge, colour = "✅", _BADGE_OK
            elif "⛔" in warning:
                badge, colour = "⛔", _BADGE_FAIL
            else:
                badge, colour = "⚠", _BADGE_WARN
            size_str = f"  {model.size_gb:.1f} GB" if model.size_gb else ""
            label    = f"{badge} {model.name}{size_str}"
            item     = QListWidgetItem(label)
            item.setData(Qt.UserRole, model)
            item.setToolTip(warning or "NPU compatible")
            item.setForeground(QColor(colour))
            self._list.addItem(item)

        def _on_selection_changed(self, current: Any, _: Any) -> None:
            has_sel = current is not None
            self._btn_use.setEnabled(has_sel)
            self._btn_delete.setEnabled(has_sel)

        def _selected_model(self) -> Any | None:
            item = self._list.currentItem()
            return item.data(Qt.UserRole) if item else None

        def _use_model(self) -> None:
            m = self._selected_model()
            if m is None:
                return
            if self._selector is not None:
                self._selector.set_model(m.name)
            backend = self._manager.get("backend", "ollama")
            if backend == "ollama":
                self._manager.set("ollama.model", m.name)
            elif backend == "openai":
                self._manager.set("openai.model", m.name)
            elif backend == "npu":
                self._manager.set("npu.model_path", m.name)
            self._set_status(f"✔ Now using: {m.name}")

        def _browse_onnx(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Select ONNX model file", str(Path.home()),
                "ONNX models (*.onnx);;All files (*)",
            )
            if path:
                self._register_file(path)

        def _register_file(self, path: str) -> None:
            from src.model_selector import ModelInfo
            m = ModelInfo(name=path)
            self._models.append(m)
            self._add_list_item(m)
            self._list.setCurrentRow(self._list.count() - 1)
            self._set_status(f"Added: {path}")

        def _drag_enter(self, event: Any) -> None:
            if event.mimeData().hasUrls():
                paths = [u.toLocalFile() for u in event.mimeData().urls()]
                if any(p.endswith((".onnx", ".gguf")) for p in paths):
                    event.acceptProposedAction()
                    return
            event.ignore()

        def _drag_move(self, event: Any) -> None:
            event.acceptProposedAction() if event.mimeData().hasUrls() else event.ignore()

        def _drop_event(self, event: Any) -> None:
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.endswith((".onnx", ".gguf")):
                    self._register_file(path)
            event.acceptProposedAction()

        def _delete_model(self) -> None:
            m = self._selected_model()
            if m is None:
                return
            name    = m.name
            is_file = name.endswith((".onnx", ".gguf")) and Path(name).exists()
            if is_file:
                reply = QMessageBox.question(
                    self, "Delete model file",
                    f"Remove <b>{name}</b> from the list?<br>Also delete from disk?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.No,
                )
                if reply == QMessageBox.Cancel:
                    return
                if reply == QMessageBox.Yes:
                    try:
                        Path(name).unlink()
                        self._set_status(f"🗑 Deleted file: {name}")
                    except OSError as exc:
                        QMessageBox.critical(self, "Error", f"Could not delete file:\n{exc}")
                        return
                self._remove_selected_item()
            else:
                reply = QMessageBox.question(
                    self, "Remove model",
                    f"Remove Ollama model <b>{name}</b>?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return
                try:
                    result = subprocess.run(
                        ["ollama", "rm", name],
                        capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode == 0:
                        self._set_status(f"🗑 Removed model: {name}")
                        self._remove_selected_item()
                    else:
                        QMessageBox.critical(
                            self, "Error", f"ollama rm failed:\n{result.stderr.strip()}"
                        )
                except FileNotFoundError:
                    QMessageBox.critical(
                        self, "Error",
                        "ollama command not found. Is Ollama installed and on PATH?"
                    )
                except subprocess.TimeoutExpired:
                    QMessageBox.critical(self, "Error", "ollama rm timed out.")

        def _remove_selected_item(self) -> None:
            row = self._list.currentRow()
            if row >= 0:
                self._list.takeItem(row)
                if row < len(self._models):
                    self._models.pop(row)

        def _set_status(self, msg: str, error: bool = False) -> None:
            colour = "#c0392b" if error else "#27ae60"
            self._status.setStyleSheet(f"color: {colour};")
            self._status.setText(msg)

    # ── Public composite widget ───────────────────────────────────────────────

    class ModelManagerWidget(QWidget):
        """Tabbed model manager combining the backend browser and NPU catalog.

        Parameters
        ----------
        manager:
            The application :class:`~src.settings.SettingsManager`.
        parent:
            Optional parent widget.
        """

        def __init__(self, manager: Any, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._manager = manager
            self._build_ui()

        def _build_ui(self) -> None:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)

            tabs = QTabWidget()

            # Tab 1 — NPU catalog
            self._catalog = NPUCatalogWidget(self._manager)
            tabs.addTab(self._catalog, "🤖 NPU Catalog")

            # Tab 2 — Backend models
            self._backend = _BackendModelPanel(self._manager)
            tabs.addTab(self._backend, "🦙 Backend Models")

            layout.addWidget(tabs)

        def refresh(self) -> None:
            """Refresh both panels."""
            self._catalog.refresh_all()
            self._backend.refresh()
