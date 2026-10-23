# -*- coding: utf-8 -*-
"""质量档位（V4.46.8）：档位解析 + LCM 诚实失败 + 档位表自洽。

为什么测这些：档位表把「实测标定」写成了代码常量，一旦有人手滑改成「fast 用 20 步」
或「LCM 用 cfg7.5」，就再也没人知道它坏了 —— 所以表本身也要有断言。
"""
import pytest

import app.core.neural.diffusers_image as DIF


# ── ① 档位表自洽 ──────────────────────────────────────────────────────
def test_preset_table_is_self_consistent():
    assert set(DIF.QUALITY_PRESETS) == {"sd15-t2i", "sdxl-t2i"}
    for mid, table in DIF.QUALITY_PRESETS.items():
        assert set(table) >= {"final", "high", "fast"}, mid
        for name, row in table.items():
            assert row["steps"] > 0, f"{mid}/{name} 步数必须为正"
            assert row["cfg"] > 0, f"{mid}/{name} cfg 必须为正"
            assert row["sampler"] in ("default", "dpm", "lcm"), f"{mid}/{name} 采样器非法"
        # final 必须是满步数（不许偷偷降质）
        assert table["final"]["steps"] == 20, f"{mid} 的 final 被改小了"
        # fast 必须比 high 快（步数更少）
        assert table["fast"]["steps"] <= table["high"]["steps"], f"{mid} fast 反而不更快"


def test_lcm_preset_uses_cfg_one():
    """LCM 必须 cfg=1.0；cfg>1 会破坏 LCM 语义（实测过 cfg2 明显变差）。"""
    for mid, table in DIF.QUALITY_PRESETS.items():
        if table["fast"]["sampler"] == "lcm":
            assert table["fast"]["cfg"] == 1.0, f"{mid} 的 LCM 档 cfg 必须 1.0"


# ── ② 解析函数 ────────────────────────────────────────────────────────
def test_resolve_preset_known():
    r = DIF.resolve_preset("sdxl-t2i", "fast")
    assert r["preset"] == "fast"
    assert r["steps"] == 8 and r["cfg"] == 1.0 and r["sampler"] == "lcm"


def test_resolve_preset_empty_means_no_intervention():
    r = DIF.resolve_preset("sdxl-t2i", "")
    assert r["preset"] == "" and r["steps"] == 0


def test_resolve_preset_unknown_falls_back_to_final():
    r = DIF.resolve_preset("sdxl-t2i", "turbo-ultra")
    assert r["preset"] == "final" and r["steps"] == 20


# ── ③ LCM 诚实失败（不触 GPU、不 import peft）────────────────────────
def test_lcm_status_without_weights(monkeypatch):
    """用独立实例 + 打桩，避免碰全局单例与真磁盘遍历。"""
    eng = DIF.DiffusersImageEngine()
    monkeypatch.setattr(eng, "_find_lcm_lora", lambda: "", raising=False)
    st = eng.lcm_status()
    assert st["lora_found"] is False
    assert st["usable"] is False


def test_enable_lcm_without_weights_is_honest(monkeypatch):
    eng = DIF.DiffusersImageEngine()
    monkeypatch.setattr(eng, "_find_lcm_lora", lambda: "", raising=False)
    ok, why = eng.enable_lcm("sdxl-t2i")
    assert ok is False
    assert "未找到" in why


# ── ④ 采样器切换在无管线时必须安全 ───────────────────────────────────
def test_apply_sampler_noop_without_pipe():
    eng = DIF.get_diffusers_image_engine()
    eng._pipe = None
    eng._apply_sampler("dpm")      # 不应抛
    eng._apply_sampler("lcm")
    eng._apply_sampler("default")
