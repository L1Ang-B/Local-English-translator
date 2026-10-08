#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
clipboard_util.py —— 剪贴板工具模块
职责（单一）：
  1. 读取 / 写入 / 恢复剪贴板文本；
  2. 用 pyautogui 模拟 Ctrl+C 复制选中内容。
不涉及 tkinter，不涉及 keyboard 快捷键注册。
"""

import time

import pyperclip
import pyautogui

# ------------------------------------------------------------------
# 两个延迟常量，都是"经验值"，解决真实环境下的时序问题：
#
# KEY_RELEASE_WAIT：快捷键触发瞬间，用户的 Ctrl / Shift 很可能还按着没松。
#   如果立刻发 Ctrl+C，物理上会被识别成 Ctrl+Shift+C（是另一个命令），
#   导致复制失败。先等一小会儿，让用户松开修饰键，再发送纯净的 Ctrl+C。
#
# COPY_WAIT：按下 Ctrl+C 后，目标程序需要时间处理并把内容写进剪贴板。
#   如果立刻去读，很可能读到"上一次"的旧内容（脏读），
#   所以发送后要留出一点时间让剪贴板刷新完成。
# ------------------------------------------------------------------
KEY_RELEASE_WAIT = 0.2   # 秒
COPY_WAIT = 0.15         # 秒


def read_text() -> str | None:
    """
    读取剪贴板文本。
    剪贴板为空时 pyperclip 返回 ""；
    若剪贴板里是非文本内容（图片、文件等），部分平台会抛异常，
    此时返回 None 表示"拿不到文本"，由调用方决定怎么处理。
    """
    try:
        return pyperclip.paste()
    except Exception:
        return None


def write_text(text: str) -> bool:
    """把文本写入剪贴板。成功返回 True，失败返回 False（不抛异常）。"""
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def simulate_copy() -> None:
    """
    模拟按下 Ctrl+C，把当前选中内容复制到剪贴板。
    这是本模块唯一使用 pyautogui 的地方（职责隔离）。
    """
    # 先等用户松开快捷键，避免 Ctrl+Shift+C 之类的组合键误触发
    time.sleep(KEY_RELEASE_WAIT)
    pyautogui.hotkey("ctrl", "c")
    # 再等目标程序把内容写进剪贴板，避免读到旧内容
    time.sleep(COPY_WAIT)


def save_clipboard() -> str | None:
    """
    保存当前剪贴板的文本内容（快照），供翻译完成后还原。
    注意：只能保存"文本"。若原剪贴板是图片/文件，这里返回 None，
    后续 restore 会跳过还原——这是 pyperclip 的固有限制，
    也是本工具"尽力不污染剪贴板"的合理边界。
    """
    return read_text()


def restore_clipboard(saved: str | None) -> None:
    """
    还原剪贴板到快照状态。
    saved 为 None 时说明原本就不是文本，无法用 pyperclip 还原，直接跳过。
    """
    if saved is None:
        return
    write_text(saved)


def grab_selected_text() -> str | None:
    """
    组合动作：模拟 Ctrl+C → 读取剪贴板，得到用户选中的文本。
    返回 None 表示没读到文本（没选中内容、或选的是非文本对象）。
    """
    simulate_copy()
    text = read_text()
    if text is None or not text.strip():
        return None
    return text


def _main():
    """
    命令行自测：
      A. 纯读写/恢复测试（不需要选中任何东西）
      B. 说明如何测试"模拟复制"
    """
    print("=" * 50)
    print("测试 A：读取 → 覆盖 → 恢复")
    print("=" * 50)
    print("请先手动复制一段文字（比如选中一行后 Ctrl+C），然后回车继续。")
    input("按回车开始...")

    original = read_text()
    print(f"① 读到当前剪贴板：{original!r}")

    marker = "__clipboard_util_测试覆盖__"
    write_text(marker)
    print(f"② 覆盖后剪贴板  ：{read_text()!r}")

    restore_clipboard(original)
    restored = read_text()
    print(f"③ 恢复后剪贴板  ：{restored!r}")

    if restored == original:
        print("✅ 测试通过：已成功保存并恢复原剪贴板内容。")
    else:
        print("❌ 测试失败：恢复内容与原始内容不一致。")

    print()
    print("=" * 50)
    print("测试 B：模拟 Ctrl+C（需手动制造选中状态）")
    print("=" * 50)
    print("即将在 3 秒后模拟 Ctrl+C。请在此期间：切换到一个有文字的地方，")
    print("用鼠标选中一段文字，并保持窗口在前台。")
    for i in range(3, 0, -1):
        print(f"  {i} ...")
        time.sleep(1)

    grabbed = grab_selected_text()
    print(f"抓取到选中内容：{grabbed!r}")
    if grabbed:
        print("✅ 模拟复制成功。")
    else:
        print("⚠️ 未抓到内容：可能没选中文本，或目标窗口不支持模拟按键。")


if __name__ == "__main__":
    _main()
