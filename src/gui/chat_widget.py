# SPDX-License-Identifier: GPL-3.0-or-later
"""Chat page widget — NPU-themed conversational interface.

Displays the conversation history as chat bubbles and provides a message
input area with attachment and send buttons.  Uses a custom message-bubble
widget that supports inline code-block rendering.

The widget emits ``message_submitted(str)`` when the user presses Send or
Enter so the parent can forward the text to the AI backend.

Usage
-----
::

    from src.gui.chat_widget import ChatWidget
    widget = ChatWidget(settings_manager, parent=main_window)
    widget.message_submitted.connect(on_user_message)
    widget.append_user_message("Hello!")
    widget.append_assistant_message("Hi there!", model_name="Llama-3-NPU-8B")
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtCore import Qt, pyqtSignal, QTimer
    from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QBrush, QPen
    from PyQt5.QtWidgets import (
        QFrame,
        QHBoxLayout,
        QLabel,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpacerItem,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    logger.warning("PyQt5 not installed — ChatWidget unavailable.")

if _HAS_QT:
    from src.gui import npu_theme as T

    # ── Code-block widget ─────────────────────────────────────────────────────

    class _CodeBlock(QFrame):
        """Dark terminal-style code block widget."""

        def __init__(self, code: str, label: str = "", parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("codeBlock")
            self.setStyleSheet(
                f"QFrame#codeBlock {{"
                f"  background-color: {T.BG_INPUT};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-radius: 8px;"
                f"}}"
            )

            layout = QVBoxLayout(self)
            layout.setContentsMargins(12, 8, 12, 8)
            layout.setSpacing(4)

            if label:
                header = QHBoxLayout()
                lbl = QLabel(label)
                lbl.setStyleSheet(f"color: {T.TEXT_CODE}; font-size: 11px; font-family: monospace;")
                header.addWidget(lbl)
                header.addStretch()
                layout.addLayout(header)

            text_widget = QLabel(code)
            text_widget.setWordWrap(True)
            text_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
            text_widget.setFont(QFont("Monospace", 10))
            text_widget.setStyleSheet(
                f"color: {T.TEXT_CODE};"
                f"background: transparent;"
                f"line-height: 1.4;"
            )
            layout.addWidget(text_widget)

    # ── Text segment helpers ──────────────────────────────────────────────────

    def _colorize_log_line(line: str) -> str:
        """Return HTML-coloured version of a log line."""
        if line.startswith("ERROR:"):
            return f'<span style="color:{T.TEXT_CODE_ERR}; font-weight:bold">ERROR:</span>' + line[6:]
        if line.startswith("INFO:"):
            return f'<span style="color:{T.TEXT_BLUE}; font-weight:bold">INFO:</span>' + line[5:]
        if line.startswith("ACTION:"):
            return f'<span style="color:{T.GREEN}; font-weight:bold">ACTION:</span>' + line[7:]
        return line

    # ── Message bubble ────────────────────────────────────────────────────────

    class _MessageBubble(QWidget):
        """Single chat message bubble (user or assistant)."""

        def __init__(
            self,
            content: str,
            role: str,                       # "user" | "assistant"
            model_name: str = "",
            timestamp: str = "",
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._role = role

            outer = QVBoxLayout(self)
            outer.setContentsMargins(8, 4, 8, 4)
            outer.setSpacing(4)

            if role == "assistant":
                self._build_assistant(outer, content, model_name, timestamp)
            else:
                self._build_user(outer, content, timestamp)

        # ── Assistant bubble ──────────────────────────────────────────────────

        def _build_assistant(
            self,
            outer: QVBoxLayout,
            content: str,
            model_name: str,
            timestamp: str,
        ) -> None:
            # Model name header
            if model_name:
                header_row = QHBoxLayout()
                icon_lbl = QLabel("✦")
                icon_lbl.setStyleSheet(
                    f"color: #ffffff; background-color: {T.GREEN};"
                    f"border-radius: 14px; padding: 2px 6px; font-size: 11px;"
                )
                icon_lbl.setFixedSize(28, 28)
                icon_lbl.setAlignment(Qt.AlignCenter)
                header_row.addWidget(icon_lbl)

                name_lbl = QLabel(model_name.upper())
                name_lbl.setStyleSheet(
                    f"color: {T.TEXT_GREEN}; font-size: 11px; font-weight: bold;"
                    f"letter-spacing: 1px; background: transparent;"
                )
                header_row.addWidget(name_lbl)
                header_row.addStretch()
                outer.addLayout(header_row)

            # Bubble with green left border
            bubble = QFrame()
            bubble.setObjectName("aiBubble")
            bubble.setStyleSheet(
                f"QFrame#aiBubble {{"
                f"  background-color: {T.BG_BUBBLE_AI};"
                f"  border: 1px solid {T.BORDER_GREEN};"
                f"  border-left: 3px solid {T.GREEN};"
                f"  border-radius: 10px;"
                f"}}"
            )
            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(14, 12, 14, 12)
            bubble_layout.setSpacing(8)

            self._add_content_blocks(bubble_layout, content)

            outer.addWidget(bubble)

            # Reaction row
            reaction_row = QHBoxLayout()
            reaction_row.setSpacing(6)
            for icon, tip in [("⧉", "Copy"), ("👍", "Like"), ("👎", "Dislike")]:
                btn = QToolButton()
                btn.setFocusPolicy(Qt.StrongFocus)
                btn.setText(icon)
                btn.setToolTip(tip)
                btn.setStyleSheet(
                    f"QToolButton {{"
                    f"  background: transparent; border: 1px solid transparent; border-radius: 4px;"
                    f"  color: {T.TEXT_MUTED}; font-size: 14px;"
                    f"  padding: 2px 4px;"
                    f"}}"
                    f"QToolButton:hover {{ color: {T.TEXT_SECONDARY}; }}"
                    f"QToolButton:focus {{ border-color: {T.BLUE}; }}"
                    f"QToolButton:focus {{ border-color: {T.BLUE}; }}"
                )
                if tip == "Copy":
                    btn.clicked.connect(lambda _, c=content: self._copy_to_clipboard(c))
                reaction_row.addWidget(btn)
            reaction_row.addStretch()
            outer.addLayout(reaction_row)

        # ── User bubble ───────────────────────────────────────────────────────

        def _build_user(
            self,
            outer: QVBoxLayout,
            content: str,
            timestamp: str,
        ) -> None:
            row = QHBoxLayout()
            row.addStretch()

            bubble = QFrame()
            bubble.setObjectName("userBubble")
            bubble.setStyleSheet(
                f"QFrame#userBubble {{"
                f"  background-color: {T.BG_BUBBLE_USER};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-radius: 14px;"
                f"  border-bottom-right-radius: 4px;"
                f"}}"
            )
            bubble.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)

            b_layout = QVBoxLayout(bubble)
            b_layout.setContentsMargins(16, 12, 16, 12)

            text_lbl = QLabel(content)
            text_lbl.setWordWrap(True)
            text_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            text_lbl.setMaximumWidth(440)
            text_lbl.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 14px; background: transparent;"
            )
            b_layout.addWidget(text_lbl)
            row.addWidget(bubble)
            outer.addLayout(row)

            # Timestamp
            if timestamp:
                ts_row = QHBoxLayout()
                ts_row.addStretch()
                ts_lbl = QLabel(timestamp + " · LOCALHOST")
                ts_lbl.setStyleSheet(
                    f"color: {T.TEXT_MUTED}; font-size: 10px; background: transparent;"
                )
                ts_row.addWidget(ts_lbl)
                outer.addLayout(ts_row)

        # ── Content block parser ───────────────────────────────────────────────

        def _add_content_blocks(self, layout: QVBoxLayout, content: str) -> None:
            """Split content into text and fenced code blocks and render each."""
            # Split on ``` fences
            parts = re.split(r"```(?:[^\n]*)?\n?", content)
            in_code = False
            for part in parts:
                part = part.rstrip("\n")
                if not part:
                    in_code = not in_code
                    continue
                if in_code:
                    layout.addWidget(_CodeBlock(part))
                else:
                    self._add_text_block(layout, part)
                in_code = not in_code

        def _add_text_block(self, layout: QVBoxLayout, text: str) -> None:
            """Render a text block, highlighting inline values (e.g. `142ms`)."""
            html = self._text_to_html(text)
            lbl = QLabel()
            lbl.setTextFormat(Qt.RichText)
            lbl.setText(html)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
            lbl.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 14px; background: transparent;"
                f"line-height: 1.5;"
            )
            layout.addWidget(lbl)

        @staticmethod
        def _text_to_html(text: str) -> str:
            """Convert plain text with backtick inline code to HTML spans."""
            # Escape HTML special chars first
            text = html.escape(text)
            # Inline code: `value`
            text = re.sub(
                r"`([^`]+)`",
                lambda m: (
                    f'<span style="color:{T.TEXT_BLUE}; background:{T.BLUE_DIM}; '
                    f'padding:1px 4px; border-radius:3px; font-family:monospace;">'
                    f"{m.group(1)}</span>"
                ),
                text,
            )
            # Bold **text**
            text = re.sub(
                r"\*\*([^*]+)\*\*",
                r"<b>\1</b>",
                text,
            )
            return text

        def _copy_to_clipboard(self, text: str) -> None:
            try:
                from PyQt5.QtWidgets import QApplication
                QApplication.clipboard().setText(text)
            except Exception:
                pass

    # ── Status pill ───────────────────────────────────────────────────────────

    class _StatusPill(QFrame):
        """Small status indicator pill (● NPU NEURAL CORE ONLINE)."""

        def __init__(
            self,
            text: str = "NPU NEURAL CORE ONLINE",
            online: bool = True,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self.setObjectName("statusPill")
            self.setStyleSheet(
                f"QFrame#statusPill {{"
                f"  background-color: {T.BG_CARD};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-radius: 16px;"
                f"}}"
            )
            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 6, 16, 6)
            layout.setSpacing(8)

            dot = QLabel("●")
            color = T.GREEN if online else T.RED
            dot.setStyleSheet(f"color: {color}; font-size: 14px; background: transparent;")
            layout.addWidget(dot)

            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 11px; "
                f"letter-spacing: 1px; background: transparent;"
            )
            layout.addWidget(lbl)

    # ── Chat page ─────────────────────────────────────────────────────────────

    class ChatWidget(QWidget):
        """Full chat page widget.

        Signals
        -------
        message_submitted(str):
            Emitted when the user sends a new message.
        """

        message_submitted = pyqtSignal(str)

        def __init__(
            self,
            settings_manager: Any = None,
            model_name: str = "Llama-3-NPU-8B",
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._settings = settings_manager
            self._model_name = model_name
            self._is_streaming = False
            self._last_screenshot: bytes | None = None
            # Optional override capture function (injected by tests or main app)
            self._screenshot_fn: "Any | None" = None

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # Status pill
            pill_row = QHBoxLayout()
            pill_row.setContentsMargins(12, 10, 12, 4)
            pill_row.addStretch()
            self._status_pill = _StatusPill()
            pill_row.addWidget(self._status_pill)
            pill_row.addStretch()
            layout.addLayout(pill_row)

            # Scroll area for messages
            self._scroll = QScrollArea()
            self._scroll.setWidgetResizable(True)
            self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            self._msg_container = QWidget()
            self._msg_layout = QVBoxLayout(self._msg_container)
            self._msg_layout.setContentsMargins(8, 8, 8, 8)
            self._msg_layout.setSpacing(12)
            self._msg_layout.addStretch()

            self._scroll.setWidget(self._msg_container)
            layout.addWidget(self._scroll, stretch=1)

            # Input area
            layout.addWidget(self._build_input_area())

        def _build_input_area(self) -> QWidget:
            container = QFrame()
            container.setObjectName("inputArea")
            container.setStyleSheet(
                f"QFrame#inputArea {{"
                f"  background-color: {T.BG_CARD};"
                f"  border-top: 1px solid {T.BORDER};"
                f"}}"
            )
            row = QHBoxLayout(container)
            row.setContentsMargins(12, 10, 12, 10)
            row.setSpacing(8)

            attach_btn = QToolButton()
            attach_btn.setFocusPolicy(Qt.StrongFocus)
            attach_btn.setText("⚇")
            attach_btn.setToolTip("Attach file")
            attach_btn.setFixedSize(36, 36)
            attach_btn.setStyleSheet(
                f"QToolButton {{"
                f"  background: transparent; border: 1px solid transparent; border-radius: 4px;"
                f"  color: {T.TEXT_SECONDARY}; font-size: 18px;"
                f"}}"
                f"QToolButton:hover {{ color: {T.TEXT_PRIMARY}; }}"
                f"QToolButton:focus {{ border-color: {T.BLUE}; }}"
                f"QToolButton:focus {{ border-color: {T.BLUE}; }}"
            )
            row.addWidget(attach_btn)

            self._input = QPlainTextEdit()
            self._input.setPlaceholderText("Message Neural Assistant…")
            self._input.setFixedHeight(42)
            self._input.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._input.setStyleSheet(
                f"QPlainTextEdit {{"
                f"  background-color: {T.BG_INPUT};"
                f"  color: {T.TEXT_PRIMARY};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-radius: 10px;"
                f"  padding: 8px 12px;"
                f"  font-size: 14px;"
                f"}}"
                f"QPlainTextEdit:focus {{ border-color: {T.BLUE}; }}"
            )
            self._input.installEventFilter(self)
            row.addWidget(self._input, stretch=1)

            self._send_btn = QPushButton("↑")
            self._send_btn.setObjectName("sendBtn")
            self._send_btn.setFixedSize(38, 38)
            self._send_btn.setToolTip("Send message (Enter)")
            self._send_btn.clicked.connect(self._on_send)
            row.addWidget(self._send_btn)

            return container

        # ── Qt event filter for Enter key ─────────────────────────────────────

        def eventFilter(self, obj: object, event: object) -> bool:
            from PyQt5.QtCore import QEvent
            if obj is self._input and event.type() == QEvent.KeyPress:
                from PyQt5.QtCore import Qt as _Qt
                if event.key() == _Qt.Key_Return and not (event.modifiers() & _Qt.ShiftModifier):
                    self._on_send()
                    return True
            return super().eventFilter(obj, event)

        # ── Public API ────────────────────────────────────────────────────────

        def set_model_name(self, name: str) -> None:
            """Update displayed model name."""
            self._model_name = name

        def set_status(self, text: str, online: bool = True) -> None:
            """Update the status pill text and colour."""
            self._status_pill.deleteLater()
            new_pill = _StatusPill(text, online)
            # Re-insert — find the pill_row index
            # Easiest approach: recreate pill row contents
            self._status_pill = new_pill

        def append_user_message(self, text: str) -> None:
            """Add a user chat bubble to the conversation."""
            ts = datetime.now().strftime("%H:%M")
            bubble = _MessageBubble(text, role="user", timestamp=ts, parent=self._msg_container)
            self._insert_bubble(bubble)

        def append_assistant_message(
            self,
            text: str,
            model_name: str = "",
        ) -> None:
            """Add an assistant chat bubble to the conversation."""
            name = model_name or self._model_name
            bubble = _MessageBubble(
                text,
                role="assistant",
                model_name=name,
                parent=self._msg_container,
            )
            self._insert_bubble(bubble)

        def append_assistant_token(self, token: str) -> None:
            """Append a streaming token to the last assistant bubble.

            If no assistant bubble exists yet a new one is created.
            """
            layout = self._msg_layout
            count = layout.count()
            # Find last _MessageBubble with role == "assistant"
            for i in range(count - 1, -1, -1):
                item = layout.itemAt(i)
                if item and isinstance(item.widget(), _MessageBubble):
                    bubble = item.widget()
                    if bubble._role == "assistant":
                        # Accumulate in bubble — simplest approach: rebuild
                        # For streaming we keep a separate accumulator
                        break
            else:
                self.append_assistant_message(token)
                return

        def set_streaming(self, streaming: bool) -> None:
            """Enable / disable the send button during streaming."""
            self._is_streaming = streaming
            self._send_btn.setEnabled(not streaming)
            self._send_btn.setText("⏹" if streaming else "↑")

        def clear_conversation(self) -> None:
            """Remove all message bubbles."""
            layout = self._msg_layout
            while layout.count() > 1:  # keep the stretch at index 0
                item = layout.takeAt(1)
                if item and item.widget():
                    item.widget().deleteLater()

        # ── Private helpers ───────────────────────────────────────────────────

        def _insert_bubble(self, bubble: _MessageBubble) -> None:
            # Insert before the trailing stretch
            count = self._msg_layout.count()
            self._msg_layout.insertWidget(count, bubble)
            QTimer.singleShot(50, self._scroll_to_bottom)

        def _scroll_to_bottom(self) -> None:
            vsb = self._scroll.verticalScrollBar()
            vsb.setValue(vsb.maximum())

        def _on_send(self) -> None:
            text = self._input.toPlainText().strip()
            if not text or self._is_streaming:
                return
            self._input.clear()

            # Take screenshot BEFORE the user bubble appears so the capture
            # shows what was on screen when the question was asked.
            auto_screen = (
                self._settings.get("ui.auto_send_screen", False)
                if self._settings is not None
                else False
            )
            if auto_screen:
                self._last_screenshot = self._take_screenshot()
            else:
                self._last_screenshot = None

            self.append_user_message(text)
            self.message_submitted.emit(text)

        # ── Screenshot helpers ────────────────────────────────────────────────

        def set_screenshot_fn(self, fn: "Any | None") -> None:
            """Inject a custom screenshot callable (for testing or custom UI).

            Parameters
            ----------
            fn:
                ``Callable[[], bytes | None]`` — called instead of the default
                opacity-trick capture when ``ui.auto_send_screen`` is True.
                Pass ``None`` to restore the default behaviour.
            """
            self._screenshot_fn = fn

        def _take_screenshot(self) -> bytes | None:
            """Capture the screen using the opacity-fade technique.

            The application window's opacity is set to 0 (transparent) before
            the capture so it does not appear in the screenshot, then restored
            to 1 immediately.  This avoids any visible flicker because the
            window is never hidden — it is simply transparent for one frame.

            Returns raw JPEG bytes, or ``None`` on failure.
            """
            if self._screenshot_fn is not None:
                try:
                    return self._screenshot_fn()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Custom screenshot fn failed: %s", exc)
                    return None

            try:
                from PyQt5.QtWidgets import QApplication  # noqa: PLC0415
                win = self.window()
                win.setWindowOpacity(0.0)
                QApplication.processEvents()

                from src.tools.screenshot_tool import ScreenshotTool  # noqa: PLC0415
                data = ScreenshotTool._capture(monitor=0, quality=75)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Screenshot failed: %s", exc)
                data = None
            finally:
                try:
                    win.setWindowOpacity(1.0)
                    QApplication.processEvents()
                except Exception:  # noqa: BLE001
                    pass
            return data
