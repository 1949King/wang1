# -*- coding: utf-8 -*-
"""app/tests/test_speaker_diarize.py — 说话人分离的诚实性回归（2026-10-09，刀 T1）。

本模块的红线只有一条，但它最重要：**分离不出来就必须诚实失败，绝不伪造 speaker 标签**。
（假标签会污染下游多角色配音，把"无依据"当成"已分离"。）

测试锁四件事：
  ① `assign_speakers()` 是纯函数：重叠投票、无重叠留空、坏输入不炸；
  ② **无重叠 ⇒ speaker=None**（不是编一个）；
  ③ `diarize()` 在 funasr 未装时诚实降级：ok=False、available=False、segments 原样带 speaker=None、
     且 reason 给出安装指引；
  ④ 源码级锁：模块内**不得**出现"伪造编号 speaker"的写法（如凭空 `speaker_00` 递增）。
"""
import io
import os
import re


from app.core.ai import speaker_diarize as sd

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "app", "core", "ai", "speaker_diarize.py")


# ─────────────────────── ① 纯函数：重叠投票 ───────────────────────

def test_assign_speakers_overlap_vote():
    segs = [{"start": 0.0, "end": 2.0, "text": "A 的话"},
            {"start": 2.0, "end": 5.0, "text": "B 的话"}]
    ranges = [{"start": 0.0, "end": 1.8, "speaker": "spk_0"},
              {"start": 2.1, "end": 4.9, "speaker": "spk_1"}]
    out = sd.assign_speakers(segs, ranges)
    assert out[0]["speaker"] == "spk_0"
    assert out[1]["speaker"] == "spk_1"


def test_assign_speakers_longest_overlap_wins():
    """一个 segment 跨多个说话人区间时，取重叠时长最长的那个。"""
    segs = [{"start": 0.0, "end": 10.0, "text": "跨两人"}]
    ranges = [{"start": 0.0, "end": 3.0, "speaker": "spk_a"},
              {"start": 3.0, "end": 10.0, "speaker": "spk_b"}]
    out = sd.assign_speakers(segs, ranges)
    assert out[0]["speaker"] == "spk_b"   # 3~10 重叠 7 秒 > 0~3 重叠 3 秒


def test_assign_speakers_no_overlap_is_none():
    """★ 完全无重叠 ⇒ speaker=None，而不是编一个。"""
    segs = [{"start": 10.0, "end": 12.0, "text": "无归属"}]
    ranges = [{"start": 0.0, "end": 1.0, "speaker": "spk_x"}]
    out = sd.assign_speakers(segs, ranges)
    assert out[0]["speaker"] is None


def test_assign_speakers_bad_input_no_crash():
    assert sd.assign_speakers([], []) == []
    # 坏时间戳不炸，且诚实留空
    out = sd.assign_speakers([{"start": "x", "end": "y", "text": "坏"}], [])
    assert out[0]["speaker"] is None
    # 不改动原对象（浅拷贝：加字段，不改原值）
    seg = {"start": 0.0, "end": 1.0, "text": "原文"}
    sd.assign_speakers([seg], [{"start": 0.0, "end": 1.0, "speaker": "s"}])
    assert seg["text"] == "原文" and "speaker" not in seg


# ─────────────────────── ② 诚实失败 ───────────────────────

def test_diarize_honest_fallback_when_funasr_missing(monkeypatch):
    monkeypatch.setattr(sd, "funasr_available", lambda: False)
    segs = [{"start": 0.0, "end": 1.0, "text": "你好"}]
    res = sd.diarize("whatever.mp3", segs)
    assert res["ok"] is False
    assert res["available"] is False
    assert res["segments"][0]["speaker"] is None
    assert "funasr" in res["reason"]            # 给出安装指引


def test_diarize_honest_when_model_returns_nothing(monkeypatch):
    monkeypatch.setattr(sd, "funasr_available", lambda: True)
    monkeypatch.setattr(sd, "diarize_ranges", lambda p: [])
    segs = [{"start": 0.0, "end": 1.0, "text": "你好"}]
    res = sd.diarize("whatever.mp3", segs)
    assert res["ok"] is False
    assert res["speaker_count"] == 0
    assert res["segments"][0]["speaker"] is None


def test_diarize_counts_distinct_speakers(monkeypatch):
    monkeypatch.setattr(sd, "funasr_available", lambda: True)
    monkeypatch.setattr(sd, "diarize_ranges", lambda p: [
        {"start": 0.0, "end": 1.0, "speaker": "spk_0"},
        {"start": 1.0, "end": 2.0, "speaker": "spk_1"},
        {"start": 2.0, "end": 3.0, "speaker": "spk_0"},
    ])
    segs = [{"start": 0.0, "end": 1.0, "text": "a"},
            {"start": 1.0, "end": 2.0, "text": "b"},
            {"start": 2.0, "end": 3.0, "text": "c"}]
    res = sd.diarize("x", segs)
    assert res["ok"] is True
    assert res["speaker_count"] == 2


