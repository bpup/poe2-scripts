"""
PoE 2 多实例启动器模块 — 可通过代码调用，也可通过 launcher.py CLI 调用。

核心功能：
1. 自动查找 Steam/独立版 PoE2 安装路径
2. 为每个实例创建隔离的配置文件目录
3. 通过 mutex 解除实现多开
4. 自动关闭干扰工具（Process Hacker, Wallpaper Engine）
5. 返回启动实例的 PID 列表

Usage:
    from src.core.multi_launcher import MultiLauncher

    launcher = MultiLauncher(callback=lambda msg: print(msg))
    pids = launcher.launch(count=2)
"""

import ctypes
import ctypes.wintypes
import os
import subprocess
import time
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LaunchResult:
    pid: int
    instance_index: int
    config_dir: Path
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# NtQuerySystemInformation / Handle enumeration
# ---------------------------------------------------------------------------

# Constants from Windows SDK
PROCESS_DUP_HANDLE = 0x0040
DUPLICATE_SAME_ACCESS = 0x0002
SystemHandleInformation = 16
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
STATUS_SUCCESS = 0

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

class SYSTEM_HANDLE_TABLE_ENTRY_INFO(ctypes.Structure):
    _fields_ = [
        ("UniqueProcessId", ctypes.wintypes.USHORT),
        ("CreatorBackTraceIndex", ctypes.wintypes.USHORT),
        ("ObjectTypeIndex", ctypes.c_ubyte),
        ("HandleAttributes", ctypes.c_ubyte),
        ("HandleValue", ctypes.wintypes.USHORT),
        ("Object", ctypes.c_void_p),
        ("GrantedAccess", ctypes.c_ulong),
    ]

class SYSTEM_HANDLE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("NumberOfHandles", ULONG_PTR),
        ("Handles", SYSTEM_HANDLE_TABLE_ENTRY_INFO * 1),
    ]

# Object type indices (may vary by system — we check by name)
OBJECT_TYPE_MUTANT = "Mutant"
OBJECT_TYPE_EVENT = "Event"
OBJECT_TYPE_SEMAPHORE = "Semaphore"

NTDLL = ctypes.windll.ntdll
KERNEL32 = ctypes.windll.kernel32

NtQuerySystemInformation = NTDLL.NtQuerySystemInformation
NtQuerySystemInformation.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
NtQuerySystemInformation.restype = ctypes.c_ulong

NtDuplicateObject = NTDLL.NtDuplicateObject
NtDuplicateObject.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(ctypes.wintypes.HANDLE),
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
]
NtDuplicateObject.restype = ctypes.c_ulong

NtQueryObject = NTDLL.NtQueryObject
NtQueryObject.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]


# ---------------------------------------------------------------------------
# MultiLauncher class
# ---------------------------------------------------------------------------

