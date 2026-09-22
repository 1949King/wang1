"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.37.4"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 37,
    "patch": 4,
    "codename": "质量先验库 + 收益函数选路（异构协作引擎规格书切片①）",
    "release_date": "2026-09-23",
    "description": (
        "V4.37.4: 把《异构动态协作引擎规格书》v4.3 的思想以最小可行切片优化进项目——"
        "★ 新增 app/core/ai/quality_prior.py（规格 §14/§39）：分桶 EMA 质量先验库"
        "（provider×kind），mean/var/n 递推（α=0.3，标准 EMA 方差公式）；"
        "inherit() 冷启动不确定度（新桶继承均值、方差×4≥0.25）；"
        "JSON+原子写持久化 data/quality_prior.json；记录异常绝不抛出（RLock——"
        "首版 Lock 嵌套 _ensure_loaded 自我死锁，与 _clips_lock 同款约束，已修）。"
        "★ 收益函数选路（规格 §11）：provider_caps.resolve_order 加可选 priors 参数"
        "（additive 向后兼容）——V = q̂ − λ_c·price（λ_c=0.2）替代纯 tier 排序；"
        "q̂ 缺失用中性 0.5 冷启动探索位，tier 做平局 tiebreak；local 永远兜底不变。"
        "★ 闭环回写：video_generation_client 成败后 _record_prior 回写先验"
        "（local 占位不记录——占位成功≠质量信号）；选路时从先验库构建 priors 字典"
        "传入，先验库不可用自动退回 tier 排序。"
        "★ 诚实边界：当前观测样本是执行成败（可用性先验）；待 B 模块评分器接入后"
        "record_outcome(quality=五维分) 直接改喂真值，路由零改动。"
        "验证：check_quality_prior_routing 28 项全过（EMA 数学/继承/持久化/"
        "收益排序反超/向后兼容/端到端假 provider）；注册 run_all_checks（41→42 项）。"
    ),
}
