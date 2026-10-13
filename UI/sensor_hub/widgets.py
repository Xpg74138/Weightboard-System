"""Reusable surfaces and numeric cards with shared theme tokens."""
from typing import Optional
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from . import theme


def surface(title: str, subtitle: str = ""):
    frame = QFrame()
    frame.setObjectName("surface")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(12)
    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    layout.addWidget(heading)
    if subtitle:
        caption = QLabel(subtitle)
        caption.setObjectName("muted")
        caption.setWordWrap(True)
        layout.addWidget(caption)
    return frame, layout


def set_role(widget, role: str) -> None:
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ValueCard(QFrame):
    def __init__(self, title: str, unit: str = "", color: str = None, parent=None):
        super().__init__(parent)
        self.setObjectName("valueCard")
        self.setMinimumHeight(64)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("muted")
        self.value_label = QLabel("—")
        self.value_label.setFont(QFont("Consolas", 18, QFont.Bold))
        self.value_label.setStyleSheet("color: %s; font-size: 22px;" % (color or theme.FG))
        self.unit_label = QLabel(unit)
        self.unit_label.setObjectName("muted")
        row = QHBoxLayout()
        row.addWidget(self.value_label)
        row.addWidget(self.unit_label, 0, Qt.AlignBottom)
        row.addStretch()
        layout.addWidget(self.title_label)
        layout.addLayout(row)

    def set_value(self, value: Optional[float], fmt: str = "%.2f") -> None:
        self.value_label.setText("—" if value is None else fmt % value)


class MetricCard(ValueCard):
    def __init__(self, title: str, unit: str, caption: str):
        super().__init__(title, unit)
        self.setObjectName("metricCard")
        self.caption = QLabel(caption)
        self.caption.setObjectName("muted")
        self.layout().addWidget(self.caption)


class CentralWidget(QWidget):
    def paintEvent(self, event):
        theme.paint_backdrop(self)
