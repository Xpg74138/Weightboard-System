"""Shared design tokens and styling for the monitoring workspace."""
from __future__ import annotations
import re
from PyQt5.QtGui import QColor, QFont, QFontDatabase

BG = "#f3f6fa"
BG_PANEL = "#ffffff"
BG_CARD = "#f7f9fc"
BG_DEEP = "#ffffff"
LINE = "#dce4ed"
LINE_SOFT = "#edf1f6"
GLASS_LINE = LINE
FG = "#172b40"
FG_DIM = "#52677c"
FG_FAINT = "#74869a"
ACCENT = "#087f8c"
ACCENT2 = "#315dc4"
ACCENT_SOFT = "#e7f4f5"
OK = "#168466"
WARN = "#ad6b0c"
BAD = "#cc4254"
OFFLINE = "#c2ccd7"
SENSOR_ACCENTS = ("#087f8c", "#4269cf", "#8c59be", "#c17b15")
FLOOR_LIGHT = "#f4f8fa"
FLOOR_MID = "#dae6eb"
FLOOR_DARK = "#bdcfd8"


def qcolor(value: str, alpha: int = 255) -> QColor:
    match = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)"
                         r"(?:\s*,\s*([\d.]+)\s*)?\)", value)
    if match:
        color = QColor(*(int(float(match.group(i))) for i in (1, 2, 3)))
        color.setAlpha(int(float(match.group(4))) if match.group(4) else 255)
    else:
        color = QColor(value)
    if alpha != 255:
        color.setAlpha(alpha)
    return color


def heat_color(ratio: float) -> QColor:
    ratio = float(ratio)
    ratio = max(0.0, min(1.0, ratio)) if ratio == ratio else 0.0
    stops = ((0.0, (126, 193, 210)), (0.35, (41, 151, 161)),
             (0.65, (83, 166, 132)), (1.0, (208, 146, 44)))
    for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
        if x0 <= ratio <= x1:
            fraction = (ratio - x0) / (x1 - x0)
            return QColor(*(int(a + (b - a) * fraction) for a, b in zip(c0, c1)))
    return QColor(*stops[-1][1])


def sensor_color(index: int) -> QColor:
    return qcolor(SENSOR_ACCENTS[index % len(SENSOR_ACCENTS)])


def configure_application(app) -> None:
    app.setStyle("Fusion")
    families = set(QFontDatabase().families())
    for family in ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC",
                   "WenQuanYi Micro Hei", "DejaVu Sans"):
        if family in families:
            app.setFont(QFont(family, 9))
            break
    app.setStyleSheet(stylesheet())


