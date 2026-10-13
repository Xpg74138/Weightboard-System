# -*- coding: utf-8 -*-
"""
config_e22.py —— E22-400T22S 参数读取/配置工具（可选功能）

★ 使用前提：必须让模块进入“配置模式”
    M0 = 1，M1 = 1   ->  配置模式（此时不能收发数据）
    配置完成后把 M0 = 0，M1 = 0 拨回去（或断电重启）才回到一般模式。

★ 关于寄存器映射
    E22 系列是“同一套 AT 指令、不同子型号寄存器含义略有差别”。本工具内置两种常见布局：
      --layout reg   （默认）REG0=信道, REG1=串口+空中速率, REG2=分包+环境噪声, REG3=功率
      --layout addr          ADDH/ADDL=模块地址, NETID=网络地址, REG0/REG1/REG2=上面的功能
    工具永远不会盲写：写之前一定先读出当前值，只改你指定的那一项，并把原始十六进制打印出来，
    方便你对照官方手册核对。如果读出来的解释和你手册不一致，换另一个 --layout 再看一次。

用法示例：
    python -m tools.config_e22 --port COM4 --scan                 # 扫描模块当前波特率（不知道波特率时用）
    python -m tools.config_e22 --port COM4 --read                # 读出全部参数
    python -m tools.config_e22 --port COM4 --set channel=23,rate=2.4k
    python -m tools.config_e22 --port COM4 --set power=22,packet=200
    python -m tools.config_e22 --port COM4 --set channel=23 --layout addr
    python -m tools.config_e22 --port COM4 --reset               # 恢复出厂设置
"""

from __future__ import annotations

import argparse
import sys
import time

SCAN_BAUDS = (9600, 19200, 38400, 57600, 115200, 4800, 2400, 1200, 230400, 460800, 921600)
DEFAULT_BAUD = 9600
REG_COUNT = 6                     # E22-400T22S 需要配置 6 个寄存器
CHANNEL_RANGE = (0, 83)           # 400M 频段：0~83 共 84 个信道
FREQ_BASE_MHZ = 410.125           # 实际频率 = 410.125 + 信道 x 1 MHz

# ---------------------------------------------------------------- 可选值表
BAUD_OPTIONS = {"1200": 0, "2400": 1, "4800": 2, "9600": 3, "19200": 4, "38400": 5,
                "57600": 6, "115200": 7, "230400": 8, "460800": 9, "921600": 10}
BAUD_TEXT = {3: "9600 bps", 4: "19200 bps", 5: "38400 bps", 6: "57600 bps",
             7: "115200 bps", 8: "230400 bps", 9: "460800 bps"}
for _k, _v in (("1200", 0), ("2400", 1), ("4800", 2), ("921600", 10)):
    BAUD_TEXT[_v] = "%s bps" % _k

AIR_OPTIONS = {"0.3k": 0, "0.3": 0, "1.2k": 1, "1200": 1, "2.4k": 2, "2400": 2,
               "4.8k": 3, "4800": 3, "9.6k": 4, "9600": 4, "19.2k": 5, "19200": 5,
               "38.4k": 6, "38400": 6, "62.5k": 7, "62500": 7}
AIR_TEXT = {0: "0.3 kbps", 1: "1.2 kbps", 2: "2.4 kbps", 3: "4.8 kbps",
            4: "9.6 kbps", 5: "19.2 kbps", 6: "38.4 kbps", 7: "62.5 kbps"}

PARITY_OPTIONS = {"8n1": 0, "8o1": 1, "8e1": 2, "8N1": 0}
PARITY_TEXT = {0: "8N1（8 位数据/无校验/1 停止位）", 1: "8O1", 2: "8E1"}

PACKET_OPTIONS = {"32": 0, "64": 1, "128": 2, "200": 3, "240": 3}
PACKET_TEXT = {0: "32 字节", 1: "64 字节", 2: "128 字节", 3: "200(240) 字节"}

