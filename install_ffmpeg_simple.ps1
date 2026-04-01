# 简单安装FFmpeg

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
Write-Host "正在下载FFmpeg..."
$client = New-Object System.Net.WebClient
$client.DownloadFile("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", "$ffmpegDir\ffmpeg.zip")

# 解压FFmpeg
Write-Host "正在解压FFmpeg..."
try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory("$ffmpegDir\ffmpeg.zip", "$ffmpegDir")
} catch {
    Write-Host "使用PowerShell Expand-Archive..."
    Expand-Archive -Path "$ffmpegDir\ffmpeg.zip" -DestinationPath "$ffmpegDir"
}

# 移动文件到正确位置
$extractedDir = Get-ChildItem -Path $ffmpegDir -Directory | Where-Object { $_.Name -like "ffmpeg-*-essentials_build" } | Select-Object -First 1
if ($extractedDir) {
    Write-Host "正在移动文件..."
    Move-Item -Path "$($extractedDir.FullName)\bin\*" -Destination $binDir -Force
    Remove-Item -Path $extractedDir -Recurse -Force
}

# 清理zip文件
Remove-Item -Path "$ffmpegDir\ffmpeg.zip" -Force -ErrorAction SilentlyContinue

# 验证FFmpeg安装
$ffmpegExe = "$binDir\ffmpeg.exe"
if (Test-Path $ffmpegExe) {
    Write-Host "FFmpeg安装成功!"
    & $ffmpegExe -version
} else {
    Write-Host "FFmpeg安装失败，请检查日志。"
    Get-ChildItem -Path $ffmpegDir -Recurse
}
