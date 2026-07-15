from __future__ import annotations

from pathlib import Path

from src.common.config_loader import load_config
from src.common.logger import get_logger, setup_logging
from src.core.window_registry import WindowRegistry
from src.follow.nav_agent import NavAgent

logger = get_logger(__name__)


def main() -> None:
    setup_logging()

    project_root = Path(__file__).resolve().parent.parent
    default_config = project_root / "config" / "nav-follow.yaml"
    config_path = default_config

    config = load_config(str(config_path))

    registry = WindowRegistry()
    all_windows = registry.scan_windows("Path of Exile 2")

    if len(all_windows) < 2:
        logger.error(
            "Found only %d PoE2 window(s) — need at least 2.", len(all_windows)
        )
        return

    leader_hwnd = all_windows[0]
    follower_hwnds = all_windows[1:]

    logger.info(
        "Nav mode: leader HWND=%d, %d follower(s): %s.",
        leader_hwnd,
        len(follower_hwnds),
        follower_hwnds,
    )

    offset_config = config.nav.offsets if hasattr(config, "nav") else {}
    agent = NavAgent(
        offset_config=offset_config,
        leader_hwnd=leader_hwnd,
        follower_hwnds=follower_hwnds,
    )
    agent.start()


if __name__ == "__main__":
    main()
