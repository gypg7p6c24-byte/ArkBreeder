from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple

from PySide6 import QtCore, QtGui, QtWidgets


@dataclass(frozen=True)
class ChartSlice:
    label: str
    value: float
    color: str


class DonutChartWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._series: List[ChartSlice] = []
        self._palette = [
            "#38bdf8",
            "#f472b6",
            "#facc15",
            "#34d399",
            "#fb923c",
            "#a78bfa",
            "#60a5fa",
            "#f97316",
        ]
        self.setMinimumHeight(130)

    def set_series(self, series: Iterable[Tuple[str, float, str | None]]) -> None:
        normalized: List[ChartSlice] = []
        for idx, (label, value, color) in enumerate(series):
            if value is None:
                continue
            try:
                num = float(value)
            except (TypeError, ValueError):
                continue
            if num <= 0:
                continue
            chosen = color or self._palette[idx % len(self._palette)]
            normalized.append(ChartSlice(label=label, value=num, color=chosen))
        self._series = normalized
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)

        total = sum(slice_.value for slice_ in self._series)
        if total <= 0:
            painter.setPen(QtGui.QColor("#94a3b8"))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "No data")
            return

        size = min(rect.width(), rect.height())
        ring_width = max(14, int(size * 0.16))
        inset = ring_width / 2 + 1
        inner_size = max(10.0, size - inset * 2)
        chart_rect = QtCore.QRectF(
            rect.center().x() - inner_size / 2,
            rect.center().y() - inner_size / 2,
            inner_size,
            inner_size,
        )
        start_angle = 90 * 16
        for slice_ in self._series:
            span = -(slice_.value / total) * 360 * 16
            pen = QtGui.QPen(QtGui.QColor(slice_.color), ring_width)
            pen.setCapStyle(QtCore.Qt.FlatCap)
            painter.setPen(pen)
            painter.drawArc(chart_rect, int(start_angle), int(span))
            start_angle += span

        painter.setPen(QtGui.QColor("#e2e8f0"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(chart_rect, QtCore.Qt.AlignCenter, f"{int(total)}")


class BarChartWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._series: List[ChartSlice] = []
        self._palette = [
            "#38bdf8",
            "#a78bfa",
            "#f472b6",
            "#34d399",
            "#f97316",
            "#facc15",
        ]
        self.setMinimumHeight(150)

    def set_series(self, series: Iterable[Tuple[str, float, str | None]]) -> None:
        normalized: List[ChartSlice] = []
        for idx, (label, value, color) in enumerate(series):
            if value is None:
                continue
            try:
                num = float(value)
            except (TypeError, ValueError):
                continue
            if num <= 0:
                continue
            chosen = color or self._palette[idx % len(self._palette)]
            normalized.append(ChartSlice(label=label, value=num, color=chosen))
        self._series = normalized
        self.setMinimumHeight(max(150, 18 + len(self._series) * 22))
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(10, 10, -10, -10)

        if not self._series:
            painter.setPen(QtGui.QColor("#94a3b8"))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "No data")
            return

        max_value = max(slice_.value for slice_ in self._series)
        if max_value <= 0:
            painter.setPen(QtGui.QColor("#94a3b8"))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "No data")
            return

        row_height = 20.0
        row_gap = 2.0
        y_start = rect.top()
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        label_width = max(metrics.horizontalAdvance(slice_.label) for slice_ in self._series)
        value_width = max(metrics.horizontalAdvance(f"{slice_.value:.1f}") for slice_ in self._series)
        bar_left = rect.left() + label_width + 12
        bar_right = rect.right() - value_width - 10
        bar_width = max(10, bar_right - bar_left)

        for idx, slice_ in enumerate(self._series):
            bar_height = 10.0
            top = y_start + idx * (row_height + row_gap) + (row_height - bar_height) / 2
            label_rect = QtCore.QRectF(rect.left(), top, label_width + 6, bar_height)
            value_rect = QtCore.QRectF(bar_right + 6, top, value_width, bar_height)

            painter.setPen(QtGui.QColor("#e2e8f0"))
            painter.drawText(label_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, slice_.label)
            painter.setPen(QtGui.QColor("#94a3b8"))
            painter.drawText(value_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, f"{slice_.value:.1f}")

            ratio = slice_.value / max_value
            bar_rect = QtCore.QRectF(bar_left, top, bar_width * ratio, bar_height)
            painter.setBrush(QtGui.QColor(slice_.color))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(bar_rect, 4, 4)

        painter.end()
