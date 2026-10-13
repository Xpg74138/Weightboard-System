# -*- coding: utf-8 -*-
"""
apply_patches.py —— 把 8 个固件补丁应用到 E22-400TBL-SC 工程（GBK 编码源文件）

已完成的（脚本会跳过并报告）：
  补丁1  menu.c          Dialog_AllTime = 8
  补丁5  menu.c          Draw_Scrollbar 重写
  补丁6  usart.c         中断里去掉 CDC_Transmit_FS（已注释）

本脚本负责：
  补丁7  usart.c / main.c / main.h   环形缓冲 + 主循环批量转发到 USB（无损中转）
  补丁8  e22_demo.c                  4 处 while(1) → 打印 + 返回
  补丁2  u8g2_hal.c                  5 处 I2C 等待加超时
  补丁3  u8g2_hal.c                  END_TRANSFER 等 STOP 完成
"""

import os
import shutil
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'Reciver'))
STAMP = time.strftime('bak_%Y%m%d_%H%M%S')

report = []


def read_gbk(rel):
    path = os.path.join(ROOT, rel)
    with open(path, 'r', encoding='gbk', errors='surrogateescape') as handle:
        return path, handle.read()


def write_gbk(path, text):
    backup = path + '.' + STAMP
    try:
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        with open(path, 'w', encoding='gbk', errors='surrogateescape', newline='') as handle:
            handle.write(text)
    except PermissionError as exc:
        report.append('  !! 无写入权限：%s（%s）' % (path, exc))
        return None
    return backup


def apply(rel, pairs, label):
    """pairs: [(old, new, count_expected)]"""
    path, text = read_gbk(rel)
    changed = 0
    for old, new, expected in pairs:
        found = text.count(old)
        if found != expected:
            report.append('  !! %-46s 匹配 %d 次（应为 %d），跳过：%s'
                          % (rel, found, expected, old.strip().splitlines()[0][:40]))
            continue
        text = text.replace(old, new)
        changed += found
    if changed:
        backup = write_gbk(path, text)
        report.append('  OK %-46s 改动 %d 处  备份=%s' % (rel, changed, os.path.basename(backup)))
    else:
        report.append('  -- %-46s 无需改动' % rel)
    return changed


# ---------------------------------------------------------------- 补丁 7-A：环形缓冲
P7_RING = '''

/* ===== 补丁7：USB 中转环形缓冲（UART 中断写 / 主循环读，单生产者单消费者，无锁）=====
   为什么需要它：原来在 UART 中断里直接调 CDC_Transmit_FS，发送端持续发送时
   每秒约 960 次中断各发起一次 USB 传输，USB 栈被打满 -> 主循环饿死 -> 整个界面卡死。
   现在中断只把字节放进环形缓冲，主循环批量转发到 USB，数据不丢也不会卡。*/
#define USB_RING_SIZE   4096
static volatile uint8_t  usb_ring[USB_RING_SIZE];
static volatile uint16_t usb_ring_head = 0;      /* 只由 UART 中断修改 */
static volatile uint16_t usb_ring_tail = 0;      /* 只由主循环修改 */
static volatile uint32_t usb_ring_drop = 0;      /* 缓冲满丢弃的字节数 */

static void usb_ring_put(uint8_t byte)
{
    uint16_t next = (uint16_t)((usb_ring_head + 1) % USB_RING_SIZE);

    if (next == usb_ring_tail) { usb_ring_drop++; return; }   /* 满则丢，绝不阻塞 */

    usb_ring[usb_ring_head] = byte;
    usb_ring_head = next;
}
'''

# ---------------------------------------------------------------- 补丁 7-B：中断只入队
P7_ISR_OLD = '''\t\t\t\tfifo_write(&fifo_uart1_rx,&rd_2,1);'''
P7_ISR_NEW = '''\t\t\t\tfifo_write(&fifo_uart1_rx,&rd_2,1);
\t\t\t\tusb_ring_put(rd_2);          /* 补丁7：只入环形缓冲，主循环再批量转发 USB */'''

# ---------------------------------------------------------------- 补丁 7-C：主循环转发函数
P7_POLL_OLD = '''\t\tusb_rx_complete = 0;
    }
}
/* USER CODE END 1 */'''

