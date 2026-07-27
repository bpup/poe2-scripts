from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

from src.common.config_loader import AccountConfig, PartyConfig
from src.common.gui_log_handler import GuiLogHandler, LogPanel
from src.common.logger import get_logger
from src.core.memory_reader import CharacterInfo, EntityPosition, HealthData
from src.ui.map_view import MapView

logger = get_logger(__name__)


_WindowEntry = Dict[str, Any]


def select_windows(
    windows: List[_WindowEntry],
    accounts: List[AccountConfig],
) -> Optional[Dict[str, int]]:
    """Show an account→HWND mapping dialog.

    Returns ``{account_id: hwnd}`` or ``None`` if cancelled.
    """
    root = tk.Tk()
    root.withdraw()

    dialog = _WindowSelectorDialog(root, windows, accounts)
    root.wait_window(dialog)

    try:
        root.destroy()
    except tk.TclError:
        pass

    return dialog.result


class _WindowSelectorDialog(tk.Toplevel):
    def __init__(
        self, parent: tk.Tk, windows: List[_WindowEntry],
        accounts: List[AccountConfig],
    ) -> None:
        super().__init__(parent)
        self.title("Map Accounts to PoE2 Windows")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._windows = windows
        self._accounts = accounts

        hwnd_options = [self._option_label(w) for w in windows]
        self._hwnd_options = hwnd_options
        self._hwnd_values = [int(w["handle"]) for w in windows]
        self._selection_vars: List[tk.StringVar] = []

        self.result: Optional[Dict[str, int]] = None

        self._build_ui()
        self.grab_set()

    @staticmethod
    def _option_label(win: _WindowEntry) -> str:
        cn = win.get("char_name", "")
        hwnd = win.get("handle", "")
        if cn and cn != "???":
            cl = win.get("char_class", "")
            lv = win.get("char_level", "")
            extra = f" {cl} L{lv}" if cl or lv else ""
            return f"{cn}{extra} (HWND={hwnd})"
        return f"HWND={hwnd} (PID={win.get('pid', '?')})"

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=f"Found {len(self._windows)} PoE2 window(s) — "
                 f"map to {len(self._accounts)} account(s):",
            wraplength=520,
        ).grid(row=0, column=0, columnspan=5, sticky=tk.W, pady=(0, 8))

        ttk.Label(frame, text="Account", font=("", 9, "bold")).grid(
            row=1, column=0, padx=4, sticky=tk.W,
        )
        ttk.Label(frame, text="Window", font=("", 9, "bold")).grid(
            row=1, column=1, padx=4, sticky=tk.W,
        )
        ttk.Label(frame, text="P1 (Slot 0)", font=("", 9, "bold")).grid(
            row=1, column=2, padx=4, sticky=tk.W,
        )
        ttk.Label(frame, text="P2 (Slot 1)", font=("", 9, "bold")).grid(
            row=1, column=3, padx=4, sticky=tk.W,
        )
        ttk.Label(frame, text="Role", font=("", 9, "bold")).grid(
            row=1, column=4, padx=4, sticky=tk.W,
        )

        sep = ttk.Separator(frame, orient=tk.HORIZONTAL)
        sep.grid(row=2, column=0, columnspan=5, sticky=tk.EW, pady=2)

        for i, account in enumerate(self._accounts):
            row = i + 3
            ttk.Label(frame, text=account.id, font=("", 9, "bold")).grid(
                row=row, column=0, padx=4, sticky=tk.W,
            )

            var = tk.StringVar(value=self._hwnd_options[0] if self._hwnd_options else "")
            self._selection_vars.append(var)
            cb = ttk.Combobox(
                frame, textvariable=var, values=self._hwnd_options,
                state="readonly", width=40,
            )
            cb.grid(row=row, column=1, padx=4, sticky=tk.W)

            p1_label = "—"
            p2_label = "gamepad"
            roles: List[str] = []
            for char in account.characters:
                if char.slot == 0:
                    roles.append(f"P1={char.role}")
                elif char.slot == 1:
                    roles.append(f"P2={char.role}")

            ttk.Label(frame, text=p1_label).grid(row=row, column=2, padx=4, sticky=tk.W)
            ttk.Label(frame, text=p2_label).grid(row=row, column=3, padx=4, sticky=tk.W)
            ttk.Label(frame, text=", ".join(roles) if roles else "—").grid(
                row=row, column=4, padx=4, sticky=tk.W,
            )

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=len(self._accounts) + 3, column=0, columnspan=5,
                       pady=(12, 0), sticky=tk.E)

        ttk.Button(btn_frame, text="OK", command=self._on_confirm).pack(
            side=tk.LEFT, padx=4,
        )
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(
            side=tk.LEFT, padx=4,
        )

    def _on_confirm(self) -> None:
        result: Dict[str, int] = {}
        for i, account in enumerate(self._accounts):
            selected = self._selection_vars[i].get()
            if not selected:
                messagebox.showwarning(
                    "Missing Window",
                    f"No window selected for account '{account.id}'.",
                    parent=self,
                )
                return
            idx = self._hwnd_options.index(selected)
            result[account.id] = self._hwnd_values[idx]

        if len(set(result.values())) != len(result):
            messagebox.showwarning(
                "Duplicate Window",
                "Each account must use a different window.",
                parent=self,
            )
            return

        self.result = result
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class FollowerTracker:
    __slots__ = (
        "key", "account_id", "slot", "role", "input_method",
        "hwnd", "pid", "index", "char_name", "char_class", "char_level",
        "pos", "formation_target", "stuck_level", "stuck_counter",
        "reverse_remaining", "wasd", "health",
    )

    def __init__(
        self, key: str, account_id: str, slot: int, role: str,
        input_method: str, hwnd: int, pid: int, index: int,
    ) -> None:
        self.key = key
        self.account_id = account_id
        self.slot = slot
        self.role = role
        self.input_method = input_method
        self.hwnd = hwnd
        self.pid = pid
        self.index = index
        self.char_name: str = ""
        self.char_class: str = ""
        self.char_level: int = 0
        self.pos: Optional[EntityPosition] = None
        self.formation_target: Optional[Tuple[float, float]] = None
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
        party_config: PartyConfig,
        account_hwnds: Dict[str, int],
        window_info: Dict[str, dict],
        on_start: Any,
        on_stop: Any,
        on_pause_toggle: Any = None,
    ) -> None:
        self._status_queue = status_queue
        self._log_handler = log_handler
        self._party_config = party_config
        self._account_hwnds = account_hwnds
        self._window_info = window_info

        self._leader_key: Optional[str] = None
        self._leader_char: Optional[CharacterInfo] = None
        self._followers: Dict[str, FollowerTracker] = {}

        follower_idx = 0
        for account in party_config.accounts:
            p1_info = window_info.get(account.id, {})
            p1_name = p1_info.get("char_name", "")
            p1_class = p1_info.get("char_class", "")
            p1_level = p1_info.get("char_level", 0)
            for char in account.characters:
                key = f"{account.id}:{char.slot}"
                hwnd = account_hwnds.get(account.id, 0)
                pid = p1_info.get("pid", 0) if isinstance(p1_info, dict) else 0
                tracker = FollowerTracker(
                    key=key, account_id=account.id, slot=char.slot,
                    role=char.role, input_method=char.input_method,
                    hwnd=hwnd, pid=pid, index=follower_idx,
                )
                if char.slot == 0:
                    tracker.char_name = p1_name
                    tracker.char_class = p1_class
                    tracker.char_level = p1_level
                self._followers[key] = tracker
                follower_idx += 1

        for ft in self._followers.values():
            if ft.role == "leader":
                self._leader_key = ft.key

        self._on_start = on_start
        self._on_stop = on_stop
        self._on_pause_toggle = on_pause_toggle
        self._running = False

        # Per-follower pause state (source of truth for GUI display)
        self._pause_states: Dict[str, bool] = {key: False for key in self._followers}

        self._root = tk.Tk()
        self._root.title("PoE2 Auto-Follow")
        self._root.geometry("1100x750")
        self._root.minsize(800, 500)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_notebook()
        self._build_button_bar()
        self._build_log_panel()

        self._root.after(self.POLL_MS, self._poll_status)

    def _build_notebook(self) -> None:
        nb = ttk.Notebook(self._root)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))

        overview = ttk.Frame(nb)
        nb.add(overview, text="Overview")

        self._build_leader_frame(overview)
        self._build_follower_table(overview)

        map_frame = ttk.Frame(nb)
        nb.add(map_frame, text="Big Map")
        self._map_view = MapView(map_frame)
        self._map_view.pack(fill=tk.BOTH, expand=True)

    def _build_leader_frame(self, parent: tk.Widget) -> None:
        frame = ttk.LabelFrame(parent, text="Leader", padding=4)
        frame.pack(fill=tk.X, padx=4, pady=(4, 2))

        info = self._leader_info_text()
        self._leader_label = ttk.Label(frame, text=info, font=("Consolas", 10))
        self._leader_label.pack(anchor=tk.W, padx=2)

    def _leader_info_text(self) -> str:
        if self._leader_key is None:
            return "Leader: —"

        ft = self._followers.get(self._leader_key)
        if ft is None:
            return f"Leader: {self._leader_key}"

        name_part = ""
        if ft.char_name:
            cl = f" ({ft.char_class})" if ft.char_class else ""
            name_part = f"  [{ft.account_id}] {ft.char_name}{cl} L{ft.char_level}"

        return (
            f"Leader: {ft.key}{name_part}  "
            f"HWND={ft.hwnd}  PID={ft.pid}  Pos: --"
        )

    def _build_follower_table(self, parent: tk.Widget) -> None:
        frame = ttk.LabelFrame(parent, text="Followers", padding=4)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        columns = ("idx", "account", "slot", "role", "name", "pos",
                   "fmt_target", "stuck", "input", "wasd", "health", "pause")
        self._tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=8,
        )
        self._tree.heading("idx", text="#", anchor=tk.CENTER)
        self._tree.heading("account", text="Account", anchor=tk.W)
        self._tree.heading("slot", text="Slot", anchor=tk.CENTER)
        self._tree.heading("role", text="Role", anchor=tk.CENTER)
        self._tree.heading("name", text="Character", anchor=tk.W)
        self._tree.heading("pos", text="Position (X, Y)", anchor=tk.W)
        self._tree.heading("fmt_target", text="Formation Target", anchor=tk.W)
        self._tree.heading("stuck", text="Stuck", anchor=tk.CENTER)
        self._tree.heading("input", text="Input", anchor=tk.CENTER)
        self._tree.heading("wasd", text="Keys", anchor=tk.CENTER)
        self._tree.heading("health", text="HP / ES", anchor=tk.CENTER)
        self._tree.heading("pause", text="Pause", anchor=tk.CENTER)

        widths = {
            "idx": 30, "account": 60, "slot": 36, "role": 48,
            "name": 160, "pos": 140, "fmt_target": 140,
            "stuck": 90, "input": 52, "wasd": 60, "health": 88,
            "pause": 50,
        }
        for col, w in widths.items():
            an = tk.CENTER if col in ("idx", "slot", "role", "stuck", "input", "wasd", "health", "pause") else tk.W
            self._tree.column(col, width=w, anchor=an)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for ft in self._followers.values():
            if ft.role == "leader":
                continue
            nm = self._fmt_char_name(ft)
            inp = ft.input_method[:4] if ft.input_method else "keyb"
            self._tree.insert(
                "",
                tk.END,
                iid=ft.key,
                values=(
                    ft.index, ft.account_id, ft.slot, ft.role,
                    nm, "--", "--", "--", inp, "--", "--", "▶",
                ),
            )

        # Click on the Pause column toggles per-follower pause
        self._tree.bind("<ButtonRelease-1>", self._on_tree_click)

    @staticmethod
    def _fmt_char_name(tracker: FollowerTracker) -> str:
        if tracker.char_name:
            cl = f" ({tracker.char_class})" if tracker.char_class else ""
            return f"{tracker.char_name}{cl} L{tracker.char_level}"
        if tracker.input_method == "gamepad":
            return "(gamepad)"
        return f"HWND={tracker.hwnd}"

    def _build_button_bar(self) -> None:
        frame = ttk.Frame(self._root)
        frame.pack(fill=tk.X, padx=4, pady=2)

        self._start_btn = ttk.Button(frame, text="Start", command=self._do_start)
        self._start_btn.pack(side=tk.LEFT, padx=2)

        self._stop_btn = ttk.Button(
            frame, text="Stop", command=self._do_stop, state=tk.DISABLED,
        )
        self._stop_btn.pack(side=tk.LEFT, padx=2)

        self._status_label = ttk.Label(frame, text="Ready.", font=("", 9))
        self._status_label.pack(side=tk.LEFT, padx=8)

    def _build_log_panel(self) -> None:
        frame = ttk.LabelFrame(self._root, text="Log", padding=2)
        frame.pack(fill=tk.BOTH, expand=False, padx=4, pady=(2, 4))
        self._log_panel = LogPanel(frame, self._log_handler, poll_ms=100, max_lines=500)
        self._log_panel.pack(fill=tk.BOTH, expand=True)

    def reset_pause_states(self) -> None:
        """Clear all per-follower pause states (called when the agent restarts)."""
        for key in list(self._pause_states):
            self._pause_states[key] = False
        for tree_id in self._tree.get_children():
            vals = list(self._tree.item(tree_id, "values"))
            if len(vals) >= 12:
                vals[11] = "▶"
                self._tree.item(tree_id, values=vals)

    def _on_tree_click(self, event: Any) -> None:
        """Toggle pause state when the Pause column (#12) is clicked."""
        col = self._tree.identify_column(event.x)
        row = self._tree.identify_row(event.y)
        if not row or col != "#12":
            return
        key = row
        paused = not self._pause_states.get(key, False)
        self._pause_states[key] = paused
        vals = list(self._tree.item(row, "values"))
        if len(vals) >= 12:
            vals[11] = "⏸" if paused else "▶"
            self._tree.item(row, values=vals)
        if self._on_pause_toggle:
            self._on_pause_toggle(key, paused)

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
            elif msg_type == "map":
                self._update_map(msg.get("data", {}))

        self._root.after(self.POLL_MS, self._poll_status)

    def _update_leader(self, msg: dict) -> None:
        pos = msg.get("pos")
        health = msg.get("health")
        ci = msg.get("char_info")
        if ci is not None:
            self._leader_char = ci

        ft = self._followers.get(self._leader_key or "")
        if ft:
            if ci:
                ft.char_name = ci.name
                ft.char_class = ci.class_name
                ft.char_level = ci.level

        hp_str = ""
        if isinstance(health, HealthData):
            hp_str = f"  HP: {health.current}/{health.maximum} ({health.ratio:.0%})"
            if health.es_maximum > 0:
                hp_str += f"  ES: {health.es_current}/{health.es_maximum}"
        elif isinstance(health, dict):
            hp_str = f"  HP: {health.get('current','?')}/{health.get('maximum','?')}"

        info = self._leader_info_text()
        if pos:
            info += f"  Pos: ({pos.x:.1f}, {pos.y:.1f}, {pos.z:.1f}){hp_str}"
        self._leader_label.configure(text=info)

    def _update_followers(self, data: List[dict]) -> None:
        for item in data:
            key = item.get("key", "")
            if not key or key not in self._tree.get_children():
                continue

            pos = item.get("pos")
            fmt = item.get("fmt_target")
            pos_str = f"({pos.x:.1f}, {pos.y:.1f})" if pos else "--"
            fmt_str = f"({fmt[0]:.1f}, {fmt[1]:.1f})" if fmt else "--"
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

            char_info = item.get("char_info")
            tracker = self._followers.get(key)
            if char_info and tracker:
                tracker.char_name = char_info.name
                tracker.char_class = char_info.class_name
                tracker.char_level = char_info.level

            name_str = self._fmt_char_name(tracker) if tracker else key
            inp_str = tracker.input_method[:4] if tracker and tracker.input_method else "keyb"

            pause_str = "⏸" if self._pause_states.get(key, False) else "▶"

            if key in self._tree.get_children():
                self._tree.item(key, values=(
                    item.get("index", "?"),
                    tracker.account_id if tracker else "?",
                    tracker.slot if tracker else "?",
                    tracker.role if tracker else "?",
                    name_str,
                    pos_str,
                    fmt_str,
                    stuck_str,
                    inp_str,
                    wasd_str,
                    hp_str,
                    pause_str,
                ))

    def _update_map(self, data: dict) -> None:
        terrain = data.get("terrain")
        leader_pos = data.get("leader_pos")
        follower_list = data.get("followers", [])
        self._map_view.update_data(
            terrain=terrain,
            leader_pos=leader_pos,
            follower_positions=follower_list,
        )

    def mainloop(self) -> None:
        self._root.mainloop()
