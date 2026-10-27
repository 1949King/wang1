# -*- coding: utf-8 -*-
"""device-tier 决策矩阵 mock 单测（V4.47.0）—— memory_policy 的显存分级行为锁。

覆盖矩阵：**8/12/16/24GB × 模型（sd15/sdxl/svd/未登记）× 帧数（0/5/10/14）**
× 能力声明（legacy 三档 / ACTIVE 四档），全部经 mock `probe_vram` 注入
（不碰真 GPU，CI/无卡机器可跑）。

锁死四件事：
  ① 8GB 开发机行为零变化（三个已登记模型的定稿模式/chunk/floor）；
  ② 能力声明过滤：layer_cpu_offload 只给显式声明 ACTIVE_MODES 的引擎
     （video_gen 只有两分支执行端 ⇒ 声明 None ⇒ 永不被给 layer）；
  ③ layer_disk_offload 是**预告**：永不返回，只在 planned_modes 里明说；
  ④ 升级路径可证：登记值/外推下限越水位 ⇒ sequential（含诚实的「改判」理由）。

这些数字同时是 Task 6「显存预算模型 / estimated 准入预测表」的输入常量——
本文件锁常量，预算模型读常量，两边不会漂。
"""

import pytest

from app.core.neural import memory_policy as MP
from app.core.neural.memory_policy import (
    MODE_LAYER_CPU_OFFLOAD,
    MODE_LAYER_DISK_OFFLOAD,
    MODE_MODEL_OFFLOAD,
    MODE_SEQUENTIAL_OFFLOAD,
    MODE_WHOLE_GPU,
    pick_memory_policy,
    probe_vram,
)

# ── 档位表：total 8/12/16/24GB，free = total×0.92（「基本空闲的卡」）───────
TIERS = {8: 7.36, 12: 11.04, 16: 14.72, 24: 22.08}

# 调优表条目（显式传入 = 纯函数测试，不依赖注册表现状）
_TUNED_SVD = {"steps": 14, "decode_chunk_size": 1, "offload": True}
_TUNED_SDXL = {"decode_chunk_size": 1, "offload": True, "prefer_mode": "model_offload"}
_TUNED_NO_OFFLOAD = {"steps": 25, "decode_chunk_size": 2, "offload": False}

# 注册表登记占用（GB）
_REG = {"sd15-t2i": 3.0, "sdxl-t2i": 7.0, "svd-xt-i2v": 7.0}


def _pick(model_id, *, frames=0, tier=8, supported=None, tuned=None,
          registered="auto", monkeypatch=None):
    """mock probe_vram 注入档位后决策（monkeypatch 由调用方传入以贴合 fixture 生命周期）。"""
    total = float(tier)
    monkeypatch.setattr(MP, "probe_vram",
                        lambda: {"free_gb": round(total * 0.92, 2), "total_gb": total})
    reg = _REG.get(model_id) if registered == "auto" else registered
    return pick_memory_policy(model_id, frames=frames, supported_modes=supported,
                              tuned=tuned, registered_vram_gb=reg)


@pytest.fixture(autouse=True)
def _no_calibration_archive(monkeypatch):
    """★ 本文件锁的是**档位矩阵规则**，档案必须钉死为空。

    `data/calibration.json` 是开发机标定产物（有无取决于跑没跑过标定），
    留着它会让同一份代码在「标定过的机器/CI」上给出不同档位 —— 那不是矩阵变了，
    是测试不自洽。档案优先级与安全闸由 `test_memory_policy_calibration.py` 专测。
    """
    monkeypatch.setattr(
        MP, "_calibration_lookup",
        lambda *a, **k: (None, None, "测试：矩阵用例，档案钉死为空"))


@pytest.fixture()
def _no_real_probe(monkeypatch):
    """默认把真探测打回 None（无 CUDA 语义），防测试机真卡泄漏进决策。"""
    monkeypatch.setattr(MP, "probe_vram", lambda: None)


# ══════════════════════════════════════════════════════════════════════
# 1. 8GB 开发机回归锁（最重的一条：加了缓存层也不许翻）
# ══════════════════════════════════════════════════════════════════════

