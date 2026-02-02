# build_agent.ps1
# Build GestureOSAgent with MediaPipe + PySide6 HUD overlay support.

$ErrorActionPreference = "Stop"

Write-Host "[1/6] Move to py folder..." -ForegroundColor Cyan
Set-Location $PSScriptRoot

Write-Host "[2/6] Activate venv (if exists)..." -ForegroundColor Cyan
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
  . .\.venv\Scripts\Activate.ps1
}

Write-Host "[3/6] Upgrade pip/pyinstaller..." -ForegroundColor Cyan
python -m pip install -U pip | Out-Host
python -m pip install -U pyinstaller | Out-Host

Write-Host "[4/6] Ensure runtime deps..." -ForegroundColor Cyan
if (Test-Path ".\requirements.txt") {
  python -m pip install -r requirements.txt | Out-Host
}

Write-Host "[5/6] Build (spec)..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean GestureOSAgent.spec | Out-Host

Write-Host "[6/6] Done. Output => dist\GestureOSAgent\" -ForegroundColor Green
Write-Host "If HUD overlay still doesn't show, open %TEMP%\GestureOS_HUD.log and %APPDATA%\GestureOS Manager\agent.log" -ForegroundColor Yellow
