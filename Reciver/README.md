# Reciver — 接收端固件

**开发板：E22-400TBL-SC**（亿佰特 E22 评估板）
**主控：STM32F103C8T6**（128 KB Flash / 20 KB RAM）

接收 E22-400T22S 无线数据 → 通过 **USB CDC 虚拟串口**转发给电脑上位机；
板上带 SSD1306 OLED 和按键菜单，可脱离电脑独立查看与配置。

> 目录名 `Reciver` 是项目早期沿用的拼写（正确为 Receiver），
> 已被 Keil 工程引用，**未重命名**以免破坏构建。

---

## 1. 硬件

### 主控引脚

| 引脚 | 功能 |
|---|---|
| PA9 / PA10 | **USART1** → E22 模组的 TX / RX |
| PA11 / PA12 | **USB**（CDC 虚拟串口 → 电脑） |
| PB10 / PB11 | **I2C2** → SSD1306 OLED |
| M0 / M1 | E22 工作模式控制（**这块板子上由固件驱动 GPIO**） |
| AUX | E22 忙闲指示（`E22_USE_GPIO_AUX` 当前为 `0`，不使用） |
| RESET | E22 复位 |
| PA13 / PA14 | SWDIO / SWCLK |

### 关键外设配置

| 项 | 配置 |
|---|---|
| 系统时钟 | HSE 8 MHz × PLL9 = **72 MHz**；USB 时钟 = PLL/1.5 = **48 MHz** |
| 串口 | USART1 @ **9600 8N1**（与发送端一致） |
| OLED | SSD1306，I2C2 |
| USB | **VID `0x0483` / PID `0x5740`** → Windows 识别为 `USB 串行设备 (COMx)` |
| USB 产品名 | `STM32 Virtual ComPort` |

### E22 工作模式（`e22_hal.h`）

```c
typedef enum {
    WORK_MODE_TRANSPARENT   = 0x00,   // 透传（收发）M0=0 M1=0
    WORK_MODE_WAKE_ON_RADIO = 0x01,   // 空中唤醒   M0=1 M1=0
    WORK_MODE_CONFIG        = 0x02,   // 配置模式   M0=1 M1=1
    WORK_MODE_SLEEP         = 0x03,   // 深度睡眠
} work_mode_t;
```

> ⚠️ **配置模式下模组既不收也不发**。板子上电流程里多处会切到 `WORK_MODE_CONFIG`
> （`e22_demo.c` 第 233/268/362 行），配置完成后再切回 `WORK_MODE_TRANSPARENT`（第 383 行）。
> 曾经排查「收不到任何数据」时，根因就是板子停在配置模式。

---

## 2. 编译

```
用 Keil MDK 打开  MDK-ARM\project.uvprojx
目标芯片：STM32F103C8
编译器：  ArmClang V6.24（AC6）
```

**编译注意事项**

| 项 | 说明 |
|---|---|
| 编译器 | 必须 AC6。AC5 会报许可证错误 `C9555E` |
| 优化等级 | 用 **-O3**；DEBUG 档（-O0）会超 Flash（`L6407E 0x1620 bytes`） |
| ⚠️ RAM 预算 | 20 KB 很紧。**ZI 不能随意增大** —— 曾把 USB 环形缓冲设成 4 KB，ZI 涨到 14760 导致**栈溢出黑屏**，改回 512 B 才恢复（ZI=11176，用 11.4 KB） |
| 上次构建 | `Code=43096  RO-data=4500  RW-data=504  ZI-data=11176`，**0 Error / 5 Warning** |
| 输出 | `MDK-ARM\project\project.hex` |

命令行构建：

先将 Keil 的 `UV4.exe` 所在目录加入 PATH；以下命令从仓库根目录执行。

```powershell
cd Reciver/MDK-ARM
UV4.exe -b project.uvprojx -j0 -o build.log
# 退出码：0=干净  1=有告警  >=2=有错误
```

---

## 3. 数据转发链路（核心）

```
E22 模组 ──USART1 中断──> usb_ring[512] ──主循环──> CDC_Transmit_FS ──USB──> 电脑
             (逐字节入环形缓冲)   (usb_passthrough_poll 批量取出转发)
```

### 为什么需要环形缓冲（重要补丁）

**原实现把 `CDC_Transmit_FS()` 直接放在 UART 中断里**。发送端持续发送时中断频率约 **960 次/秒**，
USB 发送被拖死，主循环饿死 → **整机卡住**。

修复（`Core\Src\usart.c`）：

```c
#define USB_RING_SIZE   512
static volatile uint8_t  usb_ring[USB_RING_SIZE];
static volatile uint16_t usb_ring_head = 0;   /* 只由 UART 中断修改 */
static volatile uint16_t usb_ring_tail = 0;   /* 只由主循环修改 */
static volatile uint32_t usb_ring_drop = 0;   /* 缓冲满丢弃的字节数 */

static void usb_ring_put(uint8_t byte)
{
    uint16_t next = (uint16_t)((usb_ring_head + 1) % USB_RING_SIZE);
    if (next == usb_ring_tail) { usb_ring_drop++; return; }   /* 满则丢，绝不阻塞 */
    usb_ring[usb_ring_head] = byte;
    usb_ring_head = next;
}
```

主循环（`Core\Src\main.c`）中批量转发：

