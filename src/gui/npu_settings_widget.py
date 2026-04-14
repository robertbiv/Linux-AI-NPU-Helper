# SPDX-License-Identifier: GPL-3.0-or-later
"""NPU-styled settings page widget (Settings tab).

Implements the visual design from the NPU Assistant mockup:

- **Neural Architecture** — model selection cards with primary/alternate
- **Contextual Capture** — toggle for screen-buffer analysis
- **Autonomous Tools** — three-way permission knobs (Auto / Ask / Off)
- **Thermal Thresholds** — slider for critical-alert temperature
- **Visual Core** — dark / light theme selector
- **Precision Instrument Mode** — advanced telemetry toggle

All changes are immediately forwarded to :class:`~src.settings.SettingsManager`
so they persist to ``settings.json`` without any Apply button.

Usage
-----
::

    from src.settings import SettingsManager
    from src.gui.npu_settings_widget import NPUSettingsWidget

    sm = SettingsManager()
    widget = NPUSettingsWidget(sm, parent=main_window)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtCore import Qt, pyqtSignal
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import (
        QButtonGroup,
        QCheckBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSlider,
        QVBoxLayout,
        QWidget,
    )
    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    logger.warning("PyQt5 not installed — NPUSettingsWidget unavailable.")

if _HAS_QT:
    from src.gui import npu_theme as T

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section_title(text: str, subtitle: str = "") -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)

        title = QLabel(text)
        title.setStyleSheet(
            f"color: {T.TEXT_PRIMARY}; font-size: 20px; font-weight: bold;"
            f"background: transparent;"
        )
        layout.addWidget(title)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 12px; background: transparent;"
            )
            sub.setWordWrap(True)
            layout.addWidget(sub)

        return container

    def _card(parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
        """Return a card frame and its inner layout."""
        frame = QFrame(parent)
        frame.setObjectName("settingsCard")
        frame.setStyleSheet(
            f"QFrame#settingsCard {{"
            f"  background-color: {T.BG_CARD};"
            f"  border: 1px solid {T.BORDER};"
            f"  border-radius: 12px;"
            f"}}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        return frame, layout

    def _card_section_label(text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            f"color: {T.TEXT_SECONDARY}; font-size: 10px; letter-spacing: 2px;"
            f"background: transparent;"
        )
        return lbl

    # ── Three-way toggle (Auto / Ask / Off) ───────────────────────────────────

    class _TriStateToggle(QWidget):
        """Inline three-button exclusive selector: Auto | Ask | Off."""

        value_changed = pyqtSignal(str)

        _OPTIONS = ["Auto", "Ask", "Off"]

        def __init__(self, initial: str = "Ask", parent: QWidget | None = None) -> None:
            super().__init__(parent)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self._buttons: dict[str, QPushButton] = {}
            self._group = QButtonGroup(self)
            self._group.setExclusive(True)

            for i, option in enumerate(self._OPTIONS):
                btn = QPushButton(option)
                btn.setCheckable(True)
                btn.setFixedHeight(30)

                if i == 0:
                    radius = "border-radius: 6px; border-top-right-radius: 0; border-bottom-right-radius: 0;"
                elif i == len(self._OPTIONS) - 1:
                    radius = "border-radius: 6px; border-top-left-radius: 0; border-bottom-left-radius: 0;"
                else:
                    radius = "border-radius: 0;"

                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background-color: {T.BG_CARD2};"
                    f"  color: {T.TEXT_SECONDARY};"
                    f"  border: 1px solid {T.BORDER};"
                    f"  {radius}"
                    f"  font-size: 11px;"
                    f"  padding: 4px 12px;"
                    f"}}"
                    f"QPushButton:checked {{"
                    f"  background-color: {T.BG_HOVER};"
                    f"  color: {T.TEXT_PRIMARY};"
                    f"  border-color: {T.BLUE};"
                    f"}}"
                )
                if option == "Off":
                    btn.setStyleSheet(
                        btn.styleSheet().replace(
                            f"color: {T.TEXT_PRIMARY};",
                            f"color: {T.RED};",
                        )
                    )

                self._group.addButton(btn)
                layout.addWidget(btn)
                self._buttons[option] = btn
                btn.clicked.connect(lambda checked, opt=option: self._on_click(opt))

            self.set_value(initial)

        def set_value(self, value: str) -> None:
            btn = self._buttons.get(value)
            if btn:
                btn.setChecked(True)

        def get_value(self) -> str:
            for opt, btn in self._buttons.items():
                if btn.isChecked():
                    return opt
            return "Ask"

        def _on_click(self, option: str) -> None:
            self.value_changed.emit(option)

    # ── iOS-style toggle switch ────────────────────────────────────────────────

    class _ToggleSwitch(QWidget):
        """Pill-shaped on/off toggle (like iOS UISwitch)."""

        toggled = pyqtSignal(bool)

        def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._checked = checked
            self.setFixedSize(52, 28)
            self.setCursor(Qt.PointingHandCursor)
            self._update_style()

        def _update_style(self) -> None:
            bg = T.BLUE if self._checked else T.BG_CARD2
            self.setStyleSheet(
                f"QWidget {{"
                f"  background-color: {bg};"
                f"  border-radius: 14px;"
                f"  border: 1px solid {T.BORDER if not self._checked else T.BLUE};"
                f"}}"
            )

        def isChecked(self) -> bool:
            return self._checked

        def setChecked(self, checked: bool) -> None:
            self._checked = checked
            self._update_style()
            self.update()

        def mousePressEvent(self, event: object) -> None:
            self._checked = not self._checked
            self._update_style()
            self.update()
            self.toggled.emit(self._checked)

        def paintEvent(self, event: object) -> None:
            from PyQt5.QtGui import QPainter, QBrush, QColor
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.setPen(Qt.NoPen)
            x = 26 if self._checked else 4
            painter.drawEllipse(x, 4, 20, 20)

    # ── Model selection card ──────────────────────────────────────────────────

    class _ModelCard(QFrame):
        """Single model option card (primary or alternate)."""

        selected = pyqtSignal(str)

        def __init__(
            self,
            model_id: str,
            name: str,
            description: str,
            optimization: str = "",
            badge_text: str = "",
            badge_color: str = T.GREEN,
            is_primary: bool = False,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._model_id = model_id
            self._is_primary = is_primary
            self.setCursor(Qt.PointingHandCursor)
            self._set_style(is_primary)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setSpacing(10)

            # Icon
            icon = QLabel("⚡" if is_primary else "◈")
            icon.setStyleSheet(
                f"color: {T.GREEN if is_primary else T.TEXT_SECONDARY};"
                f"font-size: 18px; background: transparent;"
            )
            icon.setFixedSize(28, 28)
            layout.addWidget(icon)

            # Text block
            text_col = QVBoxLayout()
            text_col.setSpacing(2)

            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(
                f"color: {T.TEXT_GREEN if is_primary else T.TEXT_PRIMARY};"
                f"font-size: 14px; font-weight: bold; background: transparent;"
            )
            text_col.addWidget(name_lbl)

            desc_lbl = QLabel(description)
            desc_lbl.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 11px; background: transparent;"
            )
            text_col.addWidget(desc_lbl)

            if optimization:
                opt_row = QHBoxLayout()
                opt_row.setSpacing(6)
                opt_lbl = QLabel(f"OPTIMIZATION: {optimization}")
                opt_lbl.setStyleSheet(
                    f"color: {T.TEXT_SECONDARY}; font-size: 10px; background: transparent;"
                )
                opt_row.addWidget(opt_lbl)
                if badge_text:
                    badge = QLabel(badge_text)
                    badge.setStyleSheet(
                        f"color: {T.BG_MAIN}; background: {badge_color};"
                        f"border-radius: 3px; padding: 1px 6px;"
                        f"font-size: 10px; font-weight: bold;"
                    )
                    opt_row.addWidget(badge)
                opt_row.addStretch()
                text_col.addLayout(opt_row)

            layout.addLayout(text_col)
            layout.addStretch()

            if is_primary:
                check = QLabel("✓")
                check.setStyleSheet(
                    f"color: {T.GREEN}; font-size: 18px; background: transparent;"
                )
                layout.addWidget(check)

        def _set_style(self, primary: bool) -> None:
            self.setObjectName("modelCard")
            if primary:
                self.setStyleSheet(
                    f"QFrame#modelCard {{"
                    f"  background-color: {T.GREEN_DIM};"
                    f"  border: 1px solid {T.GREEN};"
                    f"  border-radius: 10px;"
                    f"}}"
                )
            else:
                self.setStyleSheet(
                    f"QFrame#modelCard {{"
                    f"  background-color: {T.BG_CARD2};"
                    f"  border: 1px solid {T.BORDER};"
                    f"  border-radius: 10px;"
                    f"}}"
                )

        def mousePressEvent(self, event: object) -> None:
            self.selected.emit(self._model_id)

    # ── Theme card ────────────────────────────────────────────────────────────

    class _ThemeCard(QFrame):
        """Visual theme selector card."""

        selected = pyqtSignal(str)

        def __init__(
            self,
            theme_id: str,
            label: str,
            dark: bool = True,
            active: bool = False,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._theme_id = theme_id
            self._active = active
            self.setCursor(Qt.PointingHandCursor)
            self.setObjectName("themeCard")

            bg = T.BG_CARD if dark else "#f0f2f5"
            border = T.GREEN if active else T.BORDER
            self.setStyleSheet(
                f"QFrame#themeCard {{"
                f"  background-color: {bg};"
                f"  border: 2px solid {border};"
                f"  border-radius: 10px;"
                f"}}"
            )
            self.setFixedHeight(72)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(8, 6, 8, 6)

            preview_lines = QFrame()
            preview_lines.setFixedHeight(28)
            preview_lines.setStyleSheet("background: transparent;")
            # Three horizontal preview lines
            lines_layout = QVBoxLayout(preview_lines)
            lines_layout.setSpacing(4)
            lines_layout.setContentsMargins(0, 0, 0, 0)
            for _ in range(3):
                line = QFrame()
                line.setFixedHeight(3)
                line.setStyleSheet(
                    f"background: {'#2a2d38' if dark else '#c0c4d0'}; border-radius: 1px;"
                )
                lines_layout.addWidget(line)
            layout.addWidget(preview_lines)

            name_lbl = QLabel(label.upper())
            name_lbl.setAlignment(Qt.AlignCenter)
            name_lbl.setStyleSheet(
                f"color: {'#8b90a2' if dark else '#606880'}; font-size: 9px;"
                f"letter-spacing: 1px; background: transparent;"
            )
            layout.addWidget(name_lbl)

        def mousePressEvent(self, event: object) -> None:
            self.selected.emit(self._theme_id)

    # ── Main settings widget ──────────────────────────────────────────────────

    class NPUSettingsWidget(QWidget):
        """Settings page with NPU-themed cards matching the mockup design.

        Parameters
        ----------
        settings_manager:
            The application :class:`~src.settings.SettingsManager` instance.
            Can be ``None`` (settings are shown but not persisted).
        parent:
            Optional parent widget.
        """

        def __init__(
            self,
            settings_manager: Any = None,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._sm = settings_manager
            self._setup_ui()
            self._load_settings()

        def _setup_ui(self) -> None:
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(16)

            layout.addWidget(
                _section_title(
                    "Settings",
                    "Configure your neural environment and hardware-accelerated preferences.",
                )
            )

            # ── Neural Architecture ────────────────────────────────────────
            na_card, na_layout = _card()
            na_header = QHBoxLayout()
            na_icon = QLabel("⟳")
            na_icon.setStyleSheet(
                f"color: {T.BLUE}; font-size: 20px; background: transparent;"
            )
            na_header.addWidget(na_icon)
            na_title = QLabel("Neural Architecture")
            na_title.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 16px; font-weight: bold;"
                f"background: transparent;"
            )
            na_header.addWidget(na_title)
            na_header.addStretch()
            na_layout.addLayout(na_header)

            na_layout.addWidget(_card_section_label("Primary Compute Model"))

            self._model_llama = _ModelCard(
                "llama-3-npu-8b",
                "Llama-3-NPU-8B",
                "Optimized for low-latency local inference",
                optimization="5/5",
                badge_text="HIGHLY OPTIMIZED",
                badge_color=T.GREEN,
                is_primary=True,
            )
            na_layout.addWidget(self._model_llama)

            self._model_mistral = _ModelCard(
                "mistral-7b-instruct",
                "Mistral-7B-Instruct",
                "High-precision reasoning kernel",
                optimization="4/5",
                badge_text="COMPATIBLE",
                badge_color=T.BLUE,
                is_primary=False,
            )
            na_layout.addWidget(self._model_mistral)
            layout.addWidget(na_card)

            # ── Contextual Capture ─────────────────────────────────────────
            cc_card, cc_layout = _card()
            cc_header = QHBoxLayout()
            cc_icon = QLabel("☐")
            cc_icon.setStyleSheet(
                f"color: {T.BLUE}; font-size: 22px; background: transparent;"
            )
            cc_header.addWidget(cc_icon)
            cc_title = QLabel("Contextual Capture")
            cc_title.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 16px; font-weight: bold;"
                f"background: transparent;"
            )
            cc_header.addWidget(cc_title)
            cc_header.addStretch()
            cc_layout.addLayout(cc_header)

            cc_desc = QLabel(
                "Allow Assistant to analyze active screen buffer for NPU context."
            )
            cc_desc.setWordWrap(True)
            cc_desc.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 12px; background: transparent;"
            )
            cc_layout.addWidget(cc_desc)

            cc_toggle_row = QHBoxLayout()
            cc_state_lbl = QLabel("STATE: ACTIVE")
            cc_state_lbl.setStyleSheet(
                f"color: {T.TEXT_MUTED}; font-size: 10px; letter-spacing: 1px;"
                f"background: transparent;"
            )
            cc_toggle_row.addWidget(cc_state_lbl)
            cc_toggle_row.addStretch()
            self._capture_toggle = _ToggleSwitch(checked=True)
            self._capture_toggle.toggled.connect(self._on_capture_toggled)
            cc_toggle_row.addWidget(self._capture_toggle)
            cc_layout.addLayout(cc_toggle_row)
            layout.addWidget(cc_card)

            # ── Autonomous Tools ───────────────────────────────────────────
            at_card, at_layout = _card()
            at_header = QHBoxLayout()
            at_icon = QLabel("❖")
            at_icon.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 18px; background: transparent;"
            )
            at_header.addWidget(at_icon)
            at_title = QLabel("Autonomous Tools")
            at_title.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 16px; font-weight: bold;"
                f"background: transparent;"
            )
            at_header.addWidget(at_title)
            at_header.addStretch()
            at_layout.addLayout(at_header)

            self._fs_toggle = self._tool_row(
                at_layout, "⊞ FILE SYSTEM ACCESS", "Auto"
            )
            self._web_toggle = self._tool_row(
                at_layout, "⊕ WEB RETRIEVAL", "Auto"
            )
            self._kern_toggle = self._tool_row(
                at_layout, "⊡ KERNEL TERMINAL", "Off"
            )
            layout.addWidget(at_card)

            # ── Thermal Thresholds ─────────────────────────────────────────
            th_card, th_layout = _card()
            th_header = QHBoxLayout()
            th_icon = QLabel("🌡")
            th_icon.setStyleSheet(
                f"color: {T.GREEN}; font-size: 18px; background: transparent;"
            )
            th_header.addWidget(th_icon)
            th_title = QLabel("Thermal Thresholds")
            th_title.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 16px; font-weight: bold;"
                f"background: transparent;"
            )
            th_header.addWidget(th_title)
            th_header.addStretch()
            th_layout.addLayout(th_header)

            th_slider_row = QHBoxLayout()
            th_slider_lbl = QLabel("Critical Alert")
            th_slider_lbl.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 13px; background: transparent;"
            )
            th_slider_row.addWidget(th_slider_lbl)
            th_slider_row.addStretch()
            self._thermal_value_lbl = QLabel("85°C")
            self._thermal_value_lbl.setStyleSheet(
                f"color: {T.GREEN}; font-size: 13px; font-weight: bold;"
                f"background: transparent;"
            )
            th_slider_row.addWidget(self._thermal_value_lbl)
            th_layout.addLayout(th_slider_row)

            self._thermal_slider = QSlider(Qt.Horizontal)
            self._thermal_slider.setRange(60, 110)
            self._thermal_slider.setValue(85)
            self._thermal_slider.valueChanged.connect(self._on_thermal_changed)
            th_layout.addWidget(self._thermal_slider)

            th_notify_row = QHBoxLayout()
            th_notify_icon = QLabel("🔔")
            th_notify_icon.setStyleSheet("background: transparent; font-size: 14px;")
            th_notify_row.addWidget(th_notify_icon)
            self._thermal_notify_cb = QCheckBox(
                "Notify when NPU frequency throttles due to heat."
            )
            self._thermal_notify_cb.setChecked(True)
            self._thermal_notify_cb.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 12px; background: transparent;"
            )
            self._thermal_notify_cb.stateChanged.connect(self._on_thermal_notify_changed)
            th_notify_row.addWidget(self._thermal_notify_cb)
            th_layout.addLayout(th_notify_row)
            layout.addWidget(th_card)

            # ── Visual Core ────────────────────────────────────────────────
            vc_card, vc_layout = _card()
            vc_header = QHBoxLayout()
            vc_icon = QLabel("🎨")
            vc_icon.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 18px; background: transparent;"
            )
            vc_header.addWidget(vc_icon)
            vc_title = QLabel("Visual Core")
            vc_title.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 16px; font-weight: bold;"
                f"background: transparent;"
            )
            vc_header.addWidget(vc_title)
            vc_header.addStretch()
            vc_layout.addLayout(vc_header)

            themes_row = QHBoxLayout()
            themes_row.setSpacing(10)
            dark_card = _ThemeCard("neural_dark", "Neural Dark", dark=True, active=True)
            dark_card.selected.connect(lambda tid: self._on_theme_selected(tid))
            themes_row.addWidget(dark_card)

            light_card = _ThemeCard("pristine_light", "Pristine Light", dark=False, active=False)
            light_card.selected.connect(lambda tid: self._on_theme_selected(tid))
            themes_row.addWidget(light_card)
            themes_row.addStretch()
            vc_layout.addLayout(themes_row)
            layout.addWidget(vc_card)

            # ── Precision Instrument Mode ──────────────────────────────────
            pi_card, pi_layout = _card()
            pi_row = QHBoxLayout()

            pi_text = QVBoxLayout()
            pi_title = QLabel("Precision\nInstrument Mode")
            pi_title.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 15px; font-weight: bold;"
                f"background: transparent;"
            )
            pi_text.addWidget(pi_title)
            pi_desc = QLabel(
                "Enable detailed terminal logging and raw NPU kernel telemetry."
            )
            pi_desc.setWordWrap(True)
            pi_desc.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 11px; background: transparent;"
            )
            pi_text.addWidget(pi_desc)
            pi_row.addLayout(pi_text)
            pi_row.addStretch()

            pi_btn = QPushButton("ADVANCED\nTUNING")
            pi_btn.setFixedSize(90, 48)
            pi_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {T.BG_CARD2};"
                f"  color: {T.TEXT_SECONDARY};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-radius: 8px;"
                f"  font-size: 10px;"
                f"  font-weight: bold;"
                f"  letter-spacing: 0.5px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  border-color: {T.GREEN};"
                f"  color: {T.TEXT_PRIMARY};"
                f"}}"
            )
            pi_row.addWidget(pi_btn)
            pi_layout.addLayout(pi_row)
            layout.addWidget(pi_card)

            layout.addStretch()

            scroll.setWidget(page)
            outer.addWidget(scroll)

        # ── Tool permission row builder ────────────────────────────────────────

        def _tool_row(
            self,
            layout: QVBoxLayout,
            label: str,
            default: str,
        ) -> _TriStateToggle:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 10px; letter-spacing: 1px;"
                f"background: transparent;"
            )
            row.addWidget(lbl)
            row.addStretch()
            toggle = _TriStateToggle(initial=default)
            row.addWidget(toggle)
            layout.addLayout(row)
            return toggle

        # ── Settings load / save ──────────────────────────────────────────────

        def _load_settings(self) -> None:
            if self._sm is None:
                return
            auto_send = self._sm.get("ui.auto_send_screen", True)
            self._capture_toggle.setChecked(bool(auto_send))

        def _on_capture_toggled(self, checked: bool) -> None:
            if self._sm:
                self._sm.set("ui.auto_send_screen", checked, save=True)

        def _on_thermal_changed(self, value: int) -> None:
            self._thermal_value_lbl.setText(f"{value}°C")
            if self._sm:
                self._sm.set("npu.thermal_threshold_c", value, save=True)

        def _on_thermal_notify_changed(self, state: int) -> None:
            if self._sm:
                from PyQt5.QtCore import Qt as _Qt
                self._sm.set(
                    "npu.thermal_notify",
                    state == _Qt.Checked,
                    save=True,
                )

        def _on_theme_selected(self, theme_id: str) -> None:
            if self._sm:
                self._sm.set("appearance.theme", theme_id, save=True)
            logger.info("Theme selected: %s", theme_id)
