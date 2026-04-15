# SPDX-License-Identifier: GPL-3.0-or-later
"""Neural Monolith — main application window.

This is the single entry-point QMainWindow for the application.  It manages
two display modes and lets the user switch between them at any time:

Compact mode (overlay)
    A slim floating panel (~420 × 680 px) that sits in a corner of the
    screen.  Shows only the Chat interface with a bottom tab-bar for Chat /
    Data / Settings.  Ideal for quick queries without leaving the current
    app.  Activated at start-up by default.

Full mode (desktop)
    A wide, resizable window (~1100 × 760 px) with a left sidebar for
    navigation and a large main content area.  Gives access to all
    dashboards: Chat, NPU Performance, Neural Models, System Logs,
    API Integration, and Preferences.

Toggle button
    Both modes expose a small **⤢ / ⤡** button in their header that
    switches to the other mode instantly while preserving all widget state
    (the AI conversation history, current page, etc.).

Usage
-----
::

    from src.settings import SettingsManager
    from src.gui.main_window import MainWindow
    from PyQt5.QtWidgets import QApplication

    app = QApplication([])
    sm  = SettingsManager()
    win = MainWindow(settings_manager=sm)
    win.show()
    app.exec_()
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtCore import Qt, QPoint, QSize, pyqtSignal, QTimer
    from PyQt5.QtGui import QColor, QFont
    from PyQt5.QtWidgets import (
        QApplication,
        QFrame,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QPushButton,
        QSizePolicy,
        QStackedWidget,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    logger.warning("PyQt5 not installed — MainWindow unavailable.")

APP_NAME    = "Neural Monolith"
APP_VERSION = "V2.4.0-STABLE"

# Mode identifiers
MODE_COMPACT = "compact"
MODE_FULL    = "full"

# Bottom-tab identifiers (compact mode only)
TAB_CHAT     = "chat"
TAB_DATA     = "data"
TAB_SETTINGS = "settings"

if _HAS_QT:
    from src.gui import npu_theme as T

    # ── Compact header ────────────────────────────────────────────────────────

    class _CompactHeader(QFrame):
        """Top bar shown in compact (overlay) mode."""

        expand_clicked  = pyqtSignal()
        more_clicked    = pyqtSignal()

        def __init__(self, model_name: str = "Llama-3-NPU-8B", parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("compactHeader")
            self.setFixedHeight(56)
            self.setStyleSheet(
                f"QFrame#compactHeader {{"
                f"  background-color: {T.BG_CARD};"
                f"  border-bottom: 1px solid {T.BORDER};"
                f"}}"
            )

            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 0, 12, 0)
            layout.setSpacing(8)

            # App icon + name
            icon_lbl = QLabel("✦")
            icon_lbl.setFixedSize(32, 32)
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setStyleSheet(
                f"background: {T.BLUE}; color: #ffffff;"
                f"font-size: 14px; border-radius: 6px;"
            )
            layout.addWidget(icon_lbl)

            name_col = QVBoxLayout()
            name_col.setSpacing(0)
            name_lbl = QLabel(APP_NAME)
            name_lbl.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 13px; font-weight: bold;"
                f"background: transparent;"
            )
            name_col.addWidget(name_lbl)
            layout.addLayout(name_col)

            layout.addSpacing(4)

            # Model selector badge
            self._model_badge = QLabel(f"MODEL:  {model_name}  ▾")
            self._model_badge.setStyleSheet(
                f"color: {T.GREEN}; background: {T.BG_CARD2};"
                f"border: 1px solid {T.BORDER_GREEN};"
                f"border-radius: 6px; padding: 4px 10px; font-size: 11px;"
            )
            layout.addWidget(self._model_badge)

            layout.addStretch()

            # Expand button (⤢)
            expand_btn = QToolButton()
            expand_btn.setText("⤢")
            expand_btn.setToolTip("Switch to full desktop mode")
            expand_btn.setFixedSize(30, 30)
            expand_btn.setStyleSheet(
                f"QToolButton {{"
                f"  background: {T.BG_CARD2}; border: 1px solid {T.BORDER};"
                f"  border-radius: 6px; color: {T.TEXT_SECONDARY}; font-size: 16px;"
                f"}}"
                f"QToolButton:hover {{ color: {T.GREEN}; border-color: {T.GREEN}; }}"
            )
            expand_btn.clicked.connect(self.expand_clicked)
            layout.addWidget(expand_btn)

            # More (⋮)
            more_btn = QToolButton()
            more_btn.setText("⋮")
            more_btn.setToolTip("More options")
            more_btn.setFixedSize(30, 30)
            more_btn.setStyleSheet(
                f"QToolButton {{"
                f"  background: transparent; border: none;"
                f"  color: {T.TEXT_SECONDARY}; font-size: 20px;"
                f"}}"
                f"QToolButton:hover {{ color: {T.TEXT_PRIMARY}; }}"
            )
            more_btn.clicked.connect(self.more_clicked)
            layout.addWidget(more_btn)

        def set_model_name(self, name: str) -> None:
            self._model_badge.setText(f"MODEL:  {name}  ▾")

    # ── Bottom tab bar (compact mode) ─────────────────────────────────────────

    class _BottomTabBar(QFrame):
        """Bottom navigation bar with Chat / Data / Settings tabs."""

        tab_selected = pyqtSignal(str)

        _TABS = [
            ("💬", "CHAT",     TAB_CHAT),
            ("⬖",  "DATA",     TAB_DATA),
            ("⚙",  "SETTINGS", TAB_SETTINGS),
        ]

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("bottomTabBar")
            self.setFixedHeight(60)
            self.setStyleSheet(
                f"QFrame#bottomTabBar {{"
                f"  background-color: {T.BG_CARD};"
                f"  border-top: 1px solid {T.BORDER};"
                f"}}"
            )

            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self._buttons: dict[str, QPushButton] = {}
            for icon, label, tab_id in self._TABS:
                btn = QPushButton(f"{icon}\n{label}")
                btn.setCheckable(True)
                btn.setObjectName("navBtn")
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: transparent; border: none; border-top: 2px solid transparent;"
                    f"  color: {T.TEXT_MUTED}; font-size: 10px; letter-spacing: 0.5px;"
                    f"  padding: 6px 4px 2px 4px;"
                    f"}}"
                    f"QPushButton:checked {{"
                    f"  color: {T.BLUE}; border-top: 2px solid {T.BLUE};"
                    f"}}"
                    f"QPushButton:hover {{ color: {T.TEXT_SECONDARY}; }}"
                )
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                btn.clicked.connect(lambda _, tid=tab_id: self._on_tab(tid))
                layout.addWidget(btn)
                self._buttons[tab_id] = btn

            self._select(TAB_CHAT)

        def _on_tab(self, tab_id: str) -> None:
            self._select(tab_id)
            self.tab_selected.emit(tab_id)

        def _select(self, tab_id: str) -> None:
            for tid, btn in self._buttons.items():
                btn.setChecked(tid == tab_id)

        def select(self, tab_id: str) -> None:
            self._select(tab_id)

    # ── Compact widget (wraps chat + status + settings in a tab layout) ────────

    class _CompactWidget(QWidget):
        """The full compact-mode content area (header + tabs + pages)."""

        expand_clicked = pyqtSignal()

        def __init__(
            self,
            settings_manager: Any = None,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._sm = settings_manager
            self._setup_ui()

        def _setup_ui(self) -> None:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # Header
            self._header = _CompactHeader()
            self._header.expand_clicked.connect(self.expand_clicked)
            layout.addWidget(self._header)

            # Stacked pages
            self._stack = QStackedWidget()
            layout.addWidget(self._stack, stretch=1)

            # Chat page
            from src.gui.chat_widget import ChatWidget
            self._chat = ChatWidget(self._sm)
            self._chat_idx = self._stack.addWidget(self._chat)

            # Status page
            from src.gui.status_widget import StatusWidget
            self._status = StatusWidget()
            self._status_idx = self._stack.addWidget(self._status)

            # Settings page
            from src.gui.npu_settings_widget import NPUSettingsWidget
            self._settings_page = NPUSettingsWidget(self._sm)
            self._settings_idx = self._stack.addWidget(self._settings_page)

            self._stack.setCurrentIndex(self._chat_idx)

            # Bottom tab bar
            self._tab_bar = _BottomTabBar()
            self._tab_bar.tab_selected.connect(self._on_tab)
            layout.addWidget(self._tab_bar)

        def _on_tab(self, tab_id: str) -> None:
            if tab_id == TAB_CHAT:
                self._stack.setCurrentIndex(self._chat_idx)
            elif tab_id == TAB_DATA:
                self._stack.setCurrentIndex(self._status_idx)
            elif tab_id == TAB_SETTINGS:
                self._stack.setCurrentIndex(self._settings_idx)

        # ── Public API ─────────────────────────────────────────────────────

        def chat_widget(self):
            return self._chat

        def status_widget(self):
            return self._status

        def set_model_name(self, name: str) -> None:
            self._header.set_model_name(name)

    # ── Main window ───────────────────────────────────────────────────────────

    class MainWindow(QMainWindow):
        """Neural Monolith main application window.

        Manages the compact overlay and full desktop modes.  Call
        :meth:`show_compact` or :meth:`show_full` to set the initial mode,
        or let the default (compact) apply.

        Parameters
        ----------
        settings_manager:
            The application :class:`~src.settings.SettingsManager`.
        ai_assistant:
            The application :class:`~src.ai_assistant.AIAssistant`.
        start_mode:
            ``"compact"`` (default) or ``"full"``.
        parent:
            Optional parent widget.
        """

        def __init__(
            self,
            settings_manager: Any = None,
            ai_assistant: Any = None,
            start_mode: str = MODE_COMPACT,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._sm = settings_manager
            self._ai = ai_assistant
            self._current_mode: str = ""

            self.setWindowTitle(APP_NAME)

            # Apply NPU dark stylesheet globally
            self.setStyleSheet(T.STYLESHEET)

            # Set taskbar / launcher icon on all DEs that support it
            self._setup_taskbar_icon()

            # Central stacked widget: index 0 = compact, 1 = full
            self._central = QStackedWidget()
            self.setCentralWidget(self._central)

            # Build compact widget
            self._compact_widget = _CompactWidget(settings_manager=settings_manager)
            self._compact_widget.expand_clicked.connect(self.show_full)
            self._central.addWidget(self._compact_widget)  # index 0

            # Build full window widget
            from src.gui.full_window import FullWindow
            self._full_widget = FullWindow(
                settings_manager=settings_manager,
                ai_assistant=ai_assistant,
            )
            self._full_widget.collapse_requested.connect(self.show_compact)
            self._central.addWidget(self._full_widget)  # index 1

            # Initial mode
            if start_mode == MODE_FULL:
                self.show_full()
            else:
                self.show_compact()

        # ── Mode switching ────────────────────────────────────────────────────

        def show_compact(self) -> None:
            """Switch to compact floating-overlay mode."""
            if self._current_mode == MODE_COMPACT:
                return
            self._current_mode = MODE_COMPACT
            self._central.setCurrentIndex(0)

            # FramelessWindowHint keeps the panel borderless; WindowStaysOnTopHint
            # keeps it above other windows.  Qt.Tool is intentionally NOT set here:
            # it would hide the window from the taskbar, but DEs that support
            # taskbar icons (GNOME, KDE, XFCE, etc.) should be able to show it.
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            )
            self.setFixedSize(420, 680)
            self._position_compact()
            self.show()
            logger.debug("Switched to compact mode")

        def show_full(self) -> None:
            """Switch to full desktop mode."""
            if self._current_mode == MODE_FULL:
                return
            self._current_mode = MODE_FULL
            self._central.setCurrentIndex(1)

            # Restore normal window flags
            self.setWindowFlags(Qt.Window)
            self.setMinimumSize(900, 620)
            self.setMaximumSize(16777215, 16777215)  # Qt's QWIDGETSIZE_MAX
            # Remove fixed size constraint from compact mode
            self.setFixedSize(QSize())
            self.resize(1100, 760)
            self._center_window()
            self.show()
            logger.debug("Switched to full mode")

        # ── Convenience access ────────────────────────────────────────────────

        def chat_widget(self):
            """Return the chat widget (accessible from both modes)."""
            return self._compact_widget.chat_widget()

        def status_widget(self):
            """Return the status widget."""
            return self._compact_widget.status_widget()

        def set_model_name(self, name: str) -> None:
            """Update the model name shown in the compact header."""
            self._compact_widget.set_model_name(name)

        # ── Compact drag support ──────────────────────────────────────────────

        def mousePressEvent(self, event) -> None:  # noqa: ANN001
            if self._current_mode == MODE_COMPACT and event.button() == Qt.LeftButton:
                self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()

        def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
            if (
                self._current_mode == MODE_COMPACT
                and event.buttons() == Qt.LeftButton
                and hasattr(self, "_drag_pos")
            ):
                self.move(event.globalPos() - self._drag_pos)
                event.accept()

        # ── Private helpers ───────────────────────────────────────────────────

        def _setup_taskbar_icon(self) -> None:
            """Build a programmatic app icon and register it with the DE.

            Uses a 64×64 dark-navy rounded square with the "✦" Neural Monolith
            glyph rendered in the application's accent green.  Sets both the
            QApplication-wide icon (picked up by all DEs via _NET_WM_ICON on
            X11 and xdg-toplevel-icon on Wayland) and the per-window icon.

            Also calls ``QApplication.setDesktopFileName`` so GNOME Shell and
            KDE Plasma can match the window to the Flatpak .desktop entry and
            display the correct launcher icon in the dock/taskbar.
            """
            try:
                from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap  # noqa: PLC0415

                px = QPixmap(64, 64)
                px.fill(QColor(0, 0, 0, 0))  # transparent background

                painter = QPainter(px)
                painter.setRenderHint(QPainter.Antialiasing)

                # Dark navy rounded-rect background
                painter.setBrush(QColor("#1a1c28"))
                painter.setPen(QColor("#2a2c3a"))
                painter.drawRoundedRect(2, 2, 60, 60, 12, 12)

                # Accent glyph
                painter.setPen(QColor("#00d4aa"))
                f = QFont()
                f.setPointSize(28)
                f.setBold(True)
                painter.setFont(f)
                from PyQt5.QtCore import Qt as _Qt  # noqa: PLC0415
                painter.drawText(px.rect(), _Qt.AlignCenter, "✦")
                painter.end()

                icon = QIcon(px)
                QApplication.setWindowIcon(icon)
                self.setWindowIcon(icon)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not set taskbar icon: %s", exc)

            # Wayland / GNOME Shell — link the window to the .desktop file so
            # the correct launcher icon appears in the dock/taskbar.
            try:
                QApplication.setDesktopFileName(
                    "io.github.robertbiv.LinuxAiNpuAssistant"
                )
            except AttributeError:
                pass  # Qt < 5.7

        def _position_compact(self) -> None:
            """Place the compact window in the bottom-right of the screen."""
            screen = QApplication.primaryScreen().availableGeometry()
            margin = 20
            self.move(
                screen.right()  - self.width()  - margin,
                screen.bottom() - self.height() - margin,
            )

        def _center_window(self) -> None:
            """Centre the full window on the primary screen."""
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(
                screen.center().x() - self.width()  // 2,
                screen.center().y() - self.height() // 2,
            )


def open_main_window(
    settings_manager: Any = None,
    ai_assistant: Any = None,
    start_mode: str = MODE_COMPACT,
) -> "MainWindow | None":
    """Create and show the Neural Monolith main window.

    Returns the :class:`MainWindow` instance (or ``None`` if PyQt5 is not
    installed).

    Parameters
    ----------
    settings_manager:
        Optional :class:`~src.settings.SettingsManager`.
    ai_assistant:
        Optional :class:`~src.ai_assistant.AIAssistant`.
    start_mode:
        ``"compact"`` (default) or ``"full"``.
    """
    if not _HAS_QT:
        logger.error("PyQt5 is required for the GUI. Install with: pip install PyQt5")
        return None

    win = MainWindow(
        settings_manager=settings_manager,
        ai_assistant=ai_assistant,
        start_mode=start_mode,
    )
    win.show()
    return win
