# PoE2 Multi-Window Launcher
# Usage: .\scripts\launch-poe.ps1 [-Accounts 3] [-PoE2Path "D:\Path of Exile 2"]
#
# -Accounts: Number of windows (default: 3)
# -PoE2Path: Path to PathOfExile.exe / PathOfExileSteam.exe
# -ExileCore2Dir: Path to ExileCore2 folder (optional, launches loader for windows 2+)

param(
    [int]$Accounts = 3,
    [string]$PoE2Path = "",
    [string]$ExileCore2Dir = ""
)

$ErrorActionPreference = "Stop"

# ── Find PoE2 ────────────────────────────────────────────────────────
if (-not $PoE2Path) {
    $candidates = @(
        "C:\Program Files (x86)\Steam\steamapps\common\Path of Exile 2\PathOfExileSteam.exe",
        "C:\Program Files (x86)\Grinding Gear Games\Path of Exile 2\PathOfExile.exe",
        "$env:PROGRAMFILES\Path of Exile 2\PathOfExile.exe",
        "${env:PROGRAMFILES(x86)}\Path of Exile 2\PathOfExile.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $PoE2Path = $c; break }
    }
}
if (-not $PoE2Path -or -not (Test-Path $PoE2Path)) {
    Write-Host "PoE2 not found. Specify with -PoE2Path" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] PoE2: $PoE2Path" -ForegroundColor Green

# ── Find handle.exe (Sysinternals) ────────────────────────────────────
$handleExe = Get-Command handle64.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $handleExe) { $handleExe = Get-Command handle.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source }
if (-not $handleExe) { $handleExe = "$env:TEMP\handle64.exe" }
if (-not (Test-Path $handleExe)) {
    Write-Host "Downloading handle.exe from Microsoft..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://live.sysinternals.com/handle64.exe" -OutFile $handleExe
}
# Accept EULA silently
& $handleExe -accepteula 2>$null
Write-Host "[OK] handle.exe: $handleExe" -ForegroundColor Green

# ── Config dirs per account ──────────────────────────────────────────
$myGames = "$env:USERPROFILE\Documents\My Games\Path of Exile 2"
$configBase = "$env:TEMP\poe2_multi_config"
Remove-Item -Recurse -Force $configBase -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== Prepare config directories ===" -ForegroundColor Cyan
Write-Host "Base config: $myGames"
Write-Host ""

# Before each launch: copy current My Games to a temp slot, 
# optionally restore a previously saved account config.

function Close-PoE2Mutex {
    param([int]$SkipPid = 0)
    $procs = Get-Process -Name "PathOfExileSteam", "PathOfExile" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.Id -eq $SkipPid) { continue }
        $result = & $handleExe -a -p $p.Id -nobanner 2>$null | Select-String "PoERunMutexB"
        if ($result) {
            $handleId = ($result -split ':')[0].Trim()
            & $handleExe -c $handleId -p $p.Id -y 2>$null
            Write-Host "  Closed mutex on PID $($p.Id)" -ForegroundColor DarkGray
        }
    }
}

function Start-PoE2Window {
    param([int]$Index)

    $accountDir = "$configBase\account$Index"
    New-Item -ItemType Directory -Force -Path $accountDir | Out-Null

    Write-Host "── Window $Index ──" -ForegroundColor Yellow

    # Close mutex from ALL previous PoE2 processes (except none, we want to close them all)
    Close-PoE2Mutex

    # Launch PoE2
    $proc = Start-Process -FilePath $PoE2Path -PassThru
    Write-Host "  Launched (PID: $($proc.Id))"
    Write-Host "  >> LOG IN TO ACCOUNT $Index NOW <<" -ForegroundColor Magenta

    # Wait for login + character select
    for ($i = 0; $i -lt 30; $i++) {
        Write-Host -NoNewline "`r  Waiting... $((30 - $i))s   "
        Start-Sleep 1
    }
    Write-Host ""

    return $proc
}

# ── Kill existing PoE2 first ─────────────────────────────────────────
Write-Host "Closing existing PoE2 processes..." -ForegroundColor DarkGray
Get-Process -Name "PathOfExileSteam", "PathOfExile" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2

# ── Launch all windows ──────────────────────────────────────────────
Write-Host ""
Write-Host "=== Launching $Accounts PoE2 windows ===" -ForegroundColor Cyan

$pids = @()
for ($i = 1; $i -le $Accounts; $i++) {
    $proc = Start-PoE2Window -Index $i
    $pids += $proc.Id

    # Save config after login (backgrounded)
    if ($i -gt 1) {
        $accountDir = "$configBase\account$i"
        Start-Sleep 5  # let config files write
        Copy-Item -Recurse "$myGames\*" "$accountDir\" -Force -ErrorAction SilentlyContinue
    }
}

# ── Summary ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== All $Accounts windows launched ===" -ForegroundColor Green
Write-Host ""
Write-Host "Window | PID   | Role" -ForegroundColor Cyan
for ($i = 0; $i -lt $pids.Count; $i++) {
    $role = if ($i -eq 0) { "LEADER (manual)" } else { "Follower (auto)" }
    Write-Host "  $($i+1)     | $($pids[$i]) | $role"
}

# ── Launch ExileCore2 for followers ─────────────────────────────────
if ($ExileCore2Dir -and (Test-Path "$ExileCore2Dir\Loader.exe")) {
    Write-Host ""
    Write-Host "=== Launching ExileCore2 Loaders ===" -ForegroundColor Cyan
    for ($i = 1; $i -lt $Accounts; $i++) {
        # Each follower needs its own ExileCore2 copy
        $ecDir = "$ExileCore2Dir`_Win$($i+1)"
        if (-not (Test-Path $ecDir)) {
            Copy-Item -Recurse $ExileCore2Dir $ecDir
        }
        Start-Process -FilePath "$ecDir\Loader.exe"
        Write-Host "  Loader #$i launched for window $($i+1) (PID: $($pids[$i]))"
        Write-Host "    → Select PID $($pids[$i]) in the Loader window" -ForegroundColor DarkYellow
        Start-Sleep 3
    }
}

Write-Host ""
Write-Host "Done! Now:" -ForegroundColor Green
Write-Host "  1. Select PID in each Loader window"
Write-Host "  2. F12 → set LeaderName → Enable"
Write-Host "  3. Play on window 1"
