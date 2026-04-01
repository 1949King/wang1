@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ============================================================
echo   AI短剧编辑器 - 项目结构清理
echo ============================================================
echo.

echo 第1步：创建 legacy 目录...
if not exist legacy mkdir legacy
if not exist legacy\tests mkdir legacy\tests
echo   完成!

echo.
echo 第2步：移动旧 Tk 文件到 legacy/...
if exist ai_short_drama_editor.py move ai_short_drama_editor.py legacy\
if exist ai_short_drama_editor_optimized.py move ai_short_drama_editor_optimized.py legacy\
if exist ui_main.py move ui_main.py legacy\
if exist run_lego.py move run_lego.py legacy\
echo   完成!

echo.
echo 第3步：移动测试文件到 legacy/tests/...
for %%f in (test_*.py) do move "%%f" legacy\tests\
if exist simple_test.py move simple_test.py legacy\tests\
if exist test_import.py move test_import.py legacy\tests\
echo   完成!

echo.
echo ============================================================
echo   清理完成!
echo ============================================================
echo.
echo 当前项目结构:
echo   主程序: main_qt6.py
echo   旧文件: legacy/
echo   测试文件: legacy/tests/
echo.
echo 启动方式: python main_qt6.py
echo ============================================================
pause
