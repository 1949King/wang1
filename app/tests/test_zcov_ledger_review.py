# -*- coding: utf-8 -*-
"""app/tests/test_zcov_ledger_review.py — AI 辅助抽检子系统专项补测（2026-10-09）。

覆盖 app/core/ai/sampling_review.py（此前 0 专项测试）：
  · _stable_hash 确定性哈希（抽样可复现的地基）
  · _resolve_store_path 环境变量覆盖
  · 自适应分层抽样 should_sample（可复现 / 强制必检 / 24h 去重 / 概率公式）
  · 规则预审 prescreen（缺失 / 体积 / 时长 / Schema / 机器分 → 风险分级）
  · AI 打分入池 submit_ai_score（**红线：永不写先验**）
  · pending_reviews 高风险优先排序
  · 人工真值 submit_human_label（残差 EMA / 漂移 / 注入式 prior_writer 唯一通道）
  · 冻结 / 解冻闭环
  · drift_status / metrics 字段
  · JSON 账本持久化往返 + 损坏容错

纪律对齐 app/tests/test_zcov_core_a.py：每个断言锁**可观察行为**，不写 assert True 凑数。
一律显式构造 SamplingReview(store_path=...)，**不使用 get_review() 单例**。
"""
from __future__ import annotations

import hashlib
import json
import time

import pytest

from app.core.ai import sampling_review as sr
from app.core.ai.sampling_review import (
    SamplingReview,
    _stable_hash,
    _resolve_store_path,
    _P_BASE,
    _P_MIN,
    _ALPHA,
    _DEDUP_WINDOW,
    _DRIFT_WARN,
    _DRIFT_FREEZE,
    _MIN_SAMPLES_FOR_DRIFT,
    _STORE_ENV,
)


def _review(tmp_path, writer=None) -> SamplingReview:
    """显式构造（绝不走单例），账本落 tmp_path。"""
    return SamplingReview(store_path=str(tmp_path / "sampling_review.json"),
                          prior_writer=writer)


# ═══════════════════════════════════════════════════════════════
#  _stable_hash —— 抽样可复现的关键
# ═══════════════════════════════════════════════════════════════

class TestStableHash:
    def test_same_input_same_output(self):
        """同输入必须逐位相同 —— 抽样可复现/可审计的前提。"""
        assert _stable_hash("unit-42") == _stable_hash("unit-42")

    def test_distinct_inputs_produce_distinct_values(self):
        """50 个不同 unit_id 不应撞哈希（撞了就说明函数退化成常量）。"""
        vals = {_stable_hash(f"u{i}") for i in range(50)}
        assert len(vals) == 50

    def test_range_is_half_open_unit_interval(self):
        """值域必须落在 [0,1)，否则 `hash < p` 的抽样判定会失效。"""
        for i in range(200):
            v = _stable_hash(f"id-{i}")
            assert 0.0 <= v < 1.0

    def test_locks_algorithm_md5_first_12_hex(self):
        """锁住实现：md5 前 12 个十六进制字符 / 0xFFFFFFFFFFFF。

        判别性：若有人把 md5 换成 sha1、或改截断长度/除数，本用例立刻红。
        """
        text = "锁定算法"
        h = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()
        expected = int(h[:12], 16) / float(0xFFFFFFFFFFFF)
        assert _stable_hash(text) == expected

    def test_non_ascii_and_replacement_does_not_raise(self):
        """非 ASCII / 代理字符不得抛异常（errors='replace' 兜底）。"""
        assert 0.0 <= _stable_hash("中文🙂\ud800") < 1.0


class TestResolveStorePath:
    def test_env_var_overrides_default(self, monkeypatch, tmp_path):
        target = str(tmp_path / "custom.json")
        monkeypatch.setenv(_STORE_ENV, target)
        assert _resolve_store_path() == target

    def test_blank_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(_STORE_ENV, "   ")
        assert _resolve_store_path() == sr._DEFAULT_STORE


# ═══════════════════════════════════════════════════════════════
#  ① 自适应分层抽样 should_sample
# ═══════════════════════════════════════════════════════════════

