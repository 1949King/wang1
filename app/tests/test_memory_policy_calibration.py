# -*- coding: utf-8 -*-
"""标定档案 × 显存策略接线单测（2026-10-28）—— 分支 -1 的行为锁。

为什么单独一个文件
==================
`test_memory_policy.py` / `test_memory_policy_matrix.py` / `test_vram_budget.py`
测的是**规则语义**，它们的 autouse fixture 把档案钉死为空，保证任何机器上确定性。
本文件反过来：**只测档案接线本身**，且用 tmp 档案 + 假设备画像，
不读 `data/calibration.json`、不碰真 GPU。

锁死六件事
----------
  ① **实测优先于规则**：档案命中就采纳，连调优表 `prefer_mode` 也压过；
  ② **安全闸 1**：档案峰值放不进当前空闲 ⇒ 降级走规则（历史 ≠ 现在）；
  ③ **安全闸 2**：whole_gpu 永远复验 15% 余量（历史峰值只证明「当时没炸」）；
  ④ **边界诚实**：视频（frames>0）不用档案、未声明档位不用、planned 档不用；
  ⑤ **失败不阻断**：档案模块炸了/查询异常 ⇒ 规则决策照常（D-A3 精神）；
  ⑥ **决策可见**：每条分支都往 reasons 里写一句人话（同 R9，reasons 永不为空）。

⚠️ 这些用例**不允许**依赖 `data/calibration.json` 的存在与否 ——
   开发机跑过标定就有、CI 没有。所有档案都写进 `tmp_path`。
"""

import pytest

from app.core.neural import calibration as CAL
from app.core.neural import device_profile as DP
from app.core.neural import memory_policy as MP
from app.core.neural.memory_policy import (
    MODE_LAYER_CPU_OFFLOAD,
    MODE_LAYER_DISK_OFFLOAD,
    MODE_MODEL_OFFLOAD,
    MODE_SEQUENTIAL_OFFLOAD,
    MODE_WHOLE_GPU,
)

# ── 假设备画像：与本机同款（8GB / sm89），但**注入**而非探测 ──────────────
_PROFILE = {"vendor": "nvidia", "arch": "sm89", "vram_gb": 8.0,
            "torch_version": "2.6.0"}


def _key(model_id="sd15-t2i", w=512, h=512, tv="2.6.0", profile=_PROFILE):
    """用生产代码自己的 `make_key` 造 key —— 不手写字符串，避免格式漂移。"""
    return CAL.make_key(profile, model_id, w, h, tv)


@pytest.fixture()
def calib(monkeypatch, tmp_path):
    """把档案与设备画像都换成可控的：返回 (装 entries 的函数, 档案对象)。

    用法::

        store, prof = calib({_key(): Entry(...)})
    """
    def _make(entries=None, profile=None):
        prof = dict(profile or _PROFILE)
        store = CAL.CalibrationStore(str(tmp_path / "calibration.json"))
        for k, e in (entries or {}).items():
            assert store.put(k, e), "tmp 档案写不进去，用例环境有问题"
        monkeypatch.setattr(CAL, "default_store", lambda: store)
        monkeypatch.setattr(DP, "probe", lambda **kw: prof)
        return store, prof

    return _make


def _pick(mid="sd15-t2i", frames=0, free=7.36, total=8.0, **kw):
    """注入显存决策（不真探测，CI 可跑）。"""
    return MP.pick_memory_policy(
        mid, frames=frames, free_vram_gb=free, total_vram_gb=total, **kw)


def _entry(mode=MODE_WHOLE_GPU, peak=3.19, seconds=2.01, **kw):
    return CAL.Entry(mode=mode, peak_gb=peak, seconds=seconds, **kw)


# ══════════════════════════════════════════════════════════════════════════
# ① 实测优先于规则
# ══════════════════════════════════════════════════════════════════════════


def test_archive_hit_is_adopted(calib):
    """档案命中 ⇒ 直接用，floor_gb 取**实测峰值**（不是拟合外推）。"""
    calib({_key(): _entry(MODE_WHOLE_GPU, 3.19, 2.01)})

    pol = _pick()

    assert pol["mode"] == MODE_WHOLE_GPU
    assert pol["offload"] is False
    assert pol["floor_gb"] == 3.19, "floor 必须是实测峰值，不是 estimate_floor_gb 的拟合值"
    assert any("标定档案命中" in r for r in pol["reasons"])
    assert any("实测优先于水位线规则" in r for r in pol["reasons"])


