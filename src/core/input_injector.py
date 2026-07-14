"""Inject keyboard events into specific window HWNDs via Win32 PostMessage.

Uses WM_KEYDOWN/WM_KEYUP with proper lParam encoding. PostMessage queues
the message to the target window's message queue — no foreground focus required.
This is the standard approach used by open-source multi-boxing tools like
OpenMultiBoxing and PyCrossWindowKeyStrokeSender.

Note: Some games use DirectInput for movement input, which reads raw keyboard
state rather than the Windows message queue. If PostMessage is insufficient for
PoE2 movement (WASD), a SendInput + SetForegroundWindow fallback is the next step.
"""

from __future__ import annotations

from typing import Dict, Set, Tuple

from src.common.logger import get_logger

logger = get_logger(__name__)


_KeyInfo = Tuple[int, int]

_KEY_TABLE: Dict[str, _KeyInfo] = {
    "w": (0x57, 0x11),  # VK_W
    "a": (0x41, 0x1E),  # VK_A
    "s": (0x53, 0x1F),  # VK_S
    "d": (0x44, 0x20),  # VK_D
}

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101


class InputInjector:
    """Inject key events into specific window HWNDs via Win32 PostMessage.

    Uses WM_KEYDOWN (0x0100) and WM_KEYUP (0x0101) with proper lParam
    encoding. PostMessage queues the message to the target window's
    message queue — no foreground focus required.

    If PoE2 uses DirectInput for movement (ignoring Windows messages),
    a SendInput + SetForegroundWindow cycling approach is the fallback.
    """

    WM_KEYDOWN = WM_KEYDOWN
    WM_KEYUP = WM_KEYUP

    def __init__(self) -> None:
        """Create an injector instance.

        The injector is stateless — HWND is passed per call so a single
        instance can serve all follower windows.
        """

    def press(self, hwnd: int, key_str: str) -> bool:
        """Send WM_KEYDOWN to the target window.

        Args:
            hwnd: Window handle (as integer).
            key_str: Key identifier ('w', 'a', 's', 'd').

        Returns:
            True if PostMessage succeeded (non-zero return), False if the
            HWND is invalid or the message could not be queued.
        """
        vk_code, scan_code = self._lookup(key_str)
        if vk_code is None:
            return False

        # WM_KEYDOWN lParam: repeat=0, context=0, prev=0, transition=0
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
                    hwnd,
                    key_str,
                )
            return ok
        except Exception:
            logger.exception(
                "Exception sending WM_KEYDOWN to hwnd=%d key='%s'",
                hwnd,
                key_str,
            )
            return False

    def release(self, hwnd: int, key_str: str) -> bool:
        """Send WM_KEYUP to the target window.

        Args:
            hwnd: Window handle (as integer).
            key_str: Key identifier ('w', 'a', 's', 'd').

        Returns:
            True if PostMessage succeeded (non-zero return), False otherwise.
        """
        vk_code, scan_code = self._lookup(key_str)
        if vk_code is None:
            return False

        # WM_KEYUP lParam: repeat=0, context=0, prev=1, transition=1
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
                    hwnd,
                    key_str,
                )
            return ok
        except Exception:
            logger.exception(
                "Exception sending WM_KEYUP to hwnd=%d key='%s'",
                hwnd,
                key_str,
            )
            return False

    def release_all(self, hwnd: int, held_keys: Set[str]) -> None:
        """Release all currently held keys for a window.

        Best-effort — logs failures but never raises.

        Args:
            hwnd: Window handle (as integer).
            held_keys: Set of key strings currently held (e.g. {'w', 'd'}).
        """
        for key_str in list(held_keys):
            if not self.release(hwnd, key_str):
                logger.warning(
                    "release_all: failed to release '%s' on hwnd=%d",
                    key_str,
                    hwnd,
                )

    def is_key_supported(self, key_str: str) -> bool:
        """Check whether a key string is in the supported lookup table."""
        return key_str in _KEY_TABLE

    @staticmethod
    def _lookup(key_str: str) -> Tuple[int | None, int | None]:
        """Resolve a key string to (vk_code, scan_code).

        Returns (None, None) for unsupported keys.
        """
        info = _KEY_TABLE.get(key_str)
        if info is None:
            logger.warning("Unsupported key '%s' — not in key table.", key_str)
            return None, None
        return info
