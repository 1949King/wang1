"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.9.2"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 9,
    "patch": 2,
    "codename": "贴纸预览与滤镜播放优化",
    "release_date": "2026-07-12",
    "description": (
        "V4.9.1: 剪辑导出可用性修复（续）— "
        "修复致命的 subprocess 参数拼写错误：video_processor 中 12 处调用误用 "
        "`creation_flags=`（带下划线），而 subprocess.Popen 仅接受 `creationflags=`（无下划线），"
        "导致 裁剪/滤镜/合并/转场 等所有 ffmpeg 调用全部抛出 "
        "`Popen.__init__() got an unexpected keyword argument 'creation_flags'`，"
        "整个剪辑后端形同瘫痪。现统一为正确拼写，实测 裁剪+滤镜+调节+转场+导出设置 全链路跑通并产出合法 640x360/24fps 视频。"
        "（V4.9.0 已修复：导出崩溃/effects 类型混用、12 个滤镜按钮接通、导出设置生效、画面调节烘焙、AIClipAlgorithm 导入。）"
    ),
}
