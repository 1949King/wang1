# -*- coding: utf-8 -*-
"""自适应标定的自洽性测试（对应 `docs/design/自适应标定设计.md` AC-1~AC-11）。

这些测试**不碰 GPU、不 import torch** —— 标定的 GPU 部分靠 probe_run 注入，
所以本文件全用假 probe，秒级跑完。
真机行为由 `verify_torchada_coverage.py --run` 与后续 benchmark 覆盖。

守的是「这套逻辑会不会骗人」：
  · 8G 门槛真的挡住（AC-7）
  · 阶梯真的在第一个失败处停下（D-A2）
  · 失败真的不炸（AC-4）
  · 外推真的不冒充实测（AC-8）
  · torch 版本变了档案真的失效（AC-6）
"""
from __future__ import annotations

import json

import pytest

from app.core.neural import calibration as CAL


# ── 夹具 ───────────────────────────────────────────────────────────────────
def prof_nvidia(vram=8.0, arch="sm89"):
    return {"vendor": "nvidia", "arch": arch, "vram_gb": vram,
            "name": "Fake NVIDIA", "device_id": "nvidia:%s" % arch}


def prof_small(vram=6.0):
    return {"vendor": "nvidia", "arch": "sm86", "vram_gb": vram,
            "name": "Small", "device_id": "nvidia:sm86"}


def prof_unknown(vram=12.0):
    return {"vendor": "lisuan", "arch": "truegpu", "vram_gb": vram,
            "name": "Lisuan", "device_id": "lisuan:truegpu"}


def prof_cpu():
    return {"vendor": "cpu", "arch": "cpu", "vram_gb": 0.0, "device_id": "cpu:cpu"}


class FakeProbe:
    """可编排的假 probe：profile 决定每个档位的结果。"""

    def __init__(self, plan):
        # plan: {mode: ("ok", peak, secs) | ("fail", err)}
        self.plan = plan
        self.calls = []

    def __call__(self, mode, px):
        self.calls.append((mode, px))
        v = self.plan.get(mode)
        if v is None:
            return CAL.Trial(mode=mode, ok=False, error="not planned")
        if v[0] == "fail":
            return CAL.Trial(mode=mode, ok=False, error=v[1])
        if v[0] == "raise":
            raise RuntimeError(v[1])
        return CAL.Trial(mode=mode, ok=True, peak_gb=v[1], seconds=v[2])


@pytest.fixture()
def store(tmp_path):
    return CAL.CalibrationStore(str(tmp_path / "calib.json"))


# ── 1. 阶梯与 memory_policy 的一致性（双向守卫）────────────────────────────
def test_ladder_matches_memory_policy():
    """LANE 顺序必须与 memory_policy 的 ACTIVE_MODES 同集合，且保守在前。"""
    from app.core.neural import memory_policy as MP

    assert set(CAL.LADDER) == set(MP.ACTIVE_MODES), (
        "标定阶梯与 memory_policy.ACTIVE_MODES 不一致：%s vs %s"
        % (sorted(CAL.LADDER), sorted(MP.ACTIVE_MODES))
    )
    # 阶梯首项必须是最保守的逐层卸载，末项必须是整卡
    assert CAL.LADDER[0] == MP.MODE_LAYER_CPU_OFFLOAD
    assert CAL.LADDER[-1] == MP.MODE_WHOLE_GPU


# ── 2. 准入（AC-7）─────────────────────────────────────────────────────────
def test_admit_rejects_below_threshold():
    ok, why = CAL.admit(prof_small(6.0))
    assert ok is False
    assert "8GB" in why or "8" in why
    assert "6.0GB" in why  # 必须说清当前多少，不能只说不行


def test_admit_accepts_exactly_8gb():
    ok, why = CAL.admit(prof_nvidia(8.0))
    assert ok is True, why


def test_admit_rejects_cpu():
    ok, why = CAL.admit(prof_cpu())
    assert ok is False
    assert "CPU" in why or "cpu" in why


def test_admit_nvidia_is_verified_kind():
    ok, why = CAL.admit(prof_nvidia())
    assert ok and "未验证" not in why


def test_admit_unknown_backend_still_admitted_but_flagged():
    """砺算这类：显存够就准入，但必须提示「未验证」，不能假装可信。"""
    ok, why = CAL.admit(prof_unknown())
    assert ok is True
    assert "未验证" in why or "unverified" in why


