# -*- coding: utf-8 -*-
"""`video_gen` 与内核的接线（离线：假 pipe + 假内核，不加载权重）。

## 这里守的是三件"只在生产路径才会发生"的事

1. **回退必须还原随机数状态**：内核跑了几步才失败时，generator 已经被
   `encode()`（噪声增广）与 `init_latents()`（初始潜变量）消耗过。
   如果不还原就回退 stock，同 seed 得到的片子与"干净跑一次 stock"**不一样** ——
   而回执里只写"回退了"，没人会想到噪声序列被动过。
2. **回退必须带上原因**：`kernel.rejected_reason` 是用户/前端唯一能看见
   "这次为什么没用内核"的地方。缺了它，静默回退就成立了。
3. **非目标族不许硬塞**：`arch` 为空（未来 Wan 等）时直接走 stock，
   不做"试试看内核认不认识"这种探测 —— 那会把族判断散到两处。
"""
from __future__ import annotations

import types

import pytest

torch = pytest.importorskip("torch")

from app.core.neural import video_gen as VG


class _Pipe:
    """stock 替身：记录它从 generator 里拿到的第一批噪声（用来判断状态是否被还原）。"""

    def __init__(self) -> None:
        self.seen_noise = None
        self.calls = 0

    def __call__(self, **kw):
        self.calls += 1
        gen = kw.get("generator")
        self.seen_noise = torch.randn(4, generator=gen) if gen is not None else None
        # 形如上游：`frames` 是 `[batch][frame]`，调用方取 `.frames[0]`
        return types.SimpleNamespace(frames=[["f0", "f1"]])


def _engine(pipe):
    eng = VG.VideoGenEngine()
    eng._pipe = pipe
    return eng


def _call(eng, *, arch="svd", generator=None):
    return eng._run_with_kernel(
        spec={"repo": "stabilityai/stable-diffusion-video"},
        arch=arch, kw={"max_guidance_scale": 3.0, "min_guidance_scale": 1.0,
                       "noise_aug_strength": 0.02, "generator": generator},
        image_path="x.png", n_frames=4, n_steps=2, n_mb=80, fps=7,
        chunk=1, width=1024, height=576, generator=generator, seed=7,
    )


def _fail_report(reason="测试：内核拒绝"):
    from app.core.neural.kernel.contracts import KernelReport

    return {"ok": False, "image": None, "frames": None,
            "report": KernelReport(used=False, family="svd", rejected_reason=reason),
            "message": reason, "warnings": [], "breakdown": {}, "cancelled": False}


def test_fallback_restores_generator_state(monkeypatch):
    """内核消耗过随机数后回退，stock 必须拿到**与干净跑一次相同**的噪声序列。"""
    from app.core.neural.kernel import engine as KE

    def _consume_then_fail(**kw):
        torch.randn(16, generator=kw["generator"])      # 模拟噪声增广 + 初始 latents
        return _fail_report()

    monkeypatch.setattr(KE, "run", _consume_then_fail)

    baseline = torch.randn(4, generator=torch.manual_seed(7))
    pipe = _Pipe()
    frames, report, warnings = _call(_engine(pipe), generator=torch.manual_seed(7))

    assert frames == ["f0", "f1"], "stock 路径取 `.frames[0]`"
    assert pipe.seen_noise is not None
    assert torch.equal(pipe.seen_noise, baseline), (
        "回退后 stock 拿到的噪声与干净跑一次不同 ⇒ 同 seed 不可复现")


def test_fallback_keeps_rejected_reason(monkeypatch):
    """回退不许静默：原因必须一路带到回执。"""
    from app.core.neural.kernel import engine as KE

    monkeypatch.setattr(KE, "run", lambda **kw: _fail_report("族 svd 未验收"))
    _frames, report, _w = _call(_engine(_Pipe()))
    assert report["used"] is False
    assert "未验收" in report["rejected_reason"]


def test_kernel_success_skips_stock(monkeypatch):
    """内核成功时**不许**再调 stock（否则等于白跑两遍）。"""
    from app.core.neural.kernel import engine as KE

    monkeypatch.setattr(KE, "run", lambda **kw: {
        "ok": True, "image": None, "frames": ["k0", "k1"],
        "report": KE.KernelReport(used=True, family="svd", loop_owner="shiguang"),
        "message": "ok", "warnings": ["note"], "breakdown": {}, "cancelled": False,
    })
    pipe = _Pipe()
    frames, report, warnings = _call(_engine(pipe))
    assert frames == ["k0", "k1"]
    assert pipe.calls == 0, "内核已经产出结果，不该再跑一遍 stock"
    assert report["used"] is True
    assert warnings == ["note"], "内核的 note 必须原样带回（静默吞掉 = 隐藏降级）"


def test_non_target_family_goes_straight_to_stock(monkeypatch):
    """`arch` 为空（未接内核的族）⇒ 直接走 stock，不探测、不留 report。"""
    from app.core.neural.kernel import engine as KE

    called = {"n": 0}

    def _boom(**kw):
        called["n"] += 1
        raise AssertionError("非目标族不该调用内核")

    monkeypatch.setattr(KE, "run", _boom)
    pipe = _Pipe()
    frames, report, warnings = _call(_engine(pipe), arch="")
    assert frames == ["f0", "f1"]
    assert called["n"] == 0
    assert report == {} and warnings == []


def test_wiring_exception_degrades_to_stock(monkeypatch):
    """接线本身抛异常也必须降级为回退（不能让用户的生成失败）。"""
    from app.core.neural.kernel import engine as KE

    def _boom(**kw):
        raise RuntimeError("接线炸了")

    monkeypatch.setattr(KE, "run", _boom)
    pipe = _Pipe()
    frames, report, _w = _call(_engine(pipe))
    assert frames == ["f0", "f1"]
    assert report["used"] is False and "接线炸了" in report["rejected_reason"]
