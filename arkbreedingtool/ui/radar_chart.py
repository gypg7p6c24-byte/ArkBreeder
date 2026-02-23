from __future__ import annotations

import math
from typing import Dict, Iterable

from PySide6 import QtCore, QtGui, QtWidgets


class RadarChart(QtWidgets.QWidget):
    def __init__(self, axes: Iterable[str], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._axes = list(axes)
        self._values: Dict[str, float] = {axis: 0.0 for axis in self._axes}
        self._max_values: Dict[str, float] = {axis: 1.0 for axis in self._axes}
        self.setMinimumSize(220, 220)

    def set_values(
        self,
        values: Dict[str, float],
        max_values: Dict[str, float],
    ) -> None:
        self._values = dict(values)
        self._max_values = dict(max_values)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if not self._axes:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect().adjusted(24, 24, -24, -24)
        center = rect.center()
        radius = min(rect.width(), rect.height()) / 2

        axis_count = len(self._axes)
        angles = [
            (2 * math.pi * index / axis_count) - (math.pi / 2)
            for index in range(axis_count)
        ]

        grid_pen = QtGui.QPen(QtGui.QColor("#1f2937"))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)

        for ring in range(1, 5):
            ring_radius = radius * ring / 4
            points = [
                QtCore.QPointF(
                    center.x() + ring_radius * math.cos(angle),
                    center.y() + ring_radius * math.sin(angle),
                )
                for angle in angles
            ]
            painter.drawPolygon(QtGui.QPolygonF(points))

        axis_pen = QtGui.QPen(QtGui.QColor("#334155"))
        painter.setPen(axis_pen)
        for angle in angles:
            painter.drawLine(
                QtCore.QPointF(center.x(), center.y()),
                QtCore.QPointF(
                    center.x() + radius * math.cos(angle),
                    center.y() + radius * math.sin(angle),
                ),
            )

        value_points = []
        for axis, angle in zip(self._axes, angles):
            max_value = self._max_values.get(axis, 1.0)
            raw_value = self._values.get(axis, 0.0)
            ratio = 0.0 if max_value <= 0 else min(max(raw_value / max_value, 0.0), 1.0)
            value_points.append(
                QtCore.QPointF(
                    center.x() + radius * ratio * math.cos(angle),
                    center.y() + radius * ratio * math.sin(angle),
                )
            )

        area_color = QtGui.QColor("#38bdf8")
        area_color.setAlpha(90)
        painter.setBrush(area_color)
        painter.setPen(QtGui.QPen(QtGui.QColor("#38bdf8"), 2))
        painter.drawPolygon(QtGui.QPolygonF(value_points))

        label_pen = QtGui.QPen(QtGui.QColor("#e2e8f0"))
        painter.setPen(label_pen)
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        for axis, angle in zip(self._axes, angles):
            label_radius = radius + (18 if axis_count >= 6 else 12)
            x = center.x() + label_radius * math.cos(angle)
            y = center.y() + label_radius * math.sin(angle)
            text_width = metrics.horizontalAdvance(axis)
            text_height = metrics.height()
            rect = QtCore.QRectF(
                x - text_width / 2 - 2,
                y - text_height / 2,
                text_width + 4,
                text_height + 2,
            )
            painter.drawText(rect, QtCore.Qt.AlignCenter, axis)
