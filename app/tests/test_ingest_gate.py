# -*- coding: utf-8 -*-
"""入轨治理闸门回归测试（刀3 / E2 · 2026-10-23）。

本刀的核心风险**不是**「闸门不生效」，而是「闸门误拦用户素材」：
`_add_clip_to_timeline` 有 13 个调用方，其中包含用户手动导入本地视频。
若照搬 `evaluate_gate` 的 `missing_scores ⇒ block`，用户导入的每个视频都会被拦。

因此本文件把「语境区分」锁成可执行断言：
    * 无分数 ⇒ **pass**（不判定），且理由如实说明「不判定」
    * 有分数且 D 级 ⇒ **block**（坏素材进不来）
    * 有分数且 C 级 ⇒ **review**（进，但标人工确认）
    * force ⇒ 降为 review 且**留痕**（不静默放行）
    * 批量：任一 block ⇒ 整批 block（硬闸门）
"""
import pytest

from app.core.ingest_gate import (
    GATE_VERSION,
    decide,
    decide_batch,
    has_scores,
    rejection_payload,
)


def _scored(score, grade="", **extra):
    item = {"clip_id": "c", "weighted_score": score, "grade": grade,
            "dimensions": {"visual_quality": score, "narrative_highlight": score,
                           "copy_match": score, "bgm_match": score,
                           "shot_duration": score}}
    item.update(extra)
    return item


# ── has_scores ────────────────────────────────────────────────────────

def test_has_scores_detects_weighted_score():
    assert has_scores({"weighted_score": 80}) is True
    assert has_scores({"weighted_score": 0}) is True, "0 分也是一次真实评分"


def test_has_scores_detects_dimensions_only():
    assert has_scores({"dimensions": {"visual_quality": 70}}) is True


def test_has_scores_rejects_strings_and_bools():
    assert has_scores({"weighted_score": "85"}) is False, "字符串分数不可判定"
    assert has_scores({"weighted_score": True}) is False, "bool 不是分数"
    assert has_scores({"dimensions": {"visual_quality": "70"}}) is False


def test_has_scores_false_for_plain_item():
    assert has_scores({"clip_id": "c", "path": "/m/a.mp4"}) is False
    assert has_scores(None) is False
    assert has_scores("junk") is False


# ── 核心：无分数不判定（防误拦用户素材）──────────────────────────────

def test_unscored_material_passes():
    out = decide({"clip_id": "user-import", "path": "/movies/my_video.mp4"})
    assert out["decision"] == "pass", "用户自己的素材（无评分）绝不能被拦"
    assert out["scored"] is False
    assert "不判定" in out["reason"], "必须如实说明「没有判定」，不能假装判过"


def test_unscored_empty_dimensions_passes():
    out = decide({"clip_id": "c", "dimensions": {}})
    assert out["decision"] == "pass" and out["scored"] is False


def test_unscored_force_still_reports_unscored():
    out = decide({"clip_id": "c"}, force=True)
    assert out["decision"] == "pass"
    assert out["scored"] is False, "force 不该把「没测」变成「测过」"


# ── 有分数：D 级拦、C 级复核、A/B 放行 ───────────────────────────────

def test_d_grade_is_blocked():
    out = decide(_scored(45, "D"))
    assert out["decision"] == "block"
    assert out["scored"] is True
    assert "拒绝" in out["reason"]
    assert out["reasons"], "拦截必须带原因，不静默"


def test_c_grade_is_review():
    out = decide(_scored(65, "C"))
    assert out["decision"] == "review"
    assert "人工确认" in out["reason"]


def test_a_grade_passes():
    out = decide(_scored(88, "A"))
    assert out["decision"] == "pass"


def test_low_score_without_grade_still_blocks():
    """只给 weighted_score、不给 grade 时也必须能判（按分数算等级）。"""
    out = decide({"clip_id": "c", "weighted_score": 30})
    assert out["decision"] == "block"


# ── force：放行但留痕 ─────────────────────────────────────────────────

def test_force_downgrades_block_to_review_and_marks():
    out = decide(_scored(45, "D"), force=True)
    assert out["decision"] == "review", "force 是「降为人工确认」，不是直接 pass"
    assert out["forced"] is True
    assert "forced_by_caller" in out["reasons"], "放行必须留痕"
    assert "force" in out["reason"].lower()


def test_force_does_not_affect_passing_items():
    out = decide(_scored(88, "A"), force=True)
    assert out["decision"] == "pass" and out["forced"] is False


# ── 批量：硬闸门 ──────────────────────────────────────────────────────

def test_batch_any_block_blocks_whole_batch():
    out = decide_batch([_scored(88, "A"), _scored(45, "D")])
    assert out["verdict"] == "block"
    assert len(out["blocked"]) == 1
    assert out["blocked"][0]["decision"] == "block"


def test_batch_all_unscored_passes():
    out = decide_batch([{"id": "a", "path": "/m/1.mp4"}, {"id": "b", "path": "/m/2.mp4"}])
    assert out["verdict"] == "pass"
    assert out["unscored_count"] == 2, "未评分数必须如实报数"
    assert len(out["allowed"]) == 2


def test_batch_review_does_not_block():
    out = decide_batch([_scored(88, "A"), _scored(65, "C")])
    assert out["verdict"] == "review"
    assert len(out["review"]) == 1
    assert out["blocked"] == []


def test_batch_mixed_unscored_and_pass():
    out = decide_batch([_scored(88, "A"), {"id": "u", "path": "/m/x.mp4"}])
    assert out["verdict"] == "pass"
    assert out["unscored_count"] == 1
    assert len(out["allowed"]) == 2


def test_batch_ignores_non_dict_entries():
    out = decide_batch([_scored(88, "A"), "junk", None, 42])
    assert out["total"] == 1


def test_batch_empty_is_pass():
    out = decide_batch([])
    assert out["verdict"] == "pass" and out["total"] == 0
    assert decide_batch(None)["total"] == 0


def test_batch_clip_id_from_id_field():
    out = decide_batch([{"id": "x1", "weighted_score": 45, "grade": "D"}])
    assert out["blocked"][0]["clip_id"] == "x1"


# ── 拒绝载荷 ──────────────────────────────────────────────────────────

def test_rejection_payload_shape():
    verdict = decide_batch([_scored(88, "A"), _scored(45, "D"), {"id": "u"}])
    payload = rejection_payload(verdict)
    assert payload["ok"] is False
    assert payload["code"] == "gate_blocked", "与刀1 的 conflict 并列，便于上层区分"
    assert payload["blocked_count"] == 1
    assert payload["unscored_count"] == 1
    assert "拒绝入轨" in payload["message"]
    assert payload["stage"] == "ingest"


def test_rejection_payload_mentions_review_when_present():
    verdict = decide_batch([_scored(45, "D"), _scored(65, "C")])
    payload = rejection_payload(verdict)
    assert payload["review_count"] == 1
    assert "人工确认" in payload["message"]


def test_rejection_payload_preview_capped():
    items = [_scored(45, "D") for _ in range(20)]
    for i, it in enumerate(items):
        it["clip_id"] = f"c{i}"
    payload = rejection_payload(decide_batch(items))
    assert payload["blocked_count"] == 20
    assert len(payload["blocked"]) <= 5, "预览必须截断（避免响应体爆炸）"


# ── 版本与来源 ────────────────────────────────────────────────────────

def test_gate_version_present():
    assert decide({"id": "a"})["gate"] == GATE_VERSION


def test_source_recorded():
    out = decide({"clip_id": "c", "source": "canvas"})
    assert out["source"] == "canvas"
