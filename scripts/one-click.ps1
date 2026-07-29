#Requires -RunAsAdministrator
<#
.SYNOPSIS
    One-click launch: PoE2 multi-window + ExileCore2 Loaders
.DESCRIPTION
    1. Kills existing PoE2 processes
    2. Closes PoERunMutexB between launches
    3. Launches N windows, waits for manual login per window
    4. Optionally launches ExileCore2 Loaders for follower windows
.NOTES
    Config: edit one-click-config.ps1
    Double-click one-click.bat to run.
#>

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Load config ──────────────────────────────────────────────────────
$configFile = "$scriptDir\one-click-config.ps1"
if (Test-Path $configFile) { . $configFile }
if (-not $WINDOWS)       { $WINDOWS = 3 }
if (-not $LOGIN_WAIT)    { $LOGIN_WAIT = 90 }

Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  PoE2 Multi-Window One-Click Launcher    ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host "  Windows: $WINDOWS | Login wait: ${LOGIN_WAIT}s" -ForegroundColor DarkGray
if ($EXILECORE2_DIR) { Write-Host "  ExileCore2: $EXILECORE2_DIR" -ForegroundColor DarkGray }
Write-Host ""

# ── Find PoE2 executable ────────────────────────────────────────────
if (-not $POE2_PATH) {
    $candidates = @(
        "C:\Program Files (x86)\Steam\steamapps\common\Path of Exile 2\PathOfExileSteam.exe",
        "C:\Program Files\Steam\steamapps\common\Path of Exile 2\PathOfExileSteam.exe",
        "C:\Program Files (x86)\Grinding Gear Games\Path of Exile 2\PathOfExile.exe",
        "$env:PROGRAMFILES\Path of Exile 2\PathOfExile.exe",
        "${env:PROGRAMFILES(x86)}\Path of Exile 2\PathOfExile.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $POE2_PATH = $c; break }
    }
}
if (-not $POE2_PATH -or -not (Test-Path $POE2_PATH)) {
    Write-Host "[FATAL] PoE2 not found. Set `$POE2_PATH in one-click-config.ps1" -ForegroundColor Red
    pause; exit 1
}
Write-Host "[✓] PoE2: $POE2_PATH" -ForegroundColor Green

# ── Find / download handle.exe ───────────────────────────────────────
$handleExe = "$env:TEMP\handle64.exe"
$handleFound = (Get-Command handle64.exe -ErrorAction SilentlyContinue) -or
               (Get-Command handle.exe -ErrorAction SilentlyContinue)
if ($handleFound) {
    $handleExe = (Get-Command handle64.exe, handle.exe -ErrorAction SilentlyContinue |
                  Select-Object -First 1).Source
} elseif (-not (Test-Path $handleExe)) {
    Write-Host "[ ] Downloading handle64.exe (Sysinternals)..." -ForegroundColor Yellow
    Invoke-WebRequest "https://live.sysinternals.com/handle64.exe" -OutFile $handleExe
}
& $handleExe -accepteula 2>$null
Write-Host "[✓] handle.exe: $handleExe" -ForegroundColor Green

# ── Helper: close PoERunMutexB on a process ─────────────────────────
function Close-Mutex {
    param([int]$Pid)
    $lines = & $handleExe -a -p $Pid -nobanner 2>$null
    foreach ($line in $lines) {
        if ($line -match '^\s*([0-9A-Fa-f]+):\s*(Mutant|MutantEx)\s+.*PoERunMutexB') {
            $hid = $matches[1]
            & $handleExe -c $hid -p $Pid -y 2>$null
            return $true
        }
    }
    return $false
}

function Close-AllMutexes {
    $procs = Get-Process -Name "PathOfExileSteam", "PathOfExile" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        Close-Mutex -Pid $p.Id | Out-Null
    }
}

# ── Helper: countdown ────────────────────────────────────────────────
function Show-Countdown {
    param([int]$Seconds, [string]$Msg)
    for ($i = $Seconds; $i -gt 0; $i--) {
        Write-Host -NoNewline "`r  $Msg $i s  " -ForegroundColor Yellow
        Start-Sleep 1
    }
    Write-Host "`r  $Msg done.     " -ForegroundColor Green
}

