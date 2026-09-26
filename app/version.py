"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.40.3"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 40,
    "patch": 3,
    "codename": "整改 P2 起步：文档数字回正 + CI 全量 + scrub 压测",
    "release_date": "2026-09-27",
    "description": (
        "V4.40.3: 按「未修清单」推进无冻结区、零/低风险三项（A1-A3）。"
        "★ A1 文档数字回正（评价报告点名「单一事实源自身三处失准」）："
        " editor_module 8,553→9,718 行（并补 371 函数）· except:pass 173→38 处"
        "/8 文件（ok 25·ui 1·needs_log 3·frozen 9）· tsc 40→37 处且全部在冻结区"
        " （bridge.ts 3 处已于 V4.39.8 修完）；顺带回正 §2f 真源 43,210→43,603、"
        " 副库 42,533→42,954（99→100 文件）；§10 优先级条目同步现状。"
        "★ A2 CI 改造为真回归：单测从「只跑 tests/test_buses.py」改为全量"
        " app/tests（383 项）；新增 guards job（冻结区/棘轮/契约/分层/双库五守卫）"
        " 与 frontend job（npm ci + vitest）；去掉对 app/temp 草稿脚本的依赖；"
        " 触发路径补 tests/**·vendor/**·_verify/**·scripts/**；关键修正："
        " 必须在仓库根跑 pytest（app/ 下无 conftest.py，原 cd app 会假红）；"
        " continue-on-error 只保留在 build-smoke（单测/守卫/前端/集成四 job 真拦截）。"
        "★ A3 长对白 scrub 压测（报告 §6.1「四个未达标点」第 3 条，§10 列为立刻做）："
        " 新增 _verify/check_scrub_perf.py 并注册进一键回归。用 AST 从 editor_module "
        " 提取 _clips_at_playhead/_clip_at_playhead 真实函数体执行（不 import app，"
        " 绕开 wmic 沙箱链），实测 150/300/600 段：均值 0.094/0.196/0.389 ms "
        " ——精确线性、600 段仅占 30fps 帧预算 1.2% ⇒ **查找层不是长对白掉帧源**，"
        " 瓶颈若存在在解码/合成层（脚本如实标注未覆盖面）；函数指纹随源码变动，"
        " 可作回归。全量 383/383；ruff 全净；冻结区 85；稳定性 249≤269。"
    ),
}
