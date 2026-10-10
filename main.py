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
  - pystray 托盘图标由 run_detached() 跑在独立线程，它的菜单回调同样
    只往队列投递消息，真正的 UI 与退出清理由主线程完成；
  - 这样彻底避免跨线程操作 tkinter 导致的崩溃/卡死。

后台常驻特性：
  - 托盘图标常驻右下角，右键可"显示状态 / 退出"；
  - 无控制台（pythonw）运行时，所有信息写入 translator.log（见 applog.py）。
"""

import logging
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

import keyboard

import applog
import tray
from clipboard_util import grab_selected_text, restore_clipboard, save_clipboard
from popup import TranslationPopup
from translator import TranslationError, Translator, load_config

_logger = logging.getLogger(__name__)

# 主线程与后台线程（keyboard / pystray）之间的任务队列。
# 用 queue 而不是共享变量：它是官方推荐的跨线程通信方式，天然线程安全。
# 约定消息格式：
#   ("show", 文本)   请求弹窗
#   ("close", None)  请求关闭弹窗
#   ("status", None) 请求显示状态信息框（托盘菜单触发）
#   ("quit", None)   请求退出程序（托盘菜单触发）
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

# 托盘图标对象（pystray.Icon），在 main 里创建
_icon = None

# 当前生效的热键字符串，供"显示状态"信息框展示
_hotkey = ""

# 退出防重入标志：托盘的"退出"、Ctrl+C、异常兜底都会走 _shutdown()，
# 用标志保证清理逻辑只执行一次。
_shutting_down = False

# 轮询定时器的 id，退出时需要 after_cancel 取消，避免回调对着已销毁的窗口再跑
_poll_after_id: "str | None" = None

# 统计信息，供"显示状态"信息框展示（只在持有处理锁时修改，无需额外加锁）
_ok_count = 0
_fail_count = 0
_last_result = "尚无记录"


# ----------------------------------------------------------------------
# 以下函数运行在【keyboard 回调线程】，禁止操作 tkinter，只能跑后台逻辑 + 投递队列
# ----------------------------------------------------------------------
def _on_hotkey() -> None:
    """全局热键回调：取词 → 翻译 → 投递结果。全程不碰 UI。"""
    global _ok_count, _fail_count, _last_result

    # 1) 原子地尝试占用"处理权"；占用失败说明上一次还没处理完，忽略本次按键。
    if not _processing_lock.acquire(blocking=False):
        _logger.info("正在处理上一次翻译，已忽略本次按键。")
        return

    try:
        # 2) 备份当前剪贴板，稍后用于还原（避免污染用户剪贴板）
        original = save_clipboard()
        try:
            # 3) 模拟 Ctrl+C 并读取选中文本
            text = grab_selected_text()
            if not text:
                _logger.warning("未读取到选中的文本（可能没有选中内容）。")
                return

            # 4) 调用智谱 API 翻译；网络/超时等错误会抛 TranslationError
            _logger.info("开始翻译（原文 %d 字符）。", len(text))
            translated = _translator.translate(text)
            _ok_count += 1
            _last_result = f"成功（{time.strftime('%H:%M:%S')}）"
            _logger.info("翻译成功（译文 %d 字符）。", len(translated))
            _task_queue.put(("show", translated))
        except TranslationError as e:
            # 翻译失败不静默：既写日志，也投递给主线程弹窗告知用户
            _fail_count += 1
            _last_result = f"失败（{time.strftime('%H:%M:%S')}）：{e}"
            _logger.error("翻译失败：%s", e)
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


# ----------------------------------------------------------------------
# 托盘菜单回调：运行在【pystray 线程】，同样只投递队列消息，不碰 tkinter
# ----------------------------------------------------------------------
def _on_tray_status() -> None:
    """托盘"显示状态"：请求主线程弹信息框。"""
    _task_queue.put(("status", None))


def _on_tray_quit() -> None:
    """托盘"退出"：请求主线程统一退出。"""
    _task_queue.put(("quit", None))


# ----------------------------------------------------------------------
# 以下为主线程内的收尾动作
# ----------------------------------------------------------------------
def _show_status_box(root: tk.Tk) -> None:
    """显示状态信息框（主线程执行）。用户主动点菜单触发，短暂置顶聚焦是合理的。"""
    lines = [
        "程序状态：正在运行",
        f"翻译热键：{_hotkey}",
        f"翻译成功：{_ok_count} 次",
        f"翻译失败：{_fail_count} 次",
        f"最近一次：{_last_result}",
        "",
        f"日志文件：{applog.LOG_PATH}",
    ]
    messagebox.showinfo("划词翻译器 - 状态", "\n".join(lines), parent=root)


def _shutdown(root: tk.Tk, popup: TranslationPopup) -> None:
    """
    统一退出清理（必须在主线程执行）。
    托盘的"退出"与 Ctrl+C 都走这里，保证清理逻辑只有一份。
    用 _shutting_down 防重入：重复调用会直接返回。
    """
    global _shutting_down, _poll_after_id
    if _shutting_down:
        return
    _shutting_down = True
    _logger.info("开始退出清理……")

    # 1) 取消 Tk 的轮询定时器，避免它对着即将销毁的窗口继续回调
    if _poll_after_id is not None:
        try:
            root.after_cancel(_poll_after_id)
        except Exception:
            pass
        _poll_after_id = None

    # 2) 关闭当前弹窗（其 on_close 会顺带移除 ESC 钩子）
    try:
        popup.close()
    except Exception:
        _logger.exception("关闭弹窗时出错")

    # 3) 移除临时 ESC 钩子（幂等，兜底再调一次）
    _remove_esc_hook()

    # 4) 清掉所有 keyboard 热键
    try:
        keyboard.unhook_all()
    except Exception:
        _logger.exception("unhook_all 出错")

    # 5) 停止 pystray 事件循环（stop() 线程安全，由 pystray 自己收尾）
    if _icon is not None:
        try:
            _icon.stop()
        except Exception:
            _logger.exception("停止托盘时出错")

    _logger.info("清理完成，退出主循环。")

    # 6) 让 mainloop() 返回
    try:
        root.quit()
    except Exception:
        pass


def _poll_queue(root: tk.Tk, popup: TranslationPopup) -> None:
    """
    主线程轮询队列，把后台线程投递的任务转成 UI 动作。
    keyboard / pystray 线程不能碰 tkinter，所以用"轮询 + 队列"的方式交接，
    这是 tkinter 跨线程编程最稳妥的写法。
    """
    global _poll_after_id
    try:
        while True:
            kind, payload = _task_queue.get_nowait()
            if kind == "show":
                _show_popup(popup, str(payload))
            elif kind == "close":
                popup.close()
            elif kind == "status":
                _show_status_box(root)
            elif kind == "quit":
                _shutdown(root, popup)
                return  # 定时器已在 _shutdown 内取消，这里直接结束，不再续期
    except queue.Empty:
        pass

    # 已在退出流程中就不要再续期
    if _shutting_down:
        return
    # 继续下一次轮询。50ms 对肉眼无感，又能及时取到结果；
    # 同时这个周期性回调让主线程频繁回到 Python 层，Ctrl+C 也能被及时响应。
    _poll_after_id = root.after(50, lambda: _poll_queue(root, popup))


# ----------------------------------------------------------------------
def main() -> None:
    global _translator, _icon, _hotkey, _poll_after_id

    # ---- 0. 初始化日志与全局异常钩子（放最前，保证后续任何日志/异常都能落盘）----
    applog.setup_logging()
    applog.install_excepthook()
    _logger.info("程序启动。日志文件：%s", applog.LOG_PATH)

    # ---- 1. 读取配置（translator.load_config 已负责 api_key 必填校验）----
    try:
        config = load_config()
    except TranslationError as e:
        _logger.error("配置错误：%s", e)
        sys.exit(1)

    # ---- 2. 校验热键格式 ----
    # 先 parse_hotkey 单独校验再注册：把"格式写错"和"注册失败（被占用/无权限）"
    # 两类问题区分开，能给出更准确的提示。用 Exception 兜底，兼容不同版本抛出的异常类型。
    hotkey = str(config.get("hotkey", "ctrl+shift+t")).strip()
    try:
        keyboard.parse_hotkey(hotkey)
    except Exception:
        _logger.error("热键格式无效，请检查 config.yaml")
        sys.exit(1)
    _hotkey = hotkey

    # ---- 3. 创建翻译器 ----
    try:
        _translator = Translator(config)
    except TranslationError as e:
        _logger.error("初始化失败：%s", e)
        sys.exit(1)

    # ---- 4. 主线程创建 Tk 根窗口与弹窗 ----
    root = tk.Tk()
    root.withdraw()  # 隐藏根窗口，界面上只出现弹窗与托盘
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
        _logger.error("热键注册失败：%s", e)
        _remove_esc_hook()
        root.destroy()
        sys.exit(1)
    _logger.info("已注册全局热键：%s", hotkey)

    # ---- 6. 启动系统托盘（run_detached 在独立线程跑事件循环，不阻塞主线程）----
    _icon = tray.build_tray(on_status=_on_tray_status, on_quit=_on_tray_quit)
    _icon.run_detached()
    _logger.info("托盘图标已启动。")

    _logger.info("快速翻译器已就绪：选中英文按 %s 翻译；托盘右键可“显示状态 / 退出”。", hotkey)

    # ---- 7. 启动轮询并进入主循环 ----
    _poll_after_id = root.after(50, lambda: _poll_queue(root, popup))
    try:
        root.mainloop()
    finally:
        # 程序退出的兜底清理：确保不残留任何键盘钩子与托盘图标
        _logger.info("主循环已退出，执行兜底清理。")
        _remove_esc_hook()
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        if _icon is not None:
            try:
                _icon.stop()
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
        _logger.info("收到 Ctrl+C，程序退出。")
