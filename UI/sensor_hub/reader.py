# -*- coding: utf-8 -*-
"""
reader.py —— 串口读取线程

职责：
  · 在后台线程里读串口，按“行”（\\n 结尾）组包——这对本板子的 WB,...,\\r\\n 格式最稳；
    也可以切换成“按空闲间隔断包”（发送端不发换行时用）。
  · 把收到的行通过 Qt 信号发给界面，界面不会卡。
  · 支持断线自动重连（设备被拔掉/CDC 变坏状态时很有用）。
  · 支持“演示模式”：没有硬件也能看界面效果（回放内置样例数据）。

线程安全：本类只在自己的线程里碰串口，界面调用 stop()/切换参数都通过标志位，
          不做跨线程的串口操作。
"""

from __future__ import annotations

import random
import time
from typing import List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

import serial
from serial.tools import list_ports


def available_ports() -> List[str]:
    """列出系统当前串口（Windows: COMx；Linux: /dev/ttyUSB0 等）。"""
    return [p.device for p in list_ports.comports()]


def port_details() -> List[str]:
    """列出串口及其描述，给界面下拉框用。"""
    out = []
    for p in list_ports.comports():
        desc = (p.description or "").strip()
        out.append("%s — %s" % (p.device, desc) if desc else p.device)
    return out


class SerialReader(QThread):
    """后台读取串口的线程。"""

    lineReceived = pyqtSignal(str)          # 收到一行（已去掉结尾换行）
    bytesReceived = pyqtSignal(int)         # 本次读了几个字节（用于统计）
    statusChanged = pyqtSignal(str, bool)   # (状态文字, 是否已连接)
    errorOccurred = pyqtSignal(str)
    reconnecting = pyqtSignal(int)          # 重试次数

    FRAMING_LINE = "line"
    FRAMING_GAP = "gap"

    def __init__(self, port: str, baud: int = 9600, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self.framing = self.FRAMING_LINE
        self.gap = 0.15
        self.auto_reconnect = True
        self.reconnect_interval = 1.0
        self.demo = False
        self.demo_interval = 2.0

        self._running = False
        self._ser: Optional[serial.Serial] = None
        self._buffer = bytearray()
        self._last_byte_ts = 0.0
        self.bytes_total = 0
        self.lines_total = 0

    # ---------------- 对外控制 ----------------
    def request_stop(self) -> None:
        self._running = False

    # ---------------- 线程主体 ----------------
    def run(self) -> None:
        self._running = True
        if self.demo:
            self._run_demo()
            return

        retries = 0
        while self._running:
            if self._ser is None:
                if not self._open():
                    if not self.auto_reconnect:
                        break
                    retries += 1
                    self.reconnecting.emit(retries)
                    self.statusChanged.emit("等待设备 %s ..." % self.port, False)
                    self._sleep(self.reconnect_interval)
                    continue
                retries = 0
                self.statusChanged.emit("已连接 %s @ %d" % (self.port, self.baud), True)

            try:
                self._read_once()
            except Exception as exc:                      # 串口掉线
                self.errorOccurred.emit("串口读取失败：%s" % exc)
                self._close()
                self.statusChanged.emit("连接断开，等待重连 ...", False)
                if not self.auto_reconnect:
                    break
                self._sleep(self.reconnect_interval)

        self._close()
        self.statusChanged.emit("已停止", False)

    # ---------------- 打开/关闭 ----------------
    def _open(self) -> bool:
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=0.05,
                                      write_timeout=1, dsrdtr=False)
            self._buffer.clear()
            return True
        except Exception as exc:
            self.errorOccurred.emit("打开 %s 失败：%s" % (self.port, exc))
            self._ser = None
            return False

    def _close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    # ---------------- 读一帧 ----------------
    def _read_once(self) -> None:
        assert self._ser is not None
        chunk = self._ser.read(4096)
        if chunk:
            self._buffer.extend(chunk)
            self._last_byte_ts = time.monotonic()
            self.bytes_total += len(chunk)
            self.bytesReceived.emit(len(chunk))
            self._emit_lines()

        if self.framing == self.FRAMING_GAP and self._buffer:
            if time.monotonic() - self._last_byte_ts >= self.gap:
                self._emit_buffer_as_line()

    def _emit_lines(self) -> None:
        """
        把缓冲区里完整的行发出去。

        行尾按 \\r\\n / \\n / 单独的 \\r 都算换行——板子用 \\r\\n，
        但只要有一个 \\r 或 \\n 没被吃掉，就会残留在下一行行首，
        把下一行的帧头污染成 "d\\rWB,..." 这种，导致解析全部错位。
        这里一并处理，从源头保证每行开头是干净的。
        """
        while True:
            index = -1
            for i, byte in enumerate(self._buffer):
                if byte in (0x0A, 0x0D):          # \n 或 \r
                    index = i
                    break
            if index < 0:
                break
            raw = bytes(self._buffer[:index])
            # 跳过连续的 \r\n 组合，避免把空行也发出去
            cut = index + 1
            while cut < len(self._buffer) and self._buffer[cut] in (0x0A, 0x0D):
                cut += 1
            del self._buffer[:cut]
            self._emit(raw)

    def _emit_buffer_as_line(self) -> None:
        """gap 模式：把缓冲区内容当成一整行发出去，并重置计时。"""
        raw = bytes(self._buffer)
        self._buffer.clear()
        self._last_byte_ts = 0.0
        if raw:
            self._emit(raw)

    def _emit(self, raw: bytes) -> None:
        text = raw.decode("utf-8", "replace").strip("\r\n").strip()
        if not text:
            return
        self.lines_total += 1
        self.lineReceived.emit(text)

    # ---------------- 演示模式 ----------------
    def _run_demo(self) -> None:
        """
        按 11 字段 WB 协议模拟 42 块板子的原始计数和电池数据。
        """
        self.statusChanged.emit("演示模式（按称重板真实格式模拟）", True)
        self._emit(b"BOOT_SYSTICK")
        self._emit(b"ADC_INIT_OK")
        seq = 1
        # Match the modern 11-field protocol and exercise the full fleet UI.
        weights = {board: [12500 + board * 40, 8300, 4200 + board * 12, 19800]
                   for board in range(1, 43)}
        while self._running:
            for board in range(1, 43):
                if not self._running:
                    break
                weights[board] = [max(0, w + random.randint(-25, 25)) for w in weights[board]]
                bat_mv = 3900 - board * 4 + random.randint(-20, 20)
                pct = max(0, min(100, (bat_mv - 3300) * 100 // (4200 - 3300)))
                line = "WB,%d,%d,%d,%02X,%d,%d,%d,%d,%d,%d" % (
                    board, seq, int(time.monotonic() * 1000) % 100000000, 0x0F,
                    weights[board][0], weights[board][1], weights[board][2], weights[board][3], bat_mv, pct)
                self._emit(line.encode())
                self.bytes_total += len(line)
                self.bytesReceived.emit(len(line))
            seq += 1
            self._sleep(self.demo_interval)
        self.statusChanged.emit("已停止", False)

    # ---------------- 工具 ----------------
    def _sleep(self, seconds: float) -> None:
        """可被 request_stop 打断的睡眠（每 100ms 检查一次）。"""
        end = time.monotonic() + max(seconds, 0)
        while self._running and time.monotonic() < end:
            time.sleep(0.1)
