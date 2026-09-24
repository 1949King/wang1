"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.39.2"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 39,
    "patch": 2,
    "codename": "Unihan 补丁表（A）+ LLM 消歧候选约束（B）",
    "release_date": "2026-09-25",
    "description": (
        "V4.39.2: 用户选定「A 和 B 同时」。两条均由实测数据驱动，"
        "并纠正了上版抽样得出的两个不准口径。"
        "★ A：从 Unicode 官方 Unihan 数据库 kMandarin（44355 条）筛出"
        "pypinyin 查不到的 2517 字，生成 app/core/ai/pinyin_unihan_patch.py"
        "（编译进代码，64KB，零打包配置）；仅在主词典查不到时兜底"
        "（不覆盖 pypinyin，避免官方读音被常用读音顶掉）。"
        "生成工具 scripts/gen_unihan_pinyin_patch.py（正式工具可重跑）。"
        "**精确实测（逐字遍历）纠正上版口径**：扩展 B 实为 34.0%（上版抽样"
        "误报 31.1%）；三区合计 58.6% → 含补丁 58.8%。"
        "**诚实边界**：补丁分布极冷门（扩展 G 1098 · E 705 · C 386 · I 99 · "
        "B 94 · D 64 · F 61 · A 9 · H 1），与影视字幕实际相关仅约 103 字，"
        "对总覆盖率提升仅 +0.2% ⇒ 是「成本极低、遇到就赚到」，"
        "**不等于补齐扩展区**（彻底补齐需汉语大字典级非开源数据）。"
        "★ B：tts_guard 的 LLM 消歧从「填空」改为「选择题 + 判卷」——"
        "① _candidate_hint 把字典检出的多音字及**全部合法候选**写进提示词"
        "（如 重 ∈ [zhòng, chóng, tóng]）；② _validate_polys 判卷，"
        "读音越界一律丢弃（防 LLM 编造）；③ 批量模式额外校验「字在本段」"
        "（防跨段串味）。LLM 产出全被废时字典兜底接管。"
        "验证：check_pinyin_dict 64/64 全过（新增 15 项）；check_tts_guard 47 项全过；"
        "判卷实测 chóng 保留 / zhǒng 丢弃 / zhòng 保留；守卫 85 locks intact。"
    ),
}