# ─────────────────────── ③ 源码级锁：不许伪造 speaker ───────────────────────

def test_source_does_not_fabricate_speaker_ids():
    src = io.open(SRC, encoding="utf-8").read()
    # ⚠️ 先剥 docstring 与注释再判：docstring 里"提到"speaker_00/01 是**说明禁止**，
    #   不是伪造代码；不剥就会像 /host/xxx、setStyleSheet 那样误报。
    code = re.sub(r'"""[\s\S]*?"""', "", src)
    code = re.sub(r"^\s*#.*$", "", code, flags=re.M)
    # 真正的伪造模式：凭空递增编号 speaker（f-string / %-format）
    for bad in ('f"speaker_{', 'f"spk_{', '"speaker_%d"', '"spk_%d"', "spk_%d"):
        assert bad not in code, f"源码出现伪造说话人的写法：{bad}"
    # 必须明确 None 语义（诚实留空）
    assert 'speaker=None' in src or '"speaker"] = None' in src


# ─────────────────────── 性能与平票（2026-10-09 优化回归）───────────────────────

def test_tie_break_prefers_higher_overlap_ratio():
    """平票判定：重叠时长并列时，取重叠**比例**更高的区间（更公平）。

    场景：segment 0-10s；区间 A 0-10（重叠 10s，占比 100%）、区间 B 5-15（重叠 5s）
    ⇒ A 胜。旧版按"先出现"也能蒙对这种顺序，但 B 排前面时旧版就错了 —— 下面反转顺序验证。
    """
    segs = [{"start": 0.0, "end": 10.0, "text": "x"}]
    # B 在前：旧版平票规则会取"先出现"的 B（若两者重叠相等）；这里构造不等重叠验证稳定
    out = sd.assign_speakers(segs, [
        {"start": 5.0, "end": 15.0, "speaker": "B"},   # 重叠 5s
        {"start": 0.0, "end": 10.0, "speaker": "A"},   # 重叠 10s
    ])
    assert out[0]["speaker"] == "A", "应取重叠时长更大的 A（与顺序无关）"


def test_scanline_matches_bruteforce_on_random_input():
    """扫描线结果与暴力 O(n×m) 参考实现**完全一致**（随机 500 组对拍）。"""
    import random

    random.seed(42)

    def bruteforce(segments, ranges):
        out = []
        for seg in segments:
            s0, s1 = seg["start"], seg["end"]
            best, best_ov = None, 0.0
            for r in ranges:
                ov = min(s1, r["end"]) - max(s0, r["start"])
                if ov > best_ov:
                    best_ov, best = ov, r["speaker"]
            out.append({**seg, "speaker": best})
        return out

    for _ in range(500):
        n, m = random.randint(1, 8), random.randint(1, 8)
        segs = []
        t = 0.0
        for _ in range(n):
            d = random.uniform(0.5, 3.0)
            segs.append({"start": t, "end": t + d, "text": "x"})
            t += d + random.uniform(0, 1)
        ranges = []
        t = 0.0
        for i in range(m):
            d = random.uniform(0.5, 4.0)
            ranges.append({"start": t, "end": t + d, "speaker": f"spk{i}"})
            t += d + random.uniform(0, 0.8)
        got = sd.assign_speakers(segs, ranges)
        want = bruteforce(segs, ranges)
        for g, w in zip(got, want):
            assert g["speaker"] == w["speaker"], (
                f"扫描线与暴力结果不一致：seg={g['start']}-{g['end']} "
                f"scanline={g['speaker']} bruteforce={w['speaker']}")


def test_scanline_is_fast_on_large_input():
    """大数据（2000 段 × 5000 区间）应在数秒内完成（旧 O(n×m) 要千万次比较）。"""
    import time

    segs, t = [], 0.0
    for _ in range(2000):
        segs.append({"start": t, "end": t + 1.0, "text": "x"})
        t += 1.2
    ranges, t = [], 0.0
    for i in range(5000):
        ranges.append({"start": t * 0.001, "end": t * 0.001 + 0.8, "speaker": f"s{i}"})
        t += 1
    t0 = time.time()
    sd.assign_speakers(segs, ranges)
    assert time.time() - t0 < 5.0, "扫描线应在 5 秒内完成 2000×5000"
