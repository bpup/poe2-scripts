import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)

FollowerCallback = Callable[["LeaderSample"], Awaitable[None]]
SamplerCallback = Callable[[], Optional["LeaderSample"]]


@dataclass
class LeaderSample:
    tick_id: int = 0
    captured_at: float = 0.0
    movement_x: float = 0.0
    movement_y: float = 0.0
    is_moving: bool = False
    heading: float = 0.0
    event: str = "stop"
    source: str = "keyboard"


class TickBus:
    def __init__(self, tick_interval_ms: int = 50):
        self.tick_interval_ms = tick_interval_ms
        self._tick_counter: int = 0
        self._running: bool = False
        self._sampler: Optional[SamplerCallback] = None
        self._followers: Dict[str, FollowerCallback] = {}
        self._last_sample: Optional[LeaderSample] = None
        self._missed_ticks: int = 0

    def set_sampler(self, callback: SamplerCallback) -> None:
        self._sampler = callback

    def register_follower(self, role_id: str, callback: FollowerCallback) -> None:
        self._followers[role_id] = callback
        logger.debug("Registered follower '%s' on tick bus.", role_id)

    def unregister_follower(self, role_id: str) -> None:
        self._followers.pop(role_id, None)
        logger.debug("Unregistered follower '%s' from tick bus.", role_id)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def missed_ticks(self) -> int:
        return self._missed_ticks

    async def start(self) -> None:
        self._running = True
        self._tick_counter = 0
        self._missed_ticks = 0
        logger.info(
            "TickBus started (interval=%dms).", self.tick_interval_ms
        )
        await self._tick_loop()

    async def stop(self) -> None:
        self._running = False
        logger.info("TickBus stopped (final tick=%d).", self._tick_counter)

    async def _tick_loop(self) -> None:
        sleep_sec = self.tick_interval_ms / 1000.0

        while self._running:
            await asyncio.sleep(sleep_sec)
            self._tick_counter += 1

            if self._sampler is None:
                continue

            sample = self._sampler()

            if sample is None:
                self._missed_ticks += 1
                if self._missed_ticks >= 2:
                    logger.warning(
                        "Tick %d: %d consecutive missed samples.",
                        self._tick_counter,
                        self._missed_ticks,
                    )
                continue

            self._missed_ticks = 0
            sample.tick_id = self._tick_counter
            sample.captured_at = time.time()
            self._last_sample = sample

            if not self._followers:
                continue

            tasks = [
                callback(sample) for callback in self._followers.values()
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
