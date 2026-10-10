#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tray.py —— 系统托盘图标（pystray）

职责边界：只负责"创建 / 启动 / 停止托盘图标 + 菜单项"，不碰 tkinter、不碰快捷键。
菜单回调运行在 pystray 自己的线程里，因此回调内只做"往队列投递消息"这类轻量动作，
真正的 UI（信息框）和退出清理由 main.py 在主线程完成。
"""

import logging
import os
from typing import Callable

import pystray
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

# 与 config.yaml / 日志同样的"绝对路径"策略：无论从哪启动都能找到 icon.png
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")

TOOLTIP = "划词翻译器 - 按 Ctrl+Shift+T 翻译"

# 兜底图标参数
_FALLBACK_SIZE = 64
_FALLBACK_COLOR = (40, 120, 220, 255)  # 蓝色圆点


def _generate_fallback_image(size: int = _FALLBACK_SIZE) -> Image.Image:
    """用 Pillow 现场画一个纯色圆点，作为 icon.png 缺失时的兜底。"""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 8
    draw.ellipse([margin, margin, size - margin, size - margin], fill=_FALLBACK_COLOR)
    return image


def load_icon_image() -> Image.Image:
    """加载 icon.png；失败则返回兜底图标。绝不抛异常，避免因图标问题崩溃。"""
    try:
        image = Image.open(ICON_PATH)
        image.load()  # 强制解码：文件损坏会在此抛异常，被下面捕获
        logger.info("已加载托盘图标：%s", ICON_PATH)
        return image
    except Exception as e:
        logger.warning("加载 icon.png 失败（%s），改用程序化生成的兜底图标。", e)
        return _generate_fallback_image()


def build_tray(on_status: Callable[[], None], on_quit: Callable[[], None]) -> pystray.Icon:
    """
    构建托盘图标。

    on_status / on_quit 由 main.py 注入，它们只应做"往队列投递消息"的轻量动作，
    因为这两个回调运行在 pystray 线程中，不能直接操作 tkinter。
    """
    menu = pystray.Menu(
        pystray.MenuItem("显示状态", lambda icon, item: on_status(), default=True),
        pystray.MenuItem("退出", lambda icon, item: on_quit()),
    )
    return pystray.Icon("quick-translator", load_icon_image(), TOOLTIP, menu)


if __name__ == "__main__":
    # 独立测试：只验证托盘图标本身，不涉及主程序。
    # 用 python.exe 运行（有控制台可看输出）。
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    def _on_status() -> None:
        logger.info("（测试）菜单：显示状态 被点击")

    def _on_quit() -> None:
        logger.info("（测试）菜单：退出 被点击，准备停止托盘")
        icon.stop()  # 结束下面的 icon.run()

    icon = build_tray(on_status=_on_status, on_quit=_on_quit)
    logger.info("托盘已启动：悬停看 tooltip，右键试菜单，点“退出”结束测试。")
    icon.run()  # 阻塞，直到 _on_quit 里调用 icon.stop()
    logger.info("托盘已停止，测试结束。")
