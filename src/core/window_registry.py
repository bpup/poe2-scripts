import platform
from typing import Dict, List, Optional

from src.common.logger import get_logger
from src.core.party_state import WindowBinding, WindowStatus

logger = get_logger(__name__)

SYSTEM = platform.system()
_HAS_WIN32 = False

if SYSTEM == "Windows":
    try:
        import win32gui
        _HAS_WIN32 = True
    except ImportError:
        logger.warning(
            "pywin32 not installed. Window scanning unavailable on Windows."
        )


class WindowRegistry:
    def __init__(self):
        self._bindings: Dict[str, WindowBinding] = {}
        self._found_windows: List[dict] = []

    def _scan_win32(self, title_fragment: str) -> List[dict]:
        windows: List[dict] = []

        def enum_callback(hwnd, _ctx):
            title = win32gui.GetWindowText(hwnd)
            if title and title_fragment in title:
                windows.append({"handle": str(hwnd), "title": title})

        win32gui.EnumWindows(enum_callback, None)
        return windows

    def scan_windows(self, title_fragment: str = "Path of Exile 2") -> List[dict]:
        if _HAS_WIN32:
            self._found_windows = self._scan_win32(title_fragment)
        else:
            logger.warning(
                "Window scanning only supported on Windows. Found 0 windows."
            )
            self._found_windows = []

        logger.info(
            "Scan: found %d window(s) matching '%s'.",
            len(self._found_windows),
            title_fragment,
        )
        return self._found_windows

    def bind_window(
        self,
        role_id: str,
        role_type: str,
        window_title: str,
        windows: List[dict],
        window_index: int = 0,
    ) -> WindowBinding:
        """Bind a role to a window from a pre-scanned window list.

        Caller should call `scan_windows()` once, then pass the result to each
        `bind_window()` call with the appropriate index. This avoids re-scanning
        for every role and ensures consistent window ordering.
        """
        if windows and window_index < len(windows):
            win = windows[window_index]
            handle = str(win["handle"])
            status = WindowStatus.READY
        else:
            handle = ""
            status = WindowStatus.MISSING

        binding = WindowBinding(
            role_id=role_id,
            role_type=role_type,
            window_title=window_title,
            handle=handle,
            status=status,
        )
        self._bindings[role_id] = binding

        logger.info(
            "Bound %s '%s' -> window[%d] (handle=%s, status=%s).",
            role_type,
            role_id,
            window_index,
            handle,
            status.value,
        )
        return binding

    def unbind(self, role_id: str) -> None:
        self._bindings.pop(role_id, None)
        logger.info("Unbound role '%s' from registry.", role_id)

    def check_health(self, binding: WindowBinding) -> WindowStatus:
        if not binding.handle:
            binding.status = WindowStatus.MISSING
            return WindowStatus.MISSING

        if _HAS_WIN32:
            try:
                hwnd = int(binding.handle)
                alive = win32gui.IsWindow(hwnd)
                binding.status = (
                    WindowStatus.READY if alive else WindowStatus.MISSING
                )
            except (ValueError, Exception):
                binding.status = WindowStatus.MISSING
        else:
            binding.status = WindowStatus.READY

        return binding.status

    def check_all_health(self) -> Dict[str, WindowStatus]:
        return {rid: self.check_health(b) for rid, b in self._bindings.items()}

    @property
    def binding_count(self) -> int:
        return len(self._bindings)
