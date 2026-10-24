@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PATH=%CD%\.venv312\Scripts;%PATH%

:: Check system Python first (has PyQt6)
python -c "import PyQt6" 2>nul
if %errorlevel% equ 0 (
    echo Starting with system Python...
    python -m app.main_qt6
    pause
    exit /b
)

:: Fallback to venv
if exist ".venv312\Scripts\python.exe" (
    ".venv312\Scripts\python.exe" -c "import PyQt6" 2>nul
    if %errorlevel% equ 0 (
        echo Starting with venv Python...
        ".venv312\Scripts\python.exe" -m app.main_qt6
        pause
        exit /b
    )
)

echo ERROR: PyQt6 not found. Run: pip install PyQt6
pause
