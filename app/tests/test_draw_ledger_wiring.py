# -*- coding: utf-8 -*-
"""抽卡闭环接线（P1 通电 + P2 推荐回传，V4.40.8）

P1 断言：
- 生成成功 → draw_book 落账（分数、seed 按 seed_sent 决定是否入账）
- 响应就地获得 proxy_score / proxy_detail / **is_proxy=True**（红线标注）
- quality_prior 只写 **kind="proxy"** 桶 —— **不得污染 "quality" 桶**
  （人工标签真值桶，红线）；route_mean 不消费 proxy 桶 ⇒ 零路由影响
- 生成失败 → 不落账（没有图）
- 账本/评分器异常 → 不影响生成结果（异常绝不抛出）

P2 断言：
- lookup_recommendation：无历史 None / 有历史带 best_seed
"""
from __future__ import annotations

import base64
import json

import numpy as np
import pytest

import app.core.ai.draw_book as db
import app.core.ai.draw_ledger as dl
import app.core.ai.quality_prior as qp

cv2 = pytest.importorskip("cv2", reason="构造有效 PNG 需要 cv2")

import app.core.canvas_aigc as aigc


# ── 夹具：真实 PNG + 假渠道 + 捕获请求 ─────────────────────────────────────


def _png_data_url(w=512, h=288, seed=3):
    r = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 0] = np.linspace(30, 200, w, dtype=np.uint8)[None, :]
    img[:, :, 1] = np.linspace(20, 160, h, dtype=np.uint8)[:, None]
    img[:, :, 2] = 90
    for _ in range(10):
        x0, y0 = int(r.integers(0, w - 60)), int(r.integers(0, h - 60))
        img[y0:y0 + 50, x0:x0 + 50] = r.integers(0, 255, 3)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def env(tmp_path, monkeypatch):
    """假硅基渠道 + 隔离的账本/先验库（都指到 tmp_path）。"""
    data_url = _png_data_url()
    monkeypatch.setattr(aigc, "build_host_ai_config_patch", lambda: {
        "channels": [{
            "id": "ch1", "name": "测试渠道",
            "baseUrl": "https://api.siliconflow.cn/v1", "apiKey": "k",
            "models": [{"name": "m1", "capability": "image"}],
        }],
        "defaults": {},
    })
    monkeypatch.setattr(
        aigc, "_open_url_cancellable",
        lambda req, timeout=120, **kw: _FakeResp({"data": [{"b64_json": data_url.split(",", 1)[1]}]}),
    )
    book = db.DrawBookStore(store_path=str(tmp_path / "draw_book.json"))
    prior = qp.QualityPriorStore(store_path=str(tmp_path / "quality_prior.json"))
    monkeypatch.setattr(db, "get_store", lambda: book)
    monkeypatch.setattr(qp, "get_store", lambda: prior)
    return {"book": book, "prior": prior, "data_url": data_url}


# ── P1 通电 ─────────────────────────────────────────────────────────────────


def test_success_feeds_ledger_with_score_and_seed(env):
    res = aigc.generate_image_openai_compatible(
        prompt="雨夜少女", model="m1", channel_id="ch1",
        quality="draft", seed=2026)
    assert res["ok"] is True
    # 响应字段：代理分 + 红线标注
    assert res["is_proxy"] is True
    assert 0.0 <= res["proxy_score"] <= 1.0
    assert res["proxy_detail"]["broken_gate_applied"] is False
    # P4：免费附「坏区体检报告」，但**不自动修**（花钱的事需显式触发）
    assert "repair_plan" in res
    assert isinstance(res["repair_plan"]["needs_repair"], bool)
    assert "image_data_url" not in res["repair_plan"]  # 报告里不含修复图

    # 账本落账：分数一致、seed 入账（硅基 → seed_sent=True）
    b = list(env["book"]._buckets.values())[0]
    assert b["n"] == 1.0
    assert abs(b["mean"] - res["proxy_score"]) < 0.2  # EMA 首样本 = 该分
    assert b["best_seed"] == 2026
    assert b["best_score"] == res["proxy_score"]