class TestEightGbRegressionLock:
    """8GB（RTX 4060 Laptop，本项目全部实测的基线卡）三模型定稿行为。"""

    def test_svd_stays_model_offload_all_frames(self, monkeypatch):
        """SVD 定稿：offload 全帧数开启（两次反转的结论，勿凭直觉改）。"""
        for frames in (5, 8, 10, 14):
            pol = _pick("svd-xt-i2v", frames=frames, tier=8,
                        tuned=_TUNED_SVD, monkeypatch=monkeypatch)
            assert pol["mode"] == MODE_MODEL_OFFLOAD, (frames, pol)
            assert pol["offload"] is True
            assert pol["decode_chunk_size"] == 1, "SVD chunk 实测必须 1（比 2 快 6 倍）"
            assert pol["reasons"], "决策理由永不为空"

    def test_svd_floors_match_measured_fit(self, monkeypatch):
        """floor 必须等于 _MEASURED 线性拟合（预算模型的输入常量）。"""
        cases = {5: 4.65, 8: 5.58, 10: 6.20, 14: 7.44}
        for frames, want in cases.items():
            pol = _pick("svd-xt-i2v", frames=frames, tier=8,
                        tuned=_TUNED_SVD, monkeypatch=monkeypatch)
            assert pol["floor_gb"] == want, (frames, pol["floor_gb"])

    def test_sdxl_prefer_mode_wins_at_8gb(self, monkeypatch):
        """SDXL 四档实测定稿：prefer_mode=model_offload（5.21GB/27.9s）⇒ 分支 0 直达。"""
        pol = _pick("sdxl-t2i", tier=8, tuned=_TUNED_SDXL, monkeypatch=monkeypatch)
        assert pol["mode"] == MODE_MODEL_OFFLOAD
        assert pol["floor_gb"] == 5.21
        assert any("prefer_mode" in r for r in pol["reasons"])

    def test_sd15_model_offload_at_8gb(self, monkeypatch):
        """SD1.5（登记 3.0GB < 8GB×60%）⇒ 常规 model_offload，无实测 floor ⇒ None。"""
        pol = _pick("sd15-t2i", tier=8, tuned={"decode_chunk_size": 1, "offload": True},
                    monkeypatch=monkeypatch)
        assert pol["mode"] == MODE_MODEL_OFFLOAD
        assert pol["floor_gb"] is None, "无实测依据 ⇒ None（不编数字）"
        assert any("无实测下限" in r for r in pol["reasons"])

    def test_video_side_never_gets_layer_mode(self, monkeypatch):
        """视频链执行端只有两分支（model/sequential）⇒ 不声明 supported_modes
        ⇒ 即使登记 7.0GB > 8GB×60%，也不许返回 layer_cpu_offload（语义漂移防护）。"""
        pol = _pick("svd-xt-i2v", frames=5, tier=8, tuned=_TUNED_SVD,
                    supported=None, monkeypatch=monkeypatch)
        assert pol["mode"] == MODE_MODEL_OFFLOAD
        assert MODE_LAYER_CPU_OFFLOAD not in [pol["mode"]]


# ══════════════════════════════════════════════════════════════════════
# 2. 12/16/24GB 档位矩阵（estimated 准入预测的决策侧）
# ══════════════════════════════════════════════════════════════════════

