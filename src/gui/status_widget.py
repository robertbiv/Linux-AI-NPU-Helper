# SPDX-License-Identifier: GPL-3.0-or-later
"""NPU Performance status dashboard widget (Data tab).

Displays live NPU metrics in card-style panels:

- Engine status badge
- NPU clock speed, memory buffer, thermal load with progress bars
- Token throughput bar chart (last 60 s)
- Inference latency table (T-First-Token, T-Per-Token, Avg Jitter)
- Active kernel list
- Neural model context info

All metric values can be pushed in via :meth:`StatusWidget.update_metrics`
which accepts a plain dict so callers can populate it however they like
(polling files in ``/sys``, onnxruntime callbacks, etc.).
## Usage
::

    widget = StatusWidget(parent=main_window)
    widget.update_metrics({
        "npu_clock_pct": 78,
        "memory_used_gb": 12.4,
        "memory_total_gb": 20,
        "thermal_c": 54,
        "tps": 94.2,
        "tps_history": [80, 90, 85, 94, 91, 88, 94, 95, 93, 94],
        "t_first_ms": 12,
        "t_per_ms": 8,
        "jitter_ms": 0.4,
        "active_kernels": [
            {"cmd": "EXEC", "name": "lora_fusion_v4.bin", "status": "READY"},
        ],
        "model_name": "Llama-3-8B-Instruct (4-bit Quantized)",
        "model_tags": ["X-VECTOR ON", "FP16 ACCEL"],
    })
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtCore import Qt, QRectF
    from PyQt5.QtGui import QColor, QFont, QPainter, QBrush
    from PyQt5.QtWidgets import (
        QFrame,
        QHBoxLayout,
        QLabel,
        QProgressBar,
        QScrollArea,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )

    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    logger.warning("PyQt5 not installed — StatusWidget unavailable.")

if _HAS_QT:
    from src.gui import npu_theme as T

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            f"color: {T.TEXT_SECONDARY}; font-size: 10px;"
            f"letter-spacing: 2px; background: transparent;"
        )
        return lbl

    def _metric_progress(color: str = T.BLUE) -> QProgressBar:
        bar = QProgressBar()
        bar.setFixedHeight(4)
        bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar {{"
            f"  background: {T.BG_CARD2}; border-radius: 2px; border: none;"
            f"}}"
            f"QProgressBar::chunk {{"
            f"  background: {color}; border-radius: 2px;"
            f"}}"
        )
        return bar

    # ── Throughput bar chart ──────────────────────────────────────────────────

    class _ThroughputChart(QWidget):
        """Minimal bar chart for TPS history rendered with QPainter."""

        _BAR_COLOR = QColor(T.BLUE)
        _BAR_COLOR_BRIGHT = QColor("#5090ff")

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._data: list[float] = []
            self.setMinimumHeight(100)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setFixedHeight(120)

        def set_data(self, values: list[float]) -> None:
            self._data = values
            self.update()

        def paintEvent(self, event: object) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            w = self.width()
            h = self.height()
            data = self._data or []

            if not data:
                return

            n = len(data)
            max_val = max(data) if data else 1
            gap = 3
            bar_w = max(4, (w - gap * (n - 1)) // n)

            for i, val in enumerate(data):
                bar_h = int((val / max_val) * (h - 10)) if max_val > 0 else 0
                x = i * (bar_w + gap)
                y = h - bar_h

                # Gradient: last bar is brighter
                color = self._BAR_COLOR_BRIGHT if i == n - 1 else self._BAR_COLOR
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.NoPen)

                path_rect = QRectF(x, y, bar_w, bar_h)
                painter.drawRoundedRect(path_rect, 2, 2)

    # ── Individual metric card ────────────────────────────────────────────────

    class _MetricCard(QFrame):
        """Card displaying a single NPU metric with value, label, and progress."""

        def __init__(
            self,
            title: str,
            value_text: str = "—",
            unit: str = "",
            subtitle: str = "",
            progress: int = 0,
            bar_color: str = T.BLUE,
            badge_text: str = "",
            badge_color: str = T.GREEN,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self.setObjectName("metricCard")
            self.setStyleSheet(
                f"QFrame#metricCard {{"
                f"  background-color: {T.BG_CARD};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-radius: 12px;"
                f"}}"
            )
            layout = QVBoxLayout(self)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(4)

            # Header row: icon + badge
            header = QHBoxLayout()
            icon = QLabel("⬡")
            icon.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 16px; background: transparent;"
            )
            header.addWidget(icon)
            header.addStretch()
            if badge_text:
                badge = QLabel(badge_text)
                badge.setStyleSheet(
                    f"color: {T.BG_MAIN}; background: {badge_color};"
                    f"border-radius: 4px; padding: 2px 6px; font-size: 10px;"
                    f"font-weight: bold; letter-spacing: 0.5px;"
                )
                header.addWidget(badge)
            layout.addLayout(header)

            # Value
            value_row = QHBoxLayout()
            value_row.setSpacing(0)
            self._value_lbl = QLabel(value_text)
            self._value_lbl.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 40px; font-weight: bold;"
                f"background: transparent;"
            )
            value_row.addWidget(self._value_lbl)
            if unit:
                unit_lbl = QLabel(unit)
                unit_lbl.setStyleSheet(
                    f"color: {T.TEXT_SECONDARY}; font-size: 18px;"
                    f"background: transparent; padding-top: 16px;"
                )
                unit_lbl.setAlignment(Qt.AlignBottom)
                value_row.addWidget(unit_lbl)
            value_row.addStretch()
            layout.addLayout(value_row)

            # Subtitle label
            self._sub_lbl = QLabel(subtitle.upper())
            self._sub_lbl.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 10px;"
                f"letter-spacing: 1.5px; background: transparent;"
            )
            layout.addWidget(self._sub_lbl)

            # Progress bar
            layout.addSpacing(6)
            self._bar = _metric_progress(bar_color)
            self._bar.setValue(progress)
            layout.addWidget(self._bar)

            if subtitle:
                hint = QLabel(subtitle.upper())
                hint.setStyleSheet(
                    f"color: {T.TEXT_SECONDARY}; font-size: 10px;"
                    f"letter-spacing: 1px; background: transparent;"
                )

        def set_value(self, text: str, progress: int | None = None) -> None:
            self._value_lbl.setText(text)
            if progress is not None:
                self._bar.setValue(progress)

    # ── Latency row ───────────────────────────────────────────────────────────

    def _latency_row(label: str, value: str) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {T.TEXT_SECONDARY}; font-size: 13px; background: transparent;"
        )
        row.addWidget(lbl)
        row.addStretch()
        val = QLabel(value)
        val.setStyleSheet(
            f"color: {T.TEXT_PRIMARY}; font-size: 13px; background: transparent;"
        )
        row.addWidget(val)
        return row

    # ── Kernel line ───────────────────────────────────────────────────────────

    def _kernel_line(cmd: str, name: str, status: str) -> QLabel:
        status_color = T.GREEN if status in ("READY", "OK") else T.TEXT_SECONDARY
        html = (
            f'<span style="color:{T.TEXT_GREEN};">&gt;&nbsp;{cmd}:</span>'
            f'<span style="color:{T.TEXT_PRIMARY};"> {name}</span>'
            f'<span style="color:{status_color};"> [{status}]</span>'
        )
        lbl = QLabel(html)
        lbl.setTextFormat(Qt.RichText)
        lbl.setFont(QFont("Monospace", 10))
        lbl.setStyleSheet("background: transparent; padding: 1px 0;")
        return lbl

    # ── Main status widget ────────────────────────────────────────────────────

    class StatusWidget(QWidget):
        """NPU Performance dashboard page.

        Call :meth:`update_metrics` to push new data into all panels.
        """

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._metrics: dict[str, Any] = {}
            self._setup_ui()

        def _setup_ui(self) -> None:
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(14)

            self._setup_title(layout)
            self._setup_engine_status_card(layout)
            self._setup_metric_cards(layout)
            self._setup_throughput_chart_card(layout)
            self._setup_inference_latency_card(layout)
            self._setup_active_kernels_card(layout)
            self._setup_neural_model_context_card(layout)
            layout.addStretch()

            # Seed with defaults
            self._refresh_kernels(
                [
                    {"cmd": "EXEC", "name": "lora_fusion_v4.bin", "status": "READY"},
                    {
                        "cmd": "LOAD",
                        "name": "quantization_int8_map...",
                        "status": "...",
                    },
                    {"cmd": "STAT", "name": "stream_buffer_clear", "status": "OK"},
                    {"cmd": "SYNC", "name": "neural_engine_sync...", "status": "0ms"},
                ]
            )
            self._refresh_ctx_tags(["X-VECTOR ON", "FP16 ACCEL"])

            scroll.setWidget(page)
            outer.addWidget(scroll)

        def _setup_title(self, layout: QVBoxLayout) -> None:
            # ── Title ──────────────────────────────────────────────────────
            layout.addWidget(_section_label("System Architecture"))

            title_lbl = QLabel("NPU Performance")
            title_lbl.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 26px; font-weight: bold;"
                f"background: transparent;"
            )
            layout.addWidget(title_lbl)

        def _setup_engine_status_card(self, layout: QVBoxLayout) -> None:
            # ── Engine status card ─────────────────────────────────────────
            engine_card = QFrame()
            engine_card.setObjectName("engineCard")
            engine_card.setStyleSheet(
                f"QFrame#engineCard {{"
                f"  background-color: {T.BG_CARD};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-left: 3px solid {T.GREEN};"
                f"  border-radius: 10px;"
                f"}}"
            )
            ec_row = QHBoxLayout(engine_card)
            ec_row.setContentsMargins(14, 10, 14, 10)

            bolt = QLabel("⚡")
            bolt.setStyleSheet(
                f"color: {T.GREEN}; font-size: 22px; background: transparent;"
            )
            ec_row.addWidget(bolt)

            ec_text = QVBoxLayout()
            ec_text.setSpacing(0)
            ec_lbl1 = QLabel("ENGINE STATUS")
            ec_lbl1.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 10px;"
                f"letter-spacing: 1px; background: transparent;"
            )
            ec_text.addWidget(ec_lbl1)
            self._engine_status_lbl = QLabel("FULLY OPTIMIZED")
            self._engine_status_lbl.setStyleSheet(
                f"color: {T.GREEN}; font-size: 13px; font-weight: bold;"
                f"background: transparent;"
            )
            ec_text.addWidget(self._engine_status_lbl)
            ec_row.addLayout(ec_text)
            ec_row.addStretch()
            layout.addWidget(engine_card)

        def _setup_metric_cards(self, layout: QVBoxLayout) -> None:
            # ── Metric cards ───────────────────────────────────────────────
            self._card_clock = _MetricCard(
                "Clock Speed",
                "78",
                "%",
                "NPU Clock Speed",
                progress=78,
                bar_color=T.BLUE,
                badge_text="LIVE",
            )
            layout.addWidget(self._card_clock)

            self._card_mem = _MetricCard(
                "Memory Buffer",
                "62",
                "%",
                "Memory Buffer",
                progress=62,
                bar_color=T.BLUE,
            )
            layout.addWidget(self._card_mem)

            self._card_thermal = _MetricCard(
                "Thermal Load",
                "54",
                "°C",
                "Thermal Load",
                progress=54,
                bar_color=T.GREEN,
            )
            layout.addWidget(self._card_thermal)

        def _setup_throughput_chart_card(self, layout: QVBoxLayout) -> None:
            # ── Throughput chart card ──────────────────────────────────────
            tp_card = QFrame()
            tp_card.setObjectName("tpCard")
            tp_card.setStyleSheet(
                f"QFrame#tpCard {{"
                f"  background-color: {T.BG_CARD};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-radius: 12px;"
                f"}}"
            )
            tp_layout = QVBoxLayout(tp_card)
            tp_layout.setContentsMargins(14, 14, 14, 14)

            tp_header = QHBoxLayout()
            tp_title = QVBoxLayout()
            tp_title_lbl = QLabel("NPU Throughput")
            tp_title_lbl.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 15px; font-weight: bold;"
                f"background: transparent;"
            )
            tp_title.addWidget(tp_title_lbl)
            tp_sub_lbl = QLabel("Tokens Per Second (TPS) over last 60s")
            tp_sub_lbl.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 11px; background: transparent;"
            )
            tp_title.addWidget(tp_sub_lbl)
            tp_header.addLayout(tp_title)
            tp_header.addStretch()
            self._tps_badge = QLabel("94.2\nTPS")
            self._tps_badge.setAlignment(Qt.AlignCenter)
            self._tps_badge.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; background: {T.BG_CARD2};"
                f"border: 1px solid {T.BORDER}; border-radius: 8px;"
                f"padding: 4px 10px; font-size: 11px; font-weight: bold;"
            )
            tp_header.addWidget(self._tps_badge)
            tp_layout.addLayout(tp_header)

            self._throughput_chart = _ThroughputChart()
            tp_layout.addWidget(self._throughput_chart)
            layout.addWidget(tp_card)

        def _setup_inference_latency_card(self, layout: QVBoxLayout) -> None:
            # ── Inference latency card ─────────────────────────────────────
            lat_card = QFrame()
            lat_card.setObjectName("latCard")
            lat_card.setStyleSheet(
                f"QFrame#latCard {{"
                f"  background-color: {T.BG_CARD};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-radius: 12px;"
                f"}}"
            )
            lat_layout = QVBoxLayout(lat_card)
            lat_layout.setContentsMargins(14, 14, 14, 14)
            lat_layout.setSpacing(8)

            lat_title_row = QHBoxLayout()
            lat_icon = QLabel("⏱")
            lat_icon.setStyleSheet(
                f"color: {T.BLUE}; font-size: 18px; background: transparent;"
            )
            lat_title_row.addWidget(lat_icon)
            lat_title = QLabel("Inference Latency")
            lat_title.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 15px; font-weight: bold;"
                f"background: transparent;"
            )
            lat_title_row.addWidget(lat_title)
            lat_title_row.addStretch()
            lat_layout.addLayout(lat_title_row)

            self._lat_first_row = _latency_row("T-First Token", "12ms")
            lat_layout.addLayout(self._lat_first_row)
            self._lat_per_row = _latency_row("T-Per Token", "8ms")
            lat_layout.addLayout(self._lat_per_row)
            self._lat_jitter_row = _latency_row("Avg. Jitter", "0.4ms")
            lat_layout.addLayout(self._lat_jitter_row)

            layout.addWidget(lat_card)

        def _setup_active_kernels_card(self, layout: QVBoxLayout) -> None:
            # ── Active kernels card ────────────────────────────────────────
            kern_card = QFrame()
            kern_card.setObjectName("kernCard")
            kern_card.setStyleSheet(
                f"QFrame#kernCard {{"
                f"  background-color: {T.BG_CARD};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-radius: 12px;"
                f"}}"
            )
            kern_layout = QVBoxLayout(kern_card)
            kern_layout.setContentsMargins(14, 14, 14, 14)
            kern_layout.setSpacing(4)

            kern_header = QHBoxLayout()
            kern_title = QLabel("ACTIVE KERNELS")
            kern_title.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 10px; letter-spacing: 2px;"
                f"background: transparent;"
            )
            kern_header.addWidget(kern_title)
            kern_header.addStretch()
            self._kern_count_lbl = QLabel("4 PARALLEL")
            self._kern_count_lbl.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 10px; letter-spacing: 1px;"
                f"background: transparent;"
            )
            kern_header.addWidget(self._kern_count_lbl)
            kern_layout.addLayout(kern_header)

            self._kern_container = QVBoxLayout()
            kern_layout.addLayout(self._kern_container)
            layout.addWidget(kern_card)

        def _setup_neural_model_context_card(self, layout: QVBoxLayout) -> None:
            # ── Neural model context card ──────────────────────────────────
            ctx_card = QFrame()
            ctx_card.setObjectName("ctxCard")
            ctx_card.setStyleSheet(
                f"QFrame#ctxCard {{"
                f"  background-color: {T.BG_CARD};"
                f"  border: 1px solid {T.BORDER};"
                f"  border-radius: 12px;"
                f"}}"
            )
            ctx_layout = QVBoxLayout(ctx_card)
            ctx_layout.setContentsMargins(14, 14, 14, 14)
            ctx_layout.setSpacing(6)

            ctx_title = QLabel("Neural Model Context")
            ctx_title.setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-size: 15px; font-weight: bold;"
                f"background: transparent;"
            )
            ctx_layout.addWidget(ctx_title)

            self._ctx_model_lbl = QLabel("Llama-3-8B-Instruct (4-bit Quantized)")
            self._ctx_model_lbl.setStyleSheet(
                f"color: {T.TEXT_SECONDARY}; font-size: 12px; background: transparent;"
            )
            ctx_layout.addWidget(self._ctx_model_lbl)

            self._ctx_tags_row = QHBoxLayout()
            ctx_layout.addLayout(self._ctx_tags_row)

            layout.addWidget(ctx_card)

        # ── Public update API ─────────────────────────────────────────────────

        def update_metrics(self, metrics: dict[str, Any]) -> None:
            """Push new metric data into all panels.

            Keys:

            - ``npu_clock_pct``    — int 0-100
            - ``memory_used_gb``   — float
            - ``memory_total_gb``  — float
            - ``memory_pct``       — int 0-100 (computed if not provided)
            - ``thermal_c``        — int (°C)
            - ``tps``              — float (tokens/sec)
            - ``tps_history``      — list[float] (bar chart data)
            - ``t_first_ms``       — float
            - ``t_per_ms``         — float
            - ``jitter_ms``        — float
            - ``active_kernels``   — list[dict(cmd,name,status)]
            - ``model_name``       — str
            - ``model_tags``       — list[str]
            - ``engine_status``    — str
            - ``engine_ok``        — bool
            """
            self._metrics.update(metrics)

            # Clock
            if "npu_clock_pct" in metrics:
                pct = int(metrics["npu_clock_pct"])
                self._card_clock.set_value(str(pct), pct)

            # Memory
            if "memory_pct" in metrics or "memory_used_gb" in metrics:
                pct = int(metrics.get("memory_pct", 0))
                if not pct and "memory_used_gb" in metrics:
                    total = metrics.get("memory_total_gb", 1) or 1
                    pct = int(metrics["memory_used_gb"] / total * 100)
                label = str(pct)
                if "memory_used_gb" in metrics:
                    label = str(pct)
                self._card_mem.set_value(label, pct)

            # Thermal
            if "thermal_c" in metrics:
                val = int(metrics["thermal_c"])
                self._card_thermal.set_value(str(val), min(val, 100))

            # TPS
            if "tps" in metrics:
                tps = float(metrics["tps"])
                self._tps_badge.setText(f"{tps:.1f}\nTPS")
            if "tps_history" in metrics:
                self._throughput_chart.set_data(list(metrics["tps_history"]))

            # Latency
            if "t_first_ms" in metrics:
                self._update_latency_row(
                    self._lat_first_row, f"{metrics['t_first_ms']}ms"
                )
            if "t_per_ms" in metrics:
                self._update_latency_row(self._lat_per_row, f"{metrics['t_per_ms']}ms")
            if "jitter_ms" in metrics:
                self._update_latency_row(
                    self._lat_jitter_row, f"{metrics['jitter_ms']}ms"
                )

            # Kernels
            if "active_kernels" in metrics:
                self._refresh_kernels(metrics["active_kernels"])
                count = len(metrics["active_kernels"])
                self._kern_count_lbl.setText(f"{count} PARALLEL")

            # Model context
            if "model_name" in metrics:
                self._ctx_model_lbl.setText(metrics["model_name"])
            if "model_tags" in metrics:
                self._refresh_ctx_tags(metrics["model_tags"])

            # Engine status
            if "engine_status" in metrics:
                ok = metrics.get("engine_ok", True)
                self._engine_status_lbl.setText(metrics["engine_status"])
                self._engine_status_lbl.setStyleSheet(
                    f"color: {T.GREEN if ok else T.RED}; font-size: 13px; font-weight: bold;"
                    f"background: transparent;"
                )

        # ── Private helpers ────────────────────────────────────────────────────

        @staticmethod
        def _update_latency_row(row_layout: QHBoxLayout, value: str) -> None:
            """Update the value label in a latency row layout."""
            # Value label is the last widget in the row
            for i in range(row_layout.count()):
                item = row_layout.itemAt(i)
                if item and isinstance(item.widget(), QLabel):
                    # Last QLabel is the value
                    pass
            item = row_layout.itemAt(row_layout.count() - 1)
            if item and isinstance(item.widget(), QLabel):
                item.widget().setText(value)

        def _refresh_kernels(self, kernels: list[dict]) -> None:
            # Clear existing
            while self._kern_container.count():
                item = self._kern_container.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            for k in kernels:
                line = _kernel_line(
                    k.get("cmd", ""),
                    k.get("name", ""),
                    k.get("status", ""),
                )
                self._kern_container.addWidget(line)

        def _refresh_ctx_tags(self, tags: list[str]) -> None:
            while self._ctx_tags_row.count():
                item = self._ctx_tags_row.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            colors = [T.GREEN, T.BLUE, T.TEXT_SECONDARY]
            for i, tag in enumerate(tags):
                color = colors[i % len(colors)]
                lbl = QLabel(tag)
                lbl.setStyleSheet(
                    f"color: {T.BG_MAIN}; background: {color};"
                    f"border-radius: 4px; padding: 3px 8px;"
                    f"font-size: 10px; font-weight: bold;"
                )
                self._ctx_tags_row.addWidget(lbl)
            self._ctx_tags_row.addStretch()
