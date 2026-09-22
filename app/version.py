"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.38.0"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 38,
    "patch": 0,
    "codename": "置信度融合器三分 + D 双路执行体（异构协作引擎规格书切片⑦）",
    "release_date": "2026-09-23",
    "description": (
        "V4.38.0: 规格书切片⑦——第八篇融合器（三分架构）+ §10 D 模式真实执行体。"
        "★ 新模块 app/core/ai/fusion.py（纯模块）：铁律「禁止通用张量加权平均」——"
        "文本=字段锁域+命名空间仲裁（锁域不可翻越，逐字段质量分优先于优先级）；"
        "视频=关键帧择优+片段时序拼接（keyframe_ok=False 质量×0.7 降权且"
        "不享受 prefer 让步；差<0.05 稳定偏好；输出拼接计划不动文件）；"
        "音频=轨道分离混音+响度对齐（角色增益 voice1.0/sfx0.7/music0.5，"
        "峰值×增益>target 压回，总线>1 等比压缩，溯源记 pre_bus_gain）；"
        "三算子全程 Provenance 溯源（§42）。"
        "★ D 双路执行体（client._execute_dual）：generate 新 additive 参数 "
        "mode/allow_dual（双路=双倍云端花费，默认关）；顺序双路（本地先云端后）→"
        "分歧实测入库（成本门控内）→逐槽融合→溯源存 last_fusion()；"
        "云端失败诚实退化 C→L+L6，不冒充 D 交付。"
        "踩坑：路由收益排序第一名随先验/λ 浮动，测试只给 dashscope 注假实现导致"
        "first_real=seedance 拿不到云端——三渠道全注入；先验库一并隔离。"
        "验证：check_fusion 28 项全过；run_all_checks 46→47 项。"
    ),
}
