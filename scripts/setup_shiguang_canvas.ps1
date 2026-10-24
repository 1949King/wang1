# 搭建自研导演台画布（shiguang-canvas）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Dir = Join-Path $Root "vendor\shiguang-canvas"
if (-not (Test-Path (Join-Path $Dir "package.json"))) {
  Write-Error "缺少 $Dir"
}
Set-Location $Dir
npm install
npm run build
Write-Host "完成。dist 已生成。宿主默认引擎 shiguang，静态端口 3011。"
Write-Host "回退旧画布: `$env:SHIGUANG_CANVAS_ENGINE='infinite'"
