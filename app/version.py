"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.37.3"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 37,
    "patch": 3,
    "codename": "云端视频渠道接线：DashScope 万相（渠道探测+掌控验证）",
    "release_date": "2026-09-22",
    "description": (
        "V4.37.3: 免费视频渠道调研 + 云端可用性实测 + 渠道掌控端到端验证。"
        "★ 渠道选型：不需要第三方 API 集成站——项目已有的 DASHSCOPE_API_KEY "
        "（阿里云百炼）自带万相（Wan）文生视频，国内直连、key 已验证有效。"
        "★ 新增 app/core/ai/dashscope_video.py（纯模块，不 import app 包）："
        "legacy 异步协议（POST video-synthesis → GET tasks 轮询 → 当场下载，"
        "video_url 24h 有效不缓存）；模型回退链 wan2.2-t2v-flash → wanx2.1-"
        "t2v-turbo → wanx2.1-t2v-plus（命名坑：wan2.1 系带 x）；"
        "AccessDenied 识别为可降档错误（实测老账号对未开通模型返 403）；"
        "probe() 用非法模型名触发 400 做零成本连通性探测。"
        "★ 三处接线：provider_caps 声明表 + DEFAULT_REAL_ORDER 首位、"
        "video_generation_client 延迟加载（key 缺失返回 None 自动跳过）+ "
        "list_providers 展示、provider_pool 降级回退顺序。"
        "★ 实测结论：key 认证通过 + 端点可达（qwen-turbo 文本调用成功证明账号健康），"
        "但万相视频模型未开通（三个模型 ID 全 403 AccessDenied）——"
        "需用户在百炼控制台模型广场手动开通 wan2.2-t2v-flash（开通即送 50s/90 天）。"
        "★ 渠道掌控验证：test_channel_control 20 项全过——能力路由（auto 首选/报价/"
        "i2v 正确筛除）、延迟加载、额度池记账（掩码/选中/三连败冷却退避）、"
        "端到端回退（真实 403 被记录 → 无中断降级 → 本地占位出片）。"
        "教训：同一文件的两个 Edit 并行执行会互相覆盖（丢失更新），必须串行。"
    ),
}