class TestTierMatrix:
    """同模型跨档位：模式/floor 的档位不变量与差异点。"""

    @pytest.mark.parametrize("tier", [8, 12, 16, 24])
    def test_svd_model_offload_every_tier(self, monkeypatch, tier):
        """SVD offload 定稿与卡大小无关（大卡上 whole_gpu 也从未被登记表选中）。"""
        for frames in (5, 10, 14):
            pol = _pick("svd-xt-i2v", frames=frames, tier=tier,
                        tuned=_TUNED_SVD, monkeypatch=monkeypatch)
            assert pol["mode"] == MODE_MODEL_OFFLOAD, (tier, frames, pol["mode"])

    @pytest.mark.parametrize("tier", [8, 12, 16, 24])
    def test_sdxl_prefer_mode_every_tier(self, monkeypatch, tier):
        """SDXL prefer_mode 是四档实测结论，与档位无关（24GB 也不硬上整卡——
        whole_gpu 420s 超时被杀是实测，不是推测）。"""
        pol = _pick("sdxl-t2i", tier=tier, tuned=_TUNED_SDXL, monkeypatch=monkeypatch)
        assert pol["mode"] == MODE_MODEL_OFFLOAD

    def test_svd_sequential_upgrade_on_small_card(self, monkeypatch):
        """外推下限越 95% 水位 ⇒ 升级 sequential（小卡行为，非 8GB 路径）。"""
        pol = _pick("svd-xt-i2v", frames=10, tier=6, tuned=_TUNED_SVD,
                    monkeypatch=monkeypatch)
        assert pol["mode"] == MODE_SEQUENTIAL_OFFLOAD, pol
        assert pol["offload"] is True
        assert any("升级 sequential_offload" in r for r in pol["reasons"])

    def test_registered_vram_triggers_sequential(self, monkeypatch):
        """登记值越水位（Wan 8.0GB > 8GB×95% 的原型场景）⇒ sequential。"""
        pol = _pick("svd-xt-i2v", frames=5, tier=8, tuned=_TUNED_SVD,
                    registered=8.0, monkeypatch=monkeypatch)
        assert pol["mode"] == MODE_SEQUENTIAL_OFFLOAD
        assert any("95% 水位线" in r for r in pol["reasons"])


# ══════════════════════════════════════════════════════════════════════
# 3. 能力声明过滤（layer 档双向锁）
# ══════════════════════════════════════════════════════════════════════

class TestCapabilityDeclaration:
    """layer_cpu_offload 只给显式声明支持它的引擎；反向也要证（声明了才给）。"""

    def test_layer_only_when_declared(self, monkeypatch):
        """登记 7.0GB > 8GB×60%：声明 ACTIVE ⇒ layer；不声明 ⇒ model（2c 常规）。"""
        pol = _pick("svd-xt-i2v", frames=5, tier=8, tuned=_TUNED_SVD,
                    supported=MP.ACTIVE_MODES, monkeypatch=monkeypatch)
        assert pol["mode"] == MODE_LAYER_CPU_OFFLOAD, pol
        assert any("60% 中间水位" in r for r in pol["reasons"])
        # 反例：同一输入不声明 ⇒ 拿不到 layer
        pol2 = _pick("svd-xt-i2v", frames=5, tier=8, tuned=_TUNED_SVD,
                     supported=None, monkeypatch=monkeypatch)
        assert pol2["mode"] == MODE_MODEL_OFFLOAD

    def test_legacy_modes_exclude_layer(self):
        """_LEGACY_MODES 常量本身不含 layer（向后兼容层的硬约束）。"""
        assert MODE_LAYER_CPU_OFFLOAD not in MP._LEGACY_MODES
        assert MODE_LAYER_CPU_OFFLOAD in MP.ACTIVE_MODES

    def test_planned_layer_disk_never_returned(self, monkeypatch):
        """layer_disk_offload 是预告：任何输入都不返回它，只在 planned_modes 里。"""
        for tier in (8, 24):
            for supported in (None, MP.ACTIVE_MODES):
                pol = _pick("svd-xt-i2v", frames=10, tier=tier,
                            tuned=_TUNED_SVD, supported=supported,
                            monkeypatch=monkeypatch)
                assert pol["mode"] != MODE_LAYER_DISK_OFFLOAD
                assert MODE_LAYER_DISK_OFFLOAD in pol["planned_modes"]

    def test_unknown_prefer_mode_ignored(self, monkeypatch):
        """反例：prefer_mode 是 PLANNED（layer_disk）或引擎未声明 ⇒ 忽略并留痕，
        绝不静默采用一个执行端没有的模式。"""
        tun = dict(_TUNED_SVD, prefer_mode=MODE_LAYER_DISK_OFFLOAD)
        pol = _pick("svd-xt-i2v", frames=5, tier=8, tuned=tun,
                    monkeypatch=monkeypatch)
        assert pol["mode"] == MODE_MODEL_OFFLOAD
        assert any("尚未实现" in r for r in pol["reasons"])

    def test_prefer_whole_gpu_never_shortcuts(self, monkeypatch):
        """反例：prefer_mode=whole_gpu 不许走分支 0 绕过余量检查（只能走分支 1
        的双条件：offload=False + 15% 余量）。"""
        tun = {"decode_chunk_size": 1, "offload": True, "prefer_mode": MODE_WHOLE_GPU}
        pol = _pick("svd-xt-i2v", frames=5, tier=8, tuned=tun,
                    monkeypatch=monkeypatch)
        assert pol["mode"] != MODE_WHOLE_GPU, "whole_gpu 只能凭 offload=False+余量进"

    def test_no_offload_flag_downgrades_honestly(self, monkeypatch):
        """offload=False 但整卡下限超 15% 余量 ⇒ 诚实改判 model_offload（宁慢勿炸）。"""
        pol = _pick("sdxl-t2i", tier=8, tuned=dict(_TUNED_NO_OFFLOAD, prefer_mode=""),
                    monkeypatch=monkeypatch)
        # whole_gpu floor 对 sdxl 无实测 ⇒ None ⇒ 走「无依据」改判支
        assert pol["mode"] == MODE_MODEL_OFFLOAD
        assert any("诚实改判" in r for r in pol["reasons"])


