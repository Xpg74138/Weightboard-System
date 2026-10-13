# -*- coding: utf-8 -*-
"""
storage.py —— CSV 记录（长稳运行用）

每收到一帧追加一行，立即 flush，所以拔电/崩溃也不会丢太多。
列固定为：时间、序号、状态字、s1..s4、电池电压、电量、解析方式、原始数据。
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Optional

from .parser import Frame

CSV_HEADER = ["时间", "时间戳", "板号", "序号(字段2)", "板子毫秒(字段3)", "OK掩码(字段4)",
              "传感器1(字段5)", "传感器2(字段6)", "传感器3(字段7)", "传感器4(字段8)",
              "电池电压mV(字段9)", "电量%(字段10)", "解析方式", "状态", "原始数据"]


class CsvRecorder:
    """把每一帧写成一行 CSV。"""

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._file = None
        self._writer = None
        self.rows = 0

    # ---------------- 开关 ----------------
    def open(self, path: str) -> None:
        self.close()
        self.path = path
        new_file = not os.path.exists(path) or os.path.getsize(path) == 0
        self._file = open(path, "a", newline="", encoding="utf-8-sig")
        self._writer = csv.writer(self._file)
        if new_file:
            self._writer.writerow(CSV_HEADER)
        self.rows = 0

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
        self._file = None
        self._writer = None

    @property
    def is_open(self) -> bool:
        return self._file is not None

    # ---------------- 写入 ----------------
    def write(self, frame: Frame) -> None:
        if self._writer is None:
            return
        row = frame.as_row()
        stamp = datetime.fromtimestamp(frame.ts).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self._writer.writerow([
            stamp, "%.6f" % frame.ts, _s(frame.board_id),
            _s(row["seq"]), _s(row["ms"]), _s(row["flag"]),
            _s(row["s1"]), _s(row["s2"]), _s(row["s3"]), _s(row["s4"]),
            "" if frame.battery_mv is None else "%.0f" % frame.battery_mv,
            _s(row["batt_pct"]),
            frame.source, frame.status, frame.raw,
        ])
        self._file.flush()
        self.rows += 1


def _s(value) -> str:
    return "" if value is None else str(value)
