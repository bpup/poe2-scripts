@echo off
chcp 65001 >nul
title AutoFollow Setup
color 0A

echo ============================================
echo   AutoFollow - PoE2 Background Follow Bot
echo ============================================
echo.
echo Prerequisites (check before continuing):
echo   [ ] .NET 8 SDK x64 installed
echo   [ ] DirectX Runtime installed
echo   [ ] VC 2015 Redist installed
echo   [ ] PoE2 game client (Standalone or Steam)
echo.
echo If any are missing, install them first.
echo Download .NET 8: https://dotnet.microsoft.com/download/dotnet/8.0
echo.
pause

echo.
echo [1/4] Creating directory structure...
mkdir ExileCore2\Plugins 2>nul
echo   OK  Directories ready.

echo.
echo [2/4] Checking AutoFollow.dll...
if exist "ExileCore2\Plugins\AutoFollow.dll" (
    echo   OK  AutoFollow.dll found.
) else (
    echo   ERR AutoFollow.dll NOT found in ExileCore2\Plugins\
    echo   Please copy AutoFollow.dll to this directory.
    pause
    exit /b 1
)

echo.
echo [3/4] Checking ExileCore2 Loader.exe...
if exist "ExileCore2\Loader.exe" (
    echo   OK  Loader.exe found.
) else (
    echo   WARN Loader.exe NOT found.
    echo   You need to download ExileCore2 loader separately.
    echo   Download from: https://github.com/exCore2/ExileCore2/releases
    echo   Or run:  pwsh -File scripts\build.ps1 -FullPackage
    pause
)

echo.
echo [4/4] Setup complete!
echo.
echo ============================================
echo   HOW TO USE
echo ============================================
echo.
echo 1. Launch 3 PoE2 windows (use Process Explorer to close PoERunMutexB)
echo 2. For each follower window:
echo    a. Run ExileCore2\Loader.exe
echo    b. Select the PoE2 process PID from the list
echo    c. Press F12 to open overlay
echo    d. Set "LeaderName" to your leader's character name
echo    e. Enable AutoFollow
echo 3. Play your leader character normally - followers auto-follow!
echo.
echo For detailed instructions, see README.md
echo.
echo Press any key to exit...
pause >nul
