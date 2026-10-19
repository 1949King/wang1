__version__ = "4.45.1"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 45,
    "patch": 1,
    "codename": "画布启动 / 功能调用提速（首屏 -64% 流量）",
    "release_date": "2026-10-20",
    "description": (
        "V4.45.1：画布模块启动与端点调用提速（无冻结区改动）。\n"
        "\n【实测瓶颈】\n"
        "① /host/providers 冷调用 4.56s：其中 4.12s 阻塞在 Ollama list_models 的 requests 连接超时；\n"
        "② /host/comfyui/status 每次 2.08s：引擎目录在但 8188 未起时连接超时；\n"
        "③ /host/agent 每次 0.72s：is_listening() 被调用两次（2×0.35s）；\n"
        "④ 前端首屏额外预取 Stage3D 分包 + bodykun/bodychan GLB（约 3.4MB）。\n"
        "\n【修复】\n"
        "· canvas_aigc：Ollama 模型列表改为「立即返回缓存/默认 + 后台刷新」（TTL 300s），\n"
        "  整份渠道配置加 2s TTL 缓存；\n"
        "· canvas_server：启动后后台预热渠道配置 / ComfyUI 状态 / Agent 端口探活；\n"
        "· canvas_routes_get：ComfyUI 状态 5s 缓存 + 预热；/host/agent 只探活一次；\n"
        "· comfy_client.diagnose 超时 8s → 1.2s；canvas_agent_runtime 探活 0.35s → 0.15s + 2s 缓存；\n"
        "· App.tsx：移除首屏 Idle 预取 Stage3D/GLB（改由首次切导演台按需加载）。\n"
        "\n【实测收益】\n"
        "· /host/providers：4.56s → 0.7ms（预热后；首击 ≤19ms）；\n"
        "· /host/comfyui/status：2.08s → 0.5ms（预热后）；/host/agent：0.72s → 0.48ms；\n"
        "· 画布首屏传输 5.34MB → 1.92MB（-64%），JS 1.77MB → 1.16MB，JS 堆 20.5MB → 10MB；\n"
        "· 静态启动 ensure_started 813ms（二次 13ms，端口探活口径）。\n"
        "\n【验证】全量 run_all_checks 97 项全绿；vitest 587 例；tsc 37 错=既有基线；\n"
        "frozen_zone_guard 107 锁完整（本刀零冻结区）。\n"
        "\n【上一版 V4.45.0『渲染引擎刀』见 docs/CHANGELOG.md。】"
    ),
}
