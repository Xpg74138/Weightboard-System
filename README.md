# Weightboard System

LoRa 无线称重采集系统，由称重板、接收端和桌面上位机组成。每块称重板采集四路 HX711 数据和电池状态，经 E22 模组传到接收端，再通过 USB 虚拟串口交给上位机进行监控和记录。

```text
42 块称重板 → E22 LoRa → 接收端 → USB CDC → 桌面上位机
GD32E230F6             STM32F103C8          Python / PyQt5
```

## 功能

- 多设备总览，支持板号搜索、在线筛选和持续查看所选设备。
- 四角受力可视化、四路读数、通道状态及电池状态。
- 每块板子独立的实时曲线和历史记录。
- 逐帧 CSV 记录、原始数据日志、串口断线重连。
- 无硬件演示模式，可模拟 42 块称重板。
- 自动识别新版带板号和旧版无板号 WB 帧。

> 当前重量字段是 **HX711 原始计数，尚未标定为克**。界面中的 `k` 表示千计数。

## 项目结构

| 目录 | 内容 | 说明 |
|---|---|---|
| `Sender/` | GD32E230F6 发送端固件、Keil 工程 | [发送端文档](Sender/README.md) |
| `Reciver/` | STM32F103C8 接收端固件、USB CDC 和 OLED | [接收端文档](Reciver/README.md) |
| `UI/` | PyQt5 桌面上位机、辅助工具和测试 | [上位机文档](UI/README.md) |

`Reciver` 是沿用的历史目录名；为保持工程引用兼容，暂不重命名。

## 快速开始

以下命令从仓库根目录执行。需要 Python 3.8 或更高版本。

```powershell
cd UI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -B -m sensor_hub --demo
```

Windows 也可双击 `UI/scripts/run_gui.cmd`。启动器优先使用 `SENSOR_HUB_PYTHON` 指定的解释器，其次使用 `UI/.venv`，最后使用 PATH 中的 Python。

Linux：

```bash
cd UI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -B -m sensor_hub --demo
```

连接真实设备时，将示例 `COM3` 或 `/dev/ttyUSB0` 替换为实际串口：

```bash
python -B -m sensor_hub --list-ports
python -B -m sensor_hub --port COM3 --baud 9600
```

当前上位机版本为 **v1.2.0 / WB 协议 v2**。Linux 的字体和串口权限设置见 [UI 文档](UI/README.md)。

## 固件与数据协议

用 Keil MDK 打开 `Sender/weight.uvprojx` 或 `Reciver/MDK-ARM/project.uvprojx`，安装对应器件包后编译、烧写。

| 模块 | 主要依赖 |
|---|---|
| 发送端 | GD32E230F6、四路 HX711、E22-400T22S、GD32E23x 器件包 |
| 接收端 | STM32F103C8、E22-400TBL-SC、SSD1306 OLED、STM32F1xx 器件包 |
| 上位机 | Python 3.8+、PyQt5、pyserial |

WB 帧为一行 ASCII 文本，以 `\r\n` 结尾：

```text
WB,板号,序号,板子毫秒,OK掩码,重量0,重量1,重量2,重量3,电池mV,电量%
WB,序号,板子毫秒,OK掩码,重量0,重量1,重量2,重量3,电池mV,电量%
```

新版有 11 个字段，旧版有 10 个字段。详细定义见 [WB 数据协议](Sender/README.md#3-数据协议wb-协议)。板号通过发送端 `BOARD_ID` 配置，使用范围为 1–42。

收发两端 E22 模组的信道和空中速率必须一致。参数保存在模组中，可使用 `UI/tools/config_e22.py` 配置；配置模式与正常透传模式的区别见上位机文档。

## 测试

在 `UI/` 目录执行：

```bash
python -B -m unittest discover -s tests -t .
python -B -m tests.test_sensor_hub --with-gui
python -B -m tests.test_end_to_end
```

目前包含 73 项单元及界面回归测试，另有 GUI 演示冒烟和模拟串口端到端检查。已在 Windows 验证；这些检查不替代真实硬件联调。

## 后续工作

- 四路称重传感器的零点与比例标定。
- 发送端低功耗改造和续航测量，见 [硬件改造方案](UI/docs/硬件改造方案.md)。
- ADC 校准和 42 块板子的无线参数统一。

## 提交文件

仓库保留源码、工程配置、测试和文档。运行日志、采集数据、界面截图、虚拟环境及构建产物由 [`.gitignore`](.gitignore) 排除。上位机生成文件统一存放在 `UI/artifacts/`。

固件 `RTE/` 下的库源码和 `RTE_Components.h` 是构建依赖，应保留；本地调试布局和编译输出不提交。文档及启动脚本使用相对路径或环境变量，不依赖某台机器的用户名和安装位置。
