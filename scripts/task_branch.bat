@echo off
REM ============================================================
REM  拾光剪影 · 一任务一分支 + 自动回滚（Windows 包装）
REM
REM  真正的逻辑在 scripts/task_branch.sh（唯一真相源）。
REM  用法：
REM    task_branch.bat start  <任务名>
REM    task_branch.bat status
REM    task_branch.bat done   <任务名> [--keep]
REM    task_branch.bat abort  <任务名> --yes
REM    task_branch.bat rollback [tag|--list]
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
    echo [X] 找不到 Git Bash。
    exit /b 3
)

"%BASH%" scripts/task_branch.sh %*
exit /b %ERRORLEVEL%
