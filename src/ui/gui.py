from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

from src.common.gui_log_handler import GuiLogHandler, LogPanel
from src.common.logger import get_logger
from src.core.memory_reader import EntityPosition, HealthData

logger = get_logger(__name__)


# ── Window Selector Dialog ──────────────────────────────────────

_WindowEntry = Dict[str, Any]


def select_windows(windows: List[_WindowEntry]) -> Optional[Tuple[int, List[int]]]:
    """Show a modal dialog to pick the Leader window and confirm Followers.

    Returns ``(leader_hwnd, follower_hwnds)`` or ``None`` if cancelled.
    """
    root = tk.Tk()
    root.withdraw()

    dialog = _WindowSelectorDialog(root, windows)
    root.wait_window(dialog)

    try:
        root.destroy()
    except tk.TclError:
        pass

    return dialog.result


class _WindowSelectorDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, windows: List[_WindowEntry]) -> None:
        super().__init__(parent)
        self.title("Select PoE2 Windows")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._windows = windows
        self._leader_var = tk.StringVar()
        self._follower_vars: Dict[str, tk.BooleanVar] = {}
        self.result: Optional[Tuple[int, List[int]]] = None

        self._build_ui()
        self.grab_set()

    # ── UI ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=f"Found {len(self._windows)} PoE2 window(s). Select one Leader, "
                 "then choose Followers:",
            wraplength=420,
        ).grid(row=0, column=0, columnspan=5, sticky=tk.W, pady=(0, 8))

        # header row
        ttk.Label(frame, text="Leader", font=("", 9, "bold")).grid(
            row=1, column=0, padx=4
        )
        ttk.Label(frame, text="Follow", font=("", 9, "bold")).grid(
            row=1, column=1, padx=4
        )
        ttk.Label(frame, text="HWND", font=("", 9, "bold")).grid(
            row=1, column=2, padx=4, sticky=tk.W
        )
        ttk.Label(frame, text="Window Title", font=("", 9, "bold")).grid(
            row=1, column=3, padx=4, sticky=tk.W
        )

        sep = ttk.Separator(frame, orient=tk.HORIZONTAL)
        sep.grid(row=2, column=0, columnspan=5, sticky=tk.EW, pady=2)

        for i, win in enumerate(self._windows):
            hwnd_str = win["handle"]
            title = win.get("title", "")
            row = i + 3

            # leader radio — first window pre-selected
            rb = ttk.Radiobutton(
                frame, variable=self._leader_var, value=hwnd_str,
            )
            if i == 0:
                rb.invoke()
            rb.grid(row=row, column=0, padx=4)

            # follower checkbox — all checked by default
            var = tk.BooleanVar(value=True)
            self._follower_vars[hwnd_str] = var
            cb = ttk.Checkbutton(frame, variable=var)
            cb.grid(row=row, column=1, padx=4)

            ttk.Label(frame, text=hwnd_str).grid(row=row, column=2, padx=4, sticky=tk.W)
            ttk.Label(frame, text=title[:60]).grid(row=row, column=3, padx=4, sticky=tk.W)

        # ── buttons ──────────────────────────────────────
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=len(self._windows) + 3, column=0, columnspan=5,
                       pady=(12, 0), sticky=tk.E)

        ttk.Button(btn_frame, text="OK", command=self._on_confirm).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(
            side=tk.LEFT, padx=4
        )

    # ── callbacks ─────────────────────────────────────────

    def _on_confirm(self) -> None:
        leader_str = self._leader_var.get()
        if not leader_str:
            messagebox.showwarning(
                "No Leader", "Please select one Leader window.", parent=self,
            )
            return

        leader_hwnd = int(leader_str)

        follower_hwnds: List[int] = []
        for win in self._windows:
            hwnd_str = win["handle"]
            hwnd_int = int(hwnd_str)
            if hwnd_int == leader_hwnd:
                continue
            if self._follower_vars.get(hwnd_str, tk.BooleanVar(value=False)).get():
                follower_hwnds.append(hwnd_int)

        if not follower_hwnds:
            messagebox.showwarning(
                "No Followers", "Please select at least one Follower.", parent=self,
            )
            return

        self.result = (leader_hwnd, follower_hwnds)
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class FollowerTracker:
    __slots__ = (
        "hwnd",
        "pid",
        "index",
        "pos",
        "formation_target",
        "stuck_level",
        "stuck_counter",
        "reverse_remaining",
        "wasd",
        "health",
    )

    def __init__(self, hwnd: int, pid: int, index: int) -> None:
        self.hwnd = hwnd
        self.pid = pid
        self.index = index
        self.pos: Optional[EntityPosition] = None
        self.formation_target: Optional[tuple[float, float]] = None
        self.stuck_level = 0
        self.stuck_counter = 0
        self.reverse_remaining = 0
        self.wasd: str = ""
        self.health: Optional[HealthData] = None


