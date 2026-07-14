import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


class RunMode(Enum):
    IDLE = "idle"
    RUNNING = "running"
    REGROUP = "regroup"
    SAFE_PAUSE = "safe_pause"


class WindowStatus(Enum):
    READY = "ready"
    MISSING = "missing"
    MISMATCH = "mismatch"


@dataclass
class WindowBinding:
    role_id: str
    role_type: str
    window_title: str
    handle: str = ""
    width: int = 0
    height: int = 0
    scale: float = 1.0
    status: WindowStatus = WindowStatus.MISSING


@dataclass
class PartyRuntimeState:
    mode: RunMode = RunMode.IDLE
    leader_role_id: str = ""
    active_followers: List[str] = field(default_factory=list)
    paused_followers: List[str] = field(default_factory=list)
    last_healthy_tick_id: int = 0
    last_error: Optional[str] = None
    _bindings: Dict[str, WindowBinding] = field(default_factory=dict)
    _drift_counters: Dict[str, int] = field(default_factory=dict)
    _last_regroup_at: float = 0.0
    _regroup_attempts: int = 0

    def bind(self, binding: WindowBinding) -> None:
        self._bindings[binding.role_id] = binding
        if binding.role_type == "leader":
            self.leader_role_id = binding.role_id
        status_tag = binding.status.value
        logger.info(
            "Bound %s '%s' (handle=%s, status=%s)",
            binding.role_type,
            binding.role_id,
            binding.handle,
            status_tag,
        )

    def unbind(self, role_id: str) -> None:
        removed = self._bindings.pop(role_id, None)
        if removed is None:
            return
        if role_id == self.leader_role_id:
            logger.warning("Leader '%s' unbound — clearing leader_role_id.", role_id)
            self.leader_role_id = ""
        logger.info("Unbound role '%s'.", role_id)

    def get_binding(self, role_id: str) -> Optional[WindowBinding]:
        return self._bindings.get(role_id)

    def all_bindings_ready(self) -> bool:
        if not self.leader_role_id:
            return False
        leader = self._bindings.get(self.leader_role_id)
        if leader is None or leader.status != WindowStatus.READY:
            return False
        follower_bindings = [
            b
            for rid, b in self._bindings.items()
            if rid != self.leader_role_id
        ]
        if not follower_bindings:
            return False
        return all(b.status == WindowStatus.READY for b in follower_bindings)

    def leader_binding_healthy(self) -> bool:
        if not self.leader_role_id:
            return False
        binding = self._bindings.get(self.leader_role_id)
        return binding is not None and binding.status == WindowStatus.READY

    def transition_to(self, new_mode: RunMode, reason: str = "") -> None:
        if self.mode == new_mode:
            return

        old_mode = self.mode
        self.mode = new_mode

        if new_mode == RunMode.SAFE_PAUSE:
            self.last_error = reason
            logger.error(
                "Transition %s -> SAFE_PAUSE: %s", old_mode.value, reason
            )
        elif new_mode == RunMode.REGROUP:
            self._regroup_attempts += 1
            self._last_regroup_at = time.time()
            logger.info(
                "Transition %s -> REGROUP (attempt %d): %s",
                old_mode.value,
                self._regroup_attempts,
                reason,
            )
        elif new_mode == RunMode.RUNNING:
            if not self.all_bindings_ready():
                logger.warning(
                    "Entering RUNNING but not all bindings are ready."
                )
            self.last_error = None
            self._regroup_attempts = 0
            logger.info(
                "Transition %s -> RUNNING: %s", old_mode.value, reason
            )
        else:
            logger.info(
                "Transition %s -> %s: %s", old_mode.value, new_mode.value, reason
            )

    def request_regroup(
        self, reason: str = "", cooldown_ms: int = 3000
    ) -> bool:
        if self.mode == RunMode.SAFE_PAUSE:
            return False
        if self.mode == RunMode.REGROUP:
            return False

        elapsed_ms = (time.time() - self._last_regroup_at) * 1000
        if elapsed_ms < cooldown_ms:
            return False

        self.transition_to(RunMode.REGROUP, reason)
        return True

    def fail_regroup(self, reason: str = "") -> None:
        self.transition_to(RunMode.SAFE_PAUSE, reason)

    def record_drift(self, role_id: str) -> None:
        current = self._drift_counters.get(role_id, 0)
        self._drift_counters[role_id] = current + 1

    def clear_drift(self, role_id: str) -> None:
        self._drift_counters[role_id] = 0

    def is_excessively_drifting(self, role_id: str, max_ticks: int) -> bool:
        return self._drift_counters.get(role_id, 0) >= max_ticks

    def is_running(self) -> bool:
        return self.mode == RunMode.RUNNING

    def is_degraded(self) -> bool:
        return self.mode in (RunMode.REGROUP, RunMode.SAFE_PAUSE)
