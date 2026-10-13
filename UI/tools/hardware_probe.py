# -*- coding: utf-8 -*-
"""
hardware_probe.py —— 串口硬件体检（不需要 LoRa 模块配合）

做三件事，用来定位“明明发着数据却一个字节都收不到”到底是哪一层断了：
  1) 描述符：打开端口打印它的详细描述、速度；
  2) 拉线组合：分别试 (DTR,RTS) = (False,False)/(True,False)/(True,True)/(False,True)
     各监听 2 秒——有些 USB 转串口板子/CDC 固件要靠 DTR 才肯转发数据；
  3) 发一问一答：往串口写一帧 E22 读参数指令，看有没有任何回音。

用法：
    python -m tools.hardware_probe --port COM4
"""

from __future__ import annotations

import argparse
import sys
import time

# (DTR, RTS) 组合
COMBOS = [(False, False), (True, False), (True, True), (False, True)]
BAUD_LIST = [9600, 115200]
E22_QUERY = bytes([0xC1, 0xC1, 0xC1, 0x06])   # 读参数（需模块处于配置模式才会应答）


def _setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# 常见串口参数组合（E22 支持 1200~921600，出厂 9600 8N1）
BAUD_SWEEP = [9600, 115200, 19200, 38400, 57600, 4800, 2400, 230400, 460800]
FORMAT_SWEEP = [(8, "N"), (8, "E"), (8, "O"), (7, "N")]


def sweep(port: str, seconds: float) -> int:
    """
    扫串口参数：逐个 (波特率, 数据位, 校验) 组合监听，统计收到的字节。

    判断依据：波特率严重不匹配时，UART 会按错误的节拍采样，结果通常是“零星的、
    数量很少的无效字节”（帧错误会被丢弃）。所以：
      · 全是 0 字节        -> 链路上根本没信号（模块没发/接线/供电问题）
      · 有少量非零字节      -> 链路上有信号，只是参数不对 -> 重点试这一行
    """
    import serial

    print("=" * 72)
    print("扫串口参数（每个组合监听 %.1f 秒，统计收到的字节数）" % seconds)
    print("请在扫描期间让发送端保持持续发送。\n")
    print("  波特率    数据位/校验   收到字节   说明")
    print("  " + "-" * 60)
    hits = []
    for baud in BAUD_SWEEP:
        for bits, parity in FORMAT_SWEEP:
            if baud != 9600 and (bits, parity) != (8, "N"):
                continue          # 只有 9600 才顺带试校验位/数据位的各种组合
            try:
                ser = serial.Serial(port, baud, bytesize=bits, parity=parity, timeout=0.2)
            except Exception as exc:
                print("  %-9s %-13s 打不开：%s" % (baud, "%d%s1" % (bits, parity), exc))
                return 2
            try:
                got = bytearray()
                t0 = time.time()
                while time.time() - t0 < seconds:
                    chunk = ser.read(4096)
                    if chunk:
                        got += chunk
            finally:
                ser.close()
            text = "%d%s1" % (bits, parity)
            note = ""
            if got:
                hits.append((baud, text, len(got), bytes(got[:16])))
                note = "← 有信号！样本: %s" % bytes(got[:16]).hex(" ").upper()
            print("  %-9s %-13s %-10s %s" % (baud, text, len(got), note))

    print()
    if hits:
        best = max(hits, key=lambda h: h[2])
        print("✓ 这些组合收到了字节：")
        for baud, text, n, sample in hits:
            print("    %d %s -> %d 字节  样本 %s" % (baud, text, n, sample.hex(" ").upper()))
        print("\n  最可能的参数：%d %s（收到 %d 字节）。" % (best[0], best[1], best[2]))
        print("  如果样本看起来是乱码/零星字节，说明两端串口波特率不一致：")
        print("  把接收端的 --baud 改成上面这个值，或把发送端/模块的波特率改成 9600。")
        return 0
    print("✗ 所有组合都是 0 字节：链路上确实没有信号。")
    print("  这就不只是参数问题了，请检查模块供电、天线、测试板跳线（模块 TXD/RXD 是否")
    print("  真的接到了 USB 转串口上），以及发送端是否真的在发射。")
    return 1


def write_test(port: str, baud: int) -> int:
    """
    写方向测试：往串口写数据，看有没有回显。

    能证明的事：
      · 如果写之后能读到回显/任何字节 -> 串口是双向的，模块的 TXD 确实接到了 USB 转串口上；
      · 如果写得进去、但读不到任何东西 -> 写方向可能正常，但“模块 -> 电脑”这一半断了
        （或模块在一般模式，它对 C1C1C106 这种指令本来就不回应，所以这不能证明模块坏）。
    注意：不要把模块的 TX 和 RX 短路来做回环——那只测到 USB 转串口芯片，还会和模块输出打架。
    """
    import serial
    frames = [
        ("E22 读参数", bytes([0xC1, 0xC1, 0xC1, 0x06])),
        ("AT 问询  ", b"AT\r\n"),
        ("纯文本    ", b"PING\r\n"),
    ]
    print("=" * 72)
    print("写方向测试 @ %s %d 8N1" % (port, baud))
    try:
        ser = serial.Serial(port, baud, timeout=0.3)
    except Exception as exc:
        print("  ✗ 打不开：%s" % exc)
        return 2
    try:
        total = 0
        for name, frame in frames:
            ser.reset_input_buffer()
            n = ser.write(frame)
            ser.flush()
            total += n
            print("  写入 %s : %s（%d 字节）" % (name, frame.hex(" ").upper(), n))
            got = listen(ser, 1.2, "写入后")
            if got:
                print("      ✓ 有回显/回音：%s" % got.hex(" ").upper())
        print("\n  共写出 %d 字节，写入本身没有报错。" % total)
        print("  说明：写方向正常只能证明 USB 转串口的发送端在工作；")
        print("        要证明模块的 TXD 真的接上了，需要模块在配置模式下对 C1C1C106 有应答。")
    finally:
        ser.close()
    return 0


