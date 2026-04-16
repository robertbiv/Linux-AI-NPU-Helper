# SPDX-License-Identifier: GPL-3.0-or-later
"""Primary application launcher for development and packaging.

Use this module for a stable entrypoint during local development:

- ``python -m src.main``
- ``python -m src`` (via ``src.__main__`` wrapper)
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.ai_assistant import AIAssistant
from src.conversation import ConversationHistory
from src.gui.main_window import MODE_COMPACT, MODE_FULL, open_main_window
from src.npu_manager import NPUManager
from src.settings import SettingsManager


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the GUI launcher."""
    parser = argparse.ArgumentParser(prog="python -m src.main")
    parser.add_argument(
        "--start-mode",
        choices=(MODE_COMPACT, MODE_FULL),
        default=MODE_COMPACT,
        help="Initial UI mode.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the GUI application event loop and return the Qt exit code."""
    args = parse_args(argv)

    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        print("PyQt5 is required to run the GUI.", file=sys.stderr)
        return 1

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    app = QApplication(sys.argv)
    settings_manager = SettingsManager()
    cfg = settings_manager.to_config()
    history = ConversationHistory(encrypt=True)
    ai_assistant = AIAssistant(
        cfg,
        npu_manager=NPUManager(cfg.npu, cfg.resources),
    )

    window = open_main_window(
        settings_manager=settings_manager,
        ai_assistant=ai_assistant,
        conversation_history=history,
        start_mode=args.start_mode,
    )
    if window is None:
        return 1

    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
