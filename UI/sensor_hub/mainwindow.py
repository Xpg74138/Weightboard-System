"""Acquisition controller and per-device state for the monitoring workspace."""
from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import List, Optional

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox, QTableWidgetItem

from . import APP_NAME, PARSER_VERSION, __version__, theme
from .boardgrid import OFFLINE_SECONDS
from .parser import Frame, FrameParser, ParseConfig, SENSOR_KEYS
from .reader import SerialReader, port_details
from .storage import CsvRecorder
from .panels import MainWindowView
from .titlebar import TitleBar
from .widgets import set_role
from .paths import artifact_path

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".sensor_hub.json")
TABLE_MAX_ROWS = 500
LOG_EVERY_N = 10            # 多板场景下每 N 帧在日志区显示 1 帧（CSV 仍逐帧记录）
BAT_EMPTY_MV = 3300.0        # 与 main.c 的 BAT_EMPTY_MV 一致
BATTERY_HISTORY = 300        # 用于估算放电速率的历史采样点数

class MainWindow(QMainWindow, MainWindowView):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("%s v%s  [%s]" % (APP_NAME, __version__, PARSER_VERSION))
        # 去掉系统那层"模板"边框，用自绘标题栏
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(960, 640)
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        self.resize(min(1440, max(960, available.width() - 48)) if available else 1440,
                    min(980, max(640, available.height() - 48)) if available else 980)

        self.reader: Optional[SerialReader] = None
        self.parser = FrameParser(self._load_config())
        self.recorder = CsvRecorder()
        self.frame_count = 0        # 收到的【数据帧】数（不含板子启动提示行）
        self.bad_count = 0          # 无法解析的行
        self.text_count = 0         # 板子启动提示行
        self.seen_boards = set()    # 收到过数据的板号集合
        self.started_at = time.time()
        self.last_frame: Optional[Frame] = None
        self._log_seq = 0            # 日志节流计数
        self._log_skipped = 0        # 被节流掉的行数
        # (板子毫秒, 电池mV) 历史，用于推算电池还能用多久
        self.battery_history: List[tuple] = []
        self._parse_log = None       # 解析日志文件（--parse-log 打开）
        self._selected_board = None
        self._histories = {}
        self._pending_frames = deque(maxlen=TABLE_MAX_ROWS)

        self._build_ui()
        self._build_menu()

        # 自定义标题栏：标题 + 最小化/最大化/关闭
        self.title_bar = TitleBar(self)
        self.centralWidget().layout().insertWidget(0, self.title_bar)

        # 界面按 5Hz 刷新，避免高频数据把 UI 卡住
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(200)
        self.ui_timer.timeout.connect(self._refresh_ui)
        self.ui_timer.start()

        self._refresh_ports()

    # ================================================================ 界面
    # ================================================================ 串口
    def _refresh_ports(self) -> None:
        current = self.port_combo.currentText().split(" ")[0]
        self.port_combo.clear()
        details = port_details()
        for text in details:
            self.port_combo.addItem(text, text.split(" ")[0])
        if not details:
            self.port_combo.addItem("(未发现串口)")
        if current:
            for index in range(self.port_combo.count()):
                if self.port_combo.itemData(index) == current:
                    self.port_combo.setCurrentIndex(index)
                    break
        self.statusBar().showMessage("发现 %d 个串口" % len(details))

    def _selected_port(self) -> str:
        return self.port_combo.currentText().split(" ")[0].strip()

    def toggle_receive(self) -> None:
        if self.reader is not None and self.reader.isRunning():
            self.stop_receive()
        else:
            self.start_receive()

    def start_receive(self, demo: bool = False) -> None:
        if self.reader is not None:
            return
        port = self._selected_port()
        if not demo and (not port or port.startswith("(")):
            QMessageBox.warning(self, "提示", "请先选择一个串口。\n没插设备时可以用“演示模式”看效果。")
            return
        try:
            baud = int(self.baud_combo.currentText())
        except ValueError:
            QMessageBox.warning(self, "提示", "波特率必须是数字。")
            return

        self._apply_parse_config()

        self.reader = SerialReader(port if not demo else "DEMO", baud, self)
        self.reader.framing = self.framing_combo.currentData() or "line"
        self.reader.auto_reconnect = self.reconnect_check.isChecked()
        self.reader.demo = demo
        self.reader.lineReceived.connect(self.on_line)
        self.reader.statusChanged.connect(self.on_status)
        self.reader.errorOccurred.connect(self.on_error)
        reader = self.reader
        reader.finished.connect(lambda: self._reader_finished(reader))
        self.reader.start()

        self.started_at = time.time()
        self.start_btn.setText("停止接收")
        set_role(self.start_btn, "danger")
        self.demo_btn.setChecked(demo)
        self._set_connection_state("演示模式" if demo else "连接中", "demo" if demo else "idle")
        self._set_connection_controls(False)
        self._append_log("=== 开始接收：%s @ %d，组包=%s%s ==="
                         % (port, baud, self.reader.framing,
                            "（演示模式）" if demo else ""))

    def stop_receive(self) -> None:
        if self.reader is not None:
            self.reader.request_stop()
            if not self.reader.wait(3000):
                self.on_error("设备仍在停止，请稍后重试")
                return
            self.reader.deleteLater()
            self.reader = None
        self._reset_connection_controls()
        self._append_log("=== 已停止接收 ===")

    def _reader_finished(self, reader) -> None:
        if self.reader is reader:
            self.reader = None
            reader.deleteLater()
            self._reset_connection_controls()

    def _set_connection_controls(self, enabled):
        for widget in (self.port_combo, self.baud_combo, self.framing_combo,
                       self.refresh_btn, self.reconnect_check, self.parse_toggle,
                       self.delim_edit, self.auto_check):
            widget.setEnabled(enabled)

    def _reset_connection_controls(self):
        self.start_btn.setText("开始接收")
        set_role(self.start_btn, "primary")
        self.demo_btn.setChecked(False)
        self._set_connection_controls(True)
        self._set_connection_state("未连接", "idle")

    def _set_connection_state(self, text, state):
        self.connection_badge.setText("●  " + text)
        self.connection_badge.setProperty("state", state)
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)

    def toggle_demo(self) -> None:
        """演示模式开关。"""
        if self.reader is not None and self.reader.demo:
            self.stop_receive()
            return
        self.stop_receive()
        self.start_receive(demo=True)

    def on_status(self, text: str, connected: bool) -> None:
        demo = self.reader is not None and self.reader.demo
        self._set_connection_state("未连接" if self.reader is None else ("演示模式" if demo and connected else
                                   ("已连接" if connected else "等待连接")),
                                   "demo" if demo and connected else ("online" if connected else "idle"))
        self.statusBar().showMessage(text)
        self._append_log("[状态] " + text)

    def on_error(self, text: str) -> None:
        self._set_connection_state("连接异常", "error")
        self.statusBar().showMessage(text)
        self._append_log("[错误] " + text)

    # ================================================================ 数据
    def on_line(self, line: str) -> None:
        frame = self.parser.parse(line, ts=time.time())
        if frame.status == "text":
            # 板子上电提示行（BOOT_SYSTICK / ADC_INIT_OK）：只记日志，不算数据帧
            self.text_count += 1
            self._append_log("[板子] " + line)
            return
        if frame.status == "raw":
            self.bad_count += 1
        self.frame_count += 1
        self.last_frame = frame
        if frame.board_id is not None:
            self.seen_boards.add(frame.board_id)
            self._board_cache[frame.board_id] = (frame, frame.ts)
            # 板号总览：按板号更新那一块瓦片
            self.board_grid.update_board(frame.board_id, frame.values, frame.ts)
        # 单板模式（旧协议无板号）也要能看到数据，统一按板号 0 归入总览
        if frame.board_id is None and any(frame.get(k) is not None for k in SENSOR_KEYS):
            self._board_cache[0] = (frame, frame.ts)
            self.board_grid.update_board(0, frame.values, frame.ts)
        self._pending_frames.append(frame)
        board_id = frame.board_id if frame.board_id is not None else 0
        if any(frame.get(k) is not None for k in SENSOR_KEYS):
            was_selected = self._selected_board == board_id
            self._histories.setdefault(board_id, deque(maxlen=self.chart.capacity)).append(frame)
            if self._selected_board is None:
                self._on_board_clicked(board_id)
            elif self._selected_board == board_id:
                self.chart.add_sample(self._chart_values(frame))
            if was_selected and frame.ms is not None and frame.battery_mv is not None:
                if self.battery_history and frame.ms < self.battery_history[-1][0]:
                    self.battery_history.clear()
                self.battery_history.append((frame.ms, frame.battery_mv))
                self.battery_history = self.battery_history[-BATTERY_HISTORY:]
        if self._parse_log is not None:
            self._parse_log.write(
                "%s | %s | board=%s | %s | seq=%s ms=%s mask=%s w=%s batt_mv=%s pct=%s\n"
                % (time.strftime("%H:%M:%S"), frame.status, frame.board_id, frame.raw,
                   frame.seq, frame.ms, frame.flag, frame.weight_g,
                   frame.battery_mv, frame.get("batt_pct")))
            self._parse_log.flush()
        if self.recorder.is_open:
            self.recorder.write(frame)

    def enable_parse_log(self, path: str) -> None:
        """把每一帧的解析结果写入文件，方便排查“界面显示不对”这类问题。"""
        try:
            self._parse_log = open(path, "a", encoding="utf-8")
            self._parse_log.write("\n===== parse log @ %s =====\n"
                                  % time.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as exc:
            self._parse_log = None
            self._append_log("[错误] 无法写解析日志：%s" % exc)

    def _on_board_clicked(self, board_id: int) -> None:
        """点中总览里的某块板子：左侧大地板切换显示该板的数据。"""
        cached = self._board_cache.get(board_id)
        if not cached:
            return
        self._selected_board = board_id
        self.board_grid.set_selected(board_id)
        visible = self.board_grid.visible_boards()
        if board_id in visible:
            rect = self.board_grid._cell_rect(visible.index(board_id))
            self.board_scroll.ensureVisible(rect.center().x(), rect.center().y(), 20, self.board_grid.cell_h // 2)
        history = self._histories.get(board_id, ())
        self.chart.set_samples(self._chart_values(frame) for frame in history)
        self.battery_history = []
        for frame in history:
            if frame.ms is not None and frame.battery_mv is not None:
                if self.battery_history and frame.ms < self.battery_history[-1][0]:
                    self.battery_history.clear()
                self.battery_history.append((frame.ms, frame.battery_mv))
        self.battery_history = self.battery_history[-BATTERY_HISTORY:]
        self._show_frame(cached[0])
        self._update_stats()
        self.statusBar().showMessage("正在查看 板号 %s 的数据" % board_id)

    @staticmethod
    def _chart_values(frame):
        values = dict(frame.values)
        values["batt_v"] = frame.battery_mv
        return values

    def _refresh_ui(self) -> None:
        # Recompute online status even when the serial stream becomes idle.
        self.board_grid.refresh_layout()
        self.board_grid.update()
        if self._pending_frames:
            self.table.setUpdatesEnabled(False)
            while self._pending_frames:
                frame = self._pending_frames.popleft()
                self._append_table_row(frame)
                self._append_log(frame.raw)
            self.table.setUpdatesEnabled(True)
        cached = self._board_cache.get(self._selected_board)
        if cached:
            self._show_frame(cached[0])
        self._update_stats()

    def _show_frame(self, frame) -> None:

        for key in SENSOR_KEYS:
            self.cards[key].set_value(frame.get(key), "%.0f")
        self.batt_v_card.set_value(frame.battery_mv, "%.0f")      # 毫伏
        self.batt_pct_card.set_value(frame.get("batt_pct"), "%.0f")

        # 4 路 HX711 读取状态（来自 OK 掩码）：小圆点 + 文字
        ok_map = {}
        for index in range(4):
            ok = frame.channel_ok(index)
            key = SENSOR_KEYS[index]
            ok_map[key] = ok
            label = self.channel_labels[index]
            dot = self.channel_dots[index]
            if ok is None:
                label.setText("-")
                label.setStyleSheet("font-weight:bold;color:%s;" % theme.FG_FAINT)
                dot.setStyleSheet("color:%s;" % theme.FG_FAINT)
            elif ok:
                label.setText("正常")
                label.setStyleSheet("font-weight:bold;color:%s;" % theme.OK)
                dot.setStyleSheet("color:%s;" % theme.OK)
            else:
                label.setText("失败")
                label.setStyleSheet("font-weight:bold;color:%s;" % theme.BAD)
                dot.setStyleSheet("color:%s;" % theme.BAD)
        described = frame.ok_channels()
        if described == "4 路全部正常":
            described = "4/4 正常"
        self.mask_label.setText("掩码 0x%s · %s" % (frame.flag or "--", described or "未知"))

        # ---- 漏缝地板可视化 ----
        board_text = ("板号 %s" % frame.board_id) if frame.board_id is not None else "单板数据"
        self.floor_view.set_board_text(
            "%s · %s" % (board_text, time.strftime("%H:%M:%S", time.localtime(frame.ts))))
        self.floor_view.set_values({k: frame.get(k) for k in SENSOR_KEYS})
        self.floor_view.set_channel_ok(ok_map)
        offline = time.time() - frame.ts > OFFLINE_SECONDS
        self.detail_label.setText("%s  ·  %s" % (board_text, "离线 · 显示最后数据" if offline else "在线"))
        self.detail_label.setStyleSheet("color:%s;font-weight:bold;" % (theme.FG_FAINT if offline else theme.ACCENT))

    def _append_table_row(self, frame: Frame) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        battery_mv = frame.battery_mv
        values = [
            time.strftime("%H:%M:%S", time.localtime(frame.ts)),
            "" if frame.board_id is None else str(frame.board_id),
            "" if frame.seq is None else str(frame.seq),
            "" if frame.ms is None else str(frame.ms),
            frame.flag or "",
            _fmt(frame.get("s1"), "%.0f"), _fmt(frame.get("s2"), "%.0f"),
            _fmt(frame.get("s3"), "%.0f"), _fmt(frame.get("s4"), "%.0f"),
            "" if battery_mv is None else "%.0f" % battery_mv,
            _fmt(frame.get("batt_pct"), "%.0f"),
        ]
        for column, text in enumerate(values):
            item = QTableWidgetItem(text)
            if column >= 1:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item.setToolTip(frame.raw)
            self.table.setItem(row, column, item)
        if self.table.rowCount() > TABLE_MAX_ROWS:
            self.table.removeRow(0)
        self.table.scrollToBottom()

    def _update_stats(self) -> None:
        elapsed = max(time.time() - self.started_at, 1e-6)
        self.metrics["online"].set_value(self.board_grid.online_count(), "%.0f")
        self.metrics["frames"].set_value(self.frame_count, "%.0f")
        self.metrics["rate"].set_value(self.frame_count / elapsed, "%.1f")
        self.metrics["bad"].set_value(self.bad_count, "%.0f")
        self.metrics["online"].caption.setText("已发现 %d 块设备" % self.board_grid.board_count())
        self.grid_caption.setText("显示 %d / %d 块" % (len(self.board_grid.visible_boards()), self.board_grid.board_count()))
        self.stat_labels["frames"].setText(str(self.frame_count))
        self.stat_labels["ok"].setText(str(self.frame_count - self.bad_count))
        self.stat_labels["bad"].setText(str(self.bad_count))
        self.stat_labels["text"].setText(str(self.text_count))
        self.stat_labels["boards"].setText(
            "%d 块" % len(self.seen_boards) if self.seen_boards else "-")
        self.stat_labels["rate"].setText("%.3f 帧/秒" % (self.frame_count / elapsed))
        self.stat_labels["bytes"].setText(
            str(self.reader.bytes_total) if self.reader is not None else "0")
        frame = self._board_cache.get(self._selected_board, (None,))[0]
        self.stat_labels["seq"].setText(
            "-" if not frame or frame.seq is None
            else str(frame.seq))
        self.stat_labels["board_ms"].setText(
            "-" if not frame or frame.ms is None
            else str(frame.ms))
        self.stat_labels["flag"].setText(
            (frame.flag or "-") if frame else "-")
        self.stat_labels["source"].setText(frame.source if frame else "-")
        self.stat_labels["elapsed"].setText(self._battery_estimate(elapsed))

    def _battery_estimate(self, elapsed: float) -> str:
        """
        用板子自己的毫秒 + 电池电压推算“还能用多久”。

        原理：取最早和最晚两个采样点，算放电速率 mV/h，再按 3300mV(空) 外推。
        采样太短或电压没下降时给出“稳定/数据不足”，不瞎猜。
        """
        history = self.battery_history
        if len(history) < 20:
            return "数据不足（运行 %s）" % _duration(elapsed)
        (ms0, mv0), (ms1, mv1) = history[0], history[-1]
        span_ms = ms1 - ms0
        if span_ms <= 0 or span_ms < 60_000:            # 至少观察 1 分钟
            return "数据不足（运行 %s）" % _duration(elapsed)
        drop = mv0 - mv1
        if drop <= 1:                                   # 几乎没掉电
            return "电压稳定（已观察 %s）" % _duration(span_ms / 1000.0)
        rate_mv_per_h = drop / (span_ms / 3600000.0)
        remaining_h = (mv1 - BAT_EMPTY_MV) / rate_mv_per_h
        if remaining_h <= 0:
            return "已到空电阈值"
        return "约 %.1f 小时（放电 %.1f mV/h）" % (remaining_h, rate_mv_per_h)

    def _append_log(self, text: str) -> None:
        """
        写原始日志。

        多板场景下每秒可能几十上百帧，全部写进日志区会把界面刷爆、也看不清。
        所以做节流：前 20 帧照常显示，之后每 N 帧只显示 1 帧，并提示跳过多少行。
        （CSV 记录和板号总览不受影响，都是每帧都处理的）
        """
        self._log_seq += 1
        if self._log_seq > 20 and (self._log_seq % LOG_EVERY_N) != 0:
            self._log_skipped += 1
            return
        if self._log_skipped:
            self.log_view.appendPlainText(
                time.strftime("[%H:%M:%S] ") + "…… 省略了 %d 帧（多板节流，每 %d 帧显示 1 帧）"
                % (self._log_skipped, LOG_EVERY_N))
            self._log_skipped = 0
        self.log_view.appendPlainText(time.strftime("[%H:%M:%S] ") + text)

    def clear_data(self) -> None:
        self.table.setRowCount(0)
        self.chart.clear()
        self.board_grid.clear()
        self.floor_view.clear()
        self.log_view.clear()
        self.frame_count = 0
        self.bad_count = 0
        self.text_count = 0
        self.last_frame = None
        self.battery_history.clear()
        self.seen_boards.clear()
        self._board_cache.clear()
        self._histories.clear()
        self._pending_frames.clear()
        self._selected_board = None
        self.detail_label.setText("等待设备数据")
        for card in list(self.cards.values()) + [self.batt_v_card, self.batt_pct_card]:
            card.set_value(None)
        for index in range(4):
            self.channel_labels[index].setText("—")
            self.channel_labels[index].setStyleSheet("color:%s;" % theme.FG_FAINT)
            self.channel_dots[index].setStyleSheet("color:%s;" % theme.FG_FAINT)
        self.mask_label.setText("等待读取状态")
        self._log_seq = 0
        self._log_skipped = 0
        self.started_at = time.time()
        for label in self.stat_labels.values():
            label.setText("-")
        self._update_stats()
        self.statusBar().showMessage("已清空数据")

    # ================================================================ 记录
    def _toggle_record(self, checked: bool) -> None:
        if checked:
            default = artifact_path("records", "sensor_data.csv")
            path, _ = QFileDialog.getSaveFileName(self, "选择 CSV 记录文件", default,
                                                  "CSV 文件 (*.csv)")
            if not path:
                self.record_check.setChecked(False)
                return
            self.recorder.open(path)
            self._append_log("=== 开始记录：%s ===" % path)
            self.statusBar().showMessage("记录中：%s" % path)
        else:
            self.recorder.close()
            self._append_log("=== 停止记录 ===")

    def _export_table(self) -> None:
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "提示", "表格里还没有数据。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出表格", artifact_path("records", "table_export.csv"),
                                              "CSV 文件 (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            headers = [self.table.horizontalHeaderItem(i).text()
                       for i in range(self.table.columnCount())]
            handle.write(",".join(headers) + "\n")
            for row in range(self.table.rowCount()):
                cells = []
                for column in range(self.table.columnCount()):
                    item = self.table.item(row, column)
                    text = item.text() if item else ""
                    if "," in text or '"' in text:
                        text = '"%s"' % text.replace('"', '""')
                    cells.append(text)
                handle.write(",".join(cells) + "\n")
        self.statusBar().showMessage("已导出：%s" % path)

    # ================================================================ 配置
    def _apply_parse_config(self) -> None:
        config = self.parser.config
        config.delimiter = self.delim_edit.text() or ","
        config.auto_detect = self.auto_check.isChecked()
        self.parser = FrameParser(config)
        self._save_config(config)

    def _load_config(self) -> ParseConfig:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
                return ParseConfig.from_dict(json.load(handle))
        except Exception:
            return ParseConfig()

    def _save_config(self, config: ParseConfig) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
                json.dump(config.to_dict(), handle, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _about(self) -> None:
        QMessageBox.information(self, "关于", (
            "%s v%s\n\n"
            "通用串口/LoRa 传感器数据接收上位机\n"
            "支持 Windows 与 Ubuntu（依赖 Python3 + PyQt5 + pyserial）\n\n"
            "内置格式探测：\n  %s\n\n"
            "配置文件：%s" % (APP_NAME, __version__,
                              "\n  ".join(FrameParser.describe_builtin()), CONFIG_PATH)))

    # ================================================================ 收尾
    def changeEvent(self, event) -> None:      # noqa: N802
        """窗口最大化/还原时同步标题栏图标。"""
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and getattr(self, "title_bar", None):
            self.title_bar.sync_max_icon()

    def closeEvent(self, event) -> None:      # noqa: N802
        self.stop_receive()
        if self.reader is not None:
            event.ignore()
            return
        self.recorder.close()
        if self._parse_log is not None:
            self._parse_log.close()
            self._parse_log = None
        self._save_config(self.parser.config)
        event.accept()


def _fmt(value: Optional[float], pattern: str = "%.2f") -> str:
    return "" if value is None else pattern % value


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return "%d 秒" % seconds
    if seconds < 3600:
        return "%d 分 %d 秒" % (seconds // 60, seconds % 60)
    return "%d 时 %d 分" % (seconds // 3600, (seconds % 3600) // 60)
