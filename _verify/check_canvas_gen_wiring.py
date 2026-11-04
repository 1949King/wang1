#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""画布生成链路守卫（2026-11-01）

锁两件踩出来的事：

**A. 同步端点 ↔ 异步任务端点必须同一实现**
   前端默认走**异步任务化**（`submit` + 轮询）。如果异步端点搬的是「云端老函数」、
   而同步端点已经接上混合调度，那么用户把算力滑块拉到本地也照样只走云端
   ⇒ 报「没有可用的 AIGC 生图渠道」，而本地 SD 明明已下载。
   **实锤**：`/host/generate-image`（同步）2026-10-23 接了 `generate_image_hybrid`，
   而 `canvas_server._build_gen_callable._run_image` 仍直接调
   `generate_image_openai_compatible` ⇒ 混合调度在默认路径上等于不存在。
   ⇒ 断言：两处「生成函数名」逐 kind 相等（不硬编码期望值，两边对账）。

**B. 节点内「✦ 生成」按钮不得踩 stale 闭包**
   `retryNode` 是 `useCallback(…, [])`（要保引用稳定），若它直接调用组件内的
   `generateForNode`，就会永远抱着**首次渲染**的闭包 —— 那个闭包里
   `selectedModelKey` 是首渲染快照。
   **实锤**：Agent 面板选了「本地·SD1.5」，节点点生成仍走空 channel 的云端。
   ⇒ 断言：`retryNode` 体内不得直呼 `generateForNode(`，必须走 ref。

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_canvas_gen_wiring.py
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ROUTES_PY = os.path.join(ROOT, "app", "core", "canvas_routes_post.py")
SERVER_PY = os.path.join(ROOT, "app", "core", "canvas_server.py")
APP_TSX = os.path.join(ROOT, "vendor", "packages", "canvas-core", "src", "App.tsx")

# kind → (同步端点方法名, 异步 callable 名)
KIND_SYNC_ASYNC = {
    "image": ("_p_host_generate_image", "_run_image"),
    "video": ("_p_host_generate_video", "_run_video"),
    "audio": ("_p_host_generate_audio", "_run_audio"),
    "music": "_p_host_generate_music",
}

_GEN_NAME = re.compile(r"^generate_[a-z0-9_]+(?:_hybrid|_via_host)$")

_failures: list = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


def _funcdefs(path: str) -> dict:
    """收集文件里所有 FunctionDef（含嵌套），按 name 索引。"""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    out: dict = {}

    def walk(node):
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.setdefault(child.name, child)

    walk(tree)
    return out


def _gen_calls(fn) -> set:
    """函数体内调用到的「生成函数」名集合（只认 generate_*_hybrid / generate_*_via_host）。"""
    names = set()
    if fn is None:
        return names
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            name = ""
            if isinstance(f, ast.Name):
                name = f.id
            elif isinstance(f, ast.Attribute):
                name = f.attr
            if name and _GEN_NAME.match(name):
                names.add(name)
    return names


# ── A. 同步 ↔ 异步 同一实现 ───────────────────────────────────────────────
print("[A] 生成链路：同步端点 ↔ 异步任务端点同实现")
_routes = _funcdefs(ROUTES_PY)
_server = _funcdefs(SERVER_PY)

for kind, spec in KIND_SYNC_ASYNC.items():
    if isinstance(spec, str):  # 仅同步（音乐无异步 kind）
        continue
    sync_name, async_name = spec
    _sync_fn = _routes.get(sync_name)
    _async_fn = _server.get(async_name)
    check(_sync_fn is not None, f"{kind}: 找到同步端点 {sync_name}")
    check(_async_fn is not None, f"{kind}: 找到异步 callable {async_name}")
    if _sync_fn is None or _async_fn is None:
        continue
    sync_gen = _gen_calls(_sync_fn)
    async_gen = _gen_calls(_async_fn)
    check(bool(sync_gen), f"{kind}: 同步端点确实调了生成函数（{sorted(sync_gen)}）")
    check(bool(async_gen), f"{kind}: 异步端点确实调了生成函数（{sorted(async_gen)}）")
    check(
        sync_gen == async_gen,
        f"{kind}: 两边生成函数一致（同步={sorted(sync_gen)} / 异步={sorted(async_gen)}）",
    )

# 音乐端点没有走异步任务表（同步直调），但也要确认它真的调了生成函数
_mus = _routes.get(KIND_SYNC_ASYNC["music"])
check(_mus is not None, "music: 找到同步端点 _p_host_generate_music")
if _mus is not None:
    check(bool(_gen_calls(_mus)), f"music: 端点确实调了生成函数（{sorted(_gen_calls(_mus))}）")

# ── B. 节点内生成按钮不得走 stale 闭包 ────────────────────────────────────
print("[B] 节点内「✦ 生成」按钮：retryNode 不得直呼 generateForNode")
with open(APP_TSX, "r", encoding="utf-8") as fh:
    _app_src = fh.read()

_m = re.search(
    r"const retryNode = useCallback\(async \(nodeId: string\) => \{(?P<body>.*?)\n  \}, \[\],?\);",
    _app_src,
    re.S,
)
check(_m is not None, "App.tsx 里找到 retryNode（useCallback 空依赖）")
if _m:
    body = _m.group("body")
    check(
        not re.search(r"generateForNode\s*\(", body),
        "retryNode 体内没有直呼 generateForNode(（直呼=首渲染闭包，模型选择永远滞后）",
    )
    check(
        "generateForNodeRef.current(" in body,
        "retryNode 通过 generateForNodeRef.current( 取最新实现",
    )
check(
    "const generateForNodeRef = useRef(generateForNode)" in _app_src,
    "App.tsx 有 generateForNodeRef 且每次渲染刷新",
)
check(
    "NodeActionsContext.Provider value={nodeActionsValue}" in _app_src,
    "NodeActionsContext 的 value 引用稳定（不每帧新建对象）",
)

print()
if _failures:
    print(f"❌ 画布生成链路守卫失败 {len(_failures)} 项：")
    for f in _failures:
        print(f"   - {f}")
    sys.exit(1)
print("OK 画布生成链路守卫全绿（同步↔异步同实现 + 节点生成按钮不吃 stale 闭包）")
