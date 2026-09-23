"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.38.6"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 38,
    "patch": 6,
    "codename": "画布卡片尺寸统一 + 上端吸附对齐（画布 0.3.1）",
    "release_date": "2026-09-23",
    "description": (
        "V4.38.6: 画布缺陷修复（用户反馈两条，冻结区 canvas-magnetic-intent "
        "授权解冻后实施）。"
        "① **卡片大小不统一**：小白卡原为 minHeight:200，正文区内容叠加"
        "（提示语+缩略图 96+正文 3 行+元信息）实测把卡片撑到 ≈306px，同屏高矮差"
        "超 100px，且违反冻结不变量「DOM 实尺寸必须 240×200（磁吸落位基准）」"
        "——本次是**恢复**不变量：CARD_GEOMETRY.minHeight→height:200，"
        "NoviceCard 内联改 height、移除 body 内联 minHeight，.nv-card-body 补"
        " min-height:0 + overflow:hidden，缩略图 96→72 且弹性收缩"
        "（flex:1 1 auto / min 40），正文 clamp 3→2 行。"
        "② **最上端吸附没对齐**：getSnapPosition 的 top/bottom 分支原为"
        "「x 取拖拽卡当前值」（2026-09-18 单轴吸附裁定），导致上下贴住后左右边缘"
        "错开不成列；改为 x 取 targetPos.x（顶边对齐）；left/right 单轴语义保持"
        "不变（保留 09-18 修掉的「横吸时 y 瞬移一整卡高」修复）。"
        "验证：vitest 8 文件 76 例全绿（首轮一次跑全；后续批量运行受沙箱 SSR 缓存写"
        "限制偶发少收集文件，拆批累计仍 76 例，非测试失败）；tsc 37 处 = 文档基线"
        "（改动文件 0 命中）；vite build 成功；**渲染实测**（Edge 无头截图 + "
        "getBoundingClientRect）：4 种卡片形态全部 240.0×200.0、正文区裁切 0px —— "
        "该实测又抓出两处（hint/meta 被 flex 压扁裁字；四层内容在 200px 内装不下、"
        "实测裁 45px），已按「有图时提示语折叠 + 正文 1 行」收敛；"
        "双库无新增漂移（canvasVersion.ts 已同步副库）；守卫 85 locks intact；"
        "已同步 frozen_zones.json 不变量 + 现行技术文档 §5 + 知识库 17 号专文。"
        "证据图：docs/_reports/2026-09-23-画布卡片尺寸实测.png。"
    ),
}
