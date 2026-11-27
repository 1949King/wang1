# 拾光剪影 一键启动脚本
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File D:\拾光剪影\_bootstrap.ps1

$ErrorActionPreference = "Continue"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$VENV_PYTHON = "$ROOT\.venv312\Scripts\python.exe"   # 调试用 python.exe（看日志），稳定后改回 pythonw.exe
$VITE_DIR = "$ROOT\vendor\shiguang-canvas"
$VITE_PORT = 3010
$BRIDGE_PORT = 18765

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  拾光剪影 —— 一键启动 (Qt6 + Vite + Bridge)" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 0: 前置检查 ──────────────────────────────────
if (-not (Test-Path $VENV_PYTHON)) {
    Write-Host "[FAIL] 找不到 venv Python: $VENV_PYTHON" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] venv Python 存在: $VENV_PYTHON" -ForegroundColor Green

$nodeExe = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeExe) {
    Write-Host "[FAIL] 系统找不到 node.exe，请先安装 Node.js (推荐 v20 LTS)" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Node.js 存在: $($nodeExe.Source)  ($(node --version))" -ForegroundColor Green

# ── Step 1: 清理残留进程 ──────────────────────────────
Write-Host ""
Write-Host "[Step 1/6] 清理残留进程 (pythonw.exe / node.exe)..." -ForegroundColor Yellow
foreach ($img in @("pythonw.exe", "node.exe")) {
    $procs = Get-Process -Name $img -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.Id -Force -ErrorAction Stop
            Write-Host "  killed $img PID=$($p.Id)" -ForegroundColor DarkGray
        } catch {
            Write-Host "  跳过 $img PID=$($p.Id): $_" -ForegroundColor DarkGray
        }
    }
}
Write-Host "  清理完成" -ForegroundColor Green

# ── Step 2: 等待端口释放 ──────────────────────────────
Write-Host ""
Write-Host "[Step 2/6] 等待端口 $VITE_PORT / $BRIDGE_PORT 释放..." -ForegroundColor Yellow
$wait = 0
while ($wait -lt 10) {
    $busy = $false
    foreach ($p in @($VITE_PORT, $BRIDGE_PORT)) {
        $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($c) { $busy = $true; break }
    }
    if (-not $busy) { break }
    $wait++; Start-Sleep -Milliseconds 500
}
foreach ($p in @($VITE_PORT, $BRIDGE_PORT)) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($c) {
        Write-Host "  [WARN] 端口 $p 仍被占用 (PID=$($c[0].OwningProcess))，尝试强制释放..." -ForegroundColor Red
        Stop-Process -Id $c[0].OwningProcess -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "  [OK] 端口 $p 空闲" -ForegroundColor Green
    }
}

# ── Step 3: vite node_modules 检查 & npm install ─────
Write-Host ""
Write-Host "[Step 3/6] 检查 vite 依赖..." -ForegroundColor Yellow
$nodeModules = "$VITE_DIR\node_modules"
if (-not (Test-Path $nodeModules)) {
    Write-Host "  node_modules 不存在，执行 npm install..." -ForegroundColor DarkCyan
    Push-Location $VITE_DIR
    try {
        npm install 2>&1 | ForEach-Object { Write-Host "  npm: $_" -ForegroundColor DarkGray }
        Write-Host "  [OK] npm install 完成" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] npm install 失败: $_" -ForegroundColor Red
        Pop-Location
        exit 1
    }
    Pop-Location
} else {
    Write-Host "  [OK] node_modules 已存在，跳过 npm install" -ForegroundColor Green
}

# ── Step 4: 启动 vite dev server (后台) ───────────────
Write-Host ""
Write-Host "[Step 4/6] 启动 vite dev server (port=$VITE_PORT)..." -ForegroundColor Yellow
$viteLog = "$ROOT\.dbg\vite.log"
$procVite = Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev" `
    -WorkingDirectory $VITE_DIR `
    -RedirectStandardOutput $viteLog `
    -RedirectStandardError "$ROOT\.dbg\vite.err.log" `
    -PassThru -WindowStyle Hidden
Write-Host "  vite PID=$($procVite.Id)" -ForegroundColor Cyan

# 等待 vite 就绪（最多 30s）
$viteReady = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    $c = Get-NetTCPConnection -LocalPort $VITE_PORT -State Listen -ErrorAction SilentlyContinue
    if ($c) { $viteReady = $true; break }
}
if ($viteReady) {
    Write-Host "  [OK] vite 已就绪 (port=$VITE_PORT)" -ForegroundColor Green
    Write-Host "  预览: http://127.0.0.1:$VITE_PORT" -ForegroundColor DarkCyan
} else {
    Write-Host "  [WARN] vite 30s 内未就绪，请查看 $viteLog" -ForegroundColor Red
}
# 打个简短的日志摘要
if (Test-Path $viteLog) {
    Write-Host "  --- vite 日志摘要 ---" -ForegroundColor DarkGray
    Get-Content $viteLog -Tail 10 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
}

# ── Step 5: 启动 PySide6 主窗口 (后台, pythonw 无控制台) ──
Write-Host ""
Write-Host "[Step 5/6] 启动 PySide6 主窗口 (pythonw)..." -ForegroundColor Yellow
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$procQt = Start-Process -FilePath $VENV_PYTHON `
    -ArgumentList "$ROOT\main_qt6.py" `
    -WorkingDirectory $ROOT `
    -PassThru
Write-Host "  PySide6 PID=$($procQt.Id)" -ForegroundColor Cyan

# 等几秒让 Qt 初始化 canvas_bridge
Write-Host "  等待 canvas_bridge (port=$BRIDGE_PORT) 就绪..." -ForegroundColor Yellow
$bridgeReady = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $c = Get-NetTCPConnection -LocalPort $BRIDGE_PORT -State Listen -ErrorAction SilentlyContinue
    if ($c) { $bridgeReady = $true; break }
}
if ($bridgeReady) {
    Write-Host "  [OK] canvas_bridge 已就绪 (port=$BRIDGE_PORT)" -ForegroundColor Green
} else {
    Write-Host "  [WARN] canvas_bridge 20s 内未就绪 —— Qt 可能尚未初始化 bridge" -ForegroundColor Red
    Write-Host "         正常，bridge 通常在画布 WebView 首次加载时才启动" -ForegroundColor DarkGray
}

# ── Step 6: 汇总 ──────────────────────────────────────
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  启动汇总" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  vite      : PID=$($procVite.Id)  port=$VITE_PORT  " -NoNewline
if ($viteReady) { Write-Host "OK" -ForegroundColor Green } else { Write-Host "WARN" -ForegroundColor Red }
Write-Host "  PySide6     : PID=$($procQt.Id)" -NoNewline
if (-not $procQt.HasExited) { Write-Host "OK (运行中)" -ForegroundColor Green } else { Write-Host "EXITED code=$($procQt.ExitCode)" -ForegroundColor Red }
Write-Host "  bridge    : port=$BRIDGE_PORT  " -NoNewline
if ($bridgeReady) { Write-Host "OK (已就绪)" -ForegroundColor Green } else { Write-Host "PENDING (按需启动)" -ForegroundColor Yellow }
Write-Host ""
Write-Host "  vite 日志  : $viteLog" -ForegroundColor DarkGray
Write-Host "  vite 错误  : $ROOT\.dbg\vite.err.log" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  关闭所有服务: powershell -NoProfile -ExecutionPolicy Bypass -File $ROOT\_stop.ps1" -ForegroundColor DarkCyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
