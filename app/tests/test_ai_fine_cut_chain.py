# -*- coding: utf-8 -*-
"""AI 精剪链路离线回归（§40.x）—— 无网络 / 无 GPU / 无真实视频 / 不碰 Qt。

覆盖：意图规格 → 帧级语义表 → 决策编译 → 同形提案 → 注册 → 复核，
以及云端 backend 的出域拒绝与空正文加固。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

import pytest

try:
    from app.core.editing.intent import EditIntent
    from app.core.editing.semantic_table import (
        SemanticTable, build_semantic_table, compile_interval, merge_intervals,
    )
    from app.core.editing.verify import verify_proposal as _vp, submit_human_verdict
    from app.core.ai.vision_backends import (
        OpenAIVisionBackend, default_backend, parse_json_object, sample_frames,
    )
    from app.core.ai.editing_proposal_llm import (
        TextDecisionBackend, build_fine_cut_proposal, run_fine_cut,
    )
    from app.core.rough_cut_chain import RoughCutChain
    from app.core import canvas_shot_vision
except ImportError:  # 打包/副库路径兜底
    from core.editing.intent import EditIntent  # type: ignore
    from core.editing.semantic_table import (  # type: ignore
        SemanticTable, build_semantic_table, compile_interval, merge_intervals,
    )
    from core.editing.verify import verify_proposal as _vp, submit_human_verdict  # type: ignore
    from core.ai.vision_backends import (  # type: ignore
        OpenAIVisionBackend, default_backend, parse_json_object, sample_frames,
    )
    from core.ai.editing_proposal_llm import (  # type: ignore
        TextDecisionBackend, build_fine_cut_proposal, run_fine_cut,
    )
    from core.rough_cut_chain import RoughCutChain  # type: ignore
    from core import canvas_shot_vision  # type: ignore


class FakeDecision(TextDecisionBackend):
    """可注入的决策后端，用于离线验证编译逻辑。"""

    name = "fake-llm"

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> Tuple[Optional[str], str]:
        self.prompts.append(prompt)
        if self.payload is None:
            return None, "模拟后端不可用"
        if isinstance(self.payload, str):
            return self.payload, ""
        return json.dumps(self.payload, ensure_ascii=False), ""


def _clips() -> list[Dict[str, Any]]:
    return [
        {"id": "c1", "track": 0, "start_time": 0.0, "duration": 10.0},
        {"id": "c2", "track": 0, "start_time": 10.0, "duration": 10.0},
    ]


def _table() -> SemanticTable:
    return build_semantic_table(
        [
            {"shot_id": "s001", "start": 0.0, "end": 4.0, "shot": "全景",
             "description": "开场空镜", "vision": True},
            {"shot_id": "s002", "start": 4.0, "end": 10.0, "shot": "中景",
             "description": "人物对话", "vision": True},
            {"shot_id": "s003", "start": 10.0, "end": 20.0, "shot": "特写",
             "description": "情绪特写", "vision": False},
        ],
        fps=30.0,
        asr_segments=[{"start": 5.0, "end": 7.0, "text": "这句必须留"}],
        quality_by_shot={"s001": 62.0, "s002": 71.0, "s003": 92.0},
        source="local_vision",
        vision_model="fake-local",
    )


# ── 意图规格 ────────────────────────────────────────────────────

def test_intent_validation_and_fingerprint():
    good = EditIntent(target_duration_sec=12.0, pacing="fast", notes="压节奏")
    assert good.validate() == []
    assert len(good.fingerprint()) == 16
    assert EditIntent.from_dict(good.to_dict()).fingerprint() == good.fingerprint()
    assert EditIntent(notes="换意图").fingerprint() != good.fingerprint()

    bad = EditIntent(pacing="turbo", target_duration_sec=-1,
                     preserve_ranges=((5.0, 3.0),))
    problems = bad.validate()
    assert any("pacing" in p for p in problems)
    assert any("不能为负" in p for p in problems)
    assert any("倒序" in p for p in problems)

    overlap = EditIntent(preserve_ranges=((1.0, 4.0), (3.0, 6.0)))
    assert any("重叠" in p for p in overlap.validate())


def test_intent_protected_intersection():
    intent = EditIntent(preserve_ranges=((5.0, 8.0),))
    assert intent.is_protected(7.0, 9.0)
    assert intent.is_protected(4.0, 5.5)
    assert not intent.is_protected(8.0, 9.0)
    assert not intent.is_protected(3.0, 5.0)


# ── 帧级语义表 ──────────────────────────────────────────────────

def test_semantic_table_frame_mapping():
    t = _table()
    assert len(t.shots) == 3
    first = t.shots[0]
    assert (first.frame_in, first.frame_out) == (0, 120)
    assert first.frame_out - first.frame_in >= 1
    assert first.timeline_in == pytest.approx(0.0)
    assert first.quality_score == 62.0
    assert t.shots[2].highlight is True          # 92 >= 80（沿用 A 级线）
    assert t.shots[1].asr_text == "这句必须留"
    assert "frame_in" in first.evidence()


def test_semantic_table_no_fake_quality_and_invalid_shot():
    t = build_semantic_table(
        [{"shot_id": "ok", "start": 1.0, "end": 2.0},
         {"shot_id": "bad", "start": 2.0, "end": 2.0}],
        fps=25.0,
    )
    assert len(t.shots) == 1
    assert t.shots[0].quality_score is None      # 没测就不填 70 基线
    assert any("无效" in w for w in t.warnings)


def test_compile_interval_constraints():
    t = _table()
    intent = EditIntent(keep_lines=("这句必须留",))
    shot = t.shot_by_id("s001")
    assert shot is not None

    iv, why = compile_interval(shot, {"portion": "all", "reason": "开场过长"}, intent)
    assert iv is not None and why is None
    assert iv["timeline_in"] == pytest.approx(0.0)
    assert "frame_in" in iv["evidence"]
    assert iv["reason"] == "开场过长"

    _, why = compile_interval(shot, {"portion": "wat"}, intent)
    assert why and "portion" in why

    s2 = t.shot_by_id("s002")
    assert s2 is not None
    _, why = compile_interval(s2, {"portion": "all"}, intent)
    assert why and "必须保留台词" in why

    protected = EditIntent(preserve_ranges=((0.0, 2.0),))
    _, why = compile_interval(shot, {"portion": "all"}, protected)
    assert why and "禁改区间" in why

    head, _ = compile_interval(shot, {"portion": "head", "sec": 999.0}, EditIntent())
    assert head is not None and head["timeline_out"] <= shot.timeline_out

    tail, _ = compile_interval(shot, {"portion": "tail", "sec": 1.5}, EditIntent())
    assert tail is not None
    assert tail["timeline_in"] == pytest.approx(shot.timeline_out - 1.5)


def test_merge_intervals_overlap():
    merged = merge_intervals([
        {"timeline_in": 1.0, "timeline_out": 4.0, "track": 0, "reason": "a"},
        {"timeline_in": 3.0, "timeline_out": 6.0, "track": 0, "reason": "b"},
        {"timeline_in": 1.0, "timeline_out": 2.0, "track": 1, "reason": "c"},
    ])
    assert len(merged) == 2
    t0 = [m for m in merged if m["track"] == 0]
    assert len(t0) == 1 and t0[0]["timeline_out"] == 6.0
    assert t0[0]["reason"] == "a"


# ── backend 加固 ────────────────────────────────────────────────

def test_parse_json_object_variants():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('好的，结果如下：{"a": {"b": 2}} 以上') == {"a": {"b": 2}}
    assert parse_json_object("没有 JSON") is None
    assert parse_json_object("[1,2,3]") is None
    assert parse_json_object("") is None


def test_sample_frames_budget():
    frames = [b"a", b"b", b"c", b"d", b"e"]
    assert sample_frames(frames, max_frames=2) == [b"a", b"e"]
    assert len(sample_frames(frames, max_frames=3)) == 3
    assert sample_frames([], max_frames=2) == []


def test_cloud_backend_denies_upload_by_default():
    b = OpenAIVisionBackend(api_key="fake-key", allow_upload=False)
    res = b.ask_detailed("m", [b"frame"], "prompt")
    assert not res.ok
    assert "出域" in res.error
    assert res.source == "unavailable"


def test_cloud_backend_detects_thinking_budget_exhaustion(monkeypatch):
    b = OpenAIVisionBackend(api_key="fake-key", allow_upload=True)
    monkeypatch.setattr(
        b, "_post",
        lambda payload: {
            "choices": [{"message": {"content": "", "reasoning_content": "思考中..."}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 4096},
        },
    )
    res = b.ask_detailed("m", [b"frame"], "prompt")
    assert not res.ok
    assert "思考耗尽" in res.error
    assert res.usage["completion_tokens"] == 4096


def test_cloud_backend_parses_json_and_records_usage(monkeypatch):
    b = OpenAIVisionBackend(api_key="fake-key", allow_upload=True)
    monkeypatch.setattr(
        b, "_post",
        lambda payload: {
            "choices": [{"message": {"content": '```json\n{"shot_size":"特写"}\n```'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        },
    )
    res = b.ask_detailed("m", [b"f1", b"f2"], "prompt")
    assert res.ok and res.data == {"shot_size": "特写"}
    assert res.usage == {"prompt_tokens": 10, "completion_tokens": 20}


def test_default_backend_is_local():
    assert default_backend().source == "local"


def test_vision_backend_injection_is_reversible():
    original = canvas_shot_vision.get_vision_backend()
    try:
        sentinel = object()
        canvas_shot_vision.set_vision_backend(sentinel)
        assert canvas_shot_vision.get_vision_backend() is sentinel
    finally:
        canvas_shot_vision.set_vision_backend(original)


# ── 提案编译 / 注册 / 复核 ───────────────────────────────────────

def test_build_fine_cut_proposal_shape():
    t = _table()
    backend = FakeDecision({
        "ops": [
            {"op": "ripple_delete", "shot_id": "s001", "portion": "all",
             "reason": "开场空镜过长", "evidence": {"basis": "description"}},
            {"op": "ripple_delete", "shot_id": "不存在", "portion": "all", "reason": "幻觉"},
        ],
        "summary": "压开场",
    })
    out = build_fine_cut_proposal(_clips(), t, EditIntent(), backend, recall="")
    assert out.ok and out.proposal is not None
    p = out.proposal
    for key in ("plan_id", "created_at", "label", "mode", "request_id",
                "needs_confirmation", "status", "applied", "clip_ids", "layout",
                "intervals", "original_duration", "predicted_duration",
                "deleted_duration", "warnings"):
        assert key in p, f"提案缺字段 {key}"
    assert p["needs_confirmation"] is True
    assert p["applied"] is False
    assert len(p["intervals"]) == 1                 # 幻觉 shot_id 被丢弃
    assert any("不存在" in w for w in p["warnings"])
    assert p["predicted_duration"] == pytest.approx(16.0)
    assert "intent" in p and "evidence_index" in p
    assert "目标函数" in backend.prompts[0]


def test_build_fine_cut_proposal_rejects_bad_intent_and_backend():
    t = _table()
    out = build_fine_cut_proposal(
        _clips(), t, EditIntent(pacing="turbo"), FakeDecision({"ops": []}), recall="",
    )
    assert not out.ok and "意图规格非法" in out.error

    out2 = build_fine_cut_proposal(_clips(), t, EditIntent(), FakeDecision(None), recall="")
    assert not out2.ok and out2.degraded and "决策后端不可用" in out2.error
    assert out2.proposal is None                     # 绝不生成假决策


def test_register_proposal_guards_and_discipline():
    chain = RoughCutChain()
    p = build_fine_cut_proposal(
        _clips(), _table(), EditIntent(), FakeDecision({"ops": []}), recall="",
    ).proposal
    assert p is not None
    p["needs_confirmation"] = False                 # 试图绕过确认纪律
    p["applied"] = True
    reg = chain.register_proposal(p, broadcast=False)
    assert reg["ok"]
    stored = chain.get_plan(reg["plan_id"])
    assert stored is not None
    assert stored["needs_confirmation"] is True
    assert stored["applied"] is False
    assert stored["status"] == "pending_confirmation"
    assert chain.register_proposal({"clip_ids": []}, broadcast=False)["ok"] is False
    assert chain.register_proposal(
        {**p, "intervals": [{"timeline_in": 3.0, "timeline_out": 1.0}]},
        broadcast=False,
    )["ok"] is False


def test_verify_report_is_falsifiable():
    t = _table()
    intent = EditIntent(target_duration_sec=16.0, duration_tolerance_sec=1.0)
    p = build_fine_cut_proposal(
        _clips(), t, intent,
        FakeDecision({"ops": [{"shot_id": "s001", "portion": "all", "reason": "压开场"}]}),
        recall="",
    ).proposal
    assert p is not None
    ok = _vp(p, t, intent)
    assert ok.passed, ok.difference_reason()
    assert any("未实测" in w for w in ok.warnings)

    broken = dict(p)
    broken["intervals"] = [{"timeline_in": 1.0, "timeline_out": 2.0, "shot_id": "s001"}]
    bad = _vp(broken, t, intent)
    assert not bad.passed
    assert "证据可寻址" in bad.difference_reason() or "决策可解释" in bad.difference_reason()

    measured = _vp(p, t, intent, applied_duration_sec=18.0)
    assert not measured.passed
    assert any("时长目标" in c.name and not c.passed for c in measured.checks)


def test_human_verdict_label_guard():
    t = _table()
    p = build_fine_cut_proposal(
        _clips(), t, EditIntent(), FakeDecision({"ops": []}), recall="",
    ).proposal
    assert p is not None
    report = _vp(p, t, EditIntent())
    assert submit_human_verdict(report, p, label="瞎写")["ok"] is False
    # accept 会触发记忆 IO；这里只校验非法分支，避免测试污染真实记忆库


def test_run_fine_cut_falls_back_to_rule_chain():
    class FakeChain:
        def __init__(self) -> None:
            self.plan_called = 0

        def register_proposal(self, proposal, *, broadcast=True):
            return {"ok": True, "plan_id": "reg-1"}

        def plan(self, clips, **kwargs):
            self.plan_called += 1
            return {"ok": True, "proposal": {
                "plan_id": "rule-1", "intervals": [], "warnings": [],
                "label": "规则粗剪（AI 精剪降级）",
            }}

    chain = FakeChain()
    out = run_fine_cut(
        _clips(), _table(), EditIntent(),
        decision_backend=FakeDecision(None), chain=chain, recall="",
    )
    assert out.ok and out.degraded
    assert out.source == "rule-fallback"
    assert chain.plan_called == 1
    assert any("降级" in w for w in out.warnings)


def test_run_fine_cut_happy_path_registers():
    class FakeChain:
        def register_proposal(self, proposal, *, broadcast=True):
            return {"ok": True, "plan_id": proposal["plan_id"]}

        def plan(self, clips, **kwargs):
            raise AssertionError("成功路径不应降级到规则链")

    out = run_fine_cut(
        _clips(), _table(), EditIntent(),
        decision_backend=FakeDecision({"ops": []}), chain=FakeChain(), recall="",
    )
    assert out.ok and not out.degraded and out.proposal is not None
