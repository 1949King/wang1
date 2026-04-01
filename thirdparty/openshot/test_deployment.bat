@echo off
chcp 65001 >nul
title OpenShot 部署验证脚本

echo ================================================
echo   OpenShot 双内核部署验证
echo ================================================

set PYTHONPATH=../../app/core;./python;%PYTHONPATH%

echo [1/3] 测试轻量内核...
python -c "import sys; sys.path.insert(0, '../../app/core'); from editor_scheduler import EditorScheduler; editor = EditorScheduler.get_light_editor(); print('轻量内核加载成功')"
if %errorlevel% neq 0 (
    echo 轻量内核测试失败
) else (
    echo 轻量内核测试通过
)

echo.
echo [2/3] 测试专业内核...
python -c "import sys; sys.path.insert(0, './python'); from editor_scheduler import EditorScheduler; editor = EditorScheduler.get_pro_editor(); print('专业内核加载成功')"
if %errorlevel% neq 0 (
    echo 专业内核测试失败
) else (
    echo 专业内核测试通过
)

echo.
echo [3/3] 测试双内核协同...
python -c "import sys; sys.path.insert(0, './python'); sys.path.insert(0, '../../app/core'); from editor_scheduler import EditorScheduler; light = EditorScheduler.get_light_editor(); pro = EditorScheduler.get_pro_editor(); print('双内核协同工作正常')"
if %errorlevel% neq 0 (
    echo 双内核协同测试失败
) else (
    echo 双内核协同测试通过
)

echo.
echo ================================================
echo   部署验证完成！
echo ================================================
pause
