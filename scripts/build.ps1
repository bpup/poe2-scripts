# AutoFollow One-Click Build Script
# Usage: .\scripts\build.ps1 [-FullPackage]
#
# -NoFullPackage:  Only build AutoFollow.dll (default, fast)
# -FullPackage:   Clone ExileCore2, build everything, package into zip

param(
    [switch]$FullPackage
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== AutoFollow Build Script ===" -ForegroundColor Cyan

function Invoke-NativeCommand {
    param([string]$Cmd, [string]$WorkDir, [string]$Description)
    Write-Host "[>] $Description" -ForegroundColor Yellow
    $saved = Get-Location
    try {
        if ($WorkDir) { Set-Location $WorkDir }
        Invoke-Expression $Cmd
        if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit $LASTEXITCODE)" }
    }
    finally { Set-Location $saved }
}

# ── Step 1: Build AutoFollow.dll ────────────────────────────────────
Write-Host "`n[1/3] Building AutoFollow DLL..." -ForegroundColor Green

Invoke-NativeCommand `
    -Cmd "dotnet restore AutoFollow.csproj" `
    -WorkDir "$RepoRoot/ExileCore2Plugin" `
    -Description "Restore NuGet packages"

Invoke-NativeCommand `
    -Cmd "dotnet build AutoFollow.csproj -c Release --no-restore" `
    -WorkDir "$RepoRoot/ExileCore2Plugin" `
    -Description "Compile AutoFollow.dll"

$dllPath = "$RepoRoot/ExileCore2Plugin/bin/Release/net8.0-windows/AutoFollow.dll"
if (Test-Path $dllPath) {
    Write-Host "  OK  AutoFollow.dll  built: $dllPath" -ForegroundColor Green
} else {
    throw "AutoFollow.dll not found after build!"
}

# ── Step 2: If -FullPackage, clone & build ExileCore2 ──────────────
if ($FullPackage) {
    Write-Host "`n[2/3] Building full package (ExileCore2 + AutoFollow)..." -ForegroundColor Green

    $workDir = "$RepoRoot/build_temp"
    Remove-Item -Recurse -Force $workDir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null

    # Clone ExileCore2
    Invoke-NativeCommand `
        -Cmd "git clone --depth 1 https://github.com/exCore2/ExileCore2.git" `
        -WorkDir $workDir `
        -Description "Clone exCore2/ExileCore2"

    # Build ExileCore2 core
    Invoke-NativeCommand `
        -Cmd "dotnet restore Core/ExileCore2.csproj; dotnet build Core/ExileCore2.csproj -c Release --no-restore" `
        -WorkDir "$workDir/ExileCore2" `
        -Description "Build ExileCore2.dll"

    # Build Loader
    Invoke-NativeCommand `
        -Cmd "dotnet restore Loader/Loader.csproj; dotnet build Loader/Loader.csproj -c Release --no-restore" `
        -WorkDir "$workDir/ExileCore2" `
        -Description "Build Loader.exe"

    # ── Step 3: Assemble package ────────────────────────────────────
    Write-Host "`n[3/3] Assembling release package..." -ForegroundColor Green

    $pkgDir = "$RepoRoot/release"
    Remove-Item -Recurse -Force $pkgDir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path "$pkgDir/ExileCore2/Plugins" | Out-Null

    # Copy ExileCore2 Loader output
    Copy-Item -Recurse "$workDir/ExileCore2/Loader/bin/Release/net8.0-windows/*" "$pkgDir/ExileCore2/" -Force

    # Copy AutoFollow DLL
    Copy-Item $dllPath "$pkgDir/ExileCore2/Plugins/" -Force

    # Copy setup script & README
    Copy-Item "$RepoRoot/scripts/setup.bat" "$pkgDir/" -Force
    Copy-Item "$RepoRoot/ExileCore2Plugin/README.md" "$pkgDir/" -Force

    # Zip
    $zipPath = "$RepoRoot/AutoFollow-Release.zip"
    Compress-Archive -Path "$pkgDir/*" -DestinationPath $zipPath -Force

    Write-Host "`n  Done!  $zipPath" -ForegroundColor Green
    Write-Host "  Package contents:" -ForegroundColor Cyan
    Get-ChildItem -Recurse "$pkgDir" | ForEach-Object {
        $rel = $_.FullName.Replace($pkgDir, '.')
        Write-Host "    $rel"
    }

    # Cleanup temp
    Remove-Item -Recurse -Force $workDir -ErrorAction SilentlyContinue
}
else {
    Write-Host "`n  Done!  DLL only build complete." -ForegroundColor Green
    Write-Host "  Run with -FullPackage to build ExileCore2 + zip." -ForegroundColor DarkGray
}
