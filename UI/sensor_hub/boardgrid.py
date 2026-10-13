# -*- coding: utf-8 -*-
"""
boardgrid.py —— 多板号总览：地板瓦片墙

每一块板子 = 一个“迷你漏缝地板”瓦片（和左侧大图同款画法）：

    ┌──────────────┐
    │ 板 7    绿色边框 │   ← 顶部：板号
    │   ●        ●  │   ← 四角 = 4 个传感器点，光晕颜色/大小随该路数值变化
    │  ▬▬▬▬▬▬▬▬▬▬  │
    │  ▬▬▬▬▬▬▬▬▬▬  │   ← 漏缝地板（40:60 比例）
    │   ●        ●  │
    └──────────────┘

    · 一块板子一个瓦片，按板号自动平铺、自动换行（窗口越大一行放越多）
    · 点任何一块即可在左侧大图里查看它的 4 路明细
    · 久未更新的板子整块变灰并标“离线”

为什么不用文字热力条：多板场景下“一眼看哪块、哪一角异常”比看数字更直接，
数字明细交给左侧大地板和表格。
"""

from __future__ import annotations

from collections import deque
import time
import math
from typing import Deque, Dict, List, Optional, Tuple

from PyQt5.QtCore import QRect, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt5.QtWidgets import QSizePolicy, QWidget

from . import theme

OFFLINE_SECONDS = 15.0      # 超过这么久没更新就算离线
SCALE_CAPACITY = 200        # 每路传感器的历史采样，用于算颜色标尺
CELL_MIN_W = 132
CELL_MIN_H = 154
FLOOR_RATIO = 40.0 / 60.0   # 地板 40:60


