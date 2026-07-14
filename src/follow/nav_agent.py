from __future__ import annotations

import time
from typing import Dict, List, Optional, Set, Tuple

from src.common.logger import get_logger
from src.core.input_injector import InputInjector
from src.core.memory_reader import EntityPosition, GameProcess, MemoryReader
from src.core.pathfinder import Pathfinder
from src.core.window_registry import WindowRegistry
from src.core.window_registry import WindowStatus as WinStatus

logger = get_logger(__name__)

TICK_INTERVAL = 0.05
STUCK_THRESHOLD = 5.0
STUCK_STEPS = 5
UNSTUCK_VECTORS = [
    (1.0, 0.0),
    (-1.0, 0.0),
    (0.0, -1.0),
    (0.0, 1.0),
]


class NavAgent:
    def __init__(
        self,
        offset_config: dict,
        leader_hwnd: int,
        follower_hwnds: List[int],
    ) -> None:
        self._reader = MemoryReader(offset_config)
        self._injector = InputInjector()
        self._pathfinder = Pathfinder()
        self._registry = WindowRegistry()

        self._leader_hwnd = leader_hwnd
        self._follower_hwnds = follower_hwnds

        self._leader_pid: Optional[int] = None
        self._follower_pids: Dict[int, int] = {}

        self._held_keys: Dict[int, Set[str]] = {}
        self._last_positions: Dict[int, EntityPosition] = {}

        self._running = False

    def start(self) -> None:
        self._running = True
        self._resolve_pids()

        if self._leader_pid is None:
            logger.error("Leader PID not found.")
            return
        if not self._follower_pids:
            logger.error("No follower PIDs found.")
            return

        logger.info(
            "NavAgent started: leader PID=%d, %d followers.",
            self._leader_pid,
            len(self._follower_pids),
        )

        try:
            while self._running:
                self._tick()
                time.sleep(TICK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("NavAgent interrupted.")
        finally:
            self._emergency_stop()
            self._reader.close_all()

    def stop(self) -> None:
        self._running = False

    def _tick(self) -> None:
        leader_proc = self._reader.open_process(self._leader_pid)
        if leader_proc is None:
            return

        leader_pos = self._reader.read_local_player_position(leader_proc)
        if leader_pos is None:
            return

        for hwnd, pid in self._follower_pids.items():
            proc = self._reader.open_process(pid)
            if proc is None:
                continue

            follower_pos = self._reader.read_local_player_position(proc)
            if follower_pos is None:
                continue

            wasd = self._compute_wasd(hwnd, leader_pos, follower_pos)
            self._apply_keys(hwnd, wasd)

    def _compute_wasd(
        self,
        hwnd: int,
        leader: EntityPosition,
        follower: EntityPosition,
    ) -> Set[str]:
        dx = leader.x - follower.x
        dy = follower.y - leader.y  # y-axis inverted in PoE (north = -y)
        dist = (dx * dx + dy * dy) ** 0.5

        if dist < 1.0:
            return set()

        return self._pathfinder.to_wasd(
            follower.x,
            follower.y,
            leader.x,
            leader.y,
        )

    def _apply_keys(self, hwnd: int, desired: Set[str]) -> None:
        current = self._held_keys.get(hwnd, set())
        to_release = current - desired
        to_press = desired - current

        for key in to_release:
            self._injector.release(hwnd, key)
        for key in to_press:
            self._injector.press(hwnd, key)

        self._held_keys[hwnd] = desired

    def _resolve_pids(self) -> None:
        all_pids = self._reader.find_poe2_processes()
        hwnd_to_pid: Dict[int, int] = {}

        for pid in all_pids:
            proc_handle = self._reader._get_module_base
            for hwnd in [self._leader_hwnd] + self._follower_hwnds:
                if hwnd in hwnd_to_pid:
                    continue
                try:
                    import win32process

                    _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                    if found_pid == pid:
                        hwnd_to_pid[hwnd] = pid
                        break
                except Exception:
                    pass

        self._leader_pid = hwnd_to_pid.get(self._leader_hwnd)
        for hwnd in self._follower_hwnds:
            if hwnd in hwnd_to_pid:
                self._follower_pids[hwnd] = hwnd_to_pid[hwnd]
            else:
                logger.warning("No PoE2 process found for HWND %d.", hwnd)

    def _emergency_stop(self) -> None:
        for hwnd in list(self._held_keys.keys()):
            self._injector.release_all(hwnd, self._held_keys.get(hwnd, set()))
        self._held_keys.clear()
        logger.warning("NavAgent emergency stop — all keys released.")
