# SPDX-License-Identifier: GPL-3.0-or-later
"""Full desktop-style window for Neural Monolith.

Implements the wide desktop layout shown in the mockup:

- **Left sidebar** — app branding, navigation list, status bar at the bottom
- **Top header** — section title, breadcrumb tabs, right-side action icons
- **Main content area** — swaps between Chat, NPU Performance, Neural Models,
  System Logs, and Preferences pages

The window exposes :meth:`FullWindow.set_page` to switch pages programmatically
and emits ``collapse_requested`` when the user clicks the ⤡ button to return
to compact mode.
## Usage
::

    from src.gui.full_window import FullWindow
    win = FullWindow(settings_manager=sm, ai_assistant=assistant)
    win.collapse_requested.connect(on_collapse)
    win.show()
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtCore import Qt, pyqtSignal
    from PyQt5.QtWidgets import (
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QStackedWidget,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )

    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    logger.warning("PyQt5 not installed — FullWindow unavailable.")

APP_NAME = "Neural Monolith"
APP_VERSION = "V2.4.0-STABLE"

# Page identifiers
PAGE_CHAT = "chat"
PAGE_NPU_PERF = "npu_performance"
PAGE_NEURAL_MODELS = "neural_models"
PAGE_SYSTEM_LOGS = "system_logs"
PAGE_API = "api_integration"
PAGE_PREFERENCES = "preferences"

if _HAS_QT:
    from src.gui import npu_theme as T

    # ── Sidebar nav item ──────────────────────────────────────────────────────

    class _NavItem(QPushButton):
        """Single navigation item in the sidebar."""

        def __init__(
            self,
            icon: str,
            label: str,
            page_id: str,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._page_id = page_id
            self.setCheckable(True)
            self.setText(f"  {icon}   {label}")
            self.setAccessibleName(label)
            self.setFixedHeight(44)
            self.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: transparent;"
                f"  color: {T.TEXT_SECONDARY};"
                f"  border: 1px solid transparent; border-radius: 4px;"
                f"  border-left: 3px solid transparent;"
                f"  border-radius: 0;"
                f"  text-align: left;"
                f"  padding-left: 14px;"
                f"  font-size: 13px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: {T.BG_HOVER};"
                f"  color: {T.TEXT_PRIMARY};"
                f"}}"
                f"QPushButton:checked {{"
                f"  background-color: {T.BG_CARD2};"
                f"  color: {T.TEXT_PRIMARY};"
                f"  border-left: 3px solid {T.BLUE};"
                f"}}"
            )

        @property
        def page_id(self) -> str:
            return self._page_id

    # ── Sidebar ───────────────────────────────────────────────────────────────

    class _Sidebar(QFrame):
        """Left navigation sidebar."""

        page_selected = pyqtSignal(str)

        _NAV_ITEMS = [
            ("⬡", "Chat", PAGE_CHAT),
            ("⬖", "NPU Performance", PAGE_NPU_PERF),
            ("⬟", "Neural Models", PAGE_NEURAL_MODELS),
            ("☰", "System Logs", PAGE_SYSTEM_LOGS),
            ("⚙", "API Integration", PAGE_API),
            ("⚙", "Preferences", PAGE_PREFERENCES),
        ]

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("sidebar")
            self.setFixedWidth(220)
            self.setStyleSheet(
                f"QFrame#sidebar {{"
                f"  background-color: {T.BG_CARD};"
                f"  border-right: 1px solid {T.BORDER};"
                f"}}"
            )

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # ── Brand header ──────────────────────────────────────────────
            brand = QWidget()
            brand.setStyleSheet(f"background: {T.BG_CARD};")
            brand_layout = QHBoxLayout(brand)
            brand_layout.setContentsMargins(14, 16, 14, 16)
            brand_layout.setSpacing(10)

            icon_box = QLabel("✦")
            icon_box.setFixedSize(36, 36)
            icon_box.setAlignment(Qt.AlignCenter)
            icon_box.setStyleSheet(
                f"background: {T.BLUE}; color: #ffffff;"
                f"font-size: 16px; border-radius: 8px;"
            )
            brand_layout.addWidget(icon_box)

            brand_text = QVBoxLayout()
            brand_text.setSpacing(0)
            app_name_lbl = QLabel(APP_NAME)
            app_name_lbl.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;"
                f"background: transparent;"
            )
            brand_text.addWidget(app_name_lbl)
            ver_lbl = QLabel(APP_VERSION)
            ver_lbl.setStyleSheet(
                f"color: {T.TEXT_MUTED}; font-size: 10px; background: transparent;"
                f"letter-spacing: 1px;"
            )
            brand_text.addWidget(ver_lbl)
            brand_layout.addLayout(brand_text)
            brand_layout.addStretch()
            layout.addWidget(brand)

            # Divider
            div = QFrame()
            div.setFixedHeight(1)
            div.setStyleSheet(f"background: {T.BORDER};")
            layout.addWidget(div)

            layout.addSpacing(8)

            # ── Nav items ─────────────────────────────────────────────────
            self._nav_buttons: list[_NavItem] = []
            for icon, label, page_id in self._NAV_ITEMS:
                btn = _NavItem(icon, label, page_id)
                btn.clicked.connect(lambda _, b=btn: self._on_nav(b))
                layout.addWidget(btn)
                self._nav_buttons.append(btn)

            layout.addStretch()

            # Divider
            div2 = QFrame()
            div2.setFixedHeight(1)
            div2.setStyleSheet(f"background: {T.BORDER};")
            layout.addWidget(div2)

            # ── Check updates button ──────────────────────────────────────
            update_btn = QPushButton("CHECK UPDATES")
            update_btn.setToolTip("Check for and install application updates")
            update_btn.setAccessibleName("Check for and install application updates")
            update_btn.setFixedHeight(36)
            update_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {T.BLUE};"
                f"  color: #ffffff;"
                f"  border: 1px solid transparent; border-radius: 4px;"
                f"  border-radius: 6px;"
                f"  font-size: 11px;"
                f"  font-weight: bold;"
                f"  letter-spacing: 1px;"
                f"  margin: 10px 14px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: #5590ff;"
                f"}}"
            )
            layout.addWidget(update_btn)

            # ── Status bar ────────────────────────────────────────────────
            status_bar = QWidget()
            status_bar.setStyleSheet(f"background: {T.BG_CARD};")
            sb_layout = QHBoxLayout(status_bar)
            sb_layout.setContentsMargins(14, 8, 14, 12)
            sb_layout.setSpacing(12)

            self._npu_lbl = QLabel("● NPU: 12.4%")
            self._npu_lbl.setStyleSheet(
                f"color: {T.GREEN}; font-size: 10px; background: transparent;"
            )
            sb_layout.addWidget(self._npu_lbl)

            self._mem_lbl = QLabel("● MEM: 4.8 GB")
            self._mem_lbl.setStyleSheet(
                f"color: {T.BLUE}; font-size: 10px; background: transparent;"
            )
            sb_layout.addWidget(self._mem_lbl)
            sb_layout.addStretch()
            layout.addWidget(status_bar)

            # Select first item
            if self._nav_buttons:
                self._select(self._nav_buttons[0])

        def _on_nav(self, btn: _NavItem) -> None:
            self._select(btn)
            self.page_selected.emit(btn.page_id)

        def _select(self, target: _NavItem) -> None:
            for b in self._nav_buttons:
                b.setChecked(b is target)

        def select_page(self, page_id: str) -> None:
            for b in self._nav_buttons:
                if b.page_id == page_id:
                    self._select(b)
                    break

        def update_stats(self, npu_pct: float = 12.4, mem_gb: float = 4.8) -> None:
            self._npu_lbl.setText(f"● NPU: {npu_pct:.1f}%")
            self._mem_lbl.setText(f"● MEM: {mem_gb:.1f} GB")

    # ── Top header ─────────────────────────────────────────────────────────────

    class _TopHeader(QFrame):
        """Horizontal top bar with section title, breadcrumb tabs, and actions."""

        collapse_clicked = pyqtSignal()

        _BREADCRUMBS = ["ASSISTANT SETTINGS", "OVERVIEW", "ADVANCED", "SECURITY"]

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("topHeader")
            self.setFixedHeight(50)
            self.setStyleSheet(
                f"QFrame#topHeader {{"
                f"  background-color: {T.BG_CARD};"
                f"  border-bottom: 1px solid {T.BORDER};"
                f"}}"
            )

            layout = QHBoxLayout(self)
            layout.setContentsMargins(20, 0, 16, 0)
            layout.setSpacing(0)

            # Breadcrumb tabs
            self._tab_buttons: list[QPushButton] = []
            for i, crumb in enumerate(self._BREADCRUMBS):
                btn = QPushButton(crumb)
                btn.setAccessibleName(crumb)
                btn.setCheckable(True)
                is_active = i == 1  # OVERVIEW active by default
                btn.setChecked(is_active)
                btn.setFixedHeight(50)
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: transparent; border: 1px solid transparent; border-radius: 4px;"
                    f"  border-bottom: 2px solid transparent;"
                    f"  color: {T.TEXT_SECONDARY if not is_active else T.TEXT_PRIMARY};"
                    f"  font-size: 11px; letter-spacing: 0.5px;"
                    f"  padding: 0 16px;"
                    f"  border-radius: 0;"
                    f"}}"
                    + (
                        f"QPushButton:checked {{ border-bottom: 2px solid {T.GREEN}; color: {T.TEXT_PRIMARY}; }}"
                        if is_active
                        else f"QPushButton:hover {{ color: {T.TEXT_PRIMARY}; }}"
                    )
                )
                layout.addWidget(btn)
                self._tab_buttons.append(btn)

            layout.addStretch()

            # Search bar placeholder
            search = QLabel("🔍  SEARCH PARAMETERS...")
            search.setStyleSheet(
                f"color: {T.TEXT_MUTED}; font-size: 11px; background: {T.BG_INPUT};"
                f"border: 1px solid {T.BORDER}; border-radius: 6px;"
                f"padding: 4px 12px;"
            )
            search.setFixedHeight(30)
            search.setFixedWidth(180)
            layout.addWidget(search)

            layout.addSpacing(12)

            # Status dots
            for color in [T.TEXT_MUTED, T.TEXT_MUTED, T.GREEN]:
                dot = QLabel("●")
                dot.setStyleSheet(
                    f"color: {color}; font-size: 14px; background: transparent;"
                )
                layout.addWidget(dot)

            layout.addSpacing(8)

            # Notification icon
            notif = QToolButton()
            notif.setFocusPolicy(Qt.StrongFocus)
            notif.setText("🔔")
            notif.setToolTip("Notifications")
            notif.setAccessibleName("Notifications")
            notif.setStyleSheet(
                "QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; font-size: 16px; }"
            )
            layout.addWidget(notif)

            # Collapse / shrink button
            collapse_btn = QToolButton()
            collapse_btn.setFocusPolicy(Qt.StrongFocus)
            collapse_btn.setText("⤡")
            collapse_btn.setToolTip("Switch to compact mode")
            collapse_btn.setAccessibleName("Switch to compact mode")
            collapse_btn.setFixedSize(30, 30)
            collapse_btn.setStyleSheet(
                f"QToolButton {{"
                f"  background: {T.BG_CARD2}; border: 1px solid {T.BORDER};"
                f"  border-radius: 6px; color: {T.TEXT_SECONDARY}; font-size: 16px;"
                f"}}"
                f"QToolButton:hover {{ color: {T.TEXT_PRIMARY}; border-color: {T.GREEN}; }}"
                f"QToolButton:focus {{ border-color: {T.BLUE}; }}"
                f"QToolButton:focus {{ border-color: {T.BLUE}; }}"
            )
            collapse_btn.clicked.connect(self.collapse_clicked)
            layout.addSpacing(6)
            layout.addWidget(collapse_btn)

    # ── Placeholder page ──────────────────────────────────────────────────────

    def _placeholder_page(title: str, subtitle: str = "") -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(30, 30, 30, 30)
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color: {T.TEXT_PRIMARY}; font-size: 24px; font-weight: bold; background: transparent;"
        )
        layout.addWidget(lbl)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 13px; background: transparent;"
            )
            layout.addWidget(sub)
        layout.addStretch()
        return w

    # ── Full window ────────────────────────────────────────────────────────────

    class FullWindow(QWidget):
        """Full desktop-layout window for Neural Monolith.

        Args:
            settings_manager: Application :class:`~src.settings.SettingsManager` (optional).
            ai_assistant: Application :class:`~src.ai_assistant.AIAssistant` (optional).
            parent: Optional parent widget.

            Signals:
            collapse_requested: Emitted when the user clicks the shrink / ⤡ button.
        """

        collapse_requested = pyqtSignal()

        def __init__(
            self,
            settings_manager: Any = None,
            ai_assistant: Any = None,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._sm = settings_manager
            self._ai = ai_assistant
            self._setup_ui()

        def _setup_ui(self) -> None:
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

            # Top header
            self._header = _TopHeader()
            self._header.collapse_clicked.connect(self.collapse_requested)
            outer.addWidget(self._header)

            # Body: sidebar + main content
            body = QHBoxLayout()
            body.setContentsMargins(0, 0, 0, 0)
            body.setSpacing(0)

            self._sidebar = _Sidebar()
            self._sidebar.page_selected.connect(self.set_page)
            body.addWidget(self._sidebar)

            # Main stacked widget
            self._stack = QStackedWidget()
            self._stack.setStyleSheet(f"background: {T.BG_MAIN};")
            body.addWidget(self._stack, stretch=1)

            # Build pages
            self._pages: dict[str, int] = {}
            self._build_pages()

            outer.addLayout(body, stretch=1)

        def _build_pages(self) -> None:
            from src.gui.chat_widget import ChatWidget
            from src.gui.status_widget import StatusWidget
            from src.gui.npu_settings_widget import NPUSettingsWidget

            chat = ChatWidget(self._sm)
            self._chat_widget = chat
            self._add_page(PAGE_CHAT, chat)

            status = StatusWidget()
            self._status_widget = status
            self._add_page(PAGE_NPU_PERF, status)

            settings = NPUSettingsWidget(self._sm)
            self._add_page(PAGE_NEURAL_MODELS, settings)

            logs = _placeholder_page(
                "System Logs",
                "Real-time NPU kernel event stream and diagnostic history.",
            )
            self._add_page(PAGE_SYSTEM_LOGS, logs)

            api = _placeholder_page(
                "API Integration",
                "Configure external endpoints and authentication tokens.",
            )
            self._add_page(PAGE_API, api)

            prefs = NPUSettingsWidget(self._sm)
            self._add_page(PAGE_PREFERENCES, prefs)

            # Default
            self._stack.setCurrentIndex(0)

        def _add_page(self, page_id: str, widget: QWidget) -> None:
            idx = self._stack.addWidget(widget)
            self._pages[page_id] = idx

        # ── Public API ────────────────────────────────────────────────────────

        def set_page(self, page_id: str) -> None:
            """Switch the visible page."""
            idx = self._pages.get(page_id)
            if idx is not None:
                self._stack.setCurrentIndex(idx)
                self._sidebar.select_page(page_id)

        def update_stats(self, npu_pct: float = 12.4, mem_gb: float = 4.8) -> None:
            """Update the sidebar status bar."""
            self._sidebar.update_stats(npu_pct, mem_gb)

        def chat_widget(self):
            """Return the embedded :class:`~src.gui.chat_widget.ChatWidget`."""
            return self._chat_widget

        def status_widget(self):
            """Return the embedded :class:`~src.gui.status_widget.StatusWidget`."""
            return self._status_widget
