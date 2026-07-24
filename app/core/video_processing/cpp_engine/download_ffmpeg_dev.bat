@echo off
chcp 65001 >nul
title FFmpeg 开发库下载

echo ================================================
echo   FFmpeg Windows 开发库下载
echo ================================================
echo.
echo 将下载 FFmpeg shared + dev 包（含头文件和.lib）
echo 来源: https://www.gyan.dev/ffmpeg/builds/
echo.

set FFMPEG_DEV_DIR=C:\ffmpeg_win_dev
set DOWNLOAD_URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full-shared.7z

if exist "%FFMPEG_DEV_DIR%\include\libavcodec\avcodec.h" (
    echo [跳过] FFmpeg开发库已存在: %FFMPEG_DEV_DIR%
    goto :done
)

echo [1/3] 创建临时目录...
set TEMP_DIR=%TEMP%\ffmpeg_dev_download
mkdir "%TEMP_DIR%" 2>nul

echo [2/3] 下载FFmpeg开发包（约80MB，请耐心等待）...
echo URL: %DOWNLOAD_URL%
echo.
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%DOWNLOAD_URL%' -OutFile '%TEMP_DIR%\ffmpeg.7z' -UseBasicParsing}" 2>nul

if not exist "%TEMP_DIR%\ffmpeg.7z" (
    echo.
    echo [错误] 自动下载失败（可能是网络问题）
    echo.
    echo 请手动下载FFmpeg开发包:
    echo   1. 打开浏览器访问: https://www.gyan.dev/ffmpeg/builds/
    echo   2. 下载 "ffmpeg-release-full-shared.7z"
    echo   3. 解压后将 include/ 和 lib/ 目录复制到:
    echo      %FFMPEG_DEV_DIR%\
    echo.
    pause
    exit /b 1
)

echo [3/3] 解压开发库到 %FFMPEG_DEV_DIR%...
mkdir "%FFMPEG_DEV_DIR%" 2>nul
powershell -Command "& {Expand-Archive -Path '%TEMP_DIR%\ffmpeg.7z' -DestinationPath '%TEMP_DIR%\ffmpeg_extracted' -Force}" 2>nul

if not exist "%TEMP_DIR%\ffmpeg_extracted" (
    echo [提示] 使用7z解压...
    if exist "C:\Program Files\7-Zip\7z.exe" (
        "C:\Program Files\7-Zip\7z.exe" x "%TEMP_DIR%\ffmpeg.7z" -o"%TEMP_DIR%\ffmpeg_extracted" -y
    ) else (
        echo [错误] 需要7-Zip来解压.7z文件
        echo 请手动解压 %TEMP_DIR%\ffmpeg.7z 并将 include/ 和 lib/ 复制到 %FFMPEG_DEV_DIR%
        pause
        exit /b 1
    )
)

for /d %%d in ("%TEMP_DIR%\ffmpeg_extracted\*") do (
    if exist "%%d\include\libavcodec\avcodec.h" (
        echo 找到FFmpeg开发包: %%d
        xcopy /E /Y "%%d\include" "%FFMPEG_DEV_DIR%\include\" >nul
        xcopy /E /Y "%%d\lib" "%FFMPEG_DEV_DIR%\lib\" >nul
        goto :found
    )
)
echo [错误] 解压后未找到include/libavcodec/avcodec.h
pause
exit /b 1

:found
echo 开发库安装完成!
echo   头文件: %FFMPEG_DEV_DIR%\include\
echo   库文件: %FFMPEG_DEV_DIR%\lib\

rd /s /q "%TEMP_DIR%" 2>nul

:done
echo.
echo FFmpeg开发库安装完成!
pause
