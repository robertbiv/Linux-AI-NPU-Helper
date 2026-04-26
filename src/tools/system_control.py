# SPDX-License-Identifier: GPL-3.0-or-later
"""System control tool — control audio, bluetooth, wifi, brightness, etc."""

from __future__ import annotations

import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)

# Maps resource → (get_cmds, on_cmds, off_cmds, toggle_cmds)
# Each entry is a list of candidate command lists tried in order until one
# succeeds.  Commands are chosen by detecting which executables are on PATH.
#
# Backends tried in preference order:
#   audio/microphone : WirePlumber (wpctl) → PulseAudio (pactl) → ALSA (amixer)
#   bluetooth        : bluetoothctl → rfkill
#   wifi             : nmcli → rfkill
#   power_mode       : power-profiles-daemon (powerprofilesctl) → TuneD (tuned-adm)
#   brightness       : brightnessctl → xbacklight → light

_RESOURCE_ACTIONS: dict[str, dict[str, list[list[str]]]] = {
    "audio": {
        "get": [
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            ["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
            ["amixer", "get", "Master"],
        ],
        "mute": [
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"],
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
            ["amixer", "sset", "Master", "mute"],
        ],
        "unmute": [
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
            ["amixer", "sset", "Master", "unmute"],
        ],
        "toggle": [
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
            ["amixer", "sset", "Master", "toggle"],
        ],
    },
    "microphone": {
        "get": [
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
            ["pactl", "get-source-mute", "@DEFAULT_SOURCE@"],
            ["amixer", "get", "Capture"],
        ],
        "mute": [
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "1"],
            ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "1"],
            ["amixer", "sset", "Capture", "nocap"],
        ],
        "unmute": [
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0"],
            ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "0"],
            ["amixer", "sset", "Capture", "cap"],
        ],
        "toggle": [
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"],
            ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"],
            ["amixer", "sset", "Capture", "toggle"],
        ],
    },
    "bluetooth": {
        "get": [
            ["bluetoothctl", "show"],
            ["rfkill", "list", "bluetooth"],
        ],
        "on": [
            ["bluetoothctl", "power", "on"],
            ["rfkill", "unblock", "bluetooth"],
        ],
        "off": [
            ["bluetoothctl", "power", "off"],
            ["rfkill", "block", "bluetooth"],
        ],
    },
    "wifi": {
        "get": [
            ["nmcli", "radio", "wifi"],
            ["rfkill", "list", "wifi"],
        ],
        "on": [
            ["nmcli", "radio", "wifi", "on"],
            ["rfkill", "unblock", "wifi"],
        ],
        "off": [
            ["nmcli", "radio", "wifi", "off"],
            ["rfkill", "block", "wifi"],
        ],
    },
    "power_mode": {
        "get": [
            ["powerprofilesctl", "get"],
            ["tuned-adm", "active"],
        ],
        "performance": [
            ["powerprofilesctl", "set", "performance"],
            ["tuned-adm", "profile", "throughput-performance"],
        ],
        "balanced": [
            ["powerprofilesctl", "set", "balanced"],
            ["tuned-adm", "profile", "balanced"],
        ],
        "power-saver": [
            ["powerprofilesctl", "set", "power-saver"],
            ["tuned-adm", "profile", "powersave"],
        ],
    },
    "brightness": {
        "get": [
            ["brightnessctl", "get"],
            ["xbacklight", "-get"],
            ["light", "-G"],
        ],
    },
}

# Valid actions for each resource
_VALID_ACTIONS: dict[str, list[str]] = {
    "audio": ["get", "mute", "unmute", "toggle"],
    "microphone": ["get", "mute", "unmute", "toggle"],
    "bluetooth": ["get", "on", "off"],
    "wifi": ["get", "on", "off"],
    "power_mode": ["get", "performance", "balanced", "power-saver"],
    "brightness": ["get", "set"],
}


def _run_first_available(candidates: list[list[str]]) -> "tuple[bool, str]":
    """Try each command list in *candidates* until one succeeds.

    Returns ``(success, output)`` where ``output`` is stdout on success or the
    last error message on failure.
    """
    import shutil  # lazy
    import subprocess  # lazy

    last_err = "No suitable backend found."
    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        try:
            proc = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
            if proc.returncode == 0:
                return True, proc.stdout.strip()
            last_err = proc.stderr.strip() or proc.stdout.strip()
        except subprocess.TimeoutExpired:
            last_err = f"{cmd[0]} timed out."
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
    return False, last_err