def test_archive_beats_prefer_mode(calib):
    """档案压过调优表 prefer_mode —— 分支 -1 排在分支 0 之前的原因。"""
    calib({_key(): _entry(MODE_SEQUENTIAL_OFFLOAD, 3.5, 9.0)})

    pol = _pick(tuned={"decode_chunk_size": 1, "offload": True,
                       "prefer_mode": MODE_MODEL_OFFLOAD})

    assert pol["mode"] == MODE_SEQUENTIAL_OFFLOAD
    assert not any("prefer_mode" in r for r in pol["reasons"]), \
        "档案命中后不该再走到 prefer_mode 分支"


def test_archive_offload_mode_keeps_offload_semantics(calib):
    """offload 布尔跟着 mode 走（旧接口语义不能坏）。"""
    calib({_key(): _entry(MODE_MODEL_OFFLOAD, 5.21, 27.9)})

    pol = _pick()

    assert pol["mode"] == MODE_MODEL_OFFLOAD
    assert pol["offload"] is True


# ══════════════════════════════════════════════════════════════════════════
# ② 安全闸 1：历史实测 ≠ 当前可用
# ══════════════════════════════════════════════════════════════════════════


def test_safety_gate_when_free_vram_shrunk(calib):
    """别的进程占走显存 ⇒ 档案不盲用，降级走规则并**明说为什么**。"""
    calib({_key(): _entry(MODE_WHOLE_GPU, 3.19, 2.01)})

    pol = _pick(free=3.0, total=8.0)  # 3.0 < 3.19 ⇒ 过不去

    assert pol["mode"] != MODE_WHOLE_GPU
    assert pol["mode"] == MODE_MODEL_OFFLOAD, "规则分支的保守结论"
    assert any("降级走规则决策" in r for r in pol["reasons"])
    assert any("当前空闲仅 3.00GB" in r for r in pol["reasons"])


def test_safety_gate_boundary_is_inclusive(calib):
    """峰值**等于**空闲 ⇒ 仍可用（判据是 ``peak > free`` 才拒）。"""
    calib({_key(): _entry(MODE_MODEL_OFFLOAD, 5.00, 10.0)})

    pol = _pick(free=5.00, total=8.0)

    assert pol["mode"] == MODE_MODEL_OFFLOAD
    assert pol["floor_gb"] == 5.00


# ══════════════════════════════════════════════════════════════════════════
# ③ 安全闸 2：whole_gpu 的 15% 余量复验
# ══════════════════════════════════════════════════════════════════════════


def test_whole_gpu_headroom_is_rechecked(calib):
    """峰值 7.0GB 放得进空闲 7.36GB，但超过总显存 ×0.85 = 6.8GB ⇒ 仍拒。

    这条闸拦的正是「当时刚好没炸」：WDDM 分页的代价是 >600s 卡死（SVD 10 帧实测），
    所以 whole_gpu 不接受「勉强塞得下」。
    """
    calib({_key(): _entry(MODE_WHOLE_GPU, 7.00, 3.0)})

    pol = _pick(free=7.36, total=8.0)

    assert pol["mode"] != MODE_WHOLE_GPU
    assert any("15% 余量线" in r for r in pol["reasons"])


def test_whole_gpu_rejected_when_total_unknown(calib):
    """总显存未知 ⇒ 无法复验余量 ⇒ 保守改走规则（不猜）。"""
    calib({_key(): _entry(MODE_WHOLE_GPU, 3.19, 2.01)})

    mode, entry, reason = MP._calibration_lookup(
        "sd15-t2i", 512, 512, 0, 7.36, None, MP.ACTIVE_MODES)

    assert mode is None and entry is not None
    assert "无法复验 15% 余量" in reason


def test_offload_modes_need_no_headroom_check(calib):
    """非 whole_gpu 档没有 15% 余量要求（offload 自带兜底，规则同分支 2）。"""
    calib({_key(): _entry(MODE_MODEL_OFFLOAD, 7.90, 30.0)})

    pol = _pick(free=7.95, total=8.0)

    assert pol["mode"] == MODE_MODEL_OFFLOAD


# ══════════════════════════════════════════════════════════════════════════
# ④ 边界诚实：视频不猜、未声明不用、planned 不用、零峰值不用
# ══════════════════════════════════════════════════════════════════════════