def test_unknown_backend_entry_marked_unverified(store):
    cal = CAL.Calibrator(store, prof_unknown(), probe_run=FakeProbe({
        CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 5.0),
    }))
    e = cal.calibrate("some-model")
    assert e is not None
    assert e.verdict == CAL.VERDICT_UNVERIFIED, "未知后端不得标 verified"


# ── 3. 阶梯裁决（D-A2）─────────────────────────────────────────────────────
def test_decide_picks_fastest_among_success():
    """全部成功时按**实测耗时**选，不是盲取最后一个。"""
    trials = [
        CAL.Trial(CAL.MODE_LAYER_CPU_OFFLOAD, True, 3.0, 9.0),
        CAL.Trial(CAL.MODE_SEQUENTIAL_OFFLOAD, True, 4.0, 6.0),
        CAL.Trial(CAL.MODE_MODEL_OFFLOAD, True, 5.0, 4.0),
    ]
    chosen, rej = CAL.decide(trials)
    assert chosen is not None and chosen.mode == CAL.MODE_MODEL_OFFLOAD
    assert rej == []


def test_decide_does_not_assume_aggressive_is_faster():
    """★ 项目实测反例守卫：whole_gpu 单张比 offload 慢，必须选 offload。

    依据 diffusers_image.py:212-218 的实测：
      model_offload 首图 5.4s / whole_gpu 首图 7.2s（整卡加载 55.7s）。
    「越激进越快」只在批量稳态成立，单张不成立 —— 靠档位顺序猜就会选错。
    """
    trials = [
        CAL.Trial(CAL.MODE_MODEL_OFFLOAD, True, 5.0, 5.4),
        CAL.Trial(CAL.MODE_WHOLE_GPU, True, 6.5, 7.2),
    ]
    chosen, rej = CAL.decide(trials)
    assert chosen is not None
    assert chosen.mode == CAL.MODE_MODEL_OFFLOAD, (
        "选了 %s（%.1fs），但 model_offload 更快（%.1fs）"
        % (chosen.mode, chosen.seconds, 5.4))
    assert rej == []


def test_decide_handles_missing_seconds():
    """缺时间的新档不抢位，但也不让整体失败。"""
    trials = [
        CAL.Trial(CAL.MODE_SEQUENTIAL_OFFLOAD, True, 4.0, 6.0),
        CAL.Trial(CAL.MODE_MODEL_OFFLOAD, True, 5.0, None),
    ]
    chosen, rej = CAL.decide(trials)
    assert chosen is not None and chosen.mode == CAL.MODE_SEQUENTIAL_OFFLOAD


def test_decide_stops_at_first_failure():
    """第二个失败 ⇒ 选中第一个；第三个即使「能跑」也不该被采纳。"""
    trials = [
        CAL.Trial(CAL.MODE_LAYER_CPU_OFFLOAD, True, 3.0, 9.0),
        CAL.Trial(CAL.MODE_SEQUENTIAL_OFFLOAD, False, None, None, "OOM"),
        CAL.Trial(CAL.MODE_MODEL_OFFLOAD, True, 5.0, 4.0),
    ]
    chosen, rej = CAL.decide(trials)
    assert chosen is not None and chosen.mode == CAL.MODE_LAYER_CPU_OFFLOAD
    assert len(rej) == 1
    assert CAL.MODE_SEQUENTIAL_OFFLOAD in rej[0]


def test_decide_stops_at_waterline():
    trials = [
        CAL.Trial(CAL.MODE_LAYER_CPU_OFFLOAD, True, 3.0, 9.0),
        CAL.Trial(CAL.MODE_SEQUENTIAL_OFFLOAD, True, 7.8, 6.0),  # 超 7.6 水位
    ]
    chosen, rej = CAL.decide(trials, water_line_gb=7.6)
    assert chosen is not None and chosen.mode == CAL.MODE_LAYER_CPU_OFFLOAD
    assert len(rej) == 1


def test_decide_all_fail_returns_none():
    trials = [CAL.Trial(CAL.MODE_LAYER_CPU_OFFLOAD, False, None, None, "OOM")]
    chosen, rej = CAL.decide(trials)
    assert chosen is None
    assert len(rej) == 1


