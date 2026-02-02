# build_agent.ps1
# Build GestureOSAgent with MediaPipe assets + UAC admin manifest (bypass UIPI injection blocks)
$ErrorActionPreference = "Stop"

Write-Host "[1/4] Activate venv if present..." -ForegroundColor Cyan
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
  . .\.venv\Scripts\Activate.ps1
}

Write-Host "[2/4] Ensure deps..." -ForegroundColor Cyan
python -m pip install -U pip | Out-Host
python -m pip install -U pyinstaller | Out-Host

Write-Host "[3/4] Build (spec)..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean GestureOSAgent.spec | Out-Host

Write-Host "[4/4] Done. Output: dist\GestureOSAgent\" -ForegroundColor Green
Write-Host "NOTE: This build requests Admin (UAC). When launched, Windows will prompt once." -ForegroundColor Yellow
