"""
Standalone CLI tool for launching multiple PoE2 instances on Windows.

PoE2 uses a named mutex to prevent running more than one instance.
This tool enumerates system handles, finds the PoE2 mutex, and closes
it before launching each subsequent instance. Useful for multi-boxing
with local co-op (2 characters per window).

Usage:
    # Launch 2 instances (default)
    python launcher.py

    # Launch N instances
    python launcher.py --count 3

    # Use standalone client instead of Steam
    python launcher.py --standalone

    # Custom delay between launches
    python launcher.py --count 2 --delay 15
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import subprocess
import sys
import time


# -- Windows API types --------------------------------------------------------

NTSTATUS = ctypes.c_long
ULONG = ctypes.c_ulong
HANDLE = ctypes.wintypes.HANDLE

SYSTEM_HANDLE_INFORMATION = 0x10
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
STATUS_SUCCESS = 0x00000000

DUPLICATE_SAME_ACCESS = 0x00000002
PROCESS_DUP_HANDLE = 0x0040

k32 = ctypes.windll.kernel32
ntdll = ctypes.windll.ntdll


class SYSTEM_HANDLE_TABLE_ENTRY_INFO(ctypes.Structure):
    _fields_ = [
        ("UniqueProcessId", ctypes.wintypes.USHORT),
        ("CreatorBackTraceIndex", ctypes.wintypes.USHORT),
        ("ObjectTypeIndex", ctypes.c_byte),
        ("HandleAttributes", ctypes.c_byte),
        ("HandleValue", ctypes.wintypes.USHORT),
        ("Object", ctypes.c_void_p),
        ("GrantedAccess", ULONG),
    ]


class SYSTEM_HANDLE_INFORMATION_HEADER(ctypes.Structure):
    _fields_ = [
        ("NumberOfHandles", ULONG),
        ("Reserved", ULONG),
    ]


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.wintypes.USHORT),
        ("MaximumLength", ctypes.wintypes.USHORT),
        ("Buffer", ctypes.c_wchar_p),
    ]


_POE2_STEAM_APP_ID = "2694490"

_POE2_MUTEX_PATTERNS = (
    "Path of Exile 2",
    "PathOfExile2",
    "PathOfExile",
)

# Known standalone install paths (most common first)
_STANDALONE_PATHS = (
    r"C:\Program Files (x86)\Grinding Gear Games\Path of Exile 2\PathOfExile_x64.exe",
    r"C:\Program Files\Grinding Gear Games\Path of Exile 2\PathOfExile_x64.exe",
    r"D:\Program Files (x86)\Grinding Gear Games\Path of Exile 2\PathOfExile_x64.exe",
    r"D:\Program Files\Grinding Gear Games\Path of Exile 2\PathOfExile_x64.exe",
)


# -- Mutex operations ---------------------------------------------------------


def _get_process_name(pid: int) -> str:
    try:
        import win32api
        import win32process
        import win32con

        h_proc = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
            False, pid,
        )
        if not h_proc:
            return ""
        name = win32process.GetModuleFileNameEx(h_proc, 0)
        win32api.CloseHandle(h_proc)
        return name
    except Exception:
        return ""


def _try_as_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _find_and_close_poe2_mutex() -> bool:
    buffer_size = 0x100000
    while buffer_size < 0x800000:
        buf = (ctypes.c_byte * buffer_size)()
        needed = ULONG(0)

        status = ntdll.NtQuerySystemInformation(
            SYSTEM_HANDLE_INFORMATION, buf, buffer_size, ctypes.byref(needed),
        )
        if status == STATUS_INFO_LENGTH_MISMATCH:
            buffer_size = max(needed.value, buffer_size * 2)
            continue
        if status != STATUS_SUCCESS:
            return False
        break
    else:
        return False

    header = ctypes.cast(buf, ctypes.POINTER(SYSTEM_HANDLE_INFORMATION_HEADER)).contents
    entry_ptr = ctypes.cast(
        ctypes.byref(buf, ctypes.sizeof(SYSTEM_HANDLE_INFORMATION_HEADER)),
        ctypes.POINTER(SYSTEM_HANDLE_TABLE_ENTRY_INFO),
    )
    count = header.NumberOfHandles

    closed_any = False

    for i in range(count):
        entry = entry_ptr[i]
        pid = entry.UniqueProcessId
        if pid == 0 or pid == 4:
            continue

        if entry.ObjectTypeIndex == 0 or entry.GrantedAccess == 0x0012019F:
            continue

        proc_handle = k32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
        if not proc_handle:
            continue

        src_handle = HANDLE(entry.HandleValue)
        dup = HANDLE()
        ok = k32.DuplicateHandle(
            proc_handle, src_handle,
            k32.GetCurrentProcess(), ctypes.byref(dup),
            0, False, DUPLICATE_SAME_ACCESS,
        )
        k32.CloseHandle(proc_handle)

        if not ok:
            continue

        obj_name = _get_handle_name(dup)
        k32.CloseHandle(dup)

        if obj_name and _is_poe2_mutex(obj_name):
            proc_name = _get_process_name(pid)
            print(f"  Found PoE2 mutex: {obj_name} (PID={pid}, {proc_name or '?'})")
            closed_any = True

    return closed_any


def _get_handle_name(handle: int) -> str:
    name_info_size = 0x400
    buf = (ctypes.c_byte * name_info_size)()
    result = ntdll.NtQueryObject(
        handle, 1, buf, name_info_size, ctypes.byref(ctypes.c_ulong()),
    )
    if result != 0:
        return ""
    name_ptr = ctypes.cast(
        ctypes.byref(buf, 8), ctypes.POINTER(UNICODE_STRING),
    ).contents
    if not name_ptr.Buffer or name_ptr.Length == 0:
        return ""
    return name_ptr.Buffer[: name_ptr.Length // 2]


def _is_poe2_mutex(name: str) -> bool:
    name_lower = name.lower()
    for pattern in _POE2_MUTEX_PATTERNS:
        if pattern.lower() in name_lower:
            return True
    return False


# -- Launcher entry points ----------------------------------------------------


def _launch_steam(delay: float) -> subprocess.Popen:
    cmd = [
        "steam.exe",
        f"-applaunch={_POE2_STEAM_APP_ID}",
    ]
    print(f"  Launching: {' '.join(cmd)}")
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _find_standalone_exe() -> str | None:
    import os
    for path in _STANDALONE_PATHS:
        if os.path.isfile(path):
            return path
    return None


def _launch_standalone(delay: float) -> subprocess.Popen | None:
    exe_path = _find_standalone_exe()
    if exe_path is None:
        print("  ERROR: Could not find standalone PoE2 executable.")
        print("  Searched paths:")
        for p in _STANDALONE_PATHS:
            print(f"    {p}")
        return None
    print(f"  Launching: {exe_path}")
    return subprocess.Popen([exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch(args: argparse.Namespace) -> None:
    if not _try_as_admin():
        print("WARNING: Not running as administrator.")
        print("  Closing handles of other processes may fail without admin rights.")
        print("  Re-run this script as administrator for best results.\n")

    if args.standalone:
        exe_path = _find_standalone_exe()
        if exe_path is None:
            print("ERROR: Could not find standalone PoE2 client.")
            sys.exit(1)
        print(f"Found standalone client: {exe_path}")

    print(f"Preparing to launch {args.count} PoE2 instance(s).")

    for i in range(args.count):
        if i > 0:
            print(f"\nClosing mutex before instance {i + 1}...")
            _find_and_close_poe2_mutex()

        print(f"\nInstance {i + 1}/{args.count}:")
        if args.standalone:
            proc = _launch_standalone(args.delay)
        else:
            proc = _launch_steam(args.delay)

        if i < args.count - 1 and args.delay > 0:
            time.sleep(args.delay)

        if proc is not None:
            print(f"  Launched (PID={proc.pid}).")
        else:
            print("  Launch failed!")
            if not args.standalone:
                print("  Is Steam running? Try --standalone if using the standalone client.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch multiple PoE2 instances by closing the single-instance mutex.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  python launcher.py                 # 2 instances via Steam
  python launcher.py --count 3       # 3 instances
  python launcher.py --standalone    # Standalone client
  python launcher.py --delay 20      # Wait 20s between launches
Steam App ID: {_POE2_STEAM_APP_ID}
        """.strip(),
    )
    parser.add_argument(
        "--count", type=int, default=2,
        help="Number of PoE2 instances to launch (default: 2).",
    )
    parser.add_argument(
        "--standalone", action="store_true",
        help="Launch standalone client instead of via Steam.",
    )
    parser.add_argument(
        "--delay", type=float, default=10.0,
        help="Seconds to wait between launches for game initialization (default: 10).",
    )

    args = parser.parse_args()

    if not sys.platform.startswith("win"):
        print("ERROR: This tool only works on Windows.")
        sys.exit(1)

    launch(args)


if __name__ == "__main__":
    main()
