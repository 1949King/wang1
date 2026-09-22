"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.38.4"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 38,
    "patch": 4,
    "codename": "端到端仿真器（异构协作引擎规格书切片⑪）",
    "release_date": "2026-09-23",
    "description": (
        "V4.38.4: 规格书切片⑪——第十一篇端到端仿真器，引擎的「试飞风洞」。"
        "★ 新模块 app/core/ai/simulator.py（纯模块）：五属性全落地——"
        "同代码（直接驱动生产控制器 pacer/gprice/priors/probe/modes/sched/"
        "review，只替换模拟执行层，零 ffmpeg 零网络）；零成本（独立 tmp 存储"
        "不碰 data/*.json，虚拟拍推控制器不 sleep）；可复现（random.Random"
        "(seed)，报告指纹 digest——只覆盖引擎状态，时钟类字段必须排除，"
        "否则同种子也不同指纹：踩坑记录在案）；可回归（digest+不变量直接进"
        "检查）；故障注入（429风暴/断网/超支/评分漂移——漂移按 §76 分布外"
        "强制必检处理）。"
        "★ 四大用途：参数标定（κ 三档 sweep）；收敛验证（λ 序列尾部方差）；"
        "多任务不变量（每轮拍卖 Σ≤剩余逐轮断言）；极限压力（200 单元决策"
        "均时 <1ms，§69 O(1) 红线实测）。"
        "验证：check_simulator 17 项全过；run_all_checks 50→51 项。"
    ),
}
