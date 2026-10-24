# -*- coding: utf-8 -*-
"""显存预算模型单测（V4.47.0）—— vram_budget 数值锁 + 与 memory_policy 交叉锁。

锁死六件事：
  ① required_gb 公式与关键数值（含 **sdxl@1280²@8GB = 7.55 ≤ 7.6 贴线可过**
     与 **sdxl whole_gpu@8GB = 8.0 > 6.8 不过** 一对边界）；
  ② admits 判据的 headroom 与 memory_policy **同源**（0.85 / 0.95，禁另立数值）；
  ③ best_mode 的快慢排序（SVD 全模式 steady=None ⇒ first_s tiebreak，
     防「dict 顺序决胜」的隐性巧合）；
  ④ **交叉一致性**：对 9 配置 × 4 档位全矩阵，policy 现场决策选中的模式
     必须①在预算表有行、②有 floor 依据时必须被预算准入——两表不许互相打脸；
  ⑤ 反漂移：预算表与 memory_policy._MEASURED / video_gen 登记表**共用**的数字
     必须逐项相等（改一边忘另一边 = 红灯）；
  ⑥ 诚实契约：basis 三值制、estimated ⇒ evidence 必带「需标定」、
     measured ⇒ evidence 必带 文件:行号、无依据 ⇒ None 不编数字。

⚠️ 已知分歧（有意保留，见报告 §5）：sd15 预算最优是 whole_gpu（4.34GB/3.08s
实测），但 policy 无 sd15 实测登记 ⇒ 运行时保守取 model_offload。测试锁的是
「policy 选的模式预算必须准入」，不是「两表最优必须相同」——前者是安全不变量。
"""

import re

import pytest

from app.core.neural import memory_policy as MP
from app.core.neural import vram_budget as VB
from app.core.neural.memory_policy import (
    MODE_LAYER_CPU_OFFLOAD,
    MODE_MODEL_OFFLOAD,
    MODE_SEQUENTIAL_OFFLOAD,
    MODE_WHOLE_GPU,
    estimate_floor_gb,
    pick_memory_policy,
)

# ── 调优表 / 登记值（与注册表现状一致；反漂移由 TestAntiDrift 单独锁）──
_TUNED = {
    "sd15-t2i": {"steps": 20, "decode_chunk_size": 1, "offload": True},
    "sdxl-t2i": {"decode_chunk_size": 1, "offload": True,
                 "prefer_mode": "model_offload"},
    "svd-xt-i2v": {"steps": 14, "decode_chunk_size": 1, "offload": True},
    "wan21-t2v-1.3b": {"steps": 25, "decode_chunk_size": 2, "offload": True},
    "wan22-ti2v-5b": {"steps": 25, "decode_chunk_size": 2, "offload": True},
}
_REG = {"sd15-t2i": 3.0, "sdxl-t2i": 7.0, "svd-xt-i2v": 7.0,
        "wan21-t2v-1.3b": 8.2, "wan22-ti2v-5b": 8.0}

_BASIS_OK = {"measured", "estimated", "registered"}


@pytest.fixture(autouse=True)
def _no_real_probe(monkeypatch):
    """双保险：即使未来代码漏注入显存，也不许真探测泄漏进决策。"""
    monkeypatch.setattr(MP, "probe_vram", lambda: None)


# ══════════════════════════════════════════════════════════════════════
# 1. required_gb 公式与关键数值
# ══════════════════════════════════════════════════════════════════════

