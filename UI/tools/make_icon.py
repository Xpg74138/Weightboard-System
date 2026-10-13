# -*- coding: utf-8 -*-
"""
make_icon.py —— 生成打包图标 artifacts/app.ico（多尺寸）

用 Pillow 现画一个“称重传感器 + 无线”的图标，避免依赖外部素材。
生成 16/24/32/48/64/128/256 多种尺寸，Windows 会按需取用。

用法：
    python -m tools.make_icon
"""

from __future__ import annotations

import os
import sys

SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "artifacts", "app.ico")

BG = (8, 127, 140)          # 与桌面主题保持一致
FG = (255, 255, 255)        # 白色图形
ACCENT = (255, 176, 32)     # 橙色点缀


def draw(size: int):
    from PIL import Image, ImageDraw

    scale = size / 256.0
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_ctx = ImageDraw.Draw(image)

    def rounded(coords, radius, fill):
        # Keep a few pixels between opposite arcs; older Pillow versions reject
        # zero-height inner rectangles when a radius reaches half the height.
        coords = [round(value) for value in coords]
        short_side = min(coords[2] - coords[0], coords[3] - coords[1])
        radius = min(radius, max(0, (short_side - 3) // 2))
        if radius < 1:
            draw_ctx.rectangle(coords, fill=fill)
        else:
            draw_ctx.rounded_rectangle(coords, radius=radius, fill=fill)

    # 圆角底
    radius = int(48 * scale)
    rounded([0, 0, size - 1, size - 1], radius=radius, fill=BG)

    def box(x0, y0, x1, y1):
        return [x0 * scale, y0 * scale, x1 * scale, y1 * scale]

    # 托盘（秤盘）
    rounded(box(48, 150, 208, 172), radius=int(10 * scale), fill=FG)
    # 秤体
    rounded(box(78, 172, 178, 224), radius=int(12 * scale), fill=FG)
    # 显示屏（深色）
    rounded(box(100, 184, 156, 208), radius=int(6 * scale), fill=BG)

    # 秤盘上的重物
    rounded(box(96, 108, 160, 150), radius=int(8 * scale), fill=ACCENT)

    # 无线信号（右上角三段弧）
    center = (196 * scale, 44 * scale)
    for index, r in enumerate((26, 44, 62)):
        r = r * scale
        width = max(1, int((9 - index * 2) * scale))
        draw_ctx.arc([center[0] - r, center[1] - r, center[0] + r, center[1] + r],
                     start=205, end=335, fill=FG, width=width)
    dot = 7 * scale
    draw_ctx.ellipse([center[0] - dot, center[1] - dot, center[0] + dot, center[1] + dot],
                     fill=FG)
    return image


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow：pip install Pillow", file=sys.stderr)
        return 2

    images = [draw(size) for size, _ in SIZES]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    images[0].save(OUT, format="ICO", sizes=SIZES)
    print("已生成图标：%s" % OUT)
    print("包含尺寸：%s" % ", ".join("%dx%d" % s for s in SIZES))
    print("文件大小：%d 字节" % os.path.getsize(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
