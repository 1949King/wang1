# -*- coding: utf-8 -*-
"""回归：画布节点级 capability（canvas_tools 后端化）。

自包含执行（不依赖 pytest）。

覆盖：
  A. 由 _CANVAS_ACTION_ROWS 派生的节点级 capability 全部注册进 dispatcher
  B. 目录 ↔ 注册 双向一致（verify_catalog_consistency 无问题）
  C. effect 正确（queryNodes/queryTimeline/selectNode = read；其余 = canvas_write）
  D. action→capability 映射（含别名；media_write 生成类排除在外）
  E. policy：协作模式 canvas.add_node → require_approval；canvas.query_nodes → 自动放行
  F. handler 诚实失败（未知 capability_id 早退）
  G. 生成类（runGenerate/batchGenerate）仍走 SSE 桥、不进 capability 映射

安全：不真正 push task.create（node_action 对未知 id 早退，不发 SSE）；不碰网络/媒体。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.agent_action_registry import (  # noqa: E402
    canvas_node_capabilities, canvas_action_to_capability,
    canvas_capability_to_action, canvas_generation_actions, ACTION_TO_CAPABILITY,
)
from app.core.capability_dispatcher import CapabilityRequest, capability_dispatcher  # noqa: E402
from app.core.capability_handlers import (  # noqa: E402
    CanvasCapabilityHandlers, register_builtin_handlers,
)
from app.core.agent_capability_catalog import verify_catalog_consistency  # noqa: E402
from app.core.agent_policy import (  # noqa: E402
    DECISION_ALLOW, DECISION_DENY, DECISION_REQUIRE_APPROVAL,
    MODE_COLLABORATIVE, MODE_PLAN, decide,
)

READ_ACTIONS = {"queryNodes", "queryTimeline", "selectNode"}

_failures = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


caps = canvas_node_capabilities()
cap_ids = {c["capability_id"] for c in caps}

print("[A] 派生与注册")
# canonical 节点操作：queryNodes/queryTimeline/selectNode(3 read)
# + addNode/updateNode/connectNodes/deleteNode/setNodeImage/setNodeVideo/importImage
# + duplicateNode/groupNodes/bindShotlistFrame/undo/redo/breakdown/applyStoryboard/fillStoryboardCell(15 write)
check(len(caps) == 18, f"派生 18 个 canonical 节点 capability（实际 {len(caps)}）")
check(len(cap_ids) == 18, "capability_id 无重复")

register_builtin_handlers(capability_dispatcher)
registered = {e["capability_id"] for e in capability_dispatcher.list_capabilities()}
for cid in sorted(cap_ids):
    check(cid in registered, f"{cid} 已注册进 dispatcher")

print("[B] 目录一致性")
problems = verify_catalog_consistency(registered)
check(not problems, f"verify_catalog_consistency 无问题（{len(problems)} 项）")
if problems:
    for p in problems[:12]:
        print("     -", p)

print("[C] effect")
for c in caps:
    if c["action"] in READ_ACTIONS:
        check(c["effect"] == "read", f"{c['action']} = read")
    else:
        check(c["effect"] == "canvas_write", f"{c['action']} = canvas_write")

print("[D] action→capability 映射（含别名）")
m = canvas_action_to_capability()
check(m.get("addNode") == "canvas.add_node", "addNode → canvas.add_node")
check(m.get("queryNodes") == "canvas.query_nodes", "queryNodes → canvas.query_nodes")
check(m.get("canvas_query") == "canvas.query_nodes", "别名 canvas_query → canvas.query_nodes")
check(m.get("storyboardBreakdown") == "canvas.breakdown", "别名 storyboardBreakdown → canvas.breakdown")
check("runGenerate" not in m, "runGenerate（media_write）不进节点映射")
check("batchGenerate" not in m, "batchGenerate（media_write）不进节点映射")
check(ACTION_TO_CAPABILITY.get("addNode") == "canvas.add_node", "ACTION_TO_CAPABILITY 派生含节点映射")
rev = canvas_capability_to_action()
check(rev.get("canvas.add_node") == "addNode", "反向映射 canvas.add_node → addNode")

print("[E] policy")
d = decide(tool_id="canvas.add_node", mode=MODE_COLLABORATIVE)
check(d.action == DECISION_REQUIRE_APPROVAL, f"协作模式 add_node 需确认（{d.action}）")
d2 = decide(tool_id="canvas.query_nodes", mode=MODE_COLLABORATIVE)
check(d2.action == DECISION_ALLOW, f"协作模式 query_nodes 自动放行（{d2.action}）")
d3 = decide(tool_id="canvas.add_node", mode=MODE_PLAN)
check(d3.action == DECISION_DENY, f"Plan 模式 add_node 拒绝（{d3.action}）")

print("[F] handler 诚实失败（未知 id 早退，不发 SSE）")
h = CanvasCapabilityHandlers()
r = h.node_action(CapabilityRequest(capability_id="canvas.not_a_node", params={}))
check(not r.success, "node_action 未知 capability_id → error")

print("[G] 生成类仍走 SSE 桥")
gen = canvas_generation_actions()
check("runGenerate" in gen and "batchGenerate" in gen, "runGenerate/batchGenerate 在生成类集合")
check("addNode" not in gen and "queryNodes" not in gen, "节点级 action 不在生成类集合")

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项：")
    for f in _failures:
        print("   -", f)
    sys.exit(1)
print("OK 画布节点级 capability 全部断言通过 CHECK_EXIT=0")