class TestRequiredGbFormula:
    """required = base × (1-act + act×面积比) + per_frame × frames。"""

    def test_native_resolution_is_base(self):
        """原生分辨率（或未给）⇒ 缩放=1 ⇒ required 就是登记 base。"""
        assert VB.required_gb("sd15-t2i", "whole_gpu", 0, 512, 512) == 4.34
        assert VB.required_gb("sdxl-t2i", "model_offload", 0, 1024, 1024) == 5.21
        assert VB.required_gb("sdxl-t2i", "model_offload") == 5.21
        assert VB.required_gb("svd-xt-i2v", "model_offload", 0) == 3.10

    def test_resolution_scales_only_act_share(self):
        """分辨率只缩放激活份（act_share 加权），权重份不动。"""
        # sd15 whole act_share=0.09：4.34×(0.91+0.09×2.25)=4.83
        assert VB.required_gb("sd15-t2i", "whole_gpu", 0, 768, 768) == 4.83
        # sd15 model act_share=0.8：0.8×(0.2+0.8×2.25)=1.6
        assert VB.required_gb("sd15-t2i", "model_offload", 0, 768, 768) == 1.6
        # sdxl model act_share=0.8：5.21×(0.2+0.8×0.5625)=3.39
        assert VB.required_gb("sdxl-t2i", "model_offload", 0, 768, 768) == 3.39
        # sdxl model 超原生：5.21×(0.2+0.8×1.5625)=7.55（★ 贴 8GB 线）
        assert VB.required_gb("sdxl-t2i", "model_offload", 0, 1280, 1280) == 7.55
        assert VB.required_gb("sdxl-t2i", "layer_cpu_offload", 0, 1280, 1280) == 9.53
        assert VB.required_gb("sdxl-t2i", "whole_gpu", 0, 1280, 1280) == 8.54

    def test_frames_linear_term(self):
        """帧数线性项：base + per_frame × frames（SVD 双模式分别锁）。"""
        assert VB.required_gb("svd-xt-i2v", "model_offload", 14) == 7.44
        assert VB.required_gb("svd-xt-i2v", "model_offload", 25) == 10.85
        assert VB.required_gb("svd-xt-i2v", "whole_gpu", 25) == 13.23
        assert VB.required_gb("svd-xt-i2v", "sequential_offload", 25) == 11.12

    def test_image_model_ignores_frames(self):
        """图像模型 per_frame=0 ⇒ 传帧数不改变结果（防呆）。"""
        assert VB.required_gb("sd15-t2i", "whole_gpu", 99, 512, 512) == 4.34
        assert VB.required_gb("sdxl-t2i", "model_offload", 99, 1024, 1024) == 5.21

    def test_negative_frames_clamped(self):
        """负帧数钳到 0（不产生负需求）。"""
        assert VB.required_gb("svd-xt-i2v", "model_offload", -5) == 3.10

    def test_unknown_model_or_mode_returns_none(self):
        """无依据 ⇒ None，不编数字（含预告中的 layer_disk_offload）。"""
        assert VB.required_gb("nope", "whole_gpu") is None
        assert VB.required_gb("sd15-t2i", "layer_disk_offload") is None
        assert VB.required_gb("sdxl-t2i", "sequential_offload") is not None
        # Wan 没有 whole_gpu 行（policy 永不选它，也不编一个）
        assert VB.required_gb("wan21-t2v-1.3b", "whole_gpu") is None


# ══════════════════════════════════════════════════════════════════════
# 2. admits 边界（headroom 同源 + 贴线案例）
# ══════════════════════════════════════════════════════════════════════

