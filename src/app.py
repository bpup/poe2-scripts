from __future__ import annotations

import logging
import queue
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.common.config_loader import (
    AccountConfig, CharacterConfig, PartyConfig,
    RuntimeConfig, SamplingConfig, load_config,
)
from src.common.gui_log_handler import GuiLogHandler
from src.common.logger import ROOT_LOGGER_NAME, get_logger
from src.common.runtime_paths import resource_root
from src.core.window_registry import WindowRegistry
from src.ui.setup_wizard import SetupWizard
from src.follow.nav_agent import NavAgent

logger = get_logger(__name__)


def _auto_generate_party_config(window_count: int) -> PartyConfig:
    """从向导窗口数自动生成 PartyConfig，不需要用户编辑 YAML。

    规则：
    - account_1 slot 0 = leader（用户手动操控）
    - account_1 slot 1 = follower（虚拟手柄跟随）
    - 其余窗口所有 slot = follower
    """
    config_path = resource_root() / "config" / "nav-follow.yaml"
    base_config = load_config(str(config_path))

    account_names = [f"account_{i + 1}" for i in range(window_count)]

    accounts: List[AccountConfig] = []
    for i, name in enumerate(account_names):
        chars: List[CharacterConfig] = []

        if i == 0:
            chars.append(CharacterConfig(slot=0, role="leader", input_method="none"))
        else:
            chars.append(CharacterConfig(slot=0, role="follower", input_method="keyboard"))

        chars.append(CharacterConfig(slot=1, role="follower", input_method="gamepad"))

        accounts.append(AccountConfig(
            id=name,
            window_title="Path of Exile 2",
            characters=chars,
        ))

    return PartyConfig(
        accounts=accounts,
        sampling=base_config.sampling,
        runtime=base_config.runtime,
        nav=base_config.nav,
    )


def _scan_and_assign_windows(
    registry: WindowRegistry,
    config: PartyConfig,
) -> Optional[Dict[str, int]]:
    """扫描 PoE2 窗口，自动分配给账号。

    Returns {account_id: hwnd}，按检测顺序分配。
    """
    all_windows = registry.scan_windows("Path of Exile 2")

    if len(all_windows) < len(config.accounts):
        logger.error(
            "Found %d window(s) — need at least %d for %d account(s).",
            len(all_windows), len(config.accounts), len(config.accounts),
        )
        return None

    hwnds = [int(w["handle"]) for w in all_windows]
    assignment: Dict[str, int] = {}
    for i, account in enumerate(config.accounts):
        assignment[account.id] = hwnds[i]

    return assignment


def _simple_window_confirm(
    assignment: Dict[str, int],
    config: PartyConfig,
) -> bool:
    """简单弹窗确认窗口分配。返回 True 表示确认。"""
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = tk.Tk()
    root.withdraw()

    dialog = tk.Toplevel(root)
    dialog.title("窗口分配确认")
    dialog.resizable(False, False)
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    frame = ttk.Frame(dialog, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame,
        text=f"检测到 {len(assignment)} 个 PoE2 窗口，自动分配如下：",
        font=("Microsoft YaHei", 11),
        wraplength=400,
    ).pack(pady=(0, 10))

    for i, (aid, hwnd) in enumerate(assignment.items()):
        char_configs = []
        account = next((a for a in config.accounts if a.id == aid), None)
        if account:
            for ch in account.characters:
                slot_name = "P1 (键盘)" if ch.slot == 0 else "P2 (手柄)"
                role_name = {"leader": "领队", "follower": "跟��"}.get(ch.role, ch.role)
                char_configs.append(f"{slot_name} → {role_name}")
            char_desc = " + ".join(char_configs) if char_configs else "无角色"
        else:
            char_desc = "?"

        ttk.Label(
            frame,
            text=f"窗口 {i + 1}: 账号 {aid} · {char_desc} · HWND={hwnd}",
            font=("Consolas", 10),
        ).pack(anchor="w", pady=2)

    btn_frame = ttk.Frame(frame)
    btn_frame.pack(pady=(15, 0))

    confirmed = [False]

    def on_ok():
        confirmed[0] = True
        dialog.destroy()

    ttk.Button(btn_frame, text="确认，开始使用", command=on_ok).pack(
        side="left", padx=4,
    )
    ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(
        side="left", padx=4,
    )

    root.wait_window(dialog)
    try:
        root.destroy()
    except tk.TclError:
        pass

    return confirmed[0]


