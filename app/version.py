"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.39.5"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 39,
    "patch": 5,
    "codename": "虚拟形象提示词包（12 条：定妆卡 / 动态视频 / 首帧图）",
    "release_date": "2026-09-25",
    "description": (
        "V4.39.5: 新增「拾光·虚拟形象包」——供项目生成女性虚拟形象动态视频的"
        "参考提示词库（用户需求：漂亮好看的女性虚拟形象动态视频）。"
        "★ 产出 `vendor/shiguang-canvas/public/prompts/shiguang-avatar.json`"
        "（12 条，三组）："
        "① 定妆三视图 / 面部锚定特写 / 全身比例设定（category=consistency，"
        "供 character_anchor 跨镜头一致性锚定）；"
        "② 7 条动态视频（口播播报 / 窗边侧光静立 / 转身回眸 / 走向镜头 / "
        "微笑抬头特写 / 霓虹光影扫过 / 国风执扇回眸），每条都含**动作 + 动态细节"
        "（发丝/衣料/呼吸/微表情）+ 镜头运动**；"
        "③ 2 条图生视频首帧（半身正面留白 / 动态预备姿势）。"
        "★ 格式严格对齐现有包：5 字段（id/title/category/tags/prompt），"
        "已实测**字段集合与 shiguang-drama.json 完全一致**；"
        "技术提示（画幅/时长/渠道类型）写进 tags（t2v/i2v、5s/10s、9:16/16:9）"
        "以保持格式兼容。"
        "★ 两个质量校验：全部条目 prompt **明确标注「成年女性」**（合规，"
        "沿用项目既有惯例）；7 条动态条目**全部含动态要素**（动作/镜头/飘动/变化）。"
        "★ 关键接线：新提示词包必须注册进 `promptLibrary.ts` 的本地包清单，"
        "否则前端**读不到**（与 Agent 能力四处接线同理）——已注册 `shiguang-avatar-pack`。"
        "★ 双库同步：先 diff 证明副库 `src/libtv/promptLibrary.ts` 与主库本次改动前"
        "完全一致（仅差本次 6 行）⇒ 安全同步（备份 `.bak-avatar` + 补 6 行 + 复制"
        "提示词包到副库 public/prompts 与 dist/prompts）⇒ 双库校验回到基线"
        "（一致 64 / 分叉 22 / 缺失 16，exit=0）。"
        "★ 验证：vitest 76 例全过（批量 7 文件 68 例 + MagneticEngine 单跑 8 例，"
        "沙箱少收集为已知现象）；tsc 37 处 = 文档基线；vite build 成功；"
        "守卫 85 locks intact。"
    ),
}