class TestAdmitsBoundary:
    """准入 = required ≤ tier × headroom(mode)。"""

    def test_headroom_same_source_as_policy(self):
        """headroom 必须与 memory_policy 同源（禁两套数值）。"""
        assert VB._headroom(MODE_WHOLE_GPU) == MP._WHOLE_GPU_HEADROOM == 0.85
        for mode in (MODE_MODEL_OFFLOAD, MODE_SEQUENTIAL_OFFLOAD,
                     MODE_LAYER_CPU_OFFLOAD):
            assert VB._headroom(mode) == MP._OFFLOAD_HIGH_WATER == 0.95

    def test_sdxl_1280_hairstline_pass_at_8gb(self):
        """★ 贴线案例：7.55 ≤ 8×0.95=7.6 ⇒ 过（余量仅 0.05GB）。"""
        assert VB.admits("sdxl-t2i", "model_offload", 8, 0, 1280, 1280) is True

    def test_sdxl_whole_gpu_fails_at_8gb(self):
        """whole_gpu 8.0 > 8×0.85=6.8 ⇒ 不过（420s 被杀的实测口径）。"""
        assert VB.admits("sdxl-t2i", "whole_gpu", 8, 0, 1024, 1024) is False
        # 反面对照：24GB 大卡上 whole 也不短路（8.0 ≤ 20.4 会过，但 policy
        # 的 prefer_mode 才是定稿机制——预算表只回答装不装得下）
        assert VB.admits("sdxl-t2i", "whole_gpu", 24, 0, 1024, 1024) is True

    def test_sdxl_1536_exceeds_8gb(self):
        """1536² 激活 ×2.25 ⇒ model 10.42 > 7.6 ⇒ 不过（预算比 policy 更细：
        policy 不看分辨率，这是已知盲区，见报告 §6）。"""
        assert VB.required_gb("sdxl-t2i", "model_offload", 0, 1536, 1536) == 10.42
        assert VB.admits("sdxl-t2i", "model_offload", 8, 0, 1536, 1536) is False

    def test_svd_frame_thresholds(self):
        """SVD 帧数门槛：8GB 上 14 帧过 / 25 帧不过；12GB 上 25 帧过。"""
        assert VB.admits("svd-xt-i2v", "model_offload", 8, 14) is True
        assert VB.admits("svd-xt-i2v", "model_offload", 8, 22) is False
        assert VB.admits("svd-xt-i2v", "model_offload", 12, 25) is True
        assert VB.admits("svd-xt-i2v", "model_offload", 8, 25) is False

    def test_wan_registered_thresholds(self):
        """Wan：8GB 上登记 8.2>7.6 不过 / sequential 3.0 过；12GB 上 model 过。"""
        assert VB.admits("wan21-t2v-1.3b", "model_offload", 8, 14) is False
        assert VB.admits("wan21-t2v-1.3b", "sequential_offload", 8, 14) is True
        assert VB.admits("wan21-t2v-1.3b", "model_offload", 12, 14) is True
        assert VB.admits("wan22-ti2v-5b", "model_offload", 8, 14) is False
        assert VB.admits("wan22-ti2v-5b", "sequential_offload", 8, 14) is True

    def test_unknown_model_never_admits(self):
        assert VB.admits("nope", "whole_gpu", 64) is False
        assert VB.admits("sd15-t2i", "layer_disk_offload", 64) is False


# ══════════════════════════════════════════════════════════════════════
# 3. best_mode 快慢排序
# ══════════════════════════════════════════════════════════════════════

class TestBestMode:
    """ admitted 且实测最快；全无实测时效 ⇒ None。"""

    def test_sd15_whole_gpu_fastest_when_admitted(self):
        """sd15@8GB：whole 3.08s 快于 model 4.17s 且 4.34≤6.8 ⇒ whole 最优。"""
        best = VB.best_mode("sd15-t2i", 8, 0, 512, 512)
        assert best["mode"] == MODE_WHOLE_GPU
        assert best["steady_s"] == 3.08
        assert best["basis"] == "measured"
        assert best["required_gb"] == 4.34

    def test_sd15_small_card_falls_back_to_model(self):
        """5GB 卡：whole 4.34 > 5×0.85=4.25（差 0.09GB 落选，贴线不过）
        ⇒ model_offload（预算表的「小卡结论」）。6GB 上 whole 4.34 ≤ 5.1 会回头。"""
        best = VB.best_mode("sd15-t2i", 5, 0, 512, 512)
        assert best["mode"] == MODE_MODEL_OFFLOAD
        assert VB.best_mode("sd15-t2i", 6, 0, 512, 512)["mode"] == MODE_WHOLE_GPU

    def test_svd_first_s_tiebreak_beats_dict_order(self):
        """★ SVD 全模式 steady=None ⇒ 早年靠 dict 顺序决胜是隐性巧合。
        first_s tiebreak：model(40.0s) 必须胜过 sequential(None)。"""
        best = VB.best_mode("svd-xt-i2v", 8, 14, 576, 1024)
        assert best["mode"] == MODE_MODEL_OFFLOAD
        assert best["first_s"] == 40.0
        assert best["basis"] == "measured"

    def test_svd_25f_8gb_nothing_admitted(self):
        """8GB 25 帧：三档全不过 ⇒ None（调用方必须按「不可用」处理）。"""
        assert VB.best_mode("svd-xt-i2v", 8, 25, 576, 1024) is None

    def test_wan_small_card_sequential_estimated(self):
        """Wan@8GB：model 不过、sequential 过但无实测时效 ⇒ estimated 返回。"""
        best = VB.best_mode("wan21-t2v-1.3b", 8, 14, 480, 832)
        assert best["mode"] == MODE_SEQUENTIAL_OFFLOAD
        assert best["basis"] == "estimated"
        assert best["steady_s"] is None

    def test_wan_big_card_model_offload_registered(self):
        """Wan@12GB：model 登记值准入（两个模式都无时效 ⇒ dict 序稳定决胜）。"""
        best = VB.best_mode("wan21-t2v-1.3b", 12, 14, 480, 832)
        assert best["mode"] == MODE_MODEL_OFFLOAD
        assert best["basis"] == "registered"

    def test_supported_modes_filter(self):
        """调用方可收窄候选（未来 UI「只用 offload 系」场景）。"""
        best = VB.best_mode("sdxl-t2i", 8, 0, 1024, 1024,
                            supported_modes=(MODE_MODEL_OFFLOAD,))
        assert best["mode"] == MODE_MODEL_OFFLOAD
        # whole_gpu@8GB 不过 ⇒ 只许它时返回 None
        assert VB.best_mode("sdxl-t2i", 8, 0, 1024, 1024,
                            supported_modes=(MODE_WHOLE_GPU,)) is None

    def test_unknown_model_none(self):
        assert VB.best_mode("nope", 24) is None


