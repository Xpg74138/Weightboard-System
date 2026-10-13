# -*- coding: utf-8 -*-
"""
fix_black_screen.py —— 修复黑屏：把 4KB 环形缓冲缩小，并回退我误改的 I2C BUSY 等待

问题1（主因）：USB_RING_SIZE 4096 让 ZI-data 从 10592 涨到 14760，
              STM32F103C8 只有 20KB RAM，栈被挤爆 -> 跑飞/黑屏。
              改为 512 字节（一帧仅 53 字节，足够吸收 USB 忙闲抖动）。

问题2（次因）：我把 START_TRANSFER 里的 `BUSY==SET` 改成了 `BUSY==RESET`。
              虽然原代码注释写的是等 BUSY 复位，但那一行在本工程里实际起
              “让上一次 STOP 走完”的延时作用；配合 5ms 超时一旦超时就
              `return 1` 跳过整次传输，会导致整屏一个字都刷不出来 -> 黑屏。
              这里回退成原来的写法（纯延时），最稳妥。
"""

import os
import shutil
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'Reciver'))
STAMP = time.strftime('bak_%Y%m%d_%H%M%S')

report = []


def patch(rel, pairs):
    path = os.path.join(ROOT, rel)
    text = open(path, 'r', encoding='gbk', errors='surrogateescape').read()
    origin = text
    for old, new, expected in pairs:
        found = text.count(old)
        if found != expected:
            report.append('  !! %s 匹配 %d 次(应为 %d): %s' % (rel, found, expected, old.strip()[:50]))
            continue
        text = text.replace(old, new)
    if text != origin:
        backup = path + '.' + STAMP
        try:
            shutil.copy2(path, backup)
            with open(path, 'w', encoding='gbk', errors='surrogateescape', newline='') as handle:
                handle.write(text)
            report.append('  OK %-40s 已改  备份=%s' % (rel, os.path.basename(backup)))
        except PermissionError as exc:
            report.append('  !! %s 无写入权限：%s' % (rel, exc))
    else:
        report.append('  -- %-40s 无需改动' % rel)


def main():
    # ---- 1) 把环形缓冲从 4096 缩小到 512 ----
    patch(r'Core\Src\usart.c', [
        ('#define USB_RING_SIZE   4096', '#define USB_RING_SIZE   512', 1),
    ])
    # ---- 2) 回退 START_TRANSFER 里的 BUSY 等待 ----
    patch(r'Core\Src\u8g2_hal.c', [
        ('            if (oled_i2c_wait(I2C_FLAG_BUSY, RESET, 5) == 0) return 1;   /* 等总线空闲 */',
         '            (void)oled_i2c_wait(I2C_FLAG_BUSY, SET, 5);   /* 让上一次 STOP 走完（仅延时，超时不影响传输） */',
         1),
        # 同时把 helper 函数做成“超时只返回、不打断传输”的语义：声明为 void 用法不变
        ('static uint8_t oled_i2c_wait(uint32_t flag, FlagStatus want, uint32_t timeout_ms)',
         'static uint8_t oled_i2c_wait(uint32_t flag, FlagStatus want, uint32_t timeout_ms)',
         1),
    ])
    print('\n'.join(report))


if __name__ == '__main__':
    main()
