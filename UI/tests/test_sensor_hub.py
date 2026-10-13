# -*- coding: utf-8 -*-
"""
test_sensor_hub.py —— sensor_hub 应用的自动化测试

分两部分：
  1) 解析器单元测试：不需要图形界面，任何环境都能跑；
  2) 界面冒烟测试：用 offscreen 平台无头启动窗口、跑演示模式、截图，验证 UI 不崩。

运行：
    python -m tests.test_sensor_hub
    python -m tests.test_sensor_hub --with-gui      # 额外跑界面冒烟测试（Windows 上是无头窗口）
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from sensor_hub.parser import FrameParser, ParseConfig, looks_numeric, to_number  # noqa: E402


class TestNumberHelpers(unittest.TestCase):
    def test_looks_numeric(self):
        for text in ("1", "-2", "+3", "4.5", ".5", "1e3", " -12.75 "):
            self.assertTrue(looks_numeric(text), text)
        for text in ("WB", "", "12a", "0x1F", "--"):
            self.assertFalse(looks_numeric(text), text)

    def test_to_number_keeps_integers_as_int(self):
        self.assertEqual(to_number("12"), 12)
        self.assertEqual(to_number("-3"), -3)
        self.assertEqual(to_number("3.5"), 3.5)
        self.assertIsNone(to_number("WB"))


class TestBuiltinFormats(unittest.TestCase):
    """通用/后备格式。真实 WB 协议的测试在 test_wb_protocol.py。"""

    def setUp(self):
        self.parser = FrameParser(ParseConfig(auto_detect=True))

    def test_four_sensors_and_battery(self):
        """4 个传感器 + 电池：S,1,24.5,60.2,101.3,3.9,3.85,92"""
        frame = self.parser.parse("S,1,24.5,60.2,101.3,3.9,3.85,92")
        self.assertEqual(frame.status, "ok")
        self.assertEqual(frame.seq, 1)
        self.assertAlmostEqual(frame.values["s1"], 24.5)
        self.assertAlmostEqual(frame.values["s2"], 60.2)
        self.assertAlmostEqual(frame.values["s3"], 101.3)
        self.assertAlmostEqual(frame.values["s4"], 3.9)
        self.assertAlmostEqual(frame.values["batt_v"], 3.85)
        self.assertAlmostEqual(frame.values["batt_pct"], 92)

    def test_plain_numbers(self):
        """整帧 4 个数字 = 4 路传感器读数（不带序号）。"""
        frame = self.parser.parse("25.6,26.1,27.2,28.3")
        self.assertEqual(frame.status, "ok")
        self.assertIsNone(frame.seq)
        self.assertAlmostEqual(frame.values["s1"], 25.6)
        self.assertAlmostEqual(frame.values["s4"], 28.3)

    def test_key_value_format(self):
        frame = self.parser.parse("T1=25.6,T2=26.1,BATT=3.85,SOC=92")
        self.assertEqual(frame.status, "ok")
        self.assertAlmostEqual(frame.values["batt_v"], 3.85)
        self.assertAlmostEqual(frame.values["batt_pct"], 92)

    def test_unknown_format_falls_back_to_raw(self):
        frame = self.parser.parse("HELLO WORLD")
        self.assertEqual(frame.status, "raw")
        self.assertEqual(frame.raw, "HELLO WORLD")
        self.assertTrue(frame.error)

    def test_empty_line(self):
        frame = self.parser.parse("   ")
        self.assertEqual(frame.status, "raw")

    def test_negative_and_decimal_values(self):
        """带序号帧：指定 seq_mode=always 时第 1 个就是序号。"""
        parser = FrameParser(ParseConfig(auto_detect=True, seq_mode="always"))
        frame = parser.parse("1,-2.5,+3.25,-0.75")
        self.assertEqual(frame.seq, 1)
        self.assertEqual(frame.values["s1"], -2.5)
        self.assertAlmostEqual(frame.values["s2"], 3.25)
        self.assertAlmostEqual(frame.values["s3"], -0.75)

    def test_seq_mode_auto_vs_always(self):
        """auto：4 个数字当成 4 路传感器；always：第 1 个当序号。"""
        auto = FrameParser(ParseConfig(auto_detect=True, seq_mode="auto"))
        self.assertIsNone(auto.parse("1,2,3,4").seq)
        always = FrameParser(ParseConfig(auto_detect=True, seq_mode="always"))
        self.assertEqual(always.parse("1,2,3,4").seq, 1)


class TestCustomConfig(unittest.TestCase):
    def test_custom_index_mapping(self):
        config = ParseConfig(auto_detect=False, delimiter=",",
                             seq_index=0, s1_index=1, s2_index=2, s3_index=3, s4_index=4,
                             batt_v_index=5, batt_pct_index=6, flag_index=None)
        parser = FrameParser(config)
        frame = parser.parse("7,24.5,60.2,101.3,3.9,3.85,92")
        self.assertEqual(frame.status, "ok")
        self.assertEqual(frame.seq, 7)
        self.assertAlmostEqual(frame.values["s1"], 24.5)
        self.assertAlmostEqual(frame.values["batt_pct"], 92)
        self.assertEqual(frame.source, config.name)

    def test_config_round_trip(self):
        config = ParseConfig(name="我的板子", s1_index=3, auto_detect=False)
        restored = ParseConfig.from_dict(config.to_dict())
        self.assertEqual(restored.name, "我的板子")
        self.assertEqual(restored.s1_index, 3)
        self.assertFalse(restored.auto_detect)

    def test_config_ignores_unknown_keys(self):
        restored = ParseConfig.from_dict({"name": "x", "不存在的字段": 1})
        self.assertEqual(restored.name, "x")


class TestCsvRecorder(unittest.TestCase):
    def test_writes_header_and_rows(self):
        import tempfile
        from sensor_hub.storage import CsvRecorder

        path = os.path.join(tempfile.gettempdir(), "sensor_hub_test.csv")
        if os.path.exists(path):
            os.remove(path)
        recorder = CsvRecorder()
        recorder.open(path)
        parser = FrameParser(ParseConfig(auto_detect=True))
        recorder.write(parser.parse("S,1,24.5,60.2,101.3,3.9,3.85,92", ts=1000.0))
        recorder.write(parser.parse("垃圾数据", ts=1001.0))
        recorder.close()

        with open(path, "r", encoding="utf-8-sig") as handle:
            lines = handle.read().strip().splitlines()
        self.assertEqual(len(lines), 3)                 # 表头 + 2 行
        self.assertIn("传感器1(字段5)", lines[0])
        self.assertIn("24.5", lines[1])
        self.assertIn("垃圾数据", lines[2])
        os.remove(path)


class TestPortListing(unittest.TestCase):
    def test_available_ports_returns_list(self):
        from sensor_hub.reader import available_ports, port_details
        self.assertIsInstance(available_ports(), list)
        self.assertIsInstance(port_details(), list)


class TestLineSplitting(unittest.TestCase):
    """读取端断行：\\r\\n 混用时不能让 \\r 残留到下一行行首。"""

    class FakeSer:
        def __init__(self, script):
            self.script = list(script)
            self.timeout = 0.05

        @property
        def in_waiting(self):
            return len(self.script[0]) if self.script else 0

        def read(self, size=1):
            if not self.script:
                time.sleep(self.timeout)
                return b""
            return self.script.pop(0)

        def close(self):
            pass

    def test_cr_lf_and_bare_cr_do_not_pollute_next_line(self):
        from sensor_hub.reader import SerialReader

        script = [b"WB,1,2,0F,1,2,3,4,3800,50\r\n",
                  b"WB,2,2,0F,1,2,3,4,3801,51\r",      # 单独的 \r
                  b"\nWB,3,2,0F,1,2,3,4,3802,52\r\n"]
        reader = SerialReader("FAKE", 9600)
        reader._ser = self.FakeSer(script)
        got = []
        reader.lineReceived.connect(got.append)
        for _ in range(40):
            reader._read_once()
            if len(got) >= 3:
                break

        self.assertEqual(len(got), 3)
        for line in got:
            self.assertTrue(line.startswith("WB"), "行首被污染：%r" % line)


# ------------------------------------------------------------------ 界面冒烟
def run_gui_smoke() -> int:
    """无头启动界面 -> 跑演示模式 -> 检查数据 -> 截图。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtWidgets import QApplication

    from sensor_hub.mainwindow import MainWindow

    print("\n" + "=" * 70)
    print("界面冒烟测试（offscreen 无头运行）")
    app = QApplication(sys.argv[:1])
    from sensor_hub import theme
    theme.configure_application(app)
    window = MainWindow()
    window._save_config = lambda config: None
    window.setAttribute(Qt.WA_DontShowOnScreen)
    window.show()
    print("  ✓ 主窗口创建成功：%s" % window.windowTitle())

    # 解析器先喂几帧，验证信号链路
    window.start_receive(demo=True)
    print("  ✓ 演示模式已启动")

    shots = []

    def capture(stage: str):
        shots.append(stage)
        folder = os.path.join(os.path.dirname(HERE), "artifacts", "previews")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "screenshot_%s.png" % stage)
        window.grab().save(path)
        print("  ✓ 截图 stage=%s -> %s" % (stage, os.path.basename(path)))

    def check_and_close():
        frames = window.frame_count
        rows = window.table.rowCount()
        last = window.last_frame
        print("  收到帧数 = %d，表格行数 = %d" % (frames, rows))
        if last is not None:
            print("  最新一帧：seq=%s ms=%s OK掩码=%s(%s)" %
                  (last.seq, last.ms, last.flag, last.ok_channels()))
            print("            4 路重量(g) = %s" % (last.weight_g,))
            print("            电池 = %s mV / %s %%" % (last.battery_mv, last.get("batt_pct")))
        print("  统计面板：帧数=%s 解析方式=%s 电池预计可用=%s"
              % (window.stat_labels["frames"].text(), window.stat_labels["source"].text(),
                 window.stat_labels["elapsed"].text()))
        print("  第1路状态标签 = %s" % window.channel_labels[0].text())

        # 电池剩余时间推算：喂"1 小时掉 100mV"的假数据，答案必须和公式算出来的一致
        window.battery_history.clear()
        for minute in range(61):
            window.battery_history.append((minute * 60000, 3900 - minute * (100 / 60.0)))
        estimate = window._battery_estimate(3600.0)
        history = window.battery_history
        span_h = (history[-1][0] - history[0][0]) / 3600000.0
        rate = (history[0][1] - history[-1][1]) / span_h
        expected_h = (history[-1][1] - 3300.0) / rate        # 3300mV 为空电阈值
        print("  电池推算（模拟放电 %.0f mV/小时，当前 %.0f mV）= %s"
              % (rate, history[-1][1], estimate))
        print("  公式应为：约 %.1f 小时" % expected_h)
        estimate_ok = ("%.1f 小时" % expected_h) in estimate and "%.1f mV/h" % rate in estimate
        if estimate_ok:
            print("  ✓ 电池剩余时间推算正确（按 3300mV 空电外推）")
        else:
            print("  ✗ 电池剩余时间推算不对")

        ok = (frames >= 1 and rows >= 1 and last is not None
              and last.get("s1") is not None and last.battery_mv is not None
              and window.channel_labels[0].text() == "正常" and estimate_ok)
        if ok:
            print("  ✓ 数据链路正常：解析 -> 卡片/表格/曲线 都拿到数据")
        else:
            print("  ✗ 数据链路异常")
        capture("demo")
        window.close()
        app.exit(0 if ok else 1)
        return 0 if ok else 1

    QTimer.singleShot(3500, check_and_close)
    code = app.exec_()
    print("  GUI 退出码：%s" % code)
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-gui", action="store_true", help="额外跑界面冒烟测试")
    args = parser.parse_args()

    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    code = 0 if result.wasSuccessful() else 1

    if args.with_gui:
        code = max(code, run_gui_smoke())
    return code


if __name__ == "__main__":
    sys.exit(main())
