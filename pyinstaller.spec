# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

a = Analysis(
    ["src/app.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "pynput",
        "pynput.keyboard._win32",
        "pynput._util.win32",
        "win32process",
        "win32gui",
        "win32api",
        "win32con",
        "tkinter",
        "vgamepad",
        "vgamepad.win.vigem",
        "vgamepad.win.vigem.vigem_client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

a.datas += [("config/nav-follow.yaml", "config/nav-follow.yaml", "DATA")]

# Bundle ViGEmClient.dll from the vgamepad package
try:
    a.binaries += collect_dynamic_libs("vgamepad")
except Exception:
    pass

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="poe2-follow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
