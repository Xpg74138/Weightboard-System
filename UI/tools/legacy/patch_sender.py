# -*- coding: utf-8 -*-
"""
patch_sender.py —— 给发送端 Sender/main.c 打补丁

改动内容（全部“写死”，不做运行时配置）：
  1) 新增 BOARD_ID：板号写进帧里，成为字段1（WB,板号,序号,...）
  2) 新增错峰启动：按板号推迟 (BOARD_ID-1)×100ms 开始发送，降低 42 块板子的撞包率
  3) 新增采样间隔随机抖动：用板号做种子的伪随机，避免"周期完全相同→长期持续撞包"

注意：空速（62.5k 等）存在 E22 模组自己的 Flash 里，不在 GD32 固件中，
      所以本脚本不改空速——请用电脑工具在配置模式下写一次即可。
"""

import os
import shutil
import time

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'Sender', 'main.c'))
STAMP = time.strftime('bak_%Y%m%d_%H%M%S')

report = []


def patch(text, old, new, expect=1, label=''):
    n = text.count(old)
    if n != expect:
        report.append('  !! %s 匹配 %d 次（应为 %d），跳过' % (label, n, expect))
        return text
    report.append('  OK %s' % label)
    return text.replace(old, new)


def main():
    text = open(SRC, encoding='utf-8', errors='surrogateescape').read()
    origin = text

    # ---------------- 1) 板号 + 随机数辅助 ----------------
    anchor = '#define USE_HX711_CH_MASK   0x0FU'
    addition = '''#define USE_HX711_CH_MASK   0x0FU

/* ============================================================
   板号配置：每块板子必须改成不同的值（1 ~ 42）
   改完重新编译烧写即可；板号会作为帧的第一个数据字段发出，
   接收端据此区分是哪个板子发来的。
   ============================================================ */
#define BOARD_ID            1U

/* 采样间隔随机抖动幅度（毫秒）：各板周期略有差异，避免长期同步撞包 */
#define SAMPLE_JITTER_MS    6U'''
    if 'BOARD_ID' not in text:
        text = patch(text, anchor, addition, 1, '1) 新增 BOARD_ID / SAMPLE_JITTER_MS')
    else:
        report.append('  -- 已有 BOARD_ID，跳过')

    # ---------------- 2) 采样间隔抖动用的伪随机 ----------------
    anchor2 = '''static volatile uint32_t g_ms = 0;'''
    addition2 = '''static volatile uint32_t g_ms = 0;

/* ============================================================
   极简伪随机数（xorshift32）：给采样间隔加抖动用
   用板号做种子，所以每块板子的抖动序列不同，周期不会完全一致
   ============================================================ */
static uint32_t g_rand_state = 1U;

static void rand_seed(uint32_t seed)
{
    if (seed == 0U) {
        seed = 1U;
    }
    g_rand_state = seed;
}

static uint32_t rand_next(void)
{
    uint32_t x = g_rand_state;

    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    g_rand_state = x;

    return x;
}'''
    if 'rand_seed' not in text:
        text = patch(text, anchor2, addition2, 1, '2) 新增伪随机数助手')
    else:
        report.append('  -- 已有 rand_seed，跳过')

    # ---------------- 3) 帧里加板号 ----------------
    old_pkt = '''    lora_send_string("WB,");
    lora_send_uint32(seq);'''
    new_pkt = '''    lora_send_string("WB,");
    lora_send_uint32(BOARD_ID);      /* 板号：成为字段1 */
    lora_send_char(',');
    lora_send_uint32(seq);'''
    text = patch(text, old_pkt, new_pkt, 1, '3) send_packet 增加板号')

    # ---------------- 4) 错峰启动 ----------------
    old_main = '''    timebase_init();
    lora_uart_init();
    hx711_gpio_init();'''
    new_main = '''    timebase_init();
    lora_uart_init();
    hx711_gpio_init();

    /* ============================================================
       错峰启动：42 块板子各推迟 (板号-1)×100ms 开始发送，
       把发送时刻均匀摊在一个发送周期内，大幅降低空中撞包概率。
       以 42 块为例，最晚的一块推迟 41×100ms = 4.1 秒。
       ============================================================ */
    rand_seed(BOARD_ID * 2654435761U + 12345U);
    delay_ms((uint32_t)(BOARD_ID - 1U) * 100U);'''
    text = patch(text, old_main, new_main, 1, '4) main 增加错峰启动')

    # ---------------- 5) 采样间隔加抖动 ----------------
    old_delay = '''            delay_ms(SAMPLE_INTERVAL_MS);
        }'''
    new_delay = '''            /* 采样间隔加一点随机抖动：各板周期不会完全一致，
               相位缓慢滑动，避免"周期相同→长期持续撞包" */
            delay_ms(SAMPLE_INTERVAL_MS + (rand_next() % SAMPLE_JITTER_MS));
        }'''
    text = patch(text, old_delay, new_delay, 1, '5) 采样间隔增加随机抖动')

    if text == origin:
        print('没有任何改动')
        return 1

    backup = SRC + '.' + STAMP
    try:
        shutil.copy2(SRC, backup)
        with open(SRC, 'w', encoding='utf-8', errors='surrogateescape', newline='') as handle:
            handle.write(text)
        report.append('  已写回，备份 = %s' % os.path.basename(backup))
    except PermissionError as exc:
        report.append('  !! 无写入权限：%s' % exc)
        print('\n'.join(report))
        return 2

    print('\n'.join(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
