import time
from typing import Dict

from src.common.logger import get_logger
from src.core.party_state import PartyRuntimeState, RunMode

logger = get_logger(__name__)


class RegroupController:
    def __init__(
        self,
        state: PartyRuntimeState,
        max_drift_ticks: int = 10,
        regroup_cooldown_ms: int = 3000,
        max_regroup_attempts: int = 3,
    ):
        self._state = state
        self._max_drift_ticks = max_drift_ticks
        self._regroup_cooldown_ms = regroup_cooldown_ms
        self._max_regroup_attempts = max_regroup_attempts

    def evaluate(self, missed_ticks: int) -> None:
        if self._state.mode == RunMode.SAFE_PAUSE:
            return

        if self._state.mode == RunMode.REGROUP:
            self._handle_regroup_phase()
            return

        self._check_drift_failures()

        if missed_ticks >= 3:
            logger.warning(
                "Leader sampling interrupted (%d missed ticks) — safe pause.",
                missed_ticks,
            )
            self._state.fail_regroup(
                f"Leader sample missed for {missed_ticks} consecutive ticks."
            )
            return

        if missed_ticks >= 2:
            logger.warning(
                "Leader sampling degraded (%d missed ticks).", missed_ticks
            )

    def _check_drift_failures(self) -> None:
        to_pause: list[str] = []
        for role_id in list(self._state.active_followers):
            if self._state.is_excessively_drifting(role_id, self._max_drift_ticks):
                to_pause.append(role_id)

        if not to_pause:
            return

        for role_id in to_pause:
            logger.warning(
                "Follower '%s' exceeded max drift ticks (%d) — pausing.",
                role_id,
                self._max_drift_ticks,
            )
            self._state.active_followers.remove(role_id)
            self._state.paused_followers.append(role_id)

        active_count = len(self._state.active_followers)
        if active_count == 0:
            self._state.fail_regroup("All followers drifted — safe pause.")
            return

        if len(to_pause) >= 3:
            self._try_regroup(
                f"{len(to_pause)} followers drifting excessively."
            )
        else:
            self._try_regroup(
                f"Paused {len(to_pause)} follower(s) due to drift."
            )

    def _try_regroup(self, reason: str) -> bool:
        if self._state._regroup_attempts >= self._max_regroup_attempts:
            self._state.fail_regroup(
                f"Max regroup attempts ({self._max_regroup_attempts}) exceeded: {reason}"
            )
            return False

        return self._state.request_regroup(reason, self._regroup_cooldown_ms)

    def _handle_regroup_phase(self) -> None:
        elapsed_ms = (time.time() - self._state._last_regroup_at) * 1000
        grace_period_ms = 5000

        if elapsed_ms < grace_period_ms:
            return

        self._attempt_recovery()

    def _attempt_recovery(self) -> None:
        recovered: list[str] = []

        for role_id in list(self._state.paused_followers):
            self._state.clear_drift(role_id)
            self._state.paused_followers.remove(role_id)
            self._state.active_followers.append(role_id)
            recovered.append(role_id)
            logger.info("Follower '%s' recovered from regroup.", role_id)

        if self._state.paused_followers or not self._state.active_followers:
            self._state.fail_regroup(
                "Unable to recover all followers during regroup."
            )
            return

        if recovered:
            self._state.transition_to(
                RunMode.RUNNING,
                f"Recovered {len(recovered)} follower(s) from regroup.",
            )
