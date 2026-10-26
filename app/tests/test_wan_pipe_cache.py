# -*- coding: utf-8 -*-
"""Wan 常驻缓存（2026-10-27）：embeds LRU 命中，避免每次重编码。"""
from __future__ import annotations

import app.core.local_video_infer as LVI


def test_embeds_cache_hits_without_reencoding(monkeypatch):
    calls = {"n": 0}

    def fake_encode(model_path, prompt, negative, vram_gb):
        calls["n"] += 1
        return ("pe-%d" % calls["n"], "ne-%d" % calls["n"])

    monkeypatch.setattr(LVI, "_encode_wan_prompts", fake_encode)
    LVI._WAN_EMBEDS_CACHE.clear()

    a = LVI._wan_embeds_cached("/m/wan", "a cat", 8)
    b = LVI._wan_embeds_cached("/m/wan", "a cat", 8)
    assert a == b == ("pe-1", "ne-1"), "同 prompt 必须命中缓存"
    assert calls["n"] == 1, "命中后不得再次编码"

    c = LVI._wan_embeds_cached("/m/wan", "a dog", 8)
    assert c == ("pe-2", "ne-2") and calls["n"] == 2


def test_embeds_cache_lru_capacity_is_4(monkeypatch):
    monkeypatch.setattr(LVI, "_encode_wan_prompts",
                        lambda model_path, prompt, negative, vram_gb: (prompt, prompt))
    LVI._WAN_EMBEDS_CACHE.clear()
    for i in range(6):
        LVI._wan_embeds_cached("/m/wan", "p%d" % i, 8)
    assert len(LVI._WAN_EMBEDS_CACHE) == 4, "LRU 上限 4，避免无界增长"
