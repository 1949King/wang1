"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.39.0"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 39,
    "patch": 0,
    "codename": "汉字注音字典（离线确定性）+ 四处接线",
    "release_date": "2026-09-25",
    "description": (
        "V4.39.0: 新增离线汉字注音字典并挂载到 TTS 正音与 Agent 能力面。"
        "★ 痛点（真实缺陷）：tts_guard 的「多音字注音」原本让 LLM 现场猜拼音，"
        "LLM 不可用/失败 → 「降级为不注音」→ 整段注音静默消失，且同字两次调用"
        "可能不同（不可复现）。"
        "★ 新模块 app/core/ai/pinyin_dict.py（纯模块，只标准库 + 惰性 pypinyin）："
        "annotate/lookup/polyphones/to_sapi/to_ssml/stats；多音字给出**候选集**"
        "（把 LLM 的「填空」降级成「选择题」）；to_ssml 按**位置**标注"
        "（同一字多处不同音各自正确，优于 build_ssml 的首次出现替换）。"
        "★ 实测覆盖：常用字/生僻字（龘靐齉爨彧）/词组消歧（重庆 chóng qìng、"
        "银行 yín háng）全部正确；**CJK 扩展 B 区（𠀋𠮷）未覆盖 → 标 unknown，"
        "绝不编造读音**（红线）。"
        "★ 挂载：① tts_guard 加字典兜底（新增 annotated_source 字段；"
        "改前 llm=None → 零注音，改后字典接管仍出 phoneme SSML）；"
        "② Agent 能力 pipeline.pinyin_lookup 四处接线齐全（目录表/handler+register/"
        "action 白名单/帮助文案，effect=read、半球=left），action=pinyin_lookup。"
        "★ 依赖：pypinyin>=0.53.0 入 requirements.txt 与 app/requirements-optional.txt"
        "（可选语义：缺失诚实降级不阻断启动）+ DependencyChecker.OPTIONAL_PACKAGES。"
        "验证：check_pinyin_dict 40/40 全过；check_tts_guard 47 项全过"
        "（3 条断言按新行为升级）；三向一致核对全绿；守卫 85 locks intact。"
    ),
}
