# -*- coding: utf-8 -*-
"""Agent 策略派生化守卫（刀 A4，2026-10-05）。

钉死本轮修的两类**静默失效**：

  ① **方法错配**（`/host/model-preload`）：前端用 **POST** 调，后端只注册了 **GET**
     ⇒ 请求根本到不了 handler，handler 里按 `self.command == "POST"` 写的分支成了
     **不可达代码**，前端拿到 404（表现为「点了没反应」）。
     ⇒ 本守卫锁「同一路径必须 GET/POST 都注册」。
     （更一般的 (method, path) 契约检查在 `check_canvas_routes.py` 的 [1b] 段。）

  ② **两个真源**（`agentPolicy.ts` vs `agent_action_registry.py`）：前端曾自持一份
     20+ 条的 effect/paid 映射，后端加工具前端不知道 ⇒ 落到默认分支静默错判
     （轻则多问一次，**重则少问一次**）。现在真源只在后端，前端消费下发值。
     ⇒ 本守卫锁「前端不得再出现硬编码工具表」「未就绪必须保守兜底」
       以及「下发的端点**真的被调用**」（否则又是一段死代码）。

零依赖：只读源码 + AST。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GET_PY = os.path.join("app", "core", "canvas_routes_get.py")
POLICY_TS = os.path.join("vendor", "packages", "canvas-core", "src", "agentPolicy.ts")
APP_TSX = os.path.join("vendor", "packages", "canvas-core", "src", "App.tsx")

_fails = []


def _fail(msg: str) -> None:
    _fails.append(msg)


def _read(rel: str) -> str:
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        _fail(f"文件缺失：{rel}")
        return ""
    return open(p, encoding="utf-8").read()


def check_model_preload_both_methods(src: str) -> None:
    """① `/host/model-preload` 必须 GET（轮询）+ POST（触发）都注册。"""
    if '@_route_get("/host/model-preload")' not in src:
        _fail("① /host/model-preload 缺 GET 注册（前端轮询会 404）")
    if '@_route_post("/host/model-preload")' not in src:
        _fail("① /host/model-preload 缺 POST 注册（前端触发会 404，"
              "handler 里的 POST 分支会变成不可达代码）")
    # 装饰器叠加要求同文件已导入 _route_post（漏导入 = 类定义期 NameError，画布服务起不来）
    head = src.split("class ", 1)[0]
    if "@_route_post" in src and "_route_post" not in re.findall(
            r"from app\.core\.canvas_route_registry import ([^\n]+)", head + src)[0]:
        _fail("① canvas_routes_get.py 未导入 _route_post（叠加装饰器会 NameError）")


def check_agent_policy_endpoint(src: str) -> None:
    """② 后端下发端点存在，且**从单一真源派生**（端点内不得再定义工具表）。"""
    if '@_route_get("/host/agent-policy")' not in src:
        _fail("② 缺 GET /host/agent-policy（前端没有可消费的策略源）")
        return
    body = src.split('def _route_host_agent_policy', 1)
    if len(body) < 2:
        _fail("② 找不到 _route_host_agent_policy 实现")
        return
    fn = body[1].split("\n    @", 1)[0]
    if "_CANVAS_ACTION_ROWS" not in fn:
        _fail("② 端点未从 agent_action_registry._CANVAS_ACTION_ROWS 派生（真源要求）")
    # 端点内不得出现「工具名: {...}」形式的第二份表
    hard = re.findall(r'"\w+(?:Node|Generate|Breakdown|Storyboard|Query\w*)"\s*:\s*\{', fn)
    if hard:
        _fail(f"② 端点内出现硬编码工具表（第二个真源）：{hard[:4]}")


def check_frontend_consumes(src: str) -> None:
    """② 前端不得再自持映射；必须消费下发值 + 保守兜底。"""
    if "const CANVAS: Record<" in src:
        _fail("② agentPolicy.ts 仍有硬编码 CANVAS 映射（两个真源会漂移）")
    # 常见工具名在映射位置上出现 = 手抄表回流
    for probe in re.findall(r'^\s*(?:addNode|deleteNode|runGenerate)\s*:\s*\{', src, re.M):
        _fail(f"② agentPolicy.ts 出现手抄工具条目：{probe.strip()}")
    if "/host/agent-policy" not in src:
        _fail("② agentPolicy.ts 未调用 /host/agent-policy")
    if "CONSERVATIVE" not in src or 'danger: "dangerous"' not in src:
        _fail("② 缺少保守兜底（未就绪/未知工具必须按危险处理，绝不静默放行）")
    if "primeAgentPolicy" not in src:
        _fail("② 缺 primeAgentPolicy（无法把后端策略拉下来）")


def check_frontend_wired(src: str) -> None:
    """端点必须**真的被调用**（否则又是一段死代码 —— 与 model-preload 同类）。"""
    if "primeAgentPolicy" not in src:
        _fail("② App.tsx 未调用 primeAgentPolicy ⇒ /host/agent-policy 无人消费（死代码）")


def check_no_hardcoded_danger_list() -> None:
    """危险级别必须来自后端，前端不得维护第二份「危险工具名单」。"""
    src = _read(POLICY_TS)
    for probe in ('"deleteNode"', "'deleteNode'", "deleteNode ==="):
        if probe in src:
            _fail(f"② 前端出现硬编码危险工具判断 {probe}（应改用下发值的 danger 字段）")


def main() -> int:
    print("=" * 62)
    print("Agent 策略派生化守卫（刀 A4）")
    print("=" * 62)
    get_src = _read(GET_PY)
    for fn in (lambda: check_model_preload_both_methods(get_src),
               lambda: check_agent_policy_endpoint(get_src),
               lambda: check_frontend_consumes(_read(POLICY_TS)),
               lambda: check_frontend_wired(_read(APP_TSX)),
               check_no_hardcoded_danger_list):
        try:
            fn()
        except Exception as e:  # 守卫自身异常也算失败，不静默
            _fail(f"守卫异常: {type(e).__name__}: {e}")
    if _fails:
        print("✗ 失败项：")
        for p in _fails:
            print(f"  - {p}")
        return 1
    print("OK model-preload 双方法 · 策略单一真源 · 前端消费+保守兜底 · 端点真被调用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
