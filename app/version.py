__version__ = "4.46.0"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 0,
    "codename": "画布「代码成片」节点 · V4.46",
    "release_date": "2026-10-20",
    "description": (
        "V4.46.0：画布 codeVideo 节点 + 渲染端点 + SSE 进度（用户授权解冻 canvas-magnetic-intent）。\n"
        "\n【新增】\n"
        "① 前端「代码成片」节点（codeVideoNode.tsx）：分镜表 JSON / CodeVideoSpec JSON 二选一，\n"
        "  渲染→节点内播放→一键加入时间线；失败显示 stage+error，不伪造成功；\n"
        "② 客户端 codeVideoClient.ts：提交/状态查询/SSE 事件过滤（纯函数可测）；\n"
        "③ 后端 POST /host/code-video/render + GET /host/code-video/status；\n"
        "④ 异步任务 canvas_code_video_jobs.py（一任务一线程、最近 20 个/1h、结果带 QC）；\n"
        "⑤ render_host 增加 on_progress 粗粒度进度（compile/security/resolve/page/qc/render/validate/publish/done），\n"
        "  独立 progress.py 保持 render_host 行数基线；\n"
        "⑥ 节点注册四处：registerBuiltinNodes / NodePalette / ports.ts / novice 小白入口（23 kind）；\n"
        "⑦ 守卫 CODEVIDEOCANVAS（98 项体检）+ 后端任务 4 例单测 + 前端 4 例客户端单测。\n"
        "\n【不改】\n"
        "磁吸阈值 120/50/60/instant10、卡片尺寸 240×200、gap=-2、三段式阻力、灯光/配色/交互全部未动；\n"
        "codeVideoSpec 契约/渲染引擎（V4.44/V4.45）未改，只加进度旁路。\n"
        "\n【验证】真机 E2E：HTML 镜头 0.5s → mp4，QC dual_shuffle/flat_frame/text_safe_area 全 pass；\n"
        "全量 run_all_checks 98 项；vitest 591 例；pytest 1,774 passed；tsc 37 错=基线；冻结区 107 锁重锁完整。\n"
        "\n【上一版 V4.45.1『启动提速』见 docs/CHANGELOG.md。】"
    ),
}
