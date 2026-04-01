@echo off
chcp 65001 >nul
echo 正在启动AI短剧编辑器...
echo 请稍候，正在加载依赖...

cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" "app\ai_short_drama_editor.py"
) else (
    python "app\ai_short_drama_editor.py"
)

if %errorlevel% neq 0 (
    echo 启动失败，请检查依赖是否安装正确
    pause
)
