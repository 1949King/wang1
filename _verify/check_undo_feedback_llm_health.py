# -*- coding: utf-8 -*-
"""回归：B1 撤销反馈回路 + A4 LLM 降级指标化（V4.37.2）。

自包含执行（不依赖 pytest）：沙箱下 pytest 启动链会触发硬件探测被拦截。

覆盖：
  A. agent_origin 基础设施（作用域进出/嵌套/线程隔离）
  B. B1 撤销反馈回路：_record_action 盖章 / _undo·_redo 钩子（静态）+
     _infer_agent_action_capabilities / _on_agent_action_undone / _agent_brain_learn
     related 覆写（AST 提取 + stub 动态）
  C. A4 llm_fallback_stats：记录/汇总/窗口裁剪/测试重置 + 情绪向量埋点（静态）
  D. 四处接线：dispatcher 注册 + invoke 真跑 + catalog 行 + action 行 + 帮助行
"""
from __future__ import annotations

import ast
import io
import os
import sys
import threading
import textwrap
import time
import types
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

EDITOR_SRC = Path(ROOT, "app", "modules", "lego", "editor_module.py")
DISPATCHER_SRC = Path(ROOT, "app", "core", "capability_dispatcher.py")
ENGINE_SRC = Path(ROOT, "app", "modules", "lego", "drama_understanding_engine.py")

_failures = []


def check(cond, msg):
    print(f"  {'OK ' if cond else 'FAIL'}   {msg}")
    if not cond:
        _failures.append(msg)


def get_method_src(class_name: str, method: str, path: Path):
    """AST 提取类方法的源码段（不 import 重模块的动态测试手法）。"""
    src = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method:
                    return ast.get_source_segment(src, item), src
    return None, src


print("[A] agent_origin 基础设施")
from app.core.agent_origin import agent_origin_scope, is_agent_origin  # noqa: E402

check(not is_agent_origin(), "默认非 Agent 来源")
with agent_origin_scope():
    check(is_agent_origin(), "scope 内标记为 Agent 来源")
    with agent_origin_scope():
        inner = is_agent_origin()
    check(inner and is_agent_origin(), "嵌套 scope 内外层状态保持")
check(not is_agent_origin(), "退出 scope 后恢复非 Agent")

_thread_flag = {}


def _worker():
    with agent_origin_scope():
        _thread_flag["in_scope"] = is_agent_origin()
    _thread_flag["after"] = is_agent_origin()


t = threading.Thread(target=_worker)
t.start()
t.join()
check(_thread_flag.get("in_scope") is True and _thread_flag.get("after") is False,
      "线程局部：工作线程 scope 不影响主线程")

print("[B] B1 撤销反馈回路")
rec_src, _ = get_method_src("EditorModule", "_record_action", EDITOR_SRC)
check(rec_src is not None and "is_agent_origin" in rec_src
      and 'setdefault("origin"' in rec_src,
      "_record_action 盖 origin 章（agent/user）")
undo_src, editor_all = get_method_src("EditorModule", "_undo", EDITOR_SRC)
check(undo_src is not None and "_on_agent_action_undone" in undo_src
      and 'origin") == "agent"' in undo_src,
      "_undo 撤销 agent 动作时触发负反馈钩子")
redo_src, _ = get_method_src("EditorModule", "_redo", EDITOR_SRC)
check(redo_src is not None and "_on_agent_action_redone" in redo_src,
      "_redo 重做 agent 动作时收回负反馈")
disp_src = DISPATCHER_SRC.read_text(encoding="utf-8-sig")
check("agent_origin_scope" in disp_src and "entry.handler(request)" in disp_src,
      "dispatcher.invoke 用 agent_origin_scope 包住 handler")
check("相关 capability" in editor_all and "related: Optional[List[str]] = None" in editor_all,
      "_agent_brain_learn 支持 related 覆写")

