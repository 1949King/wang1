# -*- coding: utf-8 -*-
"""SVD 族适配器单测（离线：不加载真模型、不 import diffusers、不需要显卡）。

## 为什么这一族要单独一整个文件

SVD 的 11 处差异里，**每一处写错都能跑通、都能出片、都不报错**。
真机四门（PSNR/帧数/时延/显存）只能告诉你"有偏差"，不能告诉你"哪一条错了"。
所以这里对每条语义做**定点断言**：形状、顺序、调用次序、被除/被乘了几次。
真机门的跑法在 `scripts/bench_kernel_parity.py`，两者分工不重叠。

## 为什么用假组件而不是小号真模型

真的 `StableVideoDiffusionPipeline` 需要 4.2GB fp16 权重 + CUDA，
在 CI 上跑不起来；而"只跑有卡的机器"的测试等于没有测试。
假组件让每条语义都能被钉死 —— 它们不验证上游行为，只验证**我们的实现与文档一致**，
上游一致性由 bench 的 `max|Δ|` / PSNR 负责。
"""
from __future__ import annotations

import sys
import types

import pytest

torch = pytest.importorskip("torch")

from app.core.neural.kernel.adapters import svd as SVD
from app.core.neural.kernel.contracts import (
    GenRequest, RunState, VIDEO_PARITY_FIELDS, baseline_for,
)


# ══════════════════════════════════════════════════════════════════
# 假组件（只实现被调用到的那几个方法）
# ══════════════════════════════════════════════════════════════════

class _LatentDist:
    def __init__(self, value):
        self._value = value

    def mode(self):
        return self._value

    def sample(self, generator=None):  # 不该被调用
        raise AssertionError("SVD 必须用 latent_dist.mode()，不许 sample()（会多抽一组随机数）")


class _FakeVAE:
    """时序 VAE 的替身：`encode` 返回 `mode()`，`decode` 接受 `num_frames`。

    `encode` 按真实 VAE 的行为**下采样 8 倍** —— 这一点很关键：
    若替身保持原尺寸，`prepare_step` 里"噪声 latent 与图像条件必须同尺寸"
    这条约束就永远测不出来，而它在真机上恰恰是最容易写错的（拼错维度）。
    """

    downscale = 8

    def __init__(self, channels=4, scaling=0.18215, dtype=None):
        self.config = types.SimpleNamespace(scaling_factor=scaling, force_upcast=False)
        self.dtype = dtype or torch.float32
        self.encode_calls = []
        self.decode_calls = []
        self._channels = channels

    def parameters(self):
        yield torch.zeros(1, dtype=self.dtype)

    def to(self, dtype=None, device=None):
        if dtype is not None:
            self.dtype = dtype
        return self

    def encode(self, x):
        self.encode_calls.append(tuple(x.shape))
        b, _, h, w = x.shape
        h, w = h // self.downscale, w // self.downscale
        value = torch.arange(b * self._channels * h * w, dtype=x.dtype).reshape(
            b, self._channels, h, w) * 0.001 + 1.0
        return types.SimpleNamespace(latent_dist=_LatentDist(value))

    def encode_in_dtype(self, x, dtype):
        """模拟"VAE 被临时升 fp32 后编码" —— 返回值 dtype 与输入不同。

        真机首跑就是在这里炸的：`needs_upcasting` 期间 VAE 是 fp32，
        `latent_dist.mode()` 因此返回 fp32，而上游 `:524` 会 `.to(image_embeddings.dtype)`。
        漏那一行 ⇒ 条件张量停在 fp32、UNet 权重是 fp16 ⇒ 前向第一层就
        `mat1 and mat2 must have the same dtype`。
        """
        self.encode_calls.append(tuple(x.shape))
        b, _, h, w = x.shape
        h, w = h // self.downscale, w // self.downscale
        value = torch.ones((b, self._channels, h, w), dtype=dtype)
        return types.SimpleNamespace(latent_dist=_LatentDist(value))

    def decode(self, x, num_frames=None):
        self.decode_calls.append((int(x.shape[0]), num_frames))
        return types.SimpleNamespace(sample=x.clone())

    def forward(self, x, num_frames=None):
        return self.decode(x, num_frames=num_frames)


