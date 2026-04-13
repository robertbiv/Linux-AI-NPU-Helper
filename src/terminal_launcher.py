# SPDX-License-Identifier: GPL-3.0-or-later
"""Terminal launcher — open the user's terminal pre-filled with a command.

The command is inserted into the terminal's readline / editing buffer so the
user can see and edit it before pressing Enter.  The assistant **never**
executes the command itself.

Shell-specific pre-fill techniques
------------------------------------
bash    ``read -e -i "cmd"`` — readline with initial text
zsh     ``vared`` — ZLE variable editor with initial value
fish    ``fish --init-command 'commandline "cmd"'`` — pre-fills the prompt
ksh     ``read -e`` fallback (no -i support in all ksh variants)
others  Display command prominently; plain ``read`` confirmation prompt

The launcher detects the user's shell via :mod:`src.shell_detector` and
selects the appropriate script template automatically.

Supported terminal emulators (tried in order)
----------------------------------------------
x-terminal-emulator, gnome-terminal, konsole, xfce4-terminal,
mate-terminal, lxterminal, tilix, kitty, alacritty, wezterm, xterm
"""

from __future__ import annotations

import logging
import os
import shlex
import stat
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Terminal emulator detection
# ---------------------------------------------------------------------------

_TERMINALS: list[tuple[str, str]] = [
    ("x-terminal-emulator", "dashe"),
    ("gnome-terminal",      "dashdash"),
    ("konsole",             "execute"),
    ("xfce4-terminal",      "dashe"),
    ("mate-terminal",       "dashe"),
    ("lxterminal",          "dashe"),
    ("tilix",               "dashe"),
    ("kitty",               "dashdash"),
    ("alacritty",           "dashdash"),
    ("wezterm",             "dashdash"),
    ("xterm",               "dashe"),
]


def _find_terminal() -> tuple[str, str] | None:
    import shutil
    for exe, style in _TERMINALS:
        path = shutil.which(exe)
        if path:
            return path, style
    return None


def _build_launch_cmd(terminal: str, style: str, script_path: str,
                      shell_path: str) -> list[str]:
    shell_q = shlex.quote(shell_path)
    script_q = shlex.quote(script_path)
    if style == "dashdash":
        return [terminal, "--", shell_path, script_path]
    if style == "execute":
        return [terminal, f"--command={shell_q} {script_q}"]
    return [terminal, "-e", f"{shell_q} {script_q}"]


# ---------------------------------------------------------------------------
# Shell-specific script templates
# ---------------------------------------------------------------------------

_BANNER = r"""
printf '\n\033[1;36m  Linux AI NPU Assistant — suggested command:\033[0m\n\n'
printf '\033[1;33m  %s\033[0m\n\n' "$_CMD"
"""

# bash: read -e (readline) with -i (initial text)
_BASH_SCRIPT = """\
#!/usr/bin/env bash
set -euo pipefail
_CMD={quoted}
""" + _BANNER + """\
printf 'Edit if needed, then press \\033[1mEnter\\033[0m to run  (Ctrl-C to cancel):\\n\\n'
read -r -e -p '$ ' -i "$_CMD" _CONFIRMED
if [ -n "$_CONFIRMED" ]; then
    eval "$_CONFIRMED"
fi
printf '\\n\\033[2m[Press Enter to close]\\033[0m'
read -r _DONE
"""

# zsh: vared — ZLE variable editor that accepts an initial value
_ZSH_SCRIPT = """\
#!/usr/bin/env zsh
_CMD={quoted}
""" + _BANNER + """\
printf 'Edit if needed, then press \\e[1mEnter\\e[0m to run  (Ctrl-C to cancel):\\n\\n'
vared -p '$ ' -c _CMD
if [ -n "$_CMD" ]; then
    eval "$_CMD"
fi
printf '\\n\\e[2m[Press Enter to close]\\e[0m'
read -r _DONE
"""

# fish: --init-command sets the commandline buffer before the prompt appears
# We wrap in a shell script that execs fish with the right flags.
_FISH_WRAPPER = """\
#!/bin/sh
_CMD={quoted}
exec fish --init-command "
  function _ai_prefill
    commandline -- '$_CMD'
    commandline --cursor (string length -- '$_CMD')
    functions --erase _ai_prefill
  end
  bind \\r '_ai_prefill; commandline -f execute'
  bind \\n '_ai_prefill; commandline -f execute'
" 2>/dev/null || exec fish
"""

