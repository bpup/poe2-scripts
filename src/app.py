from __future__ import annotations

import queue
import logging
from typing import Optional

from src.common.config_loader import load_config
from src.common.gui_log_handler import GuiLogHandler
from src.common.logger import ROOT_LOGGER_NAME, get_logger
from src.common.runtime_paths import resource_root
from src.core.window_registry import WindowRegistry
from src.follow.nav_agent import NavAgent
from src.ui.gui import NavGui, select_windows

logger = get_logger(__name__)


def main() -> None:
    config_path = resource_root() / "config" / "nav-follow.yaml"
    config = load_config(str(config_path))

    registry = WindowRegistry()
    all_windows = registry.scan_windows("Path of Exile 2")

    if len(all_windows) < 2:
        logger.error(
            "Found only %d PoE2 window(s) — need at least 2.", len(all_windows)
        )
        return

    selection = select_windows(all_windows)
    if selection is None:
        logger.info("Window selection cancelled.")
        return

    leader_hwnd, follower_hwnds = selection

    log_handler = GuiLogHandler(level=logging.DEBUG)
    log_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)7s] %(message)s", datefmt="%H:%M:%S"
        )
    )
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.addHandler(log_handler)
    root.setLevel(logging.DEBUG)

    logger.info(
        "Leader HWND=%d, %d follower(s): %s.",
        leader_hwnd,
        len(follower_hwnds),
        follower_hwnds,
    )

    status_queue: queue.Queue[dict] = queue.Queue(maxsize=500)
    agent_ref: list[Optional[NavAgent]] = [None]

    def on_start() -> None:
        nav_config = config.nav if hasattr(config, "nav") else None
        agent = NavAgent(
            nav_config=nav_config,
            leader_hwnd=leader_hwnd,
            follower_hwnds=follower_hwnds,
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

    def on_pause_toggle(hwnd: int, paused: bool) -> None:
        agent = agent_ref[0]
        if agent is not None:
            agent.set_paused(hwnd, paused)

    gui = NavGui(
        status_queue=status_queue,
        log_handler=log_handler,
        leader_hwnd=leader_hwnd,
        leader_pid=0,
        follower_hwnds=follower_hwnds,
        follower_pids={},
        on_start=on_start,
        on_stop=on_stop,
        on_pause_toggle=on_pause_toggle,
    )
    gui.mainloop()


if __name__ == "__main__":
    main()