STYLESHEET = """
QWidget { background: transparent; color: %(FG)s; font-size: 12px; }
QMainWindow { background: %(BG)s; }
QFrame#surface, QFrame#metricCard { background: %(BG_PANEL)s; border: 1px solid %(LINE)s; border-radius: 12px; }
QFrame#valueCard { background: %(BG_CARD)s; border: 1px solid %(LINE_SOFT)s; border-radius: 8px; }
QLabel#eyebrow { color: %(FG_FAINT)s; font-size: 11px; }
QLabel#pageTitle { font-size: 23px; font-weight: bold; }
QLabel#sectionTitle { font-size: 14px; font-weight: bold; }
QLabel#muted { color: %(FG_FAINT)s; }
QLabel#connectionBadge { background: %(BG_CARD)s; border-radius: 12px; padding: 5px 12px; color: %(FG_DIM)s; }
QLabel#connectionBadge[state="online"] { background: %(ACCENT_SOFT)s; color: %(OK)s; }
QLabel#connectionBadge[state="error"] { background: #fff0f1; color: %(BAD)s; }
QLabel#connectionBadge[state="demo"] { background: #edf1fc; color: %(ACCENT2)s; }
QGroupBox { background: %(BG_PANEL)s; border: 1px solid %(LINE)s; border-radius: 10px; margin-top: 16px; padding: 12px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QPushButton, QToolButton { background: %(BG_PANEL)s; border: 1px solid %(LINE)s; border-radius: 7px; padding: 7px 12px; color: %(FG_DIM)s; }
QPushButton:hover, QToolButton:hover { background: %(ACCENT_SOFT)s; border-color: %(ACCENT)s; color: %(ACCENT)s; }
QPushButton:pressed, QToolButton:pressed { background: #d6e9ec; }
QPushButton[role="primary"] { background: %(ACCENT)s; border-color: %(ACCENT)s; color: white; font-weight: bold; }
QPushButton[role="primary"]:hover { background: #066b76; }
QPushButton[role="danger"] { background: #fff0f1; border-color: #efbac3; color: %(BAD)s; }
QPushButton:disabled, QComboBox:disabled { color: %(FG_FAINT)s; background: %(BG_CARD)s; border-color: %(LINE_SOFT)s; }
QPushButton:checked, QToolButton:checked { background: %(ACCENT_SOFT)s; color: %(ACCENT)s; border-color: %(ACCENT)s; }
QComboBox, QLineEdit { background: %(BG_PANEL)s; border: 1px solid %(LINE)s; border-radius: 7px; padding: 7px 9px; selection-background-color: %(ACCENT)s; selection-color: white; }
QComboBox:hover, QComboBox:focus, QLineEdit:focus { border-color: %(ACCENT)s; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: white; color: %(FG)s; border: 1px solid %(LINE)s; selection-background-color: %(ACCENT_SOFT)s; selection-color: %(ACCENT)s; padding: 4px; }
QCheckBox { spacing: 6px; color: %(FG_DIM)s; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #b6c5d3; border-radius: 4px; background: white; }
QCheckBox::indicator:checked { background: %(ACCENT)s; border-color: %(ACCENT)s; }
QCheckBox::indicator:hover { border-color: %(ACCENT)s; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { padding: 10px 18px; margin-right: 12px; color: %(FG_FAINT)s; border-bottom: 2px solid transparent; background: transparent; }
QTabBar::tab:selected { color: %(ACCENT)s; border-bottom: 2px solid %(ACCENT)s; font-weight: bold; }
QTabBar::tab:hover { color: %(FG)s; }
QTableWidget { background: white; alternate-background-color: %(BG_CARD)s; border: none; gridline-color: %(LINE_SOFT)s; selection-background-color: %(ACCENT_SOFT)s; selection-color: %(FG)s; }
QHeaderView::section { background: %(BG_CARD)s; color: %(FG_DIM)s; border: none; border-bottom: 1px solid %(LINE)s; padding: 9px 8px; font-weight: bold; }
QTableWidget::item { padding: 5px 8px; }
QTableCornerButton::section { background: %(BG_CARD)s; border: none; }
QPlainTextEdit { background: %(BG_CARD)s; border: 1px solid %(LINE_SOFT)s; border-radius: 8px; color: %(FG_DIM)s; padding: 6px; }
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: transparent; width: 10px; }
QSplitter::handle:hover { background: %(LINE)s; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle { background: #c5d1dc; border-radius: 3px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:hover { background: #91a6ba; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QStatusBar { background: %(BG)s; color: %(FG_FAINT)s; border: none; }
QStatusBar::item { border: none; }
QMenu { background: white; border: 1px solid %(LINE)s; padding: 6px; }
QMenu::item { padding: 8px 24px; border-radius: 5px; }
QMenu::item:selected { background: %(ACCENT_SOFT)s; color: %(ACCENT)s; }
QToolTip { background: %(FG)s; color: white; border: none; padding: 6px 9px; }
"""


def stylesheet() -> str:
    return STYLESHEET % globals()


def paint_backdrop(widget) -> None:
    from PyQt5.QtGui import QPainter
    painter = QPainter(widget)
    painter.fillRect(widget.rect(), qcolor(BG))
