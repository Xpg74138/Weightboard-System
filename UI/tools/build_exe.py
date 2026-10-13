# -*- coding: utf-8 -*-
"""
build_exe.py —— 把上位机打包成 Windows exe（PyInstaller）

用法：
    python -m tools.build_exe                     # 文件夹版 artifacts/dist/SensorHub/SensorHub.exe
    python -m tools.build_exe --onefile           # 单文件版 artifacts/dist/SensorHub.exe
    python -m tools.build_exe --console           # 保留控制台窗口（排查启动问题用）
    python -m tools.build_exe --clean             # 先清理 artifacts/ 内的构建目录

打包结果：
    artifacts/dist/SensorHub/SensorHub.exe  双击即可运行（免装 Python）
    整个 SensorHub 文件夹一起拷给别人即可

为什么默认做成“文件夹版”：
    · 启动快（单文件版每次都要解压到临时目录，第一次可能等 5~10 秒）；
    · 不容易被杀毒软件误报；
    · 出错时能看到具体缺哪个 dll。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_NAME = "SensorHub"
ENTRY_SCRIPT = os.path.join(HERE, "artifacts", "build", "build_entry.py")
ICON = os.path.join(HERE, "artifacts", "app.ico")
BUILD_DIR = os.path.join(HERE, "artifacts", "build")
DIST_DIR = os.path.join(HERE, "artifacts", "dist")

# 明确收集这些包，避免 PyInstaller 漏掉 Qt 插件/串口后端
HIDDEN_IMPORTS = [
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
    "serial.serialwin32",
    "sensor_hub",
    "sensor_hub.parser",
    "sensor_hub.reader",
    "sensor_hub.storage",
    "sensor_hub.plots",
    "sensor_hub.mainwindow",
]
COLLECT_ALL = ["PyQt5", "serial"]


def build_entry_script() -> None:
    """生成打包入口脚本（等价于 python -m sensor_hub）。"""
    content = '''# -*- coding: utf-8 -*-
"""PyInstaller 打包入口：等价于 `python -m sensor_hub`。此文件由 build_exe.py 生成。"""
import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()          # 冻结后使用多进程时的必要调用
    # 源码入口位于 artifacts/build，应用包位于 UI 根目录。
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    from sensor_hub.__main__ import main
    sys.exit(main())
'''
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(ENTRY_SCRIPT, "w", encoding="utf-8") as handle:
        handle.write(content)
    print("[1/4] 已生成入口脚本：%s" % os.path.basename(ENTRY_SCRIPT))


def ensure_icon() -> None:
    if os.path.exists(ICON):
        print("[2/4] 已存在图标：%s" % os.path.basename(ICON))
        return
    print("[2/4] 生成图标 ...")
    code = subprocess.call([sys.executable, os.path.join(HERE, "tools", "make_icon.py")])
    if code != 0 or not os.path.exists(ICON):
        print("      图标生成失败，将不使用图标继续打包。", file=sys.stderr)


def run_pyinstaller(onefile: bool, console: bool) -> int:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--paths", HERE,
        "--name", APP_NAME,
        "--onefile" if onefile else "--onedir",
        "--console" if console else "--windowed",
        "--distpath", DIST_DIR,
        "--workpath", os.path.join(BUILD_DIR, "work"),
        "--specpath", BUILD_DIR,
    ]
    if os.path.exists(ICON):
        command += ["--icon", ICON]
    for name in HIDDEN_IMPORTS:
        command += ["--hidden-import", name]
    for name in COLLECT_ALL:
        command += ["--collect-all", name]
    command.append(ENTRY_SCRIPT)

    print("[3/4] 开始打包（第一次会比较慢，PyQt5 体积大）...")
    print("      " + " ".join(command[:8]) + " ...")
    sys.stdout.flush()
    return subprocess.call(command)


def report(onefile: bool) -> None:
    target = (os.path.join(DIST_DIR, APP_NAME + ".exe") if onefile
              else os.path.join(DIST_DIR, APP_NAME, APP_NAME + ".exe"))
    print("[4/4] 打包完成")
    if os.path.exists(target):
        size = os.path.getsize(target) / 1024.0 / 1024.0
        print("      可执行文件：%s（%.1f MB）" % (target, size))
        if not onefile:
            folder = os.path.dirname(target)
            total = sum(os.path.getsize(os.path.join(root, name))
                        for root, _, names in os.walk(folder) for name in names)
            print("      整个文件夹：%.1f MB（分发时请整个文件夹一起拷贝）" % (total / 1024.0 / 1024.0))
        print("      自检命令：\"%s\" --version" % target)
    else:
        print("      ✗ 没有找到产物，请检查上面的 PyInstaller 输出。", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(prog="build_exe.py")
    parser.add_argument("--onefile", action="store_true", help="打包成单个 exe")
    parser.add_argument("--console", action="store_true", help="保留控制台窗口")
    parser.add_argument("--clean", action="store_true", help="先清理 artifacts/build 与 artifacts/dist")
    args = parser.parse_args()

    if os.name != "nt":
        print("注意：当前不是 Windows，PyInstaller 只能为本平台打包。", file=sys.stderr)

    if args.clean:
        for path in (BUILD_DIR, DIST_DIR):
            if os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)
                print("已清理 %s" % path)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller。安装：%s -m pip install pyinstaller" % sys.executable,
              file=sys.stderr)
        return 2

    build_entry_script()
    ensure_icon()
    code = run_pyinstaller(args.onefile, args.console)
    if code != 0:
        print("PyInstaller 退出码 %d，打包失败。" % code, file=sys.stderr)
        return code
    report(args.onefile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
