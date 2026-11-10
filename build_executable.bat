@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo          MEOWBOARD 🐈 Standalone Executable Build
echo ========================================================

:: Check for virtual environment
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR: .venv not found. Please run run_meowboard.bat first to set up environment.]
    pause
    exit /b 1
)

echo [1/3] Generating fresh icons and audio assets...
.\.venv\Scripts\python.exe scripts\generate_assets.py

echo [2/3] Building MEOWBOARD with PyInstaller...
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm meowboard.spec

if %errorlevel% neq 0 (
    echo [ERROR: PyInstaller build failed!]
    pause
    exit /b 1
)

echo [3/3] Build complete!
echo Output directory: dist\MEOWBOARD\MEOWBOARD.exe
echo ========================================================
pause
exit /b 0
