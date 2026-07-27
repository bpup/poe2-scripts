"""Virtual Xbox 360 gamepad controller for PoE2 local co-op character routing.

Uses the `vgamepad` Python library which creates virtual Xbox 360 controllers
on a ViGEmBus driver. Each virtual controller instance is a separate gamepad
that PoE2 sees as a distinct player — enabling character-specific input injection
for local co-op (2 characters per window).

Architecture:
    HidHide (driver-level) → whitelists specific virtual gamepad per PoE2 PID
    ViGEmBus (driver-level) → hosts virtual controller devices
    vgamepad (Python)       → creates/manages controller instances on the bus
    VGamepadManager          → this module's public API

Button mapping (PoE2 default binds for gamepad):
    A  → SPACE (jump/use)       X   → Q (secondary skill / loot)
    B  → ESC (menu/back)        Y   → (unbound)
    LB → 1 (flask slot 1)       RB → (unbound)
    DPad Up/Down → flask 2/3    DPad Left/Right → flask 4/5
    LT → CTRL (toggle)          RT → SHIFT (hold/pickup)
    L3 → (unbound)              R3 → (unbound)

HidHide setup (manual, one-time):
    1. Install HidHide Configuration Client
    2. Applications tab → whitelist each PoE2.exe by PID
    3. Devices tab → blacklist physical controllers, whitelist VX360 devices
    4. Enable "Enable device hiding"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


class VX360Button(IntEnum):
    """Xbox 360 controller button codes matching vgamepad constants."""

    A = 0x1000
    B = 0x2000
    X = 0x4000
    Y = 0x8000
    DPAD_UP = 0x0001
    DPAD_DOWN = 0x0002
    DPAD_LEFT = 0x0004
    DPAD_RIGHT = 0x0008
    START = 0x0010
    BACK = 0x0020
    LEFT_SHOULDER = 0x0100
    RIGHT_SHOULDER = 0x0200
    LEFT_THUMB = 0x0040
    RIGHT_THUMB = 0x0080


_ACTION_MAP: Dict[str, int] = {
    "A": VX360Button.A,
    "B": VX360Button.B,
    "X": VX360Button.X,
    "Y": VX360Button.Y,
    "DPAD_UP": VX360Button.DPAD_UP,
    "DPAD_DOWN": VX360Button.DPAD_DOWN,
    "DPAD_LEFT": VX360Button.DPAD_LEFT,
    "DPAD_RIGHT": VX360Button.DPAD_RIGHT,
    "LB": VX360Button.LEFT_SHOULDER,
    "RB": VX360Button.RIGHT_SHOULDER,
    "L3": VX360Button.LEFT_THUMB,
    "R3": VX360Button.RIGHT_THUMB,
    "START": VX360Button.START,
    "BACK": VX360Button.BACK,
    "JUMP": VX360Button.A,
    "SKILL": VX360Button.X,
    "FLASK_1": VX360Button.LEFT_SHOULDER,
    "FLASK_2": VX360Button.DPAD_UP,
    "FLASK_3": VX360Button.DPAD_DOWN,
    "FLASK_4": VX360Button.DPAD_LEFT,
    "FLASK_5": VX360Button.DPAD_RIGHT,
    "MENU": VX360Button.B,
    "INTERACT": VX360Button.A,
}


@dataclass
class ControllerSlot:
    """Internal state for a single virtual gamepad instance."""

    index: int
    gamepad: object
    joystick_x: float = 0.0
    joystick_y: float = 0.0
    held_buttons: set = field(default_factory=set)


class VGamepadManager:
    """Manages a pool of virtual Xbox 360 controllers on a ViGEmBus.

    Each PoE2 window in local co-op mode has exactly 1 keyboard-controlled
    character (P1) and needs 0-1 virtual gamepad characters (P2).
    This manager creates controllers on demand and routes per-character
    input to the correct virtual device.

    Usage:
        mgr = VGamepadManager()
        cid = mgr.create()                    # create controller, returns ID
        mgr.joystick(cid, 1.0, 0.0)          # move right
        mgr.press_button(cid, "JUMP")         # jump
        mgr.release_button(cid, "JUMP")
    mgr.close(cid)
    mgr.close_all()
    """

    def __init__(self) -> None:
        self._slots: Dict[int, ControllerSlot] = {}
        self._next_index: int = 0
        self._vgamepad = None

    def _ensure_imported(self) -> bool:
        """Lazy-import vgamepad. Returns True on success."""
        if self._vgamepad is not None:
            return True
        try:
            import vgamepad as vg

            self._vgamepad = vg
            logger.info("vgamepad library imported. ViGEmBus is required on the system.")
            return True
        except ImportError:
            logger.error(
                "vgamepad library not installed. Install via: pip install vgamepad\n"
                "Also requires ViGEmBus driver — download from https://github.com/nefarius/ViGEmBus/releases",
            )
            return False
        except Exception:
            logger.exception("Unexpected error importing vgamepad.")
            return False

    def create(self) -> Optional[int]:
        """Create a new virtual Xbox 360 gamepad.

        Returns:
            Controller ID (int) for subsequent calls, or None on failure.
        """
        if not self._ensure_imported():
            return None

        cid = self._next_index
        self._next_index += 1

        try:
            gamepad = self._vgamepad.VX360Gamepad()
            self._slots[cid] = ControllerSlot(index=cid, gamepad=gamepad)
            logger.info("Virtual controller %d created.", cid)
            return cid
        except Exception:
            logger.exception("Failed to create virtual controller %d.", cid)
            return None

    def joystick(self, controller_id: int, x: float, y: float) -> bool:
        """Set left joystick position for a virtual controller.

        Args:
            controller_id: Controller ID from create().
            x: Horizontal axis value, -1.0 (full left) to 1.0 (full right).
            y: Vertical axis value, -1.0 (full down) to 1.0 (full up).

        Returns:
            True if the joystick position was set and pushed.
        """
        slot = self._slots.get(controller_id)
        if slot is None:
            logger.warning("Controller %d not found for joystick update.", controller_id)
            return False

        x = max(-1.0, min(1.0, x))
        y = max(-1.0, min(1.0, y))

        slot.joystick_x = x
        slot.joystick_y = y

        try:
            slot.gamepad.left_joystick_float(x_value_float=x, y_value_float=y)
            slot.gamepad.update()
            return True
        except Exception:
            logger.exception("Failed to update joystick on controller %d.", controller_id)
            return False

    def press_button(self, controller_id: int, button_name: str) -> bool:
        """Press (hold) a named button on a virtual controller.

        Supported names: A, B, X, Y, DPAD_UP, DPAD_DOWN, DPAD_LEFT,
        DPAD_RIGHT, LB, RB, L3, R3, START, BACK.
        Convenience aliases: JUMP, SKILL, FLASK_1..5, MENU, INTERACT.

        The button remains held until release_button() or close() is called.
        """
        slot = self._slots.get(controller_id)
        if slot is None:
            logger.warning("Controller %d not found for button press.", controller_id)
            return False

        button_code = _ACTION_MAP.get(button_name.upper())
        if button_code is None:
            logger.warning("Unknown button '%s' for controller %d.", button_name, controller_id)
            return False

        if button_code in slot.held_buttons:
            return True

        try:
            slot.gamepad.press_button(button=button_code)
            slot.gamepad.update()
            slot.held_buttons.add(button_code)
            return True
        except Exception:
            logger.exception(
                "Failed to press button '%s' on controller %d.",
                button_name, controller_id,
            )
            return False

    def release_button(self, controller_id: int, button_name: str) -> bool:
        """Release a named button on a virtual controller."""
        slot = self._slots.get(controller_id)
        if slot is None:
            logger.warning("Controller %d not found for button release.", controller_id)
            return False

        button_code = _ACTION_MAP.get(button_name.upper())
        if button_code is None:
            logger.warning("Unknown button '%s' for controller %d.", button_name, controller_id)
            return False

        if button_code not in slot.held_buttons:
            return True

        try:
            slot.gamepad.release_button(button=button_code)
            slot.gamepad.update()
            slot.held_buttons.discard(button_code)
            return True
        except Exception:
            logger.exception(
                "Failed to release button '%s' on controller %d.",
                button_name, controller_id,
            )
            return False

    def release_all_buttons(self, controller_id: int) -> bool:
        """Release all held buttons on a controller. Leaves joystick as-is."""
        slot = self._slots.get(controller_id)
        if slot is None:
            return False

        for btn in list(slot.held_buttons):
            try:
                slot.gamepad.release_button(button=btn)
            except Exception:
                pass
        slot.held_buttons.clear()
        try:
            slot.gamepad.update()
        except Exception:
            pass
        return True

    def reset(self, controller_id: int) -> bool:
        """Reset controller to neutral state (center joystick, no buttons)."""
        slot = self._slots.get(controller_id)
        if slot is None:
            return False

        slot.joystick_x = 0.0
        slot.joystick_y = 0.0
        slot.held_buttons.clear()

        try:
            slot.gamepad.reset()
            slot.gamepad.update()
            return True
        except Exception:
            logger.exception("Failed to reset controller %d.", controller_id)
            return False

    def close(self, controller_id: int) -> None:
        """Close and remove a single virtual controller."""
        slot = self._slots.pop(controller_id, None)
        if slot is None:
            return
        self.reset(controller_id)
        logger.info("Virtual controller %d closed.", controller_id)

    def close_all(self) -> None:
        """Close all virtual controllers."""
        for cid in list(self._slots.keys()):
            self.close(cid)

    @property
    def active_count(self) -> int:
        """Number of currently active virtual controllers."""
        return len(self._slots)

    def is_active(self, controller_id: int) -> bool:
        """Check if a controller ID is currently active."""
        return controller_id in self._slots
