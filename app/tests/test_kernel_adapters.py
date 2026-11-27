# -*- coding: utf-8 -*-
"""适配器与引擎门禁测试 —— P2 · 2026-10-28。

## 这个文件只测"拒绝"，不测出图

出图等价性由 `scripts/bench_kernel_parity.py` 在真机上量（PSNR / 时延 / 显存）。
单测里碰真权重等于把测试绑在"这台机器有卡"上 —— 最后必然被跳过，等于没测。

所以这里锁的是**拒绝路径**，它们是"静默降级"最后一道闸：

① `caps.violations()` 必须空：声明不自洽的族不许跑。
② `parity` 基线字段必须填完：漏一项就意味着有一处语义没人负责（规范 §5.2）。
③ `run()` **永不抛异常**：内核是新增路径，任何异常都必须变成 `ok=False + 原因`，
   否则一次内核失败会中断用户生成，而回退到 pipe 本来是可以出图的。
④ `execution_device()` 在 offload 下必须拿到卡：拿不到就会在 `scheduler.step` 里
   报 device 不匹配 —— 报错点离根因三步远（SDXL 首跑就是这么挂的）。
"""
from __future__ import annotations

import pytest

from app.core.neural.kernel import engine as K


# ══════════════════════════════════════════════════════════════════
# 契约完整性
# ══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("family", ["sd15", "sdxl"])
def test_adapter_caps_are_self_consistent(family):
    ad = K.adapter_for(family)
    assert ad.caps.violations() == []


@pytest.mark.parametrize("family", ["sd15", "sdxl"])
def test_adapter_parity_baseline_is_complete(family):
    from app.core.neural.kernel.contracts import BASE_PARITY_FIELDS

    ad = K.adapter_for(family)
    missing = ad.parity.missing(BASE_PARITY_FIELDS)
    assert missing == [], "parity 基线漏填：%s" % missing


def test_sd15_caps_declare_cat_guidance():
    caps = K.adapter_for("sd15").caps
    assert caps.cfg_mode == "cat" and caps.cfg_batch_multiplier == 2
    assert caps.latent_scale == "init_noise_sigma"
    assert caps.latent_rank == 4


def test_sdxl_caps_match_sd15_shape_but_extra_cond():
    """SDXL 与前代在"怎么跑"上同构，差异全在条件与解码 —— 声明必须体现这一点。"""
    caps = K.adapter_for("sdxl").caps
    assert caps.cfg_mode == "cat" and caps.cfg_batch_multiplier == 2
    assert caps.latent_rank == 4
    assert "pooled" in caps.cond_keys and "time_ids" in caps.cond_keys


def test_sdxl_vae_scale_is_not_sd15_value():
    """0.13025 vs 0.18215 —— 写错会偏色/过曝且不报错，所以要在契约里可见。"""
    from app.core.neural.kernel.adapters.sdxl import _SDXL_SCALING_FACTOR

    assert _SDXL_SCALING_FACTOR == 0.13025
    assert K.adapter_for("sdxl").parity.fields["vae_scaling_factor"] == 0.13025


def test_unknown_family_yields_rejecting_adapter():
    """未注册族必须落到「一定拒绝」的 UnverifiedAdapter，不许走通用兜底。

    2026-10-31 更新：wan 已有真 adapter（V4.48.5，K5 4/4），「未知族」改用
    不存在的族名断言；wan 自身走 UNVERIFIED 拒绝路径由
    `test_wan_unverified_rejects_until_parity` 单独锁。
    """
    ad = K.adapter_for("hunyuan")   # 未注册族
    assert ad.family == "hunyuan"
    assert ad.validate_caps(), "未实现的族必须明确拒绝，而不是走通用兜底"
    assert type(ad).__name__ == "UnverifiedAdapter"


def test_wan_unverified_rejects_until_parity():
    """wan 有真 adapter 但 verified=UNVERIFIED ⇒ 必须仍能拒绝（parity 过前不许跑）。"""
    ad = K.adapter_for("wan")
    assert ad.family == "wan"
    assert type(ad).__name__ == "WanAdapter"
    # caps 自洽（契约完整性），但 verified 状态是 UNVERIFIED
    assert ad.caps.violations() == []
    from app.core.neural.kernel.contracts import UNVERIFIED
    assert ad.caps.verified == UNVERIFIED
    # 绑定前体检不因 UNVERIFIED 报错（拒绝发生在 validate() 的 parity 门槛），
    # 但 run() 必须拒绝 —— 这里只锁「不是放行」这一个语义。
    assert not ad.caps.verified == "verified"


