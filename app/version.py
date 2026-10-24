__version__ = "4.46.17"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 17,
    "codename": "统一推理引擎 M4 · 入口合一（端点注册表路由 + 验证态透出）",
    "release_date": "2026-10-24",
    "description": (
        "V4.46.17：统一引擎路线 M4——两个视频入口收编到注册表裁定之下。\n"
        "侦察修正了设计稿预设：画布 local/ 分支本就走 generate_video_local 统一入口，\n"
        "无需改 canvas_aigc；真正要合的是 ④ 端点的「族盲路由」与验证态不可见。\n"
        "\n【① ④ 端点 → 本地视频统一入口】\n"
        "/host/local-video-generate 从「video_gen 专属」升级：非 svd 族按 model_family\n"
        "声明委托 ③ generate_video_local（族→后端裁定读注册表，新模型接入 = 登记一条\n"
        "spec，端点零改动）。svd 族仍走 ④ 原生（TUNED/档位/蒸馏 CFG 语义所在）。\n"
        "族名解析复用 ③ 的 _guess_model_kind —— 不另造第二套关键词映射（防漂移）。\n"
        "委托 ③ 时 seed 不被本地通道支持 ⇒ 如实进 warnings，不静默假装支持。\n"
        "\n【② ③ 入口的注册表咨询（不拦路）】\n"
        "generate_video_local 执行前查 model_family：verification/warnings 随结果透出\n"
        "（成功/失败都带 —— 失败时 UI 更需要知道这族没验过）。unverified 族警示但\n"
        "照常执行：调用方显式指定 = 最高意图，「未登记 ≠ 不可用」（planner 兜底同理）。\n"
        "\n【③ status 的 families 视图】\n"
        "execution_planner.status() 挂 model_family.status()（族/验证态/权重/后端健康），\n"
        "/host/execution-status 与 execution.status 能力自动获得 —— 画布由此能区分\n"
        "「真验过的 3 族」与「只是登记的 6 族」（library-only 法条的 UI 落点）。\n"
        "\n【④ 顺手修的事实错误】\n"
        "model_family svd note 还写着「M3 委托到 ④ 后退役」——M3 实际是驻留合一、\n"
        "两条实现都保留。登记文本与事实同步。\n"
        "\n【测试 +5 例（test_entry_unify_m4.py，零真权重零 lazy 面）】\n"
        "族名解析复用断言；委托参数映射 + seed 警示；unverified 警示不拦路；\n"
        "未登记族提示补登记仍执行；status families 视图形状与 svd=verified。\n"
        "\n【验证】全量 pytest 1978 passed；run_all_checks 109 项全绿；frozen 106 锁；\n"
        "ruff 棘轮零新增；stability 无新增。\n"
        "\n【上一版 V4.46.16『统一推理引擎 M3 · SVD 驻留合一』见 docs/CHANGELOG.md。】"
    ),
}