# 动态：_infer_agent_action_capabilities（纯逻辑，AST 提取后独立执行）
infer_src, _ = get_method_src("EditorModule", "_infer_agent_action_capabilities", EDITOR_SRC)
ns = {"List": list, "Optional": None}
exec(compile(textwrap.dedent(infer_src), "<infer>", "exec"), ns)


class _InferHost:
    _infer_agent_action_capabilities = ns["_infer_agent_action_capabilities"]


infer = _InferHost()._infer_agent_action_capabilities

check(infer({"type": "compound", "label": "trim_clip_linked_av",
                   "steps": []}) == ["editor.trim_clip"],
      "推断：trim 标签 → editor.trim_clip")
check(infer({"type": "delete", "clip_id": "x"}) == ["editor.ripple_delete_range"],
      "推断：delete → editor.ripple_delete_range")
check(infer({"type": "split", "clip_id": "x"}) == ["editor.split_clip"],
      "推断：split → editor.split_clip")
check(infer({"type": "edit_clip",
                   "before": {"start_time": 0, "duration": 5},
                   "after": {"start_time": 3, "duration": 5}}) == ["editor.move_clip"],
      "推断：edit_clip 仅 start_time 变 → move_clip")
check(infer({"type": "edit_clip",
                   "before": {"start_time": 0, "duration": 5, "in_point": 0},
                   "after": {"start_time": 0, "duration": 8, "in_point": 0}}) == ["editor.trim_clip"],
      "推断：edit_clip 仅 duration 变 → trim_clip")
check(infer({"type": "edit_clip",
                   "before": {"volume": 0.5}, "after": {"volume": 0.9}})
      == ["editor.set_clip_properties"],
      "推断：edit_clip 其他字段变 → set_clip_properties")
check(infer({"type": "compound", "steps": [
    {"type": "delete", "clip_id": "a"},
    {"type": "edit_clip", "before": {"start_time": 0}, "after": {"start_time": 1}},
]}) == ["editor.ripple_delete_range", "editor.move_clip"],
      "推断：compound 无标签 → 递归步骤并去重")

# 动态：_agent_brain_learn related 覆写（注入 fake agent_brain 捕获 feedback）
learn_src, _ = get_method_src("EditorModule", "_agent_brain_learn", EDITOR_SRC)
captured = []


class _FakeBrain:
    def learn_from_feedback(self, feedback):
        captured.append(feedback)


_fake_mod = types.ModuleType("app.core.agent_brain")
_fake_mod.agent_brain = _FakeBrain()
sys.modules["app.core.agent_brain"] = _fake_mod
ns2 = {"Optional": None, "List": list, "logger": types.SimpleNamespace(
    debug=lambda *a, **k: None, warning=lambda *a, **k: None)}


class _Stub:
    def _extract_related_capabilities(self, text):
        return ["fallback.cap"]


exec(compile(textwrap.dedent(learn_src), "<learn>", "exec"), ns2)
ns2["_agent_brain_learn"](_Stub(), success=False, user_text="撤销 Agent 的操作",
                          related=["editor.trim_clip"])
fb = captured[-1] if captured else {}
check(fb.get("related_capabilities") == ["editor.trim_clip"]
      and fb.get("type") == "quality" and fb.get("severity") == "medium",
      "_agent_brain_learn：related 覆写直通 feedback（quality/medium）")
ns2["_agent_brain_learn"](_Stub(), success=True, user_text="随便什么文本")
fb2 = captured[-1] if captured else {}
check(fb2.get("related_capabilities") == ["fallback.cap"] and fb2.get("type") == "success",
      "_agent_brain_learn：不给 related 时走文本推断兜底")
# 清理 fake 注入，避免污染后续 [D] 段的 capability_handlers 启动自检 / invoke 激活
sys.modules.pop("app.core.agent_brain", None)

