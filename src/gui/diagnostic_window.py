# SPDX-License-Identifier: GPL-3.0-or-later
"""Diagnostic window — live status dashboard with integrated test runner.

Shows the health of every application subsystem in real time.  All status
data is collected by :class:`~src.gui.diagnostic_reporter.DiagnosticReporter`
(pure Python, no Qt dependency), which means the data layer is fully
unit-testable without a display.

## Features
- **Status table** — colour-coded rows for Backend, NPU, Tools, Security,
  Settings, System, Network, Dependencies
- **Security checks panel** — per-file permission results
- **Dependencies panel** — installed / missing optional packages
- **Run Tests** button — invokes the test suite in a background thread and
  streams output to an embedded text view
- **Auto-refresh** every 30 seconds (configurable)
- **Copy report** — copies the full JSON report to the clipboard
## Usage
::

    from src.gui.diagnostic_window import DiagnosticWindow
    win = DiagnosticWindow(config, registry, settings_manager)
    win.exec_()
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtCore import QThread, Qt, QTimer, pyqtSignal
    from PyQt5.QtGui import QColor, QFont
    from PyQt5.QtWidgets import (
        QApplication,
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QLabel,
        QPlainTextEdit,
        QPushButton,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    logger.warning("PyQt5 not installed — DiagnosticWindow unavailable.")

# Colour map for status values
_STATUS_COLOURS = {
    "ok": "#27ae60",
    "warn": "#e67e22",
    "fail": "#c0392b",
    "skip": "#95a5a6",
}


if _HAS_QT:

    class _TestRunThread(QThread):
        """Runs the test suite in a background thread."""

        line_ready = pyqtSignal(str)
        finished = pyqtSignal(dict)

        def __init__(self, reporter: Any, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._reporter = reporter

        def run(self) -> None:
            result = self._reporter.run_tests()
            for line in result.get("output", "").splitlines():
                self.line_ready.emit(line)
            self.finished.emit(result)

    class _RefreshThread(QThread):
        """Fetches the full diagnostic report in a background thread."""

        finished = pyqtSignal(dict)

        def __init__(self, reporter: Any, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._reporter = reporter

        def run(self) -> None:
            report = self._reporter.full_report()
            self.finished.emit(report)

    # ── Helper widget builders ─────────────────────────────────────────────────

    def _status_item(text: str, status: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setData(Qt.AccessibleTextRole, text)
        colour = _STATUS_COLOURS.get(status.lower(), "#95a5a6")
        item.setForeground(QColor(colour))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _make_status_table(
        rows: list[tuple[str, str, str]],
        accessible_name: str = "Diagnostic Status Table",
    ) -> QTableWidget:
        """Create a read-only table of (label, status, detail) rows."""
        table = QTableWidget(len(rows), 3)
        table.setAccessibleName(accessible_name)
        table.setHorizontalHeaderLabels(["Check", "Status", "Details"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)

        for i, (label, status, detail) in enumerate(rows):
            item_label = QTableWidgetItem(label)
            item_label.setData(Qt.AccessibleTextRole, label)
            table.setItem(i, 0, item_label)

            table.setItem(i, 1, _status_item(status.upper(), status))

            item_detail = QTableWidgetItem(detail)
            item_detail.setData(Qt.AccessibleTextRole, detail)
            table.setItem(i, 2, item_detail)

        table.resizeColumnsToContents()
        return table

    # ── Main dialog ────────────────────────────────────────────────────────────

    class DiagnosticWindow(QDialog):
        """Live diagnostic dashboard.

        Args:
            config: The application :class:`~src.config.Config` object.
            registry: Optional :class:`~src.tools.ToolRegistry` for tool status.
            settings_manager: Optional :class:`~src.settings.SettingsManager`.
            parent: Optional parent widget.
        """

        def __init__(
            self,
            config: Any,
            registry: Any = None,
            settings_manager: Any = None,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            from src.gui.diagnostic_reporter import DiagnosticReporter

            self._reporter = DiagnosticReporter(config, registry, settings_manager)
            self._report: dict = {}

            self.setWindowTitle("Linux AI NPU Assistant — Diagnostics")
            self.setMinimumSize(720, 560)
            self.resize(820, 640)

            # Apply desktop theme
            try:
                from src.gui.theme import apply_to_app

                apply_to_app(QApplication.instance())
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not apply theme: %s", exc)

            self._build_ui()

            # Auto-refresh every 30 s
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.refresh)
            self._timer.start(30_000)

            # Initial load
            self.refresh()

        def _build_ui(self) -> None:
            layout = QVBoxLayout(self)

            # Header row
            header = QHBoxLayout()
            self._overall_label = QLabel("● Checking…")
            self._overall_label.setFont(QFont("", weight=QFont.Bold))
            header.addWidget(self._overall_label)
            header.addStretch()
            self._last_refresh = QLabel("")
            header.addWidget(self._last_refresh)
            layout.addLayout(header)

            # Tabs
            self._tabs = QTabWidget()
            self._tabs.setAccessibleName("Diagnostic Tabs")
            layout.addWidget(self._tabs)

            # ── Overview tab ──────────────────────────────────────────────
            self._overview_tab = QWidget()
            ov_layout = QVBoxLayout(self._overview_tab)
            self._overview_table = QTableWidget()
            self._overview_table.setAccessibleName("Overview Status Table")
            ov_layout.addWidget(self._overview_table)
            self._tabs.addTab(self._overview_tab, "Overview")

            # ── Security tab ──────────────────────────────────────────────
            self._security_tab = QWidget()
            sec_layout = QVBoxLayout(self._security_tab)
            self._security_table = QTableWidget()
            self._security_table.setAccessibleName("Security Status Table")
            sec_layout.addWidget(self._security_table)
            self._tabs.addTab(self._security_tab, "Security")

            # ── Dependencies tab ──────────────────────────────────────────
            self._deps_tab = QWidget()
            deps_layout = QVBoxLayout(self._deps_tab)
            self._deps_table = QTableWidget()
            self._deps_table.setAccessibleName("Dependencies Status Table")
            deps_layout.addWidget(self._deps_table)
            self._tabs.addTab(self._deps_tab, "Dependencies")

            # ── Tools tab ─────────────────────────────────────────────────
            self._tools_tab = QWidget()
            tools_layout = QVBoxLayout(self._tools_tab)
            self._tools_table = QTableWidget()
            self._tools_table.setAccessibleName("Tools Status Table")
            tools_layout.addWidget(self._tools_table)
            self._tabs.addTab(self._tools_tab, "Tools")

            # ── Test runner tab ───────────────────────────────────────────
            self._test_tab = QWidget()
            test_layout = QVBoxLayout(self._test_tab)

            test_btns = QHBoxLayout()
            self._run_tests_btn = QPushButton("▶ Run Tests")
            self._run_tests_btn.setToolTip("Run internal test suite")
            self._run_tests_btn.setAccessibleName("Run internal test suite")
            self._run_tests_btn.clicked.connect(self._run_tests)
            test_btns.addWidget(self._run_tests_btn)
            self._test_summary = QLabel("")
            test_btns.addWidget(self._test_summary)
            test_btns.addStretch()
            test_layout.addLayout(test_btns)

            self._test_output = QPlainTextEdit()
            self._test_output.setAccessibleName("Test Output Log")
            self._test_output.setReadOnly(True)
            self._test_output.setFont(QFont("Monospace", 9))
            test_layout.addWidget(self._test_output)
            self._tabs.addTab(self._test_tab, "Test Runner")

            # ── Bottom buttons ─────────────────────────────────────────────
            btn_row = QHBoxLayout()

            refresh_btn = QPushButton("🔄 Refresh now")
            refresh_btn.setToolTip("Fetch the latest diagnostic report")
            refresh_btn.setAccessibleName("Fetch the latest diagnostic report")
            refresh_btn.clicked.connect(self.refresh)
            btn_row.addWidget(refresh_btn)

            copy_btn = QPushButton("📋 Copy JSON report")
            copy_btn.setToolTip("Copy the raw JSON report to clipboard")
            copy_btn.setAccessibleName("Copy the raw JSON report to clipboard")
            copy_btn.clicked.connect(self._copy_report)
            btn_row.addWidget(copy_btn)

            btn_row.addStretch()

            close_btn = QDialogButtonBox(QDialogButtonBox.Close)
            close_btn.rejected.connect(self.accept)
            btn_row.addWidget(close_btn)

            layout.addLayout(btn_row)

        # ── Refresh ────────────────────────────────────────────────────────

        def refresh(self) -> None:
            """Fetch all status data in a background thread."""
            self._thread = _RefreshThread(self._reporter, parent=self)
            self._thread.finished.connect(self._on_report)
            self._thread.start()

        def _on_report(self, report: dict) -> None:
            import datetime

            self._report = report
            self._populate_overview(report)
            self._populate_security(report.get("security", {}))
            self._populate_deps(report.get("dependencies", []))
            self._populate_tools(report.get("tools", []))

            overall = report.get("overall_status", "skip")
            colour = _STATUS_COLOURS.get(overall, "#95a5a6")
            self._overall_label.setText(f"● Overall: {overall.upper()}")
            self._overall_label.setStyleSheet(f"color: {colour};")
            self._last_refresh.setText(
                "Last refreshed: " + datetime.datetime.now().strftime("%H:%M:%S")
            )

        def _populate_overview(self, report: dict) -> None:
            rows: list[tuple[str, str, str]] = []

            # Backend
            b = report.get("backend", {})
            latency = f"  ({b.get('latency_ms')} ms)" if b.get("latency_ms") else ""
            rows.append(
                (
                    "AI Backend",
                    b.get("status", "skip"),
                    f"{b.get('backend', '')} @ {b.get('url', '')}{latency}  {b.get('error', '')}",
                )
            )

            # NPU
            n = report.get("npu", {})
            providers = ", ".join(n.get("providers", [])) or "none"
            rows.append(
                (
                    "NPU (ONNX)",
                    n.get("status", "skip"),
                    f"ONNX {n.get('onnxruntime_version', 'n/a')}  providers: {providers}  {n.get('error', '')}",
                )
            )

            # Security
            sec = report.get("security", {})
            rows.append(
                (
                    "Security",
                    sec.get("status", "skip"),
                    f"{sec.get('issues', 0)} issue(s) — see Security tab",
                )
            )

            # Settings
            s = report.get("settings", {})
            rows.append(
                (
                    "Settings",
                    s.get("status", "skip"),
                    f"{s.get('path', '')}  exists={s.get('exists', False)}  "
                    f"listeners={s.get('listener_count', 0)}",
                )
            )

            # System
            sys_ = report.get("system", {})
            rows.append(
                (
                    "System",
                    sys_.get("status", "skip"),
                    f"{sys_.get('os_name', '')} {sys_.get('os_version', '')}  "
                    f"DE={sys_.get('desktop_environment', '?')}  "
                    f"shell={sys_.get('shell', '?')}",
                )
            )

            # Network
            net = report.get("network", {})
            rows.append(
                (
                    "Network guard",
                    net.get("status", "skip"),
                    net.get("error")
                    or (
                        f"URL: {net.get('backend_url', '')}  "
                        f"local={net.get('backend_url_is_local', False)}"
                    ),
                )
            )

            table = _make_status_table(rows, accessible_name="Overview Status Table")
            # Replace existing table in layout
            layout = self._overview_tab.layout()
            old = layout.itemAt(0)
            if old and old.widget():
                old.widget().deleteLater()
            layout.insertWidget(0, table)

        def _populate_security(self, sec: dict) -> None:
            checks = sec.get("checks", [])
            rows = [(c["label"], c["status"], c["detail"]) for c in checks]
            table = _make_status_table(rows, accessible_name="Security Status Table")
            layout = self._security_tab.layout()
            old = layout.itemAt(0)
            if old and old.widget():
                old.widget().deleteLater()
            layout.insertWidget(0, table)

        def _populate_deps(self, deps: list) -> None:
            rows = [
                (
                    d["name"],
                    d["status"],
                    f"v{d['version']}"
                    if d["version"]
                    else ("required" if d["required"] else "optional"),
                )
                for d in deps
            ]
            table = _make_status_table(
                rows, accessible_name="Dependencies Status Table"
            )
            layout = self._deps_tab.layout()
            old = layout.itemAt(0)
            if old and old.widget():
                old.widget().deleteLater()
            layout.insertWidget(0, table)

        def _populate_tools(self, tools: list) -> None:
            rows = [
                (
                    t["name"],
                    t["status"],
                    f"{'loaded' if t['loaded'] else 'unloaded'}  {t['description']}",
                )
                for t in tools
            ]
            table = _make_status_table(rows, accessible_name="Tools Status Table")
            layout = self._tools_tab.layout()
            old = layout.itemAt(0)
            if old and old.widget():
                old.widget().deleteLater()
            layout.insertWidget(0, table)

        # ── Test runner ────────────────────────────────────────────────────

        def _run_tests(self) -> None:
            self._run_tests_btn.setEnabled(False)
            self._test_output.clear()
            self._test_summary.setText("Running…")
            self._test_thread = _TestRunThread(self._reporter, parent=self)
            self._test_thread.line_ready.connect(
                lambda line: self._test_output.appendPlainText(line)
            )
            self._test_thread.finished.connect(self._on_tests_done)
            self._test_thread.start()

        def _on_tests_done(self, result: dict) -> None:
            self._run_tests_btn.setEnabled(True)
            passed = result.get("passed", 0)
            failed = result.get("failed", 0)
            total = result.get("total", 0)
            elapsed = result.get("duration_s", 0)
            status = result.get("status", "skip")
            colour = _STATUS_COLOURS.get(status, "#95a5a6")
            summary = (
                f"<span style='color:{colour}'>"
                f"{passed}/{total} passed, {failed} failed "
                f"in {elapsed:.1f}s"
                f"</span>"
            )
            self._test_summary.setText(summary)

        # ── Copy report ────────────────────────────────────────────────────

        def _copy_report(self) -> None:
            text = json.dumps(self._report, indent=2, default=str)
            QApplication.clipboard().setText(text)
