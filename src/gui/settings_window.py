# SPDX-License-Identifier: GPL-3.0-or-later
"""PyQt5 settings dialog — tabbed GUI that stays in sync with settings.json.

Every widget change is written immediately to :class:`~src.settings.SettingsManager`
which atomically persists to ``~/.config/linux-ai-npu-assistant/settings.json``.
The dialog reads its initial state from the same manager, so the GUI and JSON
file are always consistent.

Desktop-environment theming is applied automatically via :mod:`src.gui.theme`
before the dialog is shown.
## Usage
::

    from src.settings import SettingsManager
    from src.gui.settings_window import SettingsWindow
    from PyQt5.QtWidgets import QApplication

    app = QApplication([])
    sm  = SettingsManager()
    win = SettingsWindow(sm)
    win.exec_()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QSpinBox,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )

    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    logger.warning(
        "PyQt5 not installed — SettingsWindow is unavailable. "
        "Install with: pip install PyQt5"
    )


def _require_qt() -> None:
    if not _HAS_QT:
        raise ImportError(
            "PyQt5 is required for the GUI settings window. "
            "Install it with:  pip install PyQt5"
        )


if _HAS_QT:

    class _Field:
        """Helper that connects a single widget to a settings key path."""

        def __init__(
            self,
            widget: QWidget,
            key: str,
            manager: Any,
            transform_get=None,
            transform_set=None,
        ) -> None:
            self.widget = widget
            self.key = key
            self.manager = manager
            self._transform_get = transform_get or (lambda v: v)
            self._transform_set = transform_set or (lambda v: v)

        def load(self) -> None:
            val = self._transform_get(self.manager.get(self.key))
            w = self.widget
            if isinstance(w, QLineEdit):
                w.setText(str(val or ""))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(val))
            elif isinstance(w, QComboBox):
                idx = w.findText(str(val))
                if idx >= 0:
                    w.setCurrentIndex(idx)
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.setValue(val if val is not None else 0)

        def connect(self) -> None:
            w = self.widget
            key = self.key
            mgr = self.manager
            tr = self._transform_set
            if isinstance(w, QLineEdit):
                w.textChanged.connect(lambda v: mgr.set(key, tr(v), save=True))
            elif isinstance(w, QCheckBox):
                w.stateChanged.connect(
                    lambda state: mgr.set(key, state == Qt.Checked, save=True)
                )
            elif isinstance(w, QComboBox):
                w.currentTextChanged.connect(lambda v: mgr.set(key, tr(v), save=True))
            elif isinstance(w, QSpinBox):
                w.valueChanged.connect(lambda v: mgr.set(key, tr(v), save=True))
            elif isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(lambda v: mgr.set(key, tr(v), save=True))

    # ── Tab builders ──────────────────────────────────────────────────────────

    def _history_tab(history: "Any | None") -> QWidget:
        """Build the Chat History tab (encryption, password, export, import)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignTop)

        # ── Encryption group ───────────────────────────────────────────────
        enc_grp = QGroupBox("History Encryption")
        enc_layout = QVBoxLayout(enc_grp)

        enc_status = QLabel()
        if history is None:
            enc_status.setText("History object not available.")
        elif getattr(history, "is_encrypted", False):
            enc_status.setText("🔒 History is encrypted (Fernet AES-128).")
        else:
            enc_status.setText("🔓 History is stored as plain JSON.")
        enc_layout.addWidget(enc_status)

        # Password section
        pw_grp = QGroupBox("Set / Change Password")
        pw_form = QVBoxLayout(pw_grp)

        pw_row1 = QHBoxLayout()
        pw_label = QLabel("Password:")
        pw_label.setFixedWidth(90)
        pw_input = QLineEdit()
        pw_input.setAccessibleName("New password")
        pw_input.setEchoMode(QLineEdit.Password)
        pw_input.setPlaceholderText("Leave blank to use auto-generated key")
        pw_row1.addWidget(pw_label)
        pw_row1.addWidget(pw_input)
        pw_form.addLayout(pw_row1)

        pw_row2 = QHBoxLayout()
        pw_confirm_label = QLabel("Confirm:")
        pw_confirm_label.setFixedWidth(90)
        pw_confirm = QLineEdit()
        pw_confirm.setAccessibleName("Confirm new password")
        pw_confirm.setEchoMode(QLineEdit.Password)
        pw_row2.addWidget(pw_confirm_label)
        pw_row2.addWidget(pw_confirm)
        pw_form.addLayout(pw_row2)

        pw_status = QLabel("")
        pw_form.addWidget(pw_status)

        set_pw_btn = QPushButton("Set Password")
        set_pw_btn.setToolTip(
            "Enable encryption and protect history with this password"
        )
        set_pw_btn.setAccessibleName(
            "Enable encryption and protect history with this password"
        )

        def _on_set_password() -> None:
            if history is None:
                pw_status.setText("⚠ History unavailable.")
                return
            p1 = pw_input.text()
            p2 = pw_confirm.text()
            if p1 != p2:
                pw_status.setText("⚠ Passwords do not match.")
                return
            try:
                history.set_password(p1)
                pw_input.clear()
                pw_confirm.clear()
                enc_status.setText("🔒 History is encrypted (Fernet AES-128).")
                pw_status.setText("✅ Password set and history re-encrypted.")
            except Exception as exc:  # noqa: BLE001
                pw_status.setText(f"⚠ {exc}")

        set_pw_btn.clicked.connect(_on_set_password)
        pw_form.addWidget(set_pw_btn)
        enc_layout.addWidget(pw_grp)
        layout.addWidget(enc_grp)

        # ── Export / Import group ──────────────────────────────────────────
        io_grp = QGroupBox("Export & Import")
        io_layout = QVBoxLayout(io_grp)
        io_status = QLabel("")
        io_layout.addWidget(io_status)

        def _on_export() -> None:
            if history is None:
                io_status.setText("⚠ History unavailable.")
                return
            from PyQt5.QtWidgets import QFileDialog  # noqa: PLC0415

            path, _ = QFileDialog.getSaveFileName(
                widget,
                "Export History",
                str(Path.home() / "history_export.json"),
                "JSON files (*.json);;All files (*)",
            )
            if not path:
                return
            try:
                from pathlib import Path as P  # noqa: PLC0415

                history.export_plaintext(P(path))
                io_status.setText(f"✅ Exported to {path}")
            except Exception as exc:  # noqa: BLE001
                io_status.setText(f"⚠ Export failed: {exc}")

        export_btn = QPushButton("📤 Export unencrypted JSON…")
        export_btn.setToolTip(
            "Save the full conversation history as plain JSON (no encryption)"
        )
        export_btn.setAccessibleName(
            "Save the full conversation history as plain JSON (no encryption)"
        )
        export_btn.clicked.connect(_on_export)
        io_layout.addWidget(export_btn)

        def _on_import() -> None:
            if history is None:
                io_status.setText("⚠ History unavailable.")
                return
            from PyQt5.QtWidgets import QFileDialog, QInputDialog  # noqa: PLC0415

            path, _ = QFileDialog.getOpenFileName(
                widget,
                "Import History",
                str(Path.home()),
                "JSON / Encrypted (*.json *.enc);;All files (*)",
            )
            if not path:
                return
            # Detect if encrypted
            raw = ""
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    raw = fh.read(128)
            except OSError:
                pass
            looks_enc = raw.strip() and not (
                raw.strip().startswith("[") or raw.strip().startswith("{")
            )
            password: str | None = None
            if looks_enc:
                pw, ok = QInputDialog.getText(
                    widget,
                    "Password Required",
                    "Enter the password for the encrypted history file:",
                    QLineEdit.Password,
                )
                if not ok:
                    return
                password = pw

            # Ask merge or replace
            from PyQt5.QtWidgets import QMessageBox  # noqa: PLC0415

            choice = QMessageBox.question(
                widget,
                "Import History",
                "Merge with existing history?\n\n"
                "Yes = merge (keep current + import)\n"
                "No  = replace (overwrite with import)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            merge = choice == QMessageBox.Yes

            try:
                from pathlib import Path as P  # noqa: PLC0415

                count = history.import_history(P(path), password=password, merge=merge)
                io_status.setText(f"✅ Imported {count} messages.")
            except Exception as exc:  # noqa: BLE001
                io_status.setText(f"⚠ Import failed: {exc}")

        import_btn = QPushButton("📥 Import history…")
        import_btn.setToolTip(
            "Import a previously exported JSON or encrypted history file"
        )
        import_btn.setAccessibleName(
            "Import a previously exported JSON or encrypted history file"
        )
        import_btn.clicked.connect(_on_import)
        io_layout.addWidget(import_btn)

        layout.addWidget(io_grp)
        layout.addStretch()
        return widget

    def _updates_tab() -> QWidget:
        """Build the Updates tab (Flatpak-only: managed by system package manager)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignTop)

        grp = QGroupBox("Application Updates")
        grp_layout = QVBoxLayout(grp)

        # Current version
        try:
            from src.gui.full_window import APP_VERSION  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            APP_VERSION = "unknown"  # type: ignore[assignment]

        ver_lbl = QLabel(f"Current version: <b>{APP_VERSION}</b>")
        grp_layout.addWidget(ver_lbl)

        info_lbl = QLabel(
            "This application is distributed exclusively as a <b>Flatpak</b>.<br>"
            "Updates are managed automatically by your system package manager:<br>"
            "<ul>"
            "<li><b>GNOME Software</b> — opens automatically with available updates</li>"
            "<li><b>KDE Discover</b> — checks for updates in the background</li>"
            "<li><b>Command line</b> — run <tt>flatpak update</tt> in a terminal</li>"
            "</ul>"
            "No manual update step is needed inside this application."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setOpenExternalLinks(False)
        grp_layout.addWidget(info_lbl)

        # Link to release notes
        notes_btn = QPushButton("🌐 View release notes on GitHub")
        notes_btn.setToolTip("Opens the GitHub Releases page in your default browser")
        notes_btn.setAccessibleName(
            "Opens the GitHub Releases page in your default browser"
        )

        def _open_releases() -> None:
            import subprocess  # noqa: PLC0415

            url = "https://github.com/robertbiv/Linux-AI-NPU-Assistant/releases"
            try:
                subprocess.Popen(["xdg-open", url])  # noqa: S603, S607
            except Exception:  # noqa: BLE001
                try:
                    import webbrowser  # noqa: PLC0415

                    webbrowser.open(url)
                except Exception:  # noqa: BLE001
                    pass

        notes_btn.clicked.connect(_open_releases)
        grp_layout.addWidget(notes_btn)

        layout.addWidget(grp)
        layout.addStretch()
        return widget

    def _backend_tab(manager: Any) -> tuple[QWidget, list[_Field]]:
        fields: list[_Field] = []
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignTop)

        # Backend selector
        grp = QGroupBox("AI Backend")
        form = QFormLayout(grp)
        backend_combo = QComboBox()
        backend_combo.setAccessibleName("AI Backend")
        backend_combo.addItems(["ollama", "openai", "npu"])
        fields.append(_Field(backend_combo, "backend", manager))
        form.addRow("Backend:", backend_combo)
        layout.addWidget(grp)

        # Ollama
        ollama_grp = QGroupBox("Ollama settings")
        ollama_form = QFormLayout(ollama_grp)
        ollama_url = QLineEdit()
        ollama_url.setAccessibleName("Ollama Server URL")
        ollama_url.setPlaceholderText("http://localhost:11434")
        fields.append(_Field(ollama_url, "ollama.base_url", manager))
        ollama_form.addRow("Server URL:", ollama_url)

        ollama_model = QLineEdit()
        ollama_model.setAccessibleName("Ollama Model")
        ollama_model.setPlaceholderText("llava")
        fields.append(_Field(ollama_model, "ollama.model", manager))
        ollama_form.addRow("Model:", ollama_model)

        ollama_timeout = QSpinBox()
        ollama_timeout.setAccessibleName("Ollama Timeout (seconds)")
        ollama_timeout.setRange(5, 600)
        ollama_timeout.setSuffix(" s")
        fields.append(_Field(ollama_timeout, "ollama.timeout", manager))
        ollama_form.addRow("Timeout:", ollama_timeout)
        layout.addWidget(ollama_grp)

        # OpenAI-compatible
        oai_grp = QGroupBox("OpenAI-compatible server settings")
        oai_form = QFormLayout(oai_grp)
        oai_url = QLineEdit()
        oai_url.setAccessibleName("OpenAI Base URL")
        oai_url.setPlaceholderText("http://localhost:1234/v1")
        fields.append(_Field(oai_url, "openai.base_url", manager))
        oai_form.addRow("Server URL:", oai_url)

        oai_model = QLineEdit()
        oai_model.setAccessibleName("OpenAI Model")
        oai_model.setPlaceholderText("local-model")
        fields.append(_Field(oai_model, "openai.model", manager))
        oai_form.addRow("Model:", oai_model)

        oai_key_env = QLineEdit()
        oai_key_env.setAccessibleName("OpenAI API Key Env Var")
        oai_key_env.setPlaceholderText("OPENAI_API_KEY (env var name)")
        fields.append(_Field(oai_key_env, "openai.api_key_env", manager))
        oai_form.addRow("API key env var:", oai_key_env)
        layout.addWidget(oai_grp)

        # NPU
        npu_grp = QGroupBox("NPU settings")
        npu_form = QFormLayout(npu_grp)
        npu_path = QLineEdit()
        npu_path.setAccessibleName("NPU Model Path")
        npu_path.setPlaceholderText("/path/to/model.onnx")
        fields.append(_Field(npu_path, "npu.model_path", manager))
        npu_form.addRow("ONNX model path:", npu_path)

        npu_provider = QLineEdit()
        npu_provider.setAccessibleName("NPU Execution Provider")
        npu_provider.setPlaceholderText(
            "VitisAIExecutionProvider, OpenVINOExecutionProvider, QNNExecutionProvider"
        )
        fields.append(_Field(npu_provider, "npu.provider", manager))
        npu_form.addRow("ONNX provider:", npu_provider)
        layout.addWidget(npu_grp)

        layout.addStretch()
        return widget, fields

    def _tools_tab(manager: Any) -> tuple[QWidget, list[_Field]]:
        """Build the Tools settings tab."""
        fields: list[_Field] = []
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignTop)

        grp = QGroupBox("Tool behaviour")
        form = QFormLayout(grp)

        search_path = QLineEdit()
        search_path.setAccessibleName("NPU Models Search Path")
        search_path.setPlaceholderText("~")
        fields.append(_Field(search_path, "tools.search_path", manager))
        form.addRow("Search root path:", search_path)

        max_results = QSpinBox()
        max_results.setAccessibleName("Max Results for Vector Search")
        max_results.setRange(1, 500)
        fields.append(_Field(max_results, "tools.max_results", manager))
        form.addRow("Max search results:", max_results)

        unload_cb = QCheckBox("Unload tools from memory after each use")
        unload_cb.setAccessibleName("Unload tools from memory after each use")
        fields.append(_Field(unload_cb, "tools.unload_after_use", manager))
        form.addRow("", unload_cb)

        layout.addWidget(grp)
        layout.addStretch()
        return widget, fields

    def _security_tab(manager: Any) -> tuple[QWidget, list[_Field]]:
        """Build the Security settings tab."""
        fields: list[_Field] = []
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignTop)

        net_grp = QGroupBox("Network")
        net_form = QFormLayout(net_grp)
        allow_ext = QCheckBox(
            "Allow AI backend to contact external (non-local) servers"
        )
        allow_ext.setAccessibleName(
            "Allow AI backend to contact external (non-local) servers"
        )
        fields.append(_Field(allow_ext, "network.allow_external", manager))
        net_form.addRow("", allow_ext)
        layout.addWidget(net_grp)

        rate_grp = QGroupBox("Rate limiting")
        rate_form = QFormLayout(rate_grp)
        rate_spin = QSpinBox()
        rate_spin.setAccessibleName("Rate Limit")
        rate_spin.setRange(0, 3600)
        rate_spin.setSpecialValueText("Unlimited")
        rate_spin.setSuffix(" calls / min")
        fields.append(_Field(rate_spin, "security.rate_limit_per_minute", manager))
        rate_form.addRow("Max AI calls:", rate_spin)
        layout.addWidget(rate_grp)

        safety_grp = QGroupBox("Command safety")
        safety_form = QFormLayout(safety_grp)
        confirm_cb = QCheckBox("Confirm shell commands before executing")
        confirm_cb.setAccessibleName("Confirm shell commands before executing")
        fields.append(_Field(confirm_cb, "safety.confirm_commands", manager))
        safety_form.addRow("", confirm_cb)

        perm_cb = QCheckBox("Warn if config or history file is world-readable")
        perm_cb.setAccessibleName("Warn if config or history file is world-readable")
        fields.append(_Field(perm_cb, "security.check_file_permissions", manager))
        safety_form.addRow("", perm_cb)
        layout.addWidget(safety_grp)

        layout.addStretch()
        return widget, fields

    def _appearance_tab(manager: Any) -> tuple[QWidget, list[_Field]]:
        """Build the Appearance settings tab."""
        fields: list[_Field] = []
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignTop)

        grp = QGroupBox("Window")
        form = QFormLayout(grp)

        pos_combo = QComboBox()
        pos_combo.setAccessibleName("Window Position")
        pos_combo.addItems(
            ["top-right", "top-left", "bottom-right", "bottom-left", "center"]
        )
        fields.append(_Field(pos_combo, "appearance.position", manager))
        form.addRow("Position:", pos_combo)

        width_spin = QSpinBox()
        width_spin.setAccessibleName("Compact Window Width")
        width_spin.setRange(300, 1200)
        width_spin.setSuffix(" px")
        fields.append(_Field(width_spin, "appearance.width", manager))
        form.addRow("Width:", width_spin)

        opacity_spin = QDoubleSpinBox()
        opacity_spin.setAccessibleName("Window Opacity")
        opacity_spin.setRange(0.3, 1.0)
        opacity_spin.setSingleStep(0.05)
        opacity_spin.setDecimals(2)
        fields.append(_Field(opacity_spin, "appearance.opacity", manager))
        form.addRow("Opacity:", opacity_spin)

        font_size_spin = QSpinBox()
        font_size_spin.setAccessibleName("Base Font Size")
        font_size_spin.setRange(0, 36)
        font_size_spin.setSpecialValueText("System default")
        font_size_spin.setSuffix(" pt")
        fields.append(_Field(font_size_spin, "appearance.font_size", manager))
        form.addRow("Font size:", font_size_spin)

        always_top = QCheckBox("Always on top of other windows")
        always_top.setAccessibleName("Always on top of other windows")
        fields.append(_Field(always_top, "appearance.always_on_top", manager))
        form.addRow("", always_top)

        stream_cb = QCheckBox("Stream AI responses token by token")
        stream_cb.setAccessibleName("Stream AI responses token by token")
        fields.append(_Field(stream_cb, "resources.stream_response", manager))
        form.addRow("", stream_cb)

        auto_send_screen = QCheckBox("Automatically send screen on conversation page")
        auto_send_screen.setAccessibleName(
            "Automatically send screen on conversation page"
        )
        fields.append(_Field(auto_send_screen, "ui.auto_send_screen", manager))
        form.addRow("", auto_send_screen)

        layout.addWidget(grp)
        layout.addStretch()
        return widget, fields

    # ── Main dialog ───────────────────────────────────────────────────────────

    class SettingsWindow(QDialog):
        """Tabbed settings dialog.

        All changes are written through :class:`~src.settings.SettingsManager`
        and persisted to ``settings.json`` immediately — no Apply button needed.

        Args:
            manager:
                The application :class:`~src.settings.SettingsManager` instance.
            parent:
                Optional parent widget.
        """

        def __init__(
            self,
            manager: Any,
            parent: QWidget | None = None,
            history: "Any | None" = None,
        ) -> None:
            super().__init__(parent)
            self._manager = manager
            self._history = history
            self._fields: list[_Field] = []

            self.setWindowTitle("Linux AI NPU Assistant — Settings")
            self.setMinimumWidth(520)
            self.setMinimumHeight(500)
            self.resize(560, 600)

            main_layout = QVBoxLayout(self)

            # Apply desktop theme
            try:
                from src.gui.theme import apply_to_app
                from PyQt5.QtWidgets import QApplication

                apply_to_app(QApplication.instance())
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not apply theme: %s", exc)

            # Tabs
            self._tabs = QTabWidget()
            self._tabs.setAccessibleName("Settings Tabs")
            self._build_tabs()
            main_layout.addWidget(self._tabs)

            # Buttons
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(self.accept)
            main_layout.addWidget(buttons)

            # Load values
            for f in self._fields:
                f.load()

            # Connect signals (after load so we don't trigger spurious saves)
            for f in self._fields:
                f.connect()

        def _build_tabs(self) -> None:
            # Models tab is provided by ModelManagerWidget
            try:
                from src.gui.model_manager import ModelManagerWidget

                model_widget = ModelManagerWidget(self._manager, parent=self)
            except Exception:  # noqa: BLE001
                model_widget = QLabel("Model manager unavailable.")

            backend_widget, backend_fields = _backend_tab(self._manager)
            tools_widget, tools_fields = _tools_tab(self._manager)
            security_widget, sec_fields = _security_tab(self._manager)
            appearance_widget, app_fields = _appearance_tab(self._manager)

            self._fields.extend(backend_fields)
            self._fields.extend(tools_fields)
            self._fields.extend(sec_fields)
            self._fields.extend(app_fields)

            self._tabs.addTab(backend_widget, "AI Backend")
            self._tabs.addTab(model_widget, "Models")
            self._tabs.addTab(tools_widget, "Tools")
            self._tabs.addTab(security_widget, "Security")
            self._tabs.addTab(appearance_widget, "Appearance")
            self._tabs.addTab(_history_tab(self._history), "History")
            self._tabs.addTab(_updates_tab(), "Updates")


def open_settings(
    manager: Any, parent: object = None, history: "Any | None" = None
) -> None:
    """Open the settings dialog (convenience function).

    Args:
        manager:
            The application :class:`~src.settings.SettingsManager`.
        parent:
            Optional parent widget.
        history:
            Optional :class:`~src.conversation.ConversationHistory` — enables
            the History tab controls (encryption, password, export, import).

    Raises:
        RuntimeError: If PyQt5 is not installed.
    """
    _require_qt()
    win = SettingsWindow(manager, parent=parent, history=history)
    win.exec_()
