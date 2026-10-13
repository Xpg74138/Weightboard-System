from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from . import __version__, theme

class TitleBar(QWidget):
    """
    与工作台主题一致的自定义标题栏。

    · 空白处按住可拖动窗口，双击切换最大化
    · 右侧提供菜单、最小化、最大化和关闭
    """

    HEIGHT = 48

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self._window = window
        self._drag_offset = None
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(
            "TitleBar { background: %s;"
            " border-bottom: 1px solid %s; }" % (theme.BG, theme.LINE))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(10)

        # 品牌标记与应用标题
        dot = QLabel("W")
        dot.setAlignment(Qt.AlignCenter)
        dot.setFixedSize(26, 26)
        dot.setStyleSheet("background:%s;color:white;border-radius:7px;font-weight:bold;font-size:16px;" % theme.ACCENT)
        layout.addWidget(dot)

        self.title_label = QLabel("Weightboard  /  传感器工作台")
        self.title_label.setStyleSheet(
            "color:%s;font-weight:bold;font-size:14px;letter-spacing:1px;"
            "background:transparent;" % theme.FG)
        layout.addWidget(self.title_label)

        self.sub_label = QLabel("v%s" % __version__)
        self.sub_label.setStyleSheet(
            "color:%s;font-size:11px;background:transparent;" % theme.FG_FAINT)
        layout.addWidget(self.sub_label)
        layout.addStretch(1)

        # 功能入口（无边框窗口下系统菜单栏不显示，这里兜住所有功能）
        self.menu_btn = self._make_button("菜单", "导出 / 清空 / 关于")
        self.menu_btn.setFixedSize(52, 26)
        layout.addWidget(self.menu_btn)

        # 窗口操作
        self.min_btn = self._make_button("_", "最小化")
        self.min_btn.clicked.connect(self._window.showMinimized)
        layout.addWidget(self.min_btn)

        self.max_btn = self._make_button("□", "最大化 / 还原")
        self.max_btn.clicked.connect(self.toggle_max)
        layout.addWidget(self.max_btn)

        self.close_btn = self._make_button("×", "关闭", danger=True)
        self.close_btn.clicked.connect(self._window.close)
        layout.addWidget(self.close_btn)

        # “菜单”按钮弹出功能列表（导出表格 / 清空数据 / 关于 / 退出）
        self.menu_btn.clicked.connect(self._show_menu)

    def _show_menu(self) -> None:
        from PyQt5.QtWidgets import QMenu

        window = self._window
        menu = QMenu(self)
        menu.addAction("导出表格为 CSV …", window._export_table)
        menu.addAction("采集诊断 …", window.diagnostic_dialog.show)
        menu.addAction("清空数据", window.clear_data)
        menu.addSeparator()
        menu.addAction("关于", window._about)
        menu.addSeparator()
        menu.addAction("退出", window.close)
        menu.exec_(self.menu_btn.mapToGlobal(QPoint(0, self.menu_btn.height() + 4)))

    def _make_button(self, text: str, tip: str, danger: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setFixedSize(38, 26)
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        hover_rgba = theme.BAD if danger else theme.ACCENT
        hover_bg = theme.qcolor(hover_rgba, 52).name(QColor.HexArgb)
        button.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,140);"
            " border:1px solid %s; border-radius:7px; color:%s;"
            " font-size:12px; font-weight:bold; padding:0; }"
            "QPushButton:hover { background-color:%s; border-color:%s; color:%s; }"
            % (theme.LINE, theme.FG_DIM, hover_bg, hover_rgba, theme.FG))
        return button

    def toggle_max(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def sync_max_icon(self) -> None:
        self.max_btn.setText("□" if not self._window.isMaximized() else "▣")

    # ---- 拖动窗口 ----
    def mousePressEvent(self, event) -> None:      # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self._window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:       # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            if self._window.isMaximized():
                self._window.showNormal()
                self.sync_max_icon()
            self._window.move(event.globalPos() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:    # noqa: N802
        self._drag_offset = None
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:    # noqa: N802
        self.toggle_max()
        event.accept()