def listen(ser, seconds: float, label: str) -> bytes:
    """监听 seconds 秒，返回收到的字节（边收边打印）。"""
    got = bytearray()
    t0 = time.time()
    while time.time() - t0 < seconds:
        chunk = ser.read(4096)
        if chunk:
            got += chunk
            print("      +%.2fs %d 字节: %s" % (time.time() - t0, len(chunk),
                                                chunk.hex(" ").upper()[:120]))
    print("    [%s] %s，共 %d 字节" % (label, "有数据" if got else "无数据", len(got)))
    return bytes(got)


def main(argv=None) -> int:
    _setup_stdout()
    p = argparse.ArgumentParser(prog="hardware_probe.py",
                                description="串口硬件体检：描述符 / DTR·RTS 组合 / 一问一答 / 参数扫描")
    p.add_argument("-p", "--port", default="COM4")
    p.add_argument("--seconds", type=float, default=2.0, help="每种组合监听多少秒，默认 2")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--sweep", action="store_true",
                   help="只做串口参数扫描（找波特率/校验位是否不匹配），不做其余检查")
    p.add_argument("--write-test", action="store_true",
                   help="只做写方向测试：往串口写几帧数据，看有没有任何回显/反应")
    args = p.parse_args(argv)

    if args.sweep:
        return sweep(args.port, args.seconds)
    if args.write_test:
        return write_test(args.port, args.baud)

    import serial

    # ---------- 1) 描述符 ----------
    print("=" * 72)
    print("[1] 端口描述符")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.2)
    except Exception as exc:
        print("  ✗ 打不开 %s：%s" % (args.port, exc))
        print("    端口正被别的程序占用，或驱动异常。")
        return 2
    try:
        print("  端口        : %s" % ser.name)
        print("  波特率      : %s" % ser.baudrate)
        print("  数据位/校验 : %s%s" % (ser.bytesize, ser.parity))
        print("  停止位      : %s" % ser.stopbits)
        print("  CTS/DSR/RI  : %s / %s / %s" % (ser.cts, ser.dsr, ser.ri))
        print("  CD          : %s" % ser.cd)
    finally:
        ser.close()

    # ---------- 2) DTR / RTS 组合 ----------
    print("\n[2] 逐个试 (DTR,RTS) 组合，各监听 %.1f 秒" % args.seconds)
    winners = []
    for baud in BAUD_LIST:
        for dtr, rts in COMBOS:
            try:
                ser = serial.Serial(args.port, baud, timeout=0.2)
            except Exception as exc:
                print("  ✗ %s @ %d 打不开：%s" % (args.port, baud, exc))
                return 2
            try:
                ser.dtr = dtr
                ser.rts = rts
                time.sleep(0.2)
                print("  --- %d 8N1  DTR=%s RTS=%s ---" % (baud, dtr, rts))
                got = listen(ser, args.seconds, "DTR=%s,RTS=%s" % (dtr, rts))
                if got:
                    winners.append((baud, dtr, rts, got))
            finally:
                ser.close()
    if winners:
        print("\n  ✓ 有数据进来的组合：%s" % winners)
    else:
        print("\n  - 所有组合都没有数据。")

    # ---------- 3) 一问一答 ----------
    print("\n[3] 发一帧 E22 读参数指令 %s，看有没有回音" % E22_QUERY.hex(" ").upper())
    print("    （注意：只有模块处于配置模式 M0=1,M1=1 时才会有应答）")
    for baud in BAUD_LIST:
        try:
            ser = serial.Serial(args.port, baud, timeout=0.3)
        except Exception as exc:
            print("  ✗ %s @ %d 打不开：%s" % (args.port, baud, exc))
            return 2
        try:
            ser.dtr = True
            ser.rts = True
            ser.reset_input_buffer()
            ser.write(E22_QUERY)
            ser.flush()
            echo = listen(ser, 1.5, "写入后 @%d" % baud)
            if echo:
                print("      ✓ 有回音：%s" % echo.hex(" ").upper())
            else:
                print("      - 无回音（一般模式下这是正常现象，不代表模块坏）")
        finally:
            ser.close()

    print("\n结论怎么看：")
    print("  · 若 [1][2][3] 全都没数据、也没回音 -> 电脑与模块之间的串口链路没通")
    print("    （测试板跳线/驱动/模块供电/模块没插好），先解决这一层；")
    print("  · 若只有某个 DTR/RTS 组合才有数据 -> 用 --dtr/--rts 参数固定它再收；")
    print("  · 若 [3] 有回音 -> 串口链路是通的，问题在无线参数（信道/空中速率不一致）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
