"""Tests for src/gui/theme.py — DE detection and theme selection."""

from __future__ import annotations
import os
import pytest
from unittest.mock import patch
from src.gui.theme import (
    detect_desktop_environment,
    get_theme_for_de,
    get_current_theme,
    _prefers_dark,
    ColourPalette,
    DarkColourPalette,
    Theme,
)


class TestDetectDesktopEnvironment:
    @pytest.fixture(autouse=True)
    def clear_de_cache(self):
        detect_desktop_environment.cache_clear()

    def test_gnome(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
        assert detect_desktop_environment() == "gnome"

    def test_gnome_ubuntu_colon(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
        assert detect_desktop_environment() == "gnome"

    def test_kde(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        assert detect_desktop_environment() == "kde"

    def test_plasma(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "plasma")
        assert detect_desktop_environment() == "kde"

    def test_xfce(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "XFCE")
        assert detect_desktop_environment() == "xfce"

    def test_mate(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "MATE")
        assert detect_desktop_environment() == "mate"

    def test_cinnamon(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "X-Cinnamon")
        assert detect_desktop_environment() == "cinnamon"

    def test_budgie(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "Budgie:GNOME")
        assert detect_desktop_environment() == "budgie"

    def test_pantheon(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "Pantheon")
        assert detect_desktop_environment() == "pantheon"

    def test_deepin(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "Deepin")
        assert detect_desktop_environment() == "deepin"

    def test_lxqt(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "LXQt")
        assert detect_desktop_environment() == "lxqt"

    def test_sway(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "sway")
        assert detect_desktop_environment() == "sway"

    def test_hyprland(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "Hyprland")
        assert detect_desktop_environment() == "hyprland"

    def test_i3(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "i3")
        assert detect_desktop_environment() == "i3"

    def test_fallback_to_desktop_session(self, monkeypatch):
        monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
        monkeypatch.setenv("DESKTOP_SESSION", "kde")
        assert detect_desktop_environment() == "kde"

    def test_fallback_to_gdmsession(self, monkeypatch):
        monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
        monkeypatch.delenv("DESKTOP_SESSION", raising=False)
        monkeypatch.setenv("GDMSESSION", "gnome")
        assert detect_desktop_environment() == "gnome"

    def test_unknown_when_no_env(self, monkeypatch):
        monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
        monkeypatch.delenv("DESKTOP_SESSION", raising=False)
        monkeypatch.delenv("GDMSESSION", raising=False)
        assert detect_desktop_environment() == "unknown"


class TestGetThemeForDe:
    def test_gnome_style(self):
        t = get_theme_for_de("gnome")
        assert t.style_name == "Fusion"
        assert t.de == "gnome"
        assert t.accent_hex.startswith("#")

    def test_kde_no_style_override(self):
        t = get_theme_for_de("kde")
        # KDE uses empty style so Breeze is picked natively
        assert t.style_name == ""
        assert t.de == "kde"

    def test_xfce(self):
        t = get_theme_for_de("xfce")
        assert t.de == "xfce"
        assert t.style_name == "Fusion"

    def test_mate(self):
        t = get_theme_for_de("mate")
        assert t.de == "mate"

    def test_cinnamon_accent_green(self):
        t = get_theme_for_de("cinnamon")
        assert "#4caf50" in t.accent_hex.lower() or "4caf" in t.accent_hex.lower()

    def test_pantheon(self):
        t = get_theme_for_de("pantheon")
        assert t.de == "pantheon"

    def test_deepin(self):
        t = get_theme_for_de("deepin")
        assert t.de == "deepin"

    def test_lxqt_same_as_kde(self):
        t = get_theme_for_de("lxqt")
        assert t.style_name == ""  # same as kde

    def test_sway_tiling(self):
        t = get_theme_for_de("sway")
        assert t.style_name == "Fusion"

    def test_unknown_fallback(self):
        t = get_theme_for_de("unknown")
        assert t.style_name == "Fusion"
        assert t.de == "unknown"

    def test_random_string_fallback(self):
        t = get_theme_for_de("some_nonexistent_de_xyz")
        assert isinstance(t, Theme)
        assert t.style_name == "Fusion"

    def test_all_des_return_theme(self):
        for de in [
            "gnome",
            "kde",
            "xfce",
            "mate",
            "cinnamon",
            "pantheon",
            "deepin",
            "lxqt",
            "budgie",
            "sway",
            "hyprland",
            "i3",
            "openbox",
            "unknown",
        ]:
            t = get_theme_for_de(de)
            assert isinstance(t, Theme), f"Expected Theme for DE={de}"
            assert t.accent_hex.startswith("#"), f"Bad accent for DE={de}"


class TestPrefersDark:
    def test_gtk_theme_dark(self, monkeypatch):
        monkeypatch.setenv("GTK_THEME", "Adwaita:dark")
        assert _prefers_dark() is True

    def test_gtk_prefer_dark_theme(self, monkeypatch):
        monkeypatch.delenv("GTK_THEME", raising=False)
        monkeypatch.setenv("GTK_APPLICATION_PREFER_DARK_THEME", "1")
        assert _prefers_dark() is True

    def test_color_scheme_dark(self, monkeypatch):
        monkeypatch.delenv("GTK_THEME", raising=False)
        monkeypatch.delenv("GTK_APPLICATION_PREFER_DARK_THEME", raising=False)
        monkeypatch.setenv("COLOR_SCHEME", "prefer-dark")
        assert _prefers_dark() is True

    def test_light_by_default(self, monkeypatch):
        monkeypatch.delenv("GTK_THEME", raising=False)
        monkeypatch.delenv("GTK_APPLICATION_PREFER_DARK_THEME", raising=False)
        monkeypatch.delenv("COLOR_SCHEME", raising=False)
        assert _prefers_dark() is False


class TestColourPalette:
    def test_defaults_are_hex(self):
        p = ColourPalette()
        for f in ["window", "window_text", "base", "highlight"]:
            val = getattr(p, f)
            assert val.startswith("#"), f"Field {f}={val!r} is not a hex colour"

    def test_dark_palette_darker_window(self):
        light = ColourPalette()
        dark = DarkColourPalette()

        # Dark window should be darker (lower RGB sum) than light window
        def rgb_sum(h: str) -> int:
            h = h.lstrip("#")
            return int(h[0:2], 16) + int(h[2:4], 16) + int(h[4:6], 16)

        assert rgb_sum(dark.window) < rgb_sum(light.window)


class TestGetCurrentTheme:
    @pytest.fixture(autouse=True)
    def clear_de_cache(self):
        detect_desktop_environment.cache_clear()

    def test_returns_theme(self, monkeypatch):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
        t = get_current_theme()
        assert isinstance(t, Theme)
        assert t.de == "gnome"
