# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI package for Linux AI NPU Assistant.

This package provides PyQt5-based GUI components.  All modules use
a conditional import pattern so that the rest of the application
remains importable even when PyQt5 is not installed.

Modules
-------
theme
    Desktop-environment detection and Qt style/palette application.
diagnostic_reporter
    Pure-Python (no Qt) system status collector — fully testable.
settings_window
    QDialog with tabbed settings pages (Backend, Models, Tools, Security, Appearance).
model_manager
    Model browser widget with file dialog, drag-and-drop, and delete support.
diagnostic_window
    QDialog showing live status of all subsystems plus a test runner.
"""
