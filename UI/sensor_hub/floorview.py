# -*- coding: utf-8 -*-
"""
floorview.py —— 漏缝地板称重可视化（科技风）

一块 40:60（宽:长）的漏缝地板，居中绘制，四个角各有一个称重传感器：

    ┌───────────────────────────┐   ← 前左(传感器1)     前右(传感器2)
    │  ●1                    ●2 │
    │  ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬  │   ▬ = 地板缝隙（漏缝）
    │  ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬  │
    │  ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬  │
    │  ●3                    ●4 │
    └───────────────────────────┘   ← 后左(传感器3)     后右(传感器4)

    · 每个传感器点位有“光晕”，亮度与颜色随该路数值高低变化（冷→暖）
    · 每路读数直接标在点位旁边，并给出占四路总和的百分比
    · 中间叠加实时总重与四路占比条，形成“仪表盘”观感
    · 数值越高 → 光晕越大越暖，一眼能看出受力偏向哪一角
"""

from __future__ import annotations

from typing import Dict, Optional

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                         QPainterPath, QPen, QRadialGradient)
from PyQt5.QtWidgets import QSizePolicy, QWidget

from . import theme

FLOOR_W = 40.0          # 地板宽（比例 40:60）
FLOOR_L = 60.0          # 地板长
MARGIN = 82             # 四周留白（放点位标签）

# 四个传感器的位置（归一化 0~1）与名称：按常见布置 前左/前右/后左/后右
SENSOR_SLOTS = (
    ("s1", 0.0, 0.0, "前左"),
    ("s2", 1.0, 0.0, "前右"),
    ("s3", 0.0, 1.0, "后左"),
    ("s4", 1.0, 1.0, "后右"),
)