class SystemControlTool(Tool):
    """Control system resources: audio, microphone, Bluetooth, Wi-Fi,
    power mode, and display brightness.

    ## Backend detection

    For each resource the tool tries available backends in order:

    - **Audio / Microphone**: WirePlumber (``wpctl``) → PulseAudio (``pactl``)
      → ALSA (``amixer``)
    - **Bluetooth**: ``bluetoothctl`` → ``rfkill``
    - **Wi-Fi**: ``nmcli`` (NetworkManager) → ``rfkill``
    - **Power mode**: ``powerprofilesctl`` (power-profiles-daemon) →
      ``tuned-adm`` (TuneD)
    - **Brightness**: ``brightnessctl`` → ``xbacklight`` → ``light``

    The first backend whose executable is on ``$PATH`` is used.  All
    subprocess imports and ``shutil.which`` checks are deferred to the
    first ``run()`` call so loading this module is free.

    ## Safety

    This tool is in ``requires_approval`` by default.  The user sees exactly
    which resource and action the AI is requesting before anything changes.
    Read-only ``get`` queries skip approval.
    """

    name = "system_control"
    description = (
        "Control system resources: toggle/query audio, microphone, Bluetooth, "
        "Wi-Fi, power mode, and brightness. "
        "Uses native Linux backends (wpctl/pactl, bluetoothctl, nmcli, etc.)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "resource": {
                "type": "string",
                "enum": list(_VALID_ACTIONS),
                "description": (
                    "The system resource to control. One of: "
                    + ", ".join(f"'{k}'" for k in _VALID_ACTIONS)
                    + "."
                ),
            },
            "action": {
                "type": "string",
                "description": (
                    "Action to perform. Depends on resource:\n"
                    "  audio/microphone: get | mute | unmute | toggle\n"
                    "  bluetooth/wifi:   get | on | off\n"
                    "  power_mode:       get | performance | balanced | power-saver\n"
                    "  brightness:       get | set (requires value)\n"
                ),
            },
            "value": {
                "type": "string",
                "description": (
                    "Value for actions that need one.\n"
                    "  brightness set: percentage string, e.g. '50%' or '50'.\n"
                    "  audio/microphone set-volume: e.g. '75%'."
                ),
            },
        },
        "required": ["resource", "action"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        resource: str = args.get("resource", "").lower().strip()
        action: str = args.get("action", "").lower().strip()
        value: str = args.get("value", "").strip()

        if resource not in _VALID_ACTIONS:
            return ToolResult(
                tool_name=self.name,
                error=(
                    f"Unknown resource '{resource}'. "
                    f"Valid resources: {', '.join(_VALID_ACTIONS)}."
                ),
            )

        valid = _VALID_ACTIONS[resource]
        if action not in valid:
            return ToolResult(
                tool_name=self.name,
                error=(
                    f"Invalid action '{action}' for '{resource}'. "
                    f"Valid actions: {', '.join(valid)}."
                ),
            )

        # ── Special case: brightness set ──────────────────────────────────────
        if resource == "brightness" and action == "set":
            return self._set_brightness(value)

        # ── Look up backend commands ───────────────────────────────────────────
        resource_map = _RESOURCE_ACTIONS.get(resource, {})
        candidates = resource_map.get(action)
        if not candidates:
            return ToolResult(
                tool_name=self.name,
                error=f"No backend commands defined for {resource}/{action}.",
            )

        success, output = _run_first_available(candidates)
        if not success:
            return ToolResult(
                tool_name=self.name,
                error=(
                    f"Could not {action} {resource}. "
                    f"No supported backend found or command failed: {output}"
                ),
            )

        snippet = (
            f"{resource} {action}: {output}" if output else f"{resource} {action}: OK"
        )
        return ToolResult(
            tool_name=self.name,
            results=[SearchResult(path=f"system:{resource}", snippet=snippet)],
        )

    def _set_brightness(self, value: str) -> ToolResult:
        """Handle brightness set with a percentage or absolute value."""

        if not value:
            return ToolResult(
                tool_name=self.name,
                error="brightness set requires a 'value', e.g. '50%'.",
            )

        # Normalise to percentage string for tools that accept it
        pct = value if value.endswith("%") else f"{value}%"

        candidates = [
            ["brightnessctl", "set", pct],
            ["xbacklight", "-set", value.rstrip("%")],
            ["light", "-S", value.rstrip("%")],
        ]
        success, output = _run_first_available(candidates)
        if not success:
            return ToolResult(
                tool_name=self.name,
                error=f"Could not set brightness to {value}: {output}",
            )
        return ToolResult(
            tool_name=self.name,
            results=[
                SearchResult(
                    path="system:brightness",
                    snippet=f"Brightness set to {value}.",
                )
            ],
        )

    def schema_text(self) -> str:
        resources = ", ".join(_VALID_ACTIONS)
        return (
            f"  {self.name}(resource: {resources}; action: string; value?: string)"
            f" — {self.description}"
        )
