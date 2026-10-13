# -*- coding: utf-8 -*-
"""
test_end_to_end.py —— 端到端跑一遍 receiver.py 主流程（用假串口喂真实数据）

验证：命令行解析 -> 开串口 -> 组包 -> 打印/写日志 全链路。
运行：
    python -m tests.test_end_to_end
"""

from __future__ import annotations

import io
import os
import sys
import time
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import serial  # noqa: E402
from tools import receiver as R  # noqa: E402


class FakeSerial:
    """假串口：按脚本顺序吐数据块，块之间 sleep，模拟真实的收发间隔。"""

    def __init__(self, *args, **kwargs):
        self.script = list(FakeSerial.SCRIPT)
        self.timeout = kwargs.get("timeout", 0.1)
        self.name = kwargs.get("port", "FAKE1")
        self.baudrate = kwargs.get("baudrate", 9600)
        self.is_open = True

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

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        pass


def _run(output_dir: str) -> int:
    # ---- 模拟发送端发来的 4 种数据 ----
    binary = bytes([0xAA, 0x01, 0x02, 0x0D, 0x0A, 0xFF])
    text_cn = "温度=25.6度".encode("utf-8")
    FakeSerial.SCRIPT = [
        b"HELLO LORA FROM SENDER",      # 1) 纯文本一条
        b"temp=25.6,hum=60",            # 2) 键值对一条
        text_cn[:5],                    # 3) 中文被拆成两包（第 5 字节处断开）
        text_cn[5:],
        binary,                         # 4) 二进制一包
    ]

    log = os.path.join(output_dir, "e2e_recv.log")
    raw = os.path.join(output_dir, "e2e_raw.bin")
    for path in (log, raw):
        if os.path.exists(path):
            os.remove(path)

    real_serial = serial.Serial
    serial.Serial = FakeSerial          # 让 receiver 用我们的假串口
    buf = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = buf
    try:
        code = R.main(["--port", "FAKE1", "--gap", "0.05", "--show-gap", "--show-decoded",
                       "-o", log, "--raw-file", raw,
                       "--max-packets", "5", "--stats-every", "0"])
    finally:
        sys.stdout = real_stdout
        serial.Serial = real_serial

    print(buf.getvalue())
    print("=" * 70)
    print("receiver.main() 返回:", code)

    # ---- 校验结果 ----
    out = buf.getvalue()
    expect = [b"HELLO LORA FROM SENDER", b"temp=25.6,hum=60", binary]
    # 中文被拆成两包时：第 3 包只能解出“温”，被截断的“度”要等第 4 包补齐才出现
    pkt3_utf8 = "UTF8 温" in out and "UTF8 温度" not in out
    pkt4_utf8 = "UTF8 度=25.6度" in out
    checks = [
        ("第一包文本", "HELLO LORA FROM SENDER" in out),
        ("第二包文本", "temp=25.6,hum=60" in out),
        ("中文跨包拼接（第 3 包只出“温”）", pkt3_utf8),
        ("中文跨包拼接（第 4 包补出“度”）", pkt4_utf8),
        ("二进制十六进制", "AA 01 02 0D 0A FF" in out),
        ("共 5 包", out.count("len=") == 5),
    ]
    with open(log, "rb") as f:
        log_data = f.read()
    with open(raw, "rb") as f:
        raw_data = f.read()
    checks.append(("文本日志每包都有记录",
                   all(d.hex(" ").upper().encode() in log_data for d in expect)))
    checks.append(("原始抓包写入", raw_data.endswith(binary)))

    print("\n检查项：")
    ok = True
    for name, passed in checks:
        ok = ok and passed
        print("  %s %s" % ("✓" if passed else "✗", name))
    print("\n原始抓包文件大小：%d 字节" % len(raw_data))
    print("结果：%s" % ("全部通过" if ok else "存在失败项"))
    return 0 if ok else 1


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sensor_hub_e2e_") as output_dir:
        return _run(output_dir)


if __name__ == "__main__":
    sys.exit(main())
