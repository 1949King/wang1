"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.10.3"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 10,
    "patch": 3,
    "codename": "AI画布与Agent调度",
    "release_date": "2026-08-19",
    "description": (
        "V4.10.3: 打包就绪——重写 PyInstaller spec（补 license/、"
        "config.json、隐式依赖全量收集，修复 torch 子模块收集时序 bug）；"
        "清理 5 个冗余虚拟环境，仅保留 .venv312。"
    ),
}