def test_ladder_start_skips_conservative_modes():
    assert CAL.ladder("") == CAL.LADDER
    got = CAL.ladder(CAL.MODE_MODEL_OFFLOAD)
    assert got[0] == CAL.MODE_MODEL_OFFLOAD
    assert len(got) == 2


# ── 4. 档案失效（AC-6）─────────────────────────────────────────────────────
def test_make_key_torch_patch_does_not_matter():
    a = CAL.make_key(prof_nvidia(), "m", 1024, 1024, "2.6.0")
    b = CAL.make_key(prof_nvidia(), "m", 1024, 1024, "2.6.5")
    assert a == b, "patch 版本变化不应导致全部重标"


def test_make_key_torch_minor_matters():
    a = CAL.make_key(prof_nvidia(), "m", 1024, 1024, "2.6.0")
    b = CAL.make_key(prof_nvidia(), "m", 1024, 1024, "2.7.0")
    assert a != b, "minor 变化必须让旧档案失效"


def test_make_key_arch_and_vram_matter():
    base = CAL.make_key(prof_nvidia(8.0, "sm89"), "m", 1024, 1024, "2.6.0")
    assert base != CAL.make_key(prof_nvidia(8.0, "sm90"), "m", 1024, 1024, "2.6.0")
    assert base != CAL.make_key(prof_nvidia(24.0, "sm89"), "m", 1024, 1024, "2.6.0")


def test_res_class_boundaries():
    assert CAL.res_class(512, 512) == "512"
    assert CAL.res_class(768, 768) == "768"
    assert CAL.res_class(1024, 1024) == "1024"
    assert CAL.res_class(1536, 1024) == "1536plus"
    assert CAL.res_class(0, 0) == "unknown"


# ── 5. 外推（D-A6 / AC-8）──────────────────────────────────────────────────
def test_extrapolate_linear_model_with_base():
    """给了权重固定占用 ⇒ 线性模型：只有激活部分随像素涨。"""
    got = CAL.extrapolate(6.0, 512, 1024, base_gb=4.0)
    # 4.0 + (6.0-4.0)*4 = 12.0
    assert got == pytest.approx(12.0)


def test_extrapolate_power_anchor_at_4x_pixels():
    """没给 base ⇒ 幂律兜底，锚点为实测值：像素 4 倍 → 系数 1.46。

    实测来源（2026-10-28，SD1.5 + model_offload）：
      512² 峰值 1.75GB → 1024² 峰值 2.55GB，比值 1.457。
    此前文档猜的 1.6 偏高 9.8%，已按实测否决。
    """
    got = CAL.extrapolate(5.0, 512, 1024)
    assert got == pytest.approx(7.30, rel=1e-3)


def test_extrapolate_linear_reproduces_measured_points():
    """线性模型必须能复现实测两点：base≈1.48, k≈0.267 → 1024² 得 2.55GB。"""
    got = CAL.extrapolate(1.75, 512, 1024, base_gb=1.48)
    assert got == pytest.approx(2.55, abs=0.02)


def test_extrapolate_never_shrinks_and_handles_junk():
    assert CAL.extrapolate(5.0, 1024, 512) == 5.0
    assert CAL.extrapolate(None, 512, 1024) is None
    assert CAL.extrapolate(5.0, 0, 1024) is None
    assert CAL.extrapolate(5.0, 512, 0) is None


def test_derive_for_video_is_always_derived_not_measured(store):
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=FakeProbe({
        CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0),
        CAL.MODE_SEQUENTIAL_OFFLOAD: ("ok", 4.0, 6.0),
        CAL.MODE_MODEL_OFFLOAD: ("ok", 5.0, 4.0),
        CAL.MODE_WHOLE_GPU: ("fail", "OOM"),
    }))
    img = cal.calibrate("sdxl-base", (1024, 1024))
    assert img is not None and img.source == CAL.SOURCE_MEASURED
    assert img.mode == CAL.MODE_MODEL_OFFLOAD

    img_key = cal.key_for("sdxl-base", (1024, 1024))
    vid = cal.derive_for_video(img, img_key, "svd", frames=25)
    assert vid is not None
    assert vid.source == CAL.SOURCE_DERIVED, "外推结果绝不能标 measured"
    assert vid.derived_from == img_key
    assert vid.peak_gb > img.peak_gb, "25 帧不该比单图省显存"


