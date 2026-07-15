from __future__ import annotations

import ctypes
import ctypes.wintypes
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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

AOB_CHUNK_SIZE = 0x10000


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
    def __init__(self, nav_config: dict) -> None:
        self._nav = nav_config
        self._processes: Dict[int, GameProcess] = {}
        self._game_states_cache: Dict[int, int] = {}
        self._render_index_cache: Dict[int, int] = {}

    def open_process(self, pid: int) -> Optional[GameProcess]:
        if pid in self._processes:
            return self._processes[pid]

        handle = _OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not handle:
            logger.warning("OpenProcess failed for PID %d.", pid)
            return None

        info = self._get_module_info(handle)
        if info is None:
            _CloseHandle(handle)
            return None

        base, size = info
        proc = GameProcess(pid=pid, handle=handle, base_address=base, module_size=size)
        self._processes[pid] = proc
        logger.info("Opened PoE2 PID=%d, base=0x%016X, size=%d MiB.", pid, base, size // (1024 * 1024))
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
        offsets = self._nav.get("offsets", {})
        if not offsets:
            return None

        game_states = self._game_states_cache.get(proc.pid)
        if game_states is None:
            game_states = self._resolve_game_states(proc)
            if game_states is None:
                return None
            self._game_states_cache[proc.pid] = game_states

        in_game_state = self._read_stdvec_first(
            proc.handle, game_states, offsets, "game_state", "current_state_ptr"
        )
        if in_game_state == 0:
            return None

        area_instance = self._read_ptr_at(
            proc.handle, in_game_state, offsets, "in_game_state", "area_instance"
        )
        if area_instance == 0:
            return None

        player_entity = self._read_ptr_at(
            proc.handle, area_instance, offsets, "area_instance", "local_player"
        )
        if player_entity == 0:
            return None

        render_idx = self._render_index_cache.get(proc.pid)
        if render_idx is None:
            render_idx = self._resolve_render_index(proc, player_entity)
            if render_idx is None:
                return None
            self._render_index_cache[proc.pid] = render_idx

        cl_addr = player_entity + offsets["entity"]["component_list"]
        cl_begin = self._read_pointer(proc.handle, cl_addr)
        if cl_begin == 0:
            return None
        render = self._read_pointer(proc.handle, cl_begin + render_idx * 8)
        if render == 0:
            return None

        wp_offset = offsets["render_component"]["world_position"]
        x = self._read_float(proc.handle, render + wp_offset)
        y = self._read_float(proc.handle, render + wp_offset + 4)
        z = self._read_float(proc.handle, render + wp_offset + 8)

        return EntityPosition(x, y, z)

    def close_all(self) -> None:
        for pid, proc in list(self._processes.items()):
            _CloseHandle(proc.handle)
            logger.debug("Closed handle for PID %d.", pid)
        self._processes.clear()

    # ── AOB scan ──────────────────────────────────────────────────

    def _resolve_game_states(self, proc: GameProcess) -> Optional[int]:
        aob = self._nav.get("aob", {})
        pat = aob.get("game_states")
        if not pat:
            logger.error("Missing AOB pattern 'game_states' in config.")
            return None

        match = self._scan_aob(
            proc.handle,
            proc.base_address,
            proc.module_size,
            pat["bytes"],
            pat["mask"],
        )
        if match is None:
            logger.warning("AOB scan for GameStates failed (PID %d).", proc.pid)
            return None

        disp = self._read_int32(proc.handle, match + pat["disp_offset"])
        slot = match + pat["instr_len"] + disp
        game_states = self._read_pointer(proc.handle, slot)

        logger.info(
            "GameStates @ 0x%016X (slot 0x%016X, match 0x%016X).",
            game_states, slot, match,
        )
        return game_states

    @staticmethod
    def _scan_aob(
        handle: int,
        start: int,
        size: int,
        pattern: bytes,
        mask: bytes,
    ) -> Optional[int]:
        pat_len = len(pattern)
        first_masked = mask[0] == 0xFF

        for chunk_off in range(0, size, AOB_CHUNK_SIZE):
            chunk_sz = min(AOB_CHUNK_SIZE, size - chunk_off)
            buf = (ctypes.c_byte * chunk_sz)()
            bytes_read = ctypes.c_size_t()
            ok = _ReadProcessMemory(
                handle,
                ctypes.c_void_p(start + chunk_off),
                buf,
                chunk_sz,
                ctypes.byref(bytes_read),
            )
            if not ok:
                continue
            data = bytes(buf[: bytes_read.value])

            pos = 0
            limit = len(data) - pat_len
            while pos <= limit:
                if first_masked and data[pos] != pattern[0]:
                    pos += 1
                    continue

                matched = True
                for j in range(1, pat_len):
                    if mask[j] == 0xFF and data[pos + j] != pattern[j]:
                        matched = False
                        break
                if matched:
                    return start + chunk_off + pos
                pos += 1

        return None

    # ── component name resolution ─────────────────────────────────

    def _resolve_render_index(self, proc: GameProcess, entity: int) -> Optional[int]:
        offsets = self._nav["offsets"]
        target = self._nav.get("render_component_name", "Render")

        details = self._read_ptr_at(proc.handle, entity, offsets, "entity", "details")
        if details == 0:
            return None

        lookup = self._read_ptr_at(proc.handle, details, offsets, "entity_details", "component_lookup")
        if lookup == 0:
            return None

        bucket_off = offsets["component_lookup"]["name_bucket"]
        begin = self._read_pointer(proc.handle, lookup + bucket_off)
        end = self._read_pointer(proc.handle, lookup + bucket_off + 0x08)
        if begin == 0 or end == 0:
            return None

        stride = offsets["component_lookup"]["entry_stride"]
        count = (end - begin) // stride

        for i in range(count):
            entry = begin + i * stride
            name_ptr = self._read_pointer(proc.handle, entry)
            if name_ptr == 0:
                continue
            name = self._read_utf16_string(proc.handle, name_ptr)
            if name == target:
                idx = self._read_int32(proc.handle, entry + 0x08)
                logger.info("Found component '%s' at index %d.", target, idx)
                return idx

        logger.warning("Component '%s' not found in ComponentLookUp.", target)
        return None

    # ── offset helpers ────────────────────────────────────────────

    @staticmethod
    def _read_ptr_at(handle: int, base: int, offsets: dict, *keys: str) -> int:
        cur = offsets
        for k in keys:
            cur = cur[k]
        return MemoryReader._read_pointer(handle, base + cur)

    @staticmethod
    def _read_stdvec_first(handle: int, base: int, offsets: dict, *keys: str) -> int:
        vec_off = offsets[keys[0]][keys[1]]
        begin = MemoryReader._read_pointer(handle, base + vec_off)
        if begin == 0:
            return 0
        return MemoryReader._read_pointer(handle, begin)

    # ── primitive readers ─────────────────────────────────────────

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
    def _read_utf16_string(handle: int, address: int, max_chars: int = 256) -> str:
        buffer = (ctypes.c_byte * (max_chars * 2 + 2))()
        bytes_read = ctypes.c_size_t()
        _ReadProcessMemory(
            handle,
            ctypes.c_void_p(address),
            buffer,
            ctypes.sizeof(buffer),
            ctypes.byref(bytes_read),
        )
        data = bytes(buffer[: bytes_read.value])
        null_idx = data.find(b"\x00\x00")
        if null_idx >= 0:
            data = data[:null_idx]
        return data.decode("utf-16-le", errors="replace")

    # ── process/module helpers ────────────────────────────────────

    @staticmethod
    def _get_module_info(handle: int) -> Optional[Tuple[int, int]]:
        h_mod = (ctypes.wintypes.HMODULE * 1)()
        cb_needed = ctypes.wintypes.DWORD()
        if not _EnumProcessModules(handle, h_mod, ctypes.sizeof(h_mod), ctypes.byref(cb_needed)):
            return None

        info = MODULEINFO()
        if not _GetModuleInformation(handle, h_mod[0], ctypes.byref(info), ctypes.sizeof(info)):
            return None

        return (info.lpBaseOfDll, info.SizeOfImage)

    @staticmethod
    def _get_process_name(handle: int) -> str:
        h_mod = (ctypes.wintypes.HMODULE * 1024)()
        cb_needed = ctypes.wintypes.DWORD()
        if not _EnumProcessModules(handle, h_mod, ctypes.sizeof(h_mod), ctypes.byref(cb_needed)):
            return ""

        name_buf = ctypes.create_unicode_buffer(260)
        length = _GetModuleBaseNameW(handle, h_mod[0], name_buf, 260)
        return name_buf.value if length else ""
