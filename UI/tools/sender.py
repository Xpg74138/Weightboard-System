# -*- coding: utf-8 -*-
"""
sender.py —— E22-400T22S LoRa 发送端小程序（用来配对测试接收端）

作用：
    从串口往 LoRa 模块写数据，模块会把它无线发出去（透明传输模式 M0=M1=0）。

运行示例：
    python -m tools.sender --port COM5 --text "hello lora"
    python -m tools.sender --port COM5 --text "温度=25.6" --repeat 10 --interval 1
    python -m tools.sender --port COM5 --hex "AA 01 02 0D 0A"
"""

from __future__ import annotations

import argparse
import sys
import time

DEFAULT_BAUD = 9600


def _setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def parse_payload(args: argparse.Namespace) -> bytes:
    if args.hex:
        txt = args.hex.replace(",", " ").replace("0x", " ").replace("0X", " ")
        try:
            return bytes.fromhex(txt)
        except ValueError as exc:
            raise SystemExit("--hex 参数不是合法的十六进制：%s" % exc)
    if args.text is None:
        raise SystemExit("请用 --text \"内容\" 或 --hex \"AA BB CC\" 指定要发送的数据。")
    data = args.text.encode("utf-8")
    if args.crlf:
        data += b"\r\n"
    elif args.newline:
        data += b"\n"
    return data


def main(argv: list[str] | None = None) -> int:
    _setup_stdout()
    p = argparse.ArgumentParser(
        prog="sender.py",
        description="E22-400T22S LoRa 发送端：通过串口把数据交给模块无线发出。")
    p.add_argument("-p", "--port", required=True, help="串口名，如 COM5")
    p.add_argument("-b", "--baud", type=int, default=DEFAULT_BAUD,
                   help="串口波特率（默认 %d，需与模块一致）" % DEFAULT_BAUD)
    p.add_argument("--text", help="要发送的文本（UTF-8 编码）")
    p.add_argument("--hex", help="要发送的十六进制字节，如 \"AA 01 02\"")
    p.add_argument("--newline", action="store_true", help="在文本末尾追加 \\n")
    p.add_argument("--crlf", action="store_true", help="在文本末尾追加 \\r\\n")
    p.add_argument("--repeat", type=int, default=1, help="重复发送次数，默认 1")
    p.add_argument("--interval", type=float, default=1.0, help="重复发送的间隔秒数，默认 1.0")
    p.add_argument("--delay", type=float, default=0.05, help="每次发送后等待模块发完的秒数，默认 0.05")
    args = p.parse_args(argv)

    data = parse_payload(args)
    if not data:
        raise SystemExit("要发送的数据为空。")

    import serial

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.2, write_timeout=2, dsrdtr=False)
    except Exception as exc:
        print("打开串口 %s 失败：%s" % (args.port, exc), file=sys.stderr)
        print("提示：端口可能被串口助手/接收端占用（同一串口同一时刻只能一个程序用）。",
              file=sys.stderr)
        return 2

    try:
        print("串口 %s @ %d 已打开，准备发送 %d 字节：%s"
              % (ser.name, args.baud, len(data), data.hex(" ").upper()), flush=True)
        for i in range(1, max(args.repeat, 1) + 1):
            n = ser.write(data)
            ser.flush()
            print("[%d/%d] 已写入 %d 字节" % (i, max(args.repeat, 1), n), flush=True)
            time.sleep(args.delay)
            if i < args.repeat:
                time.sleep(max(args.interval - args.delay, 0))
    except KeyboardInterrupt:
        print("\n已中断。", flush=True)
    finally:
        ser.close()
    print("发送结束。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