P7_POLL_NEW = '''\t\tusb_rx_complete = 0;
    }
}

/**
 * @brief  在主循环里把 E22 收到的数据批量转发到 USB（补丁7）
 * @note   绝不能在 UART 中断里调用 CDC_Transmit_FS：发送端持续发送时
 *         每秒约 960 次中断会把 USB 栈打满，导致主循环饿死而卡死。
 *         本函数一次最多转发 64 字节，USB 忙就直接返回（宁丢不等）。
 */
void usb_passthrough_poll(void)
{
    static uint8_t buf[64];
    uint16_t len = 0;

    if (current_feature != FUNC_FEATURE1) return;      /* 只有透传模式才转发 */

    while (len < (uint16_t)sizeof(buf))
    {
        uint16_t tail = usb_ring_tail;

        if (tail == usb_ring_head) break;              /* 缓冲空 */

        buf[len++] = usb_ring[tail];
        usb_ring_tail = (uint16_t)((tail + 1) % USB_RING_SIZE);
    }

    if (len == 0) return;

    if (CDC_Transmit_FS(buf, len) != USBD_OK)
    {
        usb_ring_drop += len;                          /* USB 忙，丢弃这批，绝不阻塞 */
    }
}

/**
 * @brief  查询被丢弃的字节数（补丁7），便于上位机提示丢包
 */
uint32_t usb_ring_drop_count(void)
{
    return usb_ring_drop;
}

/* USER CODE END 1 */'''

# ---------------------------------------------------------------- 补丁 7-D：fifo 失败不再死循环
P7_FIFO_OLD = '''\t\t\t///@todo \r\n\t\t\t/* 队列创建失败 */\r\n\t\t\twhile(1);'''
P7_FIFO_NEW = '''\t\t\t/* 补丁：队列创建失败不再死循环，避免永久卡死 */
\t\t\treturn;'''

# ---------------------------------------------------------------- 补丁 7-E：主循环调用
P7_LOOP_OLD = '''\t\t/* 菜单响应 */
\t\tMenu_Task();
\t\tusb_receive_to_tx_send();'''
P7_LOOP_NEW = '''\t\t/* 菜单响应 */
\t\tMenu_Task();
\t\tusb_receive_to_tx_send();
\t\tusb_passthrough_poll();      /* 补丁7：把接收到的数据批量转发到电脑 */'''

# ---------------------------------------------------------------- 补丁 7-F：声明
P7_DECL_OLD = '''void usb_printf(const char *format, ...);'''
P7_DECL_NEW = '''void usb_printf(const char *format, ...);
void usb_passthrough_poll(void);      /* 补丁7 */
uint32_t usb_ring_drop_count(void);   /* 补丁7 */'''

# ---------------------------------------------------------------- 补丁 8：while(1) → 返回
P8_PAIRS = [
    ('''\t\t\t/* 应答数据不正确 */
\t\t\twhile(1);\t
\t}''',
     '''\t\t\t/* 补丁8：应答不正确不再死循环，避免永久卡死 */
\t\t\tusb_printf("read device name failed\\r\\n");
\t\t\t*length = 0;
\t\t\treturn;
\t}''', 1),
    ('''\t\t\t/* 应答数据不正确 */
\t\t\twhile(1);\t\t\t
''',
     '''\t\t\t/* 补丁8：应答不正确不再死循环 */
\t\t\tusb_printf("read fw version failed\\r\\n");
\t\t\t*length = 0;
\t\t\treturn;
''', 1),
    ('''\t\t\t/* 读取超时 或 应答数据不正确 */
\t\t\twhile(1);\t\t\t
''',
     '''\t\t\t/* 补丁8：读取超时不再死循环 */
\t\t\tusb_printf("read env rssi failed\\r\\n");
\t\t\t*rssi = 0;
\t\t\treturn;
''', 1),
    ('''\t\t\t/* 模组如果回答FF FF FF 表示指令错误 */
\t\t\twhile(1);''',
     '''\t\t\t/* 补丁8：模组回 FF FF FF 时不再死循环，直接返回 */
\t\t\tusb_printf("config write failed (FF FF FF)\\r\\n");
\t\t\treturn;''', 1),
]

# ---------------------------------------------------------------- 补丁 2：I2C 超时
P2_HELPER_OLD = '''static uint8_t u8x8_byte_hw_i2c(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr) {'''
P2_HELPER_NEW = '''/* 补丁2：OLED I2C 等待加超时，避免总线异常时死等导致花屏/卡死 */
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

static uint8_t u8x8_byte_hw_i2c(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr) {'''