def test_effective_peak_prefers_conservative():
    """记账号口径取 allocated 与 reserved 的较大者。"""
    t = CAL.Trial(CAL.MODE_MODEL_OFFLOAD, True, peak_gb=2.55, seconds=6.7,
                  reserved_gb=4.36)
    assert CAL.effective_peak_gb(t) == 4.36
    t2 = CAL.Trial(CAL.MODE_MODEL_OFFLOAD, True, peak_gb=5.0, seconds=6.7)
    assert CAL.effective_peak_gb(t2) == 5.0
    assert CAL.effective_peak_gb(CAL.Trial("m", True)) is None


def test_decide_uses_reserved_when_allocated_looks_safe():
    """★ 实测陷阱守卫：allocated 没超水位但 reserved 超了，必须判这一档不可用。

    复现 2026-10-28 的 1024² 实测形状：allocated 2.55 看似安全，
    reserved 4.36 才是真实占用。只按 allocated 判就会选到会 OOM 的档。
    """
    trials = [
        CAL.Trial(CAL.MODE_MODEL_OFFLOAD, True, peak_gb=2.55, seconds=6.7,
                  reserved_gb=4.36),
    ]
    # 水位线设 4.0：allocated 2.55 过，reserved 4.36 不过
    chosen, rej = CAL.decide(trials, water_line_gb=4.0)
    assert chosen is None, "reserved 超线却被放行了"
    assert len(rej) == 1 and "4.36" in rej[0]


def test_key_for_really_contains_torch_version(store):
    """★ 回归守卫：key 里不能是 "?"。

    曾经因为 Calibrator 没拿到 torch_version 且 device_profile 不返回该字段，
    档案 key 退化成 'nvidia|sm89|8|?|model|512'，于是 torch 升级后旧档案
    永远不会失效 —— AC-6 形同虚设。
    """
    cal = CAL.Calibrator(store, prof_nvidia(), torch_version="2.6.0+cu124")
    k = cal.key_for("sdxl-base", (1024, 1024))
    assert "|?" not in k, "torch 版本没接上，档案失效机制会失灵：%s" % k
    assert "|2.6|" in k
    assert cal.stats()["torch_mm"] == "2.6"


def test_key_for_degrades_visibly_without_torch_version(store):
    """没传版本时诚实地写成 ?，但 stats 里要能看出来。"""
    cal = CAL.Calibrator(store, prof_nvidia(), torch_version="")
    assert "|?" in cal.key_for("m", (512, 512))
    assert "未提供" in cal.stats()["torch_version"]


# ── 6. 档案存储 ───────────────────────────────────────────────────────────
def test_store_roundtrip(tmp_path):
    st = CAL.CalibrationStore(str(tmp_path / "c.json"))
    e = CAL.Entry(mode=CAL.MODE_MODEL_OFFLOAD, peak_gb=5.21, seconds=27.9,
                  source=CAL.SOURCE_MEASURED, tried=(CAL.MODE_MODEL_OFFLOAD,),
                  rejected=("whole_gpu: OOM",))
    assert st.put("k1", e) is True
    got = CAL.CalibrationStore(str(tmp_path / "c.json")).get("k1")
    assert got is not None
    assert got.peak_gb == 5.21
    assert got.rejected == ("whole_gpu: OOM",)
    assert got.tried == (CAL.MODE_MODEL_OFFLOAD,)


