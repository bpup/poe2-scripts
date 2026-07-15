"""Inject keyboard/mouse events into specific window HWNDs via Win32 PostMessage.

Keyboard: WM_KEYDOWN/WM_KEYUP with proper lParam encoding. PostMessage queues
the message to the target window's message queue — no foreground focus required.
This is the standard approach used by open-source multi-boxing tools like
OpenMultiBoxing and PyCrossWindowKeyStrokeSender.

Mouse: WM_LBUTTONDOWN/WM_LBUTTONUP with MAKELPARAM for client-area coordinates.
Useful for clicking portals, NPCs, and other interactable objects when the
follower is standing on top of them.

Note: Some games use DirectInput for movement input, which reads raw keyboard
state rather than the Windows message queue. If PostMessage is insufficient for
PoE2 movement (WASD), a SendInput + SetForegroundWindow fallback is the next step.
"""

from __future__ import annotations

from typing import Dict, Set, Tuple

from src.common.logger import get_logger
from src.core.behavior_randomizer import jitter

logger = get_logger(__name__)


_KeyInfo = Tuple[int, int]

_KEY_TABLE: Dict[str, _KeyInfo] = {
    "w": (0x57, 0x11),
    "a": (0x41, 0x1E),
    "s": (0x53, 0x1F),
    "d": (0x44, 0x20),
    "SPACE": (0x20, 0x39),
    "Q": (0x51, 0x10),
    "1": (0x31, 0x02),
    "2": (0x32, 0x03),
    "3": (0x33, 0x04),
    "4": (0x34, 0x05),
    "5": (0x35, 0x06),
}

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

_CLICK_COOLDOWN_BASE = 0.5
_CLICK_COOLDOWN_JITTER = 0.2


class InputInjector:
    """Inject key/mouse events into specific window HWNDs via Win32 PostMessage.

    Uses WM_KEYDOWN (0x0100), WM_KEYUP (0x0101), WM_LBUTTONDOWN (0x0201),
    and WM_LBUTTONUP (0x0202) with proper lParam encoding.

    If PoE2 uses DirectInput for movement (ignoring Windows messages),
    a SendInput + SetForegroundWindow cycling approach is the fallback.
    """

    WM_KEYDOWN = WM_KEYDOWN
    WM_KEYUP = WM_KEYUP
    WM_LBUTTONDOWN = WM_LBUTTONDOWN
    WM_LBUTTONUP = WM_LBUTTONUP

    def __init__(self) -> None:
        self._last_click: Dict[int, float] = {}

    def press(self, hwnd: int, key_str: str) -> bool:
        vk_code, scan_code = self._lookup(key_str)
        if vk_code is None:
            return False

        lparam = 0x00000001 | (scan_code << 16)

        try:
            import win32gui

            result = win32gui.PostMessage(hwnd, WM_KEYDOWN, vk_code, lparam)
            ok = result != 0
            if ok:
                logger.debug("WM_KEYDOWN -> hwnd=%d key='%s'", hwnd, key_str)
            else:
                logger.warning(
                    "PostMessage(WM_KEYDOWN) failed for hwnd=%d key='%s'",
                    hwnd, key_str,
                )
            return ok
        except Exception:
            logger.exception(
                "Exception sending WM_KEYDOWN to hwnd=%d key='%s'", hwnd, key_str,
            )
            return False

    def release(self, hwnd: int, key_str: str) -> bool:
        vk_code, scan_code = self._lookup(key_str)
        if vk_code is None:
            return False

        lparam = 0xC0000001 | (scan_code << 16)

        try:
            import win32gui

            result = win32gui.PostMessage(hwnd, WM_KEYUP, vk_code, lparam)
            ok = result != 0
            if ok:
                logger.debug("WM_KEYUP  -> hwnd=%d key='%s'", hwnd, key_str)
            else:
                logger.warning(
                    "PostMessage(WM_KEYUP) failed for hwnd=%d key='%s'",
                    hwnd, key_str,
                )
            return ok
        except Exception:
            logger.exception(
                "Exception sending WM_KEYUP to hwnd=%d key='%s'", hwnd, key_str,
            )
            return False

    def click(self, hwnd: int, x: float = -1, y: float = -1) -> bool:
        import time as _time

        now = _time.monotonic()
        cooldown = jitter(_CLICK_COOLDOWN_BASE, _CLICK_COOLDOWN_JITTER)
        if now - self._last_click.get(hwnd, 0.0) < cooldown:
            return True

        cx, cy = x, y
        if cx < 0 or cy < 0:
            try:
                import win32gui
                _, _, cw, ch = win32gui.GetClientRect(hwnd)
                cx = cw / 2
                cy = ch / 2
            except Exception:
                cx = 960
                cy = 540

        self._last_click[hwnd] = _time.monotonic()
        lparam = int(cy) << 16 | (int(cx) & 0xFFFF)

        down_ok = False
        up_ok = False
        try:
            import win32gui

            result = win32gui.PostMessage(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
            down_ok = result != 0
            result = win32gui.PostMessage(hwnd, WM_LBUTTONUP, 0, lparam)
            up_ok = result != 0
        except Exception:
            logger.exception("Exception sending click to hwnd=%d (%d,%d)", hwnd, cx, cy)

        ok = down_ok and up_ok
        if ok:
            logger.debug("Click -> hwnd=%d pos=(%d,%d)", hwnd, cx, cy)
        else:
            logger.warning("Click failed for hwnd=%d down=%s up=%s", hwnd, down_ok, up_ok)
        return ok

    def release_all(self, hwnd: int, held_keys: Set[str]) -> None:
        for key_str in list(held_keys):
            if not self.release(hwnd, key_str):
                logger.warning(
                    "release_all: failed to release '%s' on hwnd=%d",
                    key_str, hwnd,
                )

    def is_key_supported(self, key_str: str) -> bool:
        return key_str in _KEY_TABLE

    @staticmethod
    def _lookup(key_str: str) -> Tuple[int | None, int | None]:
        info = _KEY_TABLE.get(key_str)
        if info is None:
            logger.warning("Unsupported key '%s' — not in key table.", key_str)
            return None, None
        return info
