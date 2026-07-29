"""
PoE2 多开跟随工具 — 设置向导。

提供零门槛的小白用户体验：
1. 欢迎页 + 硬件环境自检
2. 设置窗口数量（1~3）
3. 自动启动 PoE2 窗口（带进度）
4. 角色登录引导 — 告诉用户每一步该做什么
5. 就绪检查 — 确认所有角色的 P1/P2 都在游戏中
6. 完成 — 进入主控制面板
"""

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Callable, Dict, List, Optional

from src.core.hardware_check import run_all_checks, format_check_results, AllChecksResult
from src.core.multi_launcher import MultiLauncher, LaunchResult


class SetupWizard(tk.Toplevel):
    """设置向导窗口 — 引导用户从零到自动跟随就绪。"""

    def __init__(
        self,
        on_complete: Callable[[int, List[LaunchResult]], None],
        parent: Optional[tk.Tk] = None,
    ):
        """
        Args:
            on_complete: 向导完成回调 (window_count, launch_results)
            parent: 父窗口
        """
        super().__init__(parent)
        self.title("PoE2 自动跟随 — 设置向导")
        self.geometry("600x500")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self.on_complete = on_complete
        self.launch_results: List[LaunchResult] = []
        self.window_count: int = 2
        self.cancelled = False

        self._setup_style()
        self._build_ui()

        self.current_step = 0
        self._show_step(0)

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Microsoft YaHei", 18, "bold"))
        style.configure("Heading.TLabel", font=("Microsoft YaHei", 13, "bold"))
        style.configure("Body.TLabel", font=("Microsoft YaHei", 11))
        style.configure("Status.TLabel", font=("Microsoft YaHei", 10))
        style.configure("Warning.TLabel", foreground="#e67e22", font=("Microsoft YaHei", 10))
        style.configure("Error.TLabel", foreground="#e74c3c", font=("Microsoft YaHei", 10))
        style.configure("Success.TLabel", foreground="#27ae60", font=("Microsoft YaHei", 10))
        style.configure("Big.TButton", font=("Microsoft YaHei", 12, "bold"), padding=8)
        style.configure("Small.TButton", font=("Microsoft YaHei", 9), padding=4)

    def _build_ui(self):
        # 标题
        self.title_label = ttk.Label(self, text="", style="Title.TLabel")
        self.title_label.pack(pady=(20, 5))

        # 主内容区域
        self.content_frame = ttk.Frame(self)
        self.content_frame.pack(fill="both", expand=True, padx=40, pady=10)

        # 内容 Canvas (scrollable)
        self.canvas = tk.Canvas(self.content_frame, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.content_frame, orient="vertical",
                                        command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        # 默认不显示滚动条
        # self.scrollbar.pack(side="right", fill="y")

        # 底部按钮
        self.btn_frame = ttk.Frame(self)
        self.btn_frame.pack(fill="x", padx=40, pady=(0, 15))

        self.prev_btn = ttk.Button(self.btn_frame, text="上一步",
                                    style="Small.TButton", command=self._prev)
        self.prev_btn.pack(side="left")

        self.next_btn = ttk.Button(self.btn_frame, text="下一步 →",
                                    style="Big.TButton", command=self._next)
        self.next_btn.pack(side="right")

        self.cancel_btn = ttk.Button(self.btn_frame, text="取消",
                                       style="Small.TButton", command=self._on_cancel)
        self.cancel_btn.pack(side="right", padx=10)

    # ----------------------------------------------------------------
    # 步骤管理
    # ----------------------------------------------------------------

    def _clear_content(self):
        for w in self.scrollable_frame.winfo_children():
            w.destroy()

    def _show_step(self, step: int):
        self._clear_content()

        handlers = {
            0: self._step_welcome,
            1: self._step_count,
            2: self._step_launch,
            3: self._step_setup_guide,
            4: self._step_ready_check,
            5: self._step_done,
        }

        handler = handlers.get(step)
        if handler:
            handler()

        self.prev_btn.configure(state="normal" if step > 0 else "disabled")
        if step == 5:
            self.next_btn.configure(text="完成 ✓", command=self._finish)
            self.prev_btn.pack_forget()
        else:
            self.next_btn.configure(text="下一步 →", command=self._next)

    def _next(self):
        if self.current_step == 1:
            # 获取窗口数量
            if hasattr(self, 'count_var'):
                self.window_count = self.count_var.get()

        if self.current_step == 2:
            # 启动窗口
            self._do_launch()
            return

        if self.current_step == 4:
            # 最后一步检查
            pass

        self.current_step += 1
        self._show_step(self.current_step)

    def _prev(self):
        if self.current_step > 0:
            self.current_step -= 1
            self._show_step(self.current_step)

    def _on_cancel(self):
        self.cancelled = True
        self.destroy()

    # ----------------------------------------------------------------
    # Step 0: 欢迎页 + 硬件检查
    # ----------------------------------------------------------------

    def _step_welcome(self):
        self.title_label.configure(text="🎮 PoE2 自动跟随")

        ttk.Label(self.scrollable_frame,
                  text="欢迎使用 PoE2 多开自动跟随工具！",
                  style="Heading.TLabel").pack(pady=(0, 5))

        ttk.Label(self.scrollable_frame,
                  text="本工具帮你同时操控 4~6 个角色一起刷图。\n"
                       "接下来会一步步引导你完成设置。",
                  style="Body.TLabel",
                  wraplength=500).pack(pady=(0, 15))

        ttk.Separator(self.scrollable_frame, orient="horizontal").pack(fill="x", pady=5)

        ttk.Label(self.scrollable_frame,
                  text="正在检查运行环境...",
                  style="Heading.TLabel").pack(pady=(10, 5))

        check_result = run_all_checks()
        check_text = format_check_results(check_result)

        check_display = tk.Text(self.scrollable_frame, height=10, width=60,
                                 font=("Consolas", 10), state="normal",
                                 bg="#2c3e50", fg="#ecf0f1",
                                 relief="flat", padx=10, pady=10)
        check_display.pack(pady=(5, 10), fill="x")
        check_display.insert("1.0", check_text)
        check_display.configure(state="disabled")

        if not check_result.all_ok:
            ttk.Label(self.scrollable_frame,
                      text="⚠️ 检测到问题，请先修复再继续",
                      style="Error.TLabel").pack(pady=(0, 5))
            self.next_btn.configure(state="disabled")
        else:
            ttk.Label(self.scrollable_frame,
                      text="✅ 环境检查通过，可以继续",
                      style="Success.TLabel").pack(pady=(0, 5))

    # ----------------------------------------------------------------
    # Step 1: 设置窗口数量
    # ----------------------------------------------------------------

    def _step_count(self):
        self.title_label.configure(text="设置窗口数量")

        ttk.Label(self.scrollable_frame,
                  text="你想开几个 PoE2 窗口？",
                  style="Heading.TLabel").pack(pady=(0, 5))

        ttk.Label(self.scrollable_frame,
                  text="每个窗口可以登录 2 个角色（P1 键盘 + P2 手柄）\n"
                       "2 个窗口 = 4 个角色，3 个窗口 = 6 个角色",
                  style="Body.TLabel",
                  wraplength=500).pack(pady=(0, 15))

        self.count_var = tk.IntVar(value=self.window_count)

        count_frame = ttk.Frame(self.scrollable_frame)
        count_frame.pack(pady=10)

        for i in [1, 2, 3]:
            rb = ttk.Radiobutton(
                count_frame,
                text=f"{i} 个窗口 ({i * 2} 个角色)",
                variable=self.count_var,
                value=i,
            )
            rb.pack(anchor="w", pady=5)

        ttk.Separator(self.scrollable_frame, orient="horizontal").pack(fill="x", pady=15)

        ttk.Label(self.scrollable_frame,
                  text="💡 提示：如果是第一次使用，建议选 2 个窗口试试",
                  style="Body.TLabel",
                  foreground="#888").pack(pady=(0, 5))

    # ----------------------------------------------------------------
    # Step 2: 启动 PoE2 窗口
    # ----------------------------------------------------------------

    def _step_launch(self):
        self.title_label.configure(text="启动 PoE2 窗口")

        ttk.Label(self.scrollable_frame,
                  text=f"即将启动 {self.window_count} 个 PoE2 窗口",
                  style="Heading.TLabel").pack(pady=(0, 5))

        ttk.Label(self.scrollable_frame,
                  text="点击下方按钮开始启动\n"
                       "请耐心等待每个窗口加载完成",
                  style="Body.TLabel").pack(pady=(0, 15))

        self._launch_output = tk.Text(self.scrollable_frame, height=8, width=60,
                                       font=("Consolas", 9), state="normal",
                                       bg="#2c3e50", fg="#ecf0f1",
                                       relief="flat", padx=10, pady=10)
        self._launch_output.pack(pady=5, fill="x")

        self._launch_btn = ttk.Button(self.scrollable_frame,
                                       text=f"🚀 启动 {self.window_count} 个 PoE2 窗口",
                                       style="Big.TButton",
                                       command=self._do_launch)
        self._launch_btn.pack(pady=10)

        self._launch_progress = ttk.Progressbar(
            self.scrollable_frame, mode="indeterminate",
        )

        self.next_btn.configure(state="disabled")

    def _do_launch(self):
        if hasattr(self, '_launch_done') and self._launch_done:
            self.current_step = 3
            self._show_step(self.current_step)
            return

        self._launch_btn.configure(state="disabled")
        self._launch_progress.pack(pady=5, fill="x")
        self._launch_progress.start()

        self._launch_output.insert("end", f"正在启动 {self.window_count} 个 PoE2 窗口...\n")
        self._launch_output.see("end")

        def launch_thread():
            def log(msg):
                self.after(0, lambda: self._append_log(msg))

            launcher = MultiLauncher(callback=log)
            results = launcher.launch(count=self.window_count, wait_between=3.0)

            self.launch_results = results

            self.after(0, lambda: self._on_launch_done(results))

        t = threading.Thread(target=launch_thread, daemon=True)
        t.start()

    def _append_log(self, msg):
        self._launch_output.insert("end", msg + "\n")
        self._launch_output.see("end")

    def _on_launch_done(self, results: List[LaunchResult]):
        self._launch_progress.stop()
        self._launch_progress.pack_forget()

        successes = [r for r in results if r.pid > 0]
        failures = [r for r in results if r.pid == 0]

        if not successes:
            self._launch_output.insert("end", "\n❌ 所有窗口启动失败！\n")
            self._launch_output.see("end")
            messagebox.showerror("启动失败", "未能启动任何 PoE2 窗口")
            return

        self._launch_output.insert("end",
            f"\n✅ 成功启动 {len(successes)}/{len(results)} 个窗口\n")
        if failures:
            self._launch_output.insert("end",
                f"⚠️ {len(failures)} 个窗口启动失败\n")

        self._launch_output.insert("end",
            "\n现在去每个窗口中登录游戏并选择角色吧！\n")
        self._launch_output.see("end")

        self._launch_done = True
        self.next_btn.configure(state="normal")

    # ----------------------------------------------------------------
    # Step 3: 角色登录引导
    # ----------------------------------------------------------------

    def _step_setup_guide(self):
        self.title_label.configure(text="角色设置引导")

        ttk.Label(self.scrollable_frame,
                  text="按照以下步骤在每个窗口中设置角色",
                  style="Heading.TLabel").pack(pady=(0, 5))

        steps_text = (
            "━━━ 每个窗口的步骤 ━━━\n\n"
            "1️⃣ 登录账号\n"
            "   在「角色选择」界面，用键盘 ↑↓ 选择 P1 角色\n\n"
            "2️⃣ 加入 P2（手柄角色）\n"
            "   确保你的物理手柄已连接，然后在\n"
            "   「角色选择」界面按手柄 A 键激活 P2\n\n"
            "3️⃣ 选择 P2 角色\n"
            "   用手柄 ↑↓ 选择 P2 的角色\n\n"
            "4️⃣ 进入游戏\n"
            "   键盘按 Enter 或鼠标点击「开始游戏」\n"
            "   两个角色都会进入游戏世界\n\n"
            "5️⃣ 对所有窗口重复上述步骤\n\n"
            "━━━ 重要提示 ━━━\n"
            "• P1 = 键盘鼠标控制的角色\n"
            "• P2 = 手柄控制的角色（需要真手柄激活）\n"
            "• 所有窗口的 P2 都选择后，工具会自动接管 P2 控制\n"
            "• 请确保所有角色都在同一城镇/藏身处\n"
        )

        steps_display = tk.Text(self.scrollable_frame, height=20, width=60,
                                font=("Microsoft YaHei", 10),
                                bg="#f8f9fa", fg="#2c3e50",
                                relief="flat", padx=15, pady=10,
                                wrap="word")
        steps_display.pack(pady=(5, 10), fill="x")
        steps_display.insert("1.0", steps_text)
        steps_display.configure(state="disabled")

        ttk.Label(self.scrollable_frame,
                  text="完成所有窗口的角色设置后，点击「下一步」",
                  style="Body.TLabel").pack(pady=(5, 0))

    # ----------------------------------------------------------------
    # Step 4: 就绪检查
    # ----------------------------------------------------------------

    def _step_ready_check(self):
        self.title_label.configure(text="就绪检查")

        ttk.Label(self.scrollable_frame,
                  text="正在检查所有角色是否就绪...",
                  style="Heading.TLabel").pack(pady=(0, 10))

        self._check_status = tk.Text(self.scrollable_frame, height=12, width=60,
                                      font=("Consolas", 9), state="normal",
                                      bg="#2c3e50", fg="#ecf0f1",
                                      relief="flat", padx=10, pady=10)
        self._check_status.pack(pady=5, fill="x")

        self._check_progress = ttk.Progressbar(
            self.scrollable_frame, mode="indeterminate",
        )
        self._check_progress.pack(pady=5, fill="x")
        self._check_progress.start()

        self._recheck_btn = ttk.Button(
            self.scrollable_frame,
            text="🔄 重新检查",
            style="Small.TButton",
            command=lambda: self._run_ready_check(),
        )
        self._recheck_btn.pack(pady=5)

        self.next_btn.configure(state="disabled")

        self._run_ready_check()

    def _run_ready_check(self):
        self._check_status.configure(state="normal")
        self._check_status.delete("1.0", "end")

        self._check_status.insert("end", "正在检测 PoE2 窗口...\n")
        self._check_status.see("end")

        def check_thread():
            from src.core.window_registry import WindowRegistry
            import time

            registry = WindowRegistry()

            for attempt in range(20):
                time.sleep(1)
                windows = registry.scan_windows()

                self.after(0, lambda w=windows: self._update_check_status(w))

                if len(windows) >= self.window_count:
                    self.after(0, self._on_ready_ok, windows)
                    return

                self.after(0, lambda a=attempt:
                    self._check_status.insert("end",
                        f"等待窗口中... ({attempt + 1}/20)\n"))

            self.after(0, self._on_ready_fail)

        t = threading.Thread(target=check_thread, daemon=True)
        t.start()

    def _update_check_status(self, windows: List[Any]):
        self._check_status.configure(state="normal")
        self._check_status.delete("2.0", "end")

        if not windows:
            self._check_status.insert("end", "未检测到 PoE2 窗口\n")
        else:
            for i, w in enumerate(windows):
                status = "✓ 已检测到"
                hwnd = w.get("handle", w.hwnd if hasattr(w, "hwnd") else "?")
                self._check_status.insert("end",
                    f"窗口 {i + 1}: {status} (HWND: {hwnd})\n")

        self._check_status.see("end")
        self._check_status.configure(state="disabled")
        self.update_idletasks()

    def _on_ready_ok(self, windows):
        self._check_progress.stop()
        self._check_progress.pack_forget()

        count = len(windows)
        expected = self.window_count

        self._check_status.insert("end",
            f"\n✅ 检测到 {count}/{expected} 个窗口就绪！\n\n"
            "接下来将进入主控制面板，点击「完成」继续。\n")
        self._check_status.see("end")
        self._check_status.configure(state="disabled")

        self.next_btn.configure(state="normal")

    def _on_ready_fail(self):
        self._check_progress.stop()
        self._check_progress.pack_forget()

        self._check_status.insert("end",
            "\n⚠️ 超时未检测到足够窗口\n\n"
            "请确认：\n"
            "  1. PoE2 窗口已打开并登录\n"
            "  2. 所有角色已进入游戏世界\n"
            "  3. 窗口标题包含「Path of Exile 2」\n\n"
            "确认后点击「重新检查」\n")
        self._check_status.see("end")
        self._check_status.configure(state="disabled")

    # ----------------------------------------------------------------
    # Step 5: 完成
    # ----------------------------------------------------------------

    def _step_done(self):
        self.title_label.configure(text="✅ 设置完成！")

        ttk.Label(self.scrollable_frame,
                  text="一切就绪！",
                  style="Heading.TLabel").pack(pady=(0, 5))

        ttk.Label(self.scrollable_frame,
                  text=f"已检测到 {self.window_count} 个 PoE2 窗口\n"
                       f"共 {self.window_count * 2} 个角色\n\n"
                       "点击「完成」进入控制面板\n"
                       "在控制面板中分配角色后即可开始自动跟随",
                  style="Body.TLabel",
                  wraplength=500).pack(pady=(0, 15))

        ttk.Label(self.scrollable_frame,
                  text="💡 小贴士：把所有角色聚集到同一个传送点附近，\n"
                       "  然后点击 Start 开始自动跟随",
                  style="Body.TLabel",
                  foreground="#888").pack(pady=(10, 5))

    def _finish(self):
        self.destroy()
        if not self.cancelled:
            self.on_complete(self.window_count, self.launch_results)
