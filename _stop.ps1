# 拾光剪影 停止脚本
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File D:\拾光剪影\_stop.ps1

Write-Host ""
Write-Host "=============================================" -ForegroundColor Yellow
Write-Host "  停止拾光剪影所有服务" -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Yellow
Write-Host ""

$killed = 0
foreach ($img in @("pythonw.exe", "node.exe", "python.exe")) {
    $procs = Get-Process -Name ($img -replace '\.exe$','') -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.Id -Force -ErrorAction Stop
            Write-Host "  killed $img PID=$($p.Id)  $($p.ProcessName)" -ForegroundColor DarkGray
            $killed++
        } catch {
            Write-Host "  跳过 PID=$($p.Id): $_" -ForegroundColor DarkGray
        }
    }
}

Start-Sleep -Milliseconds 500
Write-Host ""
Write-Host "已停止 $killed 个进程" -ForegroundColor Green

foreach ($p in @(3010, 18765)) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($c) {
        Write-Host "  [WARN] 端口 $p 仍被占用 PID=$($c[0].OwningProcess)" -ForegroundColor Red
    } else {
        Write-Host "  [OK] 端口 $p 已释放" -ForegroundColor Green
    }
}
Write-Host ""
