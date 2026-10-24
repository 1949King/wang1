# 从BtbN下载FFmpeg

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
try {
    $client = New-Object System.Net.WebClient
    $client.DownloadFile("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip", "$ffmpegDir\ffmpeg.zip")
} catch {
    Write-Host "下载失败，尝试备用链接..."
    $client = New-Object System.Net.WebClient
    $client.DownloadFile("https://github.com/GyanD/codexffmpeg/releases/download/6.1/ffmpeg-6.1-full_build.7z", "$ffmpegDir\ffmpeg.7z")
}