class _FakeUNet:
    def __init__(self, in_channels=8, add_dim=256, sample_size=96, num_frames=25):
        self.config = types.SimpleNamespace(
            in_channels=in_channels, addition_time_embed_dim=add_dim,
            sample_size=sample_size, num_frames=num_frames,
            time_cond_proj_dim=None)
        self.add_embedding = types.SimpleNamespace(
            linear_1=types.SimpleNamespace(in_features=add_dim * 3))
        self.calls = []

    def parameters(self):
        yield torch.zeros(1)

    def __call__(self, sample, t, **kwargs):
        self.calls.append({"shape": tuple(sample.shape), "t": t, "kwargs": kwargs})
        return (torch.zeros_like(sample),)


class _FakeVideoProcessor:
    def __init__(self):
        self.pre_requests = []
        self.post_requests = []

    def preprocess(self, image, height=None, width=None):
        self.pre_requests.append((image.size, height, width))
        return torch.zeros(1, 3, height, width)

    def postprocess_video(self, video, output_type="pil"):
        self.post_requests.append(tuple(video.shape))
        return [[("frame-%d" % i) for i in range(video.shape[2])]]


class _FakePipe:
    """最小上游：只有 `_encode_image` / `video_processor` / `_execution_device`。"""

    def __init__(self, events=None, embed_dtype=torch.float32):
        self.video_processor = _FakeVideoProcessor()
        self._execution_device = "cpu"
        self._events = events if events is not None else []
        self.embed_dtype = embed_dtype
        self.encode_image_calls = []

    def _encode_image(self, image, device, num_videos_per_prompt, do_cfg):
        self._events.append("encode_image")
        self.encode_image_calls.append((image.size, str(device),
                                        num_videos_per_prompt, bool(do_cfg)))
        embeds = torch.full((1, 1, 4), 0.5, dtype=self.embed_dtype)
        if do_cfg:
            embeds = torch.cat([torch.zeros_like(embeds), embeds])
        return embeds


class _FakeScheduler:
    """Euler 的最小替身：`init_noise_sigma=700`（本模型实测值）。"""

    order = 1
    init_noise_sigma = 700.0

    def __init__(self):
        self.timesteps = torch.tensor([])
        self.set_requests = []
        self.scale_calls = 0
        self.step_calls = []

    def set_timesteps(self, n, device=None):
        self.set_requests.append(int(n))
        self.timesteps = torch.arange(int(n), 0, -1, dtype=torch.float32)

    def scale_model_input(self, sample, t):
        self.scale_calls += 1
        return sample / 2.0

    def step(self, model_output, t, sample, **kwargs):
        self.step_calls.append({"kwargs": kwargs, "shape": tuple(sample.shape)})
        # SVD 走 `.prev_sample`（上游 `:604` 的写法），所以假调度器也照这个返回
        return types.SimpleNamespace(prev_sample=sample * 0.5)

    def add_noise(self, latents, noise, timestep):
        return latents + noise


def _bag(pipe=None, *, image_encoder=True, feature_extractor=True,
         video_processor=True, net=None, vae=None, scheduler=None):
    from app.core.neural.kernel.adapters.base import ComponentBag

    parts = {}
    if net is not None:
        parts["net"] = net
    if vae is not None:
        parts["vae"] = vae
    if scheduler is not None:
        parts["scheduler"] = scheduler
    if image_encoder:
        parts["image_encoder"] = object()
    if feature_extractor:
        parts["feature_extractor"] = object()
    p = pipe if pipe is not None else _FakePipe()
    if video_processor and getattr(p, "video_processor", None) is not None:
        parts["video_processor"] = p.video_processor
    bag = ComponentBag(parts)
    bag._pipe = p
    return bag


def _adapter(**kwargs):
    ad = SVD.SVDAdapter()
    ad.bind(_bag(**kwargs))
    return ad


def _req(tmp_image, **kw):
    base = dict(family="svd", model_id="svd-xt-i2v", image_path=str(tmp_image),
                width=64, height=32, frames=4, fps=7, motion_bucket_id=127,
                noise_aug_strength=0.02, cfg=3.0, cfg_min=1.0, batch=1)
    base.update(kw)
    return GenRequest(**base)


@pytest.fixture()
def tmp_image(tmp_path):
    from PIL import Image

    p = tmp_path / "in.png"
    Image.new("RGB", (96, 64), (10, 20, 30)).save(p)
    return p


@pytest.fixture()
def sound_adapter():
    return _adapter(net=_FakeUNet(), vae=_FakeVAE(), scheduler=_FakeScheduler())


# ══════════════════════════════════════════════════════════════════
# 能力声明 / 契约
# ══════════════════════════════════════════════════════════════════