# ksh / mksh: read supports -e (readline) but not -i; display cmd and prompt
_KSH_SCRIPT = """\
#!/usr/bin/env ksh
_CMD={quoted}
""" + _BANNER + """\
printf 'Type or edit the command, then press \\033[1mEnter\\033[0m (Ctrl-C to cancel):\\n\\n'
printf '$ %s' "$_CMD"
read -r _CONFIRMED
_CONFIRMED="${_CONFIRMED:-$_CMD}"
if [ -n "$_CONFIRMED" ]; then
    eval "$_CONFIRMED"
fi
printf '\\n[Press Enter to close]'
read -r _DONE
"""

# Generic POSIX sh / dash / csh / others: just display and do a plain read
_GENERIC_SCRIPT = """\
#!/bin/sh
_CMD={quoted}
""" + _BANNER + """\
printf 'Copy-paste or retype the command, then press Enter (Ctrl-C to cancel):\\n\\n'
printf '$ '
read -r _CONFIRMED
_CONFIRMED="${_CONFIRMED:-$_CMD}"
if [ -n "$_CONFIRMED" ]; then
    sh -c "$_CONFIRMED"
fi
printf '\\n[Press Enter to close]'
read -r _DONE
"""

_FAMILY_SCRIPTS: dict[str, str] = {
    "bash": _BASH_SCRIPT,
    "zsh":  _ZSH_SCRIPT,
    "fish": _FISH_WRAPPER,
    "ksh":  _KSH_SCRIPT,
}


def _pick_script(shell_family: str, quoted_cmd: str) -> tuple[str, str]:
    """Return (script_body, shell_executable_for_running_script)."""
    template = _FAMILY_SCRIPTS.get(shell_family, _GENERIC_SCRIPT)
    return template.format(quoted=quoted_cmd), "sh"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def open_with_command(command: str) -> tuple[bool, str]:
    """Open the user's default terminal pre-filled with *command*.

    Detects the user's shell and uses the appropriate pre-fill technique.
    Returns immediately (non-blocking).

    Returns
    -------
    (success, message)
    """
    import subprocess

    terminal_info = _find_terminal()
    if terminal_info is None:
        msg = (
            "No supported terminal emulator found. "
            "Install one of: gnome-terminal, konsole, xterm, kitty, alacritty."
        )
        logger.warning("terminal_launcher: %s", msg)
        return False, msg

    terminal, style = terminal_info

    # Detect user's shell
    try:
        from src.shell_detector import detect as detect_shell
        shell_info = detect_shell()
        shell_family = shell_info.family
        shell_path   = shell_info.path
    except Exception:  # noqa: BLE001
        shell_family = "sh"
        shell_path   = "/bin/sh"

    quoted = shlex.quote(command)
    script_body, _runner = _pick_script(shell_family, quoted)

    try:
        fd, script_path = tempfile.mkstemp(suffix=".sh", prefix="ai_helper_")
        try:
            os.write(fd, script_body.encode())
        finally:
            os.close(fd)
        os.chmod(script_path, stat.S_IRWXU)

        # For fish we always use sh to run the wrapper script
        runner = shell_path if shell_family != "fish" else "/bin/sh"
        launch_cmd = _build_launch_cmd(terminal, style, script_path, runner)
        logger.info("terminal_launcher: %s (shell=%s)", " ".join(launch_cmd), shell_family)

        subprocess.Popen(
            launch_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        _schedule_delete(script_path, delay=5.0)
        return True, f"Opened terminal ({shell_info.name}) with command: {command}"

    except Exception as exc:  # noqa: BLE001
        logger.error("terminal_launcher error: %s", exc)
        return False, str(exc)


def _schedule_delete(path: str, delay: float) -> None:
    """Delete *path* after *delay* seconds in a daemon thread."""
    import threading
    import time

    def _delete() -> None:
        time.sleep(delay)
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass

    threading.Thread(target=_delete, daemon=True).start()