```c
while (1) {
    Menu_Task();                 /* OLED 菜单响应 */
    usb_receive_to_tx_send();    /* USB 收到的数据 → E22 发出 */
    usb_passthrough_poll();      /* E22 收到的数据 → 批量转发到电脑 */
}
```

> **缓冲大小的权衡**：512 B 是 RAM 与抗突发之间的折中。想调大必须先确认
> ZI 总量 + 栈空间仍在 20 KB 以内。

---

## 4. 目录结构

| 路径 | 说明 |
|---|---|
| `Core\Src\` | 源码：`main.c` / `usart.c`（含环形缓冲补丁）/ `e22_demo.c` / `e22_hal.c` / `u8g2_hal.c` / `key.c` / `i2c.c` / `tim.c` / `gpio.c` / `fifo.c` |
| `Core\Inc\` | 头文件（`e22_hal.h` 里的 `E22_USE_GPIO_AUX` 宏控制 AUX 是否启用） |
| `USB_DEVICE\` | USB CDC 类（`usbd_cdc_if.c` 提供 `CDC_Transmit_FS`） |
| `Middlewares\u8g2Lib\` | OLED 图形库 |
| `Middlewares\MultMenu\` | 菜单框架（`application` / `disp` / `menu`） |
| `Middlewares\ST\` | STM32 USB 设备库 |
| `Drivers\` | STM32 HAL + CMSIS |
| `MDK-ARM\` | Keil 工程与编译输出 |
| `project.ioc` | STM32CubeMX 工程（配置源文件，**不可忽略**） |
| `RTE\` | Keil 器件包释放的文件（**`RTE_Components.h` 等编译必需，已加入版本控制**） |

### 源码文件行数

| 文件 | 行数 | 作用 |
|---|---|---|
| `e22_demo.c` | 363 | E22 演示功能 + 菜单集成（模式切换在这里） |
| `system_stm32f1xx.c` | 367 | 系统时钟（CubeMX 生成） |
| `usart.c` | 284 | **USART1 + USB 环形缓冲补丁** |
| `stm32f1xx_it.c` | 188 | 中断向量（UART 中断在这里） |
| `main.c` | 166 | 主流程 + 时钟配置 |
| `fifo.c` | 152 | 通用 FIFO |
| `tim.c` | 121 | TIM2 |
| `u8g2_hal.c` | 120 | OLED 底层驱动 |
| `e22_hal.c` | 113 | E22 模式/复位/AUX 控制 |
| `key.c` | 109 | 按键 |
| `gpio.c` / `i2c.c` / `systick.c` | 98 / 89 / 20 | GPIO / I2C2 / 时基 |

> 部分固件源码为 GBK 编码，编辑时请保留原编码。接收端工程位于本仓库的 `Reciver/`。

---

## 5. 已修复的问题（含踩坑记录）

| 问题 | 根因 | 修复 |
|---|---|---|
| **接收时整机卡死** | `CDC_Transmit_FS` 在 UART 中断里被调用 ~960 次/秒 | 4 KB 环形缓冲 + 主循环批量转发 |
| **OLED 黑屏** | 上面的缓冲设成 4 KB，ZI 涨到 14760（14.9/20 KB）→ 栈溢出 | 缓冲改 **512 B**（ZI=11176）；还原 I2C BUSY 等待逻辑 |
| **进度条不动** | `DialogScale_AnimationParam_Init()` 漏了 `AnimationParam.Dialog_AllTime = 8;`，回调永不执行；且 `Draw_Scrollbar` 对 double 用了整数 `abs()` 导致宽度溢出 | 补上赋值；改正取值 |
| **`e22_delay_ms` 未声明** | 把 `E22_USE_GPIO_AUX` 设为 `0` 后该函数被条件编译掉 | 改用 `HAL_Delay()` |
| **收不到任何数据** | 板子上电流程停在**配置模式**（模组既不收也不发） | 确认切到透传模式 `WORK_MODE_TRANSPARENT` |
| **重复定义 `oled_i2c_wait`** | 补丁脚本重复插入 | 删除重复，现恰好 7 处（1 定义 + 6 调用） |

---

## 6. 与上位机的关系

站在电脑角度，这块板子就是一个**普通串口**：

| 项 | 值 |
|---|---|
| 设备名 | `USB 串行设备 (COMx)`，VID_0483 / PID_5740 |
| 波特率 | **CDC 忽略波特率**，上位机里填 9600 即可（填别的也能收） |
| 数据 | 原样透传，即发送端发出的一行行 `WB,...\r\n` |

> **重要概念**：上位机里设的波特率只管「电脑 ↔ 这块板子」的 USB 链路，
> **和 LoRa 空中速率毫无关系**。改空速必须用 `UI/tools/config_e22.py` 或板上菜单。

### 连接排查

| 现象 | 处理 |
|---|---|
| 报「设备没有发挥作用」/「拒绝访问」 | 这个 USB-CDC 设备频繁开关串口后会进入坏状态 → **拔插一次板子** |
| 频繁掉线 | 上位机里勾选「自动重连」，或命令行 `--reconnect 1` |
| 完全没数据 | ① 确认模组在**透传模式**；② 两端**信道与空中速率一致** |

---

## 7. 相关文档

- [项目总览](../README.md)
- [发送端固件](../Sender/README.md) — 数据来源与 WB 协议定义
- [上位机说明](../UI/README.md) — 电脑侧如何接收与解析
- [硬件改造方案](../UI/docs/硬件改造方案.md) — 发送端低功耗设计