def test_store_corrupted_file_rebuilds(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ this is not json", encoding="utf-8")
    st = CAL.CalibrationStore(str(p))
    assert st.get("anything") is None       # 不抛
    assert st.invalidate() == 0
    st.put("k", CAL.Entry(CAL.MODE_WHOLE_GPU, 1.0, 1.0))
    assert json.loads(p.read_text(encoding="utf-8"))["version"] == CAL.CALIB_VERSION


def test_store_invalidate_single_and_all(tmp_path):
    st = CAL.CalibrationStore(str(tmp_path / "c.json"))
    st.put("a", CAL.Entry(CAL.MODE_WHOLE_GPU, 1.0, 1.0))
    st.put("b", CAL.Entry(CAL.MODE_WHOLE_GPU, 2.0, 2.0))
    assert st.invalidate("a") == 1
    assert st.get("a") is None and st.get("b") is not None
    assert st.invalidate() == 1
    assert st.keys() == []


def test_store_stats_counts_by_source(tmp_path):
    st = CAL.CalibrationStore(str(tmp_path / "c.json"))
    st.put("m", CAL.Entry(CAL.MODE_WHOLE_GPU, 1.0, 1.0, source=CAL.SOURCE_MEASURED))
    st.put("d", CAL.Entry(CAL.MODE_WHOLE_GPU, 1.0, 1.0, source=CAL.SOURCE_DERIVED))
    stats = st.stats()
    assert stats["entries"] == 2
    assert stats["by_source"][CAL.SOURCE_MEASURED] == 1
    assert stats["by_source"][CAL.SOURCE_DERIVED] == 1


# ── 7. 标定器行为（AC-3/4/5）───────────────────────────────────────────────
def test_calibrator_climbs_and_records(store):
    fp = FakeProbe({
        CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0),
        CAL.MODE_SEQUENTIAL_OFFLOAD: ("ok", 4.0, 6.0),
        CAL.MODE_MODEL_OFFLOAD: ("fail", "CUDA OOM"),
    })
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp)
    e = cal.calibrate("sd15", (512, 512))
    assert e is not None
    assert e.mode == CAL.MODE_SEQUENTIAL_OFFLOAD
    assert e.source == CAL.SOURCE_MEASURED
    # tried 记「试过的全部档位」——含失败的那次，因为确实试过了；
    # rejected 记「为什么失败」。两者语义不同，不可混。
    assert e.tried == (CAL.MODE_LAYER_CPU_OFFLOAD,
                       CAL.MODE_SEQUENTIAL_OFFLOAD,
                       CAL.MODE_MODEL_OFFLOAD)
    assert e.tried[-1] == CAL.MODE_MODEL_OFFLOAD     # 失败的那个在 tried 里
    assert e.mode != CAL.MODE_MODEL_OFFLOAD          # 但它没被选中
    assert len(e.rejected) == 1
    # 第三个失败就停，不该试 whole_gpu
    assert [c[0] for c in fp.calls] == [
        CAL.MODE_LAYER_CPU_OFFLOAD, CAL.MODE_SEQUENTIAL_OFFLOAD, CAL.MODE_MODEL_OFFLOAD]


def test_calibrator_second_call_hits_cache(store):
    """AC-5：第二次必须走档案，不再试跑。"""
    fp = FakeProbe({CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0)})
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp)
    e1 = cal.calibrate("sd15", (512, 512))
    n1 = len(fp.calls)
    e2 = cal.calibrate("sd15", (512, 512))
    assert len(fp.calls) == n1, "命中档案时不应再试跑"
    assert e2 is not None and e1 is not None and e2.mode == e1.mode


def test_calibrator_probe_raises_does_not_crash(store):
    """AC-4：试跑抛异常 = 该档失败，不是整个标定崩溃。"""
    class Boom:
        def __call__(self, mode, px):
            if mode == CAL.MODE_LAYER_CPU_OFFLOAD:
                return CAL.Trial(mode=mode, ok=True, peak_gb=3.0, seconds=9.0)
            raise RuntimeError("driver exploded")

    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=Boom())
    e = cal.calibrate("sd15", (512, 512))
    assert e is not None
    assert e.mode == CAL.MODE_LAYER_CPU_OFFLOAD
    assert "driver exploded" in " ".join(e.rejected)


def test_calibrator_rejects_small_vram_without_probing(store):
    fp = FakeProbe({CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0)})
    cal = CAL.Calibrator(store, prof_small(6.0), probe_run=fp)
    assert cal.calibrate("sd15", (512, 512)) is None
    assert fp.calls == [], "未过准入门槛就不该浪费一次试跑"


def test_calibrator_all_modes_fail_returns_none(store):
    fp = FakeProbe({
        CAL.MODE_LAYER_CPU_OFFLOAD: ("fail", "OOM"),
        CAL.MODE_SEQUENTIAL_OFFLOAD: ("fail", "OOM"),
        CAL.MODE_MODEL_OFFLOAD: ("fail", "OOM"),
        CAL.MODE_WHOLE_GPU: ("fail", "OOM"),
    })
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp)
    assert cal.calibrate("sd15", (512, 512)) is None
    assert store.keys() == [], "全失败不该写档"