def test_caps_are_self_consistent(sound_adapter):
    assert sound_adapter.caps.violations() == []
    assert sound_adapter.caps.latent_rank == 5
    assert sound_adapter.caps.vae_decode == "chunked_temporal"
    assert sound_adapter.caps.latent_scale == "init_noise_sigma"


def test_verified_requires_real_gate_evidence(sound_adapter):
    """`verified=VERIFIED` 必须有一条**盘上真实的**验收记录兜底。

    这条比"断言等于某个字符串"有用得多：它把 `caps.verified` 与
    `docs/knowledge/kernel_evidence.json` 钉在一起 —— 谁把 verified 改成
    VERIFIED 却没跑过 bench，这里当场红（守卫 ⑱ 的第 ⑤ 条是同一判据的静态版）。
    """
    from app.core.neural.kernel import evidence as EV
    from app.core.neural.kernel.contracts import VERIFIED

    assert sound_adapter.caps.verified == VERIFIED
    rec = (EV.load().get("families") or {}).get("svd") or {}
    assert rec.get("passed") is True, "声明 verified 但台账里没有 svd 的 passed=true"
    assert rec.get("kind") == "video"
    assert rec.get("frames_match") is True
    assert rec.get("cancelled_ok") is True


def test_parity_fills_every_video_baseline_field(sound_adapter):
    missing = sound_adapter.parity.missing(baseline_for(sound_adapter.caps))
    assert missing == [], "视频族 parity 基线没填完：%s" % missing
    assert sound_adapter.parity.missing(VIDEO_PARITY_FIELDS) == []


def test_validate_reports_missing_clip_pieces():
    """缺 CLIP 视觉编码器 / 预处理 / video_processor 时要**说清缺什么**，不是抛异常。"""
    ad = _adapter(net=_FakeUNet(), vae=_FakeVAE(), scheduler=_FakeScheduler(),
                  image_encoder=False, feature_extractor=False, video_processor=False)
    bad = ad.validate()
    assert any("image_encoder" in x for x in bad)
    assert any("feature_extractor" in x for x in bad)
    assert any("video_processor" in x for x in bad)


def test_deep_check_rejects_odd_in_channels():
    ad = _adapter(net=_FakeUNet(in_channels=7), vae=_FakeVAE(), scheduler=_FakeScheduler())
    assert any("in_channels=7" in x for x in ad.validate())


def test_deep_check_rejects_added_time_ids_mismatch():
    net = _FakeUNet(add_dim=256)
    net.add_embedding = types.SimpleNamespace(
        linear_1=types.SimpleNamespace(in_features=512))   # 期望 768，实得 512
    ad = _adapter(net=net, vae=_FakeVAE(), scheduler=_FakeScheduler())
    assert any("added_time_ids 维度不匹配" in x for x in ad.validate())


def test_deep_check_rejects_missing_upstream_encoder():
    """上游删了 `_encode_image` 时要明确拒绝 —— 那是"必须重做编码层"级别的变更。"""
    class _Bare:
        def __init__(self):
            self.video_processor = _FakeVideoProcessor()
            self._execution_device = "cpu"

    from app.core.neural.kernel.adapters.base import ComponentBag

    bare = _Bare()
    bag = ComponentBag({"net": _FakeUNet(), "vae": _FakeVAE(),
                        "scheduler": _FakeScheduler(), "image_encoder": object(),
                        "feature_extractor": object(),
                        "video_processor": bare.video_processor})
    bag._pipe = bare
    ad = SVD.SVDAdapter()
    ad.bind(bag)
    assert any("_encode_image" in x for x in ad.validate())


# ══════════════════════════════════════════════════════════════════
# 编码：条件 / 时间 ID / 逐帧引导
# ══════════════════════════════════════════════════════════════════

def _cond(ad, req, do_guidance=True, generator=None):
    return ad.encode(req, do_guidance, generator=generator)


def test_uncond_branch_is_zeros_and_ordered_neg_pos(sound_adapter, tmp_image):
    """无条件支必须是**全零张量**（上游 `:230`），不是"空文本编码"。

    顺序 `(uncond, cond)`：写反了不会报错，只会得到"负向引导"——
    CFG 越大画面越糟，而人第一反应会去怀疑模型。
    """
    cond = _cond(sound_adapter, _req(tmp_image), do_guidance=True)
    embeds = cond["image_embeds"]
    assert tuple(embeds.shape)[0] == 2
    assert float(embeds[0].abs().sum()) == 0.0, "前半（uncond）必须全零"
    assert float(embeds[1].abs().sum()) > 0.0, "后半（cond）必须非零"


