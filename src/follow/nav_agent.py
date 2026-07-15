from __future__ import annotations

import queue
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

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

_FORMATION_DIAMOND = [(0, -1), (1, 0), (-1, 0), (-1, -2), (1, -2)]
_FORMATION_LINE = [(0, -1), (0, -2), (0, -3), (0, -4), (0, -5)]
_FORMATION_V = [(-1, -1), (1, -1), (-2, -2), (2, -2), (-3, -3)]

_FM = {
    "diamond": _FORMATION_DIAMOND,
    "line": _FORMATION_LINE,
    "v": _FORMATION_V,
}


class NavAgent:
    def __init__(
        self,
        nav_config: dict,
        leader_hwnd: int,
        follower_hwnds: List[int],
        status_queue: Optional[queue.Queue[dict]] = None,
    ) -> None:
        self._reader = MemoryReader(nav_config)
        self._injector = InputInjector()
        self._pathfinder = Pathfinder()
        self._registry = WindowRegistry()

        self._leader_hwnd = leader_hwnd
        self._follower_hwnds = follower_hwnds
        self._status_queue = status_queue

        self._leader_pid: Optional[int] = None
        self._follower_pids: Dict[int, int] = {}
        self._follower_indices: Dict[int, int] = {}

        self._held_keys: Dict[int, Set[str]] = {}
        self._last_positions: Dict[int, EntityPosition] = {}

        behavior = nav_config.get("behavior", {})
        self._formation = behavior.get("formation", {})
        self._anti_stuck = behavior.get("anti_stuck", {})

        self._stuck_counters: Dict[int, int] = {}
        self._stuck_levels: Dict[int, int] = {}
        self._reverse_remaining: Dict[int, int] = {}

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._resolve_pids()
        self._build_follower_indices()

        if self._leader_pid is None:
            logger.error("Leader PID not found.")
            self._running = False
            return
        if not self._follower_pids:
            logger.error("No follower PIDs found.")
            self._running = False
            return

        logger.info(
            "NavAgent started: leader PID=%d, %d followers.",
            self._leader_pid,
            len(self._follower_pids),
        )

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._emit_state("Stopped.")
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._emergency_stop()
        self._reader.close_all()

    def _run(self) -> None:
        try:
            while self._running:
                self._tick()
                time.sleep(TICK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("NavAgent interrupted.")
        finally:
            self._emergency_stop()
            self._reader.close_all()
            self._emit_state("Disconnected.")

    def _tick(self) -> None:
        leader_proc = self._reader.open_process(self._leader_pid)
        if leader_proc is None:
            return

        leader_pos = self._reader.read_local_player_position(leader_proc)
        if leader_pos is None:
            return

        self._emit_leader(leader_pos)

        follower_data: List[dict] = []
        for hwnd, pid in self._follower_pids.items():
            proc = self._reader.open_process(pid)
            if proc is None:
                continue

            follower_pos = self._reader.read_local_player_position(proc)
            if follower_pos is None:
                continue

            formation_target = self._apply_formation_offset(
                hwnd, leader_pos.x, leader_pos.y
            )
            wasd = self._compute_wasd(
                hwnd, formation_target, follower_pos, leader_pos
            )
            self._apply_keys(hwnd, wasd)

            idx = self._follower_indices.get(hwnd, 0)
            follower_data.append({
                "hwnd": hwnd,
                "pid": pid,
                "index": idx,
                "pos": follower_pos,
                "fmt_target": formation_target,
                "stuck_level": self._stuck_levels.get(hwnd, 0),
                "stuck_counter": self._stuck_counters.get(hwnd, 0),
                "reverse_remaining": self._reverse_remaining.get(hwnd, 0),
                "wasd": "".join(sorted(wasd)) if wasd else "",
            })

        if follower_data:
            self._emit_status("followers", follower_data)

    def _compute_wasd(
        self,
        hwnd: int,
        target: Tuple[float, float],
        follower: EntityPosition,
        leader: EntityPosition,
    ) -> Set[str]:
        anti_stuck = self._check_anti_stuck(hwnd, follower, leader, target)
        if anti_stuck is not None:
            return anti_stuck

        dx = target[0] - follower.x
        dy = follower.y - target[1]
        dist = (dx * dx + dy * dy) ** 0.5

        if dist < 1.0:
            return set()

        return self._pathfinder.to_wasd(
            follower.x, follower.y, target[0], target[1],
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

    def _build_follower_indices(self) -> None:
        for index, hwnd in enumerate(self._follower_hwnds):
            if hwnd in self._follower_pids:
                self._follower_indices[hwnd] = index

    def _apply_formation_offset(
        self, hwnd: int, leader_x: float, leader_y: float
    ) -> Tuple[float, float]:
        index = self._follower_indices.get(hwnd, 0)
        fm_type = self._formation.get("type", "diamond")
        offsets = _FM.get(fm_type, _FORMATION_DIAMOND)
        if index >= len(offsets):
            index = 0
        ox, oy = offsets[index]
        spacing = float(self._formation.get("spacing", 35.0))
        return (leader_x + ox * spacing, leader_y + oy * spacing)

    def _check_anti_stuck(
        self,
        hwnd: int,
        follower: EntityPosition,
        leader: EntityPosition,
        target: Tuple[float, float],
    ) -> Optional[Set[str]]:
        if not self._anti_stuck.get("enabled", True):
            return None

        prev = self._last_positions.get(hwnd)
        if prev is None:
            self._last_positions[hwnd] = follower
            return None

        threshold = float(self._anti_stuck.get("distance_threshold", 2.0))
        dx = follower.x - prev.x
        dy = follower.y - prev.y
        moved = (dx * dx + dy * dy) ** 0.5
        self._last_positions[hwnd] = follower

        if moved > threshold:
            self._stuck_counters[hwnd] = 0
            self._stuck_levels[hwnd] = 0
            self._reverse_remaining[hwnd] = 0
            return None

        self._stuck_counters[hwnd] = self._stuck_counters.get(hwnd, 0) + 1
        stuck_ticks = self._anti_stuck.get("stuck_ticks", 10)

        if self._stuck_counters[hwnd] < stuck_ticks:
            return None

        level = self._stuck_levels.get(hwnd, 0)

        if level == 0:
            self._stuck_levels[hwnd] = 1
            self._stuck_counters[hwnd] = 0
            jump_key = self._anti_stuck.get("jump_key", "SPACE")
            return {jump_key}

        if level == 1:
            self._stuck_levels[hwnd] = 2
            self._stuck_counters[hwnd] = 0
            skill_key = self._anti_stuck.get("skill_key", "Q")
            return {skill_key}

        if level == 2:
            self._stuck_levels[hwnd] = 3
            self._stuck_counters[hwnd] = 0
            self._reverse_remaining[hwnd] = self._anti_stuck.get(
                "reverse_duration_ticks", 8
            )

        rev = self._reverse_remaining.get(hwnd, 0)
        if rev > 0:
            self._reverse_remaining[hwnd] = rev - 1
            rx = follower.x * 2 - target[0]
            ry = follower.y * 2 - target[1]
            return self._pathfinder.to_wasd(follower.x, follower.y, rx, ry)

        cooldown = self._anti_stuck.get("reverse_cooldown_ticks", 30)
        if self._stuck_counters[hwnd] > cooldown:
            self._stuck_counters[hwnd] = 0
            self._stuck_levels[hwnd] = 0
        return None

    def _emergency_stop(self) -> None:
        for hwnd in list(self._held_keys.keys()):
            self._injector.release_all(hwnd, self._held_keys.get(hwnd, set()))
        self._held_keys.clear()
        logger.warning("NavAgent emergency stop — all keys released.")

    def _emit_status(self, msg_type: str, data: Any = None) -> None:
        if self._status_queue is None:
            return
        try:
            self._status_queue.put_nowait({"type": msg_type, "data": data} if data is not None else {"type": msg_type})
        except queue.Full:
            pass

    def _emit_state(self, text: str) -> None:
        if self._status_queue is None:
            return
        try:
            self._status_queue.put_nowait({"type": "state", "text": text})
        except queue.Full:
            pass

    def _emit_leader(self, pos: EntityPosition) -> None:
        if self._status_queue is None:
            return
        try:
            self._status_queue.put_nowait({"type": "leader", "pos": pos})
        except queue.Full:
            pass
