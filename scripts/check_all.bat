@echo off
REM ============================================================
REM  拾光剪影 · 全量体检（Windows 双击入口）
REM
REM  等价于  bash scripts/check_all.sh  —— 真正的逻辑在 .sh 里（唯一真相源），
REM  本文件只负责找到 Git Bash 并转发参数。不要在 .bat 里复制一套逻辑，
REM  否则两边必然漂移（这正是 2026-10-09 之前 CI 与本地门禁不一致的根因）。
REM
REM  用法：
REM    check_all.bat           全量
REM    check_all.bat --fast    快速
REM ============================================================
setlocal
cd /d "%~dp0.."

set "BASH="
for %%P in (
    "%ProgramFiles%\Git\bin\bash.exe"
    "%ProgramFiles(x86)%\Git\bin\bash.exe"
    "%LOCALAPPDATA%\Programs\Git\bin\bash.exe"
    "C:\Users\%USERNAME%\.workbuddy\binaries\PortableGit\versions\1.2.0\bin\bash.exe"
) do (
    if not defined BASH if exist %%P set "BASH=%%~P"
)
if not defined BASH (
    where bash >nul 2>nul && set "BASH=bash"
)
if not defined BASH (
    echo [X] 找不到 Git Bash，无法运行体检。
    echo     请安装 Git for Windows，或直接手工执行：
    echo       bash scripts/check_all.sh
    pause
    exit /b 3
)

echo 使用 Bash: %BASH%
"%BASH%" scripts/check_all.sh %*
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (echo [OK] 全量体检通过) else (echo [X] 体检失败，退出码 %RC%)
pause
exit /b %RC%