class TestShouldSample:
    def test_decision_is_reproducible_across_instances(self, tmp_path):
        """同 unit_id 在两个独立实例上必须给出同一次抽样决定。"""
        a = _review(tmp_path).should_sample("fixed-unit", "video")
        b = _review(tmp_path).should_sample("fixed-unit", "video")
        assert a["sample"] == b["sample"]
        assert a["p"] == b["p"]

    def test_base_probability_when_no_signal(self, tmp_path):
        """残差/分歧都为 0 → p 恰为基础抽样率 _P_BASE。"""
        r = _review(tmp_path).should_sample("u", "video")
        assert r["p"] == round(_P_BASE, 4)
        assert r["reasons"] == ["基础抽样率"]

    def test_residual_and_divergence_amplify_probability(self, tmp_path):
        """P = clamp(p_base×(1+α_r·r̂+α_d·Δ̂), p_min, 1) —— 直接锁公式。"""
        base = _review(tmp_path).should_sample("u", "video")["p"]
        amp = _review(tmp_path).should_sample(
            "u", "video", residual=1.0, divergence=1.0)["p"]
        assert amp == round(min(1.0, _P_BASE * (1 + 4.0 + 2.0)), 4)
        assert amp > base

    def test_p_never_below_p_min(self, tmp_path):
        """概率下限：即使无任何信号，也永不低于 _P_MIN（永不完全停检）。"""
        r = _review(tmp_path).should_sample("u", "video", residual=0.0)
        assert r["p"] >= _P_MIN

    def test_probability_clamped_at_one(self, tmp_path):
        """放大系数给到极端也不能超过 1.0。"""
        r = _review(tmp_path).should_sample(
            "u", "video", residual=1.0, divergence=1.0)
        assert r["p"] <= 1.0

    def test_new_version_forces_sampling(self, tmp_path):
        """新模型版本 → 强制必检：p=1.0 且 sample=True（不掷硬币）。"""
        r = _review(tmp_path).should_sample("u", "video", new_version=True)
        assert r["sample"] is True and r["p"] == 1.0
        assert any("新模型版本" in x for x in r["reasons"])

    def test_new_genre_forces_sampling(self, tmp_path):
        r = _review(tmp_path).should_sample("u", "video", new_genre=True)
        assert r["sample"] is True
        assert any("新题材" in x for x in r["reasons"])

    def test_forced_sampling_counts_toward_sampled(self, tmp_path):
        r = _review(tmp_path)
        r.should_sample("u1", "video", new_version=True)
        r.should_sample("u2", "video", new_genre=True)
        assert r.metrics()["counts"]["sampled"] == 2

    def test_hit_increments_sampled_counter(self, tmp_path):
        """暴力搜一个哈希 < p_base 的 unit_id，验证命中路径真的计数。

        这是唯一能确定性触发「普通抽样命中」而不靠概率掷骰的办法。
        """
        rid = next(f"hit-{i}" for i in range(100000)
                   if _stable_hash(f"hit-{i}") < _P_BASE)
        r = _review(tmp_path)
        res = r.should_sample(rid, "video")
        assert res["sample"] is True
        assert r.metrics()["counts"]["sampled"] == 1

    def test_duplicate_prompt_signature_filtered_within_24h(self, tmp_path):
        """§71.5：24h 内同 prompt 签名第二次必须被过滤（不入池）。"""
        r = _review(tmp_path)
        first = r.should_sample("u1", "video", prompt_sig="sig-A")
        # 第一条：可能命中也可能不命中，但签名已登记
        assert "重复样本过滤（24h 内同签名）" not in first["reasons"]
        second = r.should_sample("u2", "video", prompt_sig="sig-A")
        assert second["sample"] is False and second["p"] == 0.0
        assert second["reasons"] == ["重复样本过滤（24h 内同签名）"]

    def test_different_signatures_not_deduped(self, tmp_path):
        r = _review(tmp_path)
        r.should_sample("u1", "video", prompt_sig="sig-A")
        r2 = r.should_sample("u2", "video", prompt_sig="sig-B")
        assert "重复样本过滤（24h 内同签名）" not in r2["reasons"]

    def test_purge_seen_drops_stale_entries(self, tmp_path):
        """超 24h 的签名必须被清理，否则去重会永久误杀老提示词。"""
        r = _review(tmp_path)
        r._ensure_loaded()
        r._seen["stale"] = time.time() - _DEDUP_WINDOW - 100
        r.should_sample("u", "video", prompt_sig="fresh")
        assert "stale" not in r._seen
        assert "fresh" in r._seen

    def test_n_units_counts_every_call(self, tmp_path):
        r = _review(tmp_path)
        r.should_sample("u1", "video")
        r.should_sample("u2", "video")
        r.should_sample("u3", "video")
        assert r.metrics()["counts"]["units"] == 3


