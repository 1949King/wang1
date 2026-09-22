"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.37.6"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 37,
    "patch": 6,
    "codename": "六级降级体系 + L3 降质重试（异构协作引擎规格书切片③）",
    "release_date": "2026-09-23",
    "description": (
        "V4.37.6: 规格书切片③——异常处理与六级降级（§44-46）形式化落地。"
        "★ 新模块 app/core/ai/degradation.py（纯模块）：七级定义（L0 完整交付 + "
        "规格六级；L1 双路/L4 功能为预留位，诚实声明）；DegradationSession 降级轨迹"
        "（终态取最严重一级 6>5>4>3>2>1>0）；classify_error 失败四分类"
        "（resource/auth/model/unknown）；24h 滚动统计（各级计数/降级率/最严重级）。"
        "★ L3 质量降级是新增真实行为：全部真实渠道失败且含**资源类**错误"
        "（超时/OOM/429/限流）且原请求高于 480p 时，在本地兜底之前用首个真实渠道"
        "按 480p 重试一次（成本封顶：只试一次只降一档）——认证/模型类失败不降质"
        "（降了也白降，直接兜底）。"
        "★ 关键修正：local 占位实际在 provider 链**循环内**交付（不在循环后兜底块），"
        "L6 标记与 L3 重试都移到链内正确位置；显式 provider=local 是主动选择不算降级。"
        "★ 可观测：last_degradation() 本线程可查（管线/Agent 能回答「这次降到哪级」）；"
        "终态进统计（degradation_rate/by_level/worst）。"
        "验证：check_degradation 33 项全过（级别优先级/分类器/统计/端到端五种终态/"
        "主动选择豁免）；注册 run_all_checks（42→43 项）。"
    ),
}
