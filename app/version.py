__version__ = "4.46.5"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 5,
    "codename": "执行层专项决策器 + 混合算力（本地 SD × 云端 API）",
    "release_date": "2026-10-23",
    "description": (
        "V4.46.5：用户指令「前面加一个专项执行层模型，让它决定怎么调度本地与 API 之间的\n"
        "运算逻辑和方式；也要能加进画布模块和剪辑模块的智能体」。全在非冻结区。\n"
        "\n【① 执行层专项决策器（新层）】app/core/ai/execution_planner.py\n"
        "此前：本地 SD 引擎（实测 diffsynth 主选、非降级、SD1.5/SDXL/SVD 权重齐全）与\n"
        "云端 API 之间**没有任何统一裁定点**；compute_bias 只是个数字无人消费；\n"
        "decide_execution 生产里只在视频 local/ 分支被调一次，图像路径根本不经过。\n"
        "现在：plan() 一处产出可解释计划 {route, chain, engine, model_hint, reasons,\n"
        "bias, hw_tier, budget_lambda, degrade_level}，按「用户算力偏好 + 本地引擎可用性\n"
        "+ 硬件档 + 预算 λ + 云端 Key」裁定 local / cloud / hybrid 与尝试顺序。\n"
        "诚实边界：本机视频模型 SVD 是 i2v ⇒ 无参考图/首帧时**不声称可本地**（写进\n"
        "reasons 并自动走云端），不假装能纯 prompt 出片。\n"
        "\n【② 混合算力偏好（滑块真源）】app/core/ai/compute_bias.py\n"
        "0≤bias≤24 本地优先 / 25-74 动态混合 / ≥75 云端优先；持久化 data/compute_bias.json\n"
        "（原子写、异常不抛）。Qt「模型广场」头部新增滑块（实时落盘），画布侧经\n"
        "GET/POST /host/execution-bias 读写同一份数据 ⇒ 两端永远一致。\n"
        "\n【③ 执行器严格按计划走】app/core/ai/hybrid_dispatch.py\n"
        "/host/generate-image 改走 generate_image_hybrid：**按 chain 顺序真执行**\n"
        "（先本地失败再云端 / 先云端失败再本地），全链失败时逐路交代原因（不隐藏前一条）。\n"
        "默认档(engine)行为与旧版逐键一致：既有云端链路不变，只有用户拉低滑块才启用本机。\n"
        "\n【④ 智能体可直接调用】execution.plan / execution.status（effect=read，不触发生成\n"
        "与计费）；画布与剪辑两侧共用同一 dispatcher ⇒ 同一套调度语义。\n"
        "\n【验证】execution_planner 12 例 + 密钥诚实失败 9 例全过；全量 pytest 报见 CHANGELOG；\n"
        "run_all_checks 107 项；frozen_zone_guard 106 锁；ruff 棘轮零新增。\n"
        "端点 102→105 唯一（106→109 注册）、能力 126→128（文档数字已同步）。\n"
        "\n【上一版 V4.46.4『数字人口型成片 + 捏脸收口』见 docs/CHANGELOG.md。】"
    ),
}