class BoardGrid(QWidget):
    """多板号总览：每块板子一个小漏缝地板瓦片。"""

    boardClicked = pyqtSignal(int)      # 点中某块板子，发出板号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cell_w = CELL_MIN_W
        self.cell_h = CELL_MIN_H
        self._header_h = 0
        self._search = ""
        self._online_only = False
        self._boards: Dict[int, dict] = {}
        self._scales: Dict[str, Deque[float]] = {
            "s%d" % (i + 1): deque(maxlen=SCALE_CAPACITY) for i in range(4)
        }
        self._selected: Optional[int] = None
        self._rects: List[Tuple[QRect, int]] = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("每块板子一个小漏缝地板：四角光晕 = 该路数值高低；点击可在左侧查看明细")

    # ---------------- 数据 ----------------
    def update_board(self, board_id: int, values: Dict[str, float], ts: float) -> None:
        entry = self._boards.get(board_id)
        if entry is None:
            entry = {"values": {}, "ts": 0.0}
            self._boards[board_id] = entry
        entry["values"] = {k: values.get(k) for k in ("s1", "s2", "s3", "s4")}
        entry["ts"] = ts
        for key in ("s1", "s2", "s3", "s4"):
            value = entry["values"].get(key)
            if value is not None:
                self._scales[key].append(float(value))

    def clear(self) -> None:
        self._boards.clear()
        for queue in self._scales.values():
            queue.clear()
        self._selected = None
        self._rects.clear()
        self.refresh_layout()
        self.update()

    def board_count(self) -> int:
        return len(self._boards)

    def set_selected(self, board_id: Optional[int]) -> None:
        self._selected = board_id
        self.update()

    def online_count(self, now=None) -> int:
        now = time.time() if now is None else now
        return sum(now - entry["ts"] <= OFFLINE_SECONDS for entry in self._boards.values())

    def visible_boards(self):
        now = time.time()
        return [board for board in sorted(self._boards)
                if self._search in str(board)
                and (not self._online_only or now - self._boards[board]["ts"] <= OFFLINE_SECONDS)]

    def set_search(self, text):
        self._search = text.strip()
        self.refresh_layout()
        self.update()

    def set_online_only(self, enabled):
        self._online_only = enabled
        self.refresh_layout()
        self.update()

    def refresh_layout(self):
        rows = math.ceil(len(self.visible_boards()) / self._columns())
        height = max(180, rows * self.cell_h + 12)
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
        # Hit testing must use the current filter, even before the next paint.
        self._rects = [(self._cell_rect(i), board) for i, board in enumerate(self.visible_boards())]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_layout()

    def keyPressEvent(self, event):
        boards = self.visible_boards()
        if not boards:
            return super().keyPressEvent(event)
        steps = {Qt.Key_Left: -1, Qt.Key_Right: 1,
                 Qt.Key_Up: -self._columns(), Qt.Key_Down: self._columns()}
        if event.key() in steps:
            index = boards.index(self._selected) if self._selected in boards else 0
            index = max(0, min(len(boards) - 1, index + steps[event.key()]))
            self.set_selected(boards[index])
            self.boardClicked.emit(boards[index])
            event.accept()
        else:
            super().keyPressEvent(event)

    # ---------------- 颜色标尺 ----------------
    def _range(self, key: str) -> Tuple[float, float]:
        data = self._scales[key]
        if not data:
            return -1.0, 1.0
        low, high = min(data), max(data)
        if high - low < 1e-9:
            return low - 1.0, high + 1.0
        margin = (high - low) * 0.05
        return low - margin, high + margin

    def _ratio(self, key: str, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        low, high = self._range(key)
        if high - low < 1e-9:
            return 0.5
        return max(0.0, min(1.0, (float(value) - low) / (high - low)))

    # ---------------- 布局 ----------------
    def _columns(self) -> int:
        usable = max(self.width() - 12, CELL_MIN_W)
        return max(1, usable // self.cell_w)

    def _cell_rect(self, index: int) -> QRect:
        columns = self._columns()
        row, col = divmod(index, columns)
        return QRect(6 + col * self.cell_w,
                     self._header_h + 6 + row * self.cell_h,
                     self.cell_w - 5, self.cell_h - 5)

    # ---------------- 鼠标 ----------------
    def mousePressEvent(self, event) -> None:      # noqa: N802
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.refresh_layout()
        for rect, board_id in self._rects:
            if rect.contains(event.pos()):
                self._selected = board_id
                self.boardClicked.emit(board_id)
                self.update()
                return
        super().mousePressEvent(event)

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:      # noqa: N802
        try:
            self._paint()
        except Exception as exc:               # 绘制异常也不能让界面崩
            painter = QPainter(self)
            painter.fillRect(self.rect(), theme.qcolor(theme.BG_DEEP, 150))
            painter.setPen(theme.qcolor(theme.BAD))
            painter.drawText(self.rect(), Qt.AlignCenter, "板号总览绘制失败：%s" % exc)

    def _paint(self) -> None:
        import time as _time

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), theme.qcolor(theme.BG_DEEP, 140))

        boards = self.visible_boards()
        if not boards:
            painter.setPen(theme.qcolor(theme.FG_FAINT))
            painter.setFont(QFont("", 10))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "没有符合条件的设备" if self._boards else "等待设备连接\n启动演示模式，预览 42 块称重板")
            self._rects = []
            return

        now = _time.time()
        painter.setFont(QFont("", 8))
        painter.setPen(theme.qcolor(theme.FG_FAINT))

        self._rects = []
        for index, board_id in enumerate(boards):
            rect = self._cell_rect(index)
            if rect.top() > self.height():
                break
            entry = self._boards[board_id]
            offline = (now - entry["ts"]) > OFFLINE_SECONDS
            self._paint_tile(painter, rect, board_id, entry, offline)
            self._rects.append((rect, board_id))

    # ---- 单个瓦片 ----
    def _paint_tile(self, painter: QPainter, rect: QRect, board_id: int,
                    entry: dict, offline: bool) -> None:
        selected = (self._selected == board_id)

        # 玻璃瓦片底
        painter.setPen(QPen(theme.qcolor(theme.ACCENT) if selected
                            else theme.qcolor(theme.GLASS_LINE),
                            2.0 if selected else 1.0))
        painter.setBrush(theme.qcolor(theme.BG_CARD) if not offline
                         else theme.qcolor(theme.BG_PANEL))
        painter.drawRoundedRect(rect, 9, 9)

        # 板号
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.setPen(theme.qcolor(theme.ACCENT) if not offline
                       else theme.qcolor(theme.FG_FAINT))
        painter.drawText(rect.left() + 10, rect.top() + 19, "BOARD %02d" % board_id)
        painter.setFont(QFont("", 8))
        painter.setPen(theme.qcolor(theme.FG_FAINT if offline else theme.OK))
        painter.drawText(rect.adjusted(5, 5, -10, -5), Qt.AlignTop | Qt.AlignRight,
                         "离线" if offline else "在线")

        # ---- 迷你漏缝地板（40:60，居中）----
        pad = 15
        avail_w = max(rect.width() - 2 * pad, 10)
        avail_h = max(rect.height() - 62, 10)
        scale = min(avail_w / 40.0, avail_h / 60.0)
        fw, fh = 40.0 * scale, 60.0 * scale
        floor = QRectF(rect.left() + (rect.width() - fw) / 2.0,
                       rect.top() + 30, fw, fh)

        # 地板底 + 漏缝条
        grad = QLinearGradient(floor.topLeft(), floor.bottomRight())
        grad.setColorAt(0.0, theme.qcolor(theme.BG_PANEL))
        grad.setColorAt(1.0, theme.qcolor(theme.FLOOR_LIGHT))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(floor, 4, 4)

        slats = 7
        pitch = floor.height() / slats
        slat_h = pitch * 0.62
        for i in range(slats):
            y = floor.top() + i * pitch
            painter.setBrush(theme.qcolor(theme.FLOOR_MID) if not offline
                             else theme.qcolor(theme.LINE_SOFT))
            painter.drawRect(QRectF(floor.left(), y, floor.width(), slat_h))
            painter.setBrush(theme.qcolor(theme.ACCENT, 45) if not offline
                             else theme.qcolor(theme.OFFLINE, 90))
            painter.drawRect(QRectF(floor.left(), y + slat_h, floor.width(),
                                    max(0.8, (pitch - slat_h) * 0.45)))

        painter.setPen(QPen(theme.qcolor(theme.ACCENT, 170) if not offline
                            else theme.qcolor(theme.OFFLINE), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(floor, 4, 4)

        # ---- 四角传感器点 ----
        points = ((0.0, 0.0, "s1"), (1.0, 0.0, "s2"),
                  (0.0, 1.0, "s3"), (1.0, 1.0, "s4"))
        for nx, ny, key in points:
            center_x = floor.left() + floor.width() * nx
            center_y = floor.top() + floor.height() * ny
            ratio = self._ratio(key, entry["values"].get(key))
            if ratio is None:
                color = theme.qcolor(theme.OFFLINE)
                radius = 3.0
            else:
                color = theme.qcolor(theme.OFFLINE) if offline else theme.heat_color(ratio)
                radius = 3.2 + 2.6 * ratio

            glow = QRadialGradient(center_x, center_y, radius * 3.2)
            c = QColor(color)
            c.setAlpha(105)
            glow.setColorAt(0.0, c)
            c2 = QColor(color)
            c2.setAlpha(0)
            glow.setColorAt(1.0, c2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(QRectF(center_x - radius * 3.2, center_y - radius * 3.2,
                                       radius * 6.4, radius * 6.4))

            painter.setBrush(color)
            painter.drawEllipse(QRectF(center_x - radius, center_y - radius,
                                       radius * 2, radius * 2))
            painter.setPen(QPen(theme.qcolor(theme.BG_PANEL), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QRectF(center_x - radius, center_y - radius,
                                       radius * 2, radius * 2))

        # ---- 底部：四路数值（小字，紧凑）----
        painter.setFont(QFont("Consolas", 7))
        painter.setPen(theme.qcolor(theme.FG_DIM) if not offline
                       else theme.qcolor(theme.FG_FAINT))
        values = [entry["values"].get(k) for k in ("s1", "s2", "s3", "s4")]
        for row in range(2):
            texts = ["--" if v is None else ("%.1fk" % (v / 1000) if abs(v) >= 1000 else "%.0f" % v)
                     for v in values[row * 2:row * 2 + 2]]
            text = "  ·  ".join(texts)
            painter.drawText(QRect(rect.left() + 5, rect.bottom() - 27 + row * 13,
                                  rect.width() - 10, 13), Qt.AlignCenter,
                             painter.fontMetrics().elidedText(text, Qt.ElideRight, rect.width() - 10))

    def mouseMoveEvent(self, event):
        for rect, board_id in self._rects:
            if rect.contains(event.pos()):
                entry = self._boards[board_id]
                values = entry["values"]
                self.setToolTip("板号 %s\n%s\n最后更新 %s" % (
                    board_id, " / ".join("S%d: %s" % (i + 1, values.get("s%d" % (i + 1))) for i in range(4)),
                    time.strftime("%H:%M:%S", time.localtime(entry["ts"]))))
                break
        else:
            self.setToolTip("点击设备查看完整读数；k 表示千计数")
        super().mouseMoveEvent(event)
