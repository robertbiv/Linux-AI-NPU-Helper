# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop-environment detection and Qt theme application.

Detects the running desktop environment from ``XDG_CURRENT_DESKTOP``,
``DESKTOP_SESSION``, or ``GDMSESSION`` and maps it to the most
appropriate Qt style and colour palette so the assistant window blends
naturally with the user's desktop.

## Supported desktop environments
- **GNOME / Budgie / Pop!_OS** → Fusion style with Adwaita-inspired palette
- **KDE Plasma / LXQt**        → native Qt style (Breeze used automatically)
- **XFCE**                     → Fusion with neutral grey palette
- **MATE**                     → Fusion with neutral palette
- **Cinnamon**                 → Fusion with Mint-green accent
- **Pantheon (elementary OS)** → Fusion with elementary blue accent
- **Deepin**                   → Fusion with Deepin-blue accent
- **Unknown / fallback**       → Fusion (clean, cross-platform)

The module is pure Python — Qt is imported lazily inside
:func:`apply_to_app` only, so the rest of the codebase can import
:mod:`src.gui.theme` without PyQt5 being installed.
## Example
>>> from src.gui.theme import detect_desktop_environment, get_theme_for_de
>>> de = detect_desktop_environment()
>>> theme = get_theme_for_de(de)
>>> print(theme.style_name, theme.accent_hex)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Data types ────────────────────────────────────────────────────────────────


@dataclass
class ColourPalette:
    """RGB colour values for a Qt QPalette.

    All hex strings are in ``#RRGGBB`` format.
    """

    window: str = "#f0f0f0"  # QColorGroup::Window
    window_text: str = "#1a1a1a"  # QColorGroup::WindowText
    base: str = "#ffffff"  # QColorGroup::Base (input backgrounds)
    alternate_base: str = "#f5f5f5"  # QColorGroup::AlternateBase
    button: str = "#e0e0e0"  # QColorGroup::Button
    button_text: str = "#1a1a1a"  # QColorGroup::ButtonText
    text: str = "#1a1a1a"  # QColorGroup::Text
    highlight: str = "#3584e4"  # QColorGroup::Highlight (accent)
    highlight_text: str = "#ffffff"  # QColorGroup::HighlightedText
    tooltip_base: str = "#ffffcc"  # QColorGroup::ToolTipBase
    tooltip_text: str = "#1a1a1a"  # QColorGroup::ToolTipText
    mid: str = "#c8c8c8"  # QColorGroup::Mid
    shadow: str = "#808080"  # QColorGroup::Shadow
    dark: str = "#a0a0a0"  # QColorGroup::Dark


@dataclass
class DarkColourPalette(ColourPalette):
    """Dark variant — active when the system prefers a dark colour scheme."""

    window: str = "#2d2d2d"
    window_text: str = "#e0e0e0"
    base: str = "#1e1e1e"
    alternate_base: str = "#282828"
    button: str = "#3c3c3c"
    button_text: str = "#e0e0e0"
    text: str = "#e0e0e0"
    highlight: str = "#3584e4"
    highlight_text: str = "#ffffff"
    tooltip_base: str = "#3c3c3c"
    tooltip_text: str = "#e0e0e0"
    mid: str = "#505050"
    shadow: str = "#1a1a1a"
    dark: str = "#404040"


@dataclass
class Theme:
    """Complete theme description for a desktop environment.

    Attributes
    de:
        Canonical DE name (e.g. ``"gnome"``, ``"kde"``, ``"xfce"``).
    style_name:
        Qt style name passed to ``QApplication.setStyle()``.
        ``""`` means use the system default (recommended for KDE/Plasma).
    light:
        Colour palette for light mode.
    dark:
        Colour palette for dark mode.
    accent_hex:
        Primary accent colour in ``#RRGGBB`` (used for highlights).
    font_family:
        Preferred font family (empty = Qt default).
    font_size_pt:
        Preferred font size in points (0 = Qt default).
    icon_theme:
        Preferred XDG icon theme name (empty = system default).
    extra_stylesheet:
        Additional QSS applied on top of the base style.
    """

    de: str = "unknown"
    style_name: str = "Fusion"
    light: ColourPalette = field(default_factory=ColourPalette)
    dark: ColourPalette = field(default_factory=DarkColourPalette)
    accent_hex: str = "#3584e4"
    font_family: str = ""
    font_size_pt: int = 0
    icon_theme: str = ""
    extra_stylesheet: str = ""


# ── Desktop environment detection ─────────────────────────────────────────────

