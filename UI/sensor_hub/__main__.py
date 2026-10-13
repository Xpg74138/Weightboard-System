# -*- coding: utf-8 -*-
"""
__main__.py —— 程序入口

启动方式：
    python -m sensor_hub                       # 图形界面
    python -m sensor_hub --port COM4 --baud 9600
    python -m sensor_hub --demo                # 演示模式（没硬件也能看效果）
    python -m sensor_hub --list-ports          # 只列出串口

Ubuntu 上如果提示找不到 Qt 平台插件，先装：
    sudo apt install python3-pyqt5
"""

from __future__ import annotations

import argparse
import sys


def _force_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="sensor_hub",
        description="通用串口/LoRa 传感器数据接收上位机（Windows + Ubuntu）")
    parser.add_argument("-p", "--port", help="串口名，如 COM4 或 /dev/ttyUSB0")
    parser.add_argument("-b", "--baud", type=int, default=9600, help="波特率，默认 9600")
    parser.add_argument("--demo", action="store_true", help="演示模式：用内置模拟数据")
    parser.add_argument("--parse-log", metavar="FILE",
                        help="把每一帧的解析结果写入文件（每行：原文 -> 解析值），用于排查显示问题")
    parser.add_argument("--list-ports", action="store_true", help="列出串口后退出")
    parser.add_argument("--version", action="store_true", help="显示版本后退出")
    return parser.parse_args(argv)


def _ensure_font(app) -> None:
    """
    字体兜底：某些环境（精简 Linux、conda 自带的 Qt）找不到任何字体，
    界面会变成“只有控件、没有文字”。这里检测一下并给出提示/换字体。
    """
    from PyQt5.QtGui import QFont, QFontDatabase

    if QFontDatabase().families():
        return
    print("[警告] 系统里似乎没有可用字体，界面文字可能显示不出来。", file=sys.stderr)
    for name in ("Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei",
                 "DejaVu Sans", "Arial"):
        font = QFont(name)
        if font.exactMatch():
            app.setFont(font)
            print("[提示] 已切换字体：%s" % name, file=sys.stderr)
            return
    print("       Ubuntu 可装：sudo apt install fonts-noto-cjk fonts-dejavu-core",
          file=sys.stderr)


def main(argv=None) -> int:
    _force_utf8_stdout()
    args = parse_args(argv)

    from . import APP_NAME, __version__

    if args.version:
        print("%s v%s" % (APP_NAME, __version__))
        return 0

    # 串口列表不需要图形界面
    if args.list_ports:
        from .reader import port_details
        details = port_details()
        if not details:
            print("没有发现串口。（Windows 看设备管理器；Ubuntu 看 /dev/ttyUSB* /dev/ttyACM*）")
            return 1
        for text in details:
            print("  " + text)
        return 0

    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        print("缺少 PyQt5。安装方法：", file=sys.stderr)
        print("  Windows: pip install PyQt5", file=sys.stderr)
        print("  Ubuntu : sudo apt install python3-pyqt5   （或 pip install PyQt5）", file=sys.stderr)
        return 2

    from PyQt5.QtCore import Qt
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    _ensure_font(app)

    from . import theme
    theme.configure_application(app)

    from .mainwindow import MainWindow
    window = MainWindow()
    if args.parse_log:
        window.enable_parse_log(args.parse_log)
    if args.port:
        window.port_combo.setCurrentText(args.port)
    window.baud_combo.setCurrentText(str(args.baud))
    window.show()
    if args.demo:
        window.start_receive(demo=True)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
