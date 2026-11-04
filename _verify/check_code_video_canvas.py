# -*- coding: utf-8 -*-
"""V4.46 codeVideo 画布接线守卫（2026-10-20）

锁住「节点 → 客户端 → 端点 → 异步任务 → 渲染回调」这条链，防止任一段被删后
静默退化成「节点在、点了没反应」。纯静态检查，零运行时依赖。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def main() -> int:
    errors = []
    server = _read("app/core/canvas_server.py")
    routes = _read("app/core/canvas_routes_code_video.py")
    jobs = _read("app/core/canvas_code_video_jobs.py")
    render_host = _read("app/core/code_video/render_host.py")
    client = _read("vendor/packages/canvas-core/src/codeVideoClient.ts")
    node = _read("vendor/packages/canvas-core/src/codeVideoNode.tsx")
    register = _read("vendor/packages/canvas-core/src/registerBuiltinNodes.ts")
    palette = _read("vendor/packages/canvas-core/src/NodePalette.tsx")
    ports = _read("vendor/packages/canvas-core/src/ports.ts")
    novice = _read("vendor/packages/canvas-core/src/novice/types.ts")
    caps = _read("app/core/capability_handlers_code_video.py")

    # 1. 后端端点 + mixin 继承
    for path in ("/host/code-video/render", "/host/code-video/status"):
        if path not in routes:
            errors.append(f"缺少路由 {path}")
    if "CanvasCodeVideoRoutesMixin" not in server:
        errors.append("canvas_server 未引用 CanvasCodeVideoRoutesMixin")
    elif "_BridgeHandler(" in server and "CanvasCodeVideoRoutesMixin" not in server.split("class _BridgeHandler(", 1)[1][:400]:
        errors.append("_BridgeHandler 未继承 CanvasCodeVideoRoutesMixin")

    # 2. 异步任务 + 进度事件
    for token in ("start_job", "get_job", "on_progress",
                  "code_video.progress", "code_video.done", "code_video.error"):
        if token not in jobs:
            errors.append(f"任务层缺少 {token}")
    if "on_progress" not in render_host:
        errors.append("render_host.render 未接收 on_progress")

    # 3. 前端客户端路径与端点一致
    if "/host/code-video/render" not in client or "/host/code-video/status" not in client:
        errors.append("codeVideoClient 路径与后端不一致")
    if "subscribeCodeVideoJob" not in node or "startCodeVideoRender" not in node:
        errors.append("codeVideoNode 未接客户端")

    # 4. 节点注册三处（注册表 / 调色板 / 端口 / 小白入口）
    if "CodeVideoNode" not in register or "codeVideo" not in register:
        errors.append("registerBuiltinNodes 未注册 CodeVideoNode")
    if "codeVideo" not in palette:
        errors.append("NodePalette 缺少 codeVideo")
    if "codeVideo:" not in ports:
        errors.append("ports.ts 缺少 codeVideo 端口")
    if "codeVideo:" not in novice:
        errors.append("novice/types.ts 缺少 codeVideo 入口")

    # 5. 能力目录仍注册渲染能力
    if "pipeline.code_video_render" not in caps:
        errors.append("能力层缺少 pipeline.code_video_render")

    if errors:
        print("✗ codeVideo 画布接线不完整：")
        for e in errors:
            print("  -", e)
        return 1
    print("OK codeVideo 画布接线完整（节点/客户端/端点/异步任务/进度/能力）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
