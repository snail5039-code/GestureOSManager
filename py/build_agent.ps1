# build_agent.ps1
# Run this in the py/ folder (PowerShell):
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\build_agent.ps1
$ErrorActionPreference = "Stop"

# Use the current python (recommended: Python 3.10 venv)
python -m pip install -U pip pyinstaller

# Build using spec (includes MediaPipe assets)
python -m PyInstaller --noconfirm --clean .\GestureOSAgent.spec

Write-Host "`nDone. Output => .\dist\GestureOSAgent\" -ForegroundColor Green
