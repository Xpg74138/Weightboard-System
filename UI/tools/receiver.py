# -*- coding: utf-8 -*-
"""
receiver.py —— E22-400T22S LoRa 接收端小程序

作用：
    打开 E22-400T22S 所接的串口（USB 转 TTL / 开发板虚拟串口），
    持续接收发送端发来的无线数据，并按“整包”打印（十六进制 + 文本）。

模块侧的接线与设置（硬件，不用改程序）：
    1) M0 = 0, M1 = 0  ->  一般模式（透明传输），能收能发；
    2) 收发两端的 信道(信道/频率)、空中速率、数据位/校验/停止位 必须完全一致，
       否则收不到数据（程序里用 --check 可以做一致性检查）。
    3) 默认串口：9600 8N1，所以本程序默认 9600。

运行示例（先安装 requirements.txt 中的依赖）：
    python -m tools.receiver --port COM4
    python -m tools.receiver --port COM4 --mode text --raw -o recv.log
"""

from __future__ import annotations

import argparse
import codecs
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

# --------------------------------------------------------------------------
# 默认参数
# --------------------------------------------------------------------------
DEFAULT_BAUD = 9600          # E22 出厂默认串口波特率
DEFAULT_GAP = 0.15           # 断包间隔（秒）：串口空闲超过该时间即认为一包结束
DEFAULT_RAW_FILE = os.path.join("artifacts", "captures", "raw_capture.bin")


# --------------------------------------------------------------------------
# 终端编码：Windows 控制台默认可能是 GBK，这里统一用 UTF-8 打印，避免中文乱码
# --------------------------------------------------------------------------
def _setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Python 3.7+
        except Exception:
            pass


# --------------------------------------------------------------------------
# 整包读取：把串口字节流切成一个个“包”
# --------------------------------------------------------------------------
@dataclass
class Packet:
    """一包接收到的数据。"""

    data: bytes          # 原始字节
    rx_ts: float         # 收到时刻（time.time()）
    gap_s: Optional[float] = None   # 距离上一包的间隔（秒）