# 动态：_on_agent_action_undone → 触发 _agent_brain_learn(success=False)
undone_src, _ = get_method_src("EditorModule", "_on_agent_action_undone", EDITOR_SRC)
ns3 = {"logger": types.SimpleNamespace(debug=lambda *a, **k: None)}
exec(compile(textwrap.dedent(undone_src), "<undone>", "exec"), ns3)


class _Stub2:
    _infer_agent_action_capabilities = staticmethod(
        lambda action: ["editor.trim_clip"])
    calls = []

    def _agent_brain_learn(self, **kw):
        self.calls.append(kw)


stub2 = _Stub2()
ns3["_on_agent_action_undone"](stub2, {"type": "compound", "label": "trim_clip_linked_av"})
check(stub2.calls and stub2.calls[0].get("success") is False
      and stub2.calls[0].get("related") == ["editor.trim_clip"],
      "_on_agent_action_undone：负反馈 success=False + related 直通")

print("[C] A4 llm_fallback_stats")
from app.core.ai import llm_fallback_stats as lfs  # noqa: E402

lfs._reset_for_tests()
check(lfs.summary() == {}, "空统计 summary 为空字典")
lfs.record("emotion_vector", degraded=False)
lfs.record("emotion_vector", degraded=True, reason="ollama_not_probed")
lfs.record("emotion_vector", degraded=True, reason="llm_error:Timeout")
s = lfs.summary()
ev = s.get("emotion_vector", {})
check(ev.get("attempts_24h") == 3 and ev.get("degraded_24h") == 2
      and ev.get("degradation_rate") == 66.7,
      f"混合事件统计正确（got {ev}）")
check(ev.get("last_reason") == "llm_error:Timeout", "最近原因取最后一条")
# 窗口裁剪：手工塞入超窗事件
with lfs._LOCK:
    lfs._SITES["emotion_vector"]["events"].append(
        (time.time() - 90000, True, "old_event"))
s2 = lfs.summary()
check(s2["emotion_vector"]["attempts_24h"] == 3, "超 24h 窗口的事件被排除")
lfs._reset_for_tests()
check(lfs.summary() == {}, "_reset_for_tests 清空")

engine_src = ENGINE_SRC.read_text(encoding="utf-8-sig")
check(engine_src.count('_record_fb("emotion_vector"') == 3
      and 'degraded=True, reason="ollama_not_probed"' in engine_src,
      "情绪向量降级三处埋点（成功/LLM 异常/未探测）")

print("[D] 四处接线（pipeline.llm_health）")
from app.core.capability_dispatcher import (  # noqa: E402
    CapabilityRequest, capability_dispatcher)
from app.core.capability_handlers import register_builtin_handlers  # noqa: E402

register_builtin_handlers(capability_dispatcher, editor_module_ref=lambda: None)
ids = {c["capability_id"] for c in capability_dispatcher.list_capabilities()}
check("pipeline.llm_health" in ids, "dispatcher 注册 pipeline.llm_health")

req = CapabilityRequest(capability_id="pipeline.llm_health",
                        params={}, caller="check")
res = capability_dispatcher.invoke(req)
check(res.success and isinstance(res.output, dict)
      and "sites" in res.output and "worst_site" in res.output,
      f"invoke 真跑 llm_health（success={res.success}）")

from app.core.agent_capability_catalog import CAPABILITY_ROWS  # noqa: E402
check(any(r[0] == "pipeline.llm_health" and r[2] == "read"
          for r in CAPABILITY_ROWS), "catalog 行存在（read/left）")

from app.core import agent_action_registry as aar  # noqa: E402
check(aar.ACTION_TO_CAPABILITY.get("llm_health") == "pipeline.llm_health",
      "action 行映射 llm_health → pipeline.llm_health")
check("llm_health 参数" in aar.build_agent_help_block()
      if hasattr(aar, "build_agent_help_block") else True,
      "帮助块含 llm_health 行（若有 build_agent_help_block）")

print("=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} 项未通过")
    sys.exit(1)
print("OK 撤销反馈回路 + LLM 降级指标 全部通过")
