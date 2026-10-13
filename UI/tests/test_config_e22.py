# -*- coding: utf-8 -*-
"""
test_config_e22.py —— 验证 config_e22.py 的指令构造与寄存器解释（不需要真实硬件）。

运行：
    python -m tests.test_config_e22
"""

from __future__ import annotations

import sys
import unittest


from tools import config_e22 as C  # noqa: E402


class TestFrames(unittest.TestCase):
    def test_query_frame(self):
        self.assertEqual(C.build_query(0xC1).hex(" ").upper(), "C1 C1 C1 06")
        self.assertEqual(C.build_query(0xC3).hex(" ").upper(), "C3 C1 C1 06")

    def test_config_frame(self):
        """写参数：C0 + 起始地址 00 + 长度 06 + 6 个寄存器 + 校验 C1 C1 C1。"""
        frame = C.build_config({0: 0x12, 1: 0x03})
        self.assertEqual(frame.hex(" ").upper(),
                         "C0 00 06 12 03 00 00 00 00 C1 C1 C1")
        self.assertEqual(len(frame), 12)

    def test_parse_response(self):
        data = bytes.fromhex("C1000600000400000000C1C1C1")
        regs = C.parse_regs(data)
        self.assertEqual(regs, {0: 0, 1: 0, 2: 4, 3: 0, 4: 0, 5: 0})

    def test_parse_bad_response(self):
        with self.assertRaises(ValueError):
            C.parse_regs(b"\x00\x01")
        with self.assertRaises(ValueError):
            C.parse_regs(b"")


class TestSetParsing(unittest.TestCase):
    def test_reg_layout_channel(self):
        regs = C.parse_set("channel=23", "reg")
        self.assertEqual(regs, {0: 23})

    def test_addr_layout_channel_and_addr(self):
        regs = C.parse_set("addr=0x1234", "addr")
        self.assertEqual((regs[0], regs[1]), (0x12, 0x34))
        regs = C.parse_set("channel=23", "addr")
        self.assertEqual(regs[1], 23)

    def test_reg_layout_rejects_addr(self):
        with self.assertRaises(ValueError):
            C.parse_set("addr=1", "reg")

    def test_combined_fields_share_one_register(self):
        """波特率/校验/空中速率同在 REG1(reg 布局) 或 REG3(addr 布局)，不能互相覆盖。"""
        regs = C.parse_set("baud=9600,parity=8n1,rate=2.4k", "reg")
        r = regs[1]
        self.assertEqual(r & 0x0F, 3)          # 9600 bps
        self.assertEqual((r >> 3) & 0x03, 0)   # 8N1
        self.assertEqual((r >> 5) & 0x07, 2)   # 2.4 kbps
        regs = C.parse_set("baud=115200,rate=62.5k", "addr")
        self.assertEqual(regs[3] & 0x0F, 7)
        self.assertEqual((regs[3] >> 5) & 0x07, 7)

    def test_power_and_rssi_share_register(self):
        """功率档(位6~7)和 RSSI 使能(位7)同在 REG3 最高字节里——位 7 是重叠的。

        注意：REG3=0xC0 按手册解释是“10 dBm + RSSI 使能”，而不是 17 dBm。
        也就是说 power=17 且 rssi=on 时，RSSI 位会覆盖功率档的第 2 位，
        实际生效的是 10 dBm。这里按“写进去什么、解出来就是什么”做一致性校验。
        """
        # power=10 的枚举值恰好是 3（0b11），配 rssi=on 得到 0xC0
        self.assertEqual(C.parse_set("power=10,rssi=on", "reg")[3], 0xC0)
        self.assertEqual(C.get_field({3: 0xC0}, "reg", "power"), 3)
        self.assertEqual(C.get_field({3: 0xC0}, "reg", "rssi"), 1)

        # power=17（枚举 1）单独设置：位 6~7 = 0b01，位 7 仍为 0
        regs = C.parse_set("power=17", "reg")
        self.assertEqual(regs[3], 0x40)
        self.assertEqual(C.get_field(regs, "reg", "power"), C.POWER_OPTIONS["17"])
        self.assertEqual(C.get_field(regs, "reg", "rssi"), 0)

        # 关掉 RSSI 时，功率档不受影响：0x40 解回来还是 17 dBm
        self.assertEqual(C.describe({3: 0x40}, "reg").count("17 dBm"), 1)

    def test_bad_value(self):
        with self.assertRaises(ValueError):
            C.parse_set("rate=9999k", "reg")
        with self.assertRaises(ValueError):
            C.parse_set("channel=99", "reg")
        with self.assertRaises(ValueError):
            C.parse_set("unknownkey=1", "reg")


class TestDescribe(unittest.TestCase):
    def test_describe_reads_back_what_we_set(self):
        """写入的值再解释回来，应与输入一致（往返一致）。"""
        regs = C.parse_set("channel=23,baud=9600,rate=2.4k,packet=200,power=22", "reg")
        text = C.describe(regs, "reg")
        self.assertIn("信道        : 23", text)
        self.assertIn("433.125 MHz", text)      # 410.125 + 23
        self.assertIn("9600 bps", text)
        self.assertIn("2.4 kbps", text)
        self.assertIn("200(240) 字节", text)
        self.assertIn("22 dBm", text)

    def test_describe_addr_layout(self):
        regs = C.parse_set("addr=100,netid=5", "addr")
        text = C.describe(regs, "addr")
        self.assertIn("模块地址    : 100", text)
        self.assertIn("网络地址    : 5", text)

    def test_freq_formula(self):
        self.assertEqual(C.channel_to_freq(0), "410.125 MHz")
        self.assertEqual(C.channel_to_freq(83), "493.125 MHz")


if __name__ == "__main__":
    unittest.main(verbosity=2)
