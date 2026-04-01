# 手动安装FFmpeg并添加到系统PATH

# 设置工作目录
$projectRoot = "d:\本地磁盘(当前分区)(C)\Users\Administrator\Desktop\AI短剧编辑器2"
$ffmpegDir = "$projectRoot\thirdparty\ffmpeg"
$binDir = "$ffmpegDir\bin"

# 清理旧的FFmpeg目录
if (Test-Path $ffmpegDir) {
    Remove-Item -Path $ffmpegDir -Recurse -Force
}

# 创建新的FFmpeg目录
New-Item -ItemType Directory -Path $ffmpegDir -Force
New-Item -ItemType Directory -Path $binDir -Force

# 下载FFmpeg
$ffmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$ffmpegZip = "$ffmpegDir\ffmpeg.zip"

Write-Host "正在下载FFmpeg..."
Invoke-WebRequest -Uri $ffmpegUrl -OutFile $ffmpegZip

# 解压FFmpeg
Write-Host "正在解压FFmpeg..."
Expand-Archive -Path $ffmpegZip -DestinationPath $ffmpegDir

# 移动文件到正确位置
$extractedDir = Get-ChildItem -Path $ffmpegDir -Directory | Where-Object { $_.Name -like "ffmpeg-*-essentials_build" } | Select-Object -First 1
if ($extractedDir) {
    Move-Item -Path "$($extractedDir.FullName)\bin\*" -Destination $binDir
    Remove-Item -Path $extractedDir -Recurse -Force
}

# 清理zip文件
Remove-Item -Path $ffmpegZip -Force

# 验证FFmpeg安装
$ffmpegExe = "$binDir\ffmpeg.exe"
if (Test-Path $ffmpegExe) {
    Write-Host "FFmpeg安装成功!"
    & $ffmpegExe -version
    
    # 添加到系统PATH
    $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if (-not $currentPath.Contains($binDir)) {
        $newPath = "$currentPath;$binDir"
        [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        Write-Host "FFmpeg已添加到系统PATH!"
    }
} else {
    Write-Host "FFmpeg安装失败，请检查日志。"
}