def test_calibrator_without_probe_is_noop(store):
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=None)
    assert cal.calibrate("sd15") is None


def test_calibrator_waterline_uses_total_vram(store):
    """水位线默认 = 总显存 × 0.95，8GB ⇒ 7.6GB。"""
    cal = CAL.Calibrator(store, prof_nvidia(8.0), probe_run=FakeProbe({}))
    assert cal.water_line_gb == pytest.approx(7.6)


def test_calibrator_background_finishes(store):
    """AC-1：后台标定可启动、可等待，不阻塞调用方。"""
    class Slow:
        def __call__(self, mode, px):
            if mode == CAL.MODE_LAYER_CPU_OFFLOAD:
                return CAL.Trial(mode=mode, ok=True, peak_gb=3.0, seconds=9.0)
            return CAL.Trial(mode=mode, ok=False, error="stop")

    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=Slow())
    assert cal.start_background("sd15", (512, 512)) is True
    assert cal.wait(5.0) is True
    assert cal.best_for("sd15", (512, 512)) is not None


def test_calibrator_background_not_stacked(store):
    import time

    class VSlow:
        def __call__(self, mode, px):
            time.sleep(0.2)
            return CAL.Trial(mode=mode, ok=False, error="stop")

    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=VSlow())
    assert cal.start_background("m") is True
    assert cal.start_background("m") is False, "已在跑时不应再起一个线程"
    cal.cancel()
    cal.wait(5.0)


# ── 8. 台账诚实性总守卫 ────────────────────────────────────────────────────
def test_no_entry_can_be_measured_without_trial(store):
    """凡是 source=measured 的条目，必须真的试跑过至少一次。"""
    class P:
        def __call__(self, mode, px):
            return CAL.Trial(mode=mode, ok=True, peak_gb=3.0, seconds=9.0)

    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=P())
    cal.calibrate("a", (512, 512))
    for k in store.keys():
        e = store.get(k)
        assert e is not None
        if e.source == CAL.SOURCE_MEASURED:
            assert e.tried, "%s 标了 measured 却没有 tried 记录" % k


def test_module_is_torch_free():
    """本模块必须零 torch 依赖：画布 HTTP 线程会直接调它。"""
    import sys
    for name in list(sys.modules):
        if name == "torch" or name.startswith("torch."):
            pytest.skip("环境已加载 torch，跳过纯净性检查")
    import app.core.neural.calibration as C

    assert not any(k.startswith("torch") for k in vars(C)), \
        "calibration 模块不得引入 torch 符号"


# ── 9. 预热：消冷启动偏差（2026-10-28）──────────────────────────────────────
class Recorder:
    """记录调用顺序的假 warmup：可与 FakeProbe 共用一条时间线。"""

    def __init__(self, timeline, ret=None, boom=None, secs=1.5):
        self.timeline = timeline
        self.ret = ret if ret is not None else secs
        self.boom = boom
        self.calls = 0

    def __call__(self):
        self.calls += 1
        self.timeline.append("warmup")
        if self.boom is not None:
            raise self.boom
        return self.ret


def _timeline_probe(timeline, plan):
    class P(FakeProbe):
        def __call__(self, mode, px):
            timeline.append(mode)
            return super().__call__(mode, px)

    return P(plan)


def test_warmup_runs_before_first_tier(store):
    """★ 预热必须排在**第一档之前** —— 它存在的意义就是把冷启动成本吃掉。"""
    tl = []
    fp = _timeline_probe(tl, {
        CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0),
        CAL.MODE_SEQUENTIAL_OFFLOAD: ("fail", "stop"),
    })
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp,
                         warmup_run=Recorder(tl))
    e = cal.calibrate("sd15", (512, 512))

    assert e is not None
    assert tl[0] == "warmup", tl
    assert tl[1] == CAL.MODE_LAYER_CPU_OFFLOAD
    assert cal.warmup_seconds == pytest.approx(1.5)


def test_warmup_result_never_enters_tried_or_decide(store):
    """预热是**丢弃式**的：不能出现在 tried 里，也不能参与「哪档最快」的裁决。"""
    tl = []
    fp = _timeline_probe(tl, {})
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp,
                         warmup_run=Recorder(tl, secs=0.01))
    cal.calibrate("sd15", (512, 512))

    for k in store.keys():
        e = store.get(k)
        assert e is not None
        assert "warmup" not in e.tried


