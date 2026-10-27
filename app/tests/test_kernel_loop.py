# -*- coding: utf-8 -*-
"""去噪循环测试 —— P2 · 2026-10-28。

循环是**全仓唯一允许写 for-step 的地方**（H1/H2），所以它的测试不能用真模型：
一旦依赖真权重，这些测试就只会在有卡的机器上跑，最后必然被 `-k "not gpu"` 跳过。

这里用纯 Python 的假 adapter（数字加减），把四件事的**顺序**与**取反**锁死：

① `prepare → forward → guide → step` 顺序不能换。换成"先 step 再 guide"在某些
   调度器上仍能出图（只是慢半拍），人眼看不出，PSNR 也不会报警。
② 取消必须在**步首**检查。放步尾会让最后一步"跑完了还被判取消"，
   出现"结果有效却返回 cancelled"的矛盾态。
③ `step_count` 是**已完成步数**，不是"执行到第几步"。差 1 会让进度条永远差一格。
④ 循环必须处在推理态（`grad_mode.inference()`）。少了不报错，只涨显存 + 解码炸栈。
"""
from __future__ import annotations

from typing import Any, List

import pytest

from app.core.neural.kernel import grad_mode as GRAD
from app.core.neural.kernel import loop as LOOP
from app.core.neural.kernel.contracts import RunState
from app.core.neural.kernel.hooks import CancelToken, Hooks, NullHooks, StepEvent


class FakeAdapter:
    """纯 Python 假适配器：四件事都写进 call log，值用数字加减。"""

    def __init__(self, log: List[str], grad_seen: List[bool]) -> None:
        self.log = log
        self.grad_seen = grad_seen
        self.prepared = 0

    def prepare_step(self, latents, t, state):
        self.log.append("prepare:%s" % t)
        return {"model_input": latents + 1}

    def forward(self, prepared, state):
        # 循环里必须是推理态（不建图）
        self.grad_seen.append(GRAD.enabled())
        self.log.append("forward:%s" % prepared["model_input"])
        return prepared["model_input"] * 2

    def guide(self, noise, prepared, state):
        self.log.append("guide:%s" % noise)
        return noise + 0.5

    def step(self, noise, t, prepared, state):
        self.log.append("step:%s" % noise)
        return noise


def _state(n: int) -> RunState:
    return RunState(timesteps=list(range(n)), latents=0)


# ══════════════════════════════════════════════════════════════════
# 顺序与计数
# ══════════════════════════════════════════════════════════════════

def test_four_actions_run_in_order_each_step():
    log: List[str] = []
    ad = FakeAdapter(log, [])
    out = LOOP.denoise(ad, _state(2))

    # latents 从 0 开始，每步 +1 → ×2 → +0.5：
    #   步0：0 →(prepare) 1 →(forward) 2 →(guide) 2.5 →(step) 2.5
    #   步1：2.5 → 3.5 → 7.0 → 7.5 → 7.5
    assert log == [
        "prepare:0", "forward:1", "guide:2", "step:2.5",
        "prepare:1", "forward:3.5", "guide:7.0", "step:7.5",
    ], log
    assert out.latents == 7.5
    assert out.step_count == 2
    assert out.cancelled is False


def test_step_count_is_completed_steps():
    log: List[str] = []
    out = LOOP.denoise(FakeAdapter(log, []), _state(5))
    assert out.step_count == 5
    assert out.state.steps == 5


def test_zero_steps_is_not_an_error():
    """空时间轴（例如 strength=0）不炸，返回 done 而不是 IndexError。"""
    out = LOOP.denoise(FakeAdapter([], []), _state(0))
    assert out.cancelled is False and out.step_count == 0


# ══════════════════════════════════════════════════════════════════
# 取消（步首判定）
# ══════════════════════════════════════════════════════════════════

def test_cancel_before_first_step_finishes_nothing():
    tok = CancelToken()
    tok.cancel()
    log: List[str] = []
    out = LOOP.denoise(FakeAdapter(log, []), _state(4), hooks=Hooks(cancel_token=tok))
    assert out.cancelled is True
    assert out.step_count == 0
    assert log == [], "取消后不许再执行任何一步"
    assert out.latents == 0, "未完成的运行必须原样返回输入潜变量"


def test_cancel_takes_effect_at_next_step_head():
    """第 2 步跑完时置位 ⇒ 只完成 2 步，且返回的 latents 是第 2 步的结果。"""
    tok = CancelToken()
    log: List[str] = []
    seen: List[int] = []

    class _Hooks(Hooks):
        def after_step(self, ev: StepEvent, latents: Any) -> None:
            seen.append(ev.index)
            if ev.index == 1:
                tok.cancel()

    out = LOOP.denoise(FakeAdapter(log, []), _state(6), hooks=_Hooks(cancel_token=tok))
    assert out.cancelled is True
    assert out.step_count == 2
    assert seen == [0, 1], "第 2 步之后不该再有 after_step"
    # 两步的结果：0→2.5→(2.5+1)*2+0.5=7.5
    assert out.latents == 7.5
    assert out.state.latents == 7.5