# ═══════════════════════════════════════════════════════════════
#  ② 规则预审 prescreen
# ═══════════════════════════════════════════════════════════════

class TestPrescreen:
    def test_missing_file_is_high_risk(self, tmp_path):
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "video", "path": str(tmp_path / "nope.mp4")})
        assert out["risk"] == "高"
        assert "产物文件缺失" in out["defects"]
        assert out["form"]["suggested"] == "不合格"

    def test_tiny_video_size_flagged_medium(self, tmp_path):
        """视频体积 <10KB（疑似黑屏/崩坏）→ 中风险。"""
        f = tmp_path / "small.mp4"
        f.write_bytes(b"x" * 100)
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "video", "path": str(f)})
        assert out["risk"] == "中"
        assert any("视频体积异常" in d for d in out["defects"])

    def test_tiny_audio_size_flagged(self, tmp_path):
        f = tmp_path / "a.wav"
        f.write_bytes(b"x" * 10)
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "audio", "path": str(f)})
        assert any("音频体积异常" in d for d in out["defects"])

    def test_normal_video_file_not_flagged_for_size(self, tmp_path):
        """11KB 视频不该报体积问题（边界之上）。"""
        f = tmp_path / "ok.mp4"
        f.write_bytes(b"x" * (11 * 1024))
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "video", "path": str(f),
             "machine_score": 0.9})
        assert not any("体积异常" in d for d in out["defects"])

    def test_duration_deviation_over_20pct_flagged(self, tmp_path):
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "video", "duration": 10.0,
             "expected_duration": 5.0, "machine_score": 0.9})
        assert any("时长偏差" in d for d in out["defects"])

    def test_duration_within_tolerance_not_flagged(self, tmp_path):
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "video", "duration": 5.5,
             "expected_duration": 5.0, "machine_score": 0.9})
        assert not any("时长偏差" in d for d in out["defects"])

    def test_text_schema_missing_field_is_high_risk(self, tmp_path):
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "text", "fields": {"a": 1},
             "required_fields": ["a", "b"], "machine_score": 0.9})
        assert out["risk"] == "高"
        assert any("Schema 缺字段" in d for d in out["defects"])

    def test_text_unstructured_with_required_fields_flagged(self, tmp_path):
        """文本产物不是 dict 但声明了 required_fields → 无法校验 → 报缺陷。"""
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "text", "fields": "纯文本",
             "required_fields": ["title"], "machine_score": 0.9})
        assert any("非结构化" in d for d in out["defects"])

    def test_text_complete_schema_is_low_risk(self, tmp_path):
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "text", "fields": {"a": 1, "b": 2},
             "required_fields": ["a", "b"], "machine_score": 0.9})
        assert out["risk"] == "低" and out["defects"] == []

    def test_low_machine_score_flagged(self, tmp_path):
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "video", "machine_score": 0.1})
        assert any("机器分过低" in d for d in out["defects"])

    def test_uncertain_flag_for_borderline_machine_score(self, tmp_path):
        """无缺陷 + 机器分 [0.4,0.6] → uncertain（识别不了就上交，不硬判）。"""
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "video", "machine_score": 0.5})
        assert out["uncertain"] is True
        assert out["form"]["suggested"] == "存疑"

    def test_uncertain_false_when_machine_score_clear(self, tmp_path):
        out = _review(tmp_path).prescreen(
            {"unit_id": "u", "kind": "video", "machine_score": 0.95})
        assert out["uncertain"] is False
        assert out["form"]["suggested"] == "合格"

    def test_form_carries_prefilled_fields(self, tmp_path):
        """预标注表单必须一次填好机器分/模式/模型版本/渠道等字段。"""
        out = _review(tmp_path).prescreen(
            {"unit_id": "u7", "kind": "video", "machine_score": 0.9,
             "divergence": 0.3, "mode": "fast", "model_version": "v3",
             "provider": "ch1"})
        form = out["form"]
        assert form["unit_id"] == "u7"
        assert form["machine_score"] == 0.9
        assert form["divergence"] == 0.3
        assert form["mode"] == "fast"
        assert form["model_version"] == "v3"
        assert form["provider"] == "ch1"
        assert "created_at" in form

    def test_high_risk_increments_ai_flagged_counter(self, tmp_path):
        r = _review(tmp_path)
        r.prescreen({"unit_id": "u", "kind": "video",
                     "path": str(tmp_path / "missing.mp4")})
        assert r.metrics()["counts"]["ai_flagged"] == 1

    def test_low_risk_does_not_increment_ai_flagged(self, tmp_path):
        r = _review(tmp_path)
        r.prescreen({"unit_id": "u", "kind": "video", "machine_score": 0.9})
        assert r.metrics()["counts"]["ai_flagged"] == 0


