from __future__ import annotations

import ctypes
import ctypes.wintypes
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_ALL_ACCESS = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION

_OpenProcess = ctypes.windll.kernel32.OpenProcess
_OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
_OpenProcess.restype = ctypes.wintypes.HANDLE

_CloseHandle = ctypes.windll.kernel32.CloseHandle
_CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
_CloseHandle.restype = ctypes.wintypes.BOOL

_ReadProcessMemory = ctypes.windll.kernel32.ReadProcessMemory
_ReadProcessMemory.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.LPCVOID,
    ctypes.wintypes.LPVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
_ReadProcessMemory.restype = ctypes.wintypes.BOOL

_EnumProcesses = ctypes.windll.psapi.EnumProcesses
_EnumProcesses.argtypes = [
    ctypes.POINTER(ctypes.wintypes.DWORD),
    ctypes.wintypes.DWORD,
    ctypes.POINTER(ctypes.wintypes.DWORD),
]
_EnumProcesses.restype = ctypes.wintypes.BOOL

_GetModuleBaseNameW = ctypes.windll.psapi.GetModuleBaseNameW
_GetModuleBaseNameW.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HMODULE,
    ctypes.wintypes.LPWSTR,
    ctypes.wintypes.DWORD,
]
_GetModuleBaseNameW.restype = ctypes.wintypes.DWORD

_EnumProcessModules = ctypes.windll.psapi.EnumProcessModules
_EnumProcessModules.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(ctypes.wintypes.HMODULE),
    ctypes.wintypes.DWORD,
    ctypes.POINTER(ctypes.wintypes.DWORD),
]
_EnumProcessModules.restype = ctypes.wintypes.BOOL

_GetModuleInformation = ctypes.windll.psapi.GetModuleInformation
_GetModuleInformation.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HMODULE,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
]
_GetModuleInformation.restype = ctypes.wintypes.BOOL

POE2_PROCESS_NAMES = {
    "PathOfExile_x64Steam.exe",
    "PathOfExile_x64.exe",
    "PathOfExileSteam.exe",
    "PathOfExile.exe",
}


class MODULEINFO(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", ctypes.wintypes.LPVOID),
        ("SizeOfImage", ctypes.wintypes.DWORD),
        ("EntryPoint", ctypes.wintypes.LPVOID),
    ]


@dataclass(frozen=True)
class GameProcess:
    pid: int
    handle: int
    base_address: int
    module_size: int


@dataclass(frozen=True)
class EntityPosition:
    x: float
    y: float
    z: float