# ══════════════════════════════════════════════════════════════════════
# 4. 与 memory_policy 的交叉一致性（本文件的核心锁）
# ══════════════════════════════════════════════════════════════════════

class TestCrossConsistencyWithPolicy:
    """9 配置 × 4 档位：policy 现场决策 vs 预算表准入，不许互相打脸。

    不变量 A（行覆盖）：policy 选中的模式必须在预算表有行——
      「policy 说跑 sequential、预算表查无此档」= 语义漂移。
    不变量 B（有依据必准入）：policy 对该模式有 floor 实测依据时，
      预算表必须准入——「预算说装不下、policy 的实测说装得下」= 数值漂移。
    """

    @pytest.mark.parametrize("cfg_idx", range(len(VB.ADMISSION_CONFIGS)))
    @pytest.mark.parametrize("tier", list(VB.BUDGET_TIERS))
    def test_policy_pick_is_budget_consistent(self, cfg_idx, tier):
        model_id, frames, w, h, _cap = VB.ADMISSION_CONFIGS[cfg_idx]
        pol = pick_memory_policy(
            model_id, frames=frames, tuned=_TUNED[model_id],
            registered_vram_gb=_REG[model_id],
            free_vram_gb=round(tier * 0.92, 2), total_vram_gb=float(tier))
        mode = pol["mode"]
        # 不变量 A
        assert mode in VB.MODELS[model_id]["modes"], (
            model_id, tier, frames, mode, "policy 选的模式预算表无行")
        # 不变量 B（floor=None ⇒ 无依据，双方都闭嘴）
        floor = estimate_floor_gb(model_id, frames, mode)
        if floor is not None:
            assert VB.admits(model_id, mode, tier, frames, w, h), (
                model_id, tier, frames, w, h, mode, floor,
                "policy 实测 floor 在线内但预算表不准入")

    def test_budget_never_admits_what_policy_floor_rejects(self):
        """反向锁：预算准入的模式，若 policy 有同模式 floor 依据，
        该依据也必须在线内（防预算数字比实测还松）。"""
        for model_id, frames, w, h, _cap in VB.ADMISSION_CONFIGS:
            for tier in VB.BUDGET_TIERS:
                for mode in VB.MODELS[model_id]["modes"]:
                    if not VB.admits(model_id, mode, tier, frames, w, h):
                        continue
                    floor = estimate_floor_gb(model_id, frames, mode)
                    if floor is None:
                        continue
                    line = tier * VB._headroom(mode)
                    assert floor <= line, (model_id, tier, frames, mode, floor, line)

    def test_sd15_known_divergence_is_documented(self):
        """★ 已知分歧（有意保留）：sd15 预算最优 whole_gpu，引擎实跑
        model_offload（policy 无 sd15 实测登记 ⇒ 保守默认）。
        锁住它以免将来「顺手统一」时忘记这是待办而不是 bug。"""
        pol = pick_memory_policy(
            "sd15-t2i", frames=0, tuned=_TUNED["sd15-t2i"],
            registered_vram_gb=_REG["sd15-t2i"],
            free_vram_gb=7.36, total_vram_gb=8.0)
        best = VB.best_mode("sd15-t2i", 8, 0, 512, 512)
        assert pol["mode"] == MODE_MODEL_OFFLOAD
        assert best["mode"] == MODE_WHOLE_GPU
        # 安全不变量仍然成立：policy 选的模式预算准入
        assert VB.admits("sd15-t2i", pol["mode"], 8, 0, 512, 512)