class NavGui:
    POLL_MS = 80

    def __init__(
        self,
        status_queue: queue.Queue[dict],
        log_handler: GuiLogHandler,
        leader_hwnd: int,
        leader_pid: int,
        follower_hwnds: List[int],
        follower_pids: Dict[int, int],
        on_start: Any,
        on_stop: Any,
        on_pause_toggle: Any = None,
    ) -> None:
        self._status_queue = status_queue
        self._log_handler = log_handler
        self._leader_hwnd = leader_hwnd
        self._leader_pid = leader_pid

        self._followers: Dict[int, FollowerTracker] = {}
        for i, hwnd in enumerate(follower_hwnds):
            pid = follower_pids.get(hwnd, 0)
            self._followers[hwnd] = FollowerTracker(hwnd, pid, i)

        self._on_start = on_start
        self._on_stop = on_stop
        self._on_pause_toggle = on_pause_toggle
        self._running = False

        # Per-follower pause state (source of truth for GUI display)
        self._pause_states: Dict[int, bool] = {hwnd: False for hwnd in follower_hwnds}

        self._root = tk.Tk()
        self._root.title("PoE2 Auto-Follow")
        self._root.geometry("900x650")
        self._root.minsize(640, 400)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_leader_frame()
        self._build_follower_table()
        self._build_button_bar()
        self._build_log_panel()

        self._root.after(self.POLL_MS, self._poll_status)

    def _build_leader_frame(self) -> None:
        frame = ttk.LabelFrame(self._root, text="Leader", padding=4)
        frame.pack(fill=tk.X, padx=4, pady=(4, 2))

        self._leader_label = ttk.Label(
            frame,
            text=f"HWND={self._leader_hwnd}  PID={self._leader_pid}  Pos: --",
            font=("Consolas", 10),
        )
        self._leader_label.pack(anchor=tk.W, padx=2)

    def _build_follower_table(self) -> None:
        frame = ttk.LabelFrame(self._root, text="Followers", padding=4)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        columns = ("idx", "hwnd", "pid", "pos", "fmt_target", "stuck", "wasd", "health", "pause")
        self._tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=6
        )
        self._tree.heading("idx", text="#", anchor=tk.CENTER)
        self._tree.heading("hwnd", text="HWND", anchor=tk.CENTER)
        self._tree.heading("pid", text="PID", anchor=tk.CENTER)
        self._tree.heading("pos", text="Position (X, Y)", anchor=tk.W)
        self._tree.heading("fmt_target", text="Formation Target", anchor=tk.W)
        self._tree.heading("stuck", text="Stuck Lvl/Cnt/Rev", anchor=tk.CENTER)
        self._tree.heading("wasd", text="Keys", anchor=tk.CENTER)
        self._tree.heading("health", text="HP / ES", anchor=tk.CENTER)
        self._tree.heading("pause", text="Pause", anchor=tk.CENTER)

        self._tree.column("idx", width=30, anchor=tk.CENTER)
        self._tree.column("hwnd", width=60, anchor=tk.CENTER)
        self._tree.column("pid", width=55, anchor=tk.CENTER)
        self._tree.column("pos", width=140, anchor=tk.W)
        self._tree.column("fmt_target", width=140, anchor=tk.W)
        self._tree.column("stuck", width=90, anchor=tk.CENTER)
        self._tree.column("wasd", width=60, anchor=tk.CENTER)
        self._tree.column("health", width=110, anchor=tk.CENTER)
        self._tree.column("pause", width=50, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for f in self._followers.values():
            self._tree.insert(
                "",
                tk.END,
                iid=str(f.hwnd),
                values=(f.index, f.hwnd, f.pid or "--", "--", "--", "--", "", "--", "▶"),
            )

        # Click on the Pause column toggles per-follower pause
        self._tree.bind("<ButtonRelease-1>", self._on_tree_click)

    def _build_button_bar(self) -> None:
        frame = ttk.Frame(self._root)
        frame.pack(fill=tk.X, padx=4, pady=2)

        self._start_btn = ttk.Button(frame, text="Start", command=self._do_start)
        self._start_btn.pack(side=tk.LEFT, padx=2)

        self._stop_btn = ttk.Button(
            frame, text="Stop", command=self._do_stop, state=tk.DISABLED
        )
        self._stop_btn.pack(side=tk.LEFT, padx=2)

        self._status_label = ttk.Label(frame, text="Ready.", font=("", 9))
        self._status_label.pack(side=tk.LEFT, padx=8)

    def _build_log_panel(self) -> None:
        frame = ttk.LabelFrame(self._root, text="Log", padding=2)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
        self._log_panel = LogPanel(frame, self._log_handler, poll_ms=100, max_lines=500)
        self._log_panel.pack(fill=tk.BOTH, expand=True)

    def reset_pause_states(self) -> None:
        """Clear all per-follower pause states (called when the agent restarts)."""
        for hwnd in list(self._pause_states):
            self._pause_states[hwnd] = False
        for hwnd_str in self._tree.get_children():
            vals = list(self._tree.item(hwnd_str, "values"))
            if len(vals) >= 9:
                vals[8] = "▶"
                self._tree.item(hwnd_str, values=vals)

    def _on_tree_click(self, event: Any) -> None:
        """Toggle pause state when the Pause column (#9) is clicked."""
        col = self._tree.identify_column(event.x)
        row = self._tree.identify_row(event.y)
        if not row or col != "#9":
            return
        try:
            hwnd = int(row)
        except ValueError:
            return
        paused = not self._pause_states.get(hwnd, False)
        self._pause_states[hwnd] = paused
        vals = list(self._tree.item(row, "values"))
        if len(vals) >= 9:
            vals[8] = "⏸" if paused else "▶"
            self._tree.item(row, values=vals)
        if self._on_pause_toggle:
            self._on_pause_toggle(hwnd, paused)

    def _do_start(self) -> None:
        self.reset_pause_states()
        self._running = True
        self._start_btn.configure(state=tk.DISABLED)
        self._stop_btn.configure(state=tk.NORMAL)
        self._status_label.configure(text="Running...")
        try:
            self._on_start()
        except Exception:
            logger.exception("on_start callback failed")

    def _do_stop(self) -> None:
        self._on_stop()
        self._running = False
        self._start_btn.configure(state=tk.NORMAL)
        self._stop_btn.configure(state=tk.DISABLED)
        self._status_label.configure(text="Stopped.")

    def _on_close(self) -> None:
        if self._running:
            self._do_stop()
        self._root.destroy()

    def _poll_status(self) -> None:
        while True:
            try:
                msg: dict = self._status_queue.get_nowait()
            except queue.Empty:
                break

            msg_type = msg.get("type", "")
            if msg_type == "leader":
                self._update_leader(msg)
            elif msg_type == "followers":
                self._update_followers(msg.get("data", []))
            elif msg_type == "state":
                self._status_label.configure(text=msg.get("text", ""))

        self._root.after(self.POLL_MS, self._poll_status)

    def _update_leader(self, msg: dict) -> None:
        pos = msg.get("pos")
        health = msg.get("health")
        hp_str = ""
        if isinstance(health, HealthData):
            hp_str = f"  HP: {health.current}/{health.maximum} ({health.ratio:.0%})"
            if health.es_maximum > 0:
                hp_str += f"  ES: {health.es_current}/{health.es_maximum}"
        elif isinstance(health, dict):
            hp_str = f"  HP: {health.get('current','?')}/{health.get('maximum','?')}"
        if pos:
            self._leader_label.configure(
                text=f"HWND={self._leader_hwnd}  PID={self._leader_pid}  "
                f"Pos: ({pos.x:.1f}, {pos.y:.1f}, {pos.z:.1f}){hp_str}"
            )
        else:
            self._leader_label.configure(
                text=f"HWND={self._leader_hwnd}  PID={self._leader_pid}  Pos: --"
            )

    def _update_followers(self, data: list[dict]) -> None:
        for item in data:
            hwnd = item.get("hwnd")
            if hwnd is None or str(hwnd) not in self._tree.get_children():
                continue

            pos = item.get("pos")
            fmt = item.get("fmt_target")
            pos_str = (
                f"({pos.x:.1f}, {pos.y:.1f})" if pos else "--"
            )
            fmt_str = (
                f"({fmt[0]:.1f}, {fmt[1]:.1f})" if fmt else "--"
            )
            stuck_str = (
                f"L{item.get('stuck_level',0)} "
                f"C{item.get('stuck_counter',0)} "
                f"R{item.get('reverse_remaining',0)}"
            )
            wasd = item.get("wasd", "")
            wasd_str = "".join(sorted(wasd)) if wasd else "—"

            health = item.get("health")
            if isinstance(health, HealthData):
                hp_str = f"{health.current}/{health.maximum}"
                if health.es_maximum > 0:
                    hp_str += f" ES:{health.es_current}"
            elif isinstance(health, dict):
                hp_str = f"{health.get('current','?')}/{health.get('maximum','?')}"
            else:
                hp_str = "--"

            pause_str = "⏸" if self._pause_states.get(hwnd, False) else "▶"

            tk_id = str(hwnd)
            if tk_id in self._tree.get_children():
                self._tree.item(tk_id, values=(
                    item.get("index", "?"),
                    hwnd,
                    item.get("pid", "--"),
                    pos_str,
                    fmt_str,
                    stuck_str,
                    wasd_str,
                    hp_str,
                    pause_str,
                ))

    def mainloop(self) -> None:
        self._root.mainloop()