def test_auto_seed_not_booked_when_not_sent(env):
    """非硅基渠道 + 自动种子 → seed_sent=False → 不进 best_seed（不可复现不记账）。"""
    aigc.build_host_ai_config_patch = lambda: {  # 覆盖为 openai 渠道（不支持种子透传假设）
        "channels": [{
            "id": "ch1", "name": "测试渠道", "baseUrl": "https://api.openai.com/v1",
            "apiKey": "k", "models": [{"name": "m1", "capability": "image"}]}],
        "defaults": {},
    }
    res = aigc.generate_image_openai_compatible(
        prompt="自动种子", model="m1", channel_id="ch1", quality="draft")
    assert res["ok"] is True
    assert res["seed_sent"] is False
    b = list(env["book"]._buckets.values())[0]
    assert b["best_seed"] is None      # 账本最关键的诚实点
    assert b["n"] == 1.0               # 但均分照记


def test_proxy_bucket_does_not_pollute_quality_truth_bucket(env):
    """桶位纪律：代理分只进 proxy 桶；quality（人工真值）桶保持为空。"""
    res = aigc.generate_image_openai_compatible(
        prompt="桶位纪律", model="m1", channel_id="ch1", quality="draft")
    assert res["ok"] is True
    snap = env["prior"].summary()
    assert "ch1::proxy" in snap
    assert abs(float(snap["ch1::proxy"]["mean"]) - res["proxy_score"]) < 1e-6
    assert not [k for k in snap if k.endswith("::quality")]  # 真值桶零污染
    # route_mean 不读 proxy 桶 ⇒ 零路由影响
    assert env["prior"].route_mean("ch1") == 0.5


def test_lookup_prefers_quality_truth_once_available(env):
    """反证：proxy 桶存在时 route_mean 仍只认 quality/default（红线隔离有效）。"""
    env["prior"].record_outcome("ch1", True, quality=0.9, kind="proxy")
    assert env["prior"].route_mean("ch1") == 0.5  # 不消费 proxy
    env["prior"].record_outcome("ch1", True, quality=0.9, kind="quality")
    assert env["prior"].route_mean("ch1") == 0.9  # 人工真值才接管


def test_ledger_failure_does_not_break_generation(env, monkeypatch):
    """账本炸了也必须照常返回图（接线绝不拖垮主链路）。"""
    def _boom():
        raise RuntimeError("账本挂了")

    monkeypatch.setattr(db, "get_store", _boom)
    res = aigc.generate_image_openai_compatible(
        prompt="账本故障", model="m1", channel_id="ch1", quality="draft")
    assert res["ok"] is True
    assert res["image_data_url"].startswith("data:image/png;base64,")


def test_failed_generation_records_nothing(env, monkeypatch):
    monkeypatch.setattr(
        aigc, "_open_url_cancellable",
        lambda req, timeout=120, **kw: _FakeResp({"error": "boom"}))
    res = aigc.generate_image_openai_compatible(
        prompt="失败不记账", model="m1", channel_id="ch1", quality="draft")
    assert res["ok"] is False
    assert env["book"].stats()["total_draws"] == 0
    assert env["prior"].summary() == {}


# ── P2 推荐回传 ─────────────────────────────────────────────────────────────


def test_lookup_recommendation_none_without_history():
    assert dl.lookup_recommendation("从没抽过", "m1") is None


def test_lookup_recommendation_returns_best_seed(env):
    env["book"].record_draw("回头客", "m1", 0.9, seed=777, size="1024x576")
    rec = dl.lookup_recommendation("回头客", "m1", size="1024x576")
    assert rec is not None
    assert rec["best_seed"] == 777
    assert rec["n"] == 1
    assert "advice" in rec


def test_two_draws_second_response_carries_recommendation(env):
    """方案 §四 P2 验收：同一 prompt 生成两次 → 第二次响应含 recommendation。"""
    kw = dict(prompt="连续抽卡", model="m1", channel_id="ch1", quality="draft")
    r1 = aigc.generate_image_openai_compatible(**kw)
    assert r1["ok"] is True
    assert "recommendation" not in r1          # 首次无历史 → 不带该字段
    r2 = aigc.generate_image_openai_compatible(**kw)
    assert r2["ok"] is True
    assert "recommendation" in r2              # 第二次：账本已有本指纹记录
    assert r2["recommendation"]["n"] >= 1


def test_now_ms_is_monotonic_millis():
    a = dl.now_ms()
    b = dl.now_ms()
    assert b >= a
    assert b - a < 5000  # 毫秒量级（不是秒）
