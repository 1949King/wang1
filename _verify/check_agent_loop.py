# -*- coding: utf-8 -*-
"""回归：AgentLoop 多轮循环机制（Track B / C / D 数据层）。

自包含执行（不依赖 pytest、不依赖真实 LLM）：注入假 model_fn 与假 tool_executor，
验证「观察→规划→行动→观察」循环、预算、确认、诚实失败、Plan 只读、schema 派生。

覆盖：
  A. parse_tool_calls 兼容多种写法（commands / tools / 裸数组 / 原生 tool_calls / 纯文本）
  B. 多轮循环：第 1 轮出工具、第 2 轮出最终答复 → done
  C. 观察回流：模型能在第 2 轮看到第 1 轮的执行结果
  D. 预算耗尽 → budget（不假成功）
  E. 协作模式写工具待确认 → approval + pending_commands
  F. Plan 模式非只读工具被跳过
  G. 诚实失败：工具报错如实记入 step，不包装成成功
  H. 纯文本直接答复 → done（不无谓循环）
  I. build_tool_schemas 由能力目录派生且结构合法
  J. agent_console.collect_agent_status 聚合不崩（含 brain/session/tasks）

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_agent_loop.py
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.agent_loop import (  # noqa: E402
    AgentLoop, LoopStep, parse_tool_calls, build_tool_schemas,
)

_failures: list[str] = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


# ── 隔离真实大脑学习（避免把测试突触写进真实记忆库）──
def _silence_brain():
    try:
        import app.core.agent_brain as ab
        ab.agent_brain.reinforce_path = lambda *a, **k: None
    except Exception:
        pass


print("[A] parse_tool_calls 兼容性")
reply, calls = parse_tool_calls("好的，我来切分。{\"commands\":[{\"action\":\"split_clip\",\"params\":{\"clip_index\":0}}]}")
check(calls and calls[0]["action"] == "split_clip", "commands 写法解析")
check("好的，我来切分。" in reply, "中文回复保留")

reply, calls = parse_tool_calls("[{\"action\":\"addNode\",\"params\":{\"kind\":\"shot\"}}]")
check(calls and calls[0]["action"] == "addNode", "裸数组解析")

reply, calls = parse_tool_calls("{\"tools\":[{\"action\":\"trim_clip\",\"params\":{}}]}")
check(calls and calls[0]["action"] == "trim_clip", "tools 写法解析")

reply, calls = parse_tool_calls("{\"tool_calls\":[{\"function\":{\"name\":\"editor.split_clip\",\"arguments\":\"{\\\"clip_index\\\":1}\"}}]}")
check(calls and calls[0]["action"] == "editor.split_clip", "原生 tool_calls 解析")
check(calls[0]["params"].get("clip_index") == 1, "原生 arguments 反序列化")

reply, calls = parse_tool_calls("这个不需要操作，直接告诉你答案。")
check(calls == [] and "答案" in reply, "纯文本 = 最终答复，不误伤")

print("[B] 多轮循环 → done")
_silence_brain()
loop = AgentLoop()

def _model_2round(messages):
    # 第 2 轮（已收到观察）给最终答复，第 1 轮给工具调用
    saw_obs = any(m.get("role") == "user" and "工具" in str(m.get("content")) for m in messages)
    if saw_obs:
        return "已完成切分。"
    return '{"commands":[{"action":"split_clip","params":{"clip_index":0}}]}'

r = loop.run(goal="切分片段", mode="collaborative", session_id="t_b",
             model_fn=_model_2round,
             tool_executor=lambda a, p: {"ok": True, "capability_id": "editor.split_clip"})
check(r.success and r.reason == "done", f"成功结束 reason={r.reason}")
check(r.rounds == 2 and r.tool_calls == 1, f"轮次 {r.rounds} / 工具 {r.tool_calls}")
check(r.final_reply == "已完成切分。", "最终答复正确")
check(r.steps and r.steps[0].action == "split_clip", "步骤记录 action")

print("[C] 观察回流（模型能读到上一轮结果）")
seen_obs = {"v": False}
def _model_sees_obs(messages):
    blob = " ".join(str(m.get("content")) for m in messages)
    if "执行成功" in blob:
        seen_obs["v"] = True
        return "收到，完成。"
    return '{"commands":[{"action":"editor.split_clip","params":{}}]}'
loop.run(goal="切分", mode="autonomous", session_id="t_c", model_fn=_model_sees_obs,
         tool_executor=lambda a, p: {"ok": True, "capability_id": "editor.split_clip"})
check(seen_obs["v"], "第 2 轮模型能读到第 1 轮观察")

print("[D] 预算耗尽 → budget（不假成功）")
def _model_always_tool(messages):
    return '{"commands":[{"action":"editor.split_clip","params":{}}]}'
r = loop.run(goal="切分", mode="autonomous", session_id="t_d", model_fn=_model_always_tool,
             tool_executor=lambda a, p: {"ok": True, "capability_id": "editor.split_clip"},
             max_rounds=2, max_tools=2)
check(r.reason == "budget" and not r.success, f"预算耗尽 reason={r.reason} success={r.success}")

print("[E] 协作模式写工具待确认 → approval")
r = loop.run(goal="删一段", mode="collaborative", session_id="t_e",
             model_fn=lambda m: '{"commands":[{"action":"ripple_delete_range","params":{"t_in":1,"t_out":2}}]}',
             tool_executor=lambda a, p: {"ok": False, "require_approval": True, "error": "waiting_approval"})
check(r.reason == "approval", f"待确认 reason={r.reason}")
check(len(r.pending_commands) == 1, "pending_commands 收集待确认指令")
check(not r.success, "待确认时不标成功")

print("[F] Plan 模式非只读被跳过")
executed = {"v": 0}
r = loop.run(goal="切分", mode="plan", session_id="t_f",
             model_fn=lambda m: '{"commands":[{"action":"split_clip","params":{}}]}',
             tool_executor=lambda a, p: executed.__setitem__("v", executed["v"] + 1) or {"ok": True})
check(executed["v"] == 0, "Plan 模式写工具未执行")
check(r.steps and r.steps[0].skipped, "写工具被标记 skipped")

print("[G] 诚实失败：报错如实记录")
r = loop.run(goal="加滤镜", mode="autonomous", session_id="t_g",
             model_fn=lambda m: '{"commands":[{"action":"apply_filter","params":{}}]}',
             tool_executor=lambda a, p: {"ok": False, "error": "滤镜引擎不可用"})
check(r.steps and not r.steps[0].ok and "滤镜引擎不可用" in r.steps[0].error, "失败原因如实记录")

print("[H] 纯文本直接答复 → done（不无谓循环）")
r = loop.run(goal="问个问题", mode="collaborative", session_id="t_h",
             model_fn=lambda m: "竖屏短剧建议 9:16，每集 1 分钟内。")
check(r.reason == "done" and r.rounds == 1 and r.tool_calls == 0, f"直答 reason={r.reason} 轮次={r.rounds}")

print("[I] build_tool_schemas 派生")
schemas = build_tool_schemas(limit=5)
check(len(schemas) == 5, f"schema 数量 {len(schemas)}")
check(all(s["type"] == "function" and s["function"]["name"] and s["function"]["description"]
          for s in schemas), "schema 结构合法（type/name/description）")

print("[J] agent_console 聚合不崩")
from app.core.agent_console import collect_agent_status
snap = collect_agent_status(session_id="t_b")
check("session" in snap and "brain" in snap and "tasks" in snap and "active_loops" in snap,
      "快照含 session/brain/tasks/active_loops")

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项")
    sys.exit(1)
print("OK AgentLoop 多轮循环机制全部断言通过")
