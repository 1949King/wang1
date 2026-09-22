"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.37.8"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 37,
    "patch": 8,
    "codename": "六种执行模式 + 可行集投影（异构协作引擎规格书切片⑤）",
    "release_date": "2026-09-23",
    "description": (
        "V4.37.8: 规格书切片⑤——第三篇模型调度器的「单元由谁执行」形式化。"
        "★ 新模块 app/core/ai/execution_modes.py（纯模块）：Mode∈{L,C,D,L→C,"
        "C→L,SkipMerge} 六枚举；§11 定稿收益函数 V=q̂−λ_c·(ĉ−c_base)−λ_l·(l̂−l_base)"
        "−κ_sw·1{switch}——基线写死为本地（本地惩罚恒 0，宽松预算自然收敛本地，"
        "杜绝 v4.0 D 模式泛滥/λ 顶饱和）；融合质量上界 q_D=1−(1−q_L)(1−q_C)；"
        "L→C/C→L 按达标概率求期望。"
        "★ §12 可行集投影正交铁律：打分层纯收益最大化，投影层只删不可行选项、"
        "绝不修改打分（快照断言守护）；collect_infeasible 把断网/无 key/显存不足"
        "翻译成模式删除清单；choose_mode 返回完整归因字典（分数/删除理由/λ/基线）。"
        "★ 接线：client 选路时产出模式计划存 TLS（last_mode_plan），generate 末尾"
        "记录实际执行模式（last_execution_mode：C / C→L / L），计划 vs 实际可审计。"
        "执行体语义不变（既有 provider 链 = C→L），D 执行体待切片⑦接线。"
        "验证：check_execution_modes 27 项全过；run_all_checks 44→45 项。"
    ),
}
