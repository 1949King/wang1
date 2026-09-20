# 根目录残留归档 — 2026-09-19

> 为什么归档而不是删除：这批文件全部经过「静态 import + 字符串引用 + 动态导入」三重核实为零引用，
> 但其中含 159KB 的快照文件，保留可恢复性是零成本的保险。

| 文件 | 大小 | 核实结论 | 说明 |
|------|------|----------|------|
| `_tmp_original_timeline.py` | 159816 B | 零引用/字符串/动态 | 拆分 timeline_widget.py 前的原始快照（159KB） |
| `count_code.py` | 1210 B | 零引用 | 代码统计探针 |
| `scan_fast.py` | 7997 B | 零引用 | 快速扫描探针 |
| `scan_files.py` | 16895 B | 零引用 | 文件扫描探针 |
| `_nav_diag.py` | 2493 B | 零引用 | 导航栏诊断 |
| `_nav_diag2.py` | 3781 B | 零引用 | 导航栏诊断 v2 |
| `_serve_final.py` | 593 B | 零引用 | 临时静态服务 |
| `_test_breakdown.py` | 1747 B | 零引用 | 临时测试（分镜拆解） |
| `_test_breakdown2.py` | 2003 B | 零引用 | 临时测试 v2 |
| `check_torch.py` | 356 B | 零引用 | torch 环境探针 |
| `copy_project_to_desktop.py` | 5651 B | 零引用 | 一次性：复制项目到桌面 |
| `find_mediapipe_path.py` | 1033 B | 零引用 | mediapipe 路径探针 |
| `generate_project_viewer.py` | 5607 B | 零引用 | 一次性：生成项目查看器 |
| `remove_bom.py` | 695 B | 零引用 | 一次性：去 BOM |
| `remove_all_bom.py` | 1407 B | 零引用 | 一次性：批量去 BOM |
| `install_top0_deps.py` | 3944 B | 零引用 | 一次性：装依赖 |
| `trend.py` | 696 B | 零引用（3 处为词误匹配） | DIY 硬件趋势（旧） |
| `scheduler.py` | 875 B | 零引用（3 处为词误匹配） | 旧调度器 |
| `monitor_service.py` | 2529 B | 仅被零引用的 scheduler.py 引用 | 数据采集服务（依赖已下线 data_collector） |

## 恢复方式

```
# 在项目根目录执行（PowerShell）
Move-Item "docs\_archive\2026-09-19-root-cleanup\<文件名>" .
```

## 未纳入本批（需单独决策）

| 项 | 说明 |
|----|------|
| `plugin/` （2 文件） | 转发壳，re-export `app.modules.plugins.plugin_system`，自身零引用 |
| `app/modules/plugins/` （3 文件, 26.9KB） | 零引用第二套插件体系；`plugin_sandbox.py` / `pyqt_plugin_manager.py` 零引用 |
| `tests/unit/test_plugin_import.py` | **本身是坏的**：引用 `modules.plugins`（旧路径，已不存在） |
