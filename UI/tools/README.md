# 辅助与开发工具

从 `UI/` 目录使用 `python -m tools.<工具名>` 运行。

| 工具 | 用途 |
|---|---|
| `receiver` | 命令行接收、自动波特率、重连与抓包 |
| `sender` | 配对调试发送端 |
| `config_e22` | E22 参数读写 |
| `hardware_probe` | 串口及硬件链路诊断 |
| `selfcheck` | 应用版本及帧解析自检 |
| `preview` | 无硬件界面截图，默认写入 `artifacts/previews/` |
| `build_exe` | PyInstaller 打包，写入 `artifacts/build/` 和 `artifacts/dist/` |
| `make_icon` | Pillow 图标生成器，写入 `artifacts/app.ico` |
| `install_deps` | 代理异常时的依赖安装辅助工具 |

`legacy/` 保留早期固件补丁脚本，目标路径相对于仓库解析，不参与启动、测试或打包。它们仅供历史参考，运行会修改固件；日常开发直接维护固件源码。