# ══════════════════════════════════════════════════════════════════════
# 4. 探测/注入语义
# ══════════════════════════════════════════════════════════════════════

class TestProbeAndInjection:
    def test_injection_beats_probe(self, monkeypatch):
        """调用方注入的显存优先于现场探测（注入 8GB，探测假报 99GB ⇒ 按 8GB 决策）。"""
        monkeypatch.setattr(MP, "probe_vram", lambda: {"free_gb": 91.0, "total_gb": 99.0})
        pol = pick_memory_policy("svd-xt-i2v", frames=5, tuned=_TUNED_SVD,
                                 free_vram_gb=7.36, total_vram_gb=8.0,
                                 registered_vram_gb=7.0)
        assert pol["total_vram_gb"] == 8.0
        assert pol["mode"] == MODE_MODEL_OFFLOAD

    def test_probe_failure_is_conservative(self, monkeypatch):
        """探测不到（无 CUDA）⇒ 保守 model_offload + 明说「无法探测」。"""
        monkeypatch.setattr(MP, "probe_vram", lambda: None)
        pol = pick_memory_policy("svd-xt-i2v", frames=5, tuned=_TUNED_SVD,
                                 registered_vram_gb=7.0)
        assert pol["mode"] == MODE_MODEL_OFFLOAD
        assert any("无法探测显存" in r for r in pol["reasons"])
        assert pol["free_vram_gb"] is None and pol["total_vram_gb"] is None

    def test_reasons_never_empty_on_any_path(self, monkeypatch):
        """所有分支的 reasons 都非空（决策必须可见，同 R9 精神）。"""
        monkeypatch.setattr(MP, "probe_vram",
                            lambda: {"free_gb": 7.36, "total_gb": 8.0})
        cases = [
            dict(model_id="svd-xt-i2v", frames=10, tuned=_TUNED_SVD,
                 registered_vram_gb=7.0),
            dict(model_id="sdxl-t2i", tuned=_TUNED_SDXL, registered_vram_gb=7.0),
            dict(model_id="sd15-t2i", tuned={"offload": True},
                 registered_vram_gb=3.0),
            dict(model_id="unknown-model", tuned=_TUNED_NO_OFFLOAD,
                 registered_vram_gb=None, supported_modes=MP.ACTIVE_MODES),
        ]
        for kw in cases:
            pol = pick_memory_policy(**kw)
            assert pol["reasons"], kw

    def test_unknown_model_conservative_path(self, monkeypatch):
        """未登记模型 + 无实测 ⇒ model_offload 保守（不猜能力）。"""
        monkeypatch.setattr(MP, "probe_vram",
                            lambda: {"free_gb": 22.08, "total_gb": 24.0})
        pol = pick_memory_policy("mystery-model", frames=0,
                                 tuned={"offload": True, "decode_chunk_size": 2})
        assert pol["mode"] == MODE_MODEL_OFFLOAD
        assert pol["floor_gb"] is None
        assert any("保守" in r for r in pol["reasons"])


# ══════════════════════════════════════════════════════════════════════
# 5. floor 估计（Task 6 预算模型的输入常量，锁值防漂）
# ══════════════════════════════════════════════════════════════════════

