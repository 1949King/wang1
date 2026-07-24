@echo off
chcp 65001 >nul
title C++ 视频引擎编译

cd /d "%~dp0"

echo ========================================
echo AI短剧编辑器 - C++ 视频引擎编译
echo ========================================
echo.

if not exist "setup_cpp_engine.bat" (
    echo 缺少 setup_cpp_engine.bat
    pause
    exit /b 1
)

echo 请先运行 setup_cpp_engine.bat 完成环境搭建。
echo.
echo setup_cpp_engine.bat 将自动:
echo   1. 检查 VS2022
echo   2. 安装 cmake + pybind11
echo   3. 下载 FFmpeg 开发库
echo   4. 编译 + 验证
echo.
pause
call setup_cpp_engine.bat