# ══════════════════════════════════════════════════════════════════════
#  Phase 1: Kill everything, start fresh
# ══════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "── Phase 1: Clean Slate ────────────────────" -ForegroundColor Cyan
Get-Process -Name "PathOfExileSteam", "PathOfExile" -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name "Loader" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
Write-Host "  All PoE2/Loader processes killed." -ForegroundColor DarkGray

# ══════════════════════════════════════════════════════════════════════
#  Phase 2: Launch PoE2 windows one by one
# ══════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "── Phase 2: Launch PoE2 Windows ─────────────" -ForegroundColor Cyan
Write-Host "  Please log in manually for each window." -ForegroundColor Yellow
Write-Host ""

$pids = @()
for ($i = 1; $i -le $WINDOWS; $i++) {
    $role = if ($i -eq 1) { "*** LEADER ***" } else { "Follower #$($i-1)" }
    Write-Host "┌─────────────────────────────────────────┐" -ForegroundColor Cyan
    Write-Host "│  Window $i / $WINDOWS : $role" -ForegroundColor White
    Write-Host "└─────────────────────────────────────────┘" -ForegroundColor Cyan

    # Close mutex from all existing PoE2 processes
    Close-AllMutexes

    # Launch
    $proc = Start-Process -FilePath $POE2_PATH -PassThru
    $pids += $proc.Id
    Write-Host "  PID: $($proc.Id)" -ForegroundColor DarkGray

    Show-Countdown -Seconds $LOGIN_WAIT -Msg "Login & select character..."
    Write-Host ""
}

Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  All $WINDOWS windows launched!                ║" -ForegroundColor Green
Write-Host "╠══════════════════════════════════════════╣" -ForegroundColor Green
for ($i = 0; $i -lt $pids.Count; $i++) {
    $r = if ($i -eq 0) { "LEADER" } else { "Follower $i" }
    Write-Host ("║  Win " + ($i+1) + " | PID " + $pids[$i]).PadRight(35) + " | $r ║" -ForegroundColor White
}
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Green

# ══════════════════════════════════════════════════════════════════════
#  Phase 3: Launch ExileCore2 Loaders
# ══════════════════════════════════════════════════════════════════════
if ($EXILECORE2_DIR -and (Test-Path "$EXILECORE2_DIR\Loader.exe")) {
    Write-Host ""
    Write-Host "── Phase 3: Launch ExileCore2 Loaders ──────" -ForegroundColor Cyan

    for ($i = 1; $i -lt $WINDOWS; $i++) {
        $winNum = $i + 1
        $ecDir = "$EXILECORE2_DIR`_Win$winNum"

        Write-Host "  Loader for window $winNum..." -ForegroundColor White

        if (-not (Test-Path $ecDir)) {
            Copy-Item -Recurse $EXILECORE2_DIR $ecDir
            Write-Host "    Created: $ecDir" -ForegroundColor DarkGray
        }

        Start-Process -FilePath "$ecDir\Loader.exe" -WorkingDirectory $ecDir
        Write-Host "    Launched. Select PID $($pids[$i])" -ForegroundColor Yellow
        Start-Sleep 2
    }

    Write-Host ""
    Write-Host "  In each Loader window:" -ForegroundColor Yellow
    Write-Host "    1) Select the PoE2 PID shown above" -ForegroundColor DarkGray
    Write-Host "    2) Press F12 → AutoFollow → set Leader Name → Enable" -ForegroundColor DarkGray
}
else {
    Write-Host ""
    Write-Host "  Set `$EXILECORE2_DIR in one-click-config.ps1 to auto-launch Loaders." -ForegroundColor DarkGray
}

# ══════════════════════════════════════════════════════════════════════
#  Done
# ══════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  ALL DONE — Go play!                    ║" -ForegroundColor Green
Write-Host "╠══════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "║  Win 1: Your leader (manual control)     ║" -ForegroundColor Green
Write-Host "║  Win 2+: Followers (auto-follow)         ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Green
