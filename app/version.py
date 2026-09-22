"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.38.5"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 38,
    "patch": 5,
    "codename": "引擎接口规范 + 错误码体系（异构协作引擎规格书切片⑫·终篇）",
    "release_date": "2026-09-23",
    "description": (
        "V4.38.5: 规格书切片⑫——第十篇接口规范，异构引擎 12 切片全部落地。"
        "★ 新模块 app/core/ai/engine_api.py（统一门面）：四大标准接口——"
        "create_task（模块校验→DAG 提交）、submit_unit（月账单硬闸→生成→"
        "归因五件套：渠道/实际模式/模式计划/降级终态/融合溯源）、"
        "route_callback（凭 unit_id 取全归因，LRU 200 条）、"
        "resource_report（L1 预算/L0 账单/调度/抽检四视图）；"
        "统一响应信封 {ok,code,message,data}；错误码单一来源 11 个 ERR_*"
        "（禁裸字符串，同 agent_constants 纪律），全部带人话标签。"
        "★ 至此规格书 14 篇全部有落点（详见 CHANGELOG 完成度对照表）："
        "V4.37.4~4.37.7 四片（先验/真值/降级/PI）+ V4.37.8~4.38.5 八片"
        "（模式/探针/融合D/两层λ/抽检/模块DAG/仿真器/接口）。"
        "验证：check_engine_api 19 项全过；run_all_checks 51→52 项。"
    ),
}