def test_warmup_failure_does_not_abort_calibration(store):
    """预热失败 = 少一份增强，不是标定失败（D-A3）。"""
    fp = FakeProbe({CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0)})
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp,
                         warmup_run=Recorder([], boom=RuntimeError("预热炸了")))

    e = cal.calibrate("sd15", (512, 512))

    assert e is not None and e.mode == CAL.MODE_LAYER_CPU_OFFLOAD
    assert cal.warmup_seconds is None
    assert "预热炸了" in cal.warmup_error


def test_warmup_oom_does_not_abort(store):
    fp = FakeProbe({CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0)})
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp,
                         warmup_run=Recorder([], boom=MemoryError()))

    assert cal.calibrate("sd15", (512, 512)) is not None
    assert "OOM" in cal.warmup_error


def test_warmup_none_keeps_old_behaviour(store):
    """不注入 warmup_run ⇒ 完全不加跑（纯逻辑测试与旧调用方零变化）。"""
    fp = FakeProbe({CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0)})
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp)

    cal.calibrate("sd15", (512, 512))

    assert cal.warmup_seconds is None
    # 第一次调用就是阶梯第一档（没有预热插队），且阶梯照旧在失败处停
    assert [c[0] for c in fp.calls] == [
        CAL.MODE_LAYER_CPU_OFFLOAD, CAL.MODE_SEQUENTIAL_OFFLOAD]


def test_warmup_skipped_when_archive_hits(store):
    """命中档案必须秒开（AC-5）—— 预热不能插在命中判断之前白跑一次。"""
    tl = []
    fp = _timeline_probe(tl, {CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0)})
    rec = Recorder(tl)
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp, warmup_run=rec)

    cal.calibrate("sd15", (512, 512))
    n_after_first = rec.calls
    tl.clear()
    cal.calibrate("sd15", (512, 512))

    assert rec.calls == n_after_first, "第二次命中档案，不该再预热"
    assert tl == [], "命中档案时连 probe 都不该跑"


def test_warmup_not_run_when_admission_fails(store):
    """没过 8GB 准入就不该浪费一次预热（AC-7 的同一精神）。"""
    rec = Recorder([])
    cal = CAL.Calibrator(store, prof_small(6.0),
                         probe_run=FakeProbe({}), warmup_run=rec)

    assert cal.calibrate("sd15", (512, 512)) is None
    assert rec.calls == 0


def test_warmup_is_recorded_in_entry_note(store):
    """「这份档案已剔除冷启动」必须留在档里，否则事后无从考证。"""
    fp = FakeProbe({CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0)})
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp,
                         warmup_run=Recorder([], secs=2.25))

    e = cal.calibrate("sd15", (512, 512))

    assert e is not None
    assert "预热 2.25s" in e.note
    assert "已剔除首档冷启动" in e.note


def test_entry_note_says_when_warmup_failed(store):
    """预热失败也要写进档 —— 让后来的人知道这份档案的耗时可能偏高。"""
    fp = FakeProbe({CAL.MODE_LAYER_CPU_OFFLOAD: ("ok", 3.0, 9.0)})
    cal = CAL.Calibrator(store, prof_nvidia(), probe_run=fp,
                         warmup_run=Recorder([], boom=RuntimeError("nope")))

    e = cal.calibrate("sd15", (512, 512))

    assert e is not None
    assert "未预热" in e.note and "冷启动" in e.note


def test_trial_keeps_split_timings():
    """分项耗时是可证性基础：`seconds` 必须约等于 load+gen。"""
    t = CAL.Trial(mode="x", ok=True, peak_gb=1.0, reserved_gb=1.2,
                  seconds=3.0, load_seconds=2.0, gen_seconds=1.0)
    assert t.load_seconds + t.gen_seconds == pytest.approx(t.seconds)
    d = t.to_dict()
    assert d["load_seconds"] == 2.0 and d["gen_seconds"] == 1.0


def test_warmup_run_is_injected_not_imported():
    """预热必须是注入的（本模块零 GPU）—— 不许在 calibration.py 里 import 探针。"""
    import inspect

    src = inspect.getsource(CAL)
    assert "calibration_probe" not in src, \
        "纯逻辑模块不得反向依赖执行层"

