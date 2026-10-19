# -*- coding: utf-8 -*-
"""审美治理闸门测试（2026-10-20）。"""
from app.core.aesthetic_gate import (
    evaluate_batch,
    evaluate_gate,
    grade_of,
    policy_errors,
    weighted_score,
)
from app.core.capability_dispatcher import CapabilityRequest
from app.core.capability_handlers_gate import GateCapabilityHandlers


def _item(clip_id="c1", score=80.0, grade="A", **dims):
    base = {
        "visual_quality": 80.0,
        "narrative_highlight": 80.0,
        "copy_match": 80.0,
        "bgm_match": 80.0,
        "shot_duration": 80.0,
    }
    base.update(dims)
    return {
        "clip_id": clip_id,
        "dimensions": base,
        "weighted_score": score,
        "grade": grade,
    }


def test_pass_for_grade_a():
    result = evaluate_gate(_item())
    assert result["decision"] == "pass"
    assert result["reasons"] == ["passed"]


def test_c_grade_goes_to_review():
    result = evaluate_gate(_item(score=65.0, grade="C"))
    assert result["decision"] == "review"
    assert any(r.startswith("grade_review") for r in result["reasons"])


def test_d_grade_blocked():
    result = evaluate_gate(_item(score=50.0, grade="D"))
    assert result["decision"] == "block"


def test_dimension_floor_blocks():
    result = evaluate_gate(_item(visual_quality=5.0))
    assert result["decision"] == "block"
    assert any(r.startswith("dimension_floor:visual_quality") for r in result["reasons"])


def test_estimated_requires_review():
    item = _item()
    item["estimated_dims"] = ["bgm_match"]
    result = evaluate_gate(item)
    assert result["decision"] == "review"
    assert any(r.startswith("estimated_review") for r in result["reasons"])


def test_missing_scores_blocked():
    result = evaluate_gate({})
    assert result["decision"] == "block"
    assert result["reasons"] == ["missing_scores"]


def test_invalid_policy_blocked():
    result = evaluate_gate(_item(), {"min_weighted_score": 200})
    assert result["decision"] == "block"
    assert any(r.startswith("policy_invalid") for r in result["reasons"])


def test_weighted_score_from_dimensions():
    assert weighted_score({"visual_quality": 100, "narrative_highlight": 100}) == 100.0
    assert weighted_score({}) is None


def test_grade_thresholds():
    assert grade_of(95) == "S"
    assert grade_of(85) == "A"
    assert grade_of(75) == "B"
    assert grade_of(65) == "C"
    assert grade_of(10) == "D"


def test_batch_counts():
    report = evaluate_batch([
        _item("a", 85, "A"),
        _item("b", 65, "C"),
        _item("c", 40, "D"),
    ])
    assert report["counts"] == {"pass": 1, "review": 1, "block": 1}


def test_policy_errors():
    assert policy_errors({}) == []
    assert policy_errors({"block_grades": ["C"], "review_grades": ["C"]})


def test_handler_single_and_batch():
    handlers = GateCapabilityHandlers()
    single = handlers.aesthetic_gate(CapabilityRequest(
        capability_id="pipeline.aesthetic_gate", params={"item": _item()}
    ))
    assert single.success and single.output["decision"] == "pass"
    batch = handlers.aesthetic_gate(CapabilityRequest(
        capability_id="pipeline.aesthetic_gate",
        params={"items": [_item("a"), _item("b", 50, "D")]},
    ))
    assert batch.success and batch.output["counts"]["block"] == 1
    missing = handlers.aesthetic_gate(CapabilityRequest(
        capability_id="pipeline.aesthetic_gate", params={}
    ))
    assert missing.success is False and "item" in missing.error
