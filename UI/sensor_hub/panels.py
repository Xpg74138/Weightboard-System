"""Monitoring workspace layout, independent of acquisition and data state."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QSizeGrip, QSplitter, QTableWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)
from . import theme
from .boardgrid import BoardGrid
from .floorview import FloorView
from .parser import SENSOR_KEYS
from .plots import SERIES, TrendChart
from .widgets import CentralWidget, MetricCard, ValueCard, set_role, surface


class MainWindowView:
    def _build_ui(self):
        central = CentralWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 0, 18, 0)
        root.setSpacing(14)

        heading = QHBoxLayout()
        titles = QVBoxLayout()
        eyebrow = QLabel("WORKSPACE / 实时采集")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("称重监控")
        title.setObjectName("pageTitle")
        titles.addWidget(eyebrow)
        titles.addWidget(title)
        heading.addLayout(titles)
        heading.addStretch()
        self.connection_badge = QLabel("●  未连接")
        self.connection_badge.setObjectName("connectionBadge")
        heading.addWidget(self.connection_badge)
        self.log_toggle = QToolButton()
        self.log_toggle.setText("运行日志")
        self.log_toggle.setCheckable(True)
        heading.addWidget(self.log_toggle)
        root.addLayout(heading)
        root.addWidget(self._build_toolbar())

        metrics = QHBoxLayout()
        self.metrics = {}
        for key, title, unit, caption in (
            ("online", "在线设备", "块", "15 秒无更新判为离线"),
            ("frames", "接收数据", "帧", "本次采集累计"),
            ("rate", "平均帧率", "帧 / 秒", "从开始接收计时"),
            ("bad", "解析异常", "帧", "无法识别的数据"),
        ):
            card = MetricCard(title, unit, caption)
            card.set_value(0, "%.0f")
            self.metrics[key] = card
            metrics.addWidget(card, 1)
        root.addLayout(metrics)

        self.middle = QSplitter(Qt.Horizontal)
        right = self._build_right_panel()
        self.middle.addWidget(self._build_left_panel())
        self.middle.addWidget(right)
        self.middle.setChildrenCollapsible(False)
        self.middle.setStretchFactor(0, 0)
        self.middle.setStretchFactor(1, 1)
        self.middle.setSizes([360, 900])
        root.addWidget(self.middle, 1)

        self.log_box, log_layout = surface("运行日志", "多板数据自动节流；CSV 仍逐帧记录。")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setFixedHeight(85)
        log_layout.addWidget(self.log_view)
        self.log_box.hide()
        self.log_toggle.toggled.connect(self.log_box.setVisible)
        root.addWidget(self.log_box)
        self.size_grip = QSizeGrip(self)
        self.statusBar().addPermanentWidget(QLabel("WB 协议 v2  ·  USB / LoRa"))
        self.statusBar().addPermanentWidget(self.size_grip)
        self.statusBar().showMessage("就绪 · 连接设备或启动演示")

    def _build_toolbar(self):
        box, layout = surface("设备连接")
        # Two rows keep connection settings readable at smaller desktop sizes.
        row = QHBoxLayout()
        row.addWidget(QLabel("串口"))
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumWidth(180)
        row.addWidget(self.port_combo, 1)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._refresh_ports)
        row.addWidget(self.refresh_btn)
        row.addWidget(QLabel("波特率"))
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems([str(b) for b in (9600, 115200, 57600, 38400, 19200,
                                                  4800, 2400, 230400, 460800, 921600)])
        row.addWidget(self.baud_combo)
        row.addWidget(QLabel("组包"))
        self.framing_combo = QComboBox()
        self.framing_combo.addItem("按行", "line")
        self.framing_combo.addItem("按空闲间隔", "gap")
        row.addWidget(self.framing_combo)
        self.start_btn = QPushButton("开始接收")
        self.start_btn.setMinimumWidth(108)
        set_role(self.start_btn, "primary")
        self.start_btn.clicked.connect(self.toggle_receive)
        row.addWidget(self.start_btn)
        self.demo_btn = QPushButton("演示模式")
        self.demo_btn.setCheckable(True)
        self.demo_btn.setToolTip("无需硬件，模拟 42 块称重板")
        self.demo_btn.clicked.connect(self.toggle_demo)
        row.addWidget(self.demo_btn)
        layout.addLayout(row)
        options = QHBoxLayout()
        self.reconnect_check = QCheckBox("自动重连")
        self.reconnect_check.setChecked(True)
        self.record_check = QCheckBox("记录 CSV")
        self.record_check.toggled.connect(self._toggle_record)
        options.addWidget(self.reconnect_check)
        options.addWidget(self.record_check)
        options.addStretch()
        self.parse_toggle = QToolButton()
        self.parse_toggle.setText("解析设置")
        self.parse_toggle.setCheckable(True)
        options.addWidget(self.parse_toggle)
        layout.addLayout(options)
        self.parse_box = QWidget()
        parse = QHBoxLayout(self.parse_box)
        parse.setContentsMargins(0, 0, 0, 0)
        parse.addWidget(QLabel("分隔符"))
        self.delim_edit = QLineEdit(self.parser.config.delimiter)
        self.delim_edit.setMaximumWidth(70)
        parse.addWidget(self.delim_edit)
        self.auto_check = QCheckBox("自动探测帧格式")
        self.auto_check.setChecked(self.parser.config.auto_detect)
        parse.addWidget(self.auto_check)
        parse.addStretch()
        self.parse_box.hide()
        self.parse_toggle.toggled.connect(self.parse_box.setVisible)
        layout.addWidget(self.parse_box)
        return box

    def _build_left_panel(self):
        box, layout = surface("设备明细", "四角受力分布 · 原始计数（尚未标定）")
        layout.setSpacing(8)
        box.setMinimumWidth(340)
        self.detail_label = QLabel("等待设备数据")
        self.detail_label.setStyleSheet("color:%s;font-weight:bold;" % theme.ACCENT)
        layout.addWidget(self.detail_label)
        self.floor_view = FloorView(compact=True)
        layout.addWidget(self.floor_view, 1)
        values = QGridLayout()
        self.cards = {}
        for index, key in enumerate(SENSOR_KEYS):
            card = ValueCard(("前左", "前右", "后左", "后右")[index] + " · S%d" % (index + 1),
                             "", theme.SENSOR_ACCENTS[index])
            self.cards[key] = card
            values.addWidget(card, index // 2, index % 2)
        layout.addLayout(values)
        status = QHBoxLayout()
        self.channel_labels, self.channel_dots = {}, {}
        for index in range(4):
            dot, label = QLabel("●"), QLabel("—")
            dot.setStyleSheet("color:%s;" % theme.FG_FAINT)
            label.setToolTip("S%d 读取状态" % (index + 1))
            self.channel_dots[index], self.channel_labels[index] = dot, label
            status.addWidget(dot)
            status.addWidget(label)
        status.addStretch()
        layout.addLayout(status)
        self.mask_label = QLabel("等待读取状态")
        self.mask_label.setObjectName("muted")
        layout.addWidget(self.mask_label)
        battery = QHBoxLayout()
        self.batt_v_card = ValueCard("电池电压", "mV", theme.ACCENT2)
        self.batt_pct_card = ValueCard("剩余电量", "%", theme.ACCENT2)
        battery.addWidget(self.batt_v_card)
        battery.addWidget(self.batt_pct_card)
        layout.addLayout(battery)

        # Detailed diagnostics remain available without crowding the main view.
        self.stat_labels = {}
        self.diagnostics, stats = surface("采集诊断")
        grid = QGridLayout()
        for index, (key, title) in enumerate((
            ("frames", "帧数"), ("boards", "板数"), ("rate", "帧率"), ("bad", "异常"),
            ("seq", "序号"), ("board_ms", "板子毫秒"), ("flag", "掩码"), ("source", "解析方式"),
            ("elapsed", "电池估算"), ("ok", "正常帧"), ("text", "启动消息"), ("bytes", "字节"),
        )):
            grid.addWidget(QLabel(title), index, 0)
            label = QLabel("—")
            label.setWordWrap(True)
            self.stat_labels[key] = label
            grid.addWidget(label, index, 1)
        stats.addLayout(grid)
        self.diagnostic_dialog = QDialog(self)
        self.diagnostic_dialog.setWindowTitle("采集诊断")
        self.diagnostic_dialog.resize(430, 540)
        dialog_layout = QVBoxLayout(self.diagnostic_dialog)
        dialog_layout.addWidget(self.diagnostics)
        scroll = QScrollArea()
        scroll.setMinimumWidth(360)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(box)
        return scroll

    def _build_right_panel(self):
        panel, layout = surface("设备工作台")
        panel.setMinimumWidth(500)
        self.tabs = QTabWidget()
        grid_page = QWidget()
        grid_layout = QVBoxLayout(grid_page)
        grid_layout.setContentsMargins(0, 12, 0, 0)
        controls = QHBoxLayout()
        self.board_search = QLineEdit()
        self.board_search.setPlaceholderText("搜索板号，例如 12")
        self.board_search.setMaximumWidth(240)
        controls.addWidget(self.board_search)
        self.online_check = QCheckBox("仅在线")
        controls.addWidget(self.online_check)
        controls.addStretch()
        self.grid_caption = QLabel("点击设备查看明细")
        self.grid_caption.setObjectName("muted")
        controls.addWidget(self.grid_caption)
        grid_layout.addLayout(controls)
        self.board_grid = BoardGrid()
        self.board_grid.boardClicked.connect(self._on_board_clicked)
        self.board_search.textChanged.connect(self.board_grid.set_search)
        self.online_check.toggled.connect(self.board_grid.set_online_only)
        self._board_cache = {}
        self.board_scroll = QScrollArea()
        self.board_scroll.setWidgetResizable(True)
        self.board_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.board_scroll.setWidget(self.board_grid)
        grid_layout.addWidget(self.board_scroll, 1)
        hint = QLabel("青色描边 = 当前设备    ·    灰色 = 离线    ·    四角光晕 = 相对受力")
        hint.setObjectName("muted")
        grid_layout.addWidget(hint)
        self.tabs.addTab(grid_page, "板号总览")

        chart_page = QWidget()
        chart_layout = QVBoxLayout(chart_page)
        chart_layout.setContentsMargins(0, 12, 0, 0)
        caption = QLabel("当前设备 · 最近 600 帧 · 各路独立缩放，用于观察变化趋势")
        caption.setObjectName("muted")
        chart_layout.addWidget(caption)
        legend = QHBoxLayout()
        self.chart = TrendChart()
        self.legend_checks = {}
        for key, name, color in SERIES:
            check = QCheckBox(name)
            check.setChecked(True)
            check.setStyleSheet("color:%s;" % color.name())
            check.toggled.connect(lambda on, k=key: self.chart.toggle_series(k, on))
            self.legend_checks[key] = check
            legend.addWidget(check)
        legend.addStretch()
        chart_layout.addLayout(legend)
        chart_layout.addWidget(self.chart, 1)
        self.tabs.addTab(chart_page, "实时曲线")

        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(0, 12, 0, 0)
        tools = QHBoxLayout()
        note = QLabel("全部设备 · 最近 500 帧 · 完整记录请启用 CSV")
        note.setObjectName("muted")
        tools.addWidget(note)
        tools.addStretch()
        export = QPushButton("导出 CSV")
        export.clicked.connect(self._export_table)
        tools.addWidget(export)
        table_layout.addLayout(tools)
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(["时间", "板号", "序号", "板子 ms", "OK 掩码",
                                               "S1", "S2", "S3", "S4", "电池 mV", "电量 %"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setDefaultSectionSize(82)
        header.setStretchLastSection(True)
        table_layout.addWidget(self.table)
        self.tabs.addTab(table_page, "数据帧记录")
        layout.addWidget(self.tabs, 1)
        return panel

    def _build_menu(self):
        # The custom title bar provides a single menu entry point.
        self.menuBar().hide()