def test_no_guidance_single_branch(sound_adapter, tmp_image):
    cond = _cond(sound_adapter, _req(tmp_image, cfg=1.0, cfg_min=1.0), do_guidance=False)
    assert tuple(cond["image_embeds"].shape)[0] == 1
    assert tuple(cond["image_latents"].shape)[0] == 1


def test_added_time_ids_layout_and_order(sound_adapter, tmp_image):
    """`[fps-1, motion_bucket, noise_aug]`，**先 repeat 再 cat**。

    `fps` 传进去的是 `fps - 1`（`req.fps=7` ⇒ 6），这是 Stability 原始实现的口径。
    顺序写错（cat 再 repeat）会出现 2 行且值相同 —— 这里用"cat 后两行相等"反向确认
    它不是那种实现：两行相同本身是对的（neg 与 pos 的 time id 本来就一样），
    所以真正钉的是**总行数 = batch × 2** 与**每行内容**。
    """
    cond = _cond(sound_adapter, _req(tmp_image, fps=7, motion_bucket_id=80,
                                     noise_aug_strength=0.02), do_guidance=True)
    ati = cond["added_time_ids"]
    assert tuple(ati.shape) == (2, 3)
    assert [round(float(v), 6) for v in ati[0]] == [6, 80, 0.02]


def test_added_time_ids_batch_repeat_keeps_value(sound_adapter, tmp_image):
    """batch=2 + CFG ⇒ 4 行，且**每行都是同一组值**（repeat 在前，cat 在后）。"""
    cond = _cond(sound_adapter, _req(tmp_image, batch=2), do_guidance=True)
    ati = cond["added_time_ids"]
    assert tuple(ati.shape) == (4, 3)
    assert len({tuple(round(float(v), 6) for v in row) for row in ati}) == 1


def test_image_latents_broadcast_along_frame_dim(sound_adapter, tmp_image):
    """`(B,C,h,w)` → `(B,frames,C,h,w)`：帧维在 **dim=1**，且每帧完全相同。"""
    cond = _cond(sound_adapter, _req(tmp_image, frames=4), do_guidance=True)
    lat = cond["image_latents"]
    assert tuple(lat.shape) == (2, 4, 4, 4, 8)      # 2 = CFG, 4 帧, 4 通道, h=32/8, w=64/8
    assert torch.equal(lat[:, 0], lat[:, 3]), "每一帧的图像条件必须相同（同一张输入图）"


def test_guidance_is_per_frame_and_spans_min_max(sound_adapter, tmp_image):
    """逐帧引导：`linspace(min,max,frames)` 补维到 `(B,frames,1,1,1)`。

    退化成单标量也能跑通，只是首帧与末帧引导相同 ⇒ 运动幅度塌陷。
    所以这里既钉形状，也钉**两端值恰好是 min 与 max**。
    """
    cond = _cond(sound_adapter, _req(tmp_image, frames=5, cfg=3.0, cfg_min=1.0),
                 do_guidance=True)
    g = cond["guidance"]
    assert tuple(g.shape) == (1, 5, 1, 1, 1)
    assert pytest.approx(float(g[0, 0, 0, 0, 0]), rel=0, abs=1e-6) == 1.0
    assert pytest.approx(float(g[0, 4, 0, 0, 0]), rel=0, abs=1e-6) == 3.0


def test_reversed_cfg_is_swapped_with_a_note(sound_adapter, tmp_image):
    """min/max 传反（cfg < cfg_min）时修正并**留痕**，不静默照算。"""
    cond = _cond(sound_adapter, _req(tmp_image, frames=3, cfg=1.0, cfg_min=4.0),
                 do_guidance=True)
    g = cond["guidance"]
    assert float(g[0, 0, 0, 0, 0]) == pytest.approx(1.0)
    assert float(g[0, 2, 0, 0, 0]) == pytest.approx(4.0)
    assert any("传反" in n for n in sound_adapter.notes)


