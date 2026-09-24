"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.39.4"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 39,
    "patch": 4,
    "codename": "技术债止血：单文件规模守卫 + UI 归属与依赖纪律固化",
    "release_date": "2026-09-25",
    "description": (
        "V4.39.4: 按用户要求「明确的技术债能优化一点就优化一点」，"
        "本轮做**零风险高价值**的两件（不动高风险重构）。"
        "★ ① 新增单文件规模守卫 `_verify/check_file_size.py`（阈值 2000 行）："
        "把存量 12 个超标文件（editor_module.py 9,717 · Stage3D.tsx 4,660 · "
        "riggedHumanoid.ts 3,707 · CanvasShell.tsx 3,199 · canvas_server.py 3,273 · "
        "canvas_aigc.py 2,905 · store.ts 2,452 · settings_module.py 2,823 · "
        "video_processor.py 2,732 · editor_agent_panel_mixin.py 2,330 · "
        "extensions_module.py 2,198 · drama_understanding_engine.py 2,160）"
        "**冻结为基线，只许减不许增**，并已通过**负向测试**（造 2100 行文件 → 正确 FAIL）。"
        "这是**唯一能阻止 9,717 行继续变大的机制**（09-19 时 9,479 → 仍在涨）。"
        "★ ② 在《现行技术文档》新增 §2b，固化两件被反复误读的事实："
        "（a）**UI 归属真相**——不是「双前端」，而是「一个 Qt 桌面壳 + 一份 React 画布"
        "源码（vendor/shiguang-canvas）× 两个宿主」（engine=shiguang 走 WebEngine 嵌入 / "
        "engine=tauri 走独立进程），且副库 vendor/AI-Canvas-tauri **未被 git 跟踪**，"
        "改前必须备份；（b）**依赖升级纪律**——patch 直接打 / minor 需回归 / MAJOR 禁盲升，"
        "含「numpy 1.26.4 被 numba 与 opencv/torch ABI 钉死」这条硬约束。"
        "★ 待用户授权的债：前端 37 处 tsc 存量错误性质已查明（绝大多数是 "
        "`Object3D | null` vs `| undefined` 的类型标注不一致，**纯类型、运行时零影响**），"
        "但受影响文件 Stage3D.tsx / riggedHumanoid.ts **在冻结区 stage3d-core 内**，"
        "须获「解冻 stage3d-core」授权才能修。"
        "★ 验证：SIZE 守卫 PASS（含负向测试）；run_all_checks 全绿。"
    ),
}
