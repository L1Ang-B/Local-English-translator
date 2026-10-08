#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
main.py —— 主程序入口
整体流程（一次完整交互）：
  1. 启动时读配置 → 校验热键 → 创建翻译器、Tk、弹窗 → 注册全局热键；
  2. 【keyboard 线程】按下热键 → 占用处理锁 → 备份剪贴板 → 模拟 Ctrl+C
     → 读取选中文本 → 调 API 翻译 → 还原剪贴板 → 释放处理锁；
  3. 翻译结果被投递到线程安全队列；
  4. 【主线程】轮询队列 → 显示弹窗 → 注册临时 ESC 钩子；
  5. 弹窗自动关闭 / 按 ESC 关闭 → 移除 ESC 钩子。

线程模型（关键）：
  - tkinter 只能在主线程操作，所以主线程负责 mainloop + 所有 UI 动作；
  - keyboard 的回调运行在它自己的线程里，回调中【绝不】触碰 tkinter，
    只做"后台工作"并通过 queue 把结果交给主线程；
  - 这样彻底避免跨线程操作 tkinter 导致的崩溃/卡死。
"""

import queue
import sys
import threading
import tkinter as tk

import keyboard

from clipboard_util import grab_selected_text, restore_clipboard, save_clipboard
from popup import TranslationPopup
from translator import TranslationError, Translator, load_config

# 主线程与 keyboard 回调线程之间的任务队列。
# 用 queue 而不是共享变量：它是官方推荐的跨线程通信方式，天然线程安全。
# 约定消息格式：("show", 文本) 请求弹窗；("close", None) 请求关闭弹窗。
_task_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()

# 防止重复处理的锁。
# 为什么用 Lock 而不是普通布尔标志？
#   热键回调在独立线程触发，两次极快的连按可能"同时"读到标志为 False，
#   于是两次处理并发执行 —— 会导致剪贴板备份/还原互相覆盖、弹窗叠加。
#   Lock.acquire(blocking=False) 是原子的"测试并占用"，可彻底杜绝该竞态。
_processing_lock = threading.Lock()

# 翻译器实例（在 main 里初始化，供热键回调使用）
_translator: Translator | None = None

# 临时 ESC 钩子的句柄；None 表示当前未注册
_esc_handler = None


# ----------------------------------------------------------------------
# 以下函数运行在【keyboard 回调线程】，禁止操作 tkinter，只能跑后台逻辑 + 投递队列
# ----------------------------------------------------------------------
def _on_hotkey() -> None:
    """全局热键回调：取词 → 翻译 → 投递结果。全程不碰 UI。"""
    # 1) 原子地尝试占用"处理权"；占用失败说明上一次还没处理完，忽略本次按键。
    if not _processing_lock.acquire(blocking=False):
        print("[提示] 正在处理上一次翻译，已忽略本次按键。")
        return

    try:
        # 2) 备份当前剪贴板，稍后用于还原（避免污染用户剪贴板）
        original = save_clipboard()
        try:
            # 3) 模拟 Ctrl+C 并读取选中文本
            text = grab_selected_text()
            if not text:
                print("[提示] 未读取到选中的文本（可能没有选中内容）。")
                return

            # 4) 调用智谱 API 翻译；网络/超时等错误会抛 TranslationError
            translated = _translator.translate(text)
            _task_queue.put(("show", translated))
        except TranslationError as e:
            # 翻译失败不静默：把错误信息也投递给主线程弹出来告知用户
            _task_queue.put(("show", f"[翻译失败]\n{e}"))
        finally:
            # 5) 无论成功、失败还是提前 return，都还原剪贴板
            restore_clipboard(original)
    finally:
        # 6) 释放处理权，允许下一次按键
        _processing_lock.release()


def _on_esc_key() -> None:
    """临时 ESC 钩子回调：同样在 keyboard 线程，只投递"关闭"请求。"""
    _task_queue.put(("close", None))


# ----------------------------------------------------------------------
# 以下函数运行在【主线程】：注册/移除钩子、操作弹窗
# ----------------------------------------------------------------------
def _register_esc_hook() -> None:
    """注册临时全局 ESC 钩子（弹窗出现时调用）。"""
    global _esc_handler
    # 去重：若已存在钩子先移除。因为快速连续翻译时，新弹窗会直接替换旧弹窗
    # （popup.show 内部销毁旧窗口但不会触发 on_close），若不先清理就会重复注册。
    _remove_esc_hook()
    # suppress=False：不吞掉 ESC 事件，避免影响其他软件对 ESC 的使用。
    # 代价是 ESC 也会传到前台软件，但对普通文本编辑影响可忽略。
    _esc_handler = keyboard.add_hotkey("esc", _on_esc_key, suppress=False)


def _remove_esc_hook() -> None:
    """移除临时 ESC 钩子（弹窗关闭时 / 程序退出时调用）。可安全重复调用。"""
    global _esc_handler
    if _esc_handler is not None:
        try:
            keyboard.remove_hotkey(_esc_handler)
        except Exception:
            pass  # 钩子可能已被库内部清理，忽略即可
        _esc_handler = None


def _on_popup_closed() -> None:
    """
    弹窗关闭回调（主线程执行）。
    自动关闭、ESC 关闭都会走到这里，统一在这里移除 ESC 钩子，
    保证"钩子只在弹窗存活期间存在"。
    """
    _remove_esc_hook()


def _show_popup(popup: TranslationPopup, text: str) -> None:
    """显示弹窗，并（重新）注册临时 ESC 钩子。"""
    _register_esc_hook()
    popup.show(text)


def _poll_queue(root: tk.Tk, popup: TranslationPopup) -> None:
    """
    主线程轮询队列，把后台线程投递的任务转成 UI 动作。
    keyboard 线程不能碰 tkinter，所以用"轮询 + 队列"的方式交接，
    这是 tkinter 跨线程编程最稳妥的写法。
    """
    try:
        while True:
            kind, payload = _task_queue.get_nowait()
            if kind == "show":
                _show_popup(popup, str(payload))
            elif kind == "close":
                popup.close()
    except queue.Empty:
        pass
    # 继续下一次轮询。50ms 对肉眼无感，又能及时取到结果；
    # 同时这个周期性回调让主线程频繁回到 Python 层，Ctrl+C 也能被及时响应。
    root.after(50, lambda: _poll_queue(root, popup))


# ----------------------------------------------------------------------
def main() -> None:
    global _translator

    # ---- 1. 读取配置（translator.load_config 已负责 api_key 必填校验）----
    try:
        config = load_config()
    except TranslationError as e:
        print(f"[配置错误] {e}")
        sys.exit(1)

    # ---- 2. 校验热键格式 ----
    # 先 parse_hotkey 单独校验再注册：把"格式写错"和"注册失败（被占用/无权限）"
    # 两类问题区分开，能给出更准确的提示。用 Exception 兜底，兼容不同版本抛出的异常类型。
    hotkey = str(config.get("hotkey", "ctrl+shift+t")).strip()
    try:
        keyboard.parse_hotkey(hotkey)
    except Exception:
        print("热键格式无效，请检查 config.yaml")
        sys.exit(1)

    # ---- 3. 创建翻译器 ----
    try:
        _translator = Translator(config)
    except TranslationError as e:
        print(f"[初始化失败] {e}")
        sys.exit(1)

    # ---- 4. 主线程创建 Tk 根窗口与弹窗 ----
    root = tk.Tk()
    root.withdraw()  # 隐藏根窗口，界面上只出现弹窗
    popup = TranslationPopup(
        master=root,
        auto_close_ms=config.get("popup_duration_ms", 6000),
    )
    # 弹窗关闭时统一移除 ESC 钩子（覆盖自动关闭 / ESC 关闭两条路径）
    popup.on_close = _on_popup_closed

    # ---- 5. 注册全局热键 ----
    try:
        keyboard.add_hotkey(hotkey, _on_hotkey)
    except Exception as e:
        # 注册失败（例如被其他程序独占）时给出提示并清理
        print(f"热键注册失败：{e}")
        _remove_esc_hook()
        root.destroy()
        sys.exit(1)

    print(f"快速翻译器已启动。热键：{hotkey}")
    print("在任意软件中选中英文，按下热键即可翻译。")
    print("按 Ctrl+C 退出程序。")

    # ---- 6. 启动轮询并进入主循环 ----
    root.after(50, lambda: _poll_queue(root, popup))
    try:
        root.mainloop()
    finally:
        # 程序退出的兜底清理：确保不残留任何键盘钩子
        _remove_esc_hook()
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n程序已退出。")
