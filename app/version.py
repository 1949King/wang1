"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.10.0"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 10,
    "patch": 0,
    "codename": "AI画布与Agent调度",
    "release_date": "2026-08-13",
    "description": (
        "V4.10.0: AI 画布（shiguang-canvas）落地页与导演台能力扩展；"
        "Agent 能力调度层与剪辑面板拆分；账号运营迁插件；"
        "画布预热/切换卡死修复；AIEngine 单例崩溃修复；"
        "FFmpeg/ffprobe 路径与波形/缩略图稳定化；冻结区护航与死代码清理。"
    ),
}
