import time
from dataclasses import dataclass
from typing import Dict, Set

from src.common.logger import get_logger
from src.core.input_injector import InputInjector
from src.core.party_state import PartyRuntimeState, RunMode, WindowStatus
from src.core.tick_bus import LeaderSample

logger = get_logger(__name__)


@dataclass
class FollowerCommand:
    tick_id: int = 0
    role_id: str = ""
    action: str = "pause"
    movement_x: float = 0.0
    movement_y: float = 0.0
    hold_ms: int = 0
    reason: str = ""


class FollowerExecutor:
    def __init__(self, state: PartyRuntimeState, max_lag_ms: int = 200):
        self._state = state
        self._max_lag_ms = max_lag_ms
        self._injector = InputInjector()
        self._held_keys: Dict[str, Set[str]] = {}
        self._last_command_time: Dict[str, float] = {}

        for follower_role in self._state._bindings:
            if follower_role == self._state.leader_role_id:
                continue
            self._held_keys[follower_role] = set()
            self._last_command_time[follower_role] = 0.0

    def execute(self, sample: LeaderSample) -> None:
        active = list(self._state.active_followers)
        for role_id in active:
            self._execute_one(role_id, sample)

        paused = list(self._state.paused_followers)
        for role_id in paused:
            binding = self._state.get_binding(role_id)
            if binding is not None:
                try:
                    hwnd = int(binding.handle)
                    self._release_all(role_id, hwnd)
                except (ValueError, TypeError):
                    self._held_keys.pop(role_id, None)

    def _execute_one(self, role_id: str, sample: LeaderSample) -> None:
        if self._state.mode != RunMode.RUNNING:
            return

        binding = self._state.get_binding(role_id)
        if binding is None or binding.status != WindowStatus.READY:
            self._state.record_drift(role_id)
            return

        try:
            hwnd = int(binding.handle)
        except (ValueError, TypeError):
            self._state.record_drift(role_id)
            return

        now = time.time()
        cmd_time = self._last_command_time.get(role_id, 0.0)
        lag_ms = (now - cmd_time) * 1000

        if lag_ms > self._max_lag_ms:
            logger.warning("Follower '%s' lagging %dms — pausing commands.", role_id, int(lag_ms))
            self._state.record_drift(role_id)
            self._release_all(role_id, hwnd)
            return

        self._last_command_time[role_id] = now

        if sample.is_moving:
            self._press_movement(role_id, hwnd, sample.movement_x, sample.movement_y)
        else:
            self._release_all(role_id, hwnd)

        self._state.clear_drift(role_id)

    def _press_movement(self, role_id: str, hwnd: int, mx: float, my: float) -> None:
        desired = self._vector_to_keys(mx, my)
        current = self._held_keys.get(role_id, set())

        to_release = current - desired
        to_press = desired - current

        for key in to_release:
            self._injector.release(hwnd, key)

        for key in to_press:
            self._injector.press(hwnd, key)

        self._held_keys[role_id] = desired

    def _release_all(self, role_id: str, hwnd: int) -> None:
        current = self._held_keys.get(role_id, set())
        if current:
            self._injector.release_all(hwnd, current)
        self._held_keys[role_id] = set()

    @staticmethod
    def _vector_to_keys(mx: float, my: float) -> Set[str]:
        keys: Set[str] = set()
        threshold = 0.25

        if mx > threshold:
            keys.add("d")
        elif mx < -threshold:
            keys.add("a")

        if my < -threshold:
            keys.add("w")
        elif my > threshold:
            keys.add("s")

        return keys

    def emergency_stop(self) -> None:
        for role_id, keys in list(self._held_keys.items()):
            if not keys:
                continue
            binding = self._state.get_binding(role_id)
            if binding is not None:
                try:
                    hwnd = int(binding.handle)
                    self._injector.release_all(hwnd, keys)
                except (ValueError, TypeError):
                    pass
        self._held_keys.clear()
        logger.warning("Emergency stop — all follower keys released.")
