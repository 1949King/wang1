# -*- coding: utf-8 -*-
"""资源仲裁（resource_broker）测试 —— P1 · 2026-10-28。

锁的是**四个容易悄悄错掉的判断**，不是覆盖率
=============================================
① **够就别动**。最容易被"顺手清一下"毁掉的性质：常驻缓存的价值全在"下次不用重载"，
   如果每次都先清一遍，等于把常驻改成了一次性 —— 功能没坏、只是白慢，
   不会有任何异常提示。故 `skipped` 分支必须断言"一个来源都没被碰"。

② **记账用实测，不信自报**。Ollama 自报 `size_vram=2.92GB`、实占 3.62GB（实测低估 0.70GB）。
   若账本跟着自报走，所有"腾出了多少"都会系统性偏小。
   测试里造一个"自称 1.0GB、实际腾 5.0GB"的源，断言账本是 5.0。

③ **池子不能串**。视频常驻缓存让的是**内存**（offload 权重在 CPU），LLM 让的是**显存**。
   叫视频缓存腾显存不只是无效，还会让"腾了却没用"看起来像"腾了"。

④ **让位失败不许阻断**。这是优化不是前提：任何异常都只能变成 `ok=False` + note，
   绝不能把异常抛给正在加载权重的调用方。

全部用注入的假来源，不碰真显卡 —— 真机验证在 `scripts/verify_broker.py`（手动跑）。
"""
from __future__ import annotations

import pytest

from app.core.neural import resource_broker as RB


@pytest.fixture(autouse=True)
def _fallback_pool(monkeypatch):
    """把池子读数换成可控的假值（真显存不该进单测：机器不同结果就不同）。"""
    state = {"vram": 2.0, "ram": 8.0}

    def _fake_read(pool):
        v = state.get(pool)
        return v, ({pool: v} if v is not None else {})

    monkeypatch.setattr(RB, "read_pool", _fake_read)
    monkeypatch.setattr(RB, "_POOL_STATE", state, raising=False)
    yield state
    RB.reset_sources()


@pytest.fixture(autouse=True)
def _broker_on(monkeypatch):
    monkeypatch.delenv("SHIGUANG_BROKER", raising=False)


def _source(name, pool=RB.POOL_VRAM, cost=10.0, frees=2.0, est=None,
            raise_exc=None, available=True):
    """造一个假来源：让位后把池子推进 `frees` GB。"""
    calls = []

    def _release(reason):
        calls.append(reason)
        if raise_exc is not None:
            raise raise_exc
        state = RB._POOL_STATE
        cur = state.get(pool) or 0.0
        state[pool] = cur + frees
        return "fake-return"

    src = RB.ReclaimSource(
        name=name, pool=pool, cost_s=cost, release=_release,
        probe=(lambda: est) if est is not None else None,
        available=(lambda: available),
    )
    # ReclaimSource 是 frozen，不能挂字段 —— 调用记录由闭包捕获后单独返回
    return src, calls


# ══════════════════════════════════════════════════════════════════
# ① 够就别动
# ══════════════════════════════════════════════════════════════════

def test_enough_resources_skips_without_touching_any_source(monkeypatch):
    """资源本来就够 ⇒ 一个来源都不许碰（常驻收益不能被"顺手清一下"毁掉）。"""
    src, calls = _source("a", frees=99.0)
    monkeypatch.setattr(RB, "_SOURCES", [src])

    dec = RB.ensure_capacity(1.0)        # free=2.0，need×1.08=1.08 ⇒ 够

    assert dec.action == "skipped"
    assert dec.ok is True
    assert calls == [], "够用时不该调用任何 release"
    assert dec.reclaimed == []


def test_safety_margin_can_flip_skip_into_release(monkeypatch):
    """同一个 need，安全余量不同结论不同 —— 证明 safety 真的参与判定。"""
    src, calls = _source("a", frees=2.0)
    monkeypatch.setattr(RB, "_SOURCES", [src])

    # free=2.0；need=1.9 ⇒ 1.9×1.08=2.052 > 2.0 ⇒ 差一点点，要动手
    dec = RB.ensure_capacity(1.9)
    assert dec.action == "released"
    assert len(calls) == 1

    # 关掉余量 ⇒ 1.9×1.0 < 2.0 ⇒ 不动
    RB._POOL_STATE["vram"] = 2.0
    calls.clear()
    dec2 = RB.ensure_capacity(1.9, safety=1.0)
    assert dec2.action == "skipped"
    assert calls == []


# ══════════════════════════════════════════════════════════════════
# ② 记账用实测，不信自报
# ══════════════════════════════════════════════════════════════════

