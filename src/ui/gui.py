from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional

from src.common.gui_log_handler import GuiLogHandler, LogPanel
from src.common.logger import get_logger, setup_logging
from src.core.memory_reader import EntityPosition

logger = get_logger(__name__)


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
        self._running = False

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

        columns = ("idx", "hwnd", "pid", "pos", "fmt_target", "stuck", "wasd")
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

        self._tree.column("idx", width=30, anchor=tk.CENTER)
        self._tree.column("hwnd", width=60, anchor=tk.CENTER)
        self._tree.column("pid", width=55, anchor=tk.CENTER)
        self._tree.column("pos", width=140, anchor=tk.W)
        self._tree.column("fmt_target", width=140, anchor=tk.W)
        self._tree.column("stuck", width=90, anchor=tk.CENTER)
        self._tree.column("wasd", width=60, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for f in self._followers.values():
            self._tree.insert(
                "",
                tk.END,
                iid=str(f.hwnd),
                values=(f.index, f.hwnd, f.pid or "--", "--", "--", "--", ""),
            )

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

    def _do_start(self) -> None:
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
        if pos:
            self._leader_label.configure(
                text=f"HWND={self._leader_hwnd}  PID={self._leader_pid}  "
                f"Pos: ({pos.x:.1f}, {pos.y:.1f}, {pos.z:.1f})"
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
                ))

    def mainloop(self) -> None:
        self._root.mainloop()
