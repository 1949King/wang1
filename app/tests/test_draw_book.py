# -*- coding: utf-8 -*-
"""抽卡账本（生成抽卡闭环 P0b，方案 §3.1 / §四验收行）

验收覆盖（方案裁定的五条）：
- EMA 正确（α=0.3 递推 + 方差递推 + n 计数）
- 指纹归一化（空白/大小写/全半角差异 → 同键）
- 推荐命中（含 best_seed / 无尺寸时跨尺寸选最优桶）
- 持久化往返（写盘 → 新实例读回）
- 无数据返 None（不得编造推荐）

另加：best_seed 竞争语义 / seed=None 不竞争 / LRU 淘汰 / 异常不抛出。
"""
from __future__ import annotations

import json
import os

import app.core.ai.draw_book as db


def _store(tmp_path, **kw):
    return db.DrawBookStore(store_path=str(tmp_path / "draw_book.json"), **kw)


# ── 指纹归一化 ──────────────────────────────────────────────────────────────


def test_fingerprint_normalizes_whitespace_case_and_fullwidth():
    k1 = db.fingerprint("一个 女孩，站在 雨中", "FLUX.1", size="1024x576")
    k2 = db.fingerprint("一个女孩,站在雨中", "flux.1", size="1024X576")
    k3 = db.fingerprint("一个女孩，站在雨中", "FLUX.1", size="1024x576")
    assert k1 == k3  # 空白差异同键（标点保留， NFKC 统一全半角逗号）
    assert k2 == k3  # 大小写不敏感（model/size 也归一）
    assert len(k1) == 16


def test_fingerprint_distinguishes_kind_and_size():
    base = db.fingerprint("女孩", "m1", size="1024x576", kind="image")
    assert base != db.fingerprint("女孩", "m1", size="1024x576", kind="video")
    assert base != db.fingerprint("女孩", "m1", size="768x768", kind="image")
    assert base != db.fingerprint("女孩", "m2", size="1024x576", kind="image")


# ── EMA 正确性 ──────────────────────────────────────────────────────────────


def test_ema_update_math(tmp_path):
    s = _store(tmp_path)
    s.record_draw("p", "m", 1.0, seed=11)
    s.record_draw("p", "m", 0.0, seed=22)
    b = s._buckets[db.fingerprint("p", "m")]
    # mean: 1.0 → 1.0 + 0.3*(0-1.0) = 0.7
    assert abs(b["mean"] - 0.7) < 1e-9
    # var: (1-0.3)*(0.25 + 0.3*(0-1)^2) = 0.7*0.55 = 0.385
    assert abs(b["var"] - 0.385) < 1e-9
    assert b["n"] == 2.0
    # best_seed：0.7 的 EMA 不影响 best——best 按单次得分竞争，1.0 > 0.0 → 仍是 11
    assert b["best_seed"] == 11
    assert b["best_score"] == 1.0


def test_best_seed_competes_on_single_score(tmp_path):
    s = _store(tmp_path)
    s.record_draw("p", "m", 0.5, seed=100)
    s.record_draw("p", "m", 0.9, seed=200)  # 更高分 → 抢下 best
    s.record_draw("p", "m", 0.7, seed=300)  # 不如 0.9 → 不动
    b = s._buckets[db.fingerprint("p", "m")]
    assert b["best_seed"] == 200
    assert b["best_score"] == 0.9


def test_seed_none_does_not_compete_best_seed(tmp_path):
    """seed_sent=False 的观测（seed=None）只累计均分，不竞争 best_seed。"""
    s = _store(tmp_path)
    s.record_draw("p", "m", 0.4, seed=100)
    s.record_draw("p", "m", 0.99)  # 无种子高分：mean 涨，best 不动
    b = s._buckets[db.fingerprint("p", "m")]
    assert b["best_seed"] == 100
    assert b["best_score"] == 0.4
    assert b["n"] == 2.0


def test_samples_ring_capped_at_20(tmp_path):
    s = _store(tmp_path)
    for i in range(25):
        s.record_draw("p", "m", 0.5, seed=i + 1)
    b = s._buckets[db.fingerprint("p", "m")]
    assert len(b["samples"]) == 20
    assert b["samples"][-1]["seed"] == 25  # 最新保留
    assert b["samples"][0]["seed"] == 6    # 最旧 5 条被挤出


# ── 推荐 ────────────────────────────────────────────────────────────────────


def test_recommend_hit_with_best_seed(tmp_path):
    s = _store(tmp_path)
    s.record_draw("雨夜少女", "FLUX.1", 0.6, seed=42, size="1024x576")
    rec = s.recommend("雨夜 少女", "flux.1", size="1024x576")  # 归一化后同键
    assert rec is not None
    assert rec["best_seed"] == 42
    assert rec["n"] == 1
    assert "样本尚少" in rec["advice"]  # n<5 如实标注参考性有限


def test_recommend_none_when_no_history(tmp_path):
    s = _store(tmp_path)
    assert s.recommend("从未见过", "m1") is None


