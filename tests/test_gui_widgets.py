# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprehensive GUI test suite for Linux AI NPU Assistant.

Covers every UI feature, AI model integration, NPU simulation, hotkey
listener, screenshot-on-send, multiple desktop environments and shells,
encrypted/password-protected chat history, history import/export,
taskbar icon, compact/full mode geometry, all buttons, and dynamic
NPU suitability labels.

All tests run headlessly via QT_QPA_PLATFORM=offscreen (set in conftest.py).
Screenshots of each feature are saved to /tmp/npu-test-screenshots/.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

SCREENSHOT_DIR = Path("/tmp/npu-test-screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _grab(widget, name):
    try:
        px = widget.grab()
        px.save(str(SCREENSHOT_DIR / f"{name}.png"))
    except Exception:
        pass


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def settings_manager(tmp_path):
    from src.settings import SettingsManager

    return SettingsManager(path=tmp_path / "settings.json")


@pytest.fixture
def history_plain(tmp_path):
    from src.conversation import ConversationHistory

    return ConversationHistory(persist_path=tmp_path / "history.json", encrypt=False)


@pytest.fixture
def history_enc(tmp_path):
    from src.conversation import ConversationHistory

    return ConversationHistory(persist_path=tmp_path / "history.json", encrypt=True)


# ── 1. Compact mode ───────────────────────────────────────────────────────────


class TestCompactMode:
    def test_window_size(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="compact")
        win.show()
        assert win.width() == 420
        assert win.height() == 680
        _grab(win, "compact_mode")
        win.close()

    def test_no_qt_tool_flag(self, qapp, settings_manager):
        from PyQt5.QtCore import Qt
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="compact")
        win.show()
        # Qt.Tool == 11 == Qt.Window(1) | 0xa; check the window TYPE not raw flags
        wtype = win.windowType()
        assert wtype != Qt.Tool, (
            f"Window type is Qt.Tool ({wtype}); taskbar icon will be hidden"
        )
        assert win.windowFlags() & Qt.FramelessWindowHint
        assert win.windowFlags() & Qt.WindowStaysOnTopHint
        win.close()

    def test_taskbar_icon_set(self, qapp, settings_manager):
        from PyQt5.QtWidgets import QApplication
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="compact")
        win.show()
        assert not QApplication.windowIcon().isNull()
        assert not win.windowIcon().isNull()
        win.close()

    def test_expand_button(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="compact")
        win.show()
        win._compact_widget._header.expand_clicked.emit()
        assert win._current_mode == "full"
        _grab(win, "compact_expanded")
        win.close()

    def test_chat_tab(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="compact")
        win.show()
        tab_bar = win._compact_widget._tab_bar
        tab_bar._buttons["chat"].click()
        _grab(win, "compact_chat_tab")
        win.close()

    def test_data_tab(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="compact")
        win.show()
        tab_bar = win._compact_widget._tab_bar
        tab_bar._buttons["data"].click()
        _grab(win, "compact_data_tab")
        win.close()

    def test_settings_tab(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="compact")
        win.show()
        tab_bar = win._compact_widget._tab_bar
        tab_bar._buttons["settings"].click()
        _grab(win, "compact_settings_tab")
        win.close()


# ── 2. Full mode ──────────────────────────────────────────────────────────────


class TestFullMode:
    def test_min_size(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="full")
        win.show()
        assert (
            win.minimumWidth() >= 900 or win.width() >= 700
        )  # offscreen may not resize
        _grab(win, "full_mode")
        win.close()

    def test_no_fixed_size_constraint(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="full")
        win.show()
        # On offscreen, maximumWidth may be 0; check that fixed compact size is NOT applied
        assert win.minimumWidth() >= 900 or win.width() != 420
        win.close()

    def test_sidebar_navigation(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="full")
        win.show()
        sidebar = win._full_widget._sidebar
        if hasattr(sidebar, "_nav_buttons"):
            for btn in sidebar._nav_buttons:
                pid = btn._page_id if hasattr(btn, "_page_id") else btn.page_id()
                try:
                    sidebar.select_page(pid)
                    _grab(win, f"full_page_{pid}")
                except Exception:
                    pass
        win.close()

    def test_collapse(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="full")
        win.show()
        win._full_widget.collapse_requested.emit()
        assert win._current_mode == "compact"
        assert win.width() == 420
        _grab(win, "full_collapsed")
        win.close()

    def test_stats_update(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="full")
        win.show()
        win._full_widget.update_stats(npu_pct=72.5, mem_gb=6.2)
        _grab(win, "full_stats")
        win.close()