class TestFloorEstimates:
    def test_measured_fits(self):
        """_MEASURED 拟合值逐个锁（SVD 双模式 + SDXL 双档）。"""
        assert MP.estimate_floor_gb("svd-xt-i2v", 5, MODE_MODEL_OFFLOAD) == 4.65
        assert MP.estimate_floor_gb("svd-xt-i2v", 10, MODE_MODEL_OFFLOAD) == 6.20
        assert MP.estimate_floor_gb("svd-xt-i2v", 5, MODE_WHOLE_GPU) == 5.83
        assert MP.estimate_floor_gb("sdxl-t2i", 0, MODE_MODEL_OFFLOAD) == 5.21
        assert MP.estimate_floor_gb("sdxl-t2i", 0, MODE_SEQUENTIAL_OFFLOAD) == 3.76

    def test_unknown_returns_none_not_guess(self):
        """无依据 ⇒ None（不拿 params_b 之外的口径编数字）。"""
        assert MP.estimate_floor_gb("sd15-t2i", 0, MODE_MODEL_OFFLOAD) is None
        assert MP.estimate_floor_gb("mystery", 5, MODE_MODEL_OFFLOAD) is None

    def test_params_fallback_only_when_no_measured(self):
        """params_b 粗估（2B/参×1.3）只在无实测表时用。"""
        v = MP.estimate_floor_gb("mystery", 0, MODE_MODEL_OFFLOAD, params_b=1.5)
        assert v == 3.9   # 1.5×2×1.3
        # 有实测表的模型不吃粗估（实测优先）
        assert MP.estimate_floor_gb("svd-xt-i2v", 5, MODE_MODEL_OFFLOAD,
                                    params_b=99.0) == 4.65


# ══════════════════════════════════════════════════════════════════════
# 6. 返回契约稳定性
# ══════════════════════════════════════════════════════════════════════

class TestPolicyContract:
    KEYS = {"mode", "offload", "decode_chunk_size", "quant", "floor_gb",
            "free_vram_gb", "total_vram_gb", "reasons", "planned_modes"}

    def test_key_set_stable(self, monkeypatch):
        monkeypatch.setattr(MP, "probe_vram",
                            lambda: {"free_gb": 7.36, "total_gb": 8.0})
        pol = pick_memory_policy("svd-xt-i2v", frames=5, tuned=_TUNED_SVD,
                                 registered_vram_gb=7.0)
        assert set(pol) == self.KEYS

    def test_mode_always_active(self, monkeypatch):
        """mode 必是 ACTIVE_MODES 之一（layer_disk 是预告，执行端拿不到）。"""
        monkeypatch.setattr(MP, "probe_vram",
                            lambda: {"free_gb": 7.36, "total_gb": 8.0})
        for supported in (None, MP.ACTIVE_MODES):
            pol = pick_memory_policy("svd-xt-i2v", frames=5, tuned=_TUNED_SVD,
                                     registered_vram_gb=7.0,
                                     supported_modes=supported)
            assert pol["mode"] in MP.ACTIVE_MODES

    def test_real_probe_returns_something_or_none(self):
        """真机探测契约：有卡返回合理 dict，无卡返回 None（都不许炸）。

        ★ 2026-10-28 扩契约（P1.5）：返回里多了 `torch_free_gb` / `smi_free_gb`
          两个原始读数 —— 因为 `free_gb` 已改为两者较小值，必须保留原始值才能诊断
          「两个读数差多少」（实测 WDDM 下 torch 对别的进程占用无感，差可达 4GB+）。
          故这里从"键集合完全相等"改成"必需键都在 + free_gb 不大于任一原始读数"，
          后者才是这次改动真正要锁的语义。
        """
        v = probe_vram()
        assert v is None or (
            {"free_gb", "total_gb"} <= set(v)
            and 0 < v["total_gb"] < 1024
        )
        if v is not None:
            for k in ("torch_free_gb", "smi_free_gb"):
                if v.get(k) is not None:
                    assert v["free_gb"] <= v[k] + 1e-9, (
                        "free_gb 必须是保守值，不得大于 %s" % k)
