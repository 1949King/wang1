# -*- coding: utf-8 -*-
"""显存账本（vram_ledger）测试 —— 5 分项口径锁（P0 · 2026-10-28）。

为什么这个文件的断言比一般单测更"啰嗦"
======================================
账本错的方式很特别：**错得很像对的**。
把「5 个阶段峰值之和」当峰值报出去，数字看着合理，所有「省了 X%」的结论
却会系统性偏差 —— 而且不会有任何异常提醒你。2026-10-27 的 int8 事故就是同类：
显存确实降了 43.4%，画质却崩成 5.29dB，只报峰值不报归因，等于只报结论不报依据。

所以这里锁的是**口径本身**：
  ① 5 个分项名字是契约（改名即违约）；
  ② 分项 = 阶段内增量，不可相加当峰值（回收场景必须显式暴露）；
  ③ 缺项不许冒充全量（attributed=None）；
  ④ 测不出就 None，绝不 0（0 会被读成"不占显存"）；
  ⑤ 拼错分项必须抛（静默少一项是最坏失败）；
  ⑥ K4 门槛分模态（图像 1.05 / 视频 1.10），无基线判 unknown 不判 pass。
"""
from __future__ import annotations

import inspect

import pytest

from app.core.neural import vram_ledger as VL


def _reader(samples, peaks=None):
    return VL.dict_reader(samples, peaks or [0.0])


def _full_run(peaks, samples=None, kind="image"):
    """跑完 5 个阶段的账本（每阶段起点都归零，便于精确断言）。"""
    samples = samples or [(0.0, 0.0)] * 7
    led = VL.VramLedger(_reader(samples, peaks), model_id="m", kind=kind).begin()
    for k in VL.ITEMS:
        led.enter(k)
        led.leave(k)
    return led.close()


# ─────────────────── ① 分项名字是契约 ───────────────────


def test_items_are_the_contract_names():
    """架构文档 §3 定的 5 个口径，改名会让历史账本无法对照。"""
    assert VL.ITEMS == ("weight", "activation", "cache", "decode", "encoder")


def test_result_has_one_key_per_item():
    out = _full_run([1.0, 2.0, 0.5, 1.5, 0.8])
    for k in VL.ITEMS:
        assert "%s_gb" % k in out
        assert out["%s_gb" % k] is not None


# ─────────────────── ② 分项不可相加当峰值 ───────────────────


def test_items_are_stage_increments_not_global_shares():
    """每项 = 该阶段自己的峰值增量（阶段起点归零时即阶段峰值本身）。"""
    out = _full_run([2.0, 3.0, 1.0, 2.5, 1.5])
    assert out["weight_gb"] == 2.0
    assert out["activation_gb"] == 3.0
    assert out["decode_gb"] == 2.5
    assert out["peak_gb"] == 3.0, "全局峰值 = 各阶段峰值的最大者，不是求和"


def test_reclaim_scenario_is_exposed_not_swallowed():
    """阶段间回收 ⇒ 分项之和 > 峰值。必须给 reclaim_gb 并在 notes 里说清口径。"""
    out = _full_run([2.0, 3.0, 1.0, 2.5, 1.5])
    assert out["attributed_gb"] == pytest.approx(10.0)
    assert out["peak_gb"] == 3.0
    assert out["residual_gb"] is None
    assert out["reclaim_gb"] == pytest.approx(7.0)
    assert any("不可相加" in n for n in out["notes"])


def test_no_reclaim_gives_positive_residual():
    """权重常驻（不清零）时峰值 ≈ 权重+最贵的后段 ⇒ 残差为正，不该误报回收。"""
    # begin(0) → enter weight(0) → enter activation(2.0) → leave peak 3.0
    samples = [(0.0, 0.0), (0.0, 0.0), (2.0, 2.0), (2.0, 2.0), (2.0, 2.0),
               (2.0, 2.0), (2.0, 2.0), (2.0, 2.0), (2.0, 2.0)]
    led = VL.VramLedger(_reader(samples, [2.0, 1.0, 0.5, 1.0, 0.5])).begin()
    for k in VL.ITEMS:
        led.enter(k)
        led.leave(k)
    out = led.close()
    assert out["reclaim_gb"] is None
    assert out["residual_gb"] is not None


# ─────────────────── ③④ 缺项与缺 reader ───────────────────