POWER_OPTIONS = {"22": 0, "17": 1, "13": 2, "10": 3}
POWER_TEXT = {0: "22 dBm", 1: "17 dBm", 2: "13 dBm", 3: "10 dBm"}

# 两种寄存器布局：(名称, 所在寄存器, 位偏移, 位宽, 取值表)
LAYOUTS = {
    "reg": [
        ("channel", 0, 0, 8, None),
        ("baud", 1, 0, 4, BAUD_TEXT),
        ("parity", 1, 3, 2, PARITY_TEXT),
        ("rate", 1, 5, 3, AIR_TEXT),
        ("packet", 2, 0, 2, PACKET_TEXT),
        ("power", 3, 6, 2, POWER_TEXT),
        ("rssi", 3, 7, 1, {0: "关闭", 1: "开启"}),
    ],
    "addr": [
        ("addr", 0, 0, 16, None),
        ("netid", 2, 0, 8, None),
        ("baud", 3, 0, 4, BAUD_TEXT),
        ("parity", 3, 3, 2, PARITY_TEXT),
        ("rate", 3, 5, 3, AIR_TEXT),
        ("packet", 4, 0, 2, PACKET_TEXT),
        ("power", 5, 6, 2, POWER_TEXT),
        ("rssi", 5, 7, 1, {0: "关闭", 1: "开启"}),
    ],
}


def _setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def channel_to_freq(ch: int) -> str:
    return "%.3f MHz" % (FREQ_BASE_MHZ + ch)


# ---------------------------------------------------------------- 寄存器位操作
def get_field(regs: dict, layout: str, name: str):
    for fname, reg, off, width, table in LAYOUTS[layout]:
        if fname == name:
            if width == 16:      # 模块地址是 ADDH(高 8 位) + ADDL(低 8 位)，跨两个寄存器
                return ((regs.get(reg, 0) & 0xFF) << 8) | (regs.get(reg + 1, 0) & 0xFF)
            return (regs.get(reg, 0) >> off) & ((1 << width) - 1)
    raise KeyError(name)


def set_field(regs: dict, layout: str, name: str, value: int) -> None:
    """把 name 对应的位段写入 regs（同时设置的多个位段会正确合并）。"""
    for fname, reg, off, width, table in LAYOUTS[layout]:
        if fname == name:
            if width == 16:      # ADDH + ADDL
                regs[reg] = (value >> 8) & 0xFF
                regs[reg + 1] = value & 0xFF
                return
            mask = ((1 << width) - 1) << off
            regs[reg] = ((regs.setdefault(reg, 0) & ~mask) | ((value << off) & mask)) & 0xFF
            return
    raise KeyError(name)


def describe(regs: dict, layout: str) -> str:
    lines = []
    if layout == "addr":
        lines.append("  模块地址    : %d (0x%04X)" % (get_field(regs, layout, "addr"),
                                                      get_field(regs, layout, "addr")))
        lines.append("  网络地址    : %d" % get_field(regs, layout, "netid"))
    ch = get_field(regs, layout, "channel") if layout == "reg" else None
    lines += [
        "  串口波特率  : %s" % BAUD_TEXT.get(get_field(regs, layout, "baud"), "?"),
        "  校验/数据位 : %s" % PARITY_TEXT.get(get_field(regs, layout, "parity"), "?"),
        "  空中速率    : %s" % AIR_TEXT.get(get_field(regs, layout, "rate"), "?"),
        "  分包长度    : %s" % PACKET_TEXT.get(get_field(regs, layout, "packet"), "?"),
        "  发射功率    : %s" % POWER_TEXT.get(get_field(regs, layout, "power"), "?"),
        "  RSSI 字节   : %s" % ("开启" if get_field(regs, layout, "rssi") else "关闭"),
    ]
    if ch is not None:
        lines.insert(0, "  信道        : %d  =>  %s" % (ch, channel_to_freq(ch)))
    return "\n".join(lines)