def test_video_frames_skip_archive(calib):
    """档案没有帧数维度 ⇒ 视频路径明确不用它（SVD 显存 ≈0.31GB/帧，猜必翻车）。"""
    calib({_key("sd15-t2i"): _entry(MODE_WHOLE_GPU, 3.19, 2.01)})

    pol = _pick("sd15-t2i", frames=25)

    assert pol["mode"] != MODE_WHOLE_GPU
    assert any("标定档案尚无帧数维度" in r for r in pol["reasons"])


def test_mode_not_declared_by_engine_is_ignored(calib):
    """引擎没声明支持 layer 档 ⇒ 档案说的也不能用（决策与执行不许漂移）。"""
    calib({_key(): _entry(MODE_LAYER_CPU_OFFLOAD, 3.0, 8.0)})

    pol = _pick(supported_modes=None)  # legacy 三档

    assert pol["mode"] != MODE_LAYER_CPU_OFFLOAD
    assert any("引擎未声明支持该档" in r for r in pol["reasons"])


def test_declared_layer_mode_is_accepted(calib):
    """声明了 ACTIVE_MODES ⇒ 档案里的 layer 档可以被采纳。"""
    calib({_key(): _entry(MODE_LAYER_CPU_OFFLOAD, 3.0, 8.0)})

    pol = _pick(supported_modes=MP.ACTIVE_MODES)

    assert pol["mode"] == MODE_LAYER_CPU_OFFLOAD


def test_planned_mode_is_ignored(calib):
    """layer_disk_offload 仍是预告 —— 档案里就算有也不许返回（诚实失败）。"""
    calib({_key(): _entry(MODE_LAYER_DISK_OFFLOAD, 3.0, 8.0)})

    mode, _entry_obj, reason = MP._calibration_lookup(
        "sd15-t2i", 512, 512, 0, 7.36, 8.0, MP.ACTIVE_MODES)

    assert mode is None
    assert "不在 ACTIVE_MODES" in reason


def test_zero_peak_is_not_evidence(calib):
    """peak_gb=0 的坏档案不能当依据（不拿 0 当「不占显存」）。"""
    calib({_key(): _entry(MODE_WHOLE_GPU, 0.0, 0.0)})

    mode, _e, reason = MP._calibration_lookup(
        "sd15-t2i", 512, 512, 0, 7.36, 8.0, MP.ACTIVE_MODES)

    assert mode is None
    assert "无有效 peak_gb" in reason


# ══════════════════════════════════════════════════════════════════════════
# ⑤ 失败不阻断（增强 ≠ 前置依赖，D-A3）
# ══════════════════════════════════════════════════════════════════════════


def test_empty_archive_degrades_to_rules(calib):
    calib({})

    pol = _pick()

    assert pol["mode"] == MODE_MODEL_OFFLOAD
    assert any("无匹配标定档案" in r for r in pol["reasons"])


def test_lookup_exception_degrades(calib, monkeypatch):
    """档案查询抛异常 ⇒ 规则决策照常，且说得出来（不静默）。"""
    calib({})

    def _boom(*a, **k):
        raise RuntimeError("模拟档案损坏")

    monkeypatch.setattr(CAL, "lookup", _boom)

    pol = _pick()

    assert pol["mode"] == MODE_MODEL_OFFLOAD
    assert any("标定档案查询失败" in r for r in pol["reasons"])


def test_calibration_module_missing_degrades(monkeypatch):
    """标定模块整个不可 import ⇒ 也不能把档位决策搞挂。"""
    import builtins
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        # `from app.core.neural import calibration as CAL` 走的是
        # __import__("app.core.neural", fromlist=("calibration",))，不是 "....calibration"
        if name == "app.core.neural" and fromlist and "calibration" in fromlist:
            raise ImportError("模拟标定模块缺失")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    pol = _pick()

    assert pol["mode"] == MODE_MODEL_OFFLOAD
    assert any("标定模块不可用" in r for r in pol["reasons"])


def test_use_calibration_false_skips_everything(calib):
    """显式关闭 ⇒ 连查都不查（bench / 四档对比 / 排障的逃生门）。"""
    calib({_key(): _entry(MODE_WHOLE_GPU, 3.19, 2.01)})

    pol = _pick(use_calibration=False)

    assert pol["mode"] == MODE_MODEL_OFFLOAD
    assert any("use_calibration=False" in r for r in pol["reasons"])
    assert not any("标定档案命中" in r for r in pol["reasons"])