#: DE name → canonical key mapping.  Values are lower-cased substrings that
#: appear in the XDG_CURRENT_DESKTOP / DESKTOP_SESSION environment variables.
_DE_MAP: dict[str, str] = {
    "gnome": "gnome",
    "unity": "gnome",  # Ubuntu Unity uses GNOME stack
    "budgie": "budgie",
    "pop": "gnome",  # Pop!_OS GNOME
    "kde": "kde",
    "plasma": "kde",
    "lxqt": "lxqt",
    "xfce": "xfce",
    "mate": "mate",
    "cinnamon": "cinnamon",
    "pantheon": "pantheon",
    "deepin": "deepin",
    "dde": "deepin",
    "enlightenment": "enlightenment",
    "sway": "sway",
    "hyprland": "hyprland",
    "i3": "i3",
    "openbox": "openbox",
}


def detect_desktop_environment() -> str:
    """Detect the running desktop environment.

    Checks the following environment variables in order:

    1. ``XDG_CURRENT_DESKTOP``
    2. ``DESKTOP_SESSION``
    3. ``GDMSESSION``

    Returns:
        Lower-cased canonical DE name, e.g. ``"gnome"``, ``"kde"``,
        ``"xfce"``.  Returns ``"unknown"`` if detection fails.
    """
    for var in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "GDMSESSION"):
        value = os.environ.get(var, "").lower()
        if not value:
            continue
        # XDG_CURRENT_DESKTOP may contain colon-separated names (e.g. "ubuntu:gnome")
        for part in value.replace(":", " ").split():
            for key, canonical in _DE_MAP.items():
                if key in part:
                    logger.debug("Detected DE %r from %s=%r", canonical, var, value)
                    return canonical
    logger.debug("Could not detect desktop environment; using fallback theme.")
    return "unknown"


def _prefers_dark() -> bool:
    """Return ``True`` if the system colour scheme preference is dark.

    Checks:
    - ``GTK_THEME`` env var containing "dark"
    - ``GNOME_DESKTOP_SESSION_ID`` heuristic
    - ``COLOR_SCHEME`` / ``GTK_APPLICATION_PREFER_DARK_THEME``
    - Falls back to ``False`` (light mode)
    """
    gtk_theme = os.environ.get("GTK_THEME", "").lower()
    if "dark" in gtk_theme:
        return True
    if os.environ.get("GTK_APPLICATION_PREFER_DARK_THEME", "0") == "1":
        return True
    color_scheme = os.environ.get("COLOR_SCHEME", "").lower()
    if "dark" in color_scheme:
        return True
    return False


# ── Theme definitions ─────────────────────────────────────────────────────────


def _gnome_theme() -> Theme:
    return Theme(
        de="gnome",
        style_name="Fusion",
        light=ColourPalette(
            window="#f6f5f4",
            window_text="#1a1a1a",
            base="#ffffff",
            alternate_base="#f0eeec",
            button="#e0dedd",
            button_text="#1a1a1a",
            highlight="#3584e4",
            highlight_text="#ffffff",
            mid="#c8c5c2",
            shadow="#6c6966",
            dark="#aaa8a5",
        ),
        dark=DarkColourPalette(
            highlight="#3584e4",
        ),
        accent_hex="#3584e4",
        font_family="Cantarell",
        icon_theme="Adwaita",
        extra_stylesheet="""
            QToolTip { border: 1px solid #c0bfbc; }
            QGroupBox { font-weight: bold; }
        """,
    )


def _budgie_theme() -> Theme:
    t = _gnome_theme()
    t.de = "budgie"
    t.accent_hex = "#5294e2"
    t.light.highlight = "#5294e2"
    t.dark.highlight = "#5294e2"
    return t


def _kde_theme() -> Theme:
    # Use empty style_name so Qt picks Breeze automatically when installed
    return Theme(
        de="kde",
        style_name="",  # Let KDE/Breeze handle it natively
        light=ColourPalette(
            window="#eff0f1",
            window_text="#1d1d1d",
            base="#fcfcfc",
            alternate_base="#f4f4f4",
            button="#eff0f1",
            button_text="#1d1d1d",
            highlight="#3daee9",
            highlight_text="#ffffff",
            mid="#c8c9ca",
            shadow="#7d7d7d",
            dark="#acacac",
        ),
        dark=DarkColourPalette(
            window="#31363b",
            window_text="#eff0f1",
            base="#232629",
            alternate_base="#2c3034",
            button="#31363b",
            button_text="#eff0f1",
            highlight="#3daee9",
            highlight_text="#ffffff",
            mid="#404040",
            shadow="#1d1d1d",
            dark="#3c3c3c",
        ),
        accent_hex="#3daee9",
        icon_theme="breeze",
    )