class PacketReader:
    """
    从串口读取数据并按包返回。

    两种组包方式：
      framing = "gap"  （默认，推荐给 LoRa）
          读到第一个字节后再等 `gap` 秒，期间到达的字节都算同一包；
          串口安静超过 `gap` 秒即输出一包。对应“发送方用 Serial.print 发一整条”的场景。
      framing = "line"
          按换行符（\\n，自动去掉 \\r）组包，对应“发送方用 println 发一整行”的场景。
    """

    def __init__(self, ser, gap: float = DEFAULT_GAP, framing: str = "gap", chunk: int = 4096,
                 wait_timeout: float = 1.0):
        self.ser = ser
        self.gap = float(gap)
        self.framing = framing
        self.chunk = chunk
        self.wait_timeout = wait_timeout   # 一次 read() 最多等多久（秒），0=一直等
        self.packets = 0                 # 已输出的包数
        self.total_bytes = 0             # 已输出的字节数
        self._buf = bytearray()
        self._last_byte_ts: Optional[float] = None
        self._pending: list[bytes] = []  # line 模式下待补 \n 的完整行

    # ---------------- 对外接口 ----------------
    def read(self) -> Optional[Packet]:
        """
        返回下一整包；如果超过 wait_timeout 秒还凑不出一整包就返回 None。

        内部会等到“断包条件成立”才返回，不会半路吐出半包；等待期间真正的阻塞在
        ser.read 上（受 ser.timeout 限制），所以 CPU 占用接近 0。
        """
        started = time.monotonic()
        data = None
        while data is None:
            data = self._next_frame()
            if self.wait_timeout and (time.monotonic() - started) >= self.wait_timeout:
                return None          # 只是暂时没数据，不丢任何已收到的字节
        self.packets += 1
        self.total_bytes += len(data)
        return Packet(data=data, rx_ts=time.time())

    # ---------------- 内部实现 ----------------
    def _pending_data(self) -> bool:
        if self._pending:
            return True
        try:
            n = self.ser.in_waiting
        except Exception:
            n = 0
        return bool(n) or bool(self._buf)

    def _next_frame(self) -> Optional[bytes]:
        if self._pending:
            return self._pending.pop(0)

        if self.framing == "line":
            return self._read_line()

        if not self._buf:
            # 缓冲区是空的：直接阻塞读一次（最多阻塞 ser.timeout），避免空转返回 None
            self._raw_read()
        if self._buf and self._quiet_enough():
            # 串口安静够了 => 一包结束
            out = bytes(self._buf)
            self._buf.clear()
            self._last_byte_ts = None
            return out
        return None

    def _quiet_enough(self) -> bool:
        """缓冲区里有数据，且距离最后一个字节已超过 gap 秒。"""
        return (self._last_byte_ts is not None
                and (time.monotonic() - self._last_byte_ts) >= self.gap)

    def _read_line(self) -> Optional[bytes]:
        self._extract_lines()
        if not self._pending:
            self._raw_read()
            self._extract_lines()
        if self._pending:
            return self._pending.pop(0)
        return None

    def _extract_lines(self) -> None:
        """把缓冲区里所有完整的行（以 \\n 结尾）取出来，去掉 \\r。"""
        while True:
            idx = self._buf.find(b"\n")
            if idx < 0:
                break
            raw = bytes(self._buf[: idx + 1])
            del self._buf[: idx + 1]
            self._pending.append(raw[:-1].rstrip(b"\r"))

    def _raw_read(self) -> bytes:
        """读一次串口（read 会按 ser.timeout 阻塞，空闲时不烧 CPU）。"""
        try:
            data = self.ser.read(self.chunk)
        except Exception as exc:  # 串口被拔掉等
            raise IOError("串口读取失败：%s" % exc) from exc
        if data:
            self._buf.extend(data)
            self._last_byte_ts = time.monotonic()
        return data or b""


