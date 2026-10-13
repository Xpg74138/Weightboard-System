# -*- coding: utf-8 -*-
"""
test_receiver.py —— 用假串口验证 receiver.py 的组包与显示逻辑（不需要真实硬件）。

运行：
    python -m tests.test_receiver
"""

from __future__ import annotations

import io
import sys
import time
import unittest


from tools import receiver as R  # noqa: E402


class FakeSerial:
    """最小的假串口：按脚本顺序吐出数据块，并对 read 做真实的时间延迟。"""

    def __init__(self, script, timeout=0.05):
        self.script = list(script)
        self.timeout = timeout

    @property
    def in_waiting(self):
        return len(self.script[0]) if self.script else 0

    def read(self, size=1):
        if not self.script:
            time.sleep(self.timeout)
            return b""
        chunk = self.script[0]
        if len(chunk) <= size:
            self.script.pop(0)
            return chunk
        self.script[0] = chunk[size:]
        return chunk[:size]

    @property
    def remaining(self):
        return len(self.script)


def parse(args_list):
    """用给定参数解析命令行。"""
    return R.build_parser().parse_args(args_list)


class TestPacketReader(unittest.TestCase):
    def test_gap_framing_splits_packets(self):
        """串口上分两次吐字节 + 中间较长空闲 => 断成两包（模拟 LoRa 两包数据）。"""
        ser = FakeSerial([b"ABCD", b"EF"], timeout=0.05)
        rd = R.PacketReader(ser, gap=0.02, framing="gap")
        first = rd.read()
        second = rd.read()
        self.assertIsNotNone(first, "第一包没断出来")
        self.assertIsNotNone(second, "第二包没断出来")
        self.assertEqual([first.data, second.data], [b"ABCD", b"EF"])

    def test_gap_framing_keeps_fast_burst_together(self):
        """连续快速到达的字节应合并成一包。"""
        ser = FakeSerial([b"HELLO-WORLD"], timeout=0.02)
        rd = R.PacketReader(ser, gap=0.15, framing="gap")
        packets = []
        deadline = time.time() + 3
        while not packets and time.time() < deadline:
            pkt = rd.read()
            if pkt is not None:
                packets.append(pkt)
        self.assertEqual([p.data for p in packets], [b"HELLO-WORLD"])

    def test_line_framing(self):
        """按换行断包，并去掉 \\r。"""
        ser = FakeSerial([b"line1\r\nline2\npar"], timeout=0.02)
        rd = R.PacketReader(ser, framing="line")
        packets = []
        deadline = time.time() + 3
        while len(packets) < 2 and time.time() < deadline:
            pkt = rd.read()
            if pkt is not None:
                packets.append(pkt)
        self.assertEqual([p.data for p in packets], [b"line1", b"line2"])

    def test_stats_counters(self):
        ser = FakeSerial([b"12345", b"678"], timeout=0.05)
        rd = R.PacketReader(ser, gap=0.02, framing="gap")
        first = rd.read()
        second = rd.read()
        self.assertIsNotNone(first, "第一包没断出来")
        self.assertIsNotNone(second, "第二包没断出来")
        self.assertEqual([first.data, second.data], [b"12345", b"678"])
        self.assertEqual(rd.packets, 2)
        self.assertEqual(rd.total_bytes, 8)