def _lxqt_theme() -> Theme:
    t = _kde_theme()
    t.de = "lxqt"
    return t


def _xfce_theme() -> Theme:
    return Theme(
        de="xfce",
        style_name="Fusion",
        light=ColourPalette(
            window="#d4cfca",
            window_text="#1a1a1a",
            base="#ffffff",
            alternate_base="#eae8e5",
            button="#d4cfca",
            button_text="#1a1a1a",
            highlight="#2d7db3",
            highlight_text="#ffffff",
            mid="#b5b0aa",
            shadow="#6d6863",
            dark="#a09b95",
        ),
        dark=DarkColourPalette(highlight="#2d7db3"),
        accent_hex="#2d7db3",
        icon_theme="hicolor",
    )


def _mate_theme() -> Theme:
    return Theme(
        de="mate",
        style_name="Fusion",
        light=ColourPalette(
            window="#ebebeb",
            window_text="#1a1a1a",
            base="#ffffff",
            alternate_base="#f4f4f4",
            button="#e0e0e0",
            button_text="#1a1a1a",
            highlight="#729fcf",
            highlight_text="#ffffff",
        ),
        dark=DarkColourPalette(highlight="#729fcf"),
        accent_hex="#729fcf",
    )


def _cinnamon_theme() -> Theme:
    return Theme(
        de="cinnamon",
        style_name="Fusion",
        light=ColourPalette(
            window="#f0f0f0",
            window_text="#1a1a1a",
            base="#ffffff",
            alternate_base="#f5f5f5",
            button="#dcdcdc",
            button_text="#1a1a1a",
            highlight="#4caf50",
            highlight_text="#ffffff",
        ),
        dark=DarkColourPalette(highlight="#4caf50"),
        accent_hex="#4caf50",
        font_family="Noto Sans",
    )


def _pantheon_theme() -> Theme:
    return Theme(
        de="pantheon",
        style_name="Fusion",
        light=ColourPalette(
            window="#f2f2f2",
            window_text="#1a1a1a",
            base="#ffffff",
            alternate_base="#f7f7f7",
            button="#e0e0e0",
            button_text="#1a1a1a",
            highlight="#0d52bf",
            highlight_text="#ffffff",
        ),
        dark=DarkColourPalette(highlight="#0d52bf"),
        accent_hex="#0d52bf",
        font_family="Open Sans",
    )


def _deepin_theme() -> Theme:
    return Theme(
        de="deepin",
        style_name="Fusion",
        light=ColourPalette(
            window="#f0f0f0",
            window_text="#1a1a1a",
            base="#ffffff",
            alternate_base="#f5f5f5",
            button="#e0e0e0",
            button_text="#1a1a1a",
            highlight="#0081ff",
            highlight_text="#ffffff",
        ),
        dark=DarkColourPalette(highlight="#0081ff"),
        accent_hex="#0081ff",
    )


def _tiling_wm_theme() -> Theme:
    """Minimal Fusion theme for tiling WMs (i3, Sway, Hyprland, Openbox)."""
    return Theme(
        de="tiling",
        style_name="Fusion",
        accent_hex="#5c6bc0",
    )


def _fallback_theme() -> Theme:
    return Theme(de="unknown", style_name="Fusion")


_DE_THEME_MAP: dict[str, "callable"] = {
    "gnome": _gnome_theme,
    "budgie": _budgie_theme,
    "kde": _kde_theme,
    "lxqt": _lxqt_theme,
    "xfce": _xfce_theme,
    "mate": _mate_theme,
    "cinnamon": _cinnamon_theme,
    "pantheon": _pantheon_theme,
    "deepin": _deepin_theme,
    "enlightenment": _tiling_wm_theme,
    "sway": _tiling_wm_theme,
    "hyprland": _tiling_wm_theme,
    "i3": _tiling_wm_theme,
    "openbox": _tiling_wm_theme,
}


def get_theme_for_de(de: str) -> Theme:
    """Return a :class:`Theme` for the given desktop environment name.

    Args:
        de:
            Canonical DE name as returned by :func:`detect_desktop_environment`.

    Returns:
        Fully populated theme object.  Falls back to Fusion if *de* is
        unrecognised.
    """
    factory = _DE_THEME_MAP.get(de, _fallback_theme)
    return factory()


