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
import functools
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


@functools.lru_cache(maxsize=1)
def _find_terminal() -> tuple[str, str] | None:
    import shutil

    # We use a simple loop with shutil.which instead of optimizing stat()
    # calls via os.listdir caching. Profiling shows that reading massive
    # directories like /usr/bin into memory is significantly slower than
    # executing a few redundant stat() calls for the specific terminals.
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

# bash: secure interactive initialization via --rcfile
_BASH_SCRIPT = r"""#!/usr/bin/env bash
_CMD={quoted}
""" + _BANNER + r"""_TMP=$(mktemp)
cat << EOF > "$_TMP"
[ -f ~/.bashrc ] && source ~/.bashrc
history -s "\$_CMD"
rm -f "$_TMP"
EOF
printf 'Press \033[1mUp Arrow\033[0m to view and edit the command.\n\n'
export _CMD
exec bash --rcfile "$_TMP" -i
"""

# zsh: secure interactive initialization via ZDOTDIR
_ZSH_SCRIPT = r"""#!/usr/bin/env zsh
_CMD={quoted}
""" + _BANNER + r"""_TMP_DIR=$(mktemp -d)
cat << EOF > "$_TMP_DIR/.zshrc"
[ -f ~/.zshrc ] && source ~/.zshrc
print -s "\$_CMD"
rm -rf "$_TMP_DIR"
EOF
printf 'Press \e[1mUp Arrow\e[0m to view and edit the command.\n\n'
export _CMD
ZDOTDIR="$_TMP_DIR" exec zsh -i
"""

# fish: --init-command sets the commandline buffer before the prompt appears
# We wrap in a shell script that execs fish with the right flags.
_FISH_WRAPPER = r"""#!/bin/sh
_CMD={quoted}
exec fish --init-command "
  function _ai_prefill
    commandline -- '$_CMD'
    commandline --cursor (string length -- '$_CMD')
    functions --erase _ai_prefill
  end
  bind \r '_ai_prefill; commandline -f execute'
  bind \n '_ai_prefill; commandline -f execute'
" 2>/dev/null || exec fish
"""

# ksh / mksh: secure interactive initialization via ENV
_KSH_SCRIPT = r"""#!/usr/bin/env ksh
_CMD={quoted}
""" + _BANNER + r"""_TMP=$(mktemp)
cat << EOF > "$_TMP"
[ -n "$ENV" ] && [ -f "$ENV" ] && . "$ENV"
print -s "\$_CMD"
rm -f "$_TMP"
EOF
printf 'Press \033[1mUp Arrow\033[0m to view and edit the command.\n\n'
export _CMD
ENV="$_TMP" exec ksh -i
"""

# Generic POSIX sh / dash / csh / others: secure interactive initialization via ENV
_GENERIC_SCRIPT = """\
#!/bin/sh
_CMD={quoted}
""" + _BANNER + """\
_TMP=$(mktemp)
cat << EOF > "$_TMP"
[ -n "$ENV" ] && [ -f "$ENV" ] && . "$ENV"
rm -f "$_TMP"
EOF
printf 'Copy-paste the command above.\\n\\n'
ENV="$_TMP" exec sh -i
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
        shell_name   = shell_info.name
    except Exception:  # noqa: BLE001
        shell_family = "sh"
        shell_path   = "/bin/sh"
        shell_name   = "sh"

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
        return True, f"Opened terminal ({shell_name}) with command: {command}"

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