def build_query(cmd: int) -> bytes:
    """读参数(C1)/读版本(C3) 指令：命令 + 起始地址 C1 + C1 + 长度。"""
    return bytes([cmd, 0xC1, 0xC1, REG_COUNT])


def build_config(regs: dict) -> bytes:
    """写参数指令：C0 + 起始地址 00 + 长度 06 + 6 个寄存器 + 校验 C1 C1 C1。"""
    values = [regs.get(i, 0) & 0xFF for i in range(REG_COUNT)]
    return bytes([0xC0, 0x00, REG_COUNT] + values + [0xC1, 0xC1, 0xC1])


def parse_regs(data: bytes) -> dict:
    """解析读参数应答：C1 00 06 + 6 个寄存器 + C1 C1 C1。"""
    if len(data) < 3 + REG_COUNT or data[0] != 0xC1:
        raise ValueError("应答格式不对：%s" % (data.hex(" ").upper() if data else "（空）"))
    return {i: data[3 + i] for i in range(REG_COUNT)}


def read_regs(ser, size: int = 16) -> bytes:
    ser.reset_input_buffer()
    ser.write(build_query(0xC1))
    ser.flush()
    return ser.read(size)


def read_version(ser, size: int = 16) -> bytes:
    ser.reset_input_buffer()
    ser.write(build_query(0xC3))
    ser.flush()
    return ser.read(size)


def read_params_loop(port: str, baud: int, seconds: float, layout: str) -> int:
    """
    反复读模块参数（适合“板子上电自动进配置模式”的场景）。

    只在开始时打开一次端口，之后每 2 秒发一次读参数指令：
      · 读到合法应答 -> 打印完整参数并退出；
      · 一直读不到   -> 说明模块不在配置模式（或串口参数不对），会一直等到超时。
    这样你可以在不关程序的情况下拨 M0/M1，切回配置模式就会被立刻读到。
    """
    import serial
    t0 = time.time()
    ser = None
    while ser is None:
        try:
            ser = serial.Serial(port, baud, timeout=0.4)
        except Exception as exc:
            msg = str(exc)
            print("  [等端口 %s] %s" % (port, msg[:90]), flush=True)
            if time.time() - t0 >= seconds:
                print("\n× 等了 %.0f 秒端口仍不可用。" % seconds)
                print("  提示：这一般是设备枚举卡住，把板子拔插一次即可恢复；")
                print("  也可能是别的程序（串口助手/接收端）占着口，先关掉它。")
                return 2
            time.sleep(2.0)
    print("反复读取 %s @ %d 的模块参数，最多等 %.0f 秒（Ctrl+C 退出）..."
          % (port, baud, seconds - (time.time() - t0)))
    print("提示：模块必须处于配置模式 M0=1, M1=1 才会应答；读到就自动退出。\n")
    try:
        while time.time() - t0 < seconds:
            try:
                ser.reset_input_buffer()
                ser.write(build_query(0xC1))
                ser.flush()
            except Exception as exc:
                print("  写入失败（板子被拔了？）：%s" % exc)
                return 3
            data = bytearray()
            deadline = time.time() + 0.5
            while time.time() < deadline:
                chunk = ser.read(32)
                if chunk:
                    data += chunk
                    if len(data) >= 3 + REG_COUNT:
                        break
            data = bytes(data)
            if len(data) >= 3 + REG_COUNT and data[0] == 0xC1:
                regs = parse_regs(data)
                print("✓ 读到参数了！（等了 %.0f 秒）" % (time.time() - t0))
                print("  原始应答  : %s" % data.hex(" ").upper())
                print("  寄存器    : %s" % " ".join("REG%d=0x%02X" % (i, regs[i])
                                                    for i in range(REG_COUNT)))
                print("  解释 @ --layout %s:" % layout)
                print(describe(regs, layout))
                print()
                print("★ 这个模块的串口参数就是 %d 8N1；上面这些值要和发送端完全一致" % baud)
                print("  （信道、空中速率、分包长度不一致就收不到数据）。")
                return 0
            if data:
                print("  收到非参数应答的字节：%s（可能是别的东西在串口上说话）"
                      % data.hex(" ").upper()[:60])
            else:
                print("  [%4.0fs] 无应答（模块多半不在配置模式，或波特率不对）"
                      % (time.time() - t0))
            time.sleep(1.5)
    finally:
        ser.close()
    print("\n× 超时，没读到参数。请确认 M0=1、M1=1（配置模式），或换 --baud 再试。")
    return 1


