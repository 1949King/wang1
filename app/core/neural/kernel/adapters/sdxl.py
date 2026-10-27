# -*- coding: utf-8 -*-
"""SDXL 族适配器（规范 §5）。

## 与 SD1.5 的四处实质差异（都不是"多传一个参数"那么简单）

| 点 | SD1.5 | SDXL | 写错的后果 |
|---|---|---|---|
| 条件 | `prompt_embeds` | `prompt_embeds` + **pooled** + **time_ids** | 少了 `added_cond_kwargs` 直接抛 TypeError；传错形状则出灰图 |
| `add_time_ids` | 无 | `[h,w,0,0,h,w]`，**先 `cat([neg,pos])` 再 `repeat(batch,1)`** | 顺序反了：`repeat` 后再 cat ⇒ 变成 4 行，batch 错位，图全花 |
| VAE 反缩放 | 0.18215 | **0.13025**（部分 checkpoint 还有 `latents_mean/std`） | 用 0.18215 会偏色/过曝，不报错 |
| VAE 精度 | fp16 直解 | 若 `force_upcast` 则先升 fp32 再降回 | fp16 解 SDXL 会溢出成噪点 |

前三条来自 `pipeline_stable_diffusion_xl.py:1122-1155`（条件拼接）与 `:1272-1291`（解码），
第四条来自 `:1260-1291`。逐条抄，不推测。

## `add_time_ids` 为什么自己算而不调上游私有方法

上游是 `pipe._get_add_time_ids(...)`（下划线私有）。押注一个私有方法，
等于把"上游可替换性"（C3）交还给上游。所以这里自己算 6 个数，
但**保留上游那个维度断言的价值**：算完拿 `add_embedding.linear_1.in_features` 校验一遍，
不匹配就明确拒绝 —— 这比"算完直接用、形状不对再抛个看不懂的错"有用得多。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.core.neural.kernel.adapters.base import BaseAdapter
from app.core.neural.kernel.contracts import (
    AdapterCaps, GenRequest, ParityContract, VERIFIED,
)

logger = logging.getLogger(__name__)

#: SDXL 的 VAE 反缩放（**不是** SD1.5 的 0.18215）
_SDXL_SCALING_FACTOR = 0.13025


class SDXLAdapter(BaseAdapter):
    """Stable Diffusion XL 族。"""

    family = "sdxl"

    caps = AdapterCaps(
        cfg_mode="cat",
        cfg_batch_multiplier=2,
        allow_cfg_merge=False,
        cond_keys=("prompt_embeds", "pooled", "time_ids"),
        timestep_kind="scalar",
        latent_rank=4,
        latent_scale="init_noise_sigma",
        vae_decode="scalar_factor",
        scheduler_family="eps",
        # 2026-10-28 四门验收通过：PSNR=inf / 逐step Δ=0 / 时延 1.028× / 显存 0.969×
        verified=VERIFIED,
    )

    parity = ParityContract(
        fields={
            "scale_model_input": True,
            "init_noise_sigma_once": True,
            "cfg_order": "neg_pos",
            "clip_skip": 1,
            "encode_delegate": True,
            "latent_scale": 8,
            "randn_source": "diffusers.randn_tensor",
            "timestep_cond": None,
            "vae_scale_before_decode": True,
            "decode_postprocess": "pil",
            "added_cond_kwargs": ("text_embeds", "time_ids"),
            "time_ids_concat_then_repeat": True,
            "time_ids_layout": "h,w,0,0,h,w",
            "vae_scaling_factor": _SDXL_SCALING_FACTOR,
            "vae_force_upcast": "follow_config",
            "latents_mean_std": "if_present",
        },
        tensor_rtol=1e-3,
        psnr_min_db=35.0,
    )

    def bind(self, bag: Any) -> None:
        super().bind(bag)
        # 同 SD15：缺组件由 `validate()` 报原因，不在 bind 里抛（规范 §5.1）
        net = bag.get("unet")
        if net is not None:
            bag.register("net", net)

    def validate(self) -> List[str]:
        bad = super().validate()
        if bad:
            return bad
        for key, human in (("net", "主网络（unet）"), ("vae", "解码器（vae）"),
                           ("scheduler", "调度器")):
            if not self.bag.has(key):
                bad.append("缺少%s组件" % human)
        if not self.bag.has("text_encoder_2"):
            # SDXL 的 pooled 来自第二个文本编码器；缺了就没法拼 added_cond_kwargs
            bad.append("缺少第二文本编码器（text_encoder_2）⇒ 无法生成 pooled 条件")
        return bad

    # ── 编码 ──────────────────────────────────────────────────
    def encode(self, req: GenRequest, do_guidance: bool = True) -> Dict[str, Any]:
        pipe = self.pipe
        if pipe is None or not hasattr(pipe, "encode_prompt"):
            raise RuntimeError("上游 encode_prompt 不可用，SDXL 适配器无法保证编码等价性")

        out = pipe.encode_prompt(
            req.prompt,
            prompt_2=None,
            device=self._device(),
            num_images_per_prompt=1,
            do_classifier_free_guidance=bool(do_guidance),
            # ★ 逐字透传，**不许**写成 `req.negative_prompt or None`：
            #   SDXL 的 `""` 与 `None` 编出来的负向条件**不一样**（实测 max|Δ|=854）。
            #   stock 路径把用户给的字符串原样交给 pipe，内核必须与它一致，
            #   否则每步偏差 ~2.5、PSNR 掉到 23dB —— 而这两条路都"能出图"，不报错。
            negative_prompt=req.negative_prompt,
            negative_prompt_2=None,
            clip_skip=None,
        )
        if not isinstance(out, (tuple, list)) or len(out) != 4:
            raise RuntimeError("上游 encode_prompt 返回值不是 4 元组（SDXL 契约变了）")
        embeds, neg_embeds, pooled, neg_pooled = out

        time_ids = self._time_ids(req, embeds, bool(do_guidance))

        import torch

        if do_guidance:
            # ★ 顺序必须是 (neg, pos)；且 time_ids 是 **先 cat 再 repeat**
            embeds = torch.cat([neg_embeds, embeds])
            pooled = torch.cat([neg_pooled, pooled])
        return {
            "prompt_embeds": embeds.to(self._device()),
            "pooled": pooled.to(self._device()),
            "time_ids": time_ids.to(self._device()),
        }

    def _time_ids(self, req: GenRequest, embeds: Any, do_guidance: bool) -> Any:
        """`[h, w, 0, 0, h, w]` → (1,6) → cat 后 repeat(batch)。

        上游 `original_size = target_size = (height, width)`，
        `crops_coords_top_left = (0, 0)`（我们没暴露裁剪偏移，故恒为 0）。

        `do_guidance` 由调用方传入，本方法**不自己再判一次** ——
        "要不要 CFG"只能有一个判据真源，判两次迟早漂移。
        """
        import torch

        h, w = int(req.height), int(req.width)
        layout = [h, w, 0, 0, h, w]
        ids = torch.tensor([layout], dtype=embeds.dtype)

        # 保留上游那条维度断言的价值：形状不匹配时明确说清，而不是等前向抛怪错
        net = self.bag.require("net")
        try:
            expect = int(net.add_embedding.linear_1.in_features)
        except Exception:  # stability-gate: allow-swallow（个别自定义模型没有 add_embedding：跳过断言，不阻断）
            expect = -1
        proj_dim = self._projection_dim()
        if expect > 0 and proj_dim > 0:
            add_dim = int(getattr(net.config, "addition_time_embed_dim", 0) or 0)
            got = add_dim * len(layout) + proj_dim
            if add_dim and got != expect:
                raise RuntimeError(
                    "add_time_ids 维度不匹配：模型期望 %d，本次算出 %d"
                    "（addition_time_embed_dim=%d × %d + projection_dim=%d）"
                    % (expect, got, add_dim, len(layout), proj_dim))

        # do_guidance 时 neg 与 pos 的 time_ids 相同（未传 negative_original_size）
        batch = max(1, int(req.batch))
        if do_guidance:
            return torch.cat([ids, ids]).repeat(batch, 1)
        return ids.repeat(batch, 1)

    def _projection_dim(self) -> int:
        enc2 = self.bag.get("text_encoder_2")
        dim = getattr(getattr(enc2, "config", None), "projection_dim", None)
        try:
            return int(dim) if dim else 0
        except (TypeError, ValueError):
            return 0

    def cache_key(self, req: GenRequest) -> tuple:
        return ("sdxl", req.prompt, req.negative_prompt, req.width, req.height,
                int(req.batch))

    # ── 每步前向 ──────────────────────────────────────────────
    def _net_kwargs(self, state: Any, prepared: Any) -> Dict[str, Any]:
        cond = state.ctx or {}
        return {
            "encoder_hidden_states": cond.get("prompt_embeds"),
            "timestep_cond": None,
            "cross_attention_kwargs": None,
            "added_cond_kwargs": {
                "text_embeds": cond.get("pooled"),
                "time_ids": cond.get("time_ids"),
            },
        }

    # ── 解码（含 upcast / latents_mean 两个分支）───────────────
    def decode(self, latents: Any) -> Any:
        import torch

        dec = self.bag.require("vae")
        cfg = dec.config

        force_upcast = bool(getattr(cfg, "force_upcast", False))
        needs_upcast = (getattr(dec, "dtype", None) == torch.float16) and force_upcast
        if needs_upcast:
            # 上游 :1264-1266：fp16 解 SDXL 会溢出 ⇒ 先升 fp32
            dec.to(dtype=torch.float32)
            try:
                latents = latents.to(next(iter(dec.post_quant_conv.parameters())).dtype)
            except Exception:  # stability-gate: allow-swallow（个别 VAE 没有 post_quant_conv：保持原 dtype，不影响正确性）
                latents = latents.to(torch.float32)
        elif getattr(latents, "dtype", None) != getattr(dec, "dtype", None):
            latents = latents.to(getattr(dec, "dtype", torch.float32))

        mean = getattr(cfg, "latents_mean", None)
        std = getattr(cfg, "latents_std", None)
        scaling = float(getattr(cfg, "scaling_factor", _SDXL_SCALING_FACTOR))
        if mean is not None and std is not None:
            m = torch.tensor(mean).view(1, 4, 1, 1).to(latents.device, latents.dtype)
            s = torch.tensor(std).view(1, 4, 1, 1).to(latents.device, latents.dtype)
            latents = latents * s / scaling + m
        else:
            latents = latents / scaling

        image = dec.decode(latents, return_dict=False)[0]
        if needs_upcast:
            dec.to(dtype=torch.float16)

        proc = getattr(self.pipe, "image_processor", None) if self.pipe else None
        if proc is not None:
            return proc.postprocess(image, output_type="pil")[0]

        from PIL import Image as _Image

        arr = (image / 2 + 0.5).clamp(0, 1)
        arr = (arr.permute(0, 2, 3, 1).float().cpu().numpy() * 255).round().astype("uint8")
        return _Image.fromarray(arr[0])