def get_current_theme() -> Theme:
    """Detect the desktop environment and return the matching theme.

    Convenience wrapper combining :func:`detect_desktop_environment` and
    :func:`get_theme_for_de`.
    """
    de = detect_desktop_environment()
    return get_theme_for_de(de)


# ── Qt application ────────────────────────────────────────────────────────────


def apply_to_app(app: object, theme: Theme | None = None) -> Theme:
    """Apply *theme* to a ``QApplication`` instance.

    Imports PyQt5 lazily so this module is importable without Qt installed.

    Args:
        app:
            A ``PyQt5.QtWidgets.QApplication`` instance.
        theme:
            Theme to apply.  If ``None``, :func:`get_current_theme` is called
            automatically.

    Returns:
        The theme that was applied (useful for inspection / testing).

    Raises:
        RuntimeError: If PyQt5 is not installed.
    """
    try:
        from PyQt5.QtGui import QColor, QPalette
        from PyQt5.QtWidgets import QStyleFactory
    except ImportError as exc:
        raise ImportError(
            "PyQt5 is required for the GUI.  Install it with:\n"
            "  pip install PyQt5\n"
            "or via your package manager:\n"
            "  sudo apt install python3-pyqt5   # Debian/Ubuntu\n"
            "  sudo dnf install python3-qt5     # Fedora\n"
            "  sudo pacman -S python-pyqt5      # Arch"
        ) from exc

    if theme is None:
        theme = get_current_theme()

    # ── Style ──────────────────────────────────────────────────────────────
    if theme.style_name:
        available = QStyleFactory.keys()
        chosen = theme.style_name
        if chosen not in available:
            # Try case-insensitive match
            match = next((k for k in available if k.lower() == chosen.lower()), None)
            if match:
                chosen = match
            else:
                logger.debug(
                    "Style %r not available (%s); falling back to Fusion.",
                    chosen,
                    available,
                )
                chosen = (
                    "Fusion"
                    if "Fusion" in available
                    else (available[0] if available else "")
                )
        if chosen:
            app.setStyle(chosen)

    # ── Palette ────────────────────────────────────────────────────────────
    palette_data = theme.dark if _prefers_dark() else theme.light
    palette = QPalette()

    def _set(role: int, hex_color: str) -> None:
        color = QColor(hex_color)
        palette.setColor(role, color)

    W = QPalette.Window
    WT = QPalette.WindowText
    B = QPalette.Base
    AB = QPalette.AlternateBase
    BTN = QPalette.Button
    BTNT = QPalette.ButtonText
    TXT = QPalette.Text
    HL = QPalette.Highlight
    HLT = QPalette.HighlightedText
    TTB = QPalette.ToolTipBase
    TTT = QPalette.ToolTipText
    MID = QPalette.Mid
    SHD = QPalette.Shadow
    DRK = QPalette.Dark

    _set(W, palette_data.window)
    _set(WT, palette_data.window_text)
    _set(B, palette_data.base)
    _set(AB, palette_data.alternate_base)
    _set(BTN, palette_data.button)
    _set(BTNT, palette_data.button_text)
    _set(TXT, palette_data.text)
    _set(HL, palette_data.highlight)
    _set(HLT, palette_data.highlight_text)
    _set(TTB, palette_data.tooltip_base)
    _set(TTT, palette_data.tooltip_text)
    _set(MID, palette_data.mid)
    _set(SHD, palette_data.shadow)
    _set(DRK, palette_data.dark)

    app.setPalette(palette)

    # ── Font ───────────────────────────────────────────────────────────────
    if theme.font_family or theme.font_size_pt:
        font = app.font()
        if theme.font_family:
            font.setFamily(theme.font_family)
        if theme.font_size_pt:
            font.setPointSize(theme.font_size_pt)
        app.setFont(font)

    # ── Icon theme ─────────────────────────────────────────────────────────
    if theme.icon_theme:
        try:
            from PyQt5.QtGui import QIcon

            QIcon.setThemeName(theme.icon_theme)
        except Exception:  # noqa: BLE001
            pass

    # ── Stylesheet ─────────────────────────────────────────────────────────
    if theme.extra_stylesheet:
        app.setStyleSheet(theme.extra_stylesheet.strip())

    logger.info(
        "Applied theme for DE=%r (style=%r, accent=%r, dark=%s)",
        theme.de,
        theme.style_name,
        theme.accent_hex,
        _prefers_dark(),
    )
    return theme
