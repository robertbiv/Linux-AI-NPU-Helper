#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# run-gui-tests.sh — Run all GUI tests headlessly.
#
# Uses QT_QPA_PLATFORM=offscreen so no real display is needed.
# Screenshots of every tested feature are saved to /tmp/npu-test-screenshots/.
#
# Usage
# -----
#   ./run-gui-tests.sh                   # run all GUI tests
#   ./run-gui-tests.sh -k "compact"      # run tests matching a keyword
#   ./run-gui-tests.sh --no-header       # suppress the banner
#
# Dependencies (installed automatically if missing)
# -------------------------------------------------
#   pytest, pytest-qt, PyQt5

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCREENSHOT_DIR="${NPU_SCREENSHOT_DIR:-/tmp/npu-test-screenshots}"
TEST_FILE="${SCRIPT_DIR}/tests/test_gui_widgets.py"
SHOW_BANNER=true

# ── Argument parsing ──────────────────────────────────────────────────────────
EXTRA_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --no-header) SHOW_BANNER=false ;;
        *) EXTRA_ARGS+=("$arg") ;;
    esac
done

# ── Banner ────────────────────────────────────────────────────────────────────
if "$SHOW_BANNER"; then
    echo ""
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║   Linux AI NPU Assistant — GUI Test Suite           ║"
    echo "║   Headless (QT_QPA_PLATFORM=offscreen)              ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""
fi

# ── Dependency check ──────────────────────────────────────────────────────────
cd "${SCRIPT_DIR}"

echo "→ Checking dependencies…"
python3 -c "import pytest" 2>/dev/null || {
    echo "  Installing pytest…"
    pip install pytest --quiet
}
python3 -c "import pytestqt" 2>/dev/null || {
    echo "  Installing pytest-qt…"
    pip install pytest-qt --quiet
}
python3 -c "from PyQt5.QtWidgets import QApplication" 2>/dev/null || {
    echo "  ⚠ PyQt5 not found. Install with: pip install PyQt5"
    echo "  Or on Debian/Ubuntu:  sudo apt install python3-pyqt5"
    exit 1
}

# ── Screenshot directory ──────────────────────────────────────────────────────
mkdir -p "${SCREENSHOT_DIR}"
echo "→ Screenshots will be saved to: ${SCREENSHOT_DIR}"

# ── Run tests ─────────────────────────────────────────────────────────────────
echo "→ Running GUI tests…"
echo ""

export QT_QPA_PLATFORM=offscreen
export NPU_SCREENSHOT_DIR="${SCREENSHOT_DIR}"
# Suppress Qt font/plugin noise
export QT_LOGGING_RULES="*.debug=false;qt.qpa.*=false"

python3 -m pytest \
    "${TEST_FILE}" \
    --tb=short \
    -v \
    "${EXTRA_ARGS[@]}" \
    2>&1

EXIT_CODE=$?

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
SCREENSHOT_COUNT=$(ls "${SCREENSHOT_DIR}"/*.png 2>/dev/null | wc -l || echo 0)
echo "→ Screenshots captured: ${SCREENSHOT_COUNT} (in ${SCREENSHOT_DIR})"

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "✅ All GUI tests passed."
else
    echo "❌ Some GUI tests failed. See output above."
fi
echo ""
exit "$EXIT_CODE"