# ══════════════════════════════════════════════════════════════════════════
# ⑥ 分辨率宽松匹配 + 决策可见
# ══════════════════════════════════════════════════════════════════════════


def test_resolution_falls_back_to_worst_case(calib):
    """查不到同分辨率 ⇒ 取**峰值最大**那条（用最坏情况决策，宁慢勿炸）。"""
    calib({
        _key(w=512, h=512): _entry(MODE_WHOLE_GPU, 3.19, 2.01),
        _key(w=1024, h=1024): _entry(MODE_MODEL_OFFLOAD, 5.60, 27.9),
    })

    # 出图尺寸未知（pick 发生在 load 阶段）
    _m, entry_unknown, _r = MP._calibration_lookup(
        "sd15-t2i", 0, 0, 0, 7.36, 8.0, MP.ACTIVE_MODES)
    assert entry_unknown is not None and entry_unknown.peak_gb == 5.60

    # 精确 512 ⇒ 命中最省的那条
    _m2, entry_512, _r2 = MP._calibration_lookup(
        "sd15-t2i", 512, 512, 0, 7.36, 8.0, MP.ACTIVE_MODES)
    assert entry_512 is not None and entry_512.peak_gb == 3.19


def test_other_model_does_not_match(calib):
    """别的模型的档案绝不串用（key 里 model_id 是隔离维度）。"""
    calib({_key(): _entry(MODE_WHOLE_GPU, 3.19, 2.01)})

    pol = _pick("sdxl-t2i")

    assert pol["mode"] == MODE_MODEL_OFFLOAD
    assert any("无匹配标定档案" in r for r in pol["reasons"])


# ══════════════════════════════════════════════════════════════════════════
# ⑦ 分辨率换算（探针 512² → 出图 1024² 时峰值要放大再判闸）
# ══════════════════════════════════════════════════════════════════════════


def test_peak_is_scaled_to_requested_resolution(calib):
    """512² 的档案被 1024² 请求命中 ⇒ 峰值按 `EXTRAPOLATE_COEF_4X` 放大。

    3.19GB × 1.457 ≈ 4.65GB（像素 ×4，系数 1.46 换算）。
    不换算就会拿「512² 的占用」去判「1024² 的水位」，低估值正好是 OOM 的来源。
    """
    calib({_key(w=512, h=512): _entry(MODE_MODEL_OFFLOAD, 3.19, 2.01)})

    pol = _pick(width=1024, height=1024)

    assert pol["mode"] == MODE_MODEL_OFFLOAD
    assert pol["floor_gb"] > 3.19, "floor 必须是换算后的峰值"
    assert abs(pol["floor_gb"] - 4.65) <= 0.02, pol["floor_gb"]
    assert any("外推系数" in r for r in pol["reasons"])


def test_scaled_peak_can_trip_the_free_vram_gate(calib):
    """换算后放不进空闲 ⇒ 拒。原始 3.19GB 看着放得下（4.0GB 空闲），换算后放不下。"""
    calib({_key(w=512, h=512): _entry(MODE_MODEL_OFFLOAD, 3.19, 2.01)})

    pol = _pick(free=4.00, total=8.0, width=1024, height=1024)

    assert any("降级走规则决策" in r for r in pol["reasons"])


def test_peak_for_resolution_helpers(calib):
    """`peak_for_resolution` 的三种「不知道」都原样返回，不编比例。"""
    e = _entry(MODE_WHOLE_GPU, 3.00, 1.0)

    assert CAL.peak_for_resolution(e, _key(w=512, h=512), 0, 0) == 3.00   # 目标未知
    assert CAL.peak_for_resolution(e, _key(w=512, h=512), 512, 512) == 3.00  # 同尺寸
    bad_key = "nvidia|sm89|8|2.6|sd15-t2i|1536plus"
    assert CAL.peak_for_resolution(e, bad_key, 2048, 2048) == 3.00        # 非数字分桶



def test_reasons_never_empty_across_archive_branches(calib):
    """档案的每条分支都写一句人话 —— reasons 永不为空（同 R9）。"""
    # 峰值 9.9GB 必被安全闸拦 ⇒ 强制走「档案被拒」分支
    calib({_key(): _entry(MODE_WHOLE_GPU, 9.9, 2.01)})
    for kw in ({}, dict(frames=5), dict(use_calibration=False)):
        pol = _pick(**kw)
        assert pol["reasons"], kw
        assert any("标定" in r or "档案" in r for r in pol["reasons"]), kw