class FloorView(QWidget):
    """漏缝地板 + 四角称重传感器可视化。"""

    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self._compact = compact
        self._values: Dict[str, Optional[float]] = {k: None for k, _, _, _ in SENSOR_SLOTS}
        self._ok: Dict[str, Optional[bool]] = {k: None for k, _, _, _ in SENSOR_SLOTS}
        self._range = (-1.0, 1.0)      # 四路数值范围，用于配色
        self._total = 0.0
        self._board_text = "—"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(280, 180 if compact else 260)
        self.setToolTip("漏缝地板称重可视化：四角为 4 个称重传感器，"
                        "光晕颜色/大小随该路数值变化（冷色低、暖色高）")

    # ---------------- 对外接口 ----------------
    def set_values(self, values: Dict[str, Optional[float]]) -> None:
        """更新四路数值（键为 s1~s4）。"""
        nums = []
        for key, _, _, _ in SENSOR_SLOTS:
            value = values.get(key)
            self._values[key] = None if value is None else float(value)
            if value is not None:
                nums.append(float(value))
        if nums:
            low, high = min(nums), max(nums)
            if high - low < 1e-9:
                low, high = low - 1.0, high + 1.0
            self._range = (low, high)
            self._total = sum(nums)
        else:
            self._total = 0.0
        self.update()

    def set_channel_ok(self, ok: Dict[str, Optional[bool]]) -> None:
        """更新四路 HX711 读取状态（来自 OK 掩码）。"""
        self._ok = dict(ok)
        self.update()

    def set_board_text(self, text: str) -> None:
        """显示当前数据来自哪块板子。"""
        self._board_text = text
        self.update()

    def clear(self) -> None:
        self._values = {k: None for k, _, _, _ in SENSOR_SLOTS}
        self._ok = {k: None for k, _, _, _ in SENSOR_SLOTS}
        self._total = 0.0
        self._board_text = "—"
        self.update()

    # ---------------- 几何 ----------------
    def _floor_rect(self) -> QRectF:
        """按 40:60 比例计算居中的地板矩形。"""
        margin = 28 if self._compact else MARGIN
        avail_w = max(self.width() - 2 * margin, 40)
        avail_h = max(self.height() - 2 * margin, 40)
        scale = min(avail_w / FLOOR_W, avail_h / FLOOR_L)
        w = FLOOR_W * scale
        h = FLOOR_L * scale
        return QRectF((self.width() - w) / 2.0, (self.height() - h) / 2.0, w, h)

    @staticmethod
    def _slot_point(rect: QRectF, nx: float, ny: float) -> QPointF:
        return QPointF(rect.left() + rect.width() * nx,
                       rect.top() + rect.height() * ny)

    def _ratio(self, key: str) -> Optional[float]:
        value = self._values.get(key)
        if value is None:
            return None
        low, high = self._range
        if high - low < 1e-9:
            return 0.5
        return max(0.0, min(1.0, (value - low) / (high - low)))

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:      # noqa: N802
        try:
            self._paint()
        except Exception as exc:
            painter = QPainter(self)
            painter.fillRect(self.rect(), theme.qcolor(theme.BG_DEEP, 160))
            painter.setPen(theme.qcolor(theme.BAD))
            painter.drawText(self.rect(), Qt.AlignCenter, "地板绘制失败：%s" % exc)

    def _paint(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), theme.qcolor(theme.BG_DEEP, 150))

        rect = self._floor_rect()
        self._paint_glow_backdrop(painter, rect)     # 地板底部辉光
        self._paint_slats(painter, rect)             # 漏缝地板本体
        self._paint_center_readout(painter, rect)    # 中间：总重 + 占比条
        self._paint_sensors(painter, rect)           # 四角传感器点
        self._paint_footer(painter, rect)            # 底部：当前板号

    # ---- 地板底辉光 ----
    def _paint_glow_backdrop(self, painter: QPainter, rect: QRectF) -> None:
        glow = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.80)
        glow.setColorAt(0.0, theme.qcolor(theme.ACCENT, 20))
        glow.setColorAt(0.55, theme.qcolor(theme.ACCENT, 8))
        glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow))
        spread = max(rect.width(), rect.height()) * 0.34
        painter.drawRoundedRect(rect.adjusted(-spread, -spread, spread, spread), 30, 30)

    # ---- 漏缝地板 ----
    def _paint_slats(self, painter: QPainter, rect: QRectF) -> None:
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        painter.setClipPath(path)

        # 地板底：浅色玻璃
        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        base.setColorAt(0.0, theme.qcolor(theme.BG_PANEL))
        base.setColorAt(1.0, theme.qcolor(theme.FLOOR_LIGHT))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(base))
        painter.drawRect(rect)

        # 横向漏缝：浅色玻璃条 + 淡绿缝隙
        total_slats = 14
        pitch = rect.height() / total_slats
        slat_h = pitch * 0.62
        gap_h = pitch - slat_h
        for i in range(total_slats):
            y = rect.top() + i * pitch
            slat = QRectF(rect.left(), y, rect.width(), slat_h)
            grad = QLinearGradient(slat.topLeft(), slat.bottomLeft())
            grad.setColorAt(0.0, theme.qcolor(theme.BG_PANEL))
            grad.setColorAt(0.50, theme.qcolor(theme.FLOOR_MID))
            grad.setColorAt(1.0, theme.qcolor(theme.FLOOR_DARK))
            painter.setBrush(QBrush(grad))
            painter.drawRect(slat)

            # 缝隙：淡绿底 + 一条更亮的绿线（营造纵深）
            seam = QRectF(rect.left(), y + slat_h, rect.width(), gap_h)
            painter.setBrush(theme.qcolor(theme.FLOOR_MID))
            painter.drawRect(seam)
            if gap_h > 2.0:
                painter.setBrush(theme.qcolor(theme.ACCENT, 65))
                painter.drawRect(QRectF(seam.left(), seam.top(), seam.width(),
                                        max(1.0, seam.height() * 0.4)))

        # 四边发光描边（玻璃绿）
        painter.setClipping(False)
        painter.setPen(QPen(theme.qcolor(theme.ACCENT, 170), 1.8))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 12, 12)

    # ---- 中间读数：总重 + 四路占比条 ----
    def _paint_center_readout(self, painter: QPainter, rect: QRectF) -> None:
        painter.setFont(QFont("Consolas", max(9, int(rect.width() * 0.045))))
        painter.setPen(QColor(theme.FG_DIM))
        painter.drawText(rect, Qt.AlignHCenter | Qt.AlignVCenter,
                         "合计 " + self._format_total())

        # 四路占比条（中间靠下）
        bar_w = rect.width() * 0.62
        bar_h = max(8.0, rect.height() * 0.022)
        bar = QRectF(rect.center().x() - bar_w / 2.0,
                     rect.center().y() + rect.height() * 0.09, bar_w, bar_h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.LINE))
        painter.drawRoundedRect(bar, bar_h / 2, bar_h / 2)

        values = [self._values.get(key) for key, _, _, _ in SENSOR_SLOTS]
        nums = [v for v in values if v is not None]
        total = sum(nums) if nums else 0.0
        if total > 0:
            x = bar.left()
            for index, (key, _, _, _) in enumerate(SENSOR_SLOTS):
                value = self._values.get(key)
                if value is None or value <= 0:
                    continue
                width = bar.width() * (value / total)
                painter.setBrush(theme.sensor_color(index))
                painter.drawRoundedRect(QRectF(x, bar.top(), max(width, 1.5), bar.height()),
                                        bar_h / 2, bar_h / 2)
                x += width

    def _format_total(self) -> str:
        if all(value is None for value in self._values.values()):
            return "—"
        if abs(self._total) >= 10000:
            return "%.1f k" % (self._total / 1000.0)
        return "%.0f" % self._total

    # ---- 四角传感器 ----
    def _paint_sensors(self, painter: QPainter, rect: QRectF) -> None:
        for index, (key, nx, ny, label) in enumerate(SENSOR_SLOTS):
            point = self._slot_point(rect, nx, ny)
            ratio = self._ratio(key)
            value = self._values.get(key)
            ok = self._ok.get(key)
            color = theme.heat_color(ratio if ratio is not None else 0.0)
            if ratio is None:
                color = QColor(theme.OFFLINE)
            elif ok is False:
                color = QColor(theme.BAD)

            radius = 7.0 + 5.0 * (ratio if ratio is not None else 0.0)

            # 外光晕
            glow = QRadialGradient(point, radius * 3.4)
            c = QColor(color)
            c.setAlpha(120)
            glow.setColorAt(0.0, c)
            c2 = QColor(color)
            c2.setAlpha(0)
            glow.setColorAt(1.0, c2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(point, radius * 3.4, radius * 3.4)

            # 实心点 + 白环
            painter.setBrush(color)
            painter.drawEllipse(point, radius, radius)
            painter.setPen(QPen(theme.qcolor(theme.BG_PANEL), 1.8))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(point, radius, radius)

            if self._compact:
                painter.setFont(QFont("Consolas", 9, QFont.Bold))
                painter.setPen(theme.qcolor(theme.SENSOR_ACCENTS[index]))
                painter.drawText(QRectF(point.x() - 28 if nx == 0 else point.x() + 12,
                                        point.y() - 8, 24, 16), Qt.AlignCenter, "S%d" % (index + 1))
            else:
                self._paint_sensor_label(painter, rect, point, index, label, value, ok, color)

    def _paint_sensor_label(self, painter: QPainter, rect: QRectF, point: QPointF,
                            index: int, label: str, value: Optional[float],
                            ok: Optional[bool], color: QColor) -> None:
        """在点位外侧画读数（贴边摆放，不遮住地板）。"""
        left_side = point.x() <= rect.center().x()
        top_side = point.y() <= rect.center().y()

        text = "--" if value is None else "%.0f" % value
        title = "%s·S%d" % (label, index + 1)

        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        metrics = painter.fontMetrics()
        w = max(metrics.horizontalAdvance(text), metrics.horizontalAdvance(title)) + 14
        h = 34.0

        x = point.x() - w - 12 if left_side else point.x() + 12
        x = max(2.0, min(x, self.width() - w - 2.0))
        y = point.y() - h - 10 if top_side else point.y() + 10
        box = QRectF(x, y, w, h)

        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.BG_PANEL))
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(QPen(color, 1.2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(box, 6, 6)

        painter.setFont(QFont("", 8))
        painter.setPen(QColor(theme.FG_FAINT))
        painter.drawText(QRectF(box.left() + 7, box.top() + 3, box.width() - 12, 12),
                         Qt.AlignLeft | Qt.AlignVCenter, title)

        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        if ok is False:
            painter.setPen(QColor(theme.BAD))
        else:
            painter.setPen(color)
        painter.drawText(QRectF(box.left() + 7, box.top() + 15, box.width() - 12, 16),
                         Qt.AlignLeft | Qt.AlignVCenter, text)

    # ---- 底部板号 ----
    def _paint_footer(self, painter: QPainter, rect: QRectF) -> None:
        painter.setFont(QFont("", 8))
        painter.setPen(QColor(theme.FG_FAINT))
        painter.drawText(QRectF(0, rect.bottom() + 12, self.width(), 16),
                         Qt.AlignCenter, self._board_text)