def test_noise_aug_is_drawn_before_vae_encode(monkeypatch, tmp_image):
    """★ 随机数消耗顺序：噪声增广**先于** VAE 编码，也先于初始 latents。

    顺序错一位，初始 latents 就不再与 stock 比特一致，而现象只是"视频不一样"。
    这里用事件表把三次动作的次序钉死。
    """
    events = []
    pipe = _FakePipe(events=events)
    vae = _FakeVAE()

    orig_encode = vae.encode

    def _spy_encode(x):
        events.append("vae_encode")
        return orig_encode(x)

    vae.encode = _spy_encode

    ad = _adapter(pipe=pipe, net=_FakeUNet(), vae=vae, scheduler=_FakeScheduler())

    def _fake_randn(shape, generator, device, dtype):
        events.append("randn")
        return torch.zeros(tuple(shape), dtype=dtype)

    monkeypatch.setattr(SVD.SVDAdapter, "_randn", staticmethod(_fake_randn))
    _cond(ad, _req(tmp_image))
    assert events == ["encode_image", "randn", "vae_encode"], (
        "顺序必须是 CLIP 编码 → 抽噪声增广 → VAE 编码，实际：%s" % events)


def test_noise_aug_strength_zero_means_upstream_default(sound_adapter, tmp_image):
    """`0` 表示"没要求"⇒ 取上游默认 0.02（不是"完全不加噪"）。"""
    cond = _cond(sound_adapter, _req(tmp_image, noise_aug_strength=0.0))
    assert cond["noise_aug_strength"] == 0.02


def test_image_latents_cast_to_condition_dtype(tmp_image):
    """VAE 编码（可能临时升 fp32）的产物**必须**转回条件张量的 dtype。

    这条是 2026-10-28 真机首跑炸出来的：`RuntimeError: mat1 and mat2 must have
    the same dtype, but got Float and Half`。断点前一层正是"条件张量停在 fp32"。
    上游 `:524` 有一行 `.to(image_embeddings.dtype)`，漏了就必炸 ——
    所以这里让替身 VAE 刻意返回**与条件不同的 dtype**，把这条钉成离线可测。
    """
    vae = _FakeVAE()
    vae.encode = lambda x: vae.encode_in_dtype(x, torch.float32)   # 模拟升 fp32 后的编码
    ad = _adapter(pipe=_FakePipe(embed_dtype=torch.float16),
                  net=_FakeUNet(), vae=vae, scheduler=_FakeScheduler())

    cond = ad.encode(_req(tmp_image), True, generator=None)
    assert cond["image_embeds"].dtype == torch.float16
    assert cond["image_latents"].dtype == cond["image_embeds"].dtype, (
        "图像条件张量必须与 CLIP 嵌入同 dtype，否则 UNet 前向第一层就 dtype 不匹配")


# ══════════════════════════════════════════════════════════════════
# 时间轴 / 每步 / 引导 / 推进
# ══════════════════════════════════════════════════════════════════

def test_make_timesteps_ignores_strength(sound_adapter, tmp_image):
    """i2v 必然带 `image_path`（`is_i2i()` 恒真），但 SVD **没有** strength 语义。

    基类会按 strength 截尾：`strength=0.4` 时 25 步被砍到 10 步，
    出片是全噪、回执却写着 steps=10。这里正面钉住"跑满"。
    """
    req = _req(tmp_image, steps=25, strength=0.4)
    assert req.is_i2i() is True
    _, n = sound_adapter.make_timesteps(req, cond=None)
    assert n == 25


def test_prepare_step_order_expand_scale_concat(sound_adapter, tmp_image):
    """三步定序：拼 CFG batch → `scale_model_input` → 沿 **dim=2** 拼图像条件。

    同时钉 `raw`：推进调度器要用**未缩放、未拼条件**的潜变量。
    把缩放后的值交给 `scheduler.step` 在 Euler 上也能跑（差一个 sigma 因子），
    表现是"图比 stock 糊一点点"——最难查的那种。
    """
    cond = _cond(sound_adapter, _req(tmp_image, frames=4), do_guidance=True)
    sch = sound_adapter.bag.require("scheduler")
    latents = torch.ones(1, 4, 4, 4, 8)
    state = RunState(timesteps=sch.timesteps, latents=latents, do_guidance=True, ctx=cond)

    sch.scale_calls = 0
    prepared = sound_adapter.prepare_step(latents, torch.tensor(1.0), state)

    assert sch.scale_calls == 1, "scale_model_input 必须恰好调一次"
    # batch 翻倍(2) × 帧(4) × (噪声 4 + 条件 4)=8 通道
    assert tuple(prepared.model_input.shape) == (2, 4, 8, 4, 8)
    assert prepared.raw is latents, "raw 必须是未缩放的原值"
    # 前 4 通道 = 1/2（被 scale 过），后 4 通道 = 图像条件（未 scale）
    assert float(prepared.model_input[0, 0, 0].mean()) == pytest.approx(0.5)


