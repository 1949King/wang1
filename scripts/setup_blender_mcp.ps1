# ============================================================
# setup_blender_mcp.ps1
# 从 Git 下载 harveyxiacn/blender-mcp（增强版，359 工具）
# 到 thirdparty/blender/blender-mcp/
# ============================================================

$ErrorActionPreference = "Stop"

# 定位项目根目录（脚本位于 <root>/scripts/ 下）
$root = Split-Path $PSScriptRoot -Parent
$target = Join-Path $root "thirdparty\blender\blender-mcp"

# 1. 检查 git 是否安装
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    throw "未检测到 git，请先安装 Git for Windows: https://git-scm.com/download/win"
}

# 2. 已存在则跳过
if (Test-Path $target) {
    Write-Host "blender-mcp 已存在: $target" -ForegroundColor Green
    exit 0
}

# 3. 创建父目录
New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null

# 4. git clone（浅克隆，--depth 1 节省时间和空间）
Write-Host "正在 git clone harveyxiacn/blender-mcp（359 工具增强版）..." -ForegroundColor Cyan
git clone --depth 1 https://github.com/harveyxiacn/blender-mcp.git $target
if ($LASTEXITCODE -ne 0) {
    throw "git clone 失败（exit code: $LASTEXITCODE）"
}

Write-Host ""
Write-Host "完成: $target" -ForegroundColor Green
Write-Host ""
Write-Host "后续启用方式（二选一）：" -ForegroundColor Yellow
Write-Host "  1. 本地运行（推荐）: cd `"$target`"; uv sync; uv run blender-mcp"
Write-Host "  2. 直接安装: pip install blender-mcp（注：PyPI 版本为基础版，增强版需从 git 装）"
Write-Host ""
Write-Host "Blender 端：" -ForegroundColor Yellow
Write-Host "  编辑 → 首选项 → 插件 → 安装 → 选择 `"$target\dist\blender_mcp_addon.zip`""
Write-Host "  （若 dist 不存在，先在 $target 目录运行 python build_addon.py）"
