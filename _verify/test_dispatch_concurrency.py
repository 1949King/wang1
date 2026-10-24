# -*- coding: utf-8 -*-
"""自包含回归：验证 dispatch_canvas_tools 的只读并发 / 写串行 / 超时收敛。

不依赖真实画布、真实 task store；注入假 bridge + 假 store，测延迟收敛。
"""
import sys
import time
import uuid

sys.path.insert(0, ".")

import app.core.project_agent_host as host
from app.core.agent_runtime import dispatch_canvas_tools

# ── 注入假 agent_task_store / agent_session，避免 KeyError ──
class FakeTaskStore:
    def add_step(self, *a, **k):
        pass
    def bump_tool(self, *a, **k):
        pass
    def transition(self, *a, **k):
        pass

class FakeSessions:
    def begin_tool_call(self, session_id):
        return True, ""

import app.core.agent_runtime as ar
ar.agent_tasks = FakeTaskStore()   # 会在 import 处被引用？不——是函数内 import，需覆盖模块属性

# dispatch 内部 `from app.core.agent_task_store import agent_tasks`，所以直接 patch 该模块
import app.core.agent_task_store as ats
ats.agent_tasks = FakeTaskStore()
import app.core.agent_session as asess
asess.agent_sessions = FakeSessions()

# ── 注入假 push / wait ──
replies = {}

def fake_push(event_type, payload, **kw):
    eid = uuid.uuid4().hex[:8]
    action = payload.get("action", "")
    # 只读工具 0.05s，写工具 0.3s
    delay = 0.05 if ("inspect" in action or "get_media" in action or "get_timeline" in action) else 0.3
    replies[eid] = {"payload": {"ok": True}, "_delay": delay}
    return {"id": eid}

def fake_wait(correlation_id, timeout=10.0):
    r = replies.get(correlation_id)
    if r is None:
        return None
    time.sleep(r.get("_delay", 0))
    return r

host.push_to_canvas = fake_push
host.wait_for_canvas_reply = fake_wait

# ── 场景 1：3 只读 + 2 写，autonomous 模式 ──
tools = [
    {"action": "editor.inspect_media", "params": {"id": "a"}},
    {"action": "editor.get_media", "params": {"id": "b"}},
    {"action": "editor.get_timeline_context", "params": {}},
    {"action": "editor.split_clip", "params": {"t": 1}},
    {"action": "editor.trim_clip", "params": {"t": 2}},
]
t0 = time.time()
res = dispatch_canvas_tools(tools, mode="autonomous", session_id="s1", task_id="t1")
elapsed = time.time() - t0

print("=== 结果 ===")
for r in res:
    print(f"  {r.get('action', ''):32s} ok={r.get('ok')} err={r.get('error')!r}")
assert all(r.get("ok") for r in res), "有工具失败"

print(f"\n=== 耗时 {elapsed:.3f}s ===")
# 并发读 ≈0.05s + 写串行 0.3+0.3=0.6s → 期望 ~0.65s
# 串行旧逻辑 = 3*0.05 + 2*0.3 = 0.75s
assert elapsed < 0.75, f"并发未生效，耗时过高 {elapsed:.3f}"
assert elapsed >= 0.55, "耗时异常偏低"
print("OK 只读并发 + 写串行：耗时符合预期")

# ── 场景 2：Plan 模式拒绝写 ──
res2 = dispatch_canvas_tools(tools, mode="plan", session_id="s2")
assert all(not r.get("ok") and "Plan" in r.get("error", "") for r in res2)
print("OK Plan 模式正确拒绝写工具")

# ── 场景 3：空列表 ──
assert dispatch_canvas_tools([], mode="autonomous", session_id="s3") == []
print("OK 空工具列表返回空")

# ── 场景 4：超时收敛（回执缺失 → 8s 内返回 None，而非 120s）──
replies.clear()
def fake_push_timeout(event_type, payload, **kw):
    return {"id": uuid.uuid4().hex[:8]}  # 永不回执
host.push_to_canvas = fake_push_timeout
host.wait_for_canvas_reply = lambda cid, timeout=10.0: None  # 立即返回 None（模拟超时）
t0 = time.time()
res4 = dispatch_canvas_tools(
    [{"action": "editor.inspect_media", "params": {}}],
    mode="autonomous", session_id="s4",
)
elapsed4 = time.time() - t0
assert len(res4) == 1 and res4[0].get("ok") is False and "超时" in res4[0].get("error", "")
print(f"OK 超时回执正确处理（耗时 {elapsed4:.3f}s）")

print("\n全部断言通过")