# --------------------------------------------------------------------------
# 打印 / 记录
# --------------------------------------------------------------------------
class OutputPrinter:
    """按用户选择的格式打印收到的包，可选同时写文本日志和原始二进制抓包。"""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.n = 0
        self.bytes_total = 0
        self.started = time.time()
        self.last_ts: Optional[float] = None
        # 跨包拼接 UTF-8（一包结尾被截断的多字节汉字会在下一包补齐）
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._log = None
        self._raw = None

    # ---------------- 打开/关闭输出文件 ----------------
    def open(self) -> None:
        for path in (self.args.output, self.args.raw_file):
            if path:
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if self.args.output:
            self._log = open(self.args.output, "a", encoding="utf-8", newline="\n")
        if self.args.raw_file:
            self._raw = open(self.args.raw_file, "ab")

    def close(self) -> None:
        for f in (self._log, self._raw):
            if f:
                try:
                    f.close()
                except Exception:
                    pass
        self._log = self._raw = None

    # ---------------- 处理一包 ----------------
    def emit(self, pkt: Packet) -> None:
        self.n += 1
        self.bytes_total += len(pkt.data)
        if self.last_ts is not None:
            pkt.gap_s = pkt.rx_ts - self.last_ts
        self.last_ts = pkt.rx_ts

        text = self._decoder.decode(pkt.data)      # 文本视图
        window = pkt.data.decode("utf-8", "replace")  # 该包独立解码（只用于显示，不做拼接）

        lines: list[str] = []
        if not self.args.quiet:
            lines.append(self._header(pkt))
        mode = self.args.mode
        if mode == "hex":
            lines.append("  HEX  " + pkt.data.hex(" ").upper())
        elif mode == "text":
            lines.append("  TEXT " + repr(window)[1:-1])
        else:  # both
            lines.append("  HEX  " + pkt.data.hex(" ").upper())
            lines.append("  TEXT " + repr(window)[1:-1])
        if self.args.show_decoded:
            lines.append("  UTF8 " + repr(text)[1:-1])

        if self.args.raw:
            self._write_raw(pkt)
        else:
            for line in lines:
                self._out(line)

        if self._log:
            stamp = datetime.fromtimestamp(pkt.rx_ts).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            gap = "" if pkt.gap_s is None else " gap=%.3fs" % pkt.gap_s
            self._log.write("[%s] #%d len=%d%s data=%s\n"
                            % (stamp, self.n, len(pkt.data), gap, pkt.data.hex(" ").upper()))
            self._log.flush()

    def _header(self, pkt: Packet) -> str:
        parts = []
        if not self.args.no_ts:
            parts.append(datetime.fromtimestamp(pkt.rx_ts).strftime(self.args.ts_format))
        parts.append("#%d" % self.n)
        parts.append("len=%d" % len(pkt.data))
        if self.args.show_gap and pkt.gap_s is not None:
            parts.append("gap=%.3fs" % pkt.gap_s)
        return "[" + " | ".join(parts) + "]"

    # ---------------- 底层写 ----------------
    def _out(self, line: str) -> None:
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            sys.stdout.write(line.encode("utf-8", "replace").decode("utf-8", "replace") + "\n")
            sys.stdout.flush()

    def _write_raw(self, pkt: Packet) -> None:
        buf = sys.stdout.buffer
        if not self.args.no_ts:
            buf.write(("[%s] " % datetime.fromtimestamp(pkt.rx_ts)
                       .strftime(self.args.ts_format)).encode("utf-8"))
        buf.write(pkt.data)
        if not pkt.data.endswith(b"\n"):
            buf.write(b"\n")
        buf.flush()

    def write_raw_file(self, pkt: Packet) -> None:
        if self._raw:
            self._raw.write(pkt.data)
            self._raw.flush()

    # ---------------- 统计 ----------------
    def stats_line(self) -> str:
        elapsed = max(time.time() - self.started, 1e-9)
        rate = self.bytes_total / elapsed
        head = "[统计] 运行 %.0f 秒 | 收到 %d 包 / %d 字节 | 平均 %.1f B/s" % (
            elapsed, self.n, self.bytes_total, rate)
        if self.n and self.last_ts:
            return head + " | (最近一包 %s)" % datetime.fromtimestamp(
                self.last_ts).strftime(self.args.ts_format)
        return head


# --------------------------------------------------------------------------
# 自动识别波特率
# --------------------------------------------------------------------------
AUTO_BAUDS = (9600, 57600, 115200, 19200, 38400)
AUTO_PROBE_AFTER = 10.0          # 启动后多少秒没数据就开始自动找波特率


