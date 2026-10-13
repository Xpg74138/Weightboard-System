# -*- coding: utf-8 -*-
"""
test_wb_protocol.py —— 按【真实协议】验证解析（协议来源：Sender/main.c）

发送端源码里的 send_packet()：
    "WB," + seq + "," + millis() + "," + hex2(ok_mask) + ","
         + weight_g[0..3] + "," + bat_mv + "," + battery_percent(bat_mv) + "\\r\\n"

所以一行应该是 10 个字段：
    0: WB      1: 序号     2: 毫秒      3: OK掩码(十六进制两位)
    4~7: 4 路重量(克)      8: 电池(mV)  9: 电量(%)
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from sensor_hub.parser import FrameParser, ParseConfig  # noqa: E402

# 现场实测抓到的一帧（与源码格式完全一致）
REAL_FRAME = "WB,1294,1402502,0F,-12233,-9386,-3775,-15521,3906,67"


class TestWbProtocol(unittest.TestCase):
    def setUp(self):
        self.parser = FrameParser(ParseConfig())

    def test_real_frame_all_fields(self):
        frame = self.parser.parse(REAL_FRAME, ts=1000.0)
        self.assertEqual(frame.status, "ok")
        self.assertEqual(frame.source, "WB 称重板协议")
        self.assertEqual(frame.prefix, "WB")
        self.assertEqual(frame.seq, 1294)          # 序号
        self.assertEqual(frame.ms, 1402502)        # 板子 millis()
        self.assertEqual(frame.flag, "0F")         # OK 掩码
        self.assertEqual(frame.weight_g, [-12233, -9386, -3775, -15521])
        self.assertEqual(frame.battery_mv, 3906)   # 源码发的是毫伏
        self.assertAlmostEqual(frame.get("batt_v"), 3.906)   # 内部统一存伏
        self.assertEqual(frame.get("batt_pct"), 67)

    def test_ok_mask_channels(self):
        """0x0F = 4 路全部成功。"""
        frame = self.parser.parse(REAL_FRAME)
        self.assertEqual([frame.channel_ok(i) for i in range(4)],
                         [True, True, True, True])
        self.assertEqual(frame.ok_channels(), "4 路全部正常")

    def test_partial_ok_mask(self):
        """0x05 = bit0 和 bit2 -> 第 1、3 路成功（对应宏 USE_HX711_CH_MASK）。"""
        frame = self.parser.parse("WB,7,1000,05,111,0,222,0,3900,66")
        self.assertEqual([frame.channel_ok(i) for i in range(4)],
                         [True, False, True, False])
        self.assertEqual(frame.ok_channels(), "仅第 1、3 路正常")

    def test_failed_channels(self):
        """0x00 = 全部读取失败（hx711_read 超时返回 0）。"""
        frame = self.parser.parse("WB,8,2000,00,0,0,0,0,3900,66")
        self.assertEqual(frame.ok_channels(), "4 路全部读取失败")

    def test_zero_and_negative_weights(self):
        frame = self.parser.parse("WB,1,50,0F,0,-1,0,-2147483648,4200,100")
        self.assertEqual(frame.weight_g, [0, -1, 0, -2147483648])
        self.assertEqual(frame.battery_mv, 4200)
        self.assertEqual(frame.get("batt_pct"), 100)

    def test_battery_percent_bounds(self):
        """源码 battery_percent()：<=3300mV -> 0%，>=4200mV -> 100%。"""
        low = self.parser.parse("WB,1,1,0F,0,0,0,0,3300,0")
        self.assertEqual(low.battery_mv, 3300)
        self.assertEqual(low.get("batt_pct"), 0)
        high = self.parser.parse("WB,2,2,0F,0,0,0,0,4200,100")
        self.assertEqual(high.get("batt_pct"), 100)

    def test_small_battery_value_not_kept_as_volts(self):
        """毫伏值（如 3906）以前会被误当电压，现在按协议直接 /1000。"""
        frame = self.parser.parse("WB,3,3,0F,1,2,3,4,3906,67")
        self.assertAlmostEqual(frame.get("batt_v"), 3.906)
        self.assertNotIn("3906", frame.extra)

    def test_field_mapping_matches_source(self):
        """严格按发送端源码 send_packet() 核对字段归属。

        源码： WB, seq, millis(), ok_mask, weight_g[0..3], bat_mv, battery_percent()
        索引：  0   1     2          3        4  5  6  7      8       9
        """
        frame = self.parser.parse("WB,2375,2574362,0F,-11063,-8748,-3085,-13788,3818,57")
        self.assertEqual(frame.prefix, "WB")
        self.assertEqual(frame.seq, 2375)            # 字段1
        self.assertEqual(frame.ms, 2574362)          # 字段2
        self.assertEqual(frame.flag, "0F")           # 字段3
        self.assertEqual(frame.weight_g, [-11063, -8748, -3085, -13788])   # 字段4~7
        self.assertEqual(frame.battery_mv, 3818)     # 字段8（绝不能取成字段7的 -13788）
        self.assertEqual(frame.get("batt_pct"), 57)  # 字段9

    def test_battery_never_negative(self):
        """负电压物理上不可能，出现负值说明解析错位，一律归零而不是显示误导数字。"""
        frame = self.parser.parse("WB,1,1,0F,1,2,3,4,-13788,57")
        self.assertEqual(frame.battery_mv, 0.0)

    def test_new_format_with_board_id(self):
        """新版协议：WB,板号,序号,毫秒,掩码,4路重量,电池,电量（11 字段）。"""
        frame = self.parser.parse("WB,7,2375,2574362,0F,-11063,-8748,-3085,-13788,3818,57")
        self.assertEqual(frame.source, "WB 称重板协议")
        self.assertEqual(frame.board_id, 7)          # 字段1 = 板号
        self.assertEqual(frame.seq, 2375)            # 字段2
        self.assertEqual(frame.ms, 2574362)          # 字段3
        self.assertEqual(frame.flag, "0F")           # 字段4
        self.assertEqual(frame.weight_g, [-11063, -8748, -3085, -13788])   # 字段5~8
        self.assertEqual(frame.battery_mv, 3818)     # 字段9
        self.assertEqual(frame.get("batt_pct"), 57)  # 字段10

    def test_old_format_without_board_id_still_works(self):
        """旧版 10 字段格式仍要兼容（方便分批升级板子），此时板号为 None。"""
        frame = self.parser.parse("WB,2375,2574362,0F,-11063,-8748,-3085,-13788,3818,57")
        self.assertEqual(frame.source, "WB 称重板协议")
        self.assertIsNone(frame.board_id)
        self.assertEqual(frame.seq, 2375)
        self.assertEqual(frame.ms, 2574362)
        self.assertEqual(frame.flag, "0F")
        self.assertEqual(frame.battery_mv, 3818)
        self.assertEqual(frame.get("batt_pct"), 57)

    def test_board_id_42(self):
        frame = self.parser.parse("WB,42,1,5000,0F,-1,-2,-3,-4,3800,50")
        self.assertEqual(frame.board_id, 42)
        self.assertEqual(frame.weight_g, [-1, -2, -3, -4])
        self.assertEqual(frame.battery_mv, 3800)

    def test_dirty_prefix_still_parses_as_wb(self):
        """行首残留脏字节（实测出现过 "d\\rWB,..."）时不能退化成通用解析。

        这是现场真实故障：串口按 \\n 断行时一个 \\r 残留到下一行行首，
        导致 parts[0] 变成 "d\\rWB"、WB 协议匹配失败，于是字段全部错位——
        电池显示成重量4 的 -12249，界面显示 0 mV。
        """
        real = "d\rWB,71,78593,0F,-10473,-8137,-2461,-12249,3806,56"
        frame = self.parser.parse(real)
        self.assertEqual(frame.source, "WB 称重板协议")
        self.assertEqual(frame.weight_g, [-10473, -8137, -2461, -12249])
        self.assertEqual(frame.battery_mv, 3806)     # 必须取字段8，不能取字段7
        self.assertEqual(frame.get("batt_pct"), 56)

    def test_various_dirty_prefixes(self):
        """各种行首脏字符（回车/换行/制表/NUL/多字节）都要能正确解析。"""
        body = "WB,71,78593,0F,-10473,-8137,-2461,-12249,3806,56"
        for prefix in ("\r", "\r\r", "\n", "d\r", "\x00", " \t", "x"):
            frame = self.parser.parse(prefix + body)
            self.assertEqual(frame.source, "WB 称重板协议", "前缀 %r 解析失败" % prefix)
            self.assertEqual(frame.battery_mv, 3806, "前缀 %r 时电池取错" % prefix)

    def test_extra_fields_are_kept(self):
        """协议以后加字段也不能丢：多出来的进 extra。"""
        frame = self.parser.parse("WB,4,4,0F,1,2,3,4,3900,66,999,888")
        self.assertEqual(frame.extra, ["999", "888"])

    def test_boot_messages_are_marked_text(self):
        """上电时源码会先发 BOOT_SYSTICK / ADC_INIT_OK，不应算“无法解析”。"""
        for line in ("BOOT_SYSTICK", "ADC_INIT_OK"):
            frame = self.parser.parse(line)
            self.assertEqual(frame.status, "text")
            self.assertTrue(frame.is_text)
            self.assertEqual(frame.source, "板子启动提示")

    def test_wrong_field_count_is_not_wb(self):
        """字段不足 10 个就不该按 WB 协议解析（避免误判）。"""
        frame = self.parser.parse("WB,1,2,0F")
        self.assertNotEqual(frame.source, "WB 称重板协议")

    def test_csv_row_has_protocol_columns(self):
        """CSV 记录要包含协议里的关键列。"""
        from sensor_hub.storage import CsvRecorder

        path = os.path.join(tempfile.gettempdir(), "wb_protocol_test.csv")
        if os.path.exists(path):
            os.remove(path)
        recorder = CsvRecorder()
        recorder.open(path)
        recorder.write(self.parser.parse(REAL_FRAME, ts=1000.0))
        recorder.write(self.parser.parse("BOOT_SYSTICK", ts=999.0))
        recorder.close()

        with open(path, "r", encoding="utf-8-sig") as handle:
            lines = handle.read().strip().splitlines()
        header = lines[0].split(",")
        self.assertIn("板号", header)
        self.assertIn("板子毫秒(字段3)", header)
        self.assertIn("OK掩码(字段4)", header)
        self.assertIn("传感器1(字段5)", header)
        self.assertIn("电池电压mV(字段9)", header)
        self.assertIn("1294", lines[1])
        self.assertIn("1402502", lines[1])
        self.assertIn("3906", lines[1])
        os.remove(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
