# Setup infinite-canvas for 拾光剪影 (embed in AI 画布 module)
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup_infinite_canvas.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Vendor = Join-Path $Root "vendor\infinite-canvas"
$Web = Join-Path $Vendor "web"

Write-Host "== 拾光剪影 · infinite-canvas 安装 ==" -ForegroundColor Cyan

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "需要 Git"
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "需要 Node.js / npm（https://nodejs.org/）"
}

if (-not (Test-Path (Join-Path $Vendor ".git"))) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "vendor") | Out-Null
    Write-Host "克隆 basketikun/infinite-canvas ..."
    git clone --depth 1 https://github.com/basketikun/infinite-canvas.git $Vendor
} else {
    Write-Host "已存在 vendor/infinite-canvas，跳过 clone"
}

Push-Location $Web
try {
    Write-Host "npm install --legacy-peer-deps ..."
    npm install --legacy-peer-deps
    Write-Host ""
    Write-Host "完成。启动方式：" -ForegroundColor Green
    Write-Host "  1) 应用内「AI 画布」→「启动画布」"
    Write-Host "  2) 或: cd vendor/infinite-canvas/web; npm run dev"
    Write-Host "桥接端口: http://127.0.0.1:18765"
    Write-Host "画布端口: http://127.0.0.1:3000"
} finally {
    Pop-Location
}

# WebEngine tip
Write-Host ""
Write-Host "若镶嵌页空白，请安装匹配版 WebEngine：" -ForegroundColor Yellow
Write-Host "  .\.venv312\Scripts\python.exe -m pip install PyQt6-WebEngine==6.10.0"
