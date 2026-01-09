@echo off
cd /d "%~dp0"
start "" npm run dev
timeout /t 2 >nul
start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --app=http://localhost:5173 --new-window