def listen_bytes(port: str, baud: int, seconds: float, show_hex: bool = True) -> int:
    """
    裸监听：把串口上收到的任何字节原样打出来，不发任何指令。

    用途：区分“模块根本没往串口吐东西”和“只是参数不一致”。
    注意：模块处于配置模式(M0=M1=1)时不会接收无线数据；要测无线请用 M0=M1=0 + receiver.py。
    """
    import serial
    try:
        ser = serial.Serial(port, baud, timeout=0.2)
    except Exception as exc:
        print("打开串口 %s 失败：%s" % (port, exc), file=sys.stderr)
        return 2
    print("裸监听 %s @ %d，持续 %.1f 秒（不发任何 AT 指令，收到什么原样打印）..."
          % (port, baud, seconds))
    got = bytearray()
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            chunk = ser.read(4096)
            if chunk:
                got += chunk
                print("  +%6.2fs  %d 字节: %s"
                      % (time.time() - t0, len(chunk),
                         chunk.hex(" ").upper() if show_hex else repr(chunk)))
    finally:
        ser.close()
    if got:
        print("✓ 共收到 %d 字节。文本视图：%r" % (len(got), bytes(got[:200]).decode("utf-8", "replace")))
        return 0
    print("✗ %.1f 秒内一个字节都没收到。" % seconds)
    print("  这说明“模块 -> 电脑”这条串口链路没通，问题不在接收程序，请检查：")
    print("    · 测试板上模块是否插好、电源灯/发送灯有没有亮；天线是否接好；")
    print("    · 测试板的 USB 转串口芯片是否正常工作（设备管理器里有没有黄色感叹号）；")
    print("    · 板子是否把模块的 TXD/RXD 真的接到了 USB 转串口上（有些板子需要跳线帽）。")
    return 1


def scan_baud(port: str):
    import serial
    results = []
    for baud in SCAN_BAUDS:
        try:
            ser = serial.Serial(port, baud, timeout=0.25)
        except Exception as exc:
            print("打开串口失败：%s" % exc, file=sys.stderr)
            return results
        try:
            data = read_regs(ser)
        finally:
            ser.close()
        ok = len(data) >= 3 + REG_COUNT and data[0] == 0xC1
        print("  %-8s %s  %s" % (baud, "✓" if ok else "✗",
                                 data.hex(" ").upper()[:48] or "（无应答）"))
        if ok:
            results.append((baud, parse_regs(data)))
    return results