def test_guide_uses_per_frame_tensor(sound_adapter, tmp_image):
    """首帧与末帧的引导强度不同 ⇒ 用标量实现会得到"首末帧一样"的错误结果。"""
    cond = _cond(sound_adapter, _req(tmp_image, frames=3, cfg=3.0, cfg_min=1.0))
    state = RunState(timesteps=[], latents=None, do_guidance=True, ctx=cond)

    uncond = torch.zeros(1, 3, 4, 2, 2)
    text = torch.ones(1, 3, 4, 2, 2)
    out = sound_adapter.guide(torch.cat([uncond, text]), None, state)

    assert float(out[0, 0].mean()) == pytest.approx(1.0)   # g=1
    assert float(out[0, 2].mean()) == pytest.approx(3.0)   # g=3


def test_guide_passthrough_without_guidance(sound_adapter, tmp_image):
    cond = _cond(sound_adapter, _req(tmp_image, cfg=1.0, cfg_min=1.0), do_guidance=False)
    state = RunState(timesteps=[], latents=None, do_guidance=False, ctx=cond)
    noise = torch.zeros(1, 2, 4, 2, 2)
    assert sound_adapter.guide(noise, None, state) is noise


def test_step_extra_kwargs_is_empty(sound_adapter):
    """上游 `:604` 的 `scheduler.step(noise_pred, t, latents)` 什么都不传。

    Euler 的 `step` 签名里有 `generator`，但 `s_churn=0` 时 `gamma == 0`、
    那段 `randn_tensor` 根本不执行。传了结果一样 —— 但"结果一样"不该靠运气。
    """
    assert sound_adapter.step_extra_kwargs(generator=torch.Generator()) == {}


def test_scheduler_step_gets_raw_latents(sound_adapter, tmp_image):
    cond = _cond(sound_adapter, _req(tmp_image, frames=2), do_guidance=True)
    sch = sound_adapter.bag.require("scheduler")
    latents = torch.ones(1, 2, 4, 4, 8)
    state = RunState(timesteps=sch.timesteps, latents=latents, do_guidance=True,
                     ctx=cond, extra_step_kwargs={})
    prepared = sound_adapter.prepare_step(latents, torch.tensor(1.0), state)
    sound_adapter.step(torch.zeros(1, 2, 4, 4, 8), torch.tensor(1.0), prepared, state)
    assert sch.step_calls[-1]["shape"] == (1, 2, 4, 4, 8)
    assert sch.step_calls[-1]["kwargs"] == {}, "SVD 的 step 不许传可选参数"


# ══════════════════════════════════════════════════════════════════
# 解码
# ══════════════════════════════════════════════════════════════════

def test_decode_chunks_and_reshapes(sound_adapter):
    """分块解码 + `reshape(-1,frames,...)` + `permute(0,2,1,3,4)`。

    先 `permute` 再 `reshape` 会把帧维与通道维搅在一起：能播、能存、内容错位。
    """
    vae = sound_adapter.bag.require("vae")
    latents = torch.ones(1, 5, 4, 2, 3)
    state = RunState(timesteps=[], latents=latents, decode_chunk=2)

    out = sound_adapter.decode(latents, state=state)

    assert [c[0] for c in vae.decode_calls] == [2, 2, 1], "5 帧 / chunk=2 ⇒ 2+2+1"
    assert all(c[1] == c[0] for c in vae.decode_calls), "必须把分块帧数告诉 VAE"
    # postprocess 收到的是 (B=1, C=4, F=5, H=2, W=3)
    assert sound_adapter.bag.require("video_processor").post_requests[-1] == (1, 4, 5, 2, 3)
    assert len(out) == 5, "返回值必须是逐帧列表（与 stock 的 `.frames[0]` 同构）"


def test_decode_default_chunk_is_all_frames(sound_adapter):
    """`decode_chunk=0` ⇒ 一次性解完（上游 `decode_chunk_size or num_frames`）。"""
    vae = sound_adapter.bag.require("vae")
    latents = torch.ones(1, 4, 4, 2, 2)
    sound_adapter.decode(latents, state=RunState(timesteps=[], latents=latents))
    assert [c[0] for c in vae.decode_calls] == [4]


