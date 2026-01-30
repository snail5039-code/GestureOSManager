# Build GestureOSAgent (onedir) with forced hands_agent + mediapipe assets
$ErrorActionPreference = "Stop"

Write-Host "==> Cleaning dist/build"
Remove-Item -Recurse -Force .\dist,.\build -ErrorAction SilentlyContinue

Write-Host "==> Building (onedir) with spec"
python -m PyInstaller --noconfirm --clean .\GestureOSAgent-onedir.spec

Write-Host "`nDONE. Output folder:"
Get-ChildItem .\dist\GestureOSAgent -Force
