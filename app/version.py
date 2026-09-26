"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.40.4"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 40,
    "patch": 4,
    "codename": "A4 路由巨石拆分（批次 0+1：GET 全迁）",
    "release_date": "2026-09-27",
    "description": (
        "V4.40.4: 评价报告架构债 #2「路由巨石」开始拆解（分批，本轮批次 0+1）。"
        "★ 批次 0 · 路由表下沉：新增 app/core/canvas_route_registry.py"
        " （路由表 + @_route_get/@_route_post + dispatch_table），"
        " canvas_server 与端点 mixin 双方从此取，避免「canvas_server → mixin →"
        " canvas_server」循环导入；canvas_server 内 _dispatch_table 变薄转发。"
        "★ 批次 1 · GET 全迁：do_GET 的 25 个精确路径端点（约 520 行 if 链）"
        " 迁到新增 app/core/canvas_routes_get.py 的 CanvasGetRoutesMixin，"
        " 经 @_route_get 注册；canvas_server.py **3,314 → 2,757 行**"
        "（单文件规模守卫「只减不增」，基线同步下调 3,273→2,757，"
        " 属守卫指引的债务收敛正反馈）。"
        " ★ 行为等价优先：每个 handler 与迁出前逐行等价，401 响应体差异"
        " （chat-models 带 providers:[] 等）原样保留；依赖的模块级符号经"
        " 函数内 _cs() 取 canvas_server 模块访问（同一对象，行为不变）。"
        " 未迁出：/ · /health · /inject.js · /host/agent/events（SSE 长连接）·"
        " /editor_file/* 与 /inbox_file/*（前缀路由，表是精确匹配）· 404 兜底。"
        "★ 契约守卫同步升级（check_canvas_routes.py）：① 服务端路由来源从"
        " 单文件改为 SERVER_FILES 多文件（否则迁出的端点会从「服务端路由」"
        " 消失、前端调用反被误报静默 404——契约检查开天窗）；②「路由表 vs"
        " 老链重复注册」检测**按 HTTP 方法分离**（do_GET/do_POST 同名端点是"
        " 正常设计，整文件扫描会误判 3 个）。"
        "★ 门禁补漏：单文件规模守卫此前不在 hook 里，导致「写代码把文件撑过"
        " 2000 行」无人拦 —— 本次 hook 加第⑧道（8 道卡点）。"
        "★ 顺带：bridge.ts（2,016 行，V4.39.8 异步接线越线）作为存量冻结入"
        " 基线并标注待拆分。"
        "★ 验证：端到端 check_canvas_bridge_e2e（真起服务打端点）全过 ·"
        " 路由契约 OK · 全量 383/383 · ruff 全净 · 冻结区 85 · 稳定性 249≤269 ·"
        " 粘合层 18/0 · 架构 0 警告 · 双库无漂移。"
        " —— 剩余批次 2/3（POST 29 个端点，约 1,046 行）待续。"
    ),
}
