"""app/tests/test_canvas_workflow_runner.py — 画布图执行回归（2026-09-28）。

覆盖四条核心纪律：
① **默认 dry_run**（只出计划，不生成）—— 守北极星「确认后执行」；
② **诚实失败**（节点跑不了如实报告，绝不伪造产物）；
③ **上游失败冻结下游**（依赖已断不硬跑）；
④ **增量缓存**（同参数命中、改一处只重跑下游）。
"""

import pytest

from app.core import canvas_node_cache as cache
from app.core import canvas_workflow_runner as r


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv(cache._STORE_ENV, str(tmp_path / "cache.json"))
    yield


def N(nid, kind, **data):
    return {"id": nid, "type": kind, "data": {"kind": kind, **data}}


def E(src, dst):
    return {"source": src, "target": dst}


# ─────────────────────── 图结构 ───────────────────────

def test_adjacency_and_topo_order():
    up, down = r.build_adjacency(["a", "b", "c"], [E("a", "b"), E("b", "c")])
    assert up["c"] == ["b"] and up["a"] == []
    assert down["a"] == ["b"]
    assert r.topo_order(up) == ["a", "b", "c"]


def test_topo_order_is_deterministic():
    """同层按 id 排序 → 顺序稳定，便于测试与缓存复现。"""
    up, _ = r.build_adjacency(["z", "a", "m"], [])
    assert r.topo_order(up) == ["a", "m", "z"]


def test_dangling_edges_ignored():
    up, _ = r.build_adjacency(["a"], [E("a", "ghost"), E("ghost", "a")])
    assert up == {"a": []}


def test_self_loop_ignored():
    up, _ = r.build_adjacency(["a"], [E("a", "a")])
    assert up == {"a": []}


def test_cycle_detected():
    up, _ = r.build_adjacency(["a", "b"], [E("a", "b"), E("b", "a")])
    ok, cyclic = r.is_dag(up)
    assert ok is False
    assert set(cyclic) == {"a", "b"}


# ─────────────────────── dry_run 默认 ───────────────────────

def test_default_is_dry_run_and_does_not_execute(monkeypatch):
    """默认 dry_run：只出计划，**绝不调用执行器**。"""
    called = []
    monkeypatch.setattr(r, "execute_node",
                        lambda *a, **k: called.append(1) or {"ok": True, "output": {}})
    res = r.run_graph({"nodes": [N("a", "image", prompt="x")], "edges": []})
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert called == []
    assert res["counters"]["planned"] == 1
    assert res["counters"]["done"] == 0


def test_empty_graph_rejected():
    assert r.run_graph({"nodes": [], "edges": []})["ok"] is False


def test_node_limit_enforced():
    nodes = [N(f"n{i}", "image") for i in range(5)]
    res = r.run_graph({"nodes": nodes, "edges": []}, max_nodes=3)
    assert res["ok"] is False and "上限" in res["message"]


# ─────────────────────── 诚实失败 / 依赖冻结 ───────────────────────

def test_non_runnable_kinds_reported_with_reason(monkeypatch):
    """不可执行节点须给出**具体原因**，不是含糊跳过。"""
    monkeypatch.setattr(r, "execute_node", lambda *a, **k: {"ok": True, "output": {}})
    res = r.run_graph({"nodes": [N("g", "group"), N("n", "note")], "edges": []},
                      dry_run=False)
    reasons = {s["node_id"]: s["reason"] for s in res["skipped"]}
    assert "编组容器" in reasons["g"]
    assert "笔记" in reasons["n"]


def test_failure_does_not_fabricate_output(monkeypatch):
    monkeypatch.setattr(r, "execute_node",
                        lambda *a, **k: {"ok": False, "error": "渠道不可用"})
    res = r.run_graph({"nodes": [N("a", "image", prompt="x")], "edges": []},
                      dry_run=False)
    item = res["executed"][0]
    assert item["status"] == "failed"
    assert "output" not in item          # 绝不写占位产物
    assert "渠道不可用" in item["error"]
    assert res["counters"]["failed"] == 1