# ══════════════════════════════════════════════════════════════════
# 组件袋与执行设备
# ══════════════════════════════════════════════════════════════════

class _Pipe:
    """假 pipeline：带上 `_execution_device`（offload 后上游就是这么给的）。"""

    def __init__(self, exec_device="cuda:0") -> None:
        self._execution_device = exec_device
        self.scheduler = object()
        self.unet = object()
        self.vae = object()
        self.text_encoder = object()
        self.text_encoder_2 = object()


def test_component_bag_collects_upstream_components():
    from app.core.neural.kernel.adapters.base import ComponentBag

    pipe = _Pipe()
    bag = ComponentBag.from_pipe(pipe)
    assert bag.has("unet") and bag.has("vae") and bag.has("scheduler")
    assert "tokenizer" not in bag.keys(), "缺的组件不该出现在袋里"
    assert bag.pipe is pipe


def test_execution_device_follows_offload_hint():
    """offload 下权重在 CPU，但张量该放卡上 —— 判据只能来自 `_execution_device`。"""
    from app.core.neural.kernel.adapters.base import ComponentBag

    bag = ComponentBag.from_pipe(_Pipe(exec_device="cuda:1"))
    assert bag.execution_device() == "cuda:1"


def test_execution_device_falls_back_to_weights():
    """没有 `_execution_device` 时退回权重设备（whole_gpu 下就是对的）。"""
    torch = pytest.importorskip("torch")
    from app.core.neural.kernel.adapters.base import ComponentBag

    class _NoHint:
        def __init__(self) -> None:
            self.net = torch.nn.Linear(2, 2)

    bag = ComponentBag({"net": _NoHint().net})
    assert str(bag.execution_device()).startswith("cpu")


def test_execution_device_last_resort_is_cpu():
    from app.core.neural.kernel.adapters.base import ComponentBag

    assert ComponentBag({}).execution_device() == "cpu"


def test_adapter_bind_requires_net():
    """绑定后体检要能报"缺少主网络"：没它的话每步 forward 都会 KeyError。"""
    from app.core.neural.kernel.adapters.base import ComponentBag

    ad = K.adapter_for("sd15")
    ad.bind(ComponentBag({}))
    bad = ad.validate()
    assert any("主网络" in x or "unet" in x for x in bad), bad


# ══════════════════════════════════════════════════════════════════
# 编码参数的"逐字透传"（SDXL 首跑踩过的坑）
# ══════════════════════════════════════════════════════════════════

class _RecordPipe:
    """只记录 `encode_prompt` 收到了哪些关键字。"""

    def __init__(self, arity: int) -> None:
        self.arity = arity
        self.seen = None

    def encode_prompt(self, prompt, *a, **kw):
        self.seen = kw
        import torch

        t = torch.zeros(1, 2, 4)
        if self.arity == 2:
            return t, t
        return t, t, t, t


def test_sd15_encode_passes_negative_prompt_verbatim():
    """空负向必须是 `""` 而不是 `None` —— 与 stock 路径喂给 pipe 的值一字不差。"""
    from app.core.neural.kernel.adapters.base import ComponentBag
    from app.core.neural.kernel.adapters.sd15 import SD15Adapter

    pipe = _RecordPipe(2)
    ad = SD15Adapter()
    ad.bind(ComponentBag.from_pipe(pipe))
    ad.encode(_req("sd15"), True)
    assert pipe.seen["negative_prompt"] == ""
    assert pipe.seen["negative_prompt"] is not None


def test_sdxl_encode_passes_negative_prompt_verbatim():
    """SDXL 上这条不是洁癖：`""` 与 `None` 编出的负向条件实测差 max|Δ|≈854，
    每步偏差累积到 PSNR 23dB —— 两条路都"能出图"，所以只能靠断言拦住。"""
    from app.core.neural.kernel.adapters.base import ComponentBag
    from app.core.neural.kernel.adapters.sdxl import SDXLAdapter

    class _Net:
        class add_embedding:                 # 维度断言用：256*6 + 1280 = 2816
            class linear_1:
                in_features = 2816

        class config:
            addition_time_embed_dim = 256

    class _Enc2:
        class config:
            projection_dim = 1280

    pipe = _RecordPipe(4)
    ad = SDXLAdapter()
    bag = ComponentBag.from_pipe(pipe)
    bag.register("unet", _Net())
    bag.register("text_encoder_2", _Enc2())
    ad.bind(bag)

    cond = ad.encode(_req("sdxl"), True)
    assert pipe.seen["negative_prompt"] == ""
    assert pipe.seen["negative_prompt"] is not None
    # (neg, pos) 顺序 + time_ids 形状
    assert tuple(cond["prompt_embeds"].shape) == (2, 2, 4)
    assert tuple(cond["time_ids"].shape) == (2, 6)


