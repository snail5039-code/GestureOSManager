# Build GestureOSAgent with a spec that forces inclusion of hands_agent + mediapipe assets
$ErrorActionPreference = "Stop"

Write-Host "==> Cleaning dist/build/spec cache"
Remove-Item -Recurse -Force .\dist,.\build -ErrorAction SilentlyContinue

Write-Host "==> Building with PyInstaller spec"
python -m PyInstaller --noconfirm --clean .\GestureOSAgent.spec

Write-Host "`nDONE. Output:"
Get-ChildItem .\dist\GestureOSAgent -Force