# ═══════════════════════════════════════════════════════════════
#  ③ AI 打分入池 + 红线
# ═══════════════════════════════════════════════════════════════

class TestSubmitAiScore:
    def test_unit_enters_pool(self, tmp_path):
        r = _review(tmp_path)
        out = r.submit_ai_score({"unit_id": "u1", "kind": "video",
                                 "machine_score": 0.9})
        assert out["unit_id"] == "u1"
        assert [f["unit_id"] for f in r.pending_reviews()] == ["u1"]

    def test_auto_generated_uid_when_missing(self, tmp_path):
        r = _review(tmp_path)
        out = r.submit_ai_score({"kind": "video", "machine_score": 0.9})
        assert out["unit_id"].startswith("u_")

    def test_red_line_never_writes_prior(self, tmp_path):
        """§72/§76 红线：AI 打分**绝不**触碰注入的 prior_writer。"""
        calls = []
        r = _review(tmp_path, writer=lambda p, y: calls.append((p, y)))
        r.submit_ai_score({"unit_id": "u", "kind": "video",
                           "machine_score": 0.1, "provider": "ch1"})
        assert calls == [], "AI 打分不得写先验库（红线）"

    def test_pool_capacity_bounded(self, tmp_path):
        """>200 条触发淘汰，池容量必须封顶（不能无限增长）。"""
        r = _review(tmp_path)
        for i in range(210):
            r.submit_ai_score({"unit_id": f"u{i:03d}", "kind": "video",
                               "machine_score": 0.9})
        assert len(r.pending_reviews()) <= 200


# ═══════════════════════════════════════════════════════════════
#  ④ pending_reviews 排序
# ═══════════════════════════════════════════════════════════════

class TestPendingReviews:
    def _seed(self, r, tmp_path):
        # 低风险
        r.submit_ai_score({"unit_id": "low", "kind": "video",
                           "machine_score": 0.9})
        # 高风险（文件缺失）
        r.submit_ai_score({"unit_id": "high", "kind": "video",
                           "path": str(tmp_path / "missing.mp4"),
                           "machine_score": 0.9})
        # 中风险（机器分 0.4，无缺陷）
        r.submit_ai_score({"unit_id": "mid", "kind": "video",
                           "machine_score": 0.4})

    def test_high_first_ordering(self, tmp_path):
        """§73「高风险优先推送人工」：高 → 中 → 低。"""
        r = _review(tmp_path)
        self._seed(r, tmp_path)
        risks = [f["risk"] for f in r.pending_reviews(high_first=True)]
        assert risks == ["高", "中", "低"]

    def test_high_first_false_preserves_insertion_order(self, tmp_path):
        r = _review(tmp_path)
        self._seed(r, tmp_path)
        ids = [f["unit_id"] for f in r.pending_reviews(high_first=False)]
        assert ids == ["low", "high", "mid"]


# ═══════════════════════════════════════════════════════════════
#  ⑤ 人工真值 submit_human_label（唯一写先验通道）
# ═══════════════════════════════════════════════════════════════

