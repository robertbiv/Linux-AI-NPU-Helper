# SPDX-License-Identifier: GPL-3.0-or-later
"""Compatibility entry point for ``python -m src``.

The canonical launcher lives in :mod:`src.main`.
"""

from src.main import main


if __name__ == "__main__":
    raise SystemExit(main())
