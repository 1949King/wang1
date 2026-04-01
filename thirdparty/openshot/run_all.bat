@echo off
chcp 65001 >nul
title OpenShot 双内核一键部署

echo ================================================
echo   OpenShot 双内核一键部署总控脚本
echo ================================================
echo.
echo 本脚本将自动完成以下步骤：
echo   1. 下载依赖包 (FFmpeg + OpenShot 源码)
echo   2. 编译 OpenShot 内核
echo   3. 验证部署
echo.
echo 预计耗时：15-35 分钟 (取决于网络速度和 CPU 性能)
echo.
pause

echo.
echo ================================================
echo 步骤 1/3: 下载依赖包
echo ================================================
call download_deps.bat
if %errorlevel% neq 0 (
    echo.
    echo 下载依赖包失败！
    pause
    exit /b 1
)

echo.
echo ================================================
echo 步骤 2/3: 编译 OpenShot 内核
echo ================================================
call build.bat
if %errorlevel% neq 0 (
    echo.
    echo 编译失败！
    pause
    exit /b 1
)

echo.
echo ================================================
echo 步骤 3/3: 验证部署
echo ================================================
call test_deployment.bat

echo.
echo ================================================
echo   部署完成！
echo ================================================
echo.
echo 使用示例:
echo   from app.core.editor_scheduler import EditorScheduler
echo.
echo   轻量剪辑:
echo     editor = EditorScheduler.get_light_editor()
echo.
echo   专业剪辑:
echo     timeline = EditorScheduler.get_pro_editor()
echo.
echo ================================================
pause
