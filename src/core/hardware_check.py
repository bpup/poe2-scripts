"""
启动时硬件/环境预检模块。

检查项：
- ViGEmBus 驱动安装状态
- 管理员权限
- Python 依赖 (vgamepad, psutil 等)
- 可选：HidHide 安装状态

Usage:
    from src.core.hardware_check import run_all_checks

    results = run_all_checks()
    if results.all_ok:
        print("一切就绪")
    else:
        for err in results.errors:
            print(err.message)
"""

import ctypes
import importlib
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CheckResult:
    passed: bool
    name: str
    message: str
    fix_hint: str = ""
    severity: str = "error"  # "error" | "warning" | "info"


@dataclass
class AllChecksResult:
    results: List[CheckResult] = field(default_factory=list)
    errors: List[CheckResult] = field(default_factory=list)
    warnings: List[CheckResult] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return len(self.errors) == 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


def check_admin_privileges() -> CheckResult:
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False

    if is_admin:
        return CheckResult(
            passed=True,
            name="管理员权限",
            message="✓ 已获取管理员权限",
            severity="info",
        )
    else:
        return CheckResult(
            passed=False,
            name="管理员权限",
            message="✗ 未以管理员身份运行",
            fix_hint="请右键点击程序，选择「以管理员身份运行」",
            severity="error",
        )


def check_vigembus_driver() -> CheckResult:
    try:
        result = subprocess.run(
            ["sc", "query", "ViGEmBus"],
            capture_output=True, text=True, timeout=10,
        )
        if "RUNNING" in result.stdout:
            return CheckResult(
                passed=True,
                name="ViGEmBus 驱动",
                message="✓ ViGEmBus 驱动运行中",
                severity="info",
            )
        elif "STOPPED" in result.stdout:
            return CheckResult(
                passed=False,
                name="ViGEmBus 驱动",
                message="✗ ViGEmBus 驱动已安装但未运行",
                fix_hint="请尝试重启电脑，或重新安装 ViGEmBus",
                severity="error",
            )
        else:
            return CheckResult(
                passed=False,
                name="ViGEmBus 驱动",
                message="✗ 未安装 ViGEmBus 驱动",
                fix_hint="请从 https://github.com/nefarius/ViGEmBus/releases 下载安装",
                severity="error",
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CheckResult(
            passed=False,
            name="ViGEmBus 驱动",
            message="✗ 无法检查 ViGEmBus 状态",
            fix_hint="请确认 ViGEmBus 驱动已安装",
            severity="error",
        )


def check_vgamepad_library() -> CheckResult:
    try:
        importlib.import_module("vgamepad")
        return CheckResult(
            passed=True,
            name="vgamepad 库",
            message="✓ vgamepad Python 库已安装",
            severity="info",
        )
    except ImportError:
        return CheckResult(
            passed=False,
            name="vgamepad 库",
            message="✗ vgamepad 库未安装",
            fix_hint="请在终端运行: pip install vgamepad",
            severity="error",
        )


def check_psutil_library() -> CheckResult:
    try:
        importlib.import_module("psutil")
        return CheckResult(
            passed=True,
            name="psutil 库",
            message="✓ psutil 库已安装",
            severity="info",
        )
    except ImportError:
        return CheckResult(
            passed=False,
            name="psutil 库",
            message="✗ psutil 库未安装",
            fix_hint="请在终端运行: pip install psutil",
            severity="error",
        )


def check_pywin32_library() -> CheckResult:
    try:
        importlib.import_module("win32api")
        importlib.import_module("win32gui")
        importlib.import_module("win32process")
        return CheckResult(
            passed=True,
            name="pywin32 库",
            message="✓ pywin32 库已安装",
            severity="info",
        )
    except ImportError:
        return CheckResult(
            passed=False,
            name="pywin32 库",
            message="✗ pywin32 库未安装",
            fix_hint="请在终端运行: pip install pywin32",
            severity="error",
        )


def check_hidhide_driver() -> CheckResult:
    try:
        result = subprocess.run(
            ["sc", "query", "HidHide"],
            capture_output=True, text=True, timeout=10,
        )
        if "RUNNING" in result.stdout:
            return CheckResult(
                passed=True,
                name="HidHide 驱动",
                message="✓ HidHide 驱动运行中",
                severity="info",
            )
        else:
            return CheckResult(
                passed=False,
                name="HidHide 驱动",
                message="⚠ 未安装 HidHide（可选）",
                fix_hint="推荐安装 HidHide 以隐藏物理手柄，避免 P2 操作干扰。"
                        "从 https://github.com/nefarius/HidHide/releases 下载",
                severity="warning",
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CheckResult(
            passed=False,
            name="HidHide 驱动",
            message="⚠ 无法检测 HidHide（可选）",
            fix_hint="推荐安装 HidHide 以隐藏物理手柄",
            severity="warning",
        )


def run_all_checks() -> AllChecksResult:
    checks = [
        check_admin_privileges(),
        check_vigembus_driver(),
        check_vgamepad_library(),
        check_psutil_library(),
        check_pywin32_library(),
        check_hidhide_driver(),
    ]

    result = AllChecksResult(results=checks)
    for c in checks:
        if c.severity == "error" and not c.passed:
            result.errors.append(c)
        elif c.severity == "warning" and not c.passed:
            result.warnings.append(c)

    return result


def format_check_results(result: AllChecksResult) -> str:
    lines = []
    for c in result.results:
        lines.append(f"  {c.message}")
        if c.fix_hint:
            lines.append(f"    → {c.fix_hint}")
    if result.errors:
        lines.append(f"\n❌ {len(result.errors)} 个错误需要修复")
    if result.warnings:
        lines.append(f"⚠️ {len(result.warnings)} 个警告")
    if result.all_ok and not result.warnings:
        lines.append("\n✅ 环境检查通过！")
    return "\n".join(lines)