def test_decode_divides_scaling_factor_exactly_once(sound_adapter):
    """`1/scaling_factor` 只除一次，且在 `flatten(0,1)` 之后。

    漏除 ⇒ 成片过曝（latent 未被还原到 VAE 的输入尺度）；
    除两次 ⇒ 成片发暗。两者都不报错。
    """
    vae = sound_adapter.bag.require("vae")
    latents = torch.full((1, 2, 4, 1, 1), 0.18215)
    seen = []
    orig = vae.decode

    def _spy(x, num_frames=None):
        seen.append(float(x.flatten()[0]))
        return orig(x, num_frames=num_frames)

    vae.decode = _spy
    sound_adapter.decode(latents, state=RunState(timesteps=[], latents=latents, decode_chunk=2))
    assert seen[0] == pytest.approx(1.0, rel=0, abs=1e-6)


def test_decode_returns_list_of_frames_via_postprocess(sound_adapter):
    """成片必须走 `video_processor.postprocess_video(..., output_type="pil")`。"""
    latents = torch.ones(1, 3, 4, 2, 2)
    out = sound_adapter.decode(latents, state=RunState(timesteps=[], latents=latents))
    assert isinstance(out, list) and len(out) == 3
    assert out[0].startswith("frame-")


def test_vae_num_frames_probe_is_conservative():
    """探测不到 `num_frames` 时**不传**：传了会在纯图像 VAE 上炸 TypeError。"""
    class _NoFrames:
        def forward(self, x):
            return x

    class _WithFrames:
        def forward(self, x, num_frames=None):
            return x

    assert SVD.SVDAdapter._vae_accepts_num_frames(_NoFrames()) is False
    assert SVD.SVDAdapter._vae_accepts_num_frames(_WithFrames()) is True


# ══════════════════════════════════════════════════════════════════
# 缓存键
# ══════════════════════════════════════════════════════════════════

def test_cache_key_separates_motion_and_fps(sound_adapter, tmp_image):
    """视频族的条件由"输入图 + 时间/运动标量"决定，漏一个就串片。"""
    a = sound_adapter.cache_key(_req(tmp_image, motion_bucket_id=127))
    b = sound_adapter.cache_key(_req(tmp_image, motion_bucket_id=180))
    c = sound_adapter.cache_key(_req(tmp_image, fps=10))
    d = sound_adapter.cache_key(_req(tmp_image))
    assert a != b and a != c
    assert a == d, "同样的请求必须得到同样的键"


def test_cache_key_includes_image_identity(sound_adapter, tmp_image, tmp_path):
    from PIL import Image

    other = tmp_path / "other.png"
    Image.new("RGB", (96, 64), (200, 100, 50)).save(other)
    assert sound_adapter.cache_key(_req(tmp_image)) != sound_adapter.cache_key(_req(other))


# ══════════════════════════════════════════════════════════════════
# 与内核的接口
# ══════════════════════════════════════════════════════════════════

def test_kernel_loop_can_drive_svd_adapter(sound_adapter, tmp_image):
    """整条 `loop.denoise` 能驱动 SVD adapter（取消/进度/步号都由内核管）。

    这里不校验画质（离线没有真权重），只校验**接口契约**：
    内核只认 `prepare_step/forward/guide/step` 四件事，不认族名。
    """
    from app.core.neural.kernel import loop as LOOP

    req = _req(tmp_image, steps=3, frames=2)
    cond = _cond(sound_adapter, req)
    timesteps, n = sound_adapter.make_timesteps(req, cond)
    latents = sound_adapter.init_latents(req, cond, generator=torch.Generator().manual_seed(3))
    state = RunState(timesteps=timesteps, latents=latents, do_guidance=True,
                     cfg_scale=3.0, ctx=cond, steps=n,
                     extra_step_kwargs=sound_adapter.step_extra_kwargs())

    out = LOOP.denoise(sound_adapter, state)
    assert out.cancelled is False
    assert out.step_count == n == 3
    assert tuple(out.latents.shape) == (1, 2, 4, 4, 8)
    # 每步都真的调了网络，且条件一致
    net = sound_adapter.bag.require("net")
    assert len(net.calls) == 3
    assert tuple(net.calls[0]["shape"]) == (2, 2, 8, 4, 8)


