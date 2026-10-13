# -*- coding: utf-8 -*-
"""
fix_dup.py —— 修掉 u8g2_hal.c 里重复定义的 oled_i2c_wait（由 apply_patches.py 重复插入造成）

处理内容：
  1) 删除重复插入的那一份 oled_i2c_wait（保留你 16:05 已打好的那份，带单行 return 的那个）
  2) 顺手修正 START_TRANSFER 里 BUSY 等待的标志方向：
     注释写的是 “Wait until BUSY flag is reset”，但原代码等的是 BUSY==SET。
     在 stop 未发出的异常状态下会白等 5ms，正确写法是等 BUSY==RESET。
"""

import os
import shutil
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'Reciver'))
STAMP = time.strftime('bak_%Y%m%d_%H%M%S')
REL = r'Core\Src\u8g2_hal.c'

# 重复块：我插入的那一份（注释在下、函数体带换行 return）
DUP = '''/* 补丁2：OLED I2C 等待加超时，避免总线异常时死等导致花屏/卡死 */
static uint8_t oled_i2c_wait(uint32_t flag, FlagStatus want, uint32_t timeout_ms)
{
    uint32_t start = HAL_GetTick();

    while (__HAL_I2C_GET_FLAG(&hi2c2, flag) == want)
    {
        if ((HAL_GetTick() - start) > timeout_ms)
        {
            return 0;      /* 超时，放弃本次等待 */
        }
    }
    return 1;
}

'''

BUSY_OLD = '''            if (oled_i2c_wait(I2C_FLAG_BUSY, SET, 5) == 0) return 1;'''
BUSY_NEW = '''            if (oled_i2c_wait(I2C_FLAG_BUSY, RESET, 5) == 0) return 1;   /* 等总线空闲 */'''


def main():
    path = os.path.join(ROOT, REL)
    text = open(path, 'r', encoding='gbk', errors='surrogateescape').read()
    origin = text

    dup_count = text.count(DUP)
    print('找到重复块 %d 处' % dup_count)
    if dup_count == 1:
        text = text.replace(DUP, '', 1)
        print('  已删除重复定义')
    elif dup_count == 0:
        print('  没有找到重复块（可能已处理过）')

    busy_count = text.count(BUSY_OLD)
    print('BUSY 方向问题 %d 处' % busy_count)
    if busy_count == 1:
        text = text.replace(BUSY_OLD, BUSY_NEW, 1)
        print('  已修正为等 BUSY==RESET')

    print('oled_i2c_wait 定义/调用总数：%d（应为 1 个定义 + 6 处调用 = 7）'
          % text.count('oled_i2c_wait'))

    if text != origin:
        backup = path + '.' + STAMP
        try:
            shutil.copy2(path, backup)
            open(path, 'w', encoding='gbk', errors='surrogateescape', newline='').write(text)
            print('已写回，备份：%s' % os.path.basename(backup))
        except PermissionError as exc:
            print('!! 无写入权限：%s' % exc)
    else:
        print('无需改动')


if __name__ == '__main__':
    main()