class TestAntiDrift:
    """两表共用的数字必须逐项相等（改一边忘另一边 = 红灯）。"""

    def test_svd_fits_equal_memory_policy(self):
        m = VB.MODELS["svd-xt-i2v"]["modes"]
        assert m["model_offload"]["required_gb"] == \
            MP._MEASURED["svd-xt-i2v"][MODE_MODEL_OFFLOAD]["base_gb"] == 3.10
        assert m["model_offload"]["per_frame_gb"] == \
            MP._MEASURED["svd-xt-i2v"][MODE_MODEL_OFFLOAD]["per_frame_gb"] == 0.31
        assert m["whole_gpu"]["required_gb"] == \
            MP._MEASURED["svd-xt-i2v"][MODE_WHOLE_GPU]["base_gb"] == 3.98
        assert m["whole_gpu"]["per_frame_gb"] == \
            MP._MEASURED["svd-xt-i2v"][MODE_WHOLE_GPU]["per_frame_gb"] == 0.37

    def test_sdxl_fits_equal_memory_policy(self):
        m = VB.MODELS["sdxl-t2i"]["modes"]
        assert m["model_offload"]["required_gb"] == \
            MP._MEASURED["sdxl-t2i"][MODE_MODEL_OFFLOAD]["base_gb"] == 5.21
        assert m["sequential_offload"]["required_gb"] == \
            MP._MEASURED["sdxl-t2i"][MODE_SEQUENTIAL_OFFLOAD]["base_gb"] == 3.76

    def test_wan_registered_equal_video_gen(self):
        """Wan model_offload 行 basis=registered ⇒ 必须等于 video_gen 登记值。"""
        from app.core.neural import video_gen
        reg = {mid: spec["vram_gb"] for mid, spec in video_gen.VIDEO_MODELS.items()}
        assert VB.MODELS["wan21-t2v-1.3b"]["modes"]["model_offload"]["required_gb"] \
            == reg["wan21-t2v-1.3b"] == 8.2
        assert VB.MODELS["wan22-ti2v-5b"]["modes"]["model_offload"]["required_gb"] \
            == reg["wan22-ti2v-5b"] == 8.0

    def test_headroom_constants_equal(self):
        assert VB._WHOLE_GPU_HEADROOM == MP._WHOLE_GPU_HEADROOM
        assert VB._OFFLOAD_HIGH_WATER == MP._OFFLOAD_HIGH_WATER

    def test_tuned_prefer_mode_consistent(self):
        """SDXL 注册表 prefer_mode=model_offload 与预算表最优一致（四档实测结论）。"""
        from app.core.neural import diffusers_image
        spec = diffusers_image.DIFFUSERS_IMAGE_MODELS["sdxl-t2i"]
        assert spec["prefer_mode"] == MODE_MODEL_OFFLOAD
        best = VB.best_mode("sdxl-t2i", 8, 0, 1024, 1024)
        assert best["mode"] == spec["prefer_mode"]


# ══════════════════════════════════════════════════════════════════════
# 5. admission_table 结构（UI/报告直接消费的形状）
# ══════════════════════════════════════════════════════════════════════

