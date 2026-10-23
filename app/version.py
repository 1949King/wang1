__version__ = "4.46.9"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 9,
    "codename": "用法感知显存策略（首图后热提升 -25%）+ 装不下不硬上",
    "release_date": "2026-10-24",
    "description": (
        "V4.46.9：把「单张走 offload、连续走整卡」这条**只测过没接线**的优化真正落地。\n"
        "\n【① 首图后热提升（实测 -25%）】\n"
        "策略：首图仍按 offload 出（用户立刻拿到结果）→ 出完后若显存放得下，热提升到\n"
        "整卡常驻 → 之后每张都吃整卡的速度。实测（SD1.5 512²/20步，4060 8GB）：\n"
        "  第1张 5.42s（含提升开销）· 第2~4张 3.10/3.12/3.14s · 提升后剩 4.84GB\n"
        "  对照 offload 稳态 4.17s ⇒ **-25%**（与历史预测量 -26% 吻合）\n"
        "判据用「实测空闲显存 + 注册表权重大小」而不是模型名 ⇒ 换大显存机器自动生效。\n"
        "\n【② 装不下就不动（安全边界，实测）】\n"
        "`promotion_fits(size_gb, total_vram)`：需 size×1.15 + 1.2GB ≤ 显存×0.92\n"
        "  SD1.5 3.97GB/8GB → True（实测提升成功）\n"
        "  SDXL  6.46GB/8GB → False（实测整卡后空闲 0.00GB）⇒ 保持 offload\n"
        "  SDXL  6.46GB/24GB → True（换机器自动允许）\n"
        "★ 先判再动：拒绝时**不去 to('cuda')**，避免「先把卡塞爆再回退」的危险动作。\n"
        "真机验证：SDXL 状态 kept_offload、offload=model、理由如实写\n"
        "「模型 6.46GB 整卡装不下（总显存 8.0GB，需 8.63GB）」。\n"
        "\n【③ 修一个真实的进程级显存残留】\n"
        "实测：SD1.5 整卡常驻 → unload → 同进程再 load SDXL，SDXL 会因显存碎片换页卡死\n"
        "（>22min）。unload() 改为「gc.collect → synchronize → empty_cache → ipc_collect」\n"
        "并重置热提升状态（换模型必须重新评估能不能整卡）。\n"
        "\n【④ 诚实性修复】\n"
        "结果里的 memory_mode 曾报提升**之后**的模式（第1张明明跑 offload 却报 none）。\n"
        "现在报**本次实际执行**用的模式，并新增 promote_after 字段回显提升结果。\n"
        "\n【⑤ 澄清一个错误假设（A/B 实测）】\n"
        "我曾怀疑装 peft 导致 SDXL 慢 14×（那次单张 342s）。单变量 A/B：\n"
        "  屏蔽 peft：load 11.1s · 稳态 25.11s\n"
        "  装着 peft：load 11.4s · 稳态 26.46s\n"
        "⇒ peft 只带来 ~5% 开销，**不是 14×**；342s 是环境性换页（被 kill 进程残留状态）。\n"
        "同时披露：LCM 各档是在装 peft 后测的，基线 24.99s 是装之前测的，故 LCM 的\n"
        "「时间占比」含约 5% 偏差（结论不变，但数字应这样理解）。\n"
        "\n【验证】test_quality_presets.py 扩到 14 例（can_promote/promotion_fits/未知道具不\n"
        "盲提升/unload 重置状态/回退安全）；真机验证 SD1.5 提升成功与 SDXL 拒绝提升。\n"
        "全量 pytest 与 107 项门禁见 CHANGELOG。\n"
        "\n【遗留】热提升后若显存被其他程序挤占，只在**下次生成 OOM** 时才回退（当前是\n"
        "「回退 + 如实报错请重试」，不做自动重试）；SDXL 在 8GB 上永远走 offload。\n"
        "\n【上一版 V4.46.8『质量档位 + LCM 安全装载』见 docs/CHANGELOG.md。】"
    ),
}