# ---------------------------------------------------------------- 参数解析
def parse_set(text: str, layout: str) -> dict:
    """把 "channel=23,rate=2.4k" 解析成 {寄存器号: 值}（只含要改的位）。"""
    regs: dict = {}

    def apply(name: str, raw: str) -> None:
        if name in ("channel", "ch"):
            ch = int(raw)
            if not (CHANNEL_RANGE[0] <= ch <= CHANNEL_RANGE[1]):
                raise ValueError("信道需在 %d~%d 之间" % CHANNEL_RANGE)
            if layout == "reg":
                regs[0] = ch & 0xFF
            else:
                regs[1] = ch & 0xFF          # addr 布局下信道在 ADDL 的低 8 位
            return
        if name in ("addr", "address"):
            a = int(raw, 0)
            if layout == "reg":
                raise ValueError("reg 布局没有独立的模块地址，请加 --layout addr")
            regs[0], regs[1] = (a >> 8) & 0xFF, a & 0xFF
            return
        if name in ("netid", "net"):
            if layout == "reg":
                raise ValueError("reg 布局没有网络地址，请加 --layout addr")
            regs[2] = int(raw, 0) & 0xFF
            return
        if name == "baud":
            if raw not in BAUD_OPTIONS:
                raise ValueError("可用波特率：%s" % ", ".join(sorted(BAUD_OPTIONS)))
            set_field(regs, layout, "baud", BAUD_OPTIONS[raw])
            return
        if name in ("rate", "air", "airrate"):
            if raw not in AIR_OPTIONS:
                raise ValueError("可用空中速率：%s" % ", ".join(sorted(AIR_OPTIONS)))
            set_field(regs, layout, "rate", AIR_OPTIONS[raw])
            return
        if name in ("parity", "uart"):
            key = raw.lower()
            if key not in PARITY_OPTIONS:
                raise ValueError("可用校验：8n1 / 8o1 / 8e1")
            set_field(regs, layout, "parity", PARITY_OPTIONS[key])
            return
        if name in ("packet", "subpacket"):
            if raw not in PACKET_OPTIONS:
                raise ValueError("可用分包长度：32 / 64 / 128 / 200(240)")
            set_field(regs, layout, "packet", PACKET_OPTIONS[raw])
            return
        if name in ("power", "pwr"):
            if raw not in POWER_OPTIONS:
                raise ValueError("可用功率：%s" % ", ".join(sorted(POWER_OPTIONS)))
            set_field(regs, layout, "power", POWER_OPTIONS[raw])
            return
        if name == "rssi":
            on = raw.lower() in ("1", "on", "true", "yes", "开启")
            set_field(regs, layout, "rssi", 1 if on else 0)
            return
        raise ValueError("不认识的参数：%s" % name)

    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError("格式应为 key=value：%s" % item)
        key, value = [s.strip() for s in item.split("=", 1)]
        apply(key.lower(), value)
    return regs