class TestAdmissionTable:
    def test_tiers_cover_dev_machine_and_upgrades(self):
        """档位表必须含 8GB（开发机实测基线）+ 12/16/24（升级预测）。"""
        assert VB.BUDGET_TIERS == (8, 12, 16, 24)

    def test_config_matrix_shape(self):
        """9 配置：sd15×2 / sdxl×3 / svd×2 / wan×2（模型 × 分辨率/帧数维度）。"""
        rows = VB.admission_table()
        assert len(rows) == len(VB.ADMISSION_CONFIGS) == 9
        kinds = [r["kind"] for r in rows]
        assert kinds.count("image") == 5 and kinds.count("video") == 4
        for row in rows:
            assert set(row["tiers"]) == {"8", "12", "16", "24"}
            assert row["caption"]
            for _tier, cell in row["tiers"].items():
                assert set(cell) == {"admitted_modes", "best", "note"}
                assert cell["admitted_modes"] == [
                    m for m in VB.MODELS[row["model_id"]]["modes"]
                    if m in cell["admitted_modes"]]
                if not cell["admitted_modes"]:
                    assert cell["note"] == "不可用"
                    assert cell["best"] is None
                elif cell["best"]["basis"] == "measured":
                    assert cell["note"] == "最优 %s" % cell["best"]["mode"]
                else:
                    assert cell["note"] == "可行未标定"

    def test_ram_gate_only_for_wan(self):
        """T5 内存门只挂在 Wan 上（其他模型 ram_gate 为空串）。"""
        for row in VB.admission_table():
            if row["model_id"].startswith("wan"):
                assert "20GB" in row["ram_gate"], row["model_id"]
            else:
                assert row["ram_gate"] == ""

    def test_custom_tiers(self):
        """档位可收窄（如只预测 12GB）。"""
        rows = VB.admission_table(tiers=(12,))
        assert all(set(r["tiers"]) == {"12"} for r in rows)

    def test_known_answers_8gb_row(self):
        """8GB 行的已知结论（报告 §2 同源，改数必须改报告）。"""
        rows = {r["model_id"] + "@" + str(r["frames"]): r
                for r in VB.admission_table()}
        # sd15 512²：whole+model 都准入，最优 whole
        cell = rows["sd15-t2i@0"]["tiers"]["8"]
        assert set(cell["admitted_modes"]) == {"whole_gpu", "model_offload"}
        # sdxl 1024²：whole 不过，最优 model（prefer_mode 一致）
        cell = rows["sdxl-t2i@0"]["tiers"]["8"]
        assert MODE_WHOLE_GPU not in cell["admitted_modes"]
        assert cell["best"]["mode"] == MODE_MODEL_OFFLOAD
        # svd 25 帧@8GB：全不过
        assert rows["svd-xt-i2v@25"]["tiers"]["8"]["note"] == "不可用"
        # wan21@8GB：只有 sequential
        cell = rows["wan21-t2v-1.3b@14"]["tiers"]["8"]
        assert cell["admitted_modes"] == ["sequential_offload"]
        assert cell["note"] == "可行未标定"


# ══════════════════════════════════════════════════════════════════════
# 6. step_cache_overhead（DeepCache 附加显存，架构常量推算）
# ══════════════════════════════════════════════════════════════════════

class TestStepCacheOverhead:
    """Σ(up_block 输出 × 2B)；视频 ×latent 帧数。

    ★ 2026-10-25 真机标定后由 estimated 转 **measured**（基准
      `scripts/bench_p0_cache.py overhead --model M`，真实 UNet 前向 hook 抓形状）：
      sd15@512 = 0.010GB / sdxl@1024 = 0.039GB / svd@576×1024(14 帧) = 0.093GB。
      旧值 0.004/0.018/0.144 是**算错的**（空间档位错位一级 + SDXL 幻影
      2560 通道 + 视频乘输出帧数），已在 vram_budget 里改正。
    """

    def test_arch_constants(self):
        assert VB.step_cache_overhead_gb("sd15-t2i", 0, 512, 512) == 0.010
        assert VB.step_cache_overhead_gb("sdxl-t2i", 0, 1024, 1024) == 0.039
        assert VB.step_cache_overhead_gb("sdxl-t2i", 0, 1280, 1280) == 0.061
        assert VB.step_cache_overhead_gb("svd-xt-i2v", 14, 576, 1024) == 0.093

    def test_video_multiplies_latent_frames_not_output_frames(self):
        """视频乘的是 latent 帧数（输出帧 /4+1），不是输出帧数。

        14 输出帧 ⇒ 4 latent 帧 ⇒ 4× 而非 14×（旧公式高估 3.5×）。
        """
        one = VB.step_cache_overhead_gb("svd-xt-i2v", 1, 576, 1024)
        fourteen = VB.step_cache_overhead_gb("svd-xt-i2v", 14, 576, 1024)
        # 输出 1 帧 ⇒ latent 1 帧；输出 14 帧 ⇒ latent 4 帧
        assert fourteen == pytest.approx(one * 4, abs=0.002)

    def test_resolution_scales_area(self):
        """768² 是 512² 的 2.25 倍面积 ⇒ overhead 同比例。"""
        a = VB.step_cache_overhead_gb("sd15-t2i", 0, 512, 512)
        b = VB.step_cache_overhead_gb("sd15-t2i", 0, 768, 768)
        assert b == pytest.approx(a * 2.25, abs=0.001)

    def test_video_defaults_14_frames(self):
        """视频模型 frames=0 时按 14 帧计（漫剧默认档），不返回 0。"""
        assert VB.step_cache_overhead_gb("svd-xt-i2v", 0, 576, 1024) == \
            VB.step_cache_overhead_gb("svd-xt-i2v", 14, 576, 1024)

    def test_unknown_arch_zero(self):
        """无架构常数的模型（Wan）⇒ 0.0（不猜）。"""
        assert VB.step_cache_overhead_gb("wan21-t2v-1.3b", 14) == 0.0
        assert VB.step_cache_overhead_gb("nope", 14) == 0.0

    def test_overhead_small_relative_to_base(self):
        """量级 sanity：缓存开销应远小于模型需求（百分之几）。"""
        for model_id, mode in (("sd15-t2i", "whole_gpu"), ("sdxl-t2i", "model_offload")):
            oh = VB.step_cache_overhead_gb(model_id)
            base = VB.required_gb(model_id, mode)
            assert oh < base * 0.1, (model_id, oh, base)


