"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.37.5"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 37,
    "patch": 5,
    "codename": "真值质量观测回写（异构协作引擎规格书切片② B模块评分器）",
    "release_date": "2026-09-23",
    "description": (
        "V4.37.5: 规格书切片②——B 模块评分器最小落地，质量先验从「可用性」升级为「真值」。"
        "★ 观测器即初检：ai_video_generation_pipeline._generate_and_inspect 的初检"
        "（+守护质检）就是本项目的质量观测器——通过/未过即真值样本，经新纯函数"
        "quality_from_inspection 映射（通过 1.0 / 未过 0.3 / 跳过 None=观测门控§35"
        "不污染先验），写入 quality_prior 的 quality 桶。"
        "★ 渠道归因（Provenance）：provider=auto 时实际渠道在 client 内部解析，"
        "新增线程局部 last_used_provider——生成成功/兜底时盖章，管线同线程读取"
        "归因；多并发生成互不串扰；local 占位仍不产生质量信号。"
        "★ 真值接管路由：quality_prior.route_mean 真值桶（quality）优先、"
        "可用性桶（default）兜底、无数据中性 0.5；选路 priors 构建切换为 route_mean——"
        "真值一记录就自动接管，可用性信号退居兜底，路由代码零改动。"
        "验证：check_quality_prior_routing 28→41 项全过（观测映射/桶优先级/"
        "TLS 归因/管线静态接线四组新增）。"
    ),
}