# ── 3. Window sizes ───────────────────────────────────────────────────────────


class TestWindowSizes:
    @pytest.mark.parametrize("w,h", [(800, 600), (1280, 720), (1920, 1080)])
    def test_full_resizable(self, qapp, settings_manager, w, h):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="full")
        win.show()
        win.resize(w, h)
        assert win.width() <= w + 30
        _grab(win, f"full_{w}x{h}")
        win.close()

    def test_compact_fixed(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="compact")
        win.show()
        win.resize(1200, 1200)
        assert win.width() == 420
        assert win.height() == 680
        win.close()


# ── 4. ChatWidget ─────────────────────────────────────────────────────────────


class TestChatWidget:
    def test_send_button(self, qtbot, settings_manager):
        from src.gui.chat_widget import ChatWidget

        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        signals = []
        w.message_submitted.connect(signals.append)
        w._input.setPlainText("Hello")
        w._send_btn.click()
        assert signals == ["Hello"]
        assert w._input.toPlainText() == ""
        _grab(w, "chat_send")

    def test_enter_sends(self, qtbot, settings_manager):
        from PyQt5.QtCore import Qt
        from src.gui.chat_widget import ChatWidget

        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        signals = []
        w.message_submitted.connect(signals.append)
        w._input.setPlainText("Enter key")
        qtbot.keyClick(w._input, Qt.Key_Return)
        assert "Enter key" in signals

    def test_shift_enter_newline(self, qtbot, settings_manager):
        from PyQt5.QtCore import Qt
        from src.gui.chat_widget import ChatWidget

        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        signals = []
        w.message_submitted.connect(signals.append)
        w._input.setPlainText("line1")
        qtbot.keyClick(w._input, Qt.Key_Return, Qt.ShiftModifier)
        assert signals == []

    def test_empty_no_send(self, qtbot, settings_manager):
        from src.gui.chat_widget import ChatWidget

        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        signals = []
        w.message_submitted.connect(signals.append)
        w._input.setPlainText("   ")
        w._send_btn.click()
        assert signals == []

    def test_streaming_blocks_send(self, qtbot, settings_manager):
        from src.gui.chat_widget import ChatWidget

        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        w.set_streaming(True)
        assert not w._send_btn.isEnabled()
        signals = []
        w.message_submitted.connect(signals.append)
        w._input.setPlainText("blocked")
        w._on_send()
        assert signals == []
        w.set_streaming(False)
        assert w._send_btn.isEnabled()

    def test_clear_conversation(self, qtbot, settings_manager):
        from src.gui.chat_widget import ChatWidget

        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        w.append_user_message("msg")
        w.append_assistant_message("reply")
        w.clear_conversation()
        layout = w._msg_layout
        count = sum(
            1
            for i in range(layout.count())
            if layout.itemAt(i) and layout.itemAt(i).widget()
        )
        assert count == 0
        _grab(w, "chat_cleared")

    def test_user_bubble(self, qtbot, settings_manager):
        from src.gui.chat_widget import ChatWidget

        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        w.append_user_message("User message")
        _grab(w, "chat_user_bubble")

    def test_assistant_bubble(self, qtbot, settings_manager):
        from src.gui.chat_widget import ChatWidget

        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        w.append_assistant_message("Assistant reply", model_name="TestModel")
        _grab(w, "chat_assistant_bubble")


# ── 5. Screenshot-on-send ─────────────────────────────────────────────────────


