# -*- coding: utf-8 -*-
"""
parser.py —— 传感器数据帧解析

【本项目的真实协议】源码见 Sender/main.c（GD32E230F6 称重板，Keil 烧写）
板子每轮采集 4 路 HX711 称重传感器（每路 5 次采样取平均，间隔 200ms），
再用 9600 8N1 通过 LoRa 发出下面这一行：

    WB,<序号>,<系统毫秒>,<OK掩码>,<重量0>,<重量1>,<重量2>,<重量3>,<电池mV>,<电量%>\r\n

  字段0  WB        帧头
  字段1  seq       帧序号（每发一帧 +1）
  字段2  ms        单片机 millis()，单位毫秒
  字段3  ok_mask   两字符十六进制位掩码：bit0~bit3 分别表示 4 路 HX711 是否读取成功
                   （0x01=只有第1路，0x03=1/2路，0x0F=4 路全成功；硬件宏 USE_HX711_CH_MASK）
  字段4~7 weight_g 4 路重量，单位【克】，有符号整数
  字段8  bat_mv    电池电压，单位【毫伏】（分压 1000k/470k，ADC 参考 3300mV）
  字段9  bat_pct   电量百分比（3300mV=0%，4200mV=100%）

除上面这种数据帧外，板子上电时还会先发两行纯文本：BOOT_SYSTICK、ADC_INIT_OK。

为了“换一块板子也能用”，除内置的 WB 协议外还保留了自动探测和自定义下标两种方式。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ------------------------------------------------------------------ 字段定义
SENSOR_KEYS = ("s1", "s2", "s3", "s4")
VALUE_KEYS = SENSOR_KEYS + ("batt_v", "batt_pct")

NUMERIC_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
HEXFLAG_RE = re.compile(r"^[0-9A-Fa-f]{1,4}$")


def looks_numeric(text: str) -> bool:
    return bool(NUMERIC_RE.match(text.strip()))


def to_number(text: str) -> Optional[float]:
    text = text.strip()
    if not NUMERIC_RE.match(text):
        return None
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


@dataclass
class Frame:
    """一帧解析结果。status 为 'ok' 表示成功解析出字段。"""

    raw: str
    ts: float = 0.0
    status: str = "ok"                      # ok / raw（只记录原始数据）/ text（板子启动提示行）
    source: str = "auto"                    # 用的哪个解析器
    seq: Optional[Any] = None
    flag: Optional[str] = None
    prefix: str = ""                        # 帧标识（如 WB / S），解析时填
    ms: Optional[int] = None                # 板子自己的 millis()
    board_id: Optional[int] = None          # 板号（新版协议字段1；旧版为 None）
    is_text: bool = False                   # 板子启动提示行（BOOT_SYSTICK 等）
    values: Dict[str, float] = field(default_factory=dict)   # s1..s4(g), batt_v(V), batt_pct(%)
    extra: List[str] = field(default_factory=list)
    error: str = ""

    def get(self, key: str):
        return self.values.get(key)

    def as_row(self) -> Dict[str, Any]:
        row = {"ts": self.ts, "ms": self.ms, "seq": self.seq, "flag": self.flag,
               "board_id": self.board_id,
               "raw": self.raw, "status": self.status, "source": self.source}
        for key in VALUE_KEYS:
            row[key] = self.values.get(key)
        row["extra"] = ",".join(self.extra)
        return row

    # ---------------- WB 称重板语义 ----------------
    @property
    def weight_g(self) -> List[Optional[float]]:
        """4 路重量（克）。"""
        return [self.values.get("s%d" % (i + 1)) for i in range(4)]

    @property
    def battery_mv(self) -> Optional[float]:
        """
        电池电压（毫伏）。

        源码 send_packet() 里第 9 个字段就是 bat_mv（毫伏），恒为正数。
        容错：内部约定 batt_v 存“伏”，但也可能被存成毫伏。这里按数值范围
        自动识别（>100 一律视为毫伏），并对负值做归零保护——负电压在物理上
        不可能，出现负值只可能是解析错位，此时宁可显示 0 也不显示误导性数字。
        """
        volts = self.values.get("batt_v")
        if volts is None:
            return None
        mv = float(volts) if abs(volts) > 100 else float(volts) * 1000.0
        if mv < 0:
            return 0.0
        return mv

    def channel_ok(self, index: int) -> Optional[bool]:
        """第 index 路（0~3）本次是否读取成功——来自 ok_mask 的对应位。"""
        if not self.flag:
            return None
        try:
            mask = int(self.flag, 16)
        except ValueError:
            return None
        return bool(mask & (1 << index))

    def ok_channels(self) -> Optional[str]:
        """把 ok_mask 描述成人话，例如 0x0F -> '4 路全部正常'。"""
        if not self.flag:
            return None
        try:
            mask = int(self.flag, 16)
        except ValueError:
            return None
        names = [str(i + 1) for i in range(4) if mask & (1 << i)]
        if not names:
            return "4 路全部读取失败"
        if len(names) == 4:
            return "4 路全部正常"
        return "仅第 %s 路正常" % "、".join(names)


# ------------------------------------------------------------------ 解析配置
@dataclass
class ParseConfig:
    """
    自定义解析配置：用“字段在分隔后的第几个位置”来描述。

    index 为 None 表示该字段没有；下标从 0 开始。
    """

    name: str = "自定义"
    delimiter: str = ","
    skip_prefix: bool = True          # 是否丢掉第一个字段（那种 WB/帧头 之类）
    seq_index: Optional[int] = 1
    s1_index: Optional[int] = 2
    s2_index: Optional[int] = 3
    s3_index: Optional[int] = 4
    s4_index: Optional[int] = 5
    batt_v_index: Optional[int] = 6
    batt_pct_index: Optional[int] = 7
    flag_index: Optional[int] = None
    auto_detect: bool = True          # 自动探测（关闭则只用本配置）
    seq_mode: str = "auto"            # 纯数值帧里第 1 个数字：auto/always/never 当序号

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict) -> "ParseConfig":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


# ------------------------------------------------------------------ 解析器
class FrameParser:
    """把一行文本解析成 Frame。"""

    # 只含数字与分隔符的帧（很多板子直接发一串数）
    _SPLIT_RE = re.compile(r"[,;\t ]+")

    def __init__(self, config: Optional[ParseConfig] = None):
        self.config = config or ParseConfig()

    # ---------------- 对外接口 ----------------
    def parse(self, line: str, ts: float = 0.0) -> Frame:
        text = line.strip("\r\n").strip()
        frame = Frame(raw=text, ts=ts)
        if not text:
            frame.status = "raw"
            frame.error = "空行"
            return frame

        # 0) 板子上电时会先发几行纯文本提示，单独标出来（不算解析失败）
        if text in ("BOOT_SYSTICK", "ADC_INIT_OK") or "INIT_OK" in text:
            frame.status = "text"
            frame.is_text = True
            frame.source = "板子启动提示"
            return frame

        # 1) 本项目真实协议：WB 称重板（优先级最高，格式固定，不做猜测）
        if self._parse_wb(text, frame):
            frame.status = "ok"
            frame.source = "WB 称重板协议"
            return frame

        # 2) 用户自定义配置优先（关掉自动探测时也一样走这里）
        if not self.config.auto_detect:
            self._apply_config(text, frame, self.config)
            if frame.status == "ok":
                frame.source = self.config.name
            return frame

        # 3) 自动探测：依次尝试内置格式
        for name, func in (("逗号数值", self._parse_csv_numbers),
                           ("键值对", self._parse_key_value),
                           ("任意分隔数值", self._parse_any_numbers)):
            if func(text, frame):
                frame.status = "ok"
                frame.source = ("%s(带标识 %s)" % (name, frame.prefix)) if frame.prefix else name
                return frame

        # 4) 兜底：只记录原始数据
        frame.status = "raw"
        frame.error = "未识别格式"
        return frame

    # ---------------- 本项目真实协议 ----------------
    def _parse_wb(self, text: str, frame: Frame) -> bool:
        """
        解析 Sender/main.c 里 send_packet() 发出的帧。

        支持两种格式（自动识别，方便分批升级板子）：

          新版（带板号，字段1=板号）：
              WB,board,seq,ms,ok_mask,w0,w1,w2,w3,bat_mv,bat_pct      11 字段
          旧版（无板号）：
              WB,seq,ms,ok_mask,w0,w1,w2,w3,bat_mv,bat_pct            10 字段

        识别方法：看字段3 是不是两位十六进制掩码（如 0F）。
        新版字段3 是系统毫秒（大整数，不是 0F），旧版字段3 就是掩码。

        容错：串口按 \\n 断行时，行首可能残留一个 \\r 或别的脏字节
        （实测出现过 "d\\rWB,..." 这种），导致 WB 标识匹配不上而落到
        通用解析器、字段全部错位。这里对行首脏字符做清理。
        """
        # 清掉行首的空格/回车/换行/制表等不可见字符
        cleaned = text.lstrip(" \t\r\n\v\f")
        parts = [p.strip() for p in cleaned.split(",")]

        # 行首仍是脏数据时（如 "d\rWB"），在第一个字段里找 "WB"
        if parts and parts[0] != "WB" and "WB" in parts[0]:
            parts[0] = "WB"

        if len(parts) < 10 or parts[0] != "WB":
            return False
        if not looks_numeric(parts[1]):
            return False

        def number(index: int, default=None):
            value = to_number(parts[index])
            return default if value is None else value

        # 判断是哪个版本：字段3 像十六进制掩码(0F/01/1F...) => 旧版
        field3 = parts[3].strip()
        old_style = (len(field3) <= 2 and HEXFLAG_RE.match(field3) is not None)
        if old_style:
            board, seq_i, ms_i, mask_i, w_i, mv_i, pct_i = None, 1, 2, 3, 4, 8, 9
        else:
            board, seq_i, ms_i, mask_i, w_i, mv_i, pct_i = 1, 2, 3, 4, 5, 9, 10

        if len(parts) < pct_i + 1:
            return False

        frame.prefix = "WB"
        frame.board_id = number(board) if board is not None else None
        frame.seq = number(seq_i)
        frame.ms = number(ms_i)
        frame.flag = parts[mask_i].upper()
        for index in range(4):
            value = number(w_i + index)
            if value is not None:
                frame.values["s%d" % (index + 1)] = value        # 单位：克
        mv = number(mv_i)
        if mv is not None:
            frame.values["batt_v"] = mv / 1000.0                 # 毫伏 -> 伏
        pct = number(pct_i)
        if pct is not None:
            frame.values["batt_pct"] = pct
        for index in range(pct_i + 1, len(parts)):
            frame.extra.append(parts[index])
        return bool(frame.values)

    # ---------------- 内置格式 ----------------
    def _parse_csv_numbers(self, text: str, frame: Frame) -> bool:
        """逗号（或分号/制表/空格）分隔的数值列表：A,12,3.4,... 或 12,3.4,..."""
        parts = [p for p in self._SPLIT_RE.split(text) if p != ""]
        if len(parts) < 3:
            return False
        numbers = []
        for p in parts:
            if looks_numeric(p):
                numbers.append(to_number(p))
        if len(numbers) < 3:
            return False

        head_is_number = looks_numeric(parts[0])
        if head_is_number:
            # 纯数值帧：第 1 个数字是不是序号，按 seq_mode 决定
            if self.config.seq_mode == "always":
                frame.seq = numbers[0]
                rest = numbers[1:]
            elif self.config.seq_mode == "never":
                frame.seq = None
                rest = numbers
            elif len(numbers) == len(SENSOR_KEYS):
                # auto：刚好 4 个数字，当成 4 路传感器读数
                frame.seq = None
                rest = numbers
            else:
                frame.seq = numbers[0]
                rest = numbers[1:]
        else:
            # 带标识帧（WB / S / NODE1 ...）：标识后的第 1 个数字当序号
            frame.prefix = parts[0]
            frame.seq = numbers[0]
            rest = numbers[1:]

        # 十六进制状态字（如 0F）
        for p in parts:
            if not looks_numeric(p) and HEXFLAG_RE.match(p) and len(p) <= 4:
                frame.flag = p.upper()
                break

        self._fill_values(frame, rest)
        return bool(frame.values)

    def _parse_key_value(self, text: str, frame: Frame) -> bool:
        """键值对：T1=25.6,T2=26.1,BATT=3.85  或  {"T1":25.6,"T2":26.1}"""
        pairs = re.findall(r"([A-Za-z_][A-Za-z_0-9]*)\s*[=:]\s*([+-]?\d+\.?\d*)", text)
        if len(pairs) < 2:
            return False
        numbers = [to_number(v) for _, v in pairs]
        self._fill_values(frame, numbers)
        # 键名里含 batt/vol/电池 的优先当电池
        for key, value in pairs:
            low = key.lower()
            if ("batt" in low or "vol" in low or "电池" in key) and "batt_v" not in frame.values:
                frame.values["batt_v"] = to_number(value)
            if ("pct" in low or "percent" in low or "soc" in low) and "batt_pct" not in frame.values:
                frame.values["batt_pct"] = to_number(value)
        return bool(frame.values)

    def _parse_any_numbers(self, text: str, frame: Frame) -> bool:
        """从任意文本里抓出所有数字（最后手段，但比只记原始数据有用）。"""
        numbers = [to_number(m) for m in re.findall(r"[+-]?\d+\.?\d*", text)]
        numbers = [n for n in numbers if n is not None]
        if len(numbers) < 3:
            return False
        self._fill_values(frame, numbers)
        return bool(frame.values)

    # ---------------- 工具 ----------------
    @staticmethod
    def _fill_values(frame: Frame, numbers: List[float]) -> None:
        """
        把数字填进 s1..s4 / batt_v / batt_pct，剩余进 extra。

        只按顺序硬填会张冠李戴（比如本机那种 WB,...,3906,67 的帧，
        末位 67 明显是电量，3906 才不是）。所以这里用轻量启发式：
          · 末位数字若在 0~100 且带小数的可能性低 -> 当电量(%)
          · 末位前一个若在 2.5~5.5 -> 当电池电压(V)（锂电常见范围）
          · 其余按顺序填 s1..s4
        数量刚好匹配时（4 个传感器 + 电压 + 电量）不做任何猜测。
        """
        numbers = list(numbers)
        battery: Dict[str, float] = {}

        if len(numbers) > len(VALUE_KEYS):
            # 数字比槽位多：从尾部识别电量、电压
            last = numbers[-1]
            if 0 <= last <= 100 and float(last).is_integer():
                battery["batt_pct"] = numbers.pop()
            if numbers and 2.5 <= numbers[-1] <= 5.5:
                battery["batt_v"] = numbers.pop()

        keys = ["s1", "s2", "s3", "s4", "batt_v", "batt_pct"]
        # 已经通过尾部启发式识别出来的键，跳过对应槽位
        skip = {"batt_pct"} if "batt_pct" in battery else set()
        if "batt_v" in battery:
            skip.add("batt_v")
        slot = 0
        for num in numbers:
            while slot < len(keys) and keys[slot] in skip:
                slot += 1
            if slot < len(keys):
                frame.values[keys[slot]] = num
                slot += 1
            else:
                frame.extra.append(str(num))
        frame.values.update(battery)

    def _apply_config(self, text: str, frame: Frame, cfg: ParseConfig) -> None:
        """按用户配置的下标取字段。"""
        parts = [p.strip() for p in self._SPLIT_RE.split(text) if p.strip() != ""]
        if len(parts) < 2:
            frame.status = "raw"
            frame.error = "字段太少"
            return

        def take(index: Optional[int]):
            if index is None or index >= len(parts):
                return None
            return parts[index]

        seq_text = take(cfg.seq_index)
        if seq_text is not None and looks_numeric(seq_text):
            frame.seq = to_number(seq_text)

        mapping = {"s1": cfg.s1_index, "s2": cfg.s2_index, "s3": cfg.s3_index,
                   "s4": cfg.s4_index, "batt_v": cfg.batt_v_index,
                   "batt_pct": cfg.batt_pct_index}
        for key, index in mapping.items():
            text_value = take(index)
            if text_value is None:
                continue
            number = to_number(text_value)
            if number is not None:
                frame.values[key] = number

        flag = take(cfg.flag_index)
        if flag:
            frame.flag = flag.upper()
        frame.status = "ok" if frame.values else "raw"
        if not frame.values:
            frame.error = "配置的下标没有取到数值"

    # ---------------- 格式说明（给界面用） ----------------
    @staticmethod
    def describe_builtin() -> List[str]:
        return [
            "逗号数值  : WB,1294,1402502,0F,-12233,-9386,-3775,-15521  或  25.6,26.1,3.85",
            "键值对    : T1=25.6,T2=26.1,BATT=3.85",
            "任意数值  : 从文本中抓出所有数字（兜底）",
        ]