def test_accounting_uses_measured_delta_not_self_report(monkeypatch):
    """源"自称 1.0GB"但实际腾了 5.0GB ⇒ 账本必须是 5.0。

    对应真机事实：Ollama 自报 size_vram 2.92GB，实测 3.62GB（低估 0.70GB）。
    """
    src, _ = _source("liar", frees=5.0, est=1.0)
    monkeypatch.setattr(RB, "_SOURCES", [src])

    dec = RB.ensure_capacity(6.0)         # free=2.0，需要 6.48

    assert dec.action == "released"
    assert dec.freed_gb == pytest.approx(5.0)
    rec = dec.reclaimed[0]
    assert rec.estimated_gb == 1.0        # 估算如实留下
    assert rec.actual_gb == pytest.approx(5.0)   # 记账用实测
    assert rec.bias_gb == pytest.approx(4.0)     # 偏差可见，不被抹平


def test_source_return_value_goes_to_note_not_ledger(monkeypatch):
    """源返回什么都只进 note，不参与记账。"""
    src, _ = _source("a", frees=3.0)
    monkeypatch.setattr(RB, "_SOURCES", [src])

    dec = RB.ensure_capacity(4.0)
    assert "fake-return" in dec.reclaimed[0].note
    assert dec.freed_gb == pytest.approx(3.0)


def test_probe_absent_keeps_estimate_none(monkeypatch):
    """没有 probe 的来源不许编一个估算值（None 就是 None）。"""
    src, _ = _source("a", frees=3.0)      # est=None
    monkeypatch.setattr(RB, "_SOURCES", [src])

    dec = RB.ensure_capacity(4.0)
    assert dec.reclaimed[0].estimated_gb is None
    assert dec.reclaimed[0].bias_gb is None    # 缺一边就不做差


# ══════════════════════════════════════════════════════════════════
# ③ 池子不能串 / 代价升序
# ══════════════════════════════════════════════════════════════════

def test_pool_isolation_vram_request_never_touches_ram_source(monkeypatch):
    """申请显存时，内存侧来源一次都不许被调用。"""
    ram_src, ram_calls = _source("ram_only", pool=RB.POOL_RAM, frees=99.0)
    vram_src, vram_calls = _source("vram_only", pool=RB.POOL_VRAM, frees=1.0)
    monkeypatch.setattr(RB, "_SOURCES", [ram_src, vram_src])

    dec = RB.ensure_capacity(2.5, pool=RB.POOL_VRAM)

    assert ram_calls == [], "让内存侧腾显存是无意义动作"
    assert len(vram_calls) == 1
    assert dec.action == "released"


def test_ram_pool_releases_ram_sources(monkeypatch):
    ram_src, ram_calls = _source("ram_only", pool=RB.POOL_RAM, frees=4.0)
    vram_src, vram_calls = _source("vram_only", pool=RB.POOL_VRAM, frees=99.0)
    monkeypatch.setattr(RB, "_SOURCES", [ram_src, vram_src])
    RB._POOL_STATE["ram"] = 1.0

    dec = RB.ensure_capacity(4.0, pool=RB.POOL_RAM)

    assert len(ram_calls) == 1
    assert vram_calls == []
    assert dec.pool == RB.POOL_RAM


def test_cheapest_source_released_first(monkeypatch):
    """便宜的先让位（LLM 重载 5.5s < 视频管线重载 40s）。"""
    expensive, exp_calls = _source("expensive", cost=40.0, frees=5.0)
    cheap, cheap_calls = _source("cheap", cost=5.5, frees=5.0)
    monkeypatch.setattr(RB, "_SOURCES", [expensive, cheap])   # 故意乱序登记

    dec = RB.ensure_capacity(2.5)         # free=2.0，需要 2.70 ⇒ 必须让位

    assert len(cheap_calls) == 1
    assert exp_calls == [], "够用了就不该再动贵的那个"
    assert dec.reclaimed[0].name == "cheap"


def test_stops_as_soon_as_enough(monkeypatch):
    """够了立刻停手，不顺手把剩下的也关了（省得下次白等重载）。"""
    a, a_calls = _source("a", cost=1.0, frees=5.0)
    b, b_calls = _source("b", cost=2.0, frees=5.0)
    c, c_calls = _source("c", cost=3.0, frees=5.0)
    monkeypatch.setattr(RB, "_SOURCES", [a, b, c])

    dec = RB.ensure_capacity(2.5)         # free=2→7，一次就够

    assert len(a_calls) == 1
    assert b_calls == [] and c_calls == []
    assert len(dec.reclaimed) == 1


# ══════════════════════════════════════════════════════════════════
# ④ 失败不阻断
# ══════════════════════════════════════════════════════════════════

def test_release_exception_does_not_propagate(monkeypatch):
    """单个来源让位抛异常 ⇒ 不向上抛，如实记账，继续试下一个。"""
    bad, _ = _source("bad", cost=1.0, raise_exc=RuntimeError("Ollama 挂了"))
    good, good_calls = _source("good", cost=2.0, frees=5.0)
    monkeypatch.setattr(RB, "_SOURCES", [bad, good])

    dec = RB.ensure_capacity(2.5)         # 不许抛

    assert dec.action == "released"
    assert dec.reclaimed[0].ok is False
    assert "Ollama 挂了" in dec.reclaimed[0].note
    assert len(good_calls) == 1, "坏源之后要继续试好源"


