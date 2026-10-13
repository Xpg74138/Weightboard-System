# -*- coding: utf-8 -*-
"""
plots.py —— 实时曲线

用 Qt 自绘（QPainter）实现，不依赖 matplotlib/pyqtgraph：
  · 依赖最少，Windows 和 Ubuntu 上装了 PyQt5 就能用；
  · 画出 4 路传感器 + 电池电压，每条曲线独立自动缩放；
  · 数据量大时自动抽稀，长时间运行不卡。
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QSizePolicy, QWidget

from . import theme

# 曲线定义：键 -> (显示名, 颜色)
SERIES = [
    ("s1", "前左 S1", QColor(theme.SENSOR_ACCENTS[0])),
    ("s2", "前右 S2", QColor(theme.SENSOR_ACCENTS[1])),
    ("s3", "后左 S3", QColor(theme.SENSOR_ACCENTS[2])),
    ("s4", "后右 S4", QColor(theme.SENSOR_ACCENTS[3])),
    ("batt_v", "电池 mV", QColor(theme.ACCENT2)),
]


class TrendChart(QWidget):
    """多路实时折线图（自动缩放 + 自动抽稀）。"""

    def __init__(self, parent=None, capacity: int = 600):
        super().__init__(parent)
        self.capacity = capacity
        self._data: Dict[str, Deque[float]] = {key: deque(maxlen=capacity) for key, _, _ in SERIES}
        self._visible: Dict[str, bool] = {key: True for key, _, _ in SERIES}
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ---------------- 数据 ----------------
    def add_sample(self, values: Dict[str, float]) -> None:
        changed = False
        for key, _, _ in SERIES:
            value = values.get(key)
            self._data[key].append(float(value) if value is not None else float("nan"))
            changed = True
        if changed:
            self.update()

    def clear(self) -> None:
        for key, _, _ in SERIES:
            self._data[key].clear()
        self.update()

    def set_samples(self, samples) -> None:
        """Replace the trace when the selected device changes."""
        self.clear()
        for values in samples:
            for key, _, _ in SERIES:
                value = values.get(key)
                self._data[key].append(float(value) if value is not None else float("nan"))
        self.update()

    def toggle_series(self, key: str, visible: bool) -> None:
        if key in self._visible:
            self._visible[key] = visible
            self.update()

    def series_info(self) -> List[tuple]:
        return [(key, name, color, self._visible[key]) for key, name, color in SERIES]

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:      # noqa: N802 (Qt 命名)
        try:
            self._paint()
        except Exception as exc:              # 绘制出错也不能让整个界面崩
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(theme.BG_DEEP))
            painter.setPen(QColor(theme.BAD))
            painter.drawText(self.rect(), Qt.AlignCenter, "曲线绘制失败：%s" % exc)

    def _paint(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(8, 8, -8, -8)

        painter.fillRect(self.rect(), QColor(theme.BG_DEEP))
        painter.setPen(QPen(QColor(theme.LINE), 1))
        painter.drawRect(rect)

        active = [(key, name, color, visible) for key, name, color, visible in self.series_info()
                  if visible and any(v == v for v in self._data[key])]
        if not active:
            painter.setPen(QColor(theme.FG_FAINT))
            painter.setFont(QFont("", 10))
            painter.drawText(rect, Qt.AlignCenter, "等待数据 …")
            return

        # 网格
        painter.setPen(QPen(QColor(theme.LINE_SOFT), 1))
        for i in range(1, 5):
            y = rect.top() + rect.height() * i / 5
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))

        # 每条曲线独立缩放
        for index, (key, name, color, _visible) in enumerate(active):
            values = [v for v in self._data[key] if v == v]      # 过滤 NaN
            if not values:
                continue
            low, high = min(values), max(values)
            if high - low < 1e-9:
                low, high = low - 1.0, high + 1.0
            else:
                margin = (high - low) * 0.08
                low, high = low - margin, high + margin

            count = len(self._data[key])
            if count < 2:
                continue
            step = max(1, count // 800)                          # 抽稀
            points = []
            for i in range(0, count, step):
                value = self._data[key][i]
                if value != value:
                    continue
                x = rect.left() + rect.width() * i / max(count - 1, 1)
                y = rect.bottom() - rect.height() * (value - low) / (high - low)
                points.append(QPointF(x, y))
            if len(points) < 2:
                continue
            painter.setPen(QPen(color, 2))
            painter.drawPolyline(QPolygonF(points))
            # 图例（当前值）：带该路颜色
            latest = values[-1]
            painter.setFont(QFont("Consolas", 9, QFont.Bold))
            painter.setPen(color)
            painter.drawText(rect.left() + 10, rect.top() + 18 + index * 17,
                             "%s  %.0f" % (name, latest))

        # 横轴说明
        painter.setPen(QColor(theme.FG_FAINT))
        painter.setFont(QFont("", 8))
        painter.drawText(rect.adjusted(6, 0, -6, -4), Qt.AlignBottom | Qt.AlignRight,
                         "%d 点" % min(len(self._data["s1"]), self.capacity))
