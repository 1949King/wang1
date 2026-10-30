# -*- coding: utf-8 -*-
"""Wan 族适配器（Wan2.1 T2V）—— 自研去噪循环接管，组件仍用上游。

## 与 SVD 的关键差异（决定了本文件的形状）

| 维度 | SVD | Wan |
|---|---|---|
| 条件 | CLIP 单编码 + 图像条件 | **UMT5 prompt embeds**（项目已有两阶段编码，避免 RAM 墙） |
| CFG | 拼 batch（cond/uncond 一次前向） | **两次独立前向**（cond 先、uncond 后，与上游 cache_context 顺序一致） |
| 潜变量 | 4D [B,C,H,W] | **5D [B,C,T,H,W]**（T=(frames-1)//4+1） |
| 调度 | Euler（s_churn=0） | **UniPC + flow shift**，且要 set_begin_index(0) |
| 解码 | scalar_factor | **per-channel mean/std 反归一化**后 decode |

## 为什么 CFG 必须两次前向而不是拼 batch

上游 WanPipeline 的写法就是两次前向（L614-631），并且 cond 用了 `cache_context("cond")`。
改成拼 batch 看似省一半 launch，但那会改变 transformer 内部 attention 的 batch 布局 —— 
**比特级一致立刻不成立**。这里宁可慢一点，也要与上游调用形态一致（这是 SVD 已验收的同一条纪律）。

## 编码为什么委托项目自己的两阶段函数

Wan 的 UMT5-xxl 约 5.6GB，一次加全家桶会撞本机 15GB RAM 墙（项目实测过）。
`local_video_infer._encode_wan_prompts` 是分层加载 + 编完即释放的既有实现，
且 embeds 形状已按官方复刻（截真长 + 补零到 512）。自研循环只接管"循环"，不重写编码器。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.neural.kernel.adapters.base import BaseAdapter, ComponentBag, PreparedStep
from app.core.neural.kernel.contracts import (
    AdapterCaps, GenRequest, ParityContract, RunState, UNVERIFIED,
)

logger = logging.getLogger(__name__)


class WanAdapter(BaseAdapter):
    """Wan2.1 T2V：文生视频（I2V 需 image encoder，本适配器明确拒绝）。"""

    family = "wan"

    #: 组件袋里的中性 key
    _NET = "transformer"
    _VAE = "vae"
    _SCHED = "scheduler"

    caps = AdapterCaps(
        cfg_mode="two_pass",
        cfg_batch_multiplier=1,      # 两次前向，不拼 batch
        allow_cfg_merge=False,
        cond_keys=("prompt_embeds", "negative_prompt_embeds"),
        timestep_kind="scalar",
        latent_rank=5,
        latent_scale="none",         # Wan 不做 init_noise_sigma 缩放
        vae_decode="chunked_temporal",   # 视频族要求逐块解码（8GB 显存约束）
        scheduler_family="flow_match",
        verified=UNVERIFIED,         # 未跑通 parity 前不许标 verified
    )

    # Wan 的语义判据（漏一条就会"能跑但悄悄偏"，所以写成契约而不是注释）
    parity = ParityContract(
        fields={
            "cfg_mode": "two_pass",
            "cfg_order": "cond_then_uncond",     # 上游先 cond(cache_context) 再 uncond
            "encode_delegate": True,             # UMT5 两阶段编码委托 local_video_infer
            "randn_source": "diffusers.randn_tensor",
            "latent_rank": 5,
            "latent_frames": "(frames-1)//4+1",
            "spatial_div": "vae_scale_factor_spatial",
            "scheduler_begin_index": 0,          # set_timesteps 之后必须 set_begin_index(0)
            "timestep": "scalar_expand_batch",
            "net_key": "transformer",
            "decode_postprocess": "per_channel_mean_std+pil",
            "step_extra_kwargs": "none",
            # ── 视频族必需字段：Wan 的真实语义（不适用就 false/none，不冒充 SVD）──
            "scale_model_input": False,          # 上游 WanPipeline 循环里不调它
            "init_noise_sigma_once": False,      # Wan 不做 init_noise_sigma 缩放
            "noise_aug_before_vae": False,       # T2V 无输入图，无噪声增强
            "uncond_repr": "two_pass_negative_embeds",   # 不是 zeros_like，是再跑一次 uncond
            "image_latent_concat_dim": None,     # T2V 无图像条件通道
            "added_time_ids_order": None,        # Wan 无 added_time_ids
            "guidance_shape": "scalar",          # 5.0 标量，不是逐帧
            "decode_chunked": True,
        },
        tensor_rtol=1e-3,
        psnr_min_db=35.0,
    )

    def __init__(self) -> None:
        super().__init__()
        self._pe: Any = None
        self._ne: Any = None

    # ── 绑定与体检 ──────────────────────────────────────
    def bind(self, bag: ComponentBag) -> None:
        super().bind(bag)
        bag.require(self._NET)
        bag.require(self._VAE)
        bag.require(self._SCHED)

    def validate(self) -> List[str]:
        bad = super().validate()
        if bad:
            return bad
        if not self._model_path():
            bad.append("缺少 model_path（组件袋 extras）—— Wan 的 UMT5 编码需要它定位权重")
        cfg = getattr(self.bag.require(self._NET), "config", None)
        if getattr(cfg, "expand_timesteps", False):
            # Wan2.2 的 per-token 时间步需要 mask，当前未适配 ⇒ 明确拒绝而不是猜
            bad.append("该 Wan 权重 expand_timesteps=True（Wan2.2 形态），本适配器只支持 Wan2.1")
        return bad

    def _net_key(self) -> str:
        """基类默认返回 "unet"（图像族）；Wan 是 transformer。

        不 override 的后果（2026-10-30 实测）：`_dtype()` 找不到 net ⇒ 回退 float32，
        而 transformer 权重是 bf16 ⇒ "Input type (float) and bias type (BFloat16)"。
        """
        return self._NET


    def _dtype(self) -> Any:
        """按**多数权重**的 dtype 判定网络精度，而不是基类的 `next(iter(parameters()))`。

        2026-10-30 实测：Wan transformer 里存在 float32 参数（norm/rope 类），
        基类取"第一个参数"会返回 float32 ⇒ embeds/latents 全被转成 float32，
        前向立刻报 "Input type (float) and bias type (BFloat16)"。
        """
        net = self.bag.require(self._NET) if self.bag is not None else None
        if net is not None:
            from collections import Counter

            counts = Counter(p.dtype for p in net.parameters())
            if counts:
                return counts.most_common(1)[0][0]
        return super()._dtype()


    def _model_path(self) -> str:
        # 注意：ComponentBag.from_pipe 把 extras **合并进 parts**，没有独立 extras 属性。
        # 早期写成 getattr(bag, "extras") 会让 model_path 永远为空 ⇒ 每次都被 validate 拒绝。
        bag = self.bag
        return str(bag.get("model_path") or "") if bag is not None else ""

    # ── 条件编码（委托项目两阶段 UMT5）──────────────────
    def encode(self, req: GenRequest, do_guidance: bool = True,
               generator: Any = None) -> Any:
        model_path = self._model_path()
        vram_gb = int(self.bag.get("vram_gb") or 8) if self.bag is not None else 8
        try:
            from app.core.local_video_infer import _encode_wan_prompts, _WAN_NEGATIVE_DEFAULT
        except Exception as e:      # pragma: no cover - 只在缺依赖时走到
            raise RuntimeError("Wan 编码器不可用：%s: %s" % (type(e).__name__, e)) from e
        negative = str(req.negative_prompt or _WAN_NEGATIVE_DEFAULT)
        pe, ne = _encode_wan_prompts(model_path, str(req.prompt or ""), negative, vram_gb)
        self._pe, self._ne = pe, ne
        return {"prompt_embeds": pe, "negative_prompt_embeds": ne}

    # ── 时间轴 ─────────────────────────────────────────
    def make_timesteps(self, req: GenRequest, cond: Any, scheduler: Any = None,
                       steps: Optional[int] = None) -> Tuple[Any, int]:
        sch = scheduler if scheduler is not None else self.bag.require(self._SCHED)
        n = int(steps or req.steps or 20)
        # 上游顺序：set_timesteps → set_begin_index(0)。顺序颠倒会让 UniPC 的
        # begin_index 落在错误位置，结果"看起来正常"但每步都偏。
        sch.set_timesteps(n, device=self._device())
        if hasattr(sch, "set_begin_index"):
            sch.set_begin_index(0)
        return sch.timesteps, n

    # ── 潜变量 ─────────────────────────────────────────
    def init_latents(self, req: GenRequest, cond: Any, generator: Any = None,
                     scheduler: Any = None) -> Any:
        net = self.bag.require(self._NET)
        vae = self.bag.require(self._VAE)
        frames = int(req.frames or 17)          # 已是 4k+1 形态（由调用方算好）
        w = int(req.width or 512)
        h = int(req.height or 512)
        temporal = int(getattr(vae, "vae_scale_factor_temporal", 4) or 4)
        spatial = int(getattr(vae, "vae_scale_factor_spatial", 8) or 8)
        ch = int(getattr(net.config, "in_channels", 16) or 16)
        latent_frames = (frames - 1) // temporal + 1
        shape = (int(req.batch or 1), ch, latent_frames, h // spatial, w // spatial)
        from diffusers.utils.torch_utils import randn_tensor
        return randn_tensor(shape, generator=generator, device=self._device(),
                            dtype=self._dtype())

    # ── 单步 ───────────────────────────────────────────
    def prepare_step(self, latents: Any, t: Any, state: RunState) -> PreparedStep:
        net_dtype = self._dtype()
        model_input = latents.to(net_dtype)
        timestep = t.expand(latents.shape[0])
        return PreparedStep(raw=latents, model_input=model_input, timestep=timestep)

    def _net_kwargs(self, state: RunState, prepared: PreparedStep,
                    embeds: Any = None) -> Dict[str, Any]:
        e = self._pe if embeds is None else embeds
        return {
            "hidden_states": prepared.model_input,
            "timestep": prepared.timestep,
            "encoder_hidden_states": self._as_batch(e),
            "return_dict": False,
        }

    def _as_batch(self, embeds: Any) -> Any:
        """项目里的 embeds 是 [seq, dim]（编码函数返回的形态），上游要 [B, seq, dim]。"""
        if embeds is None:
            return None
        if hasattr(embeds, "dim") and embeds.dim() == 2:
            return embeds.unsqueeze(0).to(self._dtype()).to(self._device())
        return embeds.to(self._dtype()).to(self._device())

    def forward(self, prepared: PreparedStep, state: RunState) -> Any:
        net = self.bag.require(self._NET)
        return net(**self._net_kwargs(state, prepared))[0]

    def guide(self, noise: Any, prepared: PreparedStep, state: RunState) -> Any:
        """Wan 的 CFG：**再跑一次 uncond 前向**，再线性组合（与上游 L623-632 同序）。"""
        if not state.do_guidance:
            return noise
        net = self.bag.require(self._NET)
        uncond = net(**self._net_kwargs(state, prepared, embeds=self._ne))[0]
        scale = float(getattr(state, "cfg_scale", 0.0) or 0.0)
        return uncond + scale * (noise - uncond)

    def step_extra_kwargs(self, generator: Any = None) -> Dict[str, Any]:
        # 上游 WanPipeline: scheduler.step(noise_pred, t, latents, return_dict=False) —— 不带其它参数
        return {}

    def step(self, noise: Any, t: Any, prepared: PreparedStep, state: RunState) -> Any:
        sch = self.bag.require(self._SCHED)
        return sch.step(noise, t, prepared.raw, return_dict=False)[0]

    # ── 解码 ───────────────────────────────────────────
    def decode(self, latents: Any, state: Any = None) -> Any:
        import torch

        vae = self.bag.require(self._VAE)
        latents = latents.to(vae.dtype)
        cfg = vae.config
        mean = torch.tensor(cfg.latents_mean).view(1, cfg.z_dim, 1, 1, 1).to(
            latents.device, latents.dtype)
        std = 1.0 / torch.tensor(cfg.latents_std).view(1, cfg.z_dim, 1, 1, 1).to(
            latents.device, latents.dtype)
        latents = latents / std + mean
        # 分块解码：chunk<=0 或帧数不够切时与上游**完全同形**（比特级不受影响）；
        # chunk>0 才按时间维切块 —— 这是 8GB 显存策略，不改变可复现性（chunk 不进请求）。
        chunk = int(getattr(state, "decode_chunk", 0) or 0) if state is not None else 0
        total = int(latents.shape[2])
        if chunk <= 0 or total <= chunk:
            video = vae.decode(latents, return_dict=False)[0]
        else:
            parts = []
            for i in range(0, total, chunk):
                parts.append(vae.decode(latents[:, :, i:i + chunk], return_dict=False)[0])
            video = torch.cat(parts, dim=2)
        return self._to_pil_frames(video)

    def _to_pil_frames(self, video: Any) -> List[Any]:
        """与上游 video_processor.postprocess_video(output_type="pil") 等价的最小实现。"""
        import torch
        from PIL import Image
        v = video[0] if hasattr(video, "shape") and video.dim() == 5 else video
        arr = ((v.float() / 2.0 + 0.5).clamp(0, 1) * 255).round().to(torch.uint8)
        arr = arr.permute(1, 2, 3, 0).cpu().numpy()      # [T,H,W,C]
        return [Image.fromarray(f) for f in arr]

    # ── 缓存键 ─────────────────────────────────────────
    def cache_key(self) -> Tuple[str, ...]:
        return ("wan", str(self._model_path()), str(self._dtype()))
