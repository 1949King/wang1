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


# ── ⑤ 用法感知显存策略（首图后热提升 -26%）────────────────────────────
def test_can_promote_threshold():
    assert DIF.can_promote(1.5) is True
    assert DIF.can_promote(1.2) is True            # 恰好等于 reserve 也算够
    assert DIF.can_promote(0.9) is False
    assert DIF.can_promote(0.0) is False           # SDXL 实测就是这个值 ⇒ 不许提升
    assert DIF.can_promote("nonsense") is False    # 非法值不猜，按不许


def test_promote_state_starts_pending():
    eng = DIF.DiffusersImageEngine()
    st = eng.promote_status()
    assert st["state"] == "pending"
    assert st["reserve_gb"] == DIF.HOT_PROMOTE_RESERVE_GB


def test_promote_disabled_by_env(monkeypatch):
    monkeypatch.setenv("SHIGUANG_HOT_PROMOTE", "0")
    eng = DIF.DiffusersImageEngine()
    eng._pipe = None
    eng._maybe_promote()
    assert eng.promote_status()["state"] == "disabled"


def test_rollback_without_pipe_is_safe():
    """回退路径不能因为没管线就抛（真实场景：提升失败时管线可能已被 to() 弄脏）。"""
    eng = DIF.DiffusersImageEngine()
    eng._pipe = None
    eng._rollback_offload("测试原因")
    st = eng.promote_status()
    assert st["state"] == "kept_offload"
    assert "测试原因" in st["note"]


def test_promotion_fits_matches_measured_reality():
    """预测判定必须与本机实测一致：SD1.5 装得下、SDXL@8GB 装不下。"""
    assert DIF.promotion_fits(3.97, 8.0) is True      # 实测整卡峰值 4.34GB
    assert DIF.promotion_fits(6.46, 8.0) is False     # 实测整卡后空闲 0.00GB
    # 同样的模型在更大显存上应该允许 ⇒ 换机器自动生效（可移植性）
    assert DIF.promotion_fits(6.46, 24.0) is True
    assert DIF.promotion_fits(0.0, 8.0) is False      # 未知权重大小不瞎提升
    assert DIF.promotion_fits("x", 8.0) is False


def test_unload_resets_promote_state():
    """换模型必须重新评估：SD1.5 提升过后再 load SDXL，状态不能残留在 promoted。"""
    eng = DIF.DiffusersImageEngine()
    eng._promote_state = "promoted"
    eng._pipe = None
    eng.unload()
    assert eng.promote_status()["state"] == "pending"