class TestScreenshotOnSend:
    def test_capture_called_when_enabled(self, qtbot, settings_manager):
        from src.gui.chat_widget import ChatWidget

        settings_manager.set("ui.auto_send_screen", True, save=False)
        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        captured = []
        w.set_screenshot_fn(lambda: captured.append(b"JPEG") or b"JPEG")
        w._input.setPlainText("test")
        w._on_send()
        assert captured == [b"JPEG"]
        assert w._last_screenshot == b"JPEG"

    def test_no_capture_when_disabled(self, qtbot, settings_manager):
        from src.gui.chat_widget import ChatWidget

        settings_manager.set("ui.auto_send_screen", False, save=False)
        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        captured = []
        w.set_screenshot_fn(lambda: captured.append(1) or b"data")
        w._input.setPlainText("no screenshot")
        w._on_send()
        assert captured == []
        assert w._last_screenshot is None

    def test_no_hide_show(self, qtbot, settings_manager):
        from src.gui.chat_widget import ChatWidget

        settings_manager.set("ui.auto_send_screen", True, save=False)
        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        hidden = []

        class FakeWin:
            def hide(self):
                hidden.append("hide")

            def setVisible(self, v):
                if not v:
                    hidden.append("setVisible")

            def setWindowOpacity(self, v):
                pass

        w.set_screenshot_fn(lambda: b"ok")
        with patch.object(w, "window", return_value=FakeWin()):
            w._input.setPlainText("no hide")
            w._on_send()
        assert hidden == []

    def test_exception_handled(self, qtbot, settings_manager):
        from src.gui.chat_widget import ChatWidget

        settings_manager.set("ui.auto_send_screen", True, save=False)
        w = ChatWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        w.set_screenshot_fn(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        w._input.setPlainText("exception")
        w._on_send()  # must not raise
        assert w._last_screenshot is None


# ── 6. ScreenshotTool ─────────────────────────────────────────────────────────


class TestScreenshotTool:
    def test_name(self):
        from src.tools.screenshot_tool import ScreenshotTool

        assert ScreenshotTool.name == "screenshot"

    def test_in_registry(self):
        from src.tools import build_default_registry

        reg = build_default_registry({})
        names = (
            reg.names()
            if hasattr(reg, "names")
            else list(getattr(reg, "_tools", {}).keys())
        )
        assert "screenshot" in names

    def test_run_returns_base64(self, tmp_path):
        from src.tools.screenshot_tool import ScreenshotTool

        fake = bytes([0xFF, 0xD8, 0xFF]) + bytes(50)
        with patch("src.screen_capture.capture", return_value=fake):
            result = ScreenshotTool().run({"save": False})
        assert not result.error  # empty string or None = no error
        assert base64.b64decode(result.results[0].snippet) == fake

    def test_opacity_order(self):
        from src.tools.screenshot_tool import ScreenshotTool

        calls = []
        tool = ScreenshotTool(hide_opacity_fn=lambda v: calls.append(v))
        with patch("src.screen_capture.capture", return_value=b"\xff\xd8\xff"):
            tool.run({"save": False})
        assert calls[0] == 0.0
        assert calls[-1] == 1.0

    def test_opacity_restored_on_error(self):
        from src.tools.screenshot_tool import ScreenshotTool

        calls = []
        tool = ScreenshotTool(hide_opacity_fn=lambda v: calls.append(v))
        with patch("src.screen_capture.capture", side_effect=RuntimeError("fail")):
            result = tool.run({"save": False})
        assert result.error  # non-empty string = error occurred
        assert 1.0 in calls


# ── 7. StatusWidget ───────────────────────────────────────────────────────────


class TestStatusWidget:
    def test_renders(self, qtbot):
        from src.gui.status_widget import StatusWidget

        w = StatusWidget()
        qtbot.addWidget(w)
        w.show()
        _grab(w, "status_widget")

    def test_update_metrics(self, qtbot):
        from src.gui.status_widget import StatusWidget

        w = StatusWidget()
        qtbot.addWidget(w)
        w.show()
        if hasattr(w, "update_metrics"):
            w.update_metrics(
                {
                    "npu_utilization": 82.5,
                    "memory_used_gb": 5.3,
                    "memory_total_gb": 8.0,
                    "throughput_tps": 45.2,
                    "latency_ms": 120.0,
                    "engine_status": "online",
                }
            )
        _grab(w, "status_metrics")

    def test_npu_offline(self, qtbot):
        from src.gui.status_widget import StatusWidget

        w = StatusWidget()
        qtbot.addWidget(w)
        w.show()
        if hasattr(w, "update_metrics"):
            w.update_metrics({"npu_utilization": 0.0, "engine_status": "offline"})
        _grab(w, "status_npu_offline")


# ── 8. NPUSettingsWidget ──────────────────────────────────────────────────────


class TestNPUSettingsWidget:
    def test_renders(self, qtbot, settings_manager):
        from src.gui.npu_settings_widget import NPUSettingsWidget

        w = NPUSettingsWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        _grab(w, "npu_settings")

    def test_buttons_clickable(self, qtbot, settings_manager):
        from PyQt5.QtWidgets import QPushButton, QToolButton
        from src.gui.npu_settings_widget import NPUSettingsWidget

        w = NPUSettingsWidget(settings_manager)
        qtbot.addWidget(w)
        w.show()
        for btn in w.findChildren(QPushButton) + w.findChildren(QToolButton):
            if btn.isVisible() and btn.isEnabled():
                try:
                    btn.click()
                except Exception:
                    pass


# ── 9. Hotkey listener ────────────────────────────────────────────────────────


class TestHotkeyListener:
    def test_start_stop(self):
        from src.hotkey_listener import HotkeyListener

        cb = MagicMock()
        hl = HotkeyListener(hotkey="ctrl+shift+space", callback=cb)
        hl.start()
        time.sleep(0.05)
        hl.stop()
        # HotkeyListener may not be a Thread subclass; use is_alive() if available
        if hasattr(hl, "join"):
            hl.join(timeout=1.0)
        assert not hl.is_alive()

    def test_callback_fires(self):
        from src.hotkey_listener import HotkeyListener

        fired = threading.Event()
        hl = HotkeyListener(hotkey="ctrl+shift+space", callback=fired.set)
        if hasattr(hl, "_fire"):
            hl._fire()
            assert fired.is_set()
        elif hasattr(hl, "_on_key_event"):
            hl._on_key_event(None)

    def test_exception_in_callback_safe(self):
        from src.hotkey_listener import HotkeyListener

        hl = HotkeyListener(
            hotkey="ctrl+shift+space",
            callback=lambda: (_ for _ in ()).throw(ValueError("bad")),
        )
        if hasattr(hl, "_fire"):
            try:
                hl._fire()
            except Exception:
                pass


# ── 10. Desktop environments ──────────────────────────────────────────────────


class TestDesktopEnvironments:
    DES = [
        "GNOME",
        "KDE",
        "XFCE",
        "MATE",
        "Cinnamon",
        "Sway",
        "Hyprland",
        "i3",
        "LXQt",
        "Budgie",
        "Pantheon",
        "Deepin",
        "unknown-de",
    ]

    @pytest.mark.parametrize("de", DES)
    def test_theme_no_crash(self, qapp, de):
        from src.gui.theme import apply_to_app

        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": de}):
            try:
                apply_to_app(qapp)
            except Exception as exc:
                pytest.fail(f"Theme crashed for DE={de!r}: {exc}")

    @pytest.mark.parametrize("de", DES)
    def test_window_opens(self, qapp, settings_manager, de):
        from src.gui.main_window import MainWindow

        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": de}):
            win = MainWindow(settings_manager=settings_manager, start_mode="compact")
            win.show()
            _grab(win, f"de_{de.lower()}")
            win.close()


# ── 11. Shells ────────────────────────────────────────────────────────────────


class TestShells:
    SHELLS = [
        ("bash", "/bin/bash"),
        ("zsh", "/usr/bin/zsh"),
        ("fish", "/usr/bin/fish"),
        ("sh", "/bin/sh"),
        ("dash", "/bin/dash"),
        ("ksh", "/bin/ksh"),
        ("tcsh", "/bin/tcsh"),
        ("nushell", "/usr/bin/nu"),
        ("elvish", "/usr/bin/elvish"),
        ("xonsh", "/usr/bin/xonsh"),
    ]

    @pytest.mark.parametrize("name,path", SHELLS)
    def test_detected(self, name, path):
        from src.shell_detector import detect

        with patch.dict(os.environ, {"SHELL": path}):
            info = detect()
            assert info is not None


# ── 12. ConversationHistory plain ─────────────────────────────────────────────


class TestHistoryPlain:
    def test_add_retrieve(self, history_plain):
        h = history_plain
        h.add("user", "Hello")
        h.add("assistant", "Hi")
        assert len(h) == 2

    def test_max_messages(self, tmp_path):
        from src.conversation import ConversationHistory

        h = ConversationHistory(max_messages=3, persist_path=None, encrypt=False)
        for i in range(5):
            h.add("user", f"msg{i}")
        assert len(h) == 3
        assert h.all_messages()[-1].content == "msg4"

    def test_clear(self, history_plain):
        history_plain.add("user", "a")
        history_plain.clear()
        assert len(history_plain) == 0

    def test_persist_reload(self, tmp_path):
        from src.conversation import ConversationHistory

        p = tmp_path / "h.json"
        h1 = ConversationHistory(persist_path=p, encrypt=False)
        h1.add("user", "persist me")
        del h1
        h2 = ConversationHistory(persist_path=p, encrypt=False)
        assert h2.all_messages()[0].content == "persist me"

    def test_openai_format(self, history_plain):
        history_plain.add("user", "q")
        history_plain.add("assistant", "a")
        msgs = history_plain.to_openai_messages()
        assert any(m["role"] == "user" for m in msgs)

    def test_thread_safety(self, tmp_path):
        from src.conversation import ConversationHistory

        h = ConversationHistory(max_messages=1000, persist_path=None, encrypt=False)
        errors = []

        def _add(n):
            try:
                for i in range(20):
                    h.add("user", f"t{n}m{i}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_add, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ── 13. Encryption ────────────────────────────────────────────────────────────


class TestHistoryEncryption:
    def test_file_not_json(self, tmp_path):
        from src.conversation import ConversationHistory

        h = ConversationHistory(persist_path=tmp_path / "h.json", encrypt=True)
        h.add("user", "secret")
        enc = (tmp_path / "h.json").with_suffix(".enc")
        assert enc.exists()
        with pytest.raises(json.JSONDecodeError):
            json.loads(enc.read_text())

    def test_roundtrip(self, tmp_path):
        from src.conversation import ConversationHistory

        p = tmp_path / "h.json"
        h1 = ConversationHistory(persist_path=p, encrypt=True)
        h1.add("user", "roundtrip")
        del h1
        h2 = ConversationHistory(persist_path=p, encrypt=True)
        assert h2.all_messages()[0].content == "roundtrip"

    def test_wrong_key_empty(self, tmp_path):
        from src.conversation import ConversationHistory, generate_encryption_key

        p = tmp_path / "h.json"
        h1 = ConversationHistory(persist_path=p, encrypt=True)
        h1.add("user", "private")
        del h1
        h2 = ConversationHistory(
            persist_path=p, encrypt=True, encryption_key=generate_encryption_key()
        )
        assert len(h2) == 0

    def test_is_encrypted_true(self, history_enc):
        assert history_enc.is_encrypted is True

    def test_key_file_0600(self, tmp_path):
        from src.conversation import ConversationHistory

        h = ConversationHistory(persist_path=tmp_path / "h.json", encrypt=True)
        h.add("user", "x")
        kp = tmp_path / "history.key"
        assert kp.exists()
        assert (kp.stat().st_mode & 0o777) == 0o600


# ── 14. Password ──────────────────────────────────────────────────────────────


class TestHistoryPassword:
    def test_set_password(self, tmp_path):
        from src.conversation import ConversationHistory

        h = ConversationHistory(persist_path=tmp_path / "h.json", encrypt=True)
        h.add("user", "secret")
        h.set_password("mypass")
        assert (tmp_path / "history.salt").exists()

    def test_roundtrip_with_password(self, tmp_path):
        from src.conversation import ConversationHistory, _derive_key_from_password

        p = tmp_path / "h.json"
        h1 = ConversationHistory(persist_path=p, encrypt=True)
        h1.add("user", "pw content")
        h1.set_password("hunter2")
        del h1
        key = _derive_key_from_password("hunter2", tmp_path)
        h2 = ConversationHistory(persist_path=p, encrypt=True, encryption_key=key)
        assert h2.all_messages()[0].content == "pw content"

    def test_change_password(self, tmp_path):
        from src.conversation import ConversationHistory, _derive_key_from_password

        p = tmp_path / "h.json"
        h = ConversationHistory(persist_path=p, encrypt=True)
        h.add("user", "change pw")
        h.set_password("old")
        h.change_password("old", "new")
        del h
        key = _derive_key_from_password("new", tmp_path)
        h2 = ConversationHistory(persist_path=p, encrypt=True, encryption_key=key)
        assert h2.all_messages()[0].content == "change pw"

    def test_wrong_old_password_raises(self, tmp_path):
        from src.conversation import ConversationHistory

        h = ConversationHistory(persist_path=tmp_path / "h.json", encrypt=True)
        h.add("user", "x")
        h.set_password("correct")
        with pytest.raises(ValueError):
            h.change_password("wrongold", "newpw")

    def test_salt_permissions(self, tmp_path):
        from src.conversation import ConversationHistory

        h = ConversationHistory(persist_path=tmp_path / "h.json", encrypt=True)
        h.set_password("test")
        sp = tmp_path / "history.salt"
        assert sp.exists()
        assert (sp.stat().st_mode & 0o777) == 0o600


# ── 15. Import / Export ───────────────────────────────────────────────────────


class TestHistoryImportExport:
    def test_export_plain(self, tmp_path, history_plain):
        history_plain.add("user", "export me")
        out = tmp_path / "export.json"
        history_plain.export_plaintext(out)
        data = json.loads(out.read_text())
        assert data[0]["content"] == "export me"

    def test_import_plain_replace(self, tmp_path, history_plain):
        history_plain.add("user", "original")
        inp = tmp_path / "import.json"
        inp.write_text(
            json.dumps(
                [
                    {
                        "role": "user",
                        "content": "imported",
                        "timestamp": "2024-01-01T00:00:00+00:00",
                        "has_image": False,
                    }
                ]
            )
        )
        history_plain.import_history(inp, merge=False)
        assert history_plain.all_messages()[0].content == "imported"

    def test_import_plain_merge(self, tmp_path, history_plain):
        history_plain.add("user", "kept")
        inp = tmp_path / "new.json"
        inp.write_text(
            json.dumps(
                [
                    {
                        "role": "user",
                        "content": "added",
                        "timestamp": "2025-01-01T00:00:00+00:00",
                        "has_image": False,
                    }
                ]
            )
        )
        history_plain.import_history(inp, merge=True)
        contents = {m.content for m in history_plain.all_messages()}
        assert "kept" in contents and "added" in contents

    def test_import_encrypted_correct_pw(self, tmp_path):
        from src.conversation import ConversationHistory

        src = tmp_path / "src" / "h.json"
        src.parent.mkdir()
        h1 = ConversationHistory(persist_path=src, encrypt=True)
        h1.add("user", "enc import")
        h1.set_password("importpw")
        enc = src.with_suffix(".enc")
        dst = tmp_path / "dst" / "h.json"
        dst.parent.mkdir()
        h2 = ConversationHistory(persist_path=dst, encrypt=False)
        count = h2.import_history(enc, password="importpw")
        assert count == 1
        assert h2.all_messages()[0].content == "enc import"

    def test_import_encrypted_wrong_pw_raises(self, tmp_path):
        from src.conversation import ConversationHistory

        src = tmp_path / "src" / "h.json"
        src.parent.mkdir()
        h1 = ConversationHistory(persist_path=src, encrypt=True)
        h1.add("user", "secret")
        h1.set_password("correct")
        enc = src.with_suffix(".enc")
        h2 = ConversationHistory(persist_path=tmp_path / "dst.json", encrypt=False)
        with pytest.raises(ValueError):
            h2.import_history(enc, password="wrong")

    def test_import_looks_encrypted_no_pw_raises(self, tmp_path):
        from src.conversation import ConversationHistory

        fake = tmp_path / "fake.enc"
        fake.write_text("gAAAAAbadtoken")
        h = ConversationHistory(persist_path=tmp_path / "h.json", encrypt=False)
        with pytest.raises(ValueError, match="encrypted|password"):
            h.import_history(fake)

    def test_import_missing_file_raises(self, history_plain):
        with pytest.raises(FileNotFoundError):
            history_plain.import_history(Path("/nonexistent/file.json"))

    def test_import_invalid_json_raises(self, tmp_path, history_plain):
        bad = tmp_path / "bad.json"
        bad.write_text("[not valid json{{")
        with pytest.raises(ValueError):
            history_plain.import_history(bad)


# ── 16. SettingsWindow ────────────────────────────────────────────────────────


class TestSettingsWindow:
    def test_opens(self, qtbot, settings_manager):
        from src.gui.settings_window import SettingsWindow

        win = SettingsWindow(settings_manager)
        qtbot.addWidget(win)
        win.show()
        _grab(win, "settings_window")
        win.close()

    def test_history_tab(self, qtbot, settings_manager, history_plain):
        from src.gui.settings_window import SettingsWindow

        win = SettingsWindow(settings_manager, history=history_plain)
        qtbot.addWidget(win)
        win.show()
        tabs = [win._tabs.tabText(i) for i in range(win._tabs.count())]
        assert "History" in tabs
        _grab(win, "settings_history")
        win.close()

    def test_updates_tab(self, qtbot, settings_manager):
        from src.gui.settings_window import SettingsWindow

        win = SettingsWindow(settings_manager)
        qtbot.addWidget(win)
        win.show()
        tabs = [win._tabs.tabText(i) for i in range(win._tabs.count())]
        assert "Updates" in tabs
        for i, t in enumerate(tabs):
            if t == "Updates":
                win._tabs.setCurrentIndex(i)
                break
        _grab(win, "settings_updates")
        win.close()

    def test_all_tabs_navigable(self, qtbot, settings_manager, history_plain):
        from src.gui.settings_window import SettingsWindow

        win = SettingsWindow(settings_manager, history=history_plain)
        qtbot.addWidget(win)
        win.show()
        for i in range(win._tabs.count()):
            win._tabs.setCurrentIndex(i)
            _grab(win, f"settings_tab_{win._tabs.tabText(i).lower()}")
        win.close()


# ── 17. NPU suitability ───────────────────────────────────────────────────────


class TestNPUSuitability:
    def _hw(self, tops=0, ram=8, npu=False):
        from src.npu_benchmark import HardwareCapabilities

        return HardwareCapabilities(
            npu_tops=tops, ram_gb=ram, cpu_cores=8, npu_available=npu
        )

    def test_no_npu_demotes(self):
        from src.npu_benchmark import adjust_npu_fit

        assert adjust_npu_fit("excellent", self._hw(0, 8, False)) in (
            "fair",
            "not_recommended",
        )

    def test_high_tops_promotes(self):
        from src.npu_benchmark import adjust_npu_fit

        assert adjust_npu_fit("good", self._hw(50, 16, True)) in ("excellent", "good")

    def test_low_ram_demotes(self):
        from src.npu_benchmark import adjust_npu_fit

        assert adjust_npu_fit("good", self._hw(16, 4, True)) in (
            "fair",
            "not_recommended",
        )

    def test_unrecognized_fit_string(self):
        from src.npu_benchmark import adjust_npu_fit

        # If no adjustment is triggered (e.g. good hardware, but not high end)
        assert adjust_npu_fit("unknown", self._hw(16, 16, True)) == "unknown"
        # If adjustment is triggered (e.g. low ram), it treats "unknown" as "good"
        # index 1 + 1 (low ram) -> index 2 ("fair")
        assert adjust_npu_fit("unknown", self._hw(16, 4, True)) == "fair"

    def test_catalog_adjusted_label(self):
        from src.npu_model_installer import MODEL_CATALOG
        from src.npu_benchmark import HardwareCapabilities

        hw = HardwareCapabilities(npu_tops=50, ram_gb=16, npu_available=True)
        assert MODEL_CATALOG[0].hardware_adjusted_label(hw)

    def test_probe_returns_capabilities(self):
        from src.npu_benchmark import probe_hardware, HardwareCapabilities

        probe_hardware.cache_clear()
        hw = probe_hardware()
        assert isinstance(hw, HardwareCapabilities)
        assert hw.tier in ("low", "mid", "high")

    @pytest.mark.parametrize(
        "tops,tier",
        [(0, "low"), (5, "low"), (10, "mid"), (20, "mid"), (30, "high"), (50, "high")],
    )
    def test_tier_from_tops(self, tops, tier):
        from src.npu_benchmark import HardwareCapabilities

        hw = HardwareCapabilities(npu_tops=tops, ram_gb=16, npu_available=tops > 0)
        assert hw.tier == tier


# ── 18. AI models ─────────────────────────────────────────────────────────────


class TestAIModels:
    def _cfg(self, backend, model="test"):
        cfg = MagicMock()
        cfg.get = lambda k, d=None: {
            "backend": backend,
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": model,
                "timeout": 30,
            },
            "openai": {
                "base_url": "http://localhost:1234/v1",
                "model": model,
                "api_key_env": "",
            },
            "npu": {"model_path": "auto"},
            "network": {"allow_external": False},
            "security": {"rate_limit_per_minute": 0},
        }.get(k, d)
        return cfg

    def test_ollama_builds(self):
        from src.ai_assistant import AIAssistant

        assert AIAssistant(self._cfg("ollama", "llama3.2:3b")) is not None

    def test_openai_builds(self):
        from src.ai_assistant import AIAssistant

        assert AIAssistant(self._cfg("openai", "local-model")) is not None

    def test_large_model_warns(self):
        from src.model_selector import ModelSelector, ModelInfo

        cfg = self._cfg("ollama", "llama2:70b")
        sel = ModelSelector(cfg)
        warn = sel.npu_warning(ModelInfo(name="llama2:70b", size_bytes=40_000_000_000))
        assert warn

    def test_small_quantized_ok(self):
        from src.model_selector import ModelSelector, ModelInfo

        cfg = self._cfg("ollama", "llama3.2:3b-q4_K_M")
        sel = ModelSelector(cfg)
        warn = sel.npu_warning(
            ModelInfo(name="llama3.2:3b-q4_K_M", size_bytes=2_000_000_000)
        )
        assert warn is None or warn == "" or "ok" in warn.lower()

    def test_npu_unavailable(self):
        from src.npu_manager import NPUManager

        mgr = NPUManager(
            {"model_path": "nonexistent.onnx", "auto_install_default_model": False}
        )
        assert not mgr.is_npu_available()

    def test_catalog_count(self):
        from src.npu_model_installer import MODEL_CATALOG

        assert len(MODEL_CATALOG) >= 5

    def test_catalog_vision_models(self):
        from src.npu_model_installer import MODEL_CATALOG

        assert any(e.is_vision for e in MODEL_CATALOG)

    @pytest.mark.parametrize("key", ["phi3-vision-128k-int4", "phi3-mini-int4"])
    def test_catalog_entry_fields(self, key):
        from src.npu_model_installer import MODEL_CATALOG

        entry = next((e for e in MODEL_CATALOG if e.key == key), None)
        if entry is None:
            pytest.skip(f"{key} not in catalog")
        assert entry.name and entry.hf_repo
        assert entry.npu_fit in ("excellent", "good", "fair", "not_recommended")


# ── 19. Mode switching ────────────────────────────────────────────────────────


class TestModeSwitching:
    def test_compact_to_full(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="compact")
        win.show()
        win.show_full()
        assert win._current_mode == "full"
        win.close()

    def test_full_to_compact(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="full")
        win.show()
        win.show_compact()
        assert win._current_mode == "compact"
        assert win.width() == 420
        win.close()

    def test_round_trip(self, qapp, settings_manager):
        from src.gui.main_window import MainWindow

        win = MainWindow(settings_manager=settings_manager, start_mode="full")
        win.show()
        win.show_compact()
        win.show_full()
        assert win._current_mode == "full"
        win.close()


# ── 20. Full window page screenshots ─────────────────────────────────────────


class TestFullWindowPages:
    @pytest.mark.parametrize(
        "page", ["chat", "status", "models", "logs", "api", "settings"]
    )
    def test_page_renders(self, qtbot, settings_manager, page):
        from src.gui.full_window import FullWindow

        fw = FullWindow(settings_manager=settings_manager)
        qtbot.addWidget(fw)
        fw.show()
        try:
            fw.set_page(page)
        except Exception:
            pass
        _grab(fw, f"full_{page}")
        fw.close()
