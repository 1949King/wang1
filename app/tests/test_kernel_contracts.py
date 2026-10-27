# -*- coding: utf-8 -*-
"""契约层测试 —— P2 · 2026-10-28。

## 为什么契约也要有测试

契约不是注释，是**运行时会用的判据**：`caps.violations()` 每个请求都跑一遍，
`KernelReport.to_dict()` 每次回执都要用。它们写错了不会崩，只会安静地少检查一项：

① **`caps` 跨字段自洽漏一条** ⇒ 一个 `cfg_mode=cat` 但 batch 乘数写 1 的族能通过体检，
   然后每步 chunk(2) 失败被兜底吞掉，出图"正常"但是没引导。
② **`used=False` 却不给原因** ⇒ 用户看到"生成失败"，我们拿不到"为什么没用内核"。
   所以 `to_dict()` 自带一条自填原因，这里锁住它。
③ **契约版本号**：没有版本号，下游（前端诊断面板 / 证据台账）无法判断字段语义变过。
"""
from __future__ import annotations

import pytest

from app.core.neural.kernel import contracts as C


# ══════════════════════════════════════════════════════════════════
# GenRequest
# ══════════════════════════════════════════════════════════════════

def test_gen_request_is_frozen():
    """请求是只读的：跑一次生成的过程中不被中途改写（可复现的前提）。"""
    import dataclasses

    req = C.GenRequest(family="sd15", model_id="sd15-t2i")
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.prompt = "改一下"  # type: ignore[misc]


def test_gen_request_is_i2i_by_image_path():
    t2i = C.GenRequest(family="sd15", model_id="m")
    i2i = C.GenRequest(family="sd15", model_id="m", image_path="a.png")
    assert t2i.is_i2i() is False
    assert i2i.is_i2i() is True


def test_gen_request_defaults_are_neutral():
    """默认值必须是"没要求"而不是"某种实现选择"：0 表示取默认，由 adapter 翻译。"""
    req = C.GenRequest(family="sd15", model_id="m")
    assert (req.width, req.height, req.steps, req.seed) == (0, 0, 0, 0)
    assert req.cfg == 0.0 and req.strength == 0.0
    assert req.batch == 1 and req.frames == 0


# ══════════════════════════════════════════════════════════════════
# AdapterCaps.violations
# ══════════════════════════════════════════════════════════════════

def test_caps_sd15_shape_is_clean():
    caps = C.AdapterCaps(cfg_mode="cat", cfg_batch_multiplier=2, cond_keys=("prompt_embeds",),
                         latent_scale="init_noise_sigma", verified=C.UNVERIFIED)
    assert caps.violations() == []


def test_caps_cat_requires_multiplier_two():
    """`cat` 但乘数不是 2 ⇒ 必须报出来（否则每步 chunk(2) 静默失败）。"""
    caps = C.AdapterCaps(cfg_mode="cat", cfg_batch_multiplier=1)
    bad = caps.violations()
    assert any("cfg_batch_multiplier" in x for x in bad), bad


def test_caps_none_requires_multiplier_one():
    caps = C.AdapterCaps(cfg_mode="none", cfg_batch_multiplier=2)
    assert any("cfg_batch_multiplier" in x for x in caps.violations())


@pytest.mark.parametrize("field,value,needle", [
    ("cfg_mode", "magic", "cfg_mode"),
    ("latent_scale", "guess", "latent_scale"),
    ("vae_decode", "guess", "vae_decode"),
    ("scheduler_family", "guess", "scheduler_family"),
    ("timestep_kind", "guess", "timestep_kind"),
    ("verified", "大概行", "verified"),
])
def test_caps_rejects_unknown_enum_values(field, value, needle):
    """白名单字段写了个不在词表里的值 —— 必须拒绝，不能按"未知即支持"放行。"""
    caps = C.AdapterCaps(**{field: value})
    assert any(needle in x for x in caps.violations())


def test_caps_latent_rank_five_requires_chunked_decode():
    """视频族（rank=5）必须逐块解码；否则一次性解 14 帧会直接炸显存。"""
    caps = C.AdapterCaps(latent_rank=5, vae_decode="scalar_factor")
    assert any("chunked_temporal" in x for x in caps.violations())

    ok = C.AdapterCaps(latent_rank=5, vae_decode="chunked_temporal", cfg_mode="none")
    assert ok.violations() == []


