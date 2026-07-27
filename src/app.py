from __future__ import annotations

import logging
import queue
from typing import Optional

from src.common.config_loader import PartyConfig, load_config
from src.common.gui_log_handler import GuiLogHandler
from src.common.logger import ROOT_LOGGER_NAME, get_logger
from src.common.runtime_paths import resource_root
from src.core.memory_reader import MemoryReader
from src.core.window_registry import WindowRegistry
from src.follow.nav_agent import NavAgent
from src.ui.gui import NavGui, select_windows

try:
    import win32process
except ImportError:
    win32process = None

logger = get_logger(__name__)


def main() -> None:
    config_path = resource_root() / "config" / "nav-follow.yaml"
    config: PartyConfig = load_config(str(config_path))

    registry = WindowRegistry()
    all_windows = registry.scan_windows("Path of Exile 2")

    # ── Enrich windows with P1 character info ────────────────────
    if win32process is not None:
        reader = MemoryReader(config.nav or {})
        poe_pids = set(reader.find_poe2_processes())
        for win in all_windows:
            hwnd = int(win["handle"])
            try:
                _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                win_pid = 0
            win["pid"] = win_pid

            if win_pid and win_pid in poe_pids:
                proc = reader.open_process(win_pid)
                if proc:
                    result = reader.read_local_player_position(proc)
                    if result:
                        _, entity = result
                        ci = reader.read_character_info(proc, entity)
                        if ci:
                            win["char_name"] = ci.name
                            win["char_class"] = ci.class_name
                            win["char_level"] = ci.level

        reader.close_all()

    if len(all_windows) < len(config.accounts):
        logger.error(
            "Found %d PoE2 window(s) — need at least %d for %d account(s).",
            len(all_windows), len(config.accounts), len(config.accounts),
        )
        return

    # ── Account → HWND mapping dialog ────────────────────────────
    selection = select_windows(all_windows, config.accounts)
    if selection is None:
        logger.info("Window selection cancelled.")
        return

    # Build hwnds list in account order (matches config.accounts order)
    hwnds = [selection[account.id] for account in config.accounts]

    # ── Logging setup ────────────────────────────────────────────
    log_handler = GuiLogHandler(level=logging.DEBUG)
    log_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)7s] %(message)s", datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.addHandler(log_handler)
    root.setLevel(logging.DEBUG)

    for aid, hwnd in selection.items():
        logger.info("Account %s → HWND=%d", aid, hwnd)

    # ── NavAgent + callbacks ──────────────────────────────────────
    status_queue: queue.Queue[dict] = queue.Queue(maxsize=500)
    agent_ref: list[Optional[NavAgent]] = [None]

    def on_start() -> None:
        agent = NavAgent(
            config=config,
            hwnds=hwnds,
            status_queue=status_queue,
            config_path=str(config_path),
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

    # ── Window info for GUI ──────────────────────────────────────
    hwnd_to_info = {int(w["handle"]): w for w in all_windows}
    window_info: dict[str, dict] = {}
    for aid, hwnd in selection.items():
        window_info[aid] = hwnd_to_info.get(hwnd, {})

    # ── Launch GUI ───────────────────────────────────────────────
    gui = NavGui(
        status_queue=status_queue,
        log_handler=log_handler,
        party_config=config,
        account_hwnds=selection,
        window_info=window_info,
        on_start=on_start,
        on_stop=on_stop,
        on_pause_toggle=on_pause_toggle,
    )
    gui.mainloop()


if __name__ == "__main__":
    main()
