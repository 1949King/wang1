"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.40.1"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 40,
    "patch": 1,
    "codename": "整改 P1：前端三卡点接线 + prompt-image 负缓存",
    "release_date": "2026-09-26",
    "description": (
        "V4.40.1: 实测整改方案 P1 剩余三项之前两项落地。"
        "★ 前端三卡点（pre-commit 第⑦道，仅暂存画布文件触发）："
        " ⑦a tsc 类型棘轮（错误 ≤37 只减不增，基线全在 stage3d-core 冻结区"
        " 2 文件，清零需解冻）；⑦b vitest 单测（81/81 失败即拦，"
        " --pool=threads——forks pool 写临时目录被 fs-shim EPERM 假失败，"
        " threads 走内存通道）；⑦c 质量棘轮（dupNames≤8/fnOver300≤9/"
        " cycloOver60≤5，8 组同名已定性为启发式误报=多行箭头回调）。"
        " 此前画布改动只有双库一致性一道卡点（现行技术文档 §2f.3 P0-a）。"
        "★ prompt-image 失败负缓存（§2d.3 P0-b）：canvas_server.py 端点"
        " （非 canvas_bridge，不在冻结区）失败写 .fail 标记，TTL 6h 内"
        " 不再重试，成功主动清除（自愈），判定/写入出错不拦不炸；"
        " 根治每次启动对死链重复 45s 超时轰炸。测试 6 项。"
        "★ 顺带清 canvas_server.py 存量 ruff 10+1 处（死 noqa×7、死变量"
        " last_ping×2、except as e 未用、zip 补 strict=False）——"
        " 增量门禁拦下即清先例。"
        "★ 测试 383/383；ruff 净；冻结区 85；稳定性 269=269；粘合层 18/0。"
    ),
}
