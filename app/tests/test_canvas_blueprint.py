# -*- coding: utf-8 -*-
"""工作流蓝图单测（2026-10-31 · 把 Agent 从「参考助手」升级成「编排器」）

对应用户实锤的三个症状：
  ① 一次只出 1~3 张卡  → 蓝图 + 标准链补全 ⇒ 一次铺出完整流程；
  ② 不生成提示词      → 提示词规范要求每张卡写 prompt；
  ③ 摆放杂乱          → 坐标由本地拓扑引擎算（前端 blueprintLayout.ts）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import canvas_blueprint as cb
from app.core.canvas_port_model import can_connect


# ── 节点目录 ──────────────────────────────────────────────────────────────
def test_catalog_covers_ports_and_palette():
    """节点目录 = ports.ts 的 kind ∪ NodePalette.tsx 的 kind（不写第二份表）。"""
    cat = cb.node_kind_catalog()
    kinds = {row["kind"] for row in cat}
    assert "script" in kinds and "shot" in kinds and "codeVideo" in kinds
    labels = {row["kind"]: row["label"] for row in cat}
    assert labels["script"] == "剧本"
    assert labels["shot"] == "镜头"
    assert labels["codeVideo"] == "代码成片"


def test_catalog_ports_present():
    """每个 kind 都带端口类型（供 LLM 判断边能不能接）。"""
    for row in cb.node_kind_catalog():
        assert row["accepts"], row
        assert row["produces"], row


# ── 标准链自身必须类型合法（护栏：标准链自己不能接不上）──────────────────
def test_canonical_path_edges_are_type_compatible():
    """每条标准路径的相邻两环都必须过端口类型校验。

    ⚠️ 这条测试是踩坑换来的：`shotlist` 只接受 video/grid，**不吃 image**
    ⇒ 最初把「镜头 → 分镜表」写进标准链，整条链就是断的。
    """
    checked = 0
    for key, path in cb.CANONICAL_PATHS.items():
        for i in range(len(path) - 1):
            v = can_connect(path[i], path[i + 1])
            assert v.get("ok"), (
                f"标准路径「{key}」的边 {path[i]} → {path[i + 1]} 类型不兼容：{v.get('reason')}")
            checked += 1
    assert checked >= 10, checked


def test_ceiling_detection():
    """需求文本 → 流程终点。"""
    assert cb.detect_ceiling("从剧本到成片") == "codeVideo"
    assert cb.detect_ceiling("帮我做个分镜表") == "shotlist"
    assert cb.detect_ceiling("我要生图") == "image"
    assert cb.detect_ceiling("做个生视频的流程") == "video"
    # 风格描述不算 scope 信号（否则「完整流程」会被缩成「只到生图」）
    assert cb.detect_ceiling("完整流程，画面要二次元风格") is None


# ── 归一化：清洗与如实报告 ────────────────────────────────────────────────
def test_normalize_drops_unknown_kind_and_reports():
    spec, report = cb.normalize_blueprint({
        "nodes": [
            {"key": "a", "kind": "script", "title": "剧本"},
            {"key": "b", "kind": "not_a_kind"},
        ],
        "edges": [],
    })
    assert [n["key"] for n in spec["nodes"]] == ["a"]
    assert report["dropped_nodes"] == 1
    assert any("未知节点类型" in p for p in report["problems"])


def test_normalize_drops_dangling_and_type_mismatch_edges():
    spec, report = cb.normalize_blueprint({
        "nodes": [
            {"key": "a", "kind": "script"},
            {"key": "b", "kind": "shot"},
        ],
        "edges": [
            {"from": "a", "to": "ghost"},
            {"from": "a", "to": "b"},
        ],
    })
    # script→shot 是 text→text，合法；悬空边被剔除
    assert len(spec["edges"]) == 1
    assert report["dropped_edges"] == 1
    assert any("悬空" in p for p in report["problems"])


def test_normalize_drops_self_loop():
    spec, report = cb.normalize_blueprint({
        "nodes": [{"key": "a", "kind": "script"}],
        "edges": [{"from": "a", "to": "a"}],
    })
    assert spec["edges"] == []
    assert any("自环" in p for p in report["problems"])


def test_normalize_keeps_prompt_and_title():
    spec, _ = cb.normalize_blueprint({
        "nodes": [{"key": "a", "kind": "shot", "title": "镜头 1", "prompt": "中景推门"}],
        "edges": [],
    })
    assert spec["nodes"][0]["title"] == "镜头 1"
    assert spec["nodes"][0]["prompt"] == "中景推门"


# ── 标准链补全 ────────────────────────────────────────────────────────────
def test_completes_chain_when_workflow_requested():
    """用户要完整流程 ⇒ 补出缺失的必要环节（一次铺出完整工作流）。"""
    spec, report = cb.normalize_blueprint(
        {
            "mode": "workflow",
            "goal": "做一集漫剧",
            "nodes": [
                {"key": "a", "kind": "script", "title": "剧本", "prompt": "第一场"},
                {"key": "b", "kind": "codeVideo", "title": "成片"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
        user_message="帮我做一集漫剧，从剧本到成片",
    )
    kinds = [n["kind"] for n in spec["nodes"]]
    assert kinds[0] == "script"
    assert kinds[-1] == "codeVideo"
    # 「到成片」的标准路径整条补齐
    for need in ("directorCard", "shot", "image", "video", "shotlist"):
        assert need in kinds, kinds
    assert report["inserted"], report
    # 补出来的节点标 auto
    auto_nodes = [n for n in spec["nodes"] if (n.get("data") or {}).get("auto")]
    assert len(auto_nodes) == len(report["inserted"])


def test_completion_respects_scope_ceiling():
    """终点由需求决定：只到分镜表 ⇒ 不硬塞视频生成（走宫格路径）。"""
    spec, report = cb.normalize_blueprint(
        {
            "mode": "workflow",
            "goal": "做个分镜表",
            "nodes": [
                {"key": "a", "kind": "script", "title": "剧本"},
                {"key": "b", "kind": "shotlist", "title": "分镜表"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
        user_message="帮我搭一条完整流程，做到分镜表就行",
    )
    kinds = {n["kind"] for n in spec["nodes"]}
    assert report["ceiling"] == "shotlist", report
    assert "shotlist" in kinds and "shot" in kinds and "directorCard" in kinds
    assert "video" not in kinds, "到分镜表为止不该硬塞视频生成"
    assert "codeVideo" not in kinds


def test_completion_edges_are_valid_and_acyclic():
    """补全后的图必须仍是 DAG（画布执行器要求无环）。"""
    spec, _ = cb.normalize_blueprint(
        {
            "mode": "workflow",
            "goal": "做一集漫剧",
            "nodes": [
                {"key": "a", "kind": "script"},
                {"key": "b", "kind": "codeVideo"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
        user_message="做一集",
    )
    kind_by_key = {n["key"]: n["kind"] for n in spec["nodes"]}
    for e in spec["edges"]:
        v = can_connect(kind_by_key[e["from"]], kind_by_key[e["to"]])
        assert v.get("ok"), f"{e} 类型不兼容"
    # 拓扑无环（Kahn）
    indeg = dict.fromkeys(kind_by_key, 0)
    adj = {k: [] for k in kind_by_key}
    for e in spec["edges"]:
        adj[e["from"]].append(e["to"])
        indeg[e["to"]] += 1
    q = [k for k, d in indeg.items() if d == 0]
    seen = 0
    while q:
        n = q.pop()
        seen += 1
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    assert seen == len(kind_by_key), "补全后出现环"


def test_shortcut_edge_removed_when_spine_covered():
    """蓝图里的「捷径边」（script→shot）在骨架补齐后应被剔除（避免长线横穿画布）。"""
    spec, _ = cb.normalize_blueprint(
        {
            "mode": "workflow",
            "goal": "做一集",
            "nodes": [
                {"key": "a", "kind": "script"},
                {"key": "b", "kind": "shot"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
        user_message="做一集",
    )
    pairs = {(e["from"], e["to"]) for e in spec["edges"]}
    # script → shot 的直连被剔除，改走 script → directorCard → shot
    assert ("a", "b") not in pairs
    dc = [n["key"] for n in spec["nodes"] if n["kind"] == "directorCard"]
    assert dc
    assert ("a", dc[0]) in pairs
    assert (dc[0], "b") in pairs


def test_no_completion_for_single_step_request():
    """单步需求（一张图）**不补全** —— 不臆造端点。"""
    spec, report = cb.normalize_blueprint(
        {
            "nodes": [{"key": "a", "kind": "image", "prompt": "赛博朋克少女"}],
            "edges": [],
        },
        user_message="给我一张赛博朋克少女的图",
    )
    assert len(spec["nodes"]) == 1
    assert not report["inserted"]


def test_workflow_keyword_triggers_completion_without_mode():
    """即使 LLM 忘了标 mode，需求关键词命中也能补全。"""
    spec, report = cb.normalize_blueprint(
        {
            "nodes": [
                {"key": "a", "kind": "script"},
                {"key": "b", "kind": "shotlist"},
            ],
            "edges": [],
        },
        user_message="帮我搭一条完整流程，从剧本到成片",
    )
    assert report["inserted"], report
    kinds = {n["kind"] for n in spec["nodes"]}
    assert {"directorCard", "shot", "image", "video", "codeVideo"} <= kinds, kinds


# ── 工具归一化入口 ────────────────────────────────────────────────────────
def test_normalize_canvas_tools_passes_through_other_actions():
    tools, reports = cb.normalize_canvas_tools(
        [{"action": "addNode", "params": {"kind": "shot"}}],
        user_message="随便",
    )
    assert tools[0]["action"] == "addNode"
    assert reports == []


def test_normalize_canvas_tools_normalizes_blueprint():
    tools, reports = cb.normalize_canvas_tools(
        [{
            "action": "applyBlueprint",
            "params": {"blueprint": {
                "mode": "workflow",
                "goal": "做一集",
                "nodes": [{"key": "a", "kind": "script"}, {"key": "b", "kind": "codeVideo"}],
                "edges": [],
            }},
        }],
        user_message="做一集",
    )
    assert tools[0]["params"]["blueprint"]["nodes"]
    assert reports[0]["ok"] is True
    assert reports[0]["node_count"] >= 5


def test_normalize_canvas_tools_reports_missing_blueprint():
    tools, reports = cb.normalize_canvas_tools(
        [{"action": "applyBlueprint", "params": {}}],
        user_message="做一集",
    )
    assert reports[0]["ok"] is False
    assert "error" in tools[0]["params"]


# ── 提示词 ────────────────────────────────────────────────────────────────
def test_prompt_block_contains_blueprint_contract():
    block = cb.blueprint_prompt_block()
    assert "applyBlueprint" in block
    assert "禁止输出 x/y 坐标" in block
    assert "workflow" in block
    # 节点目录进提示词
    assert "script（剧本）" in block
    assert "shot（镜头）" in block


# ── 端到端：LLM 原文 → 解析 → 归一化 → 前端可消费的蓝图 ──────────────────
def test_end_to_end_llm_output_to_frontend_ready_blueprint():
    """模拟 LLM 原文（含 canvas_tools JSON）走完整条链路。

    判据：出来的 blueprint 能直接喂给前端 `applyBlueprint`（字段名对齐）
    —— 后端产出的 `nodes[].key/kind/title/prompt` + `edges[].from/to`，
    前端 `applyBlueprint.ts` 正是按这套字段读的。
    """
    from app.core.agent_runtime import parse_canvas_tools

    raw = (
        "好，我来给你搭一条从剧本到成片的完整漫剧流程。\n"
        '{"canvas_tools":[{"action":"applyBlueprint","params":{"blueprint":{'
        '"goal":"做一集 60 秒漫剧","mode":"workflow",'
        '"nodes":['
        '{"key":"n1","kind":"script","title":"剧本","prompt":"第一场：主角推门进入"},'
        '{"key":"n2","kind":"shot","title":"开场镜头","prompt":"中景，二次元少女推门"}'
        '],'
        '"edges":[{"from":"n1","to":"n2"}]}}}]}'
    )

    _clean, tools = parse_canvas_tools(raw)
    assert tools and tools[0]["action"] == "applyBlueprint"

    tools, reports = cb.normalize_canvas_tools(tools, user_message="帮我做一集漫剧流程")
    spec = tools[0]["params"]["blueprint"]

    # 前端可消费的字段（applyBlueprint.ts 的读法）
    assert spec["nodes"] and isinstance(spec["nodes"], list)
    for n in spec["nodes"]:
        assert isinstance(n["key"], str) and n["key"]
        assert isinstance(n["kind"], str) and n["kind"]
        assert "title" in n
        assert "prompt" in n
    for e in spec["edges"]:
        assert set(e) == {"from", "to"}
        assert e["from"] in {n["key"] for n in spec["nodes"]}
        assert e["to"] in {n["key"] for n in spec["nodes"]}

    # 蓝图被补成完整流程（不止 2 张卡）
    assert len(spec["nodes"]) >= 5, spec["nodes"]
    assert reports[0]["ok"] is True
    assert reports[0]["inserted"], reports[0]


def test_blueprint_has_no_coordinate_fields():
    """蓝图里绝不能出现坐标（LLM 不出像素，坐标由本地布局引擎算）。"""
    spec, _ = cb.normalize_blueprint({
        "nodes": [{"key": "a", "kind": "script", "x": 10, "y": 20}],
        "edges": [],
    })
    for n in spec["nodes"]:
        assert "x" not in n and "y" not in n
