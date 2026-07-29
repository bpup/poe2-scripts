@echo off
:: ============================================================
::  One-Click PoE2 Multi-Window + AutoFollow Launcher
::  Double-click this file to run
:: ============================================================
title PoE2 Multi-Launcher
cd /d "%~dp0"

echo Auto-elevating to administrator...
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\one-click.ps1"
pause
