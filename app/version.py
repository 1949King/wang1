"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.39.3"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 39,
    "patch": 3,
    "codename": "全项目官方补丁排查与打补丁（数据源 + 依赖库）",
    "release_date": "2026-09-25",
    "description": (
        "V4.39.3: 按用户要求排查「所有可打的官方补丁」，两个维度都做了，"
        "并明确区分「已打」与「刻意不打（附理由）」。"
        "★ 维度一 · 数据源：Unihan 其他拼音字段全部排查 —— "
        "kHanyuPinyin(34130)/kXHC1983(11072)/kTGHZ2013(8105) 对 pypinyin 缺口的"
        "补充均为 **0**（它们覆盖的字 pypinyin 全认识；价值仅在多音字候选交叉校验）。"
        "⇒ 数据源侧已榨干，kMandarin 2517 字补丁即为上限（V4.39.2 已完成）。"
        "★ 维度二 · Python 依赖：28 个直接依赖 vs 89 个可升级包求交分级 —— "
        "**已打 4 个安全补丁**：cryptography 50.0.0→50.0.1、imageio 2.37.3→2.37.4、"
        "Pillow 12.2.0→12.3.0、requests 2.32.5→2.34.2（含安全相关库）。"
        "**刻意不打 6 个 MAJOR**：numpy 1.26.4（被 numba 0.64 与 opencv/torch ABI "
        "钉死，升 2.x 会连锁炸）、moviepy 1.0→2.2（API 大改）、opencv 4→5、"
        "librosa 0.11→1.0、mediapipe 0.10→1.0、anthropic 0.25→1.8。"
        "**待评估 12 个 minor**（PyQt6 三件套 / transformers / dashscope / "
        "onnxruntime / aiohttp / numba 等）—— 需专项回归，未擅自升级。"
        "★ 维度三 · 前端依赖（画布 vendor/shiguang-canvas）：已打 semver 内全部"
        "官方补丁（npm update）—— react/react-dom 19.2.8→19.3.0、"
        "**@xyflow/react（磁吸核心）12.11.2→12.11.6**、zustand 5.0.14→5.0.15、"
        "@types/react* →19.3.0。"
        "**npm audit 报 5 个漏洞（1 critical + 1 high + 3 moderate）全部在 "
        "vitest 测试工具链**（dev-only，不进发布包；触发场景是本地 vitest UI server "
        "监听），唯一修复路径是 vitest 2→5 + vite 6→8 双 major 跳跃 —— "
        "**刻意不打**（dev-only 收益 << 破坏面风险），已提供一键命令供决策。"
        "★ 验证：Python 侧 run_all_checks 全绿；前端 vitest 8 文件 76 例全过、"
        "tsc 37 处 = 文档基线（Stage3D 16 + riggedHumanoid 21，零新增）、"
        "vite build 成功、双库无新增漂移。"
    ),
}
