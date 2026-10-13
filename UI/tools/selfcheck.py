# -*- coding: utf-8 -*-
"""
selfcheck.py —— 上位机自检：确认真实运行的代码版本，并打印每帧每个字段的取值

用法（在 UI 目录下）：
    python -m tools.selfcheck
    python -m tools.selfcheck "WB,2375,2574362,0F,-11063,-8748,-3085,-13788,3818,57"

输出内容：
    1) python 路径、sensor_hub 加载路径、版本号
    2) parser.py 的 md5（和别人的对比即可确认是不是同一份代码）
    3) 逐个字段的下标 -> 值，以及解析器把它们分别放进了哪个槽位
    4) 界面卡片实际会显示什么
"""

import hashlib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# 用固定示例帧验证旧版协议
DEFAULT_FRAME = "WB,2375,2574362,0F,-11063,-8748,-3085,-13788,3818,57"

SEP = "-" * 78


def main():
    frame_text = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FRAME

    print(SEP)
    print("1) 运行环境")
    print("   python      :", sys.executable)
    print("   python 版本 :", sys.version.split()[0])
    print("   sys.path[0] :", HERE)

    print(SEP)
    print("2) 加载的 sensor_hub 代码")
    try:
        from sensor_hub import __version__, PARSER_VERSION
        import sensor_hub.parser as P
        print("   sensor_hub 包 :", os.path.dirname(P.__file__))
        print("   版本号        :", __version__, " PARSER_VERSION:", PARSER_VERSION)
        src = open(P.__file__, "rb").read()
        print("   parser.py md5 :", hashlib.md5(src).hexdigest())
        print("   parser.py 大小:", len(src), "字节")
        print("   _parse_wb 存在:", "是" if hasattr(P.FrameParser, "_parse_wb") else "否  <<< 这是旧代码！")
    except Exception as exc:
        print("   !! 导入失败：", exc)
        return 1

    print(SEP)
    print("3) 逐字段解析")
    print("   输入帧 :", frame_text)
    parts = [p.strip() for p in frame_text.split(",")]
    print("   分隔后共 %d 个字段：" % len(parts))
    for i, p in enumerate(parts):
        print("      字段[%2d] = %-12s" % (i, p))

    parser = P.FrameParser(P.ParseConfig())
    frame = parser.parse(frame_text, ts=time.time())
    print()
    print("   解析方式 :", frame.source, " 状态:", frame.status)
    print("   seq      :", frame.seq, " (应=字段1)")
    print("   ms       :", frame.ms, " (应=字段2)")
    print("   ok_mask  :", frame.flag, " (应=字段3)")
    print("   4 路重量 :", frame.weight_g, " (应=字段4~7)")
    print("   电池 mV  :", frame.battery_mv, " (应=字段8)")
    print("   电量 %   :", frame.get("batt_pct"), " (应=字段9)")

    print(SEP)
    print("4) 界面卡片实际会显示")
    print("   重量1~4  :", [frame.get(k) for k in ("s1", "s2", "s3", "s4")])
    mv = frame.battery_mv
    print("   电池电压 :", "%.0f mV" % mv if mv is not None else "--")
    print("   电池电量 :", frame.get("batt_pct"))

    print(SEP)
    ok = (frame.get("batt_pct") is not None
          and frame.battery_mv is not None
          and abs(frame.battery_mv - float(parts[8])) < 1.0)
    if ok:
        print("结论：解析正确。电池电压 =", frame.battery_mv, "mV")
    else:
        print("结论：解析不正确！请把以上完整输出发给开发者。")
    print(SEP)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
