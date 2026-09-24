"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.39.1"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 39,
    "patch": 1,
    "codename": "注音字典补齐（专名校订 + lip_sync 挂载）",
    "release_date": "2026-09-25",
    "description": (
        "V4.39.1: 注音字典齐全度体检 + 针对性补齐。"
        "★ 体检实测（硬数据）：CJK 基本区 99.7%（20924/20992）、扩展 A 87.7%、"
        "扩展 B **31.1%**；**专名读音错误率 20%**（25 例错 5：大宛→wǎn 应 yuān、"
        "皋陶→táo 应 yáo、金日磾→rì 应 mì、樊於期→yú qī 应 wū jī、"
        "曹参→cān 应 shēn）、易错词「削苹果」→xuē 应 xiāo —— 古装短剧里"
        "古人名/地名密度极高，不校订会成片读错。"
        "★ 补齐①：内置人工校订表（**169 词组 + 24 单字**）经 "
        "pypinyin.load_phrases_dict/load_single_dict 注入，覆盖古人名、复姓、"
        "地名、成语易错词；**字数不符的条目自动跳过并报告**（绝不静默错位）；"
        "校订后专名 25/25、易错词 24/24（原 20/25、25/26）。"
        "★ 补齐②：新增项目自定义读音表 `data/pinyin_overrides.json`"
        "（`override_template()` 给模板）—— 剧中人名/门派名读音可全项目统一，"
        "优先级最高可覆盖内置条目。"
        "★ 补齐③：**lip_sync 改走字典入口**（原直接 import pypinyin 拿不到校订）"
        "⇒ 口型与 TTS 正音**同源**，消除「配音读 chóng、口型按 zhòng」的音画不一致；"
        "并用 chars 详情过滤非汉字，修掉「'abc123' 被当成一个音素传下游」。"
        "★ 依赖：pypinyin>=0.53.0 入 requirements.txt 与 app/requirements-optional.txt"
        "（可选语义：缺失诚实降级不阻断启动）+ DependencyChecker.OPTIONAL_PACKAGES。"
        "★ 诚实边界：**扩展 A/B 区未补齐**（补齐需引入 Unihan 数据约 8MB，"
        "而扩展 B 字在实际字幕中几乎不出现）——覆盖率缺口已在 stats() 显式标注，"
        "查不到的字标 unknown、绝不编造读音。"
        "验证：check_pinyin_dict 49/49 全过（新增专名 25 例 + 易错词 24 例 + "
        "lip_sync 3 项接线断言）；check_tts_guard 47 项全过；"
        "三向一致核对全绿；守卫 85 locks intact（改动全在冻结区外）。"
    ),
}