# ══════════════════════════════════════════════════════════════════
# engine 门禁（永不抛异常）
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def _kernel_on(monkeypatch):
    monkeypatch.setenv("SHIGUANG_KERNEL", "on")
    monkeypatch.setenv("SHIGUANG_KERNEL_ALLOW_UNVERIFIED", "1")
    monkeypatch.delenv("SHIGUANG_KERNEL_FAMILIES", raising=False)


def _req(family="sd15"):
    from app.core.neural.kernel.contracts import GenRequest

    return GenRequest(family=family, model_id="m", prompt="a cat",
                      width=512, height=512, steps=1, cfg=7.5)


def test_mode_off_rejects_with_reason(monkeypatch):
    monkeypatch.setenv("SHIGUANG_KERNEL", "off")
    res = K.run(pipe=object(), req=_req())
    assert res["ok"] is False
    assert res["report"].used is False
    assert "off" in res["report"].rejected_reason
    assert res["report"].to_dict()["rejected_reason"], "拒绝必须有原因（可观测门）"


def test_invalid_mode_string_is_treated_as_off(monkeypatch):
    """拼错开关不许把内核打开：`SHIGUANG_KERNEL=ON!` 按 off 处理。"""
    monkeypatch.setenv("SHIGUANG_KERNEL", "ON!")
    assert K.mode() == K.MODE_OFF


def test_family_whitelist_blocks_others(_kernel_on, monkeypatch):
    monkeypatch.setenv("SHIGUANG_KERNEL_FAMILIES", "sdxl")
    res = K.run(pipe=object(), req=_req("sd15"))
    assert res["ok"] is False
    assert "白名单" in res["report"].rejected_reason


def test_whitelisted_family_passes_gate(_kernel_on, monkeypatch):
    monkeypatch.setenv("SHIGUANG_KERNEL_FAMILIES", "sd15")
    assert K.family_allowed("SD15") is True, "白名单比对应忽略大小写"


def test_unverified_family_rejected_by_default(monkeypatch):
    """未验收的族默认不许跑：必须拒绝并说明"未验收"。

    2026-10-28 P2 之后 sd15/sdxl 都已是 `verified`，所以这条规则**不能再靠现成的族触发**。
    这里显式造一个"caps 合法但未验收"的适配器传进 `run(adapter=...)`——
    守的是规则本身，而不是"此刻恰好有哪个族没验收"（后者只会到期失效）。
    """
    import dataclasses

    from app.core.neural.kernel.adapters.sd15 import SD15Adapter
    from app.core.neural.kernel.contracts import UNVERIFIED

    class _Unverified(SD15Adapter):
        caps = dataclasses.replace(SD15Adapter.caps, verified=UNVERIFIED)

    monkeypatch.setenv("SHIGUANG_KERNEL", "on")
    monkeypatch.delenv("SHIGUANG_KERNEL_ALLOW_UNVERIFIED", raising=False)
    res = K.run(pipe=object(), req=_req("sd15"), adapter=_Unverified())
    assert res["ok"] is False
    assert "未验收" in res["report"].rejected_reason


def test_run_never_raises_on_broken_pipe(_kernel_on):
    """组件缺失的 pipeline ⇒ 返回 ok=False，绝不把异常抛给调用方。"""
    res = K.run(pipe=object(), req=_req("sd15"))
    assert res["ok"] is False
    assert res["report"].used is False
    assert res["report"].rejected_reason


def test_run_never_raises_on_none_pipe(_kernel_on):
    res = K.run(pipe=None, req=_req("sd15"))
    assert res["ok"] is False and res["report"].rejected_reason


def test_run_rejects_unknown_family(_kernel_on):
    res = K.run(pipe=object(), req=_req("wan"))
    assert res["ok"] is False
    assert res["report"].rejected_reason


# ══════════════════════════════════════════════════════════════════
# 诊断快照
# ══════════════════════════════════════════════════════════════════

def test_describe_shape():
    d = K.describe()
    for k in ("contract_version", "mode", "families_allowed", "builtin_families",
              "allow_unverified", "adapters"):
        assert k in d, k
    assert set(d["builtin_families"]) >= {"sd15", "sdxl"}
    for fam in d["builtin_families"]:
        assert d["adapters"][fam]["caps"]["violations"] == []


def test_supported_families_sorted():
    assert K.supported_families() == sorted(K.supported_families())