def main() -> None:
    # ── Phase 1: Setup Wizard ─────────────────────────────────────
    wizard_result: dict = {"window_count": 0, "launch_results": []}

    def on_wizard_complete(window_count: int, launch_results: list):
        wizard_result["window_count"] = window_count
        wizard_result["launch_results"] = list(launch_results)

    wizard = SetupWizard(on_complete=on_wizard_complete)
    wizard.grab_set()
    wizard.wait_window()

    if not wizard_result["window_count"]:
        return

    window_count = wizard_result["window_count"]
    logger.info("Wizard completed: %d window(s)", window_count)

    # ── Phase 2: Auto-generate config ─────────────────────────────
    config = _auto_generate_party_config(window_count)

    for account in config.accounts:
        logger.info(
            "Account %s: %d character(s)",
            account.id, len(account.characters),
        )

    # ── Phase 3: Scan & assign windows ────────────────────────────
    registry = WindowRegistry()
    assignment = _scan_and_assign_windows(registry, config)

    if assignment is None:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "错误",
            f"需要 {window_count} 个 PoE2 窗口，但只检测到 {len(registry.scan_windows('Path of Exile 2'))} 个。\n"
            "请确认所有窗口已打开并登录到游戏中。",
        )
        root.destroy()
        return

    hwnds = [assignment[account.id] for account in config.accounts]

    # ── Phase 4: Simple confirm dialog ────────────────────────────
    if not _simple_window_confirm(assignment, config):
        logger.info("Window assignment cancelled.")
        return

    # ── Phase 5: Logging setup ────────────────────────────────────
    log_handler = GuiLogHandler(level=logging.DEBUG)
    log_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)7s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    root_logger.addHandler(log_handler)
    root_logger.setLevel(logging.DEBUG)

    for aid, hwnd in assignment.items():
        logger.info("Account %s → HWND=%d", aid, hwnd)

    # ── Phase 6: NavAgent + callbacks ─────────────────────────────
    status_queue: queue.Queue[dict] = queue.Queue(maxsize=500)
    agent_ref: List[Optional[NavAgent]] = [None]

    config_path = str(resource_root() / "config" / "nav-follow.yaml")

    def on_start() -> None:
        agent = NavAgent(
            config=config,
            hwnds=hwnds,
            status_queue=status_queue,
            config_path=config_path,
        )
        agent_ref[0] = agent
        agent.start()

    def on_stop() -> None:
        agent = agent_ref[0]
        if agent is not None:
            agent.stop()
            agent_ref[0] = None

    def on_pause_toggle(player_key: str, paused: bool) -> None:
        agent = agent_ref[0]
        if agent is not None:
            agent.set_paused(player_key, paused)

    # ── Phase 7: Build window info ─────────────────────────────────
    window_info: Dict[str, dict] = {}
    for aid, hwnd in assignment.items():
        window_info[aid] = {"handle": hwnd}

    # ── Phase 8: Launch NavGui ────────────────────────────────────
    from src.ui.gui import NavGui

    gui = NavGui(
        status_queue=status_queue,
        log_handler=log_handler,
        party_config=config,
        account_hwnds=assignment,
        window_info=window_info,
        on_start=on_start,
        on_stop=on_stop,
        on_pause_toggle=on_pause_toggle,
    )
    gui.mainloop()


if __name__ == "__main__":
    main()