def test_partial_items_do_not_fake_a_total():
    """只测 3 项 ⇒ attributed 必须 None（拿部分和冒充全量是误导）。"""
    led = VL.VramLedger(_reader([(0.0, 0.0)] * 8, [1.0] * 8)).begin()
    for k in ("weight", "activation", "decode"):
        led.enter(k)
        led.leave(k)
    out = led.close()
    assert out["attributed_gb"] is None
    assert out["cache_gb"] is None and out["encoder_gb"] is None


def test_no_reader_means_none_not_zero():
    """没有 reader ⇒ 峰值 None。报 0 会被下游读成「不占显存」。"""
    out = VL.VramLedger(None).begin().close()
    assert out["peak_gb"] is None
    assert out["attributed_gb"] is None
    assert all(out["%s_gb" % k] is None for k in VL.ITEMS)


def test_reader_failure_degrades_to_none():
    class Boom:
        def snapshot(self):
            raise RuntimeError("驱动炸了")

        def peak(self):
            raise RuntimeError("驱动炸了")

        def reset_peak(self):
            pass

    out = VL.VramLedger(Boom()).begin().close()
    assert out["peak_gb"] is None


# ─────────────────── ⑤ 拼错分项必须抛 ───────────────────


@pytest.mark.parametrize("bad", ["wieght", "DECODE ", "cache2", ""])
def test_unknown_item_raises(bad):
    led = VL.VramLedger(_reader([(0.0, 0.0)] * 4)).begin()
    if bad == "DECODE ":        # 大小写与空白被归一，合法
        led.enter(bad)
    else:
        with pytest.raises(ValueError):
            led.enter(bad)


def test_leave_unknown_item_raises():
    led = VL.VramLedger(_reader([(0.0, 0.0)] * 4)).begin()
    with pytest.raises(ValueError):
        led.leave("nope")


# ─────────────────── ⑥ K4 门槛 ───────────────────


def _once(peak, kind="image"):
    led = VL.VramLedger(_reader([(0.0, 0.0)] * 4, [peak] * 4), kind=kind).begin()
    led.enter("weight")
    led.leave("weight")
    led.close()
    return led


def test_k4_image_threshold():
    ratio, verdict, why = _once(2.04).ratio_vs(2.0, kind="image")
    assert ratio == pytest.approx(1.02) and verdict == "pass"
    ratio2, verdict2, _ = _once(2.20).ratio_vs(2.0, kind="image")
    assert ratio2 == pytest.approx(1.10) and verdict2 == "over"


def test_k4_video_is_looser():
    """同一 1.10 倍：图像超限，视频通过（视频帧间波动本来就大）。"""
    led = _once(2.20)
    assert led.ratio_vs(2.0, kind="image")[1] == "over"
    assert led.ratio_vs(2.0, kind="video")[1] == "pass"


def test_k4_without_baseline_is_unknown_not_pass():
    _ratio, verdict, why = _once(2.0).ratio_vs(None)
    assert verdict == "unknown"
    assert "无法判定" in why


def test_k4_close_is_idempotent():
    """`close()` 可重复调（ratio_vs 内部会再调一次），不能重复追加 notes。"""
    out = _full_run([2.0, 3.0, 1.0, 2.5, 1.5])
    led = VL.VramLedger(_reader([(0.0, 0.0)] * 9, [2.0, 3.0, 1.0, 2.5, 1.5])).begin()
    for k in VL.ITEMS:
        led.enter(k)
        led.leave(k)
    a = led.close()
    b = led.close()
    assert a is b
    assert len(a["notes"]) == len(out["notes"])


# ─────────────────── 纪律 ───────────────────


def test_ledger_is_torch_free_at_module_level():
    src = inspect.getsource(VL)
    body = src.split('"""', 2)[-1]
    # torch 只允许出现在 torch_reader() 函数体内
    assert body.count("import torch") == 1
    assert "def torch_reader" in body


def test_ledger_does_not_decide_tier():
    """账本只记账 —— 出现档位决策就是第二个决策点，必须禁。"""
    src = inspect.getsource(VL)
    for forbidden in ("pick_memory_policy", "whole_gpu", "layer_cpu_offload"):
        assert forbidden not in src, "vram_ledger 越界做了档位决策：%s" % forbidden


def test_describe_marks_missing_as_unmeasured():
    out = VL.VramLedger(None).begin().close()
    text = VL.describe(out)
    assert "未测" in text
    assert " 0.000 GB" not in text, "缺失项不许显示成 0"
