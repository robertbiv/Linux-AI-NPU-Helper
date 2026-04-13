# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings manager — single source of truth for all application settings.

The :class:`SettingsManager` owns the authoritative in-memory settings dict
and is the **only** code that reads from / writes to the settings JSON file on
disk.  Both the GUI settings page and every other module talk to this object;
they never touch the file directly.

Sync model
----------
1. GUI widget changes a value  →  calls :meth:`set` / :meth:`set_nested`.
2. :meth:`set` updates in-memory dict and calls :meth:`save`.
3. :meth:`save` writes JSON atomically with owner-only (0o600) permissions.
4. Any registered *change listener* is notified so other components
   (e.g. :class:`~src.ai_assistant.AIAssistant`) can react immediately.

The JSON file mirrors the same structure as ``config.yaml`` (all keys,
nested dicts).  On load it is deep-merged over the compiled-in defaults
from :mod:`src.config` so missing keys always have sane values.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from src.security import check_path_permissions, secure_write

logger = logging.getLogger(__name__)

_DEFAULT_SETTINGS_PATH = (
    Path.home() / ".config" / "linux-ai-npu-assistant" / "settings.json"
)

# Type alias for change listeners: (key_path, new_value) → None
ChangeListener = Callable[[str, Any], None]


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _get_nested(d: dict, key_path: str) -> Any:
    """Retrieve a value from *d* using a dot-separated *key_path*.

    Example: ``_get_nested(d, "ollama.model")``
    """
    parts = key_path.split(".")
    node: Any = d
    for part in parts:
        if not isinstance(node, dict):
            raise KeyError(f"Cannot descend into non-dict at {part!r}")
        node = node[part]
    return node


def _set_nested(d: dict, key_path: str, value: Any) -> None:
    """Set a value in *d* using a dot-separated *key_path*, creating dicts
    along the way as needed.

    Example: ``_set_nested(d, "ollama.model", "llama3")``
    """
    parts = key_path.split(".")
    node = d
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


class SettingsManager:
    """Thread-safe settings manager with JSON persistence and change listeners.

    Parameters
    ----------
    path:
        Path to the ``settings.json`` file.  Created (with secure permissions)
        if it does not exist.  Pass ``None`` to disable persistence (useful in
        tests).
    defaults:
        Base default values deep-merged *before* the file is loaded.  Typically
        the ``_DEFAULTS`` dict from :mod:`src.config`.
    """

    def __init__(
        self,
        path: str | Path | None = _DEFAULT_SETTINGS_PATH,
        defaults: dict | None = None,
    ) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.RLock()
        self._listeners: list[ChangeListener] = []

        # Start from compiled-in defaults
        from src.config import _DEFAULTS
        base = dict(defaults) if defaults is not None else dict(_DEFAULTS)
        self._data: dict = base

        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load settings from JSON file, deep-merging over defaults."""
        if self._path is None or not self._path.exists():
            return
        check_path_permissions(self._path, label="settings file")
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                logger.warning("Settings file is not a JSON object; ignoring.")
                return
            with self._lock:
                self._data = _deep_merge(self._data, raw)
            logger.info("Settings loaded from %s", self._path)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load settings: %s", exc)

    def save(self) -> None:
        """Persist current settings to JSON with owner-only permissions.

        Writes are atomic (temp-file + rename) via :func:`~src.security.secure_write`.
        Safe to call from any thread.
        """
        if self._path is None:
            return
        with self._lock:
            data = dict(self._data)
        try:
            secure_write(
                self._path,
                json.dumps(data, indent=2, ensure_ascii=False),
                mode=0o600,
            )
            logger.debug("Settings saved to %s", self._path)
        except OSError as exc:
            logger.warning("Could not save settings: %s", exc)

    def reload(self) -> None:
        """Reload settings from disk, re-merging over defaults.

        Useful when the config file has been edited externally.
        """
        from src.config import _DEFAULTS
        with self._lock:
            self._data = dict(_DEFAULTS)
        self._load()

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, key_path: str, default: Any = None) -> Any:
        """Return the value at dot-separated *key_path*, or *default*.

        Example::

            settings.get("ollama.model")          # "llava"
            settings.get("tools.unload_after_use") # False
        """
        with self._lock:
            try:
                return _get_nested(self._data, key_path)
            except (KeyError, TypeError):
                return default

    def get_section(self, section: str) -> dict:
        """Return a *copy* of a top-level section dict.

        Returns an empty dict if the section does not exist.
        """
        with self._lock:
            value = self._data.get(section, {})
            return dict(value) if isinstance(value, dict) else {}

    def all(self) -> dict:
        """Return a deep copy of the entire settings dict."""
        import copy
        with self._lock:
            return copy.deepcopy(self._data)

    # ── Write ─────────────────────────────────────────────────────────────────

    def set(self, key_path: str, value: Any, *, save: bool = True) -> None:
        """Set *value* at dot-separated *key_path* and optionally persist.

        Notifies all registered change listeners synchronously before returning.

        Parameters
        ----------
        key_path:
            Dot-separated path, e.g. ``"ollama.model"`` or ``"tools.allowed"``.
        value:
            New value (any JSON-serialisable type).
        save:
            Write to disk immediately (default: ``True``).  Set to ``False``
            when making several changes in a batch and calling :meth:`save`
            manually afterwards.
        """
        with self._lock:
            _set_nested(self._data, key_path, value)
        logger.debug("Setting %r = %r", key_path, value)
        if save:
            self.save()
        self._notify(key_path, value)

    def set_many(self, changes: dict[str, Any]) -> None:
        """Apply multiple changes atomically and save once.

        Parameters
        ----------
        changes:
            Dict mapping dot-separated key paths to new values.

        Example::

            settings.set_many({
                "backend": "ollama",
                "ollama.model": "llama3:8b-q4_K_M",
                "tools.unload_after_use": True,
            })
        """
        with self._lock:
            for key_path, value in changes.items():
                _set_nested(self._data, key_path, value)
        self.save()
        for key_path, value in changes.items():
            self._notify(key_path, value)

    def update_section(self, section: str, values: dict) -> None:
        """Deep-merge *values* into an existing top-level *section* and save.

        Parameters
        ----------
        section:
            Top-level key (e.g. ``"tools"``, ``"ollama"``).
        values:
            Dict of new values to merge in.
        """
        with self._lock:
            existing = self._data.get(section, {})
            if isinstance(existing, dict):
                self._data[section] = _deep_merge(existing, values)
            else:
                self._data[section] = values
        self.save()
        self._notify(section, self._data[section])

    # ── Change listeners ──────────────────────────────────────────────────────

    def add_listener(self, listener: ChangeListener) -> None:
        """Register *listener* to be called whenever a setting changes.

        The listener receives ``(key_path: str, new_value: Any)``.  It is
        called from whatever thread called :meth:`set`, so listeners must be
        thread-safe.
        """
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: ChangeListener) -> None:
        """Unregister a previously registered *listener*."""
        with self._lock:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

    def _notify(self, key_path: str, value: Any) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(key_path, value)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Settings listener raised an error: %s", exc)

    # ── Convenience builders ──────────────────────────────────────────────────

    def to_config(self):
        """Return a :class:`~src.config.Config` built from the current settings.

        Useful for reconstructing the ``Config`` object after the user changes
        settings in the GUI.
        """
        from src.config import Config
        import copy
        with self._lock:
            return Config(copy.deepcopy(self._data))