class TestSubmitHumanLabel:
    def test_illegal_label_rejected(self, tmp_path):
        r = _review(tmp_path)
        out = r.submit_human_label("u", "凑合")
        assert out["ok"] is False and "非法标签" in out["error"]

    def test_valid_label_pops_from_pool_and_appends_history(self, tmp_path):
        r = _review(tmp_path)
        r.submit_ai_score({"unit_id": "u1", "kind": "video",
                           "machine_score": 0.9})
        out = r.submit_human_label("u1", "合格", ai_score=0.9)
        assert out["ok"] is True and out["y"] == 1.0
        assert out["residual"] == pytest.approx(0.1)  # |1.0 − 0.9|
        assert r.pending_reviews() == []
        assert r._labels[-1]["unit_id"] == "u1"
        assert r._labels[-1]["label"] == "合格"

    def test_residual_is_abs_diff(self, tmp_path):
        r = _review(tmp_path)
        out = r.submit_human_label("u", "不合格", ai_score=0.8)
        assert out["residual"] == 0.8
        assert out["y"] == 0.0

    def test_ai_score_defaults_from_pool_form(self, tmp_path):
        """未显式传 ai_score → 取池中预审表单的 machine_score。"""
        r = _review(tmp_path)
        r.submit_ai_score({"unit_id": "u", "kind": "video",
                           "machine_score": 0.7})
        out = r.submit_human_label("u", "合格")
        assert out["residual"] == pytest.approx(0.3)

    def test_prior_writer_called_with_provider_and_y(self, tmp_path):
        """注入式 prior_writer 是人工真值写先验库的**唯一通道**，必须真被调用。"""
        calls = []
        r = _review(tmp_path, writer=lambda p, y: calls.append((p, y)))
        out = r.submit_human_label("u", "合格", ai_score=0.9, provider="ch1")
        assert calls == [("ch1", 1.0)]
        assert out["wrote_prior"] is True

    def test_prior_writer_not_called_without_provider(self, tmp_path):
        """没有 provider 就不写先验（不知道往哪个桶写）。"""
        calls = []
        r = _review(tmp_path, writer=lambda p, y: calls.append((p, y)))
        out = r.submit_human_label("u", "合格", ai_score=0.9)
        assert calls == []
        assert out["wrote_prior"] is False

    def test_no_writer_still_records_label(self, tmp_path):
        """无 writer 时只记标签、不崩（诚实降级）。"""
        r = _review(tmp_path)
        out = r.submit_human_label("u", "存疑", ai_score=0.5, provider="ch1")
        assert out["ok"] is True and out["wrote_prior"] is False
        assert r._labels[-1]["y"] == 0.5

    def test_writer_exception_swallowed(self, tmp_path):
        """先验写入抛异常不能拖垮标签入库（不阻断）。"""
        def boom(p, y):
            raise RuntimeError("先验库挂了")

        r = _review(tmp_path, writer=boom)
        out = r.submit_human_label("u", "合格", ai_score=0.9, provider="ch1")
        assert out["ok"] is True and out["wrote_prior"] is False

    def test_residual_ema_matches_alpha_formula(self, tmp_path):
        """残差 EMA：mean = mean + α·(r − mean)，第一样本 mean = α·r。"""
        r = _review(tmp_path)
        out = r.submit_human_label("u", "合格", ai_score=0.0)
        assert out["residual_mean"] == pytest.approx(round(_ALPHA * 1.0, 4))

    def test_metrics_recall_precision_after_labels(self, tmp_path):
        """构造 TP / FN 两类样本，验证召回率与精确率算法。

        tp=1, fn=1, ai_flagged=1 ⇒ recall=0.5, precision=1.0。
        """
        r = _review(tmp_path)
        # TP：高风险入池 + 人工判不合格
        r.submit_ai_score({"unit_id": "tp", "kind": "video",
                           "path": str(tmp_path / "m.mp4"),
                           "machine_score": 0.9})
        r.submit_human_label("tp", "不合格", ai_score=0.9)
        # FN：低风险入池 + 人工判不合格（AI 没标出来）
        r.submit_ai_score({"unit_id": "fn", "kind": "video",
                           "machine_score": 0.9})
        r.submit_human_label("fn", "不合格", ai_score=0.9)
        m = r.metrics()
        assert m["recall"] == pytest.approx(0.5)
        assert m["precision"] == pytest.approx(1.0)
        assert m["counts"]["tp"] == 1 and m["counts"]["fn"] == 1
        assert m["counts"]["true_defect"] == 2


# ═══════════════════════════════════════════════════════════════
#  ⑥ 漂移检测 + 冻结/解冻
# ═══════════════════════════════════════════════════════════════

