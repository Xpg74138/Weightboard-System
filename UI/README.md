# 称重监控工作台

Python / PyQt5 桌面上位机，用于接收称重板经 LoRa 和 USB 串口传来的数据。提供多板监控、四角受力可视化、实时曲线和逐帧 CSV 记录。当前版本 **v1.2.0 / WB 协议 v2**。

重量字段目前是 **HX711 原始计数，尚未标定为克**；`k` 表示千计数。帧定义见 [发送端协议](../Sender/README.md#3-数据协议wb-协议)。

## 安装与运行

下面的命令均在 `UI/` 目录执行。

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -B -m sensor_hub --demo
python -B -m sensor_hub --list-ports
python -B -m sensor_hub --port COM3 --baud 9600
```

`COM3` 是示例，请换成真实串口；Linux 示例为 `/dev/ttyUSB0`。

| 平台 | 启动入口 |
|---|---|
| Windows | `scripts/run_gui.cmd` 或 `scripts/run_gui.cmd --demo` |
| Windows 调试 | `scripts/run_gui_debug.cmd --demo`，日志写入 `artifacts/logs/` |
| Windows 命令行接收 | `scripts/run_receiver.cmd COM3 9600` |
| Linux | `bash scripts/run_gui.sh --demo` 或 `bash scripts/run_gui.sh /dev/ttyUSB0 9600` |

启动器按顺序选择 `SENSOR_HUB_PYTHON`、项目 `.venv`、PATH 中的 Python，无需修改脚本内的个人路径。Windows 启动器会检查并安装缺失依赖。

Ubuntu 如缺少中文字体或串口权限：

```bash
sudo apt install fonts-noto-cjk
sudo usermod -aG dialout "$USER"  # 重新登录后生效
```

## 目录约定

```text
UI/
├── README.md          安装、使用和开发说明
├── requirements.txt   运行依赖
├── sensor_hub/        应用源码和统一主题
├── scripts/           Windows / Linux 启动脚本
├── tools/             串口诊断、E22 配置、预览和打包工具
│   └── legacy/        早期固件补丁，仅供历史参考
├── tests/             协议、串口、存储和界面测试
├── docs/              硬件改造等设计文档
└── artifacts/         本地日志、截图、数据和构建产物（不提交）
```

应用控制位于 `sensor_hub/mainwindow.py`；布局在 `panels.py`，标题栏在 `titlebar.py`，通用卡片在 `widgets.py`，颜色和样式集中在 `theme.py`。帧解析、串口线程和 CSV 分别由 `parser.py`、`reader.py`、`storage.py` 负责。

辅助工具以模块方式运行：`python -m tools.<工具名>`。测试使用 `python -m tests.<测试名>` 或 unittest discovery。新增文件按用途放入对应目录，生成文件使用 `artifacts/`。

## 界面与记录

| 区域 | 内容 |
|---|---|
| 设备连接 | 串口、波特率、组包、接收 / 停止、演示、重连、CSV 与解析设置 |
| 关键指标 | 在线设备、累计帧数、平均帧率、解析异常 |
| 设备明细 | 选中板的四角受力、四路原始读数、通道状态和电池 |
| 板号总览 | 自动换行、滚动、板号搜索、仅在线筛选、鼠标及方向键选择 |
| 实时曲线 | 当前设备最近 600 帧，各路独立缩放；切换板号恢复该板历史 |
| 数据帧记录 | 全部设备最近 500 帧，按 5 Hz 批量刷新，可导出 CSV |
| 运行日志 | 右上角展开；前 20 条全显示，此后每 10 条显示一条并提示省略数量 |
| 菜单 | 导出、采集诊断、清空、关于、退出 |

选择保持：其他板子的数据不会覆盖当前设备。15 秒无更新判为离线；所选设备离线时保留最后读数并提示状态。旧版无板号帧在总览中归为板号 `0`。

表格和待刷新队列最多保留最新 500 帧。CSV 在接收时逐帧写入，不受刷新、表格容量或日志节流影响，包含时间、板号、序号、板子毫秒、通道掩码、四路数据、电池、解析方式、状态和原始数据。

## 测试与预览

```bash
python -B -m unittest discover -s tests -t .
python -B -m tests.test_sensor_hub --with-gui
python -B -m tests.test_end_to_end
python -B -m tools.preview
```

Windows 控制台如不能输出测试中的勾叉符号，可先设置 `$env:PYTHONIOENCODING = "utf-8"`。

共 73 项测试，覆盖 WB 协议、串口组包、存储、选择保持、多板历史隔离、离线筛选、42 板访问、容量限制和演示启停；另有 GUI 演示冒烟和模拟串口端到端检查。已在 Windows 验证，Linux 尚未实机验证。

预览写入 `artifacts/previews/`，包含空态、总览、曲线、表格和小窗口截图。Windows 使用隐藏窗口保证字体渲染；Linux 默认 offscreen。端到端测试使用临时目录，不在源码目录留下抓包文件。

## 辅助工具

```bash
python -m tools.receiver --port COM3 --framing line --show-gap -o artifacts/logs/recv.log
python -m tools.receiver --port COM3 --auto-baud
python -m tools.receiver --port COM3 --reconnect 1
python -m tools.config_e22 --port COM3 --params 10
python -m tools.config_e22 --port COM3 --set rate=62.5k
python -m tools.hardware_probe --port COM3
python -m tools.selfcheck
```

日志目录会自动创建，默认原始抓包写入 `artifacts/captures/`。E22 参数配置需要 **M0=M1=1 配置模式**；正常无线收发需要透传模式。两端信道和空中速率必须一致，WB 文本帧建议使用「按行」组包。

打包需额外安装 PyInstaller；生成图标需 Pillow：

```bash
python -m pip install pyinstaller Pillow
python -m tools.build_exe
```

默认输出 `artifacts/dist/SensorHub/`；`--onefile` 生成单文件版。图标、入口脚本和构建缓存也放在 `artifacts/`。PyInstaller 只为当前平台生成可执行文件。

## 排错与数据边界

| 现象 | 检查 |
|---|---|
| 无数据 | 检查发送端是否工作、两端信道 / 空速以及透传模式；串口打开不代表有数据 |
| 串口拒绝访问 | 检查其他程序占用；USB CDC 异常时拔插接收板，启用自动重连 |
| 曲线幅度相近 | 各路独立缩放，适合观察趋势；绝对值以明细为准 |
| 电池估算不足 | 需要至少 20 个有效采样、观察一分钟且电压下降；外推结果不等同于实际续航 |

硬件标定与低功耗改造需独立完成，见 [硬件改造方案](docs/硬件改造方案.md)。模拟测试不替代真实称重板联调。

## 公开仓库约定

提交源码、测试、文档和启动脚本；不提交 `artifacts/`、虚拟环境、日志、采集数据和本地配置。不要将用户名、个人安装路径或本机代理信息写入示例及脚本；机器差异通过 PATH、项目虚拟环境或环境变量处理。