def test_downstream_skipped_when_upstream_fails(monkeypatch):
    def fake(node, inputs, **kw):
        kind = r.node_kind(node)
        if kind == "image":
            return {"ok": False, "error": "断了"}
        return {"ok": True, "output": {"video_url": "v.mp4"}}
    monkeypatch.setattr(r, "execute_node", fake)
    res = r.run_graph({
        "nodes": [N("i", "image", prompt="x"), N("v", "video", prompt="y")],
        "edges": [E("i", "v")]}, dry_run=False)
    statuses = {e["node_id"]: e["status"] for e in res["executed"]}
    assert statuses["i"] == "failed"
    assert "v" not in statuses                       # v 未执行
    assert any("上游失败" in s["reason"] for s in res["skipped"])


def test_cycle_rejected_before_execution(monkeypatch):
    monkeypatch.setattr(r, "execute_node",
                        lambda *a, **k: pytest.fail("有环不应执行任何节点"))
    res = r.run_graph({"nodes": [N("a", "image"), N("b", "image")],
                       "edges": [E("a", "b"), E("b", "a")]}, dry_run=False)
    assert res["ok"] is False and "环" in res["message"]


# ─────────────────────── 上游注入 ───────────────────────

def test_collect_inputs_injects_text():
    nodes = {"s": N("s", "script", content="第一场"),
             "k": N("k", "shot", prompt="中景")}
    node_map = {"s": nodes["s"], "k": nodes["k"]}
    up, _ = r.build_adjacency(["s", "k"], [E("s", "k")])
    got = r.collect_inputs("k", up, node_map, {})
    assert got["prompt"] == "第一场"


def test_collect_inputs_injects_image_from_output():
    """图/视频上游的**产物**要能注入下游（当前前端只拼文本，这是补齐）。"""
    node_map = {"i": N("i", "image"), "v": N("v", "video")}
    up, _ = r.build_adjacency(["i", "v"], [E("i", "v")])
    got = r.collect_inputs("v", up, node_map, {"i": {"image_url": "http://x/a.png"}})
    assert got["reference_image"] == "http://x/a.png"


# ─────────────────────── 增量缓存 ───────────────────────

def test_second_run_hits_cache(monkeypatch):
    calls = []

    def fake(node, inputs, **kw):
        calls.append(r.node_kind(node))
        return {"ok": True, "output": {"image_url": "a.png"}}
    monkeypatch.setattr(r, "execute_node", fake)
    g = {"nodes": [N("a", "image", prompt="猫")], "edges": []}

    r1 = r.run_graph(g, dry_run=False)
    assert calls == ["image"] and r1["counters"]["done"] == 1

    calls.clear()
    r2 = r.run_graph(g, dry_run=False)
    assert calls == []                     # 缓存命中，不再调用
    assert r2["counters"]["cached"] == 1


def test_changing_param_invalidates_that_node(monkeypatch):
    calls = []

    def fake(node, inputs, **kw):
        calls.append(r.node_kind(node))
        return {"ok": True, "output": {"image_url": "a.png"}}
    monkeypatch.setattr(r, "execute_node", fake)

    r.run_graph({"nodes": [N("a", "image", prompt="猫")], "edges": []}, dry_run=False)
    calls.clear()
    r.run_graph({"nodes": [N("a", "image", prompt="狗")], "edges": []}, dry_run=False)
    assert calls == ["image"]              # 参数变 → 重跑


def test_upstream_change_invalidates_downstream(monkeypatch):
    """改上游 → 下游指纹变 → 下游重跑（增量执行的关键语义）。"""
    calls = []

    def fake(node, inputs, **kw):
        calls.append(r.node_kind(node))
        return {"ok": True, "output": {"image_url": "a.png", "video_url": "v.mp4"}}
    monkeypatch.setattr(r, "execute_node", fake)

    def graph(script_text):
        return {"nodes": [N("s", "script", content=script_text),
                          N("k", "shot", prompt="中景"),
                          N("i", "image", prompt="")],
                "edges": [E("s", "k"), E("k", "i")]}

    r.run_graph(graph("第一场"), dry_run=False)
    calls.clear()
    r.run_graph(graph("第二场"), dry_run=False)   # 只改 s
    assert "image" in calls                       # i 因上游链变化重跑