def auto_baud_detect(port: str, candidates=AUTO_BAUDS, per_baud: float = 6.0,
                     bytesize: int = 8, parity: str = "N", stopbits: float = 1):
    """
    依次在候选波特率上试听，返回 (波特率, 收到的字节)；都不行返回 (None, b'').

    判断标准：收到任何字节就算命中（LoRa 数据是整帧到达的，只要波特率对，
    帧头那几个 ASCII 字节几乎必然能读到）。
    """
    import serial
    empty = b""
    for baud in candidates:
        try:
            ser = serial.Serial(port, baud, bytesize=bytesize, parity=parity,
                                stopbits=stopbits, timeout=0.2, dsrdtr=False)
        except Exception as exc:
            print("  %-7d 打不开：%s" % (baud, str(exc)[:70]))
            continue
        try:
            ser.reset_input_buffer()
            data = bytearray()
            t0 = time.time()
            while time.time() - t0 < per_baud:
                chunk = ser.read(8192)
                if chunk:
                    data += chunk
                    break
        finally:
            ser.close()
        if data:
            print("  %-7d ✓ 收到 %d 字节：%s" % (baud, len(data), bytes(data[:48])))
            return baud, bytes(data)
        print("  %-7d ✗ 无数据" % baud)
    return None, empty


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="receiver.py",
        description="E22-400T22S LoRa 接收端：从串口接收发送端发来的无线数据并整包打印。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="提示：M0=M1=0（一般模式）、收发两端信道/空中速率/串口参数一致，才能收到数据。")

    p.add_argument("-p", "--port", default="COM4", help="串口名，如 COM4（默认 COM4）")
    p.add_argument("-b", "--baud", type=int, default=DEFAULT_BAUD,
                   help="串口波特率（默认 %d，与模块设置的波特率一致）" % DEFAULT_BAUD)
    p.add_argument("--bytesize", type=int, default=8, choices=(5, 6, 7, 8), help="数据位，默认 8")
    p.add_argument("--parity", default="N", choices=("N", "E", "O", "M", "S"), help="校验位，默认 N")
    p.add_argument("--stopbits", type=float, default=1, choices=(1, 1.5, 2), help="停止位，默认 1")

    p.add_argument("--framing", choices=("gap", "line"), default="gap",
                   help="组包方式：gap=按空闲间隔断包(默认)；line=按换行断包")
    p.add_argument("--gap", type=float, default=DEFAULT_GAP,
                   help="gap 模式的断包间隔秒数（默认 %s）" % DEFAULT_GAP)

    p.add_argument("--mode", choices=("both", "hex", "text"), default="both",
                   help="显示方式：both=HEX+TEXT(默认)，hex=只要十六进制，text=只要文本")
    p.add_argument("--raw", action="store_true", help="只把原始数据写到标准输出（便于重定向/管道）")
    p.add_argument("--show-decoded", action="store_true",
                   help="额外显示跨包拼接后的 UTF-8 文本（发送方发中文且被拆包时有用）")
    p.add_argument("--show-gap", action="store_true", help="在包头显示与上一包的间隔时间")
    p.add_argument("--no-ts", action="store_true", help="不显示时间戳")
    p.add_argument("--ts-format", default="%H:%M:%S.%f",
                   help="时间戳格式，默认 %%H:%%M:%%S.%%f（小时:分:秒.微秒）")
    p.add_argument("-q", "--quiet", action="store_true", help="不显示包头（#序号/长度），只输出数据")

    p.add_argument("-o", "--output", help="同时把每包记录写入文本日志文件（追加）")
    p.add_argument("--raw-file", nargs="?", const=DEFAULT_RAW_FILE, default=None,
                   metavar="FILE", help="把原始字节追加写入文件（不带参数则用 %s）" % DEFAULT_RAW_FILE)
    p.add_argument("--max-packets", type=int, default=0, help="收满 N 包后自动退出（0=不限）")
    p.add_argument("--stats-every", type=float, default=60.0,
                   help="每多少秒打印一次统计（0=关闭，默认 60）")
    p.add_argument("--check", action="store_true",
                   help="启动前做串口自检（端口是否存在/能否打开/是否被占用），然后退出")
    p.add_argument("--reconnect", type=float, default=0.0, metavar="SECONDS",
                   help="串口掉线/设备被拔掉时自动等 N 秒重试重连（0=关闭，默认关闭）")
    p.add_argument("--auto-baud", action="store_true",
                   help="启动后若 %d 秒收不到数据，自动依次试 %s 找对波特率"
                        % (AUTO_PROBE_AFTER, "/".join(str(b) for b in AUTO_BAUDS)))
    return p


