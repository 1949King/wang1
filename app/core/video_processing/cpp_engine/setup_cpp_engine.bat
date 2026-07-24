@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo ================================================
echo   AI short drama editor - C++ engine setup
echo ================================================
echo.
echo   [1] Check compile tools
echo   [2] Install Python deps (cmake/pybind11)
echo   [3] Download FFmpeg dev libraries
echo   [4] Compile C++ engine
echo   [5] Verify
echo.
pause

cd /d "%~dp0"

REM ---- step 1: find VS2022 ----
echo.
echo [1/5] Checking VS2022...

set VS_VCVARS=
for %%d in (
    "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
    "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
    "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
) do (
    if exist %%d (
        set "VS_VCVARS=%%~d"
        echo   Found: %%~d
    )
)

if "%VS_VCVARS%"=="" (
    echo   NOT FOUND: Visual Studio 2022
    echo   Install: winget install Microsoft.VisualStudio.2022.BuildTools
    pause
    exit /b 1
)

python --version >nul 2>&1
if errorlevel 1 (
    echo   NOT FOUND: Python
    pause
    exit /b 1
)
echo   Python: OK

REM ---- step 2: pip install ----
echo.
echo [2/5] Installing Python deps...

python -c "import cmake" >nul 2>&1
if errorlevel 1 (
    echo   Installing cmake...
    pip install cmake
) else (
    echo   cmake: already installed
)

python -c "import pybind11" >nul 2>&1
if errorlevel 1 (
    echo   Installing pybind11...
    pip install pybind11
) else (
    echo   pybind11: already installed
)

REM ---- step 3: download FFmpeg dev ----
echo.
echo [3/5] Checking FFmpeg dev libs...

set "FFMPEG_DEV=C:\ffmpeg_win_dev"
if exist "%FFMPEG_DEV%\include\libavcodec\avcodec.h" (
    echo   FFmpeg dev: FOUND
) else (
    echo   FFmpeg dev: NOT FOUND, downloading...
    if exist download_ffmpeg_dev.bat (
        call download_ffmpeg_dev.bat
        if errorlevel 1 (
            echo   Download failed
            pause
            exit /b 1
        )
    ) else (
        echo   download_ffmpeg_dev.bat missing!
        pause
        exit /b 1
    )
)

REM ---- step 4: compile ----
echo.
echo [4/5] Compiling C++ engine...

call "%VS_VCVARS%" >nul 2>&1

if exist build (
    rd /s /q build
)
mkdir build
cd build

cmake .. -G "Visual Studio 17 2022" -A x64 -DCMAKE_BUILD_TYPE=Release -DFFMPEG_ROOT="%FFMPEG_DEV%"
if errorlevel 1 (
    echo   CMake configure FAILED
    cd ..
    pause
    exit /b 1
)

cmake --build . --config Release --parallel
if errorlevel 1 (
    echo   Build FAILED
    cd ..
    pause
    exit /b 1
)

echo   Build OK

REM ---- step 5: verify ----
echo.
echo [5/5] Verifying...

for %%f in (Release\video_engine_cpp.cp3*.pyd) do (
    echo   Product: %%f
    copy /Y "%%f" "..\" >nul
)

cd ..

python -c "from video_engine_cpp import VideoEngine; e = VideoEngine(); print('   IMPORT OK')" 2>nul
if errorlevel 1 (
    echo   Import test FAILED
    echo   May need FFmpeg DLLs: copy %FFMPEG_DEV%\bin\*.dll to current dir
)

echo.
echo ================================================
echo   Setup complete
echo ================================================
echo   PYD: video_engine_cpp.pyd
echo.
echo   Usage:
echo     from video_engine_cpp import VideoEngine
echo     engine = VideoEngine()
echo ================================================
pause
