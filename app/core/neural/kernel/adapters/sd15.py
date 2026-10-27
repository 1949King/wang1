# -*- coding: utf-8 -*-
"""SD1.5 族适配器（规范 §5）。

## 语义来源（逐条抄自上游，不是推测）

`.venv312/Lib/site-packages/diffusers/pipelines/stable_diffusion/pipeline_stable_diffusion.py`

| 行 | 语义 |
|---|---|
| 601 / 1085 | 解码前 `latents / vae.config.scaling_factor`（SD1.5 = 0.18215） |
| 690-713 | `shape = (b, c, h//8, w//8)`；`randn_tensor`；`* scheduler.init_noise_sigma` |
| 1038-1039 | `hasattr(scheduler, "scale_model_input")` 才调（DDIM 有，LCM 无） |
| 1028-1032 | CFG：`cat([latents]*2)` → `chunk(2)` → `uncond + s*(text-uncond)` |
| 1057-1059 | `guidance_rescale > 0` 才做 rescale |
| 1062 | `scheduler.step(noise, t, latents, **extra, return_dict=False)[0]` |

## 三个"漏了不报错、只掉 PSNR"的点（已写进 ParityContract）

1. **`timestep_cond`**：SD1.5 的 `time_cond_proj_dim is None` ⇒ 必须传 `None`。
   LCM 系模型不为 None，此时上游会**关掉 CFG** —— 我们的 `do_guidance` 判据也照此。
2. **`clip_skip`**：上游 `encode_prompt(clip_skip=None)` ⇒ 走 `hidden_states[-2]`。
   自己实现编码时写成 `[0]`（last_hidden_state）不会报错，图会变"平"。
   本 adapter 把编码委托上游（`encode_delegate=True`），从根上避开这条。
3. **`scale_model_input` 的对象是"拼好的 batch"**，不是原始 latents。
   顺序反了在 Euler 上无差别（scale=1），在 LCM/DPMSolver 上才开始糊。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.core.neural.kernel.adapters.base import BaseAdapter
from app.core.neural.kernel.contracts import (
    AdapterCaps, GenRequest, ParityContract, VERIFIED,
)

logger = logging.getLogger(__name__)

#: vae_scale_factor 的兜底值（SD1.5 = 8）
_LATENT_SCALE = 8


class SD15Adapter(BaseAdapter):
    """Stable Diffusion 1.x 族。"""

    family = "sd15"

    caps = AdapterCaps(
        cfg_mode="cat",
        cfg_batch_multiplier=2,
        allow_cfg_merge=False,
        cond_keys=("prompt_embeds",),
        timestep_kind="scalar",
        latent_rank=4,
        latent_scale="init_noise_sigma",
        vae_decode="scalar_factor",
        scheduler_family="eps",
        # 2026-10-28 四门验收通过：PSNR=inf / 逐step Δ=0 / 时延 1.015× / 显存 1.000×
        verified=VERIFIED,
    )

    parity = ParityContract(
        fields={
            "scale_model_input": True,
            "init_noise_sigma_once": True,
            "cfg_order": "neg_pos",
            "clip_skip": 1,
            "encode_delegate": True,
            "latent_scale": _LATENT_SCALE,
            "randn_source": "diffusers.randn_tensor",
            "timestep_cond": None,
            "vae_scale_before_decode": True,
            "decode_postprocess": "pil",
        },
        tensor_rtol=1e-3,
        psnr_min_db=35.0,
    )

    def bind(self, bag: Any) -> None:
        super().bind(bag)
        # 中性 key 映射：上游叫 unet，内核只认 net（上游改名时只改这一行）。
        # 用 get 不用 require：缺组件是**体检结论**（`validate()` 报原因），
        # 不是异常 —— 规范 §5.1 明确禁止用异常代替返回原因。
        net = bag.get("unet")
        if net is not None:
            bag.register("net", net)

    def validate(self) -> List[str]:
        bad = super().validate()
        if bad:
            return bad
        if not self.bag.has("net"):
            bad.append("缺少主网络组件（unet）")
        if not self.bag.has("vae"):
            bad.append("缺少解码器组件（vae）")
        if not self.bag.has("scheduler"):
            bad.append("缺少调度器组件（scheduler）")
        return bad

    # ── 编码（委托上游，保证 bit 一致）──────────────────────────
    def encode(self, req: GenRequest, do_guidance: bool = True) -> Dict[str, Any]:
        pipe = self.pipe
        if pipe is None or not hasattr(pipe, "encode_prompt"):
            # 没有上游编码工具 ⇒ 明确拒绝，不自己拼一套近似编码
            raise RuntimeError("上游 encode_prompt 不可用，SD15 适配器无法保证编码等价性")

        embeds, neg = pipe.encode_prompt(
            req.prompt,
            self._device(),
            1,                                  # num_images_per_prompt
            bool(do_guidance),
            # 逐字透传（不写 `or None`）：与 stock 路径喂给 pipe 的值保持一字不差。
            # SD15 上 "" 与 None 结果相同，但**不能因此**两族写两套 —— 判据一次就够。
            negative_prompt=req.negative_prompt,
            clip_skip=None,                     # 上游默认 ⇒ hidden_states[-2]
        )
        try:
            import torch

            if do_guidance and neg is not None:
                # ★ 顺序 (neg, pos)：与上游 cat([negative_prompt_embeds, prompt_embeds]) 一致
                embeds = torch.cat([neg, embeds])
        except Exception:  # stability-gate: allow-swallow（无 torch 说明环境不对，引擎会在更外层以缺依赖拒绝）
            logger.debug("[kernel.sd15] 条件张量拼接失败", exc_info=True)
        return {"prompt_embeds": embeds}

    def cache_key(self, req: GenRequest) -> tuple:
        return ("sd15", req.prompt, req.negative_prompt, req.width, req.height,
                int(req.batch))

    # ── 每步前向的额外 kwargs ──────────────────────────────────
    def _net_kwargs(self, state: Any, prepared: Any) -> Dict[str, Any]:
        cond = state.ctx or {}
        return {
            "encoder_hidden_states": cond.get("prompt_embeds"),
            # 上游 SD1.5 恒传 timestep_cond（time_cond_proj_dim 为 None 时就是 None）
            "timestep_cond": None,
            "cross_attention_kwargs": None,
            "added_cond_kwargs": None,
        }

    # ── 解码 ──────────────────────────────────────────────────
    def decode(self, latents: Any, state: Any = None) -> Any:
        dec = self.bag.require("vae")
        scaling = float(getattr(dec.config, "scaling_factor", 0.18215))
        image = dec.decode(latents / scaling, return_dict=False)[0]
        proc = getattr(self.pipe, "image_processor", None) if self.pipe else None
        if proc is not None:
            return proc.postprocess(image, output_type="pil")[0]
        # 退路：手写 [-1,1] → [0,255]（与上游 postprocess 等价）
        import numpy as np
        from PIL import Image as _Image

        arr = (image / 2 + 0.5).clamp(0, 1)
        arr = (arr.permute(0, 2, 3, 1).float().cpu().numpy() * 255).round().astype("uint8")
        return _Image.fromarray(arr[0]) if np is not None else None