def test_caps_latent_rank_only_4_or_5():
    caps = C.AdapterCaps(latent_rank=3)
    assert any("latent_rank" in x for x in caps.violations())


def test_caps_allow_cfg_merge_only_for_two_pass():
    caps = C.AdapterCaps(cfg_mode="cat", cfg_batch_multiplier=2, allow_cfg_merge=True)
    assert any("allow_cfg_merge" in x for x in caps.violations())


# ══════════════════════════════════════════════════════════════════
# ParityContract
# ══════════════════════════════════════════════════════════════════

def test_parity_missing_lists_unfilled_fields():
    pc = C.ParityContract(fields={"a": 1, "c": True})
    assert pc.missing(("a", "b", "c")) == ["b"]
    assert pc.missing(("a", "c")) == []


def test_parity_defaults_are_conservative():
    """默认容差不能是"随便过"：1e-3 / 35dB 是规范 §4.4 写死的判据。"""
    pc = C.ParityContract()
    assert pc.tensor_rtol == 1e-3
    assert pc.psnr_min_db == 35.0


# ══════════════════════════════════════════════════════════════════
# KernelReport
# ══════════════════════════════════════════════════════════════════

def test_report_without_reason_gets_self_filled_reason():
    """`used=False` 且没给原因 ⇒ to_dict 自填。锁住这条，否则"静默回退"就这样发生。"""
    rep = C.KernelReport(used=False, family="sd15")
    d = rep.to_dict()
    assert d["used"] is False
    assert d["rejected_reason"], "used=False 必须带原因"
    assert "内部错误" in d["rejected_reason"]


def test_report_keeps_given_reason():
    rep = C.KernelReport(used=False, family="sd15", rejected_reason="内核未启用")
    assert rep.to_dict()["rejected_reason"] == "内核未启用"


def test_report_dict_has_required_keys():
    """前端诊断面板与证据台账依赖这组键；少键会让面板显示空白而不是报错。"""
    d = C.KernelReport(used=True, family="sdxl", steps=20).to_dict()
    for k in ("used", "family", "loop_owner", "steps", "rejected_reason",
              "breakdown", "contract_version"):
        assert k in d, k
    assert d["loop_owner"] == C.LOOP_UPSTREAM
    assert d["contract_version"] == C.CONTRACT_VERSION


def test_report_dict_is_a_copy():
    """回执里的 breakdown 必须是拷贝：外部改它不能反向污染 report。"""
    rep = C.KernelReport(used=True, breakdown={"loop": 100})
    d = rep.to_dict()
    d["breakdown"]["loop"] = 999
    assert rep.breakdown["loop"] == 100


# ══════════════════════════════════════════════════════════════════
# RunState / DenoiseOutput
# ══════════════════════════════════════════════════════════════════

def test_run_state_defaults_do_not_guide():
    """默认不引导：宁可少做一次减法，也不要在没算过的前提下默认开 CFG。"""
    st = C.RunState(timesteps=[1, 2, 3], latents=None)
    assert st.do_guidance is False
    assert st.cfg_scale == 1.0
    assert st.guidance_rescale == 0.0
    assert st.extra_step_kwargs == {}


def test_run_state_extra_kwargs_not_shared_between_instances():
    """可变默认值必须是 factory，否则两次运行共用一个 dict —— 经典串状态。"""
    a = C.RunState(timesteps=[], latents=None)
    b = C.RunState(timesteps=[], latents=None)
    a.extra_step_kwargs["eta"] = 0.5
    assert b.extra_step_kwargs == {}


def test_denoise_output_defaults():
    st = C.RunState(timesteps=[], latents=None)
    out = C.DenoiseOutput(latents="x", state=st)
    assert out.cancelled is False and out.step_count == 0


def test_contract_version_is_pinned():
    """版本号变化必须在 CHANGELOG 有迁移说明；测试先拦住"悄悄改"。"""
    assert C.CONTRACT_VERSION == "1.1"
