#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
applog.py —— 统一日志配置（供 main.py 调用）

为什么单独成模块：
  1. pythonw.exe 下没有控制台，sys.stdout / sys.stderr 都是 None，
     任何 print() 都会抛 AttributeError 直接崩溃，所以可见信息必须落到日志文件；
  2. 日志路径与 config.yaml 一样采用"模块所在目录"的绝对路径，
     保证用快捷方式 / 任意工作目录启动时，日志都写在项目根目录，不会散落；
  3. 集中安装全局异常钩子，让任意线程（keyboard / pystray）的崩溃都能留痕。
"""

import logging
import logging.handlers
import os
import sys
import threading

# 与 config.yaml 相同的处理方式：绝对路径，避免随启动目录漂移
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translator.log")

# 单文件 1MB，保留 3 个备份（translator.log.1 ~ translator.log.3）
_MAX_BYTES = 1024 * 1024
_BACKUP_COUNT = 3

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """配置根 logger。重复调用安全（不会叠加 Handler）。"""
    root = logging.getLogger()
    root.setLevel(level)

    # 幂等：已经装过文件 Handler 就直接返回，避免重复调用时日志写多份
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # 仅在存在真正的 stderr 时才加控制台输出。
    # pythonw.exe 下 sys.stderr 为 None，此时若加 StreamHandler，写日志时同样会报错。
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)


def install_excepthook() -> None:
    """安装全局异常钩子：主线程 + 子线程的未捕获异常都写进日志，便于排查。"""
    logger = logging.getLogger("excepthook")

    def _main_hook(exc_type, exc_value, exc_tb):
        logger.critical("主线程未捕获异常", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _main_hook

    def _thread_hook(args):
        name = args.thread.name if args.thread is not None else "unknown"
        logger.critical(
            "子线程未捕获异常（线程：%s）",
            name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_hook
