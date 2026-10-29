"""PhoneMic 启动器（源码版）

双击桌面快捷方式时由 pythonw.exe 运行本脚本，再启动 PhoneMic。

为什么要这个文件（而不是直接 pythonw -m phonemic.PhoneMic）：
本仓库的 .venv 基于 D:\\Anaconda 的 Python 3.13。Windows 11 上
PySide6 6.11 的 Qt6Core.dll 依赖系统自带的 icuuc.dll（未加版本后缀的
导出符号 UCNV_TO_U_CALLBACK_SUBSTITUTE）。Anaconda 的
D:\\Anaconda\\Library\\bin\\icuuc.dll（ICU 73）只有带 _73 后缀的导出，
一旦被加载器优先绑定，就会弹「无法定位程序输入点 UCNV_TO_U_CALLBACK_SUBSTITUTE」。
这里在导入 Qt 之前先显式加载 System32 的 icuuc.dll，让 Qt 绑定到正确的
系统 ICU，双击启动即可正常工作。
"""

import ctypes
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 持有引用，防止模块被卸载
_system_icu = None


def _pin_system_icu():
    """在导入 PySide6 之前把系统 icuuc.dll 固定下来。"""
    global _system_icu
    if os.name != "nt":
        return
    icu = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "icuuc.dll"
    if not icu.is_file():
        return
    try:
        _system_icu = ctypes.WinDLL(str(icu))
    except OSError:
        _system_icu = None


def _show_error(text):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, "PhoneMic 启动失败", 0x10)
    except Exception:
        pass


def _write_log(text):
    try:
        log_dir = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "PhoneMic"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "launch_error.log", "a", encoding="utf-8") as f:
            f.write(text + "\n")
        return str(log_dir / "launch_error.log")
    except Exception:
        return None


def main():
    _pin_system_icu()
    from phonemic.PhoneMic import main as app_main

    app_main()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        tb = traceback.format_exc()
        log_path = _write_log(tb)
        detail = tb if log_path is None else "%s\n\n详细日志：%s" % (tb, log_path)
        _show_error("PhoneMic 启动失败：\n\n" + detail[-1800:])
        raise