# ══════════════════════════════════════════════════════════════════════
# 7. resolution_scale 纯函数
# ══════════════════════════════════════════════════════════════════════

class TestResolutionScale:
    def test_area_ratio(self):
        assert VB.resolution_scale(768, 768, (512, 512)) == pytest.approx(2.25)
        assert VB.resolution_scale(576, 1024, (576, 1024)) == pytest.approx(1.0)
        assert VB.resolution_scale(1280, 1280, (1024, 1024)) == pytest.approx(1.5625)

    def test_degenerate_native_returns_one(self):
        """原生尺寸缺 0 ⇒ 视为 1.0（不除零）。"""
        assert VB.resolution_scale(512, 512, (0, 0)) == 1.0
        assert VB.resolution_scale(512, 512, (512, 0)) == 1.0


# ══════════════════════════════════════════════════════════════════════
# 8. 诚实契约（basis 三值制 + evidence 可追溯）
# ══════════════════════════════════════════════════════════════════════

class TestHonestyContract:
    def test_basis_values_and_evidence(self):
        """measured ⇒ evidence 带 文件:行号；estimated ⇒ 带「需标定」。"""
        for model_id, m in VB.MODELS.items():
            for mode, row in m["modes"].items():
                basis, ev = row["basis"], row["evidence"]
                assert basis in _BASIS_OK, (model_id, mode, basis)
                assert ev, (model_id, mode, "evidence 不许空")
                if basis == "measured":
                    assert re.search(r"[\w/]+\.py:\d+", ev), (model_id, mode, ev)
                elif basis == "estimated":
                    assert "需标定" in ev, (model_id, mode, ev)

    def test_no_per_frame_invention_for_wan(self):
        """Wan 每帧增量必须为 0（照抄 SVD 的 0.31 会造出与 policy 的矛盾，
        见 vram_budget.py wan21 注释）。"""
        for mid in ("wan21-t2v-1.3b", "wan22-ti2v-5b"):
            for mode, row in VB.MODELS[mid]["modes"].items():
                assert row["per_frame_gb"] == 0.0, (mid, mode)

    def test_svd_sequential_row_exists_for_policy(self):
        """policy 分支 2b 可对 SVD 返回 sequential ⇒ 预算表必须有行
        （否则交叉不变量 A 会红——这是本行的存在理由）。"""
        assert "sequential_offload" in VB.MODELS["svd-xt-i2v"]["modes"]

    def test_registered_rows_match_claim(self):
        """basis=registered 的行只允许出现在 Wan（唯一无本栈实测的族）。"""
        for model_id, m in VB.MODELS.items():
            for mode, row in m["modes"].items():
                if row["basis"] == "registered":
                    assert model_id.startswith("wan"), (model_id, mode)
