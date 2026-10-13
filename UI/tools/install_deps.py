# -*- coding: utf-8 -*-
"""
install_deps.py —— 在国内网络/代理异常时，绕过系统代理用清华源安装依赖

适用于系统代理配置导致 pip 安装失败的情况。仅在当前进程中关闭代理探测，
使用镜像源，不修改系统设置。

用法：
    python -m tools.install_deps pyinstaller            # 安装 pyinstaller
    python -m tools.install_deps pyinstaller -U         # 升级安装
    python -m tools.install_deps --download pyinstaller -d .\\wheels   # 只下载不安装
"""

from __future__ import annotations

import os
import sys

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
TRUSTED = "pypi.tuna.tsinghua.edu.cn"


def _patch_urllib_proxies() -> None:
    """让 stdlib 的代理探测返回空 —— 只影响本进程。"""
    import urllib.request

    urllib.request.getproxies = lambda: {}
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    # 有些库会直接读这两个变量，显式清空
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                 "ALL_PROXY", "all_proxy"):
        os.environ.pop(name, None)


def _patch_pip_proxies() -> None:
    """
    pip 内部用 requests，会通过 Session.merge_environment_settings ->
    urllib.request.getproxies() 拿系统代理（这才是 Windows 上真正的来源）。
    这里把它包装一层，强制返回空代理。

    兼容不同 pip 版本：老版本叫 Session，新版本（>=23）叫 PipSession。
    """
    try:
        import pip._internal.network.session as session
    except Exception as exc:                     # pragma: no cover
        print("[提示] 无法加载 pip 网络模块，跳过 patch：%s" % exc, file=sys.stderr)
        return

    session_class = None
    for name in ("PipSession", "Session"):
        session_class = getattr(session, name, None)
        if session_class is not None:
            break
    if session_class is None:
        print("[提示] 找不到 pip 的 session 类，跳过 patch（代理可能仍生效）", file=sys.stderr)
        return

    original = session_class.merge_environment_settings

    def merge(self, url, proxies, stream, verify, cert):
        result = original(self, url, proxies, stream, verify, cert)
        # requests 的返回顺序：(proxies, stream, verify, cert, ...)
        if isinstance(result, tuple) and len(result) >= 2:
            for index, item in enumerate(result):
                if isinstance(item, dict) and item and all(
                        str(v).startswith(("http", "socks")) for v in item.values()):
                    result = result[:index] + ({},) + result[index + 1:]
                    break
        return result

    session_class.merge_environment_settings = merge
    print("[绕过系统代理] 已 patch pip 的 %s.merge_environment_settings" % session_class.__name__)


def main(argv) -> int:
    _patch_urllib_proxies()
    _patch_pip_proxies()

    download_dir = None
    args = list(argv)
    if args and args[0] == "--download":
        args.pop(0)
        download_dir = "wheels"
        if args and args[0] in ("-d", "--dest"):
            args.pop(0)
            download_dir = args.pop(0)

    if not args:
        args = ["pyinstaller"]

    from pip._internal.cli.main import main as pip_main

    command = ["download" if download_dir else "install", *args]
    command += ["-i", MIRROR, "--trusted-host", TRUSTED, "--timeout", "30"]
    if download_dir:
        command += ["-d", download_dir]
    print("[绕过系统代理] 执行：pip " + " ".join(command))
    sys.stdout.flush()
    return pip_main(command)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