# --------------------------------------------------------------------------
# 串口自检
# --------------------------------------------------------------------------
def run_check(port: str, baud: int) -> int:
    import serial
    from serial.tools import list_ports

    print("[自检] 当前系统识别到的串口：")
    ports = list(list_ports.comports())
    if not ports:
        print("  （没有发现任何串口：检查 USB 线/驱动，或开发板是否已上电）")
    for info in ports:
        mark = "  <== 你要用的口" if info.device.upper() == port.upper() else ""
        print("  %-6s %s%s" % (info.device, info.description, mark))

    print("\n[自检] 尝试打开 %s @ %d 8N1 ..." % (port, baud))
    try:
        ser = serial.Serial(port, baud, timeout=0.3)
    except Exception as exc:
        print("  ✗ 打不开：%s" % exc)
        print("  常见原因：")
        print("    1) 端口被别的程序占用（串口助手、Arduino IDE 串口监视器、STM32CubeProgrammer 等）→ 关掉它们；")
        print("    2) 端口号不对或被拔掉；")
        print("    3) 需要装驱动（CH340 / CP210x / 开发板自带 CDC 驱动）。")
        return 1
    print("  ✓ 打开成功：%s" % ser.name)
    ser.timeout = 0.5
    print("  等待 3 秒，看是否有数据进来（请在发送端发一条测试数据）...")
    deadline = time.time() + 3
    got = b""
    while time.time() < deadline:
        got += ser.read(4096)
        if got:
            break
    if got:
        print("  ✓ 收到 %d 字节：%s" % (len(got), got.hex(" ").upper()))
        print("    文本：%r" % got.decode("utf-8", "replace"))
    else:
        print("  - 3 秒内没有数据。若发送端确实在发，请核对：")
        print("    · 收发两端 信道、空中速率、分包长度、串口波特率 是否一致；")
        print("    · 模块 M0=M1=0（一般模式）；天线是否接好；")
        print("    · 串口波特率是否与模块设置一致（默认 9600）。")
    ser.close()
    return 0


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def receive(args: argparse.Namespace) -> int:
    import serial

    def open_port():
        return serial.Serial(
            port=args.port,
            baudrate=args.baud,
            bytesize=args.bytesize,
            parity=args.parity,
            stopbits=args.stopbits,
            timeout=min(args.gap, 0.2),   # 空闲 0.2 秒就返回，保证断包判定及时
            write_timeout=1,
            dsrdtr=False,                 # 不动 DTR，避免某些板子被复位
        )

    try:
        ser = open_port()
    except Exception as exc:
        # 开了重连就先等端口可用（设备被拔掉/CDC 处于坏状态时很有用）
        if not args.reconnect:
            print("打开串口 %s 失败：%s" % (args.port, exc), file=sys.stderr)
            print("提示：先运行  python -m tools.receiver --check --port %s  做自检；" % args.port,
                  file=sys.stderr)
            print("      或加 --reconnect 1，让程序自己等设备插入/恢复。", file=sys.stderr)
            return 2
        print("打开串口 %s 失败：%s" % (args.port, str(exc)[:110]))
        print("已开启重连，等待设备可用（把板子插上/拔插一次即可，Ctrl+C 退出）...", flush=True)
        t_wait = time.time()
        while True:
            try:
                ser = open_port()
                print("  ✓ %s 已就绪（等了 %.0f 秒），开始接收。\n" % (ser.name, time.time() - t_wait),
                      flush=True)
                break
            except Exception as exc2:
                print("  [%4.0fs] 还没好：%s" % (time.time() - t_wait, str(exc2)[:90]), flush=True)
                time.sleep(max(args.reconnect, 0.5))

    reader = PacketReader(ser, gap=args.gap, framing=args.framing)
    printer = OutputPrinter(args)
    printer.open()

    print("=" * 68)
    print(" E22-400T22S LoRa 接收端已启动")
    print(" 串口      : %s @ %d %d%s%s" % (ser.name, args.baud, args.bytesize,
                                           args.parity, int(args.stopbits)))
    print(" 组包方式  : %s%s" % (args.framing,
                                 ("（空闲 %.0f ms 断包）" % (args.gap * 1000))
                                 if args.framing == "gap" else ""))
    print(" 显示方式  : %s%s%s" % (args.mode,
                                   "，原始输出" if args.raw else "",
                                   "，静默包头" if args.quiet else ""))
    if args.output:
        print(" 文本日志  : %s（追加）" % args.output)
    if args.raw_file:
        print(" 原始抓包  : %s（追加）" % args.raw_file)
    if args.reconnect:
        print(" 掉线重连  : 开启（设备被拔掉/串口故障时自动等待重新插入）")
    print(" 退出      : 按 Ctrl+C")
    print("=" * 68, flush=True)

    last_stats = time.time()
    exit_code = 0
    autobaud_deadline = (time.time() + AUTO_PROBE_AFTER) if args.auto_baud else None
    try:
        while True:
            try:
                pkt = reader.read()
            except IOError as exc:
                # 串口故障/设备被拔掉：开了重连就等它回来，否则退出
                print("\n串口错误：%s" % exc, file=sys.stderr, flush=True)
                try:
                    ser.close()
                except Exception:
                    pass
                if not args.reconnect:
                    print("（加 --reconnect 可以让程序自动等设备重新插入后继续收）",
                          file=sys.stderr)
                    exit_code = 3
                    break
                while True:
                    print("等待 %s 重新可用（把设备插回去即可，Ctrl+C 退出）..."
                          % args.port, flush=True)
                    time.sleep(max(args.reconnect, 0.5))
                    try:
                        ser = open_port()
                    except Exception as exc2:
                        print("  还没好：%s" % exc2, flush=True)
                        continue
                    reader = PacketReader(ser, gap=args.gap, framing=args.framing)
                    print("  ✓ 已重连 %s，继续接收。" % ser.name, flush=True)
                    break
                continue

            if pkt is not None:
                printer.emit(pkt)
                printer.write_raw_file(pkt)
                if args.max_packets and printer.n >= args.max_packets:
                    break
            elif autobaud_deadline and time.time() >= autobaud_deadline:
                # 启动至今一包都没收到 -> 自动找波特率
                autobaud_deadline = None
                print("\n%d 秒内没收到数据，开始自动识别波特率（每次 6 秒）..."
                      % int(AUTO_PROBE_AFTER), flush=True)
                try:
                    ser.close()
                except Exception:
                    pass
                baud, sniffed = auto_baud_detect(
                    args.port, bytesize=args.bytesize, parity=args.parity,
                    stopbits=args.stopbits)
                if baud is None:
                    print("没找到能收到数据的波特率。请确认：模块处于透明传输模式(M0=M1=0)、"
                          "发送端在发、收发两端信道与空中速率一致。", flush=True)
                    print("（继续用 %d 监听，也可 Ctrl+C 退出）" % args.baud, flush=True)
                    ser = open_port()
                else:
                    print("★ 锁定波特率 %d，继续接收。\n" % baud, flush=True)
                    args.baud = baud
                    ser = serial.Serial(port=args.port, baudrate=baud, bytesize=args.bytesize,
                                        parity=args.parity, stopbits=args.stopbits,
                                        timeout=min(args.gap, 0.2), dsrdtr=False)
                    if sniffed:      # 把探测时先抓到的数据也算进来，不浪费
                        reader = PacketReader(ser, gap=args.gap, framing=args.framing)
                        first = Packet(data=sniffed, rx_ts=time.time())
                        printer.emit(first)
                        printer.write_raw_file(first)
                reader = PacketReader(ser, gap=args.gap, framing=args.framing)
                last_stats = time.time()
            if args.stats_every and time.time() - last_stats >= args.stats_every:
                last_stats = time.time()
                if not args.raw:
                    print(printer.stats_line(), flush=True)
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，准备退出 ...", flush=True)
    finally:
        printer.close()
        try:
            ser.close()
        except Exception:
            pass
        print(printer.stats_line(), flush=True)
    return exit_code


def main(argv: Optional[list[str]] = None) -> int:
    _setup_stdout()
    args = build_parser().parse_args(argv)
    if args.check:
        return run_check(args.port, args.baud)
    return receive(args)


if __name__ == "__main__":
    sys.exit(main())