class TestPrinter(unittest.TestCase):
    def setUp(self):
        self._stdout = sys.stdout
        sys.stdout = io.StringIO()

    def tearDown(self):
        sys.stdout = self._stdout

    def _printer(self, argv):
        return R.OutputPrinter(parse(argv))

    def test_hex_and_text_display(self):
        pr = self._printer(["--port", "COM1"])
        pr.emit(R.Packet(data="温度=25.6".encode("utf-8"), rx_ts=time.time()))
        out = sys.stdout.getvalue()
        self.assertIn("HEX", out)
        self.assertIn("TEXT", out)
        self.assertIn("len=11", out)

    def test_quiet_and_hex_mode(self):
        pr = self._printer(["--port", "COM1", "-q", "--mode", "hex"])
        pr.emit(R.Packet(data=b"\x01\x02", rx_ts=time.time()))
        self.assertEqual(sys.stdout.getvalue().strip(), "HEX  01 02")

    def test_show_decoded_reassembles_split_utf8(self):
        """一包结尾被截断的汉字，下一包应被拼出来。"""
        pr = self._printer(["--port", "COM1", "-q", "--mode", "hex", "--show-decoded"])
        raw = "温度".encode("utf-8")          # 6 字节
        pr.emit(R.Packet(data=raw[:4], rx_ts=time.time()))
        pr.emit(R.Packet(data=raw[4:], rx_ts=time.time()))
        out = sys.stdout.getvalue()
        self.assertIn("UTF8 温", out)
        self.assertIn("UTF8 度", out)

    def test_gap_shown_between_packets(self):
        pr = self._printer(["--port", "COM1", "--show-gap"])
        pr.emit(R.Packet(data=b"A", rx_ts=1000.0))
        pr.emit(R.Packet(data=b"B", rx_ts=1000.5))
        self.assertIn("gap=0.500s", sys.stdout.getvalue())

    def test_stats_line(self):
        pr = self._printer(["--port", "COM1"])
        pr.emit(R.Packet(data=b"ABC", rx_ts=time.time()))
        line = pr.stats_line()
        self.assertIn("收到 1 包 / 3 字节", line)

    def test_raw_file(self):
        import os
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "lora_raw_test.bin")
        if os.path.exists(path):
            os.remove(path)
        pr = self._printer(["--port", "COM1", "--raw-file", path])
        pr.open()
        pr.write_raw_file(R.Packet(data=b"\xAA\xBB", rx_ts=time.time()))
        pr.close()
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"\xAA\xBB")
        os.remove(path)


class TestAutoBaud(unittest.TestCase):
    def test_detects_the_baud_that_has_data(self):
        """只有 57600 有数据时，auto_baud_detect 应该锁定 57600。"""
        import serial

        class BaudFake:
            """假串口：支持位置参数或关键字参数传波特率（auto_baud_detect 用的是位置参数）。"""

            def __init__(self, *a, **kw):
                self.baudrate = kw.get("baudrate", a[1] if len(a) > 1 else 9600)
                self.timeout = kw.get("timeout", 0.1)
                self.name = "FAKE"
                self._sent = False

            def read(self, size=1):
                if self.baudrate == 57600 and not self._sent:
                    self._sent = True
                    return b"WB,741,803495,0F\r\n"
                time.sleep(0.02)
                return b""

            def reset_input_buffer(self):
                pass

            def close(self):
                pass

        real = serial.Serial
        serial.Serial = BaudFake
        try:
            baud, data = R.auto_baud_detect("FAKE1", candidates=(9600, 57600, 115200),
                                            per_baud=0.15)
        finally:
            serial.Serial = real
        self.assertEqual(baud, 57600)
        self.assertTrue(data.startswith(b"WB,"))

    def test_returns_none_when_nothing_answers(self):
        import serial

        class DeadFake:
            def __init__(self, *a, **kw):
                self.baudrate = kw.get("baudrate", a[1] if len(a) > 1 else 9600)
                self.name = "FAKE"

            def read(self, size=1):
                time.sleep(0.02)
                return b""

            def reset_input_buffer(self):
                pass

            def close(self):
                pass

        real = serial.Serial
        serial.Serial = DeadFake
        try:
            baud, data = R.auto_baud_detect("FAKE1", candidates=(9600, 19200), per_baud=0.1)
        finally:
            serial.Serial = real
        self.assertIsNone(baud)
        self.assertEqual(data, b"")


class TestCli(unittest.TestCase):
    def test_defaults(self):
        args = parse(["--port", "COM7"])
        self.assertEqual((args.port, args.baud, args.framing, args.mode),
                         ("COM7", 9600, "gap", "both"))

    def test_raw_file_const(self):
        self.assertEqual(parse(["--port", "COM7", "--raw-file"]).raw_file,
                         R.DEFAULT_RAW_FILE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
