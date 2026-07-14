import asyncio
import signal
import sys
import time
from pathlib import Path

from src.common.config_loader import load_config
from src.common.logger import setup_logging, get_logger
from src.core.party_state import PartyRuntimeState, RunMode, WindowBinding, WindowStatus
from src.core.tick_bus import TickBus
from src.core.window_registry import WindowRegistry
from src.follow.follower_executor import FollowerExecutor
from src.follow.leader_sampler import LeaderSampler
from src.follow.nav_agent import NavAgent
from src.follow.regroup_controller import RegroupController

logger = get_logger(__name__)


class Poe2FollowApp:
    def __init__(self, config_path: str):
        self._config = load_config(config_path)
        self._state = PartyRuntimeState()
        self._registry = WindowRegistry()
        self._tick_bus = TickBus(tick_interval_ms=self._config.sampling.tick_ms)
        self._sampler = LeaderSampler(
            turn_threshold=self._config.sampling.turn_threshold
        )
        self._executor: FollowerExecutor | None = None
        self._regroup: RegroupController | None = None
        self._shutdown_requested = False

    def _bind_all_windows(self) -> bool:
        leader = self._config.leader

        # Scan once — bind_window uses index from this single scan result
        # to avoid inconsistent ordering across multiple scan calls.
        all_windows = self._registry.scan_windows("Path of Exile 2")

        self._registry.bind_window(
            role_id=leader.role_id,
            role_type="leader",
            window_title="Path of Exile 2",
            windows=all_windows,
            window_index=0,
        )

        for idx, follower in enumerate(self._config.followers, start=1):
            self._registry.bind_window(
                role_id=follower.role_id,
                role_type="follower",
                window_title=follower.window_title,
                windows=all_windows,
                window_index=idx,
            )

        for rid, binding in self._registry._bindings.items():
            if binding.status == WindowStatus.MISSING:
                logger.warning(
                    "Window '%s' (role '%s') not found — continuing anyway.",
                    binding.window_title,
                    rid,
                )

        leader_binding = self._registry._bindings.get(leader.role_id)
        if leader_binding is None or leader_binding.status == WindowStatus.MISSING:
            logger.error(
                "Leader window '%s' not found. Check window title and ensure PoE2 is running.",
                leader.role_id,
            )
            return False

        expected_followers = len(self._config.followers)
        follower_count = sum(
            1
            for rid, b in self._registry._bindings.items()
            if rid != leader.role_id and b.status == WindowStatus.READY
        )
        logger.info(
            "Leader bound. %d/%d follower window(s) found.",
            follower_count,
            expected_followers,
        )

        return True

    async def _health_monitor(self) -> None:
        while not self._shutdown_requested:
            await asyncio.sleep(2.0)

            statuses = self._registry.check_all_health()
            for role_id, status in statuses.items():
                binding = self._registry._bindings.get(role_id)
                if binding is None:
                    continue

                if status == WindowStatus.MISSING and binding.status == WindowStatus.READY:
                    binding.status = WindowStatus.MISSING
                    self._state.bind(binding)
                    logger.warning(
                        "Window lost for role '%s' (health check failed).",
                        role_id,
                    )
                elif status == WindowStatus.READY and binding.status == WindowStatus.MISSING:
                    binding.status = WindowStatus.READY
                    self._state.bind(binding)
                    logger.info(
                        "Window recovered for role '%s'.", role_id
                    )

            if not self._state.leader_binding_healthy():
                self._state.fail_regroup("Leader window lost.")
                await self._shutdown()

    async def _shutdown(self) -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True

        logger.info("Shutting down...")
        self._sampler.stop()

        if self._executor is not None:
            self._executor.emergency_stop()

        await self._tick_bus.stop()

    async def run(self) -> None:
        total = 1 + len(self._config.followers)
        logger.info("=== PoE2 %d-Client Auto-Follow ===", total)
        logger.info(
            "Leader: %s (%dms tick, %.1f° turn threshold)",
            self._config.leader.role_id,
            self._config.sampling.tick_ms,
            self._config.sampling.turn_threshold,
        )
        logger.info(
            "Followers: %s",
            ", ".join(f.role_id for f in self._config.followers),
        )
        logger.info("---")

        if not self._bind_all_windows():
            logger.error("Failed to bind leader window. Exiting.")
            return

        for rid, binding in self._registry._bindings.items():
            self._state.bind(binding)

        self._state.active_followers = [
            f.role_id
            for f in self._config.followers
            if f.role_id in self._registry._bindings
        ]

        self._executor = FollowerExecutor(
            state=self._state,
            max_lag_ms=self._config.runtime.max_follower_lag_ms,
        )

        self._regroup = RegroupController(
            state=self._state,
            max_drift_ticks=self._config.runtime.max_drift_ticks,
            regroup_cooldown_ms=self._config.runtime.regroup_cooldown_ms,
        )

        async def follower_dispatch(sample):
            if self._state.mode == RunMode.RUNNING:
                self._executor.execute(sample)

        for role_id in self._state.active_followers:
            self._tick_bus.register_follower(role_id, follower_dispatch)

        self._tick_bus.set_sampler(self._sampler.sample)

        self._sampler.start()
        self._state.transition_to(RunMode.RUNNING, "System initialized.")

        loop = asyncio.get_running_loop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self._shutdown()))

        health_task = asyncio.create_task(self._health_monitor())
        tick_task = asyncio.create_task(self._tick_bus.start())
        monitor_task = asyncio.create_task(self._run_monitor())

        try:
            done, pending = await asyncio.wait(
                [health_task, tick_task, monitor_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

        logger.info("=== Session ended ===")

    async def _run_monitor(self) -> None:
        while not self._shutdown_requested:
            await asyncio.sleep(1.0)

            if self._regroup is not None:
                self._regroup.evaluate(self._tick_bus.missed_ticks)

            if self._state.mode == RunMode.SAFE_PAUSE:
                logger.warning(
                    "SAFE_PAUSE active — last error: %s",
                    self._state.last_error or "unknown",
                )


def main_nav():
    project_root = Path(__file__).resolve().parent.parent
    default_config = project_root / "config" / "nav-follow.yaml"
    config_path = sys.argv[1] if len(sys.argv) > 1 else str(default_config)

    setup_logging()
    config = load_config(config_path)

    registry = WindowRegistry()
    all_windows = registry.scan_windows("Path of Exile 2")

    if len(all_windows) < 2:
        logger.error("Found only %d PoE2 window(s) — need at least 2.", len(all_windows))
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


def main():
    if "--nav" in sys.argv:
        sys.argv.remove("--nav")
        main_nav()
        return

    project_root = Path(__file__).resolve().parent.parent
    default_config = project_root / "config" / "party-six-follow.yaml"
    config_path = sys.argv[1] if len(sys.argv) > 1 else str(default_config)

    setup_logging()
    app = Poe2FollowApp(config_path)
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
