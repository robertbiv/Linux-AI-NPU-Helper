"""Configuration management for Linux AI NPU Helper."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Default paths searched in order
_CONFIG_SEARCH_PATHS = [
    Path("config.yaml"),
    Path.home() / ".config" / "linux-ai-npu-helper" / "config.yaml",
    Path("/etc/linux-ai-npu-helper/config.yaml"),
]

_DEFAULTS: dict[str, Any] = {
    # ── Hotkey ────────────────────────────────────────────────────────────────
    # Use 'copilot' to listen for the physical Copilot/Fn key via evdev.
    # Alternatively supply a pynput-style key combo, e.g. "<ctrl>+<alt>+space".
    "hotkey": "copilot",
    # ── Network / privacy ─────────────────────────────────────────────────────
    # SECURITY: By default the assistant never contacts any external server.
    # All AI inference must run on localhost or a private-network address.
    # Set allow_external to true ONLY if you are self-hosting on a LAN server
    # you control and fully trust.
    "network": {
        "allow_external": False,
    },
    # ── Resource / power management ───────────────────────────────────────────
    "resources": {
        # Unload the NPU/ONNX session from memory after each inference call.
        # Keeps RAM free at the cost of a small reload delay on the next call.
        "unload_model_after_inference": True,
        # Close the HTTP connection to the AI backend after every request.
        # Prevents idle TCP sockets from lingering between interactions.
        "close_http_after_request": True,
        # Delete the screenshot bytes from memory as soon as they have been
        # forwarded to the AI backend.
        "discard_screenshot_after_send": True,
        # Stream AI tokens to the UI as they arrive rather than waiting for the
        # full response (reduces perceived latency and peak memory use).
        "stream_response": True,
    },
    # ── AI backend ────────────────────────────────────────────────────────────
    # Supported backends: "ollama", "openai", "npu"
    # NOTE: "openai" here means any *local* OpenAI-compatible server such as
    # LM Studio (default port 1234) or llama.cpp server.  The application
    # blocks all external URLs by default (see network.allow_external above).
    "backend": "ollama",
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "llava",          # vision-capable model
        "timeout": 120,
    },
    "openai": {
        # Point this at a LOCAL OpenAI-compatible server only.
        # e.g. LM Studio: http://localhost:1234/v1
        #      llama.cpp : http://localhost:8080/v1
        "base_url": "http://localhost:1234/v1",
        "api_key_env": "",         # not needed for local servers
        "model": "local-model",
        "timeout": 120,
    },
    # ── AMD NPU ───────────────────────────────────────────────────────────────
    "npu": {
        # Path to a pre-compiled ONNX vision model for the AMD Ryzen AI NPU.
        # When empty the assistant falls back to the configured backend above.
        "model_path": "",
        # Execution provider preference order (VitisAI first, then fallbacks)
        "providers": ["VitisAIExecutionProvider", "CPUExecutionProvider"],
        # Ryzen AI config JSON expected by VitisAI EP
        "vitisai_config": "/opt/xilinx/xrt/share/vitis_ai_library/models/vitisai_ep_json_config.json",
    },
    # ── Screen capture ────────────────────────────────────────────────────────
    "capture": {
        # "mss" (fast, pure-Python) or "scrot" (external tool)
        "method": "mss",
        # Monitor index: 0 = primary, 1-N = individual monitors
        "monitor": 0,
        # JPEG quality used when sending screenshots to vision model (1-95)
        "jpeg_quality": 75,
    },
    # ── UI / interaction ──────────────────────────────────────────────────────
    "ui": {
        # Overlay window position: "center", "top-right", "top-left",
        # "bottom-right", "bottom-left"
        "position": "center",
        # Width of the assistant overlay window in pixels
        "width": 700,
        # Maximum height before the text area scrolls
        "max_height": 500,
        # Font size inside the overlay
        "font_size": 12,
        # Opacity 0.0 (transparent) – 1.0 (opaque)
        "opacity": 0.92,
    },
    # ── Safety ────────────────────────────────────────────────────────────────
    "safety": {
        # Always require explicit confirmation before executing any shell command
        "confirm_commands": True,
        # Commands that are NEVER executed (regex patterns)
        "blocked_commands": [
            r"rm\s+-rf\s+/",
            r"mkfs",
            r"dd\s+.*of=/dev/[sh]d",
            r">\s*/dev/[sh]d",
        ],
    },
    # ── Tools ─────────────────────────────────────────────────────────────────
    "tools": {
        # Root directory used as the default for file/content searches
        "search_path": "~",
        # Paths the SearchInFilesTool will NEVER read from (security/privacy)
        "blocked_paths": [
            "~/.ssh",
            "~/.gnupg",
            "/etc/shadow",
            "/etc/sudoers",
            "/proc",
            "/sys",
        ],
        # Web-search browser tool
        "web_search": {
            # Which engine to use by default.  Must be a key in "engines" below.
            "engine": "duckduckgo",
            # Engine URL templates.  Use {query} as the placeholder.
            # The app opens these with xdg-open — it never makes HTTP requests
            # to search engines itself.
            "engines": {
                "duckduckgo": "https://duckduckgo.com/?q={query}",
                "startpage":  "https://www.startpage.com/search?q={query}",
                "brave":      "https://search.brave.com/search?q={query}",
                "ecosia":     "https://www.ecosia.org/search?q={query}",
                "google":     "https://www.google.com/search?q={query}",
                "bing":       "https://www.bing.com/search?q={query}",
            },
        },
    },
    # ── Logging ───────────────────────────────────────────────────────────────
    "log_level": "INFO",
    "log_file": "",   # empty = stderr only
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """Thin wrapper around a dict that gives attribute-style access to sections."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    # ── dict-like access ──────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def network(self) -> dict:
        return self._data.get("network", {"allow_external": False})

    @property
    def tools(self) -> dict:
        return self._data.get("tools", {})

    @property
    def resources(self) -> dict:
        return self._data.get("resources", {})

    @property
    def backend(self) -> str:
        return self._data["backend"]

    @property
    def hotkey(self) -> str:
        return self._data["hotkey"]

    @property
    def ollama(self) -> dict:
        return self._data["ollama"]

    @property
    def openai(self) -> dict:
        return self._data["openai"]

    @property
    def npu(self) -> dict:
        return self._data["npu"]

    @property
    def capture(self) -> dict:
        return self._data["capture"]

    @property
    def ui(self) -> dict:
        return self._data["ui"]

    @property
    def safety(self) -> dict:
        return self._data["safety"]

    @property
    def log_level(self) -> str:
        return self._data.get("log_level", "INFO")

    @property
    def log_file(self) -> str:
        return self._data.get("log_file", "")

    # ── repr ──────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"Config(backend={self.backend!r}, hotkey={self.hotkey!r})"


def load(path: str | Path | None = None) -> Config:
    """Load configuration, merging user file over built-in defaults.

    Parameters
    ----------
    path:
        Explicit path to a ``config.yaml`` file.  When *None* the function
        searches :data:`_CONFIG_SEARCH_PATHS` in order and uses the first file
        it finds.  If no file is found the built-in defaults are used as-is.
    """
    data = dict(_DEFAULTS)

    # Resolve the file to load
    config_file: Path | None = None
    if path is not None:
        config_file = Path(path)
    else:
        for candidate in _CONFIG_SEARCH_PATHS:
            if candidate.exists():
                config_file = candidate
                break

    if config_file is not None and config_file.exists():
        with config_file.open("r", encoding="utf-8") as fh:
            user_data = yaml.safe_load(fh) or {}
        data = _deep_merge(data, user_data)

    # Allow environment variable to override API key (local servers may not
    # need one; only look it up when api_key_env is explicitly set).
    openai_key_env = data["openai"].get("api_key_env", "")
    if openai_key_env and os.environ.get(openai_key_env):
        data["openai"]["api_key"] = os.environ[openai_key_env]
    else:
        data["openai"].setdefault("api_key", "")

    return Config(data)
