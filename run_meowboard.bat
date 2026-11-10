@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo               MEOWBOARD 🐈 Launcher
echo ========================================================

:: Check for virtual environment
if not exist ".venv\Scripts\python.exe" (
    echo [.venv not found. Initializing virtual environment...]
    py -3.12 -m venv .venv 2>nul || python -m venv .venv
    echo [Installing required dependencies...]
    .\.venv\Scripts\pip.exe install -r requirements.txt
)

:: Prefer pythonw to suppress console window
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".\.venv\Scripts\pythonw.exe" "main.py" %*
) else (
    start "" ".\.venv\Scripts\python.exe" "main.py" %*
)

exit /b 0
