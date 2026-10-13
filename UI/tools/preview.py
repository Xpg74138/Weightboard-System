"""Render representative desktop states without a serial device.

Run from UI: python -B -m tools.preview
"""
import argparse
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from sensor_hub import theme
from sensor_hub.mainwindow import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/previews")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    theme.configure_application(app)
    window = MainWindow()
    window.resize(1440, 980)
    window._save_config = lambda config: None
    window.setAttribute(Qt.WA_DontShowOnScreen)
    window.show()
    app.processEvents()
    window.grab().save(str(output / "empty.png"))
    for seq in range(1, 61):
        for board in range(1, 43):
            window.on_line("WB,%d,%d,%d,0F,%d,%d,%d,%d,3870,63" % (
                board, seq, seq * 2000, 12500 + board * 40 + int(250 * math.sin(seq / 8)),
                8300 + int(180 * math.sin(seq / 7 + 0.8)),
                4200 + board * 12 + int(140 * math.sin(seq / 6 + 1.8)),
                19800 + int(350 * math.sin(seq / 8 + 2.4))))
    window.started_at = time.time() - 120
    window._set_connection_state("模拟数据", "demo")
    # Include offline boards as well as live ones.
    for board in (8, 17, 29):
        window.board_grid._boards[board]["ts"] = time.time() - 20
    window._refresh_ui()
    window._on_board_clicked(12)
    app.processEvents()
    for index, name in enumerate(("overview", "trends", "frames")):
        window.tabs.setCurrentIndex(index)
        app.processEvents()
        window.grab().save(str(output / (name + ".png")))
    window.tabs.setCurrentIndex(0)
    window.resize(1100, 760)
    app.processEvents()
    window.grab().save(str(output / "compact.png"))
    window.close()
    print("Previews saved to", output.resolve())


if __name__ == "__main__":
    main()
