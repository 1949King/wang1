@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PATH=%CD%\.venv312\Scripts;%PATH%

:: 诊断用启动器：在 --no-sandbox 之外额外禁用 GPU 合成，
:: 用于验证「3D 群像出现占屏巨物」是否由 DirectComposition 合成失败引起。
:: 日志证据：direct_composition_support.cc(1122) QueryInterface to IDCompositionDevice4 failed (0x80004002)
set QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox --disable-gpu-compositing

echo [诊断] QTWEBENGINE_CHROMIUM_FLAGS=%QTWEBENGINE_CHROMIUM_FLAGS%
echo [诊断] 若本启动器下群像正常、原启动器异常 => 确认是 GPU 合成回退问题
echo.

".venv312\Scripts\python.exe" -m app.main_qt6

echo.
echo [诊断] 程序已退出
pause
