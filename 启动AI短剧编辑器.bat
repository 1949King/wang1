@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PATH=%CD%\.venv312\Scripts;%PATH%

:: 优先项目 venv：它同时具备 PySide6 与 CUDA torch（本地 SD/Wan 生成必需）。
:: 历史上先探测系统 Python，会把只有 PySide6、没有 torch 的 C:\Python314 选走，
:: 结果本地模型全部显示“未安装 torch”。venv 不可用时才回退系统 Python。
if exist ".venv312\Scripts\python.exe" (
    ".venv312\Scripts\python.exe" -c "import PySide6" >nul 2>&1
    if not errorlevel 1 (
        echo Starting with project venv: .venv312
        ".venv312\Scripts\python.exe" -m app.main_qt6
        pause
        exit /b
    )
)

:: Fallback: system Python with PySide6 (may lack torch; local generation unavailable)
python -c "import PySide6" >nul 2>&1
if not errorlevel 1 (
    echo WARNING: using system Python without project venv; local models may require torch.
    python -m app.main_qt6
    pause
    exit /b
)

echo ERROR: PySide6 not found. Run: pip install PySide6
pause
