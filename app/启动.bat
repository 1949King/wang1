@echo off
chcp 65001 > nul
title AI短剧编辑器 v3.0

cd /d "%~dp0"

echo ============================================================
echo   AI短剧编辑器 v3.0 - Qt6版
echo   乐高积木式插件系统 + Skill 执行引擎
echo ============================================================
echo.

REM 检查虚拟环境
if exist ..\venv\Scripts\python.exe (
    set PYTHON_CMD=..\venv\Scripts\python.exe
    echo 使用虚拟环境: ..\venv\Scripts\python.exe
) else if exist venv\Scripts\python.exe (
    set PYTHON_CMD=venv\Scripts\python.exe
    echo 使用虚拟环境: venv\Scripts\python.exe
) else (
    set PYTHON_CMD=python
    echo 使用系统 Python
)

echo.
echo 检查 Python 版本...
%PYTHON_CMD% --version

echo.
echo ============================================================
echo   启动主程序...
echo ============================================================

%PYTHON_CMD% main_qt6.py

if errorlevel 1 (
    echo.
    echo ============================================================
    echo   启动失败！请检查以下问题：
    echo   1. 确保已安装 PyQt6: pip install PyQt6
    echo   2. 查看日志文件: logs/app_*.log
    echo ============================================================
    echo.
    pause
)