def test_all_sources_fail_returns_insufficient_not_exception(monkeypatch):
    bad, _ = _source("bad", cost=1.0, raise_exc=RuntimeError("boom"))
    monkeypatch.setattr(RB, "_SOURCES", [bad])

    dec = RB.ensure_capacity(5.0)

    assert dec.action == "insufficient"
    assert dec.ok is False                # 调用方据此知道"别抱希望"，但仍可尝试
    assert "仍差" in dec.note


def test_unavailable_source_is_skipped_without_release(monkeypatch):
    """源声明自己不可用（如 Ollama 没起）⇒ 连 release 都不调。"""
    src, calls = _source("not_now", frees=9.0, available=False)
    monkeypatch.setattr(RB, "_SOURCES", [src])

    dec = RB.ensure_capacity(5.0)
    assert calls == []
    assert dec.action == "insufficient"


def test_probe_exception_does_not_block_release(monkeypatch):
    """预估失败只影响 note，不影响让位本身。"""
    src = RB.ReclaimSource(
        name="noisy", pool=RB.POOL_VRAM, cost_s=1.0,
        release=lambda reason: None,
        probe=lambda: (_ for _ in ()).throw(RuntimeError("probe 炸了")),
        available=None,
    )
    monkeypatch.setattr(RB, "_SOURCES", [src])
    monkeypatch.setattr(RB, "read_pool", lambda pool: (2.0, {"vram": 2.0}))

    dec = RB.ensure_capacity(5.0)         # 不许抛
    assert dec.reclaimed[0].estimated_gb is None


def test_unreadable_pool_is_insufficient_not_crash(monkeypatch):
    """读不到显存 ⇒ 判 insufficient 并说明原因，绝不虚报"够了"。"""
    monkeypatch.setattr(RB, "read_pool", lambda pool: (None, {"torch": None, "smi": None}))

    dec = RB.ensure_capacity(3.0)

    assert dec.action == "insufficient"
    assert dec.ok is False
    assert "读不到" in dec.note
    assert dec.free_before_gb is None


# ══════════════════════════════════════════════════════════════════
# 开关与来源表
# ══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("val", ["off", "0", "false", "no", ""])
def test_switch_off_disables_arbitration(monkeypatch, val):
    """`SHIGUANG_BROKER=off` ⇒ 退化为 P0 之前：不探测、不让位。"""
    src, calls = _source("a", frees=9.0)
    monkeypatch.setattr(RB, "_SOURCES", [src])
    monkeypatch.setenv("SHIGUANG_BROKER", val)

    dec = RB.ensure_capacity(5.0)

    assert dec.action == "disabled"
    assert dec.ok is True                 # 关闭不是失败，是"不做这件事"
    assert calls == []
    assert dec.free_before_gb is None     # 连探测都没做


def test_default_on_when_unset(monkeypatch):
    monkeypatch.delenv("SHIGUANG_BROKER", raising=False)
    assert RB.enabled() is True


def test_register_source_sorts_by_cost(monkeypatch):
    RB.reset_sources()
    RB.register_source(RB.ReclaimSource(
        name="zzz", pool=RB.POOL_VRAM, cost_s=0.5, release=lambda r: None))
    names = [s.name for s in RB.get_sources()]
    assert names[0] == "zzz", "登记后仍须按代价升序"
    costs = [s.cost_s for s in RB.get_sources()]
    assert costs == sorted(costs)


def test_builtin_sources_declare_correct_pools():
    """内置来源的池子必须对：视频常驻缓存让的是**内存**，不是显存。"""
    by_name = {s.name: s for s in RB.default_sources()}
    assert by_name["video_pipe_cache"].pool == RB.POOL_RAM
    assert by_name["ollama"].pool == RB.POOL_VRAM
    # LLM 必须先让位（重载 5.5s ≪ 视频管线 40s）
    assert by_name["ollama"].cost_s < by_name["video_pipe_cache"].cost_s


# ══════════════════════════════════════════════════════════════════
# Decision 自身语义
# ══════════════════════════════════════════════════════════════════

def test_decision_freed_gb_is_zero_when_readings_missing():
    """读数缺失时 freed 是 0.0，不是 None 也不是编的数。"""
    dec = RB.Decision(action="released", pool=RB.POOL_VRAM, need_gb=1.0,
                      free_before_gb=None, free_after_gb=5.0)
    assert dec.freed_gb == 0.0


def test_decision_describe_is_single_line_and_mentions_action():
    dec = RB.Decision(action="released", pool=RB.POOL_VRAM, need_gb=3.0,
                      free_before_gb=2.0, free_after_gb=6.0)
    line = dec.describe()
    assert "\n" not in line
    assert "released" in line and "pool=vram" in line