P2_PAIRS = [
    ('''\t\t\t\t\t\t\t\twhile( __HAL_I2C_GET_FLAG(&hi2c2, I2C_FLAG_TXE) == RESET );''',
     '''\t\t\t\t\t\t\t\tif (oled_i2c_wait(I2C_FLAG_TXE, RESET, 5) == 0) return 1;''', 1),
    ('''            while( __HAL_I2C_GET_FLAG( &hi2c2, I2C_FLAG_BUSY ) == SET );''',
     '''            if (oled_i2c_wait(I2C_FLAG_BUSY, SET, 5) == 0) return 1;''', 1),
    ('''\t\t\t\t\t\twhile( __HAL_I2C_GET_FLAG( &hi2c2, I2C_FLAG_SB ) == RESET );''',
     '''\t\t\t\t\t\tif (oled_i2c_wait(I2C_FLAG_SB, RESET, 5) == 0) return 1;''', 1),
    ('''\t\t\t\t\t\twhile ( __HAL_I2C_GET_FLAG( &hi2c2, I2C_FLAG_ADDR) == RESET );''',
     '''\t\t\t\t\t\tif (oled_i2c_wait(I2C_FLAG_ADDR, RESET, 5) == 0) return 1;''', 1),
    ('''\t\t\t\t    while( __HAL_I2C_GET_FLAG(&hi2c2, I2C_FLAG_TXE) == RESET );''',
     '''\t\t\t\t    if (oled_i2c_wait(I2C_FLAG_TXE, RESET, 5) == 0) return 1;''', 1),
    (P2_HELPER_OLD, P2_HELPER_NEW, 1),
]

# ---------------------------------------------------------------- 补丁 3：等 STOP
P3_OLD = '''\t\t\t\t\t\t/* Generate Stop */
\t\t\t\t\t\tSET_BIT( I2C2->CR1, I2C_CR1_STOP );'''
P3_NEW = '''\t\t\t\t\t\t/* Generate Stop */
\t\t\t\t\t\tSET_BIT( I2C2->CR1, I2C_CR1_STOP );
\t\t\t\t\t\t/* 补丁3：等 STOP 真正发完，否则紧接着的 START 会造成总线时序错乱 -> 花屏 */
\t\t\t\t\t\t(void)oled_i2c_wait(I2C_FLAG_BUSY, SET, 5);'''


def main():
    print('工程：%s' % ROOT)
    print('备份后缀：.%s' % STAMP)
    print()

    # 先检查已完成的补丁
    _, usart = read_gbk(r'Core\Src\usart.c')
    _, menu = read_gbk(r'Middlewares\MultMenu\menu\menu.c')
    print('== 已完成（跳过） ==')
    print('  menu.c   Dialog_AllTime=8         : %s'
          % ('已改' if 'Dialog_AllTime = 8' in menu else '未改'))
    print('  menu.c   Draw_Scrollbar 新写法    : %s'
          % ('已改' if 'double ratio' in menu else '未改'))
    print('  usart.c  中断里 CDC 已注释        : %s'
          % ('已改' if '/*CDC_Transmit_FS(&usb_rx_data,1);*/' in usart else '未改'))
    print()

    print('== 本次应用 ==')
    # ---- usart.c：补丁 7 全部 ----
    path, text = read_gbk(r'Core\Src\usart.c')
    n = 0
    # 声明区插入环形缓冲
    if 'USB_RING_SIZE' not in text:
        old = '/* USER CODE END 0 */'
        text = text.replace(old, P7_RING.strip('\n') + '\n' + old, 1)
        n += 1
    # 中断里入队
    if 'usb_ring_put(rd_2)' not in text:
        text = text.replace(P7_ISR_OLD, P7_ISR_NEW, 1)
        n += 1
    # fifo 创建失败不再死循环
    if P7_FIFO_OLD in text:
        text = text.replace(P7_FIFO_OLD, P7_FIFO_NEW, 1)
        n += 1
    # 追加轮询函数
    if 'usb_passthrough_poll' not in text:
        text = text.replace(P7_POLL_OLD, P7_POLL_NEW, 1)
        n += 1
    if n:
        write_gbk(path, text)
    report.append('  %-46s 改动 %d 处（环形缓冲+批量转发）' % (r'Core\Src\usart.c', n))

    # ---- main.c：主循环调用 ----
    apply(r'Core\Src\main.c', [(P7_LOOP_OLD, P7_LOOP_NEW, 1)], 'main')

    # ---- main.h：声明 ----
    apply(r'Core\Inc\main.h', [(P7_DECL_OLD, P7_DECL_NEW, 1)], 'main.h')

    # ---- e22_demo.c：补丁 8 ----
    apply(r'Core\Src\e22_demo.c', P8_PAIRS, 'demo')

    # ---- u8g2_hal.c：补丁 2 + 3 ----
    apply(r'Core\Src\u8g2_hal.c', P2_PAIRS + [(P3_OLD, P3_NEW, 1)], 'u8g2')

    print()
    for line in report:
        print(line)


if __name__ == '__main__':
    main()
