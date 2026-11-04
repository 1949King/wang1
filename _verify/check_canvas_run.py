# -*- coding: utf-8 -*-
"""「运行到此处」接线守卫（刀 A4 第 3 项，2026-10-05）。

**先说清楚现状**（差点写成第二个实现，故把结论固化在这里）：
后端图执行**早就建好了** —— `POST /host/canvas-run` → `canvas_workflow_runner.run_graph`，
已含拓扑序（`topo_order`/`is_dag`）、**指纹增量缓存**（`canvas_node_cache`）、
端口问题报告、`counters`、以及**默认 `dry_run=True`（只出计划）**的「确认后执行」语义；
配套 `POST /host/canvas-cache` 管缓存。**当时缺的只有前端调用方**。

所以本守卫第一条就是**反模式锁**：不许再出现第二个「图规划/执行」实现
（我确实写过一版 `ai/canvas_run_planner.py`，发现重复后已删除）。

其余锁「接线每一环都真的接上」：
  后端端点 → 调既有 runner（不是重写）· 默认 dry_run · 前端桥 → **POST** 且
  `dry_run` 只在明示执行时才发（后端按「显式 false」判定）· App.tsx 真的调用 ·
  canvasRun.ts 已登记进路由契约扫描（否则新端点对契约检查隐身）。

零依赖：只读源码。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POST_PY = os.path.join("app", "core", "canvas_routes_post.py")
RUNNER_PY = os.path.join("app", "core", "canvas_workflow_runner.py")
RUN_TS = os.path.join("vendor", "packages", "canvas-core", "src", "canvasRun.ts")
APP_TSX = os.path.join("vendor", "packages", "canvas-core", "src", "App.tsx")
ROUTES_GUARD = os.path.join("_verify", "check_canvas_routes.py")
DEAD_PLANNER = os.path.join("app", "core", "ai", "canvas_run_planner.py")

_fails = []


def _fail(msg: str) -> None:
    _fails.append(msg)


def _read(rel: str) -> str:
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        _fail(f"文件缺失：{rel}")
        return ""
    return open(p, encoding="utf-8").read()


def _endpoint_body(src: str, name: str) -> str:
    if f"def {name}" not in src:
        return ""
    return src.split(f"def {name}", 1)[1].split("\n    @", 1)[0]


def check_no_second_implementation() -> None:
    """★ 反模式锁：不得再出现第二个图规划/执行实现。"""
    if os.path.isfile(DEAD_PLANNER):
        _fail("① canvas_run_planner.py 回流 —— 图推理的单一真源是 canvas_workflow_runner，"
              "不要再造第二个（拓扑/环检测/增量缓存都在那边，重复实现必然漂移）")
    for rel in (POST_PY, os.path.join("app", "core", "canvas_server.py")):
        src = _read(rel)
        if "canvas_run_planner" in src:
            _fail(f"① {rel} 引用了 canvas_run_planner（重复实现）")


def check_endpoint_uses_runner() -> None:
    src = _read(POST_PY)
    body = _endpoint_body(src, "_p_host_canvas_run")
    if not body:
        _fail("② 找不到 /host/canvas-run 端点实现")
        return
    if "run_graph(" not in body:
        _fail("② 端点未调用 canvas_workflow_runner.run_graph（就地重写了图逻辑？）")
    if "canvas_workflow_runner" not in body:
        _fail("② 端点未从 canvas_workflow_runner 取实现")
    if "topo_order(" in body or "is_dag(" in body:
        _fail("② 端点内自行做拓扑/环检测 ⇒ 第二个实现（应由 runner 负责）")


def check_dry_run_defaults_true() -> None:
    """默认只出计划 —— 「确认后执行」的北极星语义不能丢。"""
    body = _endpoint_body(_read(POST_PY), "_p_host_canvas_run")
    if not body:
        return
    if 'get("dry_run", True)' not in body:
        _fail('② 端点未以 `dry_run` 缺省 True（默认真跑会绕过「确认后执行」）')
    if '"false"' not in body and "'false'" not in body:
        _fail("② 端点未处理「显式 false」字符串（bool(\"false\") 是历史坑）")


def check_cache_endpoint_exists() -> None:
    if '@_route_post("/host/canvas-cache")' not in _read(POST_PY):
        _fail("③ 缺 POST /host/canvas-cache（增量缓存无法查看/清理）")


def check_runner_has_the_core_pieces() -> None:
    src = _read(RUNNER_PY)
    for probe in ("def topo_order(", "def is_dag(", "def run_graph(", "canvas_node_cache"):
        if probe not in src:
            _fail(f"④ runner 缺核心件 {probe}")


def check_frontend_bridge_contract() -> None:
    src = _read(RUN_TS)
    if "/host/canvas-run" not in src:
        _fail("⑤ canvasRun.ts 未调用 /host/canvas-run")
    if 'method: "POST"' not in src:
        _fail("⑤ canvasRun.ts 未用 POST（后端只注册 POST）")
    # dry_run 只在明示执行时才发：缺省必须让后端用自己的默认
    if re.search(r"dry_run:\s*args\.dryRun\s*!==\s*false\s*\?", src):
        _fail("⑤ dry_run 被无条件写入（应只在 dryRun===false 时才发，避免与后端默认理解不一致）")
    if 'if (args.dryRun === false) payload.dry_run = false;' not in src:
        _fail("⑤ 缺「只在明示执行时发 dry_run=false」的写法")
    if "/host/canvas-cache" not in src:
        _fail("⑤ canvasRun.ts 未提供增量缓存查询（stats）入口")


def check_frontend_wired() -> None:
    app = _read(APP_TSX)
    run_ts = _read(RUN_TS)
    # 2026-10-05：编排体抽到 canvasRun.ts（App.tsx 顶到规模守卫 2000 行），
    # 故 App.tsx 调的是编排入口 runGraphWithConfirm，由它再调 runCanvasGraph。
    if "runGraphWithConfirm" not in app:
        _fail("⑥ App.tsx 未调用 runGraphWithConfirm ⇒ /host/canvas-run 无人消费（死代码）")
    if "runCanvasGraph" not in run_ts:
        _fail("⑥ canvasRun.ts 的编排未调用 runCanvasGraph（桥被架空）")
    if "runToHere" not in app:
        _fail("⑥ App.tsx 缺 runToHere")
    if "confirm(" not in app and "confirm(" not in run_ts:
        _fail("⑥ 缺执行前确认（默认 dry_run 拿计划后必须让用户确认）")
    if "formatPlanForConfirm" not in run_ts:
        _fail("⑥ 缺计划展示文本（确认时要把付费/跳过明细摆给用户，而不是一句「要执行吗」）")


def check_registered_in_route_contract() -> None:
    if "canvasRun.ts" not in _read(ROUTES_GUARD):
        _fail("⑦ canvasRun.ts 未登记进 check_canvas_routes 的 CLIENTS（端点会隐身）")


def main() -> int:
    print("=" * 62)
    print("「运行到此处」接线守卫（刀 A4 第 3 项）")
    print("=" * 62)
    for fn in (check_no_second_implementation, check_endpoint_uses_runner,
               check_dry_run_defaults_true, check_cache_endpoint_exists,
               check_runner_has_the_core_pieces, check_frontend_bridge_contract,
               check_frontend_wired, check_registered_in_route_contract):
        try:
            fn()
        except Exception as e:
            _fail(f"{fn.__name__} 抛异常: {type(e).__name__}: {e}")
    if _fails:
        print("✗ 失败项：")
        for p in _fails:
            print(f"  - {p}")
        return 1
    print("OK 单一实现（无第二个规划器）· 默认只出计划 · 前端接线+确认+契约登记")
    return 0


if __name__ == "__main__":
    sys.exit(main())