def main(argv=None) -> int:
    _setup_stdout()
    p = argparse.ArgumentParser(
        prog="config_e22.py",
        description="E22-400T22S 参数读取/配置工具（需先把 M0=M1=1 进入配置模式）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="不确定寄存器映射时：先用 --read 看原始十六进制，再对照官方手册选择 --layout。")
    p.add_argument("-p", "--port", required=True, help="串口名，如 COM4")
    p.add_argument("-b", "--baud", type=int, default=DEFAULT_BAUD,
                   help="与模块通信的波特率（默认 %d；不知道就先用 --scan）" % DEFAULT_BAUD)
    p.add_argument("--layout", choices=sorted(LAYOUTS), default="reg",
                   help="寄存器布局：reg=REG0 为信道(默认)，addr=ADDH/ADDL 为地址、REG0 为信道")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--scan", action="store_true", help="依次试常见波特率，找出模块当前设置")
    g.add_argument("--listen", type=float, metavar="SECONDS",
                   help="裸监听 N 秒：把串口收到的任何字节原样打印，用来判断串口链路通不通")
    g.add_argument("--params", type=float, metavar="SECONDS",
                   help="反复读参数最多 N 秒（板子上电自动进配置模式时用这个，读到就退出）")
    g.add_argument("--read", action="store_true", help="读出当前全部参数")
    g.add_argument("--version", action="store_true", help="读模块版本")
    g.add_argument("--set", help="设置参数，逗号分隔，如 channel=23,rate=2.4k,baud=9600,power=22")
    g.add_argument("--reset", action="store_true", help="恢复出厂设置")
    args = p.parse_args(argv)

    new_regs = {}
    if args.set:
        try:
            new_regs = parse_set(args.set, args.layout)
        except ValueError as exc:
            raise SystemExit("解析 --set 出错：%s" % exc)

    if args.listen:
        return listen_bytes(args.port, args.baud, args.listen)
    if args.params:
        return read_params_loop(args.port, args.baud, args.params, args.layout)

    import serial

    if args.scan:
        print("[扫描] 依次尝试常见波特率（若全部 ✗，请确认 M0=M1=1 且接线正确）...")
        found = scan_baud(args.port)
        if not found:
            print("\n没有找到模块。请检查：M0=M1=1（配置模式）、TX/RX 交叉接线、USB-TTL 是否正常。")
            return 1
        baud, regs = found[0]
        print("\n找到 %d 个可用波特率，第一个（%d）的参数如下：" % (len(found), baud))
        print("  原始寄存器  : %s" % " ".join("%02X" % regs[i] for i in range(REG_COUNT)))
        print(describe(regs, args.layout))
        print("（如果解释结果和手册不符，换 --layout %s 再看一次）"
              % ("addr" if args.layout == "reg" else "reg"))
        return 0

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.4)
    except Exception as exc:
        print("打开串口 %s 失败：%s" % (args.port, exc), file=sys.stderr)
        return 2

    try:
        if args.read or args.version:
            data = read_version(ser) if args.version else read_regs(ser)
            print("[原始应答] %s" % (data.hex(" ").upper() or "（无应答）"))
            if args.version:
                return 0 if data else 1
            if len(data) < 3 + REG_COUNT or data[0] != 0xC1:
                print("读参数失败。请确认：M0=M1=1（配置模式）、波特率正确（可用 --scan）、"
                      "串口没被别的程序占用。")
                return 1
            regs = parse_regs(data)
            print("[寄存器原始值] " + " ".join("REG%d=0x%02X" % (i, regs[i]) for i in range(REG_COUNT)))
            print("[解释 @ --layout %s]" % args.layout)
            print(describe(regs, args.layout))
            return 0

        if args.reset:
            # 恢复出厂：C0 00 06 + 全 0 + C1 C1 C1
            frame = build_config({i: 0 for i in range(REG_COUNT)})
            print("[恢复出厂] 发送 %s" % frame.hex(" ").upper())
            ser.reset_input_buffer()
            ser.write(frame)
            ser.flush()
            time.sleep(0.3)
            resp = ser.read(16)
            print("[应答] %s" % (resp.hex(" ").upper() or "（无应答）"))
            print("模块参数已回到默认（信道 0 / 9600 8N1 / 22dBm）。注意串口波特率也会变回 9600。")
            return 0 if resp[:3] == b"\xC0\x00\x06" else 1

        if new_regs:
            cur = {}
            data = read_regs(ser)
            if len(data) >= 3 + REG_COUNT and data[0] == 0xC1:
                cur = parse_regs(data)
                print("[当前参数]")
                print(describe(cur, args.layout))
            else:
                print("警告：读不到当前参数，将以出厂默认值(全 0)为基础写入。")
            merged = dict(cur)
            merged.update(new_regs)          # 只覆盖你指定的寄存器，其余保持原值
            frame = build_config(merged)
            print("\n[写入 @ --layout %s] %s" % (args.layout, frame.hex(" ").upper()))
            ser.reset_input_buffer()
            ser.write(frame)
            ser.flush()
            time.sleep(0.3)
            resp = ser.read(16)
            print("[应答] %s" % (resp.hex(" ").upper() or "（无应答）"))
            if resp[:3] != b"\xC0\x00\x06":
                print("✗ 没有收到正确的写入应答，参数可能未生效。")
                return 1
            print("✓ 已写入。请把 M0=M1 拨回 0/0（或断电重启）回到一般模式。新参数：")
            print(describe(merged, args.layout))
            return 0
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
