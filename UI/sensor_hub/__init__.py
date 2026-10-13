# -*- coding: utf-8 -*-
"""
sensor_hub —— 通用串口/LoRa 传感器数据接收上位机（Windows + Ubuntu 通用）

模块结构：
    sensor_hub/
        __init__.py
        parser.py     —— 数据帧解析（可配置、自动探测）
        reader.py     —— 串口读取线程（组包、断线重连）
        storage.py    —— CSV 记录
        plots.py      —— QPainter 实时曲线
        mainwindow.py —— 采集控制与每板状态
        panels.py     —— 工作台布局
        widgets.py    —— 通用卡片
        titlebar.py   —— 自定义标题栏
        theme.py      —— 设计 token 与样式
        __main__.py   —— 入口：python -m sensor_hub

设计目标：一块板子每次回传一批数据（多个传感器 + 电池），界面要能同时看到
          “当前值”“历史记录”“曲线”，并且换一种板子/格式也能用。
"""

__version__ = "1.2.0"
APP_NAME = "传感器数据接收上位机"

# 协议解析版本：改动 parser.py 里的协议字段映射时请同时递增。
# 窗口标题与“关于”里都会显示，方便确认界面跑的是哪一版代码。
PARSER_VERSION = "WB协议 v2"