def test_cache_can_be_disabled(monkeypatch):
    calls = []

    def fake(node, inputs, **kw):
        calls.append(1)
        return {"ok": True, "output": {"image_url": "a.png"}}
    monkeypatch.setattr(r, "execute_node", fake)
    g = {"nodes": [N("a", "image", prompt="猫")], "edges": []}
    r.run_graph(g, dry_run=False, use_cache=False)
    r.run_graph(g, dry_run=False, use_cache=False)
    assert len(calls) == 2                 # 关缓存 → 每次都跑


# ─────────────────────── 进度回调 ───────────────────────

def test_progress_callback_emitted(monkeypatch):
    monkeypatch.setattr(r, "execute_node",
                        lambda *a, **k: {"ok": True, "output": {"image_url": "a.png"}})
    events = []
    r.run_graph({"nodes": [N("a", "image", prompt="x")], "edges": []},
                dry_run=False, progress=lambda stage, payload: events.append((stage, payload)))
    assert any(stage == "node" for stage, _ in events)


def test_progress_callback_exception_does_not_break_run(monkeypatch):
    monkeypatch.setattr(r, "execute_node",
                        lambda *a, **k: {"ok": True, "output": {"image_url": "a.png"}})

    def bad_progress(stage, payload):
        raise RuntimeError("回调炸了")
    res = r.run_graph({"nodes": [N("a", "image", prompt="x")], "edges": []},
                      dry_run=False, progress=bad_progress)
    assert res["ok"] is True               # 回调异常不得中断执行


# ─────────────────────── 图签名 ───────────────────────

def test_graph_signature_deterministic():
    g = {"nodes": [N("a", "image")], "edges": []}
    assert r.graph_signature(g) == r.graph_signature(g)


def test_graph_signature_changes_with_edges():
    n = [N("a", "image"), N("b", "video")]
    s1 = r.graph_signature({"nodes": n, "edges": []})
    s2 = r.graph_signature({"nodes": n, "edges": [E("a", "b")]})
    assert s1 != s2


def test_handler_for_known_kinds():
    assert r.handler_for("shot") == "image"
    assert r.handler_for("image") == "image"
    assert r.handler_for("video") == "video"
    assert r.handler_for("group") is None


# ─────────────────────── 文本节点（2026-09-28 补齐） ───────────────────────

def test_text_node_is_runnable():
    """此前 text 不在 handler 表里，导致「前端能生成文本、整图执行却跳过」的不一致。"""
    assert r.handler_for("text") == "text"


class _FakeAIEngine:
    """桩：模拟 chat_with_fallback 的返回（generator 语义）。"""

    def __init__(self, chunks):
        self._chunks = chunks

    def chat_with_fallback(self, *_a, **_k):
        return iter(self._chunks)


def _patch_ai(monkeypatch, chunks):
    import app.core.ai_engine as ae
    monkeypatch.setattr(ae, "AIEngine", lambda *a, **k: _FakeAIEngine(chunks))


def test_text_node_success(monkeypatch):
    _patch_ai(monkeypatch, ["这是", "生成的", "文本"])
    res = r.execute_node({"id": "t", "data": {"kind": "text", "content": "写点什么"}}, {})
    assert res["ok"] is True
    assert res["output"]["text"] == "这是生成的文本"


def test_text_node_error_string_is_not_treated_as_success(monkeypatch):
    """★ 三级降级全失败时 chat_with_fallback 会 yield 一个「错误: …」**字符串**，
    必须识别出来如实报失败 —— 不能把它当成成功产出的文本。"""
    _patch_ai(monkeypatch, ["错误: 没有可用的 AI 提供者"])
    res = r.execute_node({"id": "t", "data": {"kind": "text", "content": "写点什么"}}, {})
    assert res["ok"] is False
    assert "错误" in res["error"]


def test_text_node_empty_output_reports_failure(monkeypatch):
    _patch_ai(monkeypatch, [])
    res = r.execute_node({"id": "t", "data": {"kind": "text", "content": "写点什么"}}, {})
    assert res["ok"] is False
    assert res["error"]


def test_text_node_empty_prompt_reports_failure(monkeypatch):
    _patch_ai(monkeypatch, ["不该被调用"])
    res = r.execute_node({"id": "t", "data": {"kind": "text"}}, {})
    assert res["ok"] is False
    assert "提示词为空" in res["error"]