def test_recommend_without_size_picks_best_size_bucket(tmp_path):
    s = _store(tmp_path)
    for _ in range(3):
        s.record_draw("p", "m", 0.4, size="768x768")
    for _ in range(3):
        s.record_draw("p", "m", 0.9, seed=7, size="1024x576")
    rec = s.recommend("p", "m")  # 不给 size → 选均分最高的 1024x576 桶
    assert rec is not None
    assert rec["size"] == "1024x576"
    assert rec["best_seed"] == 7
    assert "1024x576" in rec["advice"]


def test_recommend_no_seed_history_says_so(tmp_path):
    s = _store(tmp_path)
    s.record_draw("p", "m", 0.8)  # 从未透传种子
    rec = s.recommend("p", "m")
    assert rec["best_seed"] is None
    assert "无可复现种子" in rec["advice"]


# ── 持久化往返 ──────────────────────────────────────────────────────────────


def test_persistence_roundtrip(tmp_path):
    s1 = _store(tmp_path)
    s1.record_draw("持久化", "m1", 0.88, seed=999, size="1024x576")
    path = str(tmp_path / "draw_book.json")
    assert os.path.exists(path)
    # 磁盘 JSON 结构可直读
    raw = json.load(open(path, encoding="utf-8"))
    assert len(raw) == 1

    s2 = _store(tmp_path)  # 新实例从同一文件恢复
    rec = s2.recommend("持久化", "m1", size="1024x576")
    assert rec is not None
    assert rec["best_seed"] == 999
    assert rec["mean"] == 0.88


def test_corrupted_file_starts_empty(tmp_path):
    path = tmp_path / "draw_book.json"
    path.write_text("{ 这不是 JSON", encoding="utf-8")
    s = _store(tmp_path)
    assert s.recommend("p", "m") is None  # 不抛、按空库启动
    s.record_draw("p", "m", 0.5)          # 且能继续写（自愈覆盖坏文件）
    assert s.recommend("p", "m") is not None


# ── LRU 淘汰 ────────────────────────────────────────────────────────────────


def test_lru_eviction(tmp_path):
    s = _store(tmp_path, max_buckets=10)
    for i in range(12):
        s.record_draw(f"prompt-{i}", "m", 0.5)
    assert len(s._buckets) == 10
    # 最早两条被淘汰，最新的都在
    assert s.recommend("prompt-0", "m") is None
    assert s.recommend("prompt-1", "m") is None
    assert s.recommend("prompt-11", "m") is not None


# ── 异常不抛出（账本绝不能拖垮主链路） ──────────────────────────────────────


def test_record_never_raises_on_garbage(tmp_path):
    s = _store(tmp_path)
    s.record_draw("", "m", 0.5)            # 空 prompt → 不记
    s.record_draw("p", "", 0.5)            # 空 model → 不记
    s.record_draw("p", "m", "不是数字")     # 坏分数 → 不记
    s.record_draw("p", "m", 1.7, seed=-3)  # 越界分钳到 1.0；负种子视为无种子
    s.record_draw("p", "m", float("nan"))  # nan → _clamp01 后不崩（记为 0 或忽略皆可，关键是不抛）
    assert s.stats()["total_draws"] >= 1
    b = s._buckets[db.fingerprint("p", "m")]
    assert b["best_seed"] is None          # 负种子不入账


# ── 推荐新鲜度（P3：过期桶不参与推荐） ─────────────────────────────────────


def test_stale_bucket_not_recommended(tmp_path):
    s = _store(tmp_path)
    s.record_draw("旧账", "m", 0.9, seed=1, size="1024x576")
    key = db.fingerprint("旧账", "m", size="1024x576")
    s._buckets[key]["last_used"] -= 90 * 86400  # 拨回 90 天前（超默认 60 天）
    assert s.recommend("旧账", "m", size="1024x576") is None
    # 关闭新鲜度检查仍可回看（调试通道）
    assert s.recommend("旧账", "m", size="1024x576", max_age_days=0) is not None


def test_stale_does_not_delete_data(tmp_path):
    """过期只管推荐，不删数据（内存上限归 LRU 管）——stats 仍能看到。"""
    s = _store(tmp_path)
    s.record_draw("旧账2", "m", 0.9)
    s._buckets[db.fingerprint("旧账2", "m")]["last_used"] -= 400 * 86400
    assert s.recommend("旧账2", "m") is None
    assert s.stats()["buckets"] == 1 and s.stats()["total_draws"] == 1


def test_recommend_without_size_skips_stale_buckets(tmp_path):
    s = _store(tmp_path)
    s.record_draw("混合", "m", 0.95, size="768x768")      # 高分但过期
    s._buckets[db.fingerprint("混合", "m", size="768x768")]["last_used"] -= 90 * 86400
    s.record_draw("混合", "m", 0.5, seed=5, size="1024x576")  # 低分但新鲜
    rec = s.recommend("混合", "m")  # 不给 size：只能选新鲜的那个
    assert rec is not None
    assert rec["size"] == "1024x576"
    assert rec["best_seed"] == 5


def test_stats_shape(tmp_path):
    s = _store(tmp_path)
    assert s.stats() == {"buckets": 0, "total_draws": 0, "mean_score": 0.0}
    s.record_draw("p", "m", 0.8)
    st = s.stats()
    assert st["buckets"] == 1 and st["total_draws"] == 1 and st["mean_score"] == 0.8
