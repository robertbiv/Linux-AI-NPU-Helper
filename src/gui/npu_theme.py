# SPDX-License-Identifier: GPL-3.0-or-later
"""NPU dark-mode stylesheet and colour palette.

Provides the "Neural Dark" visual theme used by the NPU Assistant main window.
All colour constants are centralised here so they can be updated in one place.

## Colour roles
- ``BG_MAIN``   — outermost window / page background (near-black)
- ``BG_CARD``   — surface inside a card/panel (slightly lighter)
- ``BG_INPUT``  — text input / code block background
- ``GREEN``     — primary accent (status online, progress, highlights)
- ``BLUE``      — secondary accent (interactive elements, progress bars)
- ``RED``       — alert / error accent
- ``TEXT_*``    — text hierarchy from primary to muted
"""

from __future__ import annotations

# ── Colour constants ──────────────────────────────────────────────────────────

BG_MAIN = "#0d0f14"  # main window background
BG_CARD = "#161820"  # card / panel background
BG_CARD2 = "#1c1e28"  # slightly elevated card (messages, code blocks)
BG_INPUT = "#12141c"  # text-input / code-block background
BG_BUBBLE_USER = "#22242e"  # user chat bubble
BG_BUBBLE_AI = "#181a22"  # assistant chat bubble
BG_HOVER = "#2a2c38"  # hover state

BORDER = "#2a2c3a"  # card / widget border
BORDER_GREEN = "#2a4a2a"  # green-tinted border for AI messages

GREEN = "#39d353"  # primary accent — online / positive
GREEN_DIM = "#1e4a28"  # dark-green tinted background
BLUE = "#3b7eff"  # secondary accent — interactive
BLUE_DIM = "#1a2a50"  # dark-blue tinted background
RED = "#e05252"  # error / alert

TEXT_PRIMARY = "#e8eaf0"  # main readable text
TEXT_SECONDARY = "#8b90a2"  # captions, timestamps, metadata
TEXT_MUTED = "#50546a"  # very dim / disabled
TEXT_GREEN = "#39d353"  # green accent text (model name, status)
TEXT_BLUE = "#7ab4ff"  # blue accent text (links, values)
TEXT_CODE = "#a8d8a8"  # code/terminal text (soft green)
TEXT_CODE_ERR = "#e07070"  # ERROR lines in code
TEXT_CODE_INFO = "#70a0e0"  # INFO lines in code


# ── Global stylesheet ─────────────────────────────────────────────────────────

STYLESHEET = f"""
/* ── Base ─────────────────────────────────────────────────────────────── */
QWidget {{
    background-color: {BG_MAIN};
    color: {TEXT_PRIMARY};
    font-family: "Inter", "Segoe UI", "Roboto", sans-serif;
    font-size: 13px;
    border: 1px solid transparent; border-radius: 4px;
    outline: none;
}}

QMainWindow, QDialog {{
    background-color: {BG_MAIN};
}}

/* ── ScrollArea ────────────────────────────────────────────────────────── */
QScrollArea {{
    background-color: transparent;
    border: 1px solid transparent; border-radius: 4px;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}
QScrollBar:vertical {{
    background: {BG_CARD};
    width: 5px;
    border-radius: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 2px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
QTabBar::tab:focus {{
    border: 1px solid {BLUE};
    outline: none;
}}

/* ── Buttons ────────────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {BG_CARD2};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 12px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {GREEN};
}}
QPushButton:pressed {{
    background-color: {GREEN_DIM};
}}
QPushButton:focus, QToolButton:focus {{
    border-color: {BLUE};
    outline: none;
}}

QPushButton#sendBtn {{
    background-color: {BLUE};
    color: #ffffff;
    border: 1px solid transparent; border-radius: 4px;
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 16px;
    font-weight: bold;
}}
QPushButton#sendBtn:hover {{
    background-color: #5590ff;
}}
QPushButton#sendBtn:disabled {{
    background-color: {BG_HOVER};
    color: {TEXT_MUTED};
}}

QPushButton#navBtn {{
    background-color: transparent;
    border: 1px solid transparent; border-radius: 4px;
    border-radius: 0;
    color: {TEXT_SECONDARY};
    font-size: 10px;
    padding: 6px 4px 2px 4px;
}}
QPushButton#navBtn:hover {{
    color: {TEXT_PRIMARY};
}}

/* ── Line Edit ─────────────────────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 12px;
    selection-background-color: {BLUE_DIM};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {BLUE};
}}

/* ── ComboBox ───────────────────────────────────────────────────────────── */
QComboBox {{
    background-color: {BG_CARD2};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px 10px;
    min-width: 80px;
}}
QComboBox::drop-down {{
    border: 1px solid transparent; border-radius: 4px;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_SECONDARY};
}}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    selection-background-color: {BG_HOVER};
    color: {TEXT_PRIMARY};
    border-radius: 6px;
}}

/* ── Slider ─────────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    background: {BG_CARD2};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {GREEN};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {GREEN};
    border-radius: 2px;
}}

/* ── Labels ─────────────────────────────────────────────────────────────── */
QLabel {{
    background-color: transparent;
    color: {TEXT_PRIMARY};
}}

/* ── GroupBox ───────────────────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 8px;
    color: {TEXT_PRIMARY};
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: {TEXT_GREEN};
}}

/* ── CheckBox ───────────────────────────────────────────────────────────── */
QCheckBox {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 2px solid {BORDER};
    border-radius: 4px;
    background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background: {GREEN};
    border-color: {GREEN};
}}

/* ── ToolTip ─────────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}}
"""


def card_style(
    radius: int = 12,
    border_color: str = BORDER,
    bg: str = BG_CARD,
) -> str:
    """Return a QSS snippet for a card widget."""
    return (
        f"background-color: {bg};"
        f"border: 1px solid {border_color};"
        f"border-radius: {radius}px;"
        f"padding: 14px;"
    )