def test_finished_called_with_ok_flag():
    calls: List[tuple] = []

    class _Hooks(NullHooks):
        def finished(self, ok: bool, note: str = "") -> None:
            calls.append((ok, note))

    LOOP.denoise(FakeAdapter([], []), _state(2), hooks=_Hooks())
    assert len(calls) == 1
    assert calls[0][0] is True


def test_finished_reports_cancel():
    """取消也必须走到 `finished(ok=False, 原因)`：界面靠这一条把进度条收掉。"""
    calls: List[tuple] = []

    class _Hooks(NullHooks):
        def __init__(self, token):
            self.cancel_token = token

        def cancelled(self) -> bool:
            return self.cancel_token.is_set()

        def finished(self, ok: bool, note: str = "") -> None:
            calls.append((ok, note))

    tok = CancelToken()
    tok.cancel()
    LOOP.denoise(FakeAdapter([], []), _state(2), hooks=_Hooks(tok))
    assert calls == [(False, "已取消（完成 0/2 步）")], calls


# ══════════════════════════════════════════════════════════════════
# 推理态
# ══════════════════════════════════════════════════════════════════

def test_loop_runs_without_grad():
    """每步前向都发生在推理态。少了它：显存按步数翻倍，解码处 `numpy()` 直接抛。"""
    grad_seen: List[bool] = []
    LOOP.denoise(FakeAdapter([], grad_seen), _state(3))
    assert grad_seen == [True, True, True], "循环内必须处于不建图状态"


def test_grad_state_restored_after_loop():
    """循环结束后恢复调用方的梯度状态：不能把整进程永久设成 no_grad。"""
    import torch

    assert torch.is_grad_enabled() is True
    LOOP.denoise(FakeAdapter([], []), _state(1))
    assert torch.is_grad_enabled() is True


# ══════════════════════════════════════════════════════════════════
# 打点
# ══════════════════════════════════════════════════════════════════

def test_hooks_collect_steps_off_by_default():
    h = Hooks()
    LOOP.denoise(FakeAdapter([], []), _state(3), hooks=h)
    assert h.events == [], "默认不收集：每步做张量统计会拖慢循环"


def test_instrument_mark_step_called_per_step():
    class _Ins:
        def __init__(self) -> None:
            self.rows: List[dict] = []

        def mark_step(self, row: dict) -> None:
            self.rows.append(row)

    ins = _Ins()
    LOOP.denoise(FakeAdapter([], []), _state(3), instrument=ins)
    assert [r["index"] for r in ins.rows] == [0, 1, 2]
    assert all("elapsed_ms" in r and "timestep" in r for r in ins.rows)


def test_progress_callback_receives_done_and_total():
    got: List[tuple] = []
    h = Hooks(progress=lambda done, total, note: got.append((done, total)))
    LOOP.denoise(FakeAdapter([], []), _state(4), hooks=h)
    assert (1, 4) in got and (4, 4) in got, got
    assert got[-1] == (4, 4)


def test_progress_exception_does_not_break_generation():
    """UI 回调抛异常不能中断出图（与既有 progress_cb 纪律一致）。"""
    def _boom(done, total, note):
        raise RuntimeError("界面已销毁")

    h = Hooks(progress=_boom)
    out = LOOP.denoise(FakeAdapter([], []), _state(3), hooks=h)
    assert out.step_count == 3 and out.cancelled is False


# ══════════════════════════════════════════════════════════════════
# 契约体检
# ══════════════════════════════════════════════════════════════════

def test_check_step_order_passes_real_adapter():
    assert LOOP.check_step_order(FakeAdapter([], [])) is None


@pytest.mark.parametrize("missing", ["prepare_step", "forward", "guide", "step"])
def test_check_step_order_reports_each_missing_method(missing):
    """四个动作**逐个**都要能报出来 —— 只测一个等于只证四分之一。"""
    class _Half:
        def prepare_step(self, *a, **k): ...
        def forward(self, *a, **k): ...
        def guide(self, *a, **k): ...
        def step(self, *a, **k): ...

    obj = _Half()
    delattr(_Half, missing)
    assert missing in (LOOP.check_step_order(obj) or "")


def test_adapter_exception_propagates_to_caller():
    """循环不吞异常：降级决策归 engine（它要写 rejected_reason），循环只负责跑。"""
    class _Boom(FakeAdapter):
        def forward(self, prepared, state):
            raise RuntimeError("权重崩了")

    with pytest.raises(RuntimeError, match="权重崩了"):
        LOOP.denoise(_Boom([], []), _state(2))
