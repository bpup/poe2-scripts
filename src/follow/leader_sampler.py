import time
from threading import Lock
from typing import Optional, Set

from pynput.keyboard import Key, Listener

from src.common.logger import get_logger
from src.core.tick_bus import LeaderSample

logger = get_logger(__name__)

MOVE_KEYS: Set[str] = {"w", "a", "s", "d", "up", "down", "left", "right"}

_DIRECTION_MAP = {
    "w": (0.0, -1.0),
    "s": (0.0, 1.0),
    "a": (-1.0, 0.0),
    "d": (1.0, 0.0),
    "up": (0.0, -1.0),
    "down": (0.0, 1.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
}

_KEY_HEADING = {
    "w": 0.0,
    "s": 180.0,
    "a": 270.0,
    "d": 90.0,
    "up": 0.0,
    "down": 180.0,
    "left": 270.0,
    "right": 90.0,
}


class LeaderSampler:
    def __init__(self, turn_threshold: float = 15.0):
        self._turn_threshold = turn_threshold
        self._pressed: Set[str] = set()
        self._lock = Lock()
        self._last_heading: float = 0.0
        self._was_moving: bool = False
        self._listener: Optional[Listener] = None

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.start()
        logger.info("LeaderSampler started (turn_threshold=%.1f°).", self._turn_threshold)

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        logger.info("LeaderSampler stopped.")

    def _on_press(self, key) -> None:
        key_str = self._key_to_str(key)
        if key_str is None:
            return
        with self._lock:
            self._pressed.add(key_str)

    def _on_release(self, key) -> None:
        key_str = self._key_to_str(key)
        if key_str is None:
            return
        with self._lock:
            self._pressed.discard(key_str)

    @staticmethod
    def _key_to_str(key) -> Optional[str]:
        try:
            name = key.char.lower()
            return name if name in MOVE_KEYS else None
        except AttributeError:
            name = key.name
            return name if name in MOVE_KEYS else None

    def _compute_movement(self) -> tuple:
        with self._lock:
            active = self._pressed & MOVE_KEYS

        if not active:
            return 0.0, 0.0

        dx, dy = 0.0, 0.0
        for k in active:
            kdx, kdy = _DIRECTION_MAP.get(k, (0.0, 0.0))
            dx += kdx
            dy += kdy

        norm = (dx * dx + dy * dy) ** 0.5
        if norm == 0:
            return 0.0, 0.0
        return dx / norm, dy / norm

    def sample(self) -> Optional[LeaderSample]:
        mx, my = self._compute_movement()
        is_moving = mx != 0.0 or my != 0.0

        if is_moving:
            heading = self._compute_heading(mx, my)
        else:
            heading = self._last_heading

        heading_delta = abs(heading - self._last_heading)
        if heading_delta > 180:
            heading_delta = 360 - heading_delta

        if not self._was_moving and is_moving:
            event = "move"
        elif self._was_moving and not is_moving:
            event = "stop"
        elif is_moving and heading_delta >= self._turn_threshold:
            event = "turn"
        else:
            event = "stop" if not is_moving else "move"

        self._last_heading = heading
        self._was_moving = is_moving

        return LeaderSample(
            captured_at=time.time(),
            movement_x=mx,
            movement_y=my,
            is_moving=is_moving,
            heading=heading,
            event=event,
            source="keyboard",
        )

    @staticmethod
    def _compute_heading(mx: float, my: float) -> float:
        import math

        if mx == 0.0 and my == 0.0:
            return 0.0

        angle = math.degrees(math.atan2(mx, -my))
        if angle < 0:
            angle += 360.0

        return round(angle, 1)