class TestDriftAndFreeze:
    def test_no_freeze_below_min_samples(self, tmp_path):
        """样本数 < 5 时即使残差极大也不冻结（防小样本误冻结）。"""
        r = _review(tmp_path)
        for i in range(_MIN_SAMPLES_FOR_DRIFT - 1):
            out = r.submit_human_label(f"u{i}", "合格", ai_score=0.0)
        assert out["frozen"] is False
        assert r.is_frozen() is False

    def test_freeze_triggered_on_high_residual(self, tmp_path):
        """残差均值 >0.30 且够样本 → 冻结闭环，返回 drift='freeze'。"""
        r = _review(tmp_path)
        drift = None
        for i in range(_MIN_SAMPLES_FOR_DRIFT):
            out = r.submit_human_label(f"u{i}", "合格", ai_score=0.0)
            drift = out["drift"]
        assert drift == "freeze"
        assert r.is_frozen() is True
        assert r.drift_status()["frozen"] is True

    def test_warn_triggered_on_mid_residual(self, tmp_path):
        """残差均值落在 (0.15, 0.30] → 告警但不冻结。"""
        r = _review(tmp_path)
        drift = None
        for i in range(_MIN_SAMPLES_FOR_DRIFT):
            out = r.submit_human_label(f"u{i}", "合格", ai_score=0.8)
            drift = out["drift"]
        assert drift == "warn"
        assert r.is_frozen() is False

    def test_freeze_alert_recorded(self, tmp_path):
        r = _review(tmp_path)
        for i in range(_MIN_SAMPLES_FOR_DRIFT):
            r.submit_human_label(f"u{i}", "合格", ai_score=0.0)
        kinds = [a["kind"] for a in r.drift_status()["alerts"]]
        assert "freeze" in kinds

    def test_unfreeze_resets_baseline_and_records_alert(self, tmp_path):
        r = _review(tmp_path)
        for i in range(_MIN_SAMPLES_FOR_DRIFT):
            r.submit_human_label(f"u{i}", "合格", ai_score=0.0)
        assert r.is_frozen() is True
        out = r.unfreeze(operator="张三")
        assert out == {"ok": True, "was_frozen": True}
        assert r.is_frozen() is False
        st = r.drift_status()
        assert st["residual_n"] == 0
        assert st["residual_mean"] == 0.0
        assert any(a["kind"] == "unfreeze" for a in st["alerts"])

    def test_unfreeze_when_not_frozen_is_idempotent_no_alert(self, tmp_path):
        """未冻结时解冻不应产生 unfreeze 告警（避免噪声告警）。"""
        r = _review(tmp_path)
        out = r.unfreeze()
        assert out == {"ok": True, "was_frozen": False}
        assert all(a["kind"] != "unfreeze"
                   for a in r.drift_status()["alerts"])

    def test_drift_status_exposes_thresholds(self, tmp_path):
        st = _review(tmp_path).drift_status()
        assert st["warn_threshold"] == _DRIFT_WARN
        assert st["freeze_threshold"] == _DRIFT_FREEZE
        assert st["frozen"] is False and st["residual_n"] == 0


# ═══════════════════════════════════════════════════════════════
#  ⑦ metrics 字段
# ═══════════════════════════════════════════════════════════════

class TestMetrics:
    def test_empty_metrics_have_none_ratios(self, tmp_path):
        """无数据时比率必须为 None（不能用 0 冒充「表现差」）。"""
        m = _review(tmp_path).metrics()
        assert m["recall"] is None
        assert m["precision"] is None
        assert m["labor_reduction"] is None
        assert m["counts"] == {"units": 0, "sampled": 0, "ai_flagged": 0,
                               "true_defect": 0, "tp": 0, "fn": 0}

    def test_labor_reduction_formula(self, tmp_path):
        """人工减负率 = 1 − 抽样数/总单元数。"""
        r = _review(tmp_path)
        # 5 单元，其中仅 1 个被新版本强制必检 → sampled=1, units=5
        for i in range(4):
            r.should_sample(f"plain{i}", "video")
        r.should_sample("forced", "video", new_version=True)
        m = r.metrics()
        assert m["counts"]["units"] == 5
        assert m["counts"]["sampled"] == 1
        assert m["labor_reduction"] == pytest.approx(0.8)

    def test_targets_present(self, tmp_path):
        t = _review(tmp_path).metrics()["targets"]
        assert t["recall"] == "≥0.80"
        assert t["labor_reduction"] == "0.70~0.90"