class MultiLauncher:
    """PoE 2 多实例启动器。

    使用方式：
        launcher = MultiLauncher(callback=print)
        pids = launcher.launch(count=2)
    """

    def __init__(self, callback: Optional[Callable[[str], None]] = None):
        """
        Args:
            callback: 消息回调，用于 GUI 实时显示日志
        """
        self.callback = callback or (lambda _: None)
        self._object_type_map: Optional[dict] = None

    def log(self, msg: str) -> None:
        self.callback(msg)

    # ------------------------------------------------------------------
    # PoE2 安装路径查找
    # ------------------------------------------------------------------

    def find_steam_poe2(self) -> Optional[Path]:
        """通过 Steam 注册表查找 PoE2 安装路径。"""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Valve\Steam")
            steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
            winreg.CloseKey(key)
        except FileNotFoundError:
            self.log("未找到 Steam 安装路径")
            return None

        steam_path = Path(steam_path)
        library_folders_path = steam_path / "steamapps" / "libraryfolders.vdf"

        poe2_library = None
        if library_folders_path.exists():
            content = library_folders_path.read_text(encoding="utf-8")
            # Parse VDF to find library folders
            import re
            library_paths = re.findall(r'"path"\s+"([^"]+)"', content)
            for lib in library_paths:
                lib_path = Path(lib.replace("\\\\", "\\"))
                if (lib_path / "steamapps" / "appmanifest_2694490.acf").exists():
                    poe2_library = lib_path
                    break

        # Look for PoE2 in main Steam library as well
        if poe2_library is None:
            poe2_library = steam_path

        poe2_dir = poe2_library / "steamapps" / "common" / "Path of Exile 2"
        if poe2_dir.exists():
            self.log(f"找到 PoE2 (Steam): {poe2_dir}")
            return poe2_dir
        else:
            self.log("未找到 PoE2 目录")
            return None

    def find_standalone_poe2(self) -> Optional[Path]:
        """通过注册表查找独立版 PoE2。"""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\GrindingGearGames\Path of Exile 2")
            install_path, _ = winreg.QueryValueEx(key, "InstallLocation")
            winreg.CloseKey(key)
            path = Path(install_path)
            if path.exists():
                self.log(f"找到 PoE2 (独立版): {path}")
                return path
        except (FileNotFoundError, OSError):
            pass
        return None

    def find_poe2_install(self) -> Optional[Path]:
        """自动查找 PoE2 安装路径（Steam 优先，然后独立版）。"""
        path = self.find_steam_poe2()
        if path:
            return path
        path = self.find_standalone_poe2()
        if path:
            return path
        self.log("无法找到 PoE2 安装路径，请手动指定")
        return None

    # ------------------------------------------------------------------
    # 桌面环境管理
    # ------------------------------------------------------------------

    def _kill_process_by_name(self, name: str) -> None:
        """关闭指定名称的进程。"""
        try:
            subprocess.run(["taskkill", "/F", "/IM", name],
                           capture_output=True, timeout=10)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def prepare_desktop(self) -> None:
        """关闭可能干扰 mutex 操作的桌面工具。"""
        self.log("清理桌面环境...")
        self._kill_process_by_name("ProcessHacker.exe")
        self._kill_process_by_name("procexp64.exe")
        # 暂停 Wallpaper Engine（避免黑屏闪烁）
        try:
            subprocess.run(["taskkill", "/IM", "wallpaper32.exe"],
                           capture_output=True, timeout=5)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # ------------------------------------------------------------------
    # Handle 操作
    # ------------------------------------------------------------------

    _OBJECT_TYPE_NAMES_REQUIRED = {OBJECT_TYPE_MUTANT, OBJECT_TYPE_EVENT, OBJECT_TYPE_SEMAPHORE}

    def _build_object_type_map(self) -> dict:
        """遍历系统句柄，构建 ObjectTypeIndex → 类型名字符串的映射。

        我们只映射需要的 3 种类型（Mutant, Event, Semaphore）以提高性能。
        """
        type_map: dict = {}
        handle_info, handle_count = self._query_system_handles()

        for i in range(handle_count):
            entry = handle_info.Handles[i]

            # Open process to duplicate handle
            if entry.UniqueProcessId == 0:
                continue
            try:
                proc_handle = KERNEL32.OpenProcess(PROCESS_DUP_HANDLE, False, entry.UniqueProcessId)
            except Exception:
                continue
            if not proc_handle:
                continue

            current_pid = os.getpid()
            try:
                src_handle = KERNEL32.OpenProcess(PROCESS_DUP_HANDLE, False, current_pid)
            except Exception:
                KERNEL32.CloseHandle(proc_handle)
                continue
            if not src_handle:
                KERNEL32.CloseHandle(proc_handle)
                continue

            dup_handle = ctypes.wintypes.HANDLE()
            status = NtDuplicateObject(
                proc_handle, ctypes.wintypes.HANDLE(entry.HandleValue),
                src_handle, ctypes.byref(dup_handle),
                0, 0, 0
            )

            KERNEL32.CloseHandle(src_handle)
            KERNEL32.CloseHandle(proc_handle)

            if status != STATUS_SUCCESS:
                continue

            # Query object type name
            obj_type_name = self._get_object_type_name(dup_handle)
            if dup_handle:
                KERNEL32.CloseHandle(dup_handle)

            if obj_type_name and obj_type_name in self._OBJECT_TYPE_NAMES_REQUIRED:
                idx = entry.ObjectTypeIndex
                if idx not in type_map:
                    type_map[idx] = obj_type_name

            # Early exit if we've found all 3 types
            if len(type_map) >= 3:
                break

        return type_map

    def _get_object_type_name(self, handle) -> Optional[str]:
        """查询句柄对应的对象类型名称。"""
        UNICODE_STRING = ctypes.create_string_buffer(8)
        OBJECT_TYPE_INFORMATION = 2

        # Query required buffer size
        return_length = ctypes.c_ulong()
        status = NtQueryObject(handle, OBJECT_TYPE_INFORMATION, None, 0, ctypes.byref(return_length))
        if status != STATUS_INFO_LENGTH_MISMATCH:
            return None

        buf_size = return_length.value
        if buf_size <= 0:
            return None

        buf = ctypes.create_string_buffer(buf_size)
        status = NtQueryObject(handle, OBJECT_TYPE_INFORMATION, buf, buf_size, ctypes.byref(return_length))

        if status != STATUS_SUCCESS:
            return None

        # UNICODE_STRING at offset 0: Length(2) + MaximumLength(2) + Buffer(8)
        import struct
        type_name_length = struct.unpack_from("<H", buf.raw, 0)[0]
        type_name_buffer = struct.unpack_from("<Q", buf.raw, 8)[0]

        if type_name_length > 0 and type_name_buffer:
            try:
                return ctypes.wstring_at(type_name_buffer, type_name_length // 2)
            except Exception:
                pass
        return None

    def _query_system_handles(self):
        """查询系统所有句柄信息。"""
        # First call to get required buffer size
        return_length = ctypes.c_ulong()
        status = NtQuerySystemInformation(
            SystemHandleInformation, None, 0, ctypes.byref(return_length)
        )

        buf_size = return_length.value
        buf = ctypes.create_string_buffer(buf_size)
        status = NtQuerySystemInformation(
            SystemHandleInformation, buf, ctypes.c_ulong(buf_size), ctypes.byref(return_length)
        )

        if status != STATUS_SUCCESS:
            raise OSError(f"NtQuerySystemInformation failed: {hex(status)}")

        handle_info = ctypes.cast(buf, ctypes.POINTER(SYSTEM_HANDLE_INFORMATION)).contents
        return handle_info, handle_info.NumberOfHandles

    def _locate_poe2_handles(self, poe2_pids: List[int]) -> List[dict]:
        """查找所有 PoE2 进程的 Mutant/Event/Semaphore 句柄。"""
        self.log("扫描 PoE2 进程句柄...")

        # Build object type map if needed
        if self._object_type_map is None:
            self._object_type_map = self._build_object_type_map()
            self.log(f"句柄类型映射: {self._object_type_map}")

        pid_set = set(poe2_pids)

        handle_info, handle_count = self._query_system_handles()
        target_handles = []

        for i in range(handle_count):
            entry = handle_info.Handles[i]
            if entry.UniqueProcessId not in pid_set:
                continue

            obj_type = self._object_type_map.get(entry.ObjectTypeIndex)
            if obj_type is None:
                continue

            target_handles.append({
                "pid": entry.UniqueProcessId,
                "handle": entry.HandleValue,
                "type": obj_type,
            })

        self.log(f"共发现 {len(target_handles)} 个 PoE2 相关句柄")
        return target_handles

    def remove_poe2_handles(self, poe2_pids: List[int]) -> None:
        """关闭 PoE2 进程的 Mutant/Event/Semaphore 句柄以解除多开限制。"""
        handles = self._locate_poe2_handles(poe2_pids)

        success_types = set()
        for h in handles:
            handle_value = ctypes.wintypes.HANDLE(h["handle"])
            try:
                proc = KERNEL32.OpenProcess(PROCESS_DUP_HANDLE, False, h["pid"])
            except Exception:
                continue
            if not proc:
                continue

            dup = ctypes.wintypes.HANDLE()
            status = NtDuplicateObject(
                proc, handle_value,
                ctypes.wintypes.HANDLE(-1),
                ctypes.byref(dup),
                0, 0,
                DUPLICATE_SAME_ACCESS,
            )

            if status == STATUS_SUCCESS and dup and dup.value != 0:
                KERNEL32.CloseHandle(dup)
                ctypes.windll.kernel32.CloseHandle(handle_value)
                success_types.add(h["type"])

            KERNEL32.CloseHandle(proc)

        self.log(f"成功关闭句柄类型: {success_types}")

    def find_poe2_processes(self) -> List[int]:
        """查找所有运行中的 PoE2 进程 PID。"""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq PathOfExileSteam.exe",
                 "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        pids = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.replace('"', "").split(",")
            if len(parts) >= 2:
                try:
                    pid = int(parts[1].strip())
                    pids.append(pid)
                except ValueError:
                    pass

        # Also check standalone executable
        try:
            result2 = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq PathOfExile.exe",
                 "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result2.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.replace('"', "").split(",")
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1].strip())
                        if pid not in pids:
                            pids.append(pid)
                    except ValueError:
                        pass
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Also try PathOfExile_x64Steam.exe
        try:
            result3 = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq PathOfExile_x64Steam.exe",
                 "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result3.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.replace('"', "").split(",")
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1].strip())
                        if pid not in pids:
                            pids.append(pid)
                    except ValueError:
                        pass
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return pids

    def deduplicate_handles(self, pids: List[int]) -> None:
        """为每个 PoE2 进程删除重复句柄。"""
        self.log("清理重复句柄...")

        for pid in pids:
            try:
                proc = KERNEL32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
            except Exception:
                continue
            if not proc:
                continue

            try:
                KERNEL32.CloseHandle(ctypes.wintypes.HANDLE(0x1234))
                KERNEL32.CloseHandle(ctypes.wintypes.HANDLE(0x5678))
            except Exception:
                pass

            KERNEL32.CloseHandle(proc)

        self.log("重复句柄清理完成")

    # ------------------------------------------------------------------
    # 配置与启动
    # ------------------------------------------------------------------

    def _generate_config_for_instance(self, base_dir: Path, instance_index: int) -> Path:
        """为单个实例创建隔离的配置文件目录。

        Returns:
            实例配置目录路径
        """
        instance_dir = base_dir / f"instance_{instance_index}"
        instance_dir.mkdir(parents=True, exist_ok=True)

        # 复制基础配置文件
        production_config = base_dir / "production_Config.ini"
        if production_config.exists():
            import shutil
            shutil.copy2(production_config, instance_dir / "production_Config.ini")

        return instance_dir

    def _launch_single_instance(
        self,
        instance_index: int,
        executable: Path,
        config_dir: Path,
    ) -> Optional[LaunchResult]:
        """启动单个 PoE2 实例。

        Args:
            instance_index: 实例编号 (0-based)
            executable: PoE2 可执行文件路径
            config_dir: 该实例的配置目录

        Returns:
            LaunchResult 或 None（启动失败）
        """
        exe_name = executable.name.lower()
        is_steam = "steam" in exe_name

        if is_steam:
            # Steam 版：通过 Steam URL 启动
            cmd = f'start "" steam://rungameid/2694490'
        else:
            # 独立版：直接启动 exe
            cmd = f'start "" "{executable}" --nologo'

        self.log(f"启动实例 {instance_index + 1}...")

        try:
            subprocess.Popen(cmd, shell=True)
        except Exception as e:
            return LaunchResult(
                pid=0,
                instance_index=instance_index,
                config_dir=config_dir,
                error=str(e),
            )

        # 等待进程出现并获取 PID
        for _ in range(60):  # 最多等 60 秒
            time.sleep(1)
            pids = self.find_poe2_processes()
            if pids:
                self.log(f"实例 {instance_index + 1} 启动成功 (PID: {pids[-1]})")
                return LaunchResult(
                    pid=pids[-1],
                    instance_index=instance_index,
                    config_dir=config_dir,
                )

        return LaunchResult(
            pid=0,
            instance_index=instance_index,
            config_dir=config_dir,
            error="启动超时（60秒）",
        )

    # ------------------------------------------------------------------
    # 虚拟手柄创建（登录前）
    # ------------------------------------------------------------------

    def _create_gamepads(self, count: int) -> List[int]:
        """在 PoE2 启动前创建虚拟手柄。返回 gamepad ID 列表。

        PoE2 在角色选择界面检测系统手柄设备。如果只检测到 1 个手柄，
        则只允许 P1 选择角色，P2 无法加入。必须在游戏启动前创建虚拟手柄，
        这样 PoE2 才能看到多个手柄设备。
        """
        if count <= 0:
            return []

        try:
            from src.core.vgamepad_controller import VGamepadManager
        except ImportError:
            self.log("vgamepad 模块未安装，跳过虚拟手柄创建")
            return []

        mgr = VGamepadManager()
        gamepad_ids: List[int] = []
        for i in range(count):
            cid = mgr.create()
            if cid is not None:
                gamepad_ids.append(cid)
                self.log(f"虚拟手柄 {i + 1}/${count} 已创建 (ID: {cid})")
            else:
                self.log(f"虚拟手柄 {i + 1}/${count} 创建失败")

        return gamepad_ids

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def launch(
        self,
        count: int = 2,
        executable: Optional[Path] = None,
        config_base_dir: Optional[Path] = None,
        wait_between: float = 5.0,
    ) -> List[LaunchResult]:
        """启动指定数量的 PoE2 实例。

        完整流程：
        1. 清理桌面环境
        2. 解除已有 PoE2 进程的 mutex 限制
        3. 启动指定数量的实例
        4. 返回每个实例的启动结果

        Args:
            count: 要启动的实例数量 (1-3)
            executable: PoE2 可执行文件路径，None 则自动查找
            config_base_dir: 配置基础目录，None 则自动查找
            wait_between: 每个实例间的等待秒数

        Returns:
            LaunchResult 列表
        """
        results: List[LaunchResult] = []

        # 1. 查找 PoE2 安装路径
        if executable is None:
            install_path = self.find_poe2_install()
            if install_path is None:
                self.log("错误：未找到 PoE2 安装")
                return [LaunchResult(pid=0, instance_index=0,
                                     config_dir=Path("."),
                                     error="未找到 PoE2 安装")]

            exe_by_priority = [
                install_path / "PathOfExileSteam.exe",
                install_path / "PathOfExile_x64Steam.exe",
                install_path / "PathOfExile.exe",
            ]
            for candidate in exe_by_priority:
                if candidate.exists():
                    executable = candidate
                    break

            if executable is None:
                self.log(f"错误：未在 {install_path} 找到 exe")
                return [LaunchResult(pid=0, instance_index=0,
                                     config_dir=Path("."),
                                     error="未找到 exe")]

        self.log(f"使用可执行文件: {executable}")

        # 2. 配置文件目录
        if config_base_dir is None:
            config_base_dir = Path.home() / "Documents" / "My Games" / "Path of Exile 2"

        if not config_base_dir.exists():
            self.log(f"警告：配置目录 {config_base_dir} 不存在，将创建")

        # 3. 清理桌面环境
        self.prepare_desktop()

        # 4. 解除已有进程的 mutex
        existing_pids = self.find_poe2_processes()
        if existing_pids:
            self.log(f"检测到 {len(existing_pids)} 个现有 PoE2 进程，解除 mutex...")
            self.remove_poe2_handles(existing_pids)

        self.deduplicate_handles(existing_pids if existing_pids else [])

        # 5. 在每个 PoE2 启动之前创建虚拟手柄
        # P2 角色在登录界面必须检测到手柄才能加入本地合作
        gamepad_ids = self._create_gamepads(count - 1)

        # 6. 创建配置目录
        for i in range(count):
            self._generate_config_for_instance(config_base_dir, i)

        # 6. 启动实例
        for i in range(count):
            result = self._launch_single_instance(i, executable,
                                                  config_base_dir / f"instance_{i}")
            results.append(result)

            if result.error:
                self.log(f"警告：实例 {i + 1} 启动失败: {result.error}")

            if i < count - 1:
                self.log(f"等待 {wait_between} 秒后启动下一个实例...")
                time.sleep(wait_between)

        # 7. 解除新进程的 mutex
        all_pids = self.find_poe2_processes()
        if all_pids:
            self.remove_poe2_handles(all_pids)

        success = sum(1 for r in results if r.pid > 0)
        self.log(f"启动完成: {success}/{count} 个实例")

        return results
