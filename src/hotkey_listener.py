# SPDX-License-Identifier: GPL-3.0-or-later
"""Hotkey / Copilot-button listener.

Two detection strategies are attempted in order:

1. **evdev** – Low-level input device scanning.  On many AMD laptops the
   Copilot key (or dedicated Fn key) shows up in ``/dev/input/event*`` as
   ``KEY_PROG1``, ``KEY_ASSISTANT``, or a vendor-specific code.  This
   approach does not depend on a running desktop environment and works even
   in console sessions.

2. **pynput** – Falls back to a keyboard-shortcut combination (e.g.
   ``<ctrl>+<alt>+space``) using the pynput library.  This is more portable
   but requires an X11 or Wayland input stack.

The listener calls *callback* in a background thread whenever the configured
key/combination is activated.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

# Key codes that represent the Copilot / AI-assistant button on various laptops.
# This list is extended as more hardware is encountered.
_COPILOT_KEY_CODES: set[int] = {
    # KEY_PROG1 (0x1b8 = 440) – common on many AMD Ryzen AI laptops
    0x1B8,
    # KEY_ASSISTANT (0x247 = 583) – reported on some ASUS / Lenovo devices
    0x247,
    # KEY_COPILOT – may appear on devices with Windows Copilot button
    0x24A,
}


class HotkeyListener:
    """Background listener that triggers *callback* when the hotkey fires.

    Args:
        hotkey: Either the literal string ``"copilot"`` (scan for Copilot key via
            evdev) or a pynput hotkey string such as ``"<ctrl>+<alt>+space"``.
        callback: Callable invoked (from a background thread) when the key fires.
    """

    def __init__(self, hotkey: str, callback: Callable[[], None]) -> None:
        self._hotkey = hotkey
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start listening in a background daemon thread."""
        self._stop_event.clear()
        if self._hotkey.lower() == "copilot":
            self._thread = threading.Thread(
                target=self._evdev_loop, daemon=True, name="hotkey-evdev"
            )
        else:
            self._thread = threading.Thread(
                target=self._pynput_loop, daemon=True, name="hotkey-pynput"
            )
        self._thread.start()
        logger.info("Hotkey listener started (hotkey=%r).", self._hotkey)

    def stop(self) -> None:
        """Signal the background thread to stop."""
        self._stop_event.set()
        logger.debug("Hotkey listener stop requested.")

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── evdev strategy ────────────────────────────────────────────────────────

    def _evdev_loop(self) -> None:
        try:
            import evdev  # type: ignore[import]
        except ImportError:
            logger.warning(
                "evdev not installed; falling back to pynput hotkey listener."
            )
            self._pynput_loop()
            return

        devices = self._find_copilot_devices(evdev)
        if not devices:
            logger.warning(
                "No evdev device found for Copilot key codes %s.  "
                "Falling back to pynput.",
                _COPILOT_KEY_CODES,
            )
            self._pynput_loop()
            return

        logger.info(
            "Monitoring evdev devices for Copilot key: %s",
            [d.path for d in devices],
        )

        import selectors

        sel = selectors.DefaultSelector()
        for dev in devices:
            sel.register(dev.fd, selectors.EVENT_READ, dev)

        try:
            while not self._stop_event.is_set():
                events = sel.select(timeout=0.5)
                for key, _ in events:
                    device: evdev.InputDevice = key.data
                    for event in device.read():
                        if (
                            event.type == evdev.ecodes.EV_KEY
                            and event.value == evdev.KeyEvent.key_down
                            and event.code in _COPILOT_KEY_CODES
                        ):
                            logger.debug(
                                "Copilot key pressed (code=%d) on %s",
                                event.code,
                                device.path,
                            )
                            self._fire()
        except Exception as exc:  # noqa: BLE001
            logger.error("evdev loop error: %s", exc)
        finally:
            sel.close()
            for dev in devices:
                dev.close()

    @staticmethod
    def _find_copilot_devices(evdev) -> list:  # type: ignore[no-untyped-def]
        """Return all input devices that report at least one Copilot key code."""
        found = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                capabilities = dev.capabilities()
                key_caps: list[int] = capabilities.get(evdev.ecodes.EV_KEY, [])
                if any(code in _COPILOT_KEY_CODES for code in key_caps):
                    found.append(dev)
                else:
                    dev.close()
            except (PermissionError, OSError):
                pass
        return found

    # ── pynput strategy ───────────────────────────────────────────────────────

    def _pynput_loop(self) -> None:
        try:
            from pynput import keyboard  # type: ignore[import]
        except ImportError:
            logger.error(
                "Neither evdev nor pynput is available.  "
                "Install pynput: pip install pynput"
            )
            return

        hotkey_str = self._hotkey
        if hotkey_str.lower() == "copilot":
            # Sensible default when running without Copilot key hardware
            hotkey_str = "<ctrl>+<alt>+space"
            logger.info(
                "No Copilot key detected via evdev; using pynput hotkey %r.",
                hotkey_str,
            )

        try:
            with keyboard.GlobalHotKeys({hotkey_str: self._fire}) as listener:
                self._stop_event.wait()
                listener.stop()
        except Exception as exc:  # noqa: BLE001
            logger.error("pynput listener error: %s", exc)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _fire(self) -> None:
        """Invoke the user callback, catching any exceptions."""
        try:
            self._callback()
        except Exception as exc:  # noqa: BLE001
            logger.error("Hotkey callback raised an exception: %s", exc, exc_info=True)