# ═══════════════════════════════════════════════════════════════
#  ⑧ 持久化往返 + 损坏容错
# ═══════════════════════════════════════════════════════════════

class TestPersistence:
    def test_roundtrip_preserves_pool_and_labels(self, tmp_path):
        """A 写入 → B 从同一路径读回，池与人工标签历史必须一致。"""
        path = str(tmp_path / "sr.json")
        a = SamplingReview(store_path=path)
        a.submit_ai_score({"unit_id": "u1", "kind": "video",
                           "machine_score": 0.9})
        a.submit_ai_score({"unit_id": "u2", "kind": "video",
                           "machine_score": 0.9})
        a.submit_human_label("u1", "合格", ai_score=0.9, provider="ch1")

        b = SamplingReview(store_path=path)
        assert [f["unit_id"] for f in b.pending_reviews()] == ["u2"]
        assert b._labels[-1]["unit_id"] == "u1"
        assert b.drift_status()["residual_n"] == 1

    def test_roundtrip_preserves_frozen_state(self, tmp_path):
        path = str(tmp_path / "sr.json")
        a = SamplingReview(store_path=path)
        for i in range(_MIN_SAMPLES_FOR_DRIFT):
            a.submit_human_label(f"u{i}", "合格", ai_score=0.0)
        assert a.is_frozen() is True
        b = SamplingReview(store_path=path)
        assert b.is_frozen() is True
        assert b.drift_status()["residual_mean"] > _DRIFT_FREEZE

    def test_roundtrip_preserves_metrics_counters(self, tmp_path):
        path = str(tmp_path / "sr.json")
        a = SamplingReview(store_path=path)
        a.submit_ai_score({"unit_id": "tp", "kind": "video",
                           "path": str(tmp_path / "m.mp4"),
                           "machine_score": 0.9})
        a.submit_human_label("tp", "不合格", ai_score=0.9)
        b = SamplingReview(store_path=path)
        m = b.metrics()
        assert m["counts"]["ai_flagged"] == 1
        assert m["counts"]["tp"] == 1

    def test_corrupted_json_starts_fresh_without_crash(self, tmp_path):
        """损坏的账本文件不得让模块崩 —— 按初始状态启动。"""
        path = tmp_path / "sr.json"
        path.write_text("{ 这不是合法 JSON ", encoding="utf-8")
        r = SamplingReview(store_path=path)
        assert r.is_frozen() is False
        m = r.metrics()
        assert m["counts"]["units"] == 0
        # 且仍可正常继续工作（写入覆盖损坏文件）
        r.should_sample("u", "video")
        assert r.metrics()["counts"]["units"] == 1

    def test_non_dict_json_starts_fresh(self, tmp_path):
        """顶层是 list 的 JSON 也应被安全忽略（不得 AttributeError）。"""
        path = tmp_path / "sr.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        r = SamplingReview(store_path=path)
        assert r.metrics()["counts"]["units"] == 0

    def test_file_written_with_expected_keys(self, tmp_path):
        """落盘 JSON 必须含全部持久化字段（结构契约）。"""
        path = tmp_path / "sr.json"
        r = SamplingReview(store_path=path)
        r.submit_ai_score({"unit_id": "u", "kind": "video",
                           "machine_score": 0.9})
        data = json.loads(path.read_text(encoding="utf-8"))
        for k in ("pool", "labels", "residual_mean", "residual_var",
                  "residual_n", "frozen", "alerts", "seen",
                  "n_sampled", "n_units", "n_ai_flagged",
                  "n_true_defect", "n_flagged_defect",
                  "n_unflagged_defect"):
            assert k in data

    def test_save_is_atomic_no_tmp_leftover(self, tmp_path):
        """原子写：保存后目录里不应残留 .tmp 临时文件。"""
        path = tmp_path / "sr.json"
        r = SamplingReview(store_path=path)
        r.submit_ai_score({"unit_id": "u", "kind": "video",
                           "machine_score": 0.9})
        leftovers = list(tmp_path.glob("sr_*.tmp"))
        assert leftovers == []