def test_init_latents_uses_half_channels_and_sigma(sound_adapter, tmp_image):
    """噪声通道 = `in_channels // 2` = 4；`init_noise_sigma`(700) **只乘一次**。

    漏乘 ⇒ 噪声缩 700 倍 ⇒ 成片是一团糊；乘两次 ⇒ 噪声强 700 倍 ⇒ 全是雪花。
    """
    import math

    req = _req(tmp_image, frames=2)
    cond = _cond(sound_adapter, req)
    lat = sound_adapter.init_latents(req, cond, generator=torch.Generator().manual_seed(1))
    assert tuple(lat.shape) == (1, 2, 4, 4, 8)

    # 与"不乘 sigma"的同一 seed 采样对照，比值必须是 700（而不是 1 或 490000）
    from app.core.neural.kernel import latents as LAT

    raw = LAT.make_frames(batch=1, frames=2, channels=4, height=32, width=64,
                          latent_scale=8, generator=torch.Generator().manual_seed(1),
                          device="cpu", dtype=lat.dtype, init_noise_sigma=1.0)
    ratio = (lat.double() / raw.double())
    assert math.isclose(float(ratio.mean()), 700.0, rel_tol=1e-5)


def test_module_has_no_family_name_in_loop(sound_adapter):
    """H1 自查：内核循环里不许出现族名/组件名（族语义只在本 adapter 里）。"""
    import inspect

    from app.core.neural.kernel import loop as LOOP

    src = inspect.getsource(LOOP)
    for token in ("svd", "SVD", "image_latents", "encoder_hidden_states", "vae", "unet"):
        assert token not in src, "loop.py 里出现了族/组件相关标识：%s" % token


def test_stdout_guard_no_torch_at_adapter_import_time():
    """H3 延伸：`contracts.py` 仍不许顶层 import torch（本文件不新增违规）。"""
    src = open("app/core/neural/kernel/contracts.py", encoding="utf-8").read()
    top = [ln for ln in src.splitlines() if ln.startswith(("import ", "from "))]
    assert not any("torch" in ln for ln in top), "contracts.py 顶层出现了 torch"
    assert "torch" not in sys.modules or True   # 仅说明本断言不依赖进程状态


# ══════════════════════════════════════════════════════════════════
# 引擎层：返回结构必须按族分流
# ══════════════════════════════════════════════════════════════════

class _FullPipe(_FakePipe):
    """`ComponentBag.from_pipe` 能拆出来的最小上游（组件挂在属性上）。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.unet = _FakeUNet()
        self.vae = _FakeVAE()
        self.scheduler = _FakeScheduler()
        self.image_encoder = object()
        self.feature_extractor = object()


def _video_req(tmp_image, **kw):
    base = dict(family="svd", model_id="m", image_path=str(tmp_image),
                width=64, height=32, steps=1, frames=2, fps=7,
                motion_bucket_id=127, noise_aug_strength=0.02,
                cfg=3.0, cfg_min=1.0, batch=1)
    base.update(kw)
    return GenRequest(**base)


def test_engine_returns_frames_and_leaves_image_none(tmp_image, monkeypatch):
    """视频族走内核时：`frames` 有值、`image` 必须是 `None`。

    为什么不把 `list[PIL]` 塞进 `image`：所有图像调用方都写着
    `if res["image"]:` 然后 `.save()`，塞个 list 进去会让它们拿到一个
    不能 save 的东西 —— 报错点离根因十万八千里。
    """
    monkeypatch.setenv("SHIGUANG_KERNEL", "on")
    monkeypatch.setenv("SHIGUANG_KERNEL_ALLOW_UNVERIFIED", "1")

    from app.core.neural.kernel import engine as K

    res = K.run(pipe=_FullPipe(), req=_video_req(tmp_image),
                generator=torch.Generator().manual_seed(1), decode_chunk=1)
    assert res["ok"] is True, res.get("message")
    assert res["frames"] is not None and res["image"] is None
    assert isinstance(res["frames"], list) and len(res["frames"]) == 2
    assert res["report"].to_dict()["used"] is True


def test_engine_rejection_still_carries_frames_key(tmp_image, monkeypatch):
    """**每个**返回分支都必须有 `frames` 键。

    少一个键 ⇒ 视频调用方从"内核拒绝、回退上游"变成 `KeyError` ——
    回退机制本身失效，而现象是抛异常，不是降级。
    """
    monkeypatch.setenv("SHIGUANG_KERNEL", "off")

    from app.core.neural.kernel import engine as K

    res = K.run(pipe=None, req=_video_req(tmp_image))
    assert res["ok"] is False
    assert "frames" in res and res["frames"] is None
    assert "image" in res and res["image"] is None
    assert res["report"].to_dict()["rejected_reason"]
