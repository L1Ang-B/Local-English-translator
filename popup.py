#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
popup.py —— 弹窗模块
职责（单一）：显示一个无边框、置顶、位于屏幕右上角的翻译结果弹窗。
不涉及快捷键注册，不涉及剪贴板。
"""

import logging
import sys
import tkinter as tk
from typing import Callable

logger = logging.getLogger(__name__)

# 弹窗外观参数（集中放这里，方便统一调整）
MARGIN = 20          # 弹窗距离屏幕边缘的间距（像素）
MAX_TEXT_WIDTH = 360 # 文本换行宽度，防止长句撑爆屏幕
BG_COLOR = "#2b2b2b"
FG_COLOR = "#f5f5f5"
FONT = ("Microsoft YaHei", 11)


class TranslationPopup:
    """
    翻译弹窗。

    设计要点：
      - 复用外部传入的 Tk（master）时，不自己开事件循环，方便集成进 main.py；
      - master 为 None 时自建 Tk 并跑 mainloop，便于单独测试。
    """

    def __init__(
        self,
        master: tk.Misc | None = None,
        auto_close_ms: int = 6000,
        on_close: Callable[[], None] | None = None,
    ):
        # 是否由本类"拥有"根窗口：拥有才负责 mainloop 和 destroy
        self._owns_root = master is None
        self.root = master if master is not None else tk.Tk()
        if self._owns_root:
            # 隐藏根窗口，只显示下面的 Toplevel 弹窗
            self.root.withdraw()

        self.auto_close_ms = auto_close_ms
        # 关闭弹窗后的回调。默认 None：
        #   - 正式路径（main.py 传 master）不传回调，弹窗关闭后主循环继续常驻；
        #   - 测试分支（自建 Tk）传入 root.quit，让 mainloop 能退出、程序正常结束。
        self.on_close = on_close

        self._top: tk.Toplevel | None = None
        self._after_id: str | None = None

    # ------------------------------------------------------------------
    def show(self, text: str, auto_close_ms: int | None = None) -> None:
        """显示（或刷新）弹窗内容。重复调用会先销毁旧窗口，避免多层叠加。"""
        self._destroy_current()

        top = tk.Toplevel(self.root)

        # overrideredirect(True)：让窗口不受窗口管理器管辖，
        # 从而去掉标题栏和边框，得到一个"干净"的悬浮卡片。
        # 代价是它也不再带系统提供的关闭按钮，所以关闭逻辑要我们自己实现。
        top.overrideredirect(True)

        # -topmost：始终置顶。作用是即使目标软件（浏览器/Word）在全屏，
        # 弹窗也浮在最上层不被遮挡——这正是"即时查看翻译"的关键。
        top.attributes("-topmost", True)

        # 注意：这里刻意【不】调用 grab_set() / focus_force()。
        # grab_set 会让窗口变成"模态"，把所有鼠标键盘事件都抢过来，
        # 用户就无法继续操作原来的软件了；focus_force 会把输入焦点抢走，
        # 用户正在打的字会跑到弹窗上。两者都会打断用户，所以都不做。
        top.configure(bg=BG_COLOR)

        # 一个小色条，作为视觉左边界，让卡片有点层次（纯装饰）
        accent = tk.Frame(top, bg="#4a9eff", width=4)
        accent.pack(side="left", fill="y")

        label = tk.Label(
            top,
            text=text,
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT,
            justify="left",
            anchor="w",
            wraplength=MAX_TEXT_WIDTH,  # 超过宽度自动换行
            padx=14,
            pady=12,
        )
        label.pack(side="left", fill="both", expand=True)

        # 绑定 ESC：仅在弹窗自身获得焦点时生效（因为我们不抢焦点）。
        # 想先聚焦再按 ESC，可以点一下弹窗，或直接等它自动关闭。
        top.bind("<Escape>", lambda _e: self._close())

        self._top = top
        self._place_top_right(top)

        # 自动关闭定时器。存下 after 的 id，便于提前关闭时取消，防止误触发。
        duration = auto_close_ms if auto_close_ms is not None else self.auto_close_ms
        self._after_id = self.root.after(duration, self._close)

    # ------------------------------------------------------------------
    def _place_top_right(self, top: tk.Toplevel) -> None:
        """把窗口放到屏幕右上角。"""
        # update_idletasks：先让 tkinter 完成布局计算，
        # 这样 winfo_width/height 才能拿到"包好文字后"的真实尺寸。
        top.update_idletasks()
        w = top.winfo_width()
        h = top.winfo_height()
        screen_w = top.winfo_screenwidth()

        x = screen_w - w - MARGIN  # 右对齐：屏幕宽 - 窗口宽 - 边距
        y = MARGIN                 # 贴顶，留一点点边距
        top.geometry(f"{w}x{h}+{x}+{y}")

    def _destroy_current(self) -> None:
        """销毁当前弹窗（若有）。"""
        if self._top is not None:
            self._top.destroy()
            self._top = None

    def _close(self) -> None:
        """关闭弹窗：先取消定时器，再销毁窗口。可安全重复调用。"""
        # 防重入：弹窗已销毁且没有待执行的定时器时直接返回，
        # 避免 ESC 与自动关闭"双触发"导致 on_close 被执行两次。
        if self._top is None and self._after_id is None:
            return

        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass  # 定时器可能已经触发过，取消失败无所谓
            self._after_id = None
        self._destroy_current()

        # 关闭回调：仅在调用方显式传入时执行（见 __init__ 的说明）。
        if self.on_close is not None:
            self.on_close()

    def close(self) -> None:
        """
        公开的关闭方法，供外部（如 main.py 的主线程）调用。
        线程模型下，keyboard 线程只负责"请求关闭"，真正的关闭动作
        必须回到主线程执行，所以通过这个方法在轮询里被调用。
        """
        self._close()

    def run(self) -> None:
        """仅当本类拥有根窗口时可调用：进入事件循环。"""
        if self._owns_root:
            self.root.mainloop()


def _main():
    """命令行自测：python popup.py "要显示的文本" """
    # 测试块单独配置日志，保证用 python.exe 直接运行时输出可见
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    text = " ".join(sys.argv[1:]).strip() or (
        "这是一条测试翻译结果：Artificial intelligence is transforming the world."
    )
    popup = TranslationPopup()
    # 关键：自建 Tk 的测试分支，弹窗关闭后必须退出主循环。
    # 否则隐藏的 root 会一直卡在 mainloop()，run() 不返回，程序无法结束。
    popup.on_close = popup.root.quit
    # 稍等 300ms 再显示，模拟"主程序已启动、事件循环已就绪"的场景
    popup.root.after(300, lambda: popup.show(text))
    logger.info("弹窗已弹出（屏幕右上角）。")
    logger.info("关闭方式：点击弹窗后按 ESC，或等待 6 秒自动关闭。")
    popup.run()
    popup.root.destroy()  # mainloop 退出后再回收根窗口
    logger.info("弹窗已关闭，程序正常退出。")


if __name__ == "__main__":
    _main()