class MemoryReader:
    def __init__(self, offset_config: dict) -> None:
        self._config = offset_config
        self._processes: Dict[int, GameProcess] = {}

    def open_process(self, pid: int) -> Optional[GameProcess]:
        if pid in self._processes:
            return self._processes[pid]

        handle = _OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not handle:
            logger.warning("OpenProcess failed for PID %d.", pid)
            return None

        base = self._get_module_base(handle)
        if base is None:
            _CloseHandle(handle)
            return None

        proc = GameProcess(
            pid=pid,
            handle=handle,
            base_address=base,
            module_size=0,
        )
        self._processes[pid] = proc
        logger.info("Opened PoE2 process PID=%d, base=0x%016X.", pid, base)
        return proc

    def find_poe2_processes(self) -> List[int]:
        pids = (ctypes.wintypes.DWORD * 4096)()
        cb_needed = ctypes.wintypes.DWORD()
        if not _EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(cb_needed)):
            return []

        count = cb_needed.value // ctypes.sizeof(ctypes.wintypes.DWORD)
        found: List[int] = []

        for i in range(count):
            pid = pids[i]
            if pid == 0:
                continue

            proc_handle = _OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if not proc_handle:
                continue

            name = self._get_process_name(proc_handle)
            _CloseHandle(proc_handle)

            if name in POE2_PROCESS_NAMES:
                found.append(pid)

        logger.info("Found %d PoE2 processes: %s.", len(found), found)
        return found

    def read_local_player_position(self, proc: GameProcess) -> Optional[EntityPosition]:
        chain = self._config.get("local_player_chain", [])
        if not chain:
            logger.warning("No local_player_chain in offset config.")
            return None

        addr = proc.base_address
        for i, offset in enumerate(chain[:-1]):
            addr = self._read_pointer(proc.handle, addr + offset)
            if addr == 0:
                return None

        pos_offset = chain[-1]
        try:
            x = self._read_float(proc.handle, addr + pos_offset)
            y = self._read_float(proc.handle, addr + pos_offset + 0x04)
            z = self._read_float(proc.handle, addr + pos_offset + 0x08)
            return EntityPosition(x, y, z)
        except Exception:
            return None

    def read_entity_positions(self, proc: GameProcess, offset_chain: List[int]) -> List[EntityPosition]:
        addr = proc.base_address
        for offset in offset_chain:
            addr = self._read_pointer(proc.handle, addr + offset)
            if addr == 0:
                return []

        entity_count = self._read_int32(proc.handle, addr + self._config.get("entity_count_offset", 0x0))
        if entity_count <= 0 or entity_count > 10000:
            return []

        entity_list_ptr = self._read_pointer(proc.handle, addr + self._config.get("entity_list_offset", 0x8))
        if entity_list_ptr == 0:
            return []

        entity_size = self._config.get("entity_size", 0x08)
        pos_offset = self._config.get("position_offset", 0x00)

        positions: List[EntityPosition] = []
        for i in range(entity_count):
            entity_ptr = self._read_pointer(proc.handle, entity_list_ptr + i * entity_size)
            if entity_ptr == 0:
                continue
            try:
                x = self._read_float(proc.handle, entity_ptr + pos_offset)
                y = self._read_float(proc.handle, entity_ptr + pos_offset + 0x04)
                z = self._read_float(proc.handle, entity_ptr + pos_offset + 0x08)
                positions.append(EntityPosition(x, y, z))
            except Exception:
                continue

        return positions

    def close_all(self) -> None:
        for pid, proc in list(self._processes.items()):
            _CloseHandle(proc.handle)
            logger.debug("Closed handle for PID %d.", pid)
        self._processes.clear()

    @staticmethod
    def _read_pointer(handle: int, address: int) -> int:
        buffer = ctypes.c_uint64()
        bytes_read = ctypes.c_size_t()
        success = _ReadProcessMemory(
            handle,
            ctypes.c_void_p(address),
            ctypes.byref(buffer),
            ctypes.sizeof(buffer),
            ctypes.byref(bytes_read),
        )
        if not success or bytes_read.value != ctypes.sizeof(buffer):
            return 0
        return buffer.value

    @staticmethod
    def _read_int32(handle: int, address: int) -> int:
        buffer = ctypes.c_int32()
        bytes_read = ctypes.c_size_t()
        success = _ReadProcessMemory(
            handle,
            ctypes.c_void_p(address),
            ctypes.byref(buffer),
            ctypes.sizeof(buffer),
            ctypes.byref(bytes_read),
        )
        if not success or bytes_read.value != ctypes.sizeof(buffer):
            return -1
        return buffer.value

    @staticmethod
    def _read_float(handle: int, address: int) -> float:
        buffer = ctypes.c_float()
        bytes_read = ctypes.c_size_t()
        success = _ReadProcessMemory(
            handle,
            ctypes.c_void_p(address),
            ctypes.byref(buffer),
            ctypes.sizeof(buffer),
            ctypes.byref(bytes_read),
        )
        if not success or bytes_read.value != ctypes.sizeof(buffer):
            return 0.0
        return buffer.value

    @staticmethod
    def _get_module_base(handle: int) -> Optional[int]:
        h_mod = (ctypes.wintypes.HMODULE * 1024)()
        cb_needed = ctypes.wintypes.DWORD()
        if not _EnumProcessModules(handle, h_mod, ctypes.sizeof(h_mod), ctypes.byref(cb_needed)):
            return None
        return h_mod[0] or None

    @staticmethod
    def _get_process_name(handle: int) -> str:
        h_mod = (ctypes.wintypes.HMODULE * 1024)()
        cb_needed = ctypes.wintypes.DWORD()
        if not _EnumProcessModules(handle, h_mod, ctypes.sizeof(h_mod), ctypes.byref(cb_needed)):
            return ""

        name_buf = ctypes.create_unicode_buffer(260)
        length = _GetModuleBaseNameW(handle, h_mod[0], name_buf, 260)
        return name_buf.value if length else ""
