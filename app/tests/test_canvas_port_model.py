"""app/tests/test_canvas_port_model.py — 画布端口模型（后端镜像）回归（2026-09-28）。

核心纪律：后端**直接解析前端真源 ports.ts**（不做第二份表）⇒ 漂移不可能。
本测试锁定：解析健康度 · 与前端一致的判据 · 宽松兜底 · 整图校验。
"""

import pytest

from app.core import canvas_port_model as pm


def test_parses_frontend_source():
    st = pm.stats()
    assert st["parsed_ok"] is True, f"ports.ts 解析失败: {st}"
    assert st["kinds"] == 21, f"kind 数不对: {st}"
    assert st["compat_rules"] >= 1


def test_parses_all_node_kinds():
    ports = pm.node_ports()
    for k in ("script", "shot", "image", "video", "audio", "music",
              "digitalHuman", "director", "directorCard", "storyboard",
              "shotlist", "animation", "panorama", "generator", "source", "group"):
        assert k in ports, f"缺 kind: {k}"
        assert "accepts" in ports[k] and "produces" in ports[k]


# ─────────────────────── 判据（与 ports.test.ts 同源） ───────────────────────

@pytest.mark.parametrize("src,dst,want,desc", [
    ("script", "shot", True, "剧本文本 → 镜头"),
    ("image", "video", True, "图生视频"),
    ("music", "video", True, "音乐配乐（靠 PORT_COMPAT）"),
    ("image", "image", True, "图生图"),
    ("video", "text", False, "视频不能当文本输入"),
    ("audio", "image", False, "音频不能当图像输入"),
    ("director", "audio", False, "3D 场景不产音频"),
])
def test_can_connect_matrix(src, dst, want, desc):
    assert pm.can_connect(src, dst)["ok"] is want, desc


def test_music_satisfies_audio_slot_via_compat():
    """music ⊂ audio：必须能接进视频的配乐位。"""
    v = pm.can_connect("music", "video")
    assert v["ok"] is True
    assert v["via"] == "audio"          # 命中兼容表，落到 audio 槽位


def test_illegal_connection_has_readable_reason():
    v = pm.can_connect("audio", "image")
    assert v["ok"] is False
    assert "audio" in v["reason"] and "image" in v["reason"]


# ─────────────────────── 宽松兜底 ───────────────────────

def test_unknown_kind_is_permissive_both_ends():
    """未知 kind 不误拦（新增节点类型时不会因忘填表而连不上）。"""
    assert pm.can_connect("__brand_new__", "image")["ok"] is True
    assert pm.can_connect("image", "__brand_new__")["ok"] is True


def test_ports_of_unknown_falls_back():
    p = pm.ports_of("__nope__")
    assert p["accepts"].get("any") == pm.UNBOUNDED


# ─────────────────────── 边语义 ───────────────────────

def test_group_edges_are_associate():
    assert pm.edge_kind_for("group", "image") == "associate"
    assert pm.edge_kind_for("image", "group") == "associate"


def test_normal_edges_are_data():
    assert pm.edge_kind_for("script", "shot") == "data"


def test_associate_always_connects():
    assert pm.can_connect("group", "image")["ok"] is True
    assert pm.can_connect("audio", "group")["ok"] is True


# ─────────────────────── 整图校验 ───────────────────────

def _n(i, k):
    return {"id": i, "type": k, "data": {"kind": k}}


def _e(s, t):
    return {"source": s, "target": t}


def test_clean_graph_has_no_problems():
    problems = pm.validate_graph([_n("s", "script"), _n("k", "shot")], [_e("s", "k")])
    assert problems == []


def test_type_mismatch_reported():
    problems = pm.validate_graph([_n("a", "audio"), _n("i", "image")], [_e("a", "i")])
    assert any(p["code"] == "type-mismatch" and p["level"] == "error" for p in problems)


def test_fan_in_exceeded_reported():
    """shot 的 image 输入上限 1 → 接两条应超限。"""
    nodes = [_n("i1", "image"), _n("i2", "image"), _n("k", "shot")]
    problems = pm.validate_graph(nodes, [_e("i1", "k"), _e("i2", "k")])
    assert any(p["code"] == "fan-in-exceeded" for p in problems)


def test_fan_in_within_limit_ok():
    problems = pm.validate_graph([_n("s", "script"), _n("k", "shot")], [_e("s", "k")])
    assert not any(p["code"] == "fan-in-exceeded" for p in problems)


def test_dangling_edge_is_warn_not_error():
    problems = pm.validate_graph([_n("a", "image")], [_e("a", "ghost")])
    assert any(p["code"] == "dangling" and p["level"] == "warn" for p in problems)


def test_data_cycle_reported():
    nodes = [_n("x", "image"), _n("y", "image")]
    problems = pm.validate_graph(nodes, [_e("x", "y"), _e("y", "x")])
    assert any(p["code"] == "cycle" for p in problems)


def test_associate_cycle_not_reported():
    nodes = [_n("g", "group"), _n("h", "group")]
    problems = pm.validate_graph(nodes, [_e("g", "h"), _e("h", "g")])
    assert not any(p["code"] == "cycle" for p in problems)


def test_validate_graph_tolerates_empty_and_garbage():
    assert pm.validate_graph([], []) == []
    assert pm.validate_graph(None, None) == []
    assert pm.validate_graph([{"no_id": 1}], [{"bogus": True}]) == []


def test_describe_illegal_edges_only_returns_connectivity_errors():
    """便捷入口只返回「非法连接」，过滤掉 dangling（那不是连接错误）。"""
    graph = {"nodes": [_n("a", "audio"), _n("i", "image")],
             "edges": [_e("a", "i"), _e("a", "ghost")]}
    illegals = pm.describe_illegal_edges(graph)
    assert len(illegals) == 1
    assert illegals[0]["code"] == "type-mismatch"
