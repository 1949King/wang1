# -*- coding: utf-8 -*-
"""SVD 族适配器（Stable Video Diffusion img2vid，规范 §5）。

语义来源：`.venv312/Lib/site-packages/diffusers/pipelines/stable_video_diffusion/
pipeline_stable_video_diffusion.py`（diffusers 0.40.0）。**逐行对照，不推测。**

## 与图像族的 11 处实质差异（每一处漏了都不报错，只出错视频）

| 点 | 图像族 | SVD | 写错的后果 |
|---|---|---|---|
| 条件来源 | 文本 `encode_prompt` | **CLIP 视觉编码器** `image_embeds` → `(B,1,1024)` | 没有文本可言，传 prompt 无用 |
| 无条件支 | 空串负向编码 | **`torch.zeros_like(embeds)`**（`:230`） | 用"空文本"会得到非零支 ⇒ 引导方向错，画面漂移 |
| 引导强度 | 单标量 `cfg` | **逐帧标量** `linspace(min,max,frames)`（`:570-573`） | 单标量能跑通，只是首帧与末帧引导相同 ⇒ 运动塌陷 |
| 是否 CFG | `cfg > 1` | `guidance_scale.max() > 1`（`:378`） | 等价（linspace 的 max 就是 `max_guidance_scale`） |
| 噪声增广 | 无 | `image + noise_aug * noise`，**先于初始 latents 抽随机数**（`:511`） | 顺序错一位 ⇒ 初始 latents 不再比特一致，且不报错 |
| VAE 编码 | `sample()` + `*scaling` | `latent_dist.mode()`，**不乘 scaling**（`:247`） | 乘了 scaling 会让条件弱 5.5 倍，画面几乎不跟首帧 |
| 条件拼接 | batch 维（encoder_hidden_states） | 图像 latent 沿**通道维** `dim=2` 拼（`:587`） | 拼 batch 维能跑通（4 通道），只是 UNet 收到的是别的帧的条件 |
| latents 形状 | `(B,C,H,W)` | `(B, frames, C, H, W)`，噪声通道 = `in_channels//2`（`:345-351`） | 用 `in_channels` 会造 8 通道噪声，前向直接崩 |
| `added_time_ids` | 无 / SDXL 6 个数 | 3 个数 `[fps-1, motion_bucket, noise_aug]`，**先 repeat 再 cat**（`:283-286`） | 与 SDXL 相反；写反了变成 2 行 ⇒ batch 错位 |
| 解码 | 一次解完 | **按 `decode_chunk_size` 分块** + `reshape/permute`（`:290-317`） | 一次解 25 帧直接 OOM（8GB 卡实测） |
| `fps` | 无 | 传进去的是 **`fps - 1`**（`:507`，Stability 原始实现如此） | 传 fps 本身 ⇒ 运动幅度与 stock 不同 |

## 随机数消耗顺序（唯一一处"顺序本身就是语义"的地方）

上游 `__call__` 的顺序是：

```
_encode_image(CLIP)          # 无随机
fps = fps - 1                # 无随机
randn_tensor(image.shape)    # ★ 第 1 次抽：噪声增广
_encode_vae_image            # mode()，无随机
prepare_latents → randn      # ★ 第 2 次抽：初始潜变量
```

所以本 adapter 的 `encode()` 必须**自己**完成"抽噪声增广 + VAE 编码"，
而不能留给 `init_latents()` —— 引擎的调用顺序恰好是 `encode()` → `make_timesteps()`
→ `init_latents()`，顺序天然对齐；若把增广挪进 `init_latents`，两组噪声就互换了，
初始 latents 不再比特一致，而现象只是"视频不一样"。

## 编码为什么仍然委托上游私有方法

`_encode_image` 里含 `_resize_with_antialiasing`（高斯模糊 + bicubic，约 80 行）
与 CLIP 预处理的 4 个 `do_*` 开关。抄一遍的唯一后果是"多一处与上游漂移的可能"，
而它恰好是最难测的一项（像素级 resize 差异只表现为条件张量差 1e-3）。
策略与 `sd15.py` 的 `encode_prompt` 一致：**编码委托上游、循环归本仓库**，
并在 `ParityContract.encode_delegate` 里写明这一项依赖上游。
上游删了这个方法 ⇒ `validate()` 会明确拒绝（见 `_encode_image_delegate`），
不是静默降级。

## 为什么 `decode()` 不升 fp32

上游 `:621-623` 在 `needs_upcasting` 时把 VAE **降回 fp16 再解码**
（编码时升 fp32、解码时降回来，看着反直觉，但这就是它写的）。
本 adapter 与上游一致：编码处临时升 fp32 并在 `finally` 里还原，解码处不动 dtype。
"顺手把解码也升 fp32"会让 PSNR 对照立刻掉到 30dB 以下 —— 那是我们自己引入的偏差。
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.neural.kernel import schedule as SCHED
from app.core.neural.kernel.adapters.base import BaseAdapter, PreparedStep
from app.core.neural.kernel.contracts import (
    AdapterCaps, GenRequest, ParityContract, VERIFIED,
)

logger = logging.getLogger(__name__)

#: 上游 `__call__` 的默认 `fps`（`:396`）
_DEFAULT_FPS = 7
#: 上游默认 `motion_bucket_id`（`:397`）
_DEFAULT_MOTION_BUCKET = 127
#: 上游默认 `noise_aug_strength`（`:398`）
_DEFAULT_NOISE_AUG = 0.02
#: 上游默认 `min/max_guidance_scale`（`:394-395`）
_DEFAULT_CFG_MIN = 1.0
_DEFAULT_CFG_MAX = 3.0
#: 上游默认 `num_inference_steps`（`:392`）
_DEFAULT_STEPS = 25


class SVDAdapter(BaseAdapter):
    """Stable Video Diffusion（图生视频）族。

    `caps.verified=VERIFIED` 的依据是 2026-10-28 P3 的四门实测（见 caps 处注释与
    `docs/knowledge/kernel_evidence.json`）。**任何一个门重新变红，这个字段就要改回
    UNVERIFIED** —— 内核会随即明确拒绝并回退上游，而不是继续悄悄接管。
    """

    family = "svd"

    caps = AdapterCaps(
        # SVD 的引导同样是"拼 batch 做一次前向再 chunk"，与 cat 同构
        cfg_mode="cat",
        cfg_batch_multiplier=2,
        allow_cfg_merge=False,
        cond_keys=("image_embeds", "image_latents", "added_time_ids", "guidance"),
        timestep_kind="scalar",
        latent_rank=5,
        # Euler 的 init_noise_sigma = 700（本模型 scheduler_config sigma_max=700），
        # 必须由内核乘**一次**；漏乘等于把噪声缩了 700 倍 ⇒ 出片是一团糊
        latent_scale="init_noise_sigma",
        vae_decode="chunked_temporal",
        scheduler_family="eps",
        # 2026-10-28 P3 四门验收通过（512×288 / 6 帧 / 14 步 / 3 seed / 交错 3 轮换序）：
        #   初始 latents 比特一致 · 逐 step max|Δ|=0 · **逐帧** PSNR=inf ·
        #   时延 1.014×（持平档）· 显存 1.000×（门槛 1.10）· 第 0 步前取消生效。
        # 证据：docs/knowledge/kernel_evidence.json（含两次速度门失败的历史）。
        verified=VERIFIED,
    )

    parity = ParityContract(
        fields={
            "scale_model_input": True,
            "init_noise_sigma_once": True,
            "cfg_order": "neg_pos",
            "randn_source": "diffusers.randn_tensor",
            # 输入图先加噪再进 VAE，且**先于**初始 latents 消耗随机数
            "noise_aug_before_vae": True,
            # 无条件支是全零张量，不是"空文本编码"
            "uncond_repr": "zeros_like",
            # 图像条件拼在通道维（4 + 4 = 8）
            "image_latent_concat_dim": 2,
            # 先 repeat 再 cat（与 SDXL 的 cat 再 repeat 相反）
            "added_time_ids_order": "repeat_then_cat",
            "added_time_ids_layout": "fps-1,motion_bucket,noise_aug",
            # 逐帧标量（frames 维），不是单个标量
            "guidance_shape": "per_frame",
            # 分块解码 + reshape/permute
            "decode_chunked": True,
            "decode_postprocess": "video_processor.pil",
            # 编码委托上游 CLIP 视觉编码器（含抗锯齿 resize，抄不动也不该抄）
            "encode_delegate": True,
            "latent_rank": 5,
            "vae_encode_mode": "latent_dist.mode",
            "vae_encode_no_scaling": True,
            "vae_scale_before_decode": True,
            "fps_minus_one": True,
        },
        tensor_rtol=1e-3,
        psnr_min_db=35.0,
    )

    def bind(self, bag: Any) -> None:
        super().bind(bag)
        # 中性 key 映射；缺组件由 validate() 报原因（规范 §5.1，不用异常代替返回原因）
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
        # 条件来自 CLIP **视觉**编码器：缺了就没有条件可用（SVD 不接受文本）
        if not self.bag.has("image_encoder"):
            bad.append("缺少图像编码器（image_encoder）⇒ SVD 无文本条件，缺它就没有条件")
        if not self.bag.has("feature_extractor"):
            bad.append("缺少 CLIP 预处理（feature_extractor）⇒ 条件张量无法归一化")
        if not self.bag.has("video_processor"):
            bad.append("缺少 video_processor ⇒ 输入图预处理与成片后处理都会与上游漂移")
        bad.extend(self._deep_checks())
        return bad

    def _deep_checks(self) -> List[str]:
        """绑定之后才能做的三条"事先就能判死"的检查。

        放在这里而不是等前向抛错，是因为这三种情况都是**配置层面的必然失败**：
        `added_time_ids` 维度不对时上游抛的是一句"模型 config 有问题，请检查..."，
        对一个只想出片的调用方毫无可操作性。
        """
        bad: List[str] = []
        net = self.bag.get("net")
        cfg = getattr(net, "config", None)
        if cfg is None:
            return bad

        # ① 噪声通道必须正好是 in_channels 的一半
        try:
            in_ch = int(cfg.in_channels)
        except (TypeError, ValueError):
            in_ch = 0
        if in_ch and in_ch % 2:
            bad.append("unet.config.in_channels=%d 为奇数 ⇒ 无法拆成「噪声一半 + 图像条件一半」"
                       % in_ch)

        # ② added_time_ids 的宽度必须与 add_embedding 的入口维度对上
        add_dim = int(getattr(cfg, "addition_time_embed_dim", 0) or 0)
        expect = -1
        try:
            expect = int(net.add_embedding.linear_1.in_features)
        except Exception:  # stability-gate: allow-swallow（个别自定义模型没有 add_embedding：跳过断言，不阻断）
            expect = -1
        if add_dim and expect > 0 and add_dim * 3 != expect:
            bad.append(
                "added_time_ids 维度不匹配：模型期望 %d，本次算出 %d（addition_time_embed_dim=%d × 3）"
                % (expect, add_dim * 3, add_dim))

        # ③ 上游 CLIP 编码入口必须在（本 adapter 委托它，没有就等价于"没有条件编码"）
        if self.pipe is not None and not hasattr(self.pipe, "_encode_image"):
            bad.append("上游缺少 `_encode_image`（SVD 条件编码入口已被上游移除）"
                       "⇒ 内核无法保证条件等价，需重做编码层")
        return bad

    # ══════════════════════════════════════════════════════════════
    # 编码：CLIP 嵌入 + 噪声增广 + VAE 图 latent + 时间 ID + 逐帧引导
    # ══════════════════════════════════════════════════════════════
    def encode(self, req: GenRequest, do_guidance: bool = True,
               generator: Any = None) -> Dict[str, Any]:
        image = self._load_input_image(req)
        h, w = self._pixel_size(req)
        frames = self._num_frames(req)

        # ① CLIP 图像嵌入（无随机）。无条件支由上游 `_encode_image` 自己补全零。
        embeds = self._encode_clip(image, bool(do_guidance))

        # ② fps - 1（Stability 原始实现如此，见上游 :505-507 的注释）
        fps = max(1, int(req.fps or _DEFAULT_FPS)) - 1
        mb = int(req.motion_bucket_id or _DEFAULT_MOTION_BUCKET)
        nas = self._noise_aug(req)

        # ③ 噪声增广：**先于**初始 latents 抽随机数（顺序即语义，见模块文档）
        proc = self.bag.require("video_processor")
        pixels = proc.preprocess(image, height=h, width=w).to(self._device())
        noise = self._randn(pixels.shape, generator=generator,
                            device=self._device(), dtype=pixels.dtype)
        pixels = pixels + float(nas) * noise

        # ④ VAE 编码 → 图像 latent（`mode()`，**不乘 scaling_factor**）
        image_latents = self._encode_vae_image(pixels, bool(do_guidance))
        # ★ 上游 `:524` 的 `image_latents.to(image_embeddings.dtype)`。
        #   漏了它 → 条件张量停在 fp32，而 UNet 权重是 fp16，
        #   前向第一层就 `mat1 and mat2 must have the same dtype` —— 报错还算好的，
        #   最坏情况是某些算子静默按 fp32 算完再降回来，逐帧 PSNR 慢慢掉。
        #   这条在离线单测里看不出来（替身 VAE 就一个 dtype），只有真机才炸。
        image_latents = image_latents.to(embeds.dtype)

        # ⑤ 帧维广播：`(B,C,h,w)` → `(B,frames,C,h,w)`
        image_latents = image_latents.unsqueeze(1).repeat(1, frames, 1, 1, 1)

        # ⑥ 时间 ID（先 repeat 再 cat）
        added_time_ids = self._added_time_ids(
            fps, mb, nas, embeds.dtype, bool(do_guidance),
            batch=max(1, int(req.batch)))
        added_time_ids = added_time_ids.to(self._device())

        # ⑦ 逐帧引导强度（min → max 线性插值）
        guidance = self._guidance_scale(req, frames, bool(do_guidance), embeds.dtype)

        return {
            "image_embeds": embeds,
            "image_latents": image_latents,
            "added_time_ids": added_time_ids,
            "guidance": guidance,
            "fps": fps,
            "motion_bucket_id": mb,
            "noise_aug_strength": nas,
            "frames": frames,
            "pixel_size": (h, w),
        }

    # ── 编码子步骤 ────────────────────────────────────────────────
    def _load_input_image(self, req: GenRequest) -> Any:
        """按 `video_gen.generate` 的**同一路径**读图。

        为什么不用 `PIL.Image.open`：stock 路径是 `imageio.v3.imread` + `fromarray`，
        两条路对 JPEG 的解码（IDCT 实现不同）可能差 1 个 LSB。
        只差 1 个 LSB 也够让"逐帧 PSNR"从 inf 掉到 50dB 以下 —— 然后人会去查循环，
        查半天发现是读图读法不同。所以这里刻意与调用方用同一个读法。
        """
        path = str(req.image_path or "")
        if not path:
            raise RuntimeError("SVD 是图生视频族：必须给 image_path（没有文本条件可用）")
        import os

        if not os.path.isfile(path):
            raise RuntimeError("输入图不存在: %s" % path)
        try:
            import imageio.v3 as iio
            import numpy as np
            from PIL import Image as _Image

            img = iio.imread(path)
            if img.ndim == 2:
                img = np.stack([img] * 3, axis=-1)
            return _Image.fromarray(img[:, :, :3])
        except Exception:  # stability-gate: allow-swallow（imageio 缺失/读不了时退回 PIL，并记 warning 让差异可见）
            logger.warning("[kernel.svd] imageio 读图失败，退回 PIL 读图"
                           "（JPEG 解码可能与 stock 差 1 个 LSB）", exc_info=True)
            from PIL import Image as _Image

            return _Image.open(path).convert("RGB")

    def _pixel_size(self, req: GenRequest) -> Tuple[int, int]:
        """`(height, width)`。`0` 表示"没要求"，此时按上游的派生规则算。

        上游 `__call__:480-481` 是 `height or unet.config.sample_size * vae_scale_factor`。
        但**上游签名默认值是 576×1024**，所以 stock 路径在调用方不传尺寸时用的是
        576×1024，而不是派生出来的 768×768。两条路尺寸不同 ⇒ PSNR 无从谈起。
        因此：调用方（`video_gen`）**必须**显式传尺寸；真没传时这里按派生规则算，
        并留一条 note 让"尺寸与 stock 可能不同"这件事可见，而不是静默当成对齐。
        """
        h, w = int(req.height or 0), int(req.width or 0)
        if h > 0 and w > 0:
            return h, w
        net = self.bag.get("net")
        sample = int(getattr(getattr(net, "config", None), "sample_size", 0) or 0)
        factor = self._latent_scale()
        if sample > 0:
            d = sample * factor
            self.notes.append(
                "请求未给尺寸 ⇒ 按 unet.config.sample_size×vae_scale_factor 取 %d×%d；"
                "stock 路径的签名默认是 576×1024，两者画质不可直接比较" % (d, d))
            return (h or d), (w or d)
        self.notes.append("请求未给尺寸且模型未声明 sample_size ⇒ 回落 576×1024（上游签名默认）")
        return (h or 576), (w or 1024)

    def _num_frames(self, req: GenRequest) -> int:
        frames = int(req.frames or 0)
        if frames > 0:
            return frames
        net = self.bag.get("net")
        default = int(getattr(getattr(net, "config", None), "num_frames", 0) or 14)
        self.notes.append("请求未给帧数 ⇒ 取 unet.config.num_frames=%d" % default)
        return default

    def _noise_aug(self, req: GenRequest) -> float:
        """噪声增广强度。

        `0` 表示"取上游默认 0.02"（本结构里 0 一律是"没要求"，见 `GenRequest` 文档）。
        **想表达"完全不加噪"请传 1e-6** —— 这一条写在这里而不是让 0 兼两义：
        0.0 与 0.02 在 SVD 上出来的片子差别很大（加噪越小越"冻结"），
        把两者混成一个值，用户就没法要"绝对冻结"了。
        """
        v = float(req.noise_aug_strength or 0.0)
        return _DEFAULT_NOISE_AUG if v == 0.0 else v

    def _encode_clip(self, image: Any, do_guidance: bool) -> Any:
        """委托上游 `_encode_image`（含抗锯齿 resize + CLIP 预处理）。

        返回 `(B, 1, 1024)`；`do_guidance` 时 batch 维翻倍且**前半是全零张量**。
        这条"无条件支是全零、不是空文本"由上游实现，我们只在 `parity` 里记下这个事实
        （`uncond_repr="zeros_like"`）—— 记下来是为了将来不依赖上游时知道要补什么。
        """
        pipe = self.pipe
        if pipe is None or not hasattr(pipe, "_encode_image"):
            raise RuntimeError("上游 `_encode_image` 不可用，SVD 适配器无法保证条件等价性")
        # 委托上游编码是本族的既定策略（见模块文档「编码为什么仍然委托上游私有方法」）
        return pipe._encode_image(
            image,
            self._device(),
            1,                      # num_videos_per_prompt
            bool(do_guidance),
        )

    def _encode_vae_image(self, pixels: Any, do_guidance: bool) -> Any:
        """`vae.encode(px).latent_dist.mode()`，必要时空升 fp32。

        三点必须照抄：
          1. **`mode()` 而不是 `sample()`**：`sample()` 会再抽一次随机数，
             随机数消耗顺序当场错位（而且多抽一组噪声）。
          2. **不乘 `scaling_factor`**：SVD 的编码侧就是不带 scaling 的，
             解码侧才除以它。对称地"补上"会让条件整体弱 5.5 倍。
          3. `needs_upcasting` 时临时升 fp32、算完立刻**还原**：上游 `:514-528` 同逻辑。
             不还原会让后续解码在 fp32 下跑，与 stock 的 fp16 解码产生可见偏差。
        """
        import torch

        dec = self.bag.require("vae")
        force_upcast = bool(getattr(getattr(dec, "config", None), "force_upcast", False))
        needs_upcast = (getattr(dec, "dtype", None) == torch.float16) and force_upcast
        if needs_upcast:
            dec.to(dtype=torch.float32)
        try:
            latents = dec.encode(pixels).latent_dist.mode()
        finally:
            if needs_upcast:
                dec.to(dtype=torch.float16)

        # 逐帧共享同一张条件图（上游 `:250` 的 repeat 是给 num_videos_per_prompt 用的，
        # 这里 batch 恒为 1，帧维广播在 encode() 里做）
        if do_guidance:
            # ★ 无条件支 = 全零张量，顺序 (uncond, cond)
            latents = torch.cat([torch.zeros_like(latents), latents])
        return latents

    def _added_time_ids(self, fps: int, motion_bucket: int, noise_aug: float,
                        dtype: Any, do_guidance: bool, batch: int = 1) -> Any:
        """`[fps-1, motion_bucket_id, noise_aug_strength]`，**先 repeat 再 cat**。

        与 SDXL 的 `cat` 再 `repeat` 相反。写反了不会报错：
        SDXL 那条路 repeat(2,1) 恰好也出 2 行，只是内容成了 `[a,a]` 而不是 `[a,b]`。
        这里照抄上游 `:282-286`。
        """
        import torch

        ids = torch.tensor([[int(fps), int(motion_bucket), float(noise_aug)]], dtype=dtype)
        ids = ids.repeat(max(1, int(batch)), 1)
        if do_guidance:
            ids = torch.cat([ids, ids])
        return ids

    def _guidance_scale(self, req: GenRequest, frames: int, do_guidance: bool,
                        dtype: Any) -> Any:
        """逐帧引导强度：`linspace(min, max, frames)` → repeat(batch) → 末尾补维。

        上游 `:570-573`：`linspace(...).unsqueeze(0)` → `.to(device, latents.dtype)`
        → `.repeat(batch, 1)` → `_append_dims(x, latents.ndim)`。
        `_append_dims` 补在**末尾**，所以 final shape = `(B, frames, 1, 1, 1)`，
        正好能与 `(B, frames, C, h, w)` 的噪声预测广播。

        `do_guidance=False`（蒸馏权重 min=max=1.0）时仍然返回这个张量：
        下游 `guide()` 按 `state.do_guidance` 决定用不用，判据只有一处。
        """
        import torch

        lo = float(req.cfg_min or 0.0) or _DEFAULT_CFG_MIN
        hi = float(req.cfg or 0.0) or _DEFAULT_CFG_MAX
        if hi < lo:
            # linspace(3, 1, n) 在 torch 上是合法的（递减），但上游从没这么用过；
            # 出现这种入参几乎一定是调用方把 min/max 传反了 —— 修好并留痕。
            self.notes.append(
                "cfg(%s) < cfg_min(%s)：min/max 疑似传反，已按 (min, max) 语义交换" % (hi, lo))
            lo, hi = hi, lo
        g = torch.linspace(lo, hi, int(frames)).unsqueeze(0)
        g = g.to(self._device(), dtype)
        g = g.repeat(max(1, int(req.batch)), 1)
        target_ndim = 5                      # (B, frames, C, h, w)
        while g.ndim < target_ndim:
            g = g.unsqueeze(-1)
        return g

    @staticmethod
    def _randn(shape: Any, generator: Any, device: Any, dtype: Any) -> Any:
        """与上游同一个 `randn_tensor`（同 seed 比特一致的前提）。"""
        try:
            from diffusers.utils.torch_utils import randn_tensor

            return randn_tensor(shape, generator=generator, device=device, dtype=dtype)
        except Exception:  # stability-gate: allow-swallow（上游工具缺失时走等价退路并记 warning）
            logger.warning("[kernel.svd] 上游 randn_tensor 不可用，改用 CPU 生成后搬迁")

        import torch

        kwargs = {} if generator is None else {"generator": generator}
        return torch.randn(tuple(shape), dtype=dtype, device="cpu", **kwargs).to(device)

    # ══════════════════════════════════════════════════════════════
    # 时间轴 / 每步 / 推进 / 解码
    # ══════════════════════════════════════════════════════════════
    def make_timesteps(self, req: GenRequest, cond: Any, scheduler: Any = None,
                       steps: Optional[int] = None) -> Tuple[Any, int]:
        """SVD **没有 strength 语义**，时间轴恒定跑满。

        为什么必须覆盖基类：`req.is_i2i()` 在视频族恒为 True（i2v 必然带 image_path），
        基类会按 `strength` 截尾。若调用方顺手传了 `strength=0.5`，
        `int(25*0.5)=12` 步被悄悄砍掉一半 —— 出片是全噪，回执里却写着 steps=12。
        与控制"与原图关系"的旋钮是 `noise_aug_strength`，不是 strength。
        """
        sch = scheduler or self._scheduler()
        n = int(steps) if steps else int(req.steps or _DEFAULT_STEPS)
        return SCHED.build_timesteps(sch, n, device=self._device(), strength=1.0)

    def prepare_step(self, latents: Any, t: Any, state: Any) -> PreparedStep:
        """三步定序：**先**拼 CFG batch → **再** scale → **最后**拼图像条件。

        顺序来自上游 `:583-587`。把 `scale_model_input` 放到拼条件之后也能跑通
        （Euler 的 scale 是逐元素除法，通道多 4 个不影响），但 `scheduler` 内部的
        `is_scale_input_called` 标记与 sigma 索引是按"整批输入"计数的，
        顺序一变，某些调度族（LCM/DPMSolver）会开始慢慢糊。
        """
        import torch

        from app.core.neural.kernel import cfg as CFG

        mult = self.caps.cfg_batch_multiplier if state.do_guidance else 1
        model_input = CFG.expand_for_guidance(latents, mult)

        sch = self._scheduler()
        if sch is not None and hasattr(sch, "scale_model_input"):
            model_input = sch.scale_model_input(model_input, t)

        cond = state.ctx or {}
        image_latents = cond.get("image_latents")
        if image_latents is None:
            raise RuntimeError("SVD 条件缺失 image_latents（encode 未执行或已失败）")
        model_input = torch.cat([model_input, image_latents], dim=2)
        return PreparedStep(model_input=model_input, timestep=t, raw=latents)

    def _net_kwargs(self, state: Any, prepared: Any) -> Dict[str, Any]:
        cond = state.ctx or {}
        return {
            "encoder_hidden_states": cond.get("image_embeds"),
            "added_time_ids": cond.get("added_time_ids"),
        }

    def guide(self, noise: Any, prepared: Any, state: Any) -> Any:
        """`uncond + g * (cond - uncond)`，其中 `g` 是**逐帧**张量。

        为什么不能复用基类 `CFG.combine`：它内部 `float(scale)`，
        拿到 `(B,frames,1,1,1)` 张量会直接 TypeError；而"退化成标量"能跑通，
        只是首帧与末帧引导相同 ⇒ 运动幅度塌陷成静止画面。
        """
        if not state.do_guidance:
            return noise
        cond = state.ctx or {}
        g = cond.get("guidance")
        if g is None:
            raise RuntimeError("SVD 引导强度缺失（encode 未产出 guidance）")
        uncond, text = noise.chunk(2)
        return uncond + g * (text - uncond)

    def step_extra_kwargs(self, generator: Any = None) -> Dict[str, Any]:
        """**什么都不传** —— 与上游 `:604` 的 `scheduler.step(noise_pred, t, latents)` 一致。

        Euler 的 `step` 签名里确实有 `generator`，但 `s_churn=0` 时
        `gamma == 0`、那段 `randn_tensor` 根本不会执行（见
        `scheduling_euler_discrete.py:754-760`）。传了结果一样，
        但"结果一样"不该靠运气，靠的是与上游一致的调用形态。
        """
        return {}

    def step(self, noise: Any, t: Any, prepared: PreparedStep, state: Any) -> Any:
        """`.prev_sample`，不是 `return_dict=False` + `[0]`。

        两种写法数值完全一样，区别只在**调用形态**：上游是
        `latents = self.scheduler.step(noise_pred, t, latents).prev_sample`（`:604`）。
        本类刻意连这一点也对齐 —— 这样"与上游一致"是字面成立的，
        而不是"我认为等价"。基类给图像族用的是 `return_dict=False`（那是它们上游的写法）。
        """
        sch = self.bag.require("scheduler")
        return sch.step(noise, t, prepared.raw).prev_sample

    def decode(self, latents: Any, state: Any = None) -> Any:
        """分块时间解码 → `list[PIL.Image]`。

        上游 `:290-317` 五步：`flatten(0,1)` → `/scaling_factor` → 分块 `vae.decode`
        → `reshape(-1, frames, ...)` + `permute(0,2,1,3,4)` → `float()`。
        **顺序不能换**：先 `permute` 再 `reshape` 会把帧维和通道维搅在一起，
        出来是一堆错位的静帧（能播、能存、就是内容不对）。
        """
        import torch

        num_frames = int(latents.shape[1])
        chunk = int(getattr(state, "decode_chunk", 0) or 0) or num_frames
        chunk = max(1, min(chunk, num_frames))

        dec = self.bag.require("vae")
        flat = latents.flatten(0, 1)
        flat = flat / float(getattr(dec.config, "scaling_factor", 0.18215))

        accepts_num_frames = self._vae_accepts_num_frames(dec)
        outs = []
        for i in range(0, flat.shape[0], chunk):
            part = flat[i:i + chunk]
            kwargs = {"num_frames": int(part.shape[0])} if accepts_num_frames else {}
            outs.append(dec.decode(part, **kwargs).sample)
        frames = torch.cat(outs, dim=0)

        frames = frames.reshape(-1, num_frames, *frames.shape[1:]).permute(0, 2, 1, 3, 4)
        frames = frames.float()

        proc = self.bag.get("video_processor")
        if proc is None and self.pipe is not None:
            proc = getattr(self.pipe, "video_processor", None)
        if proc is not None:
            # postprocess_video 做 `(x/2+0.5).clamp(0,1)` → PIL，且返回 `[batch][frames]`
            return proc.postprocess_video(video=frames, output_type="pil")[0]

        from PIL import Image as _Image

        self.notes.append("缺少 video_processor ⇒ 用手写后处理（与上游数值等价，但少了它的 resize 语义）")
        arr = (frames / 2 + 0.5).clamp(0, 1)
        arr = (arr.permute(0, 2, 1, 3, 4) * 255).round().to(torch.uint8).cpu().numpy()
        return [_Image.fromarray(px.transpose(1, 2, 0)) for px in arr[0]]

    @staticmethod
    def _vae_accepts_num_frames(dec: Any) -> bool:
        """上游 `:296-297`：只在 VAE 的 `forward` 真声明了 `num_frames` 时才传。

        无条件传会在 IMAGE_ONLY 的 VAE 上炸 `unexpected keyword argument`；
        无条件不传则时序 VAE 会按"单帧"解码 —— 后者更糟：不报错，出片逐帧闪烁。
        """
        try:
            from diffusers.utils.torch_utils import is_compiled_module

            fn = dec._orig_mod.forward if is_compiled_module(dec) else dec.forward
            return "num_frames" in set(inspect.signature(fn).parameters.keys())
        except Exception:  # stability-gate: allow-swallow（探测失败按"不声明"处理，退化为逐帧解码）
            logger.debug("[kernel.svd] 无法探测 vae.forward 是否接受 num_frames", exc_info=True)
            return False

    # ── 缓存键 ────────────────────────────────────────────────────
    def cache_key(self, req: GenRequest) -> tuple:
        """视频族的条件由"输入图 + 四个时间/运动标量"决定，缺一个就串片。"""
        import hashlib
        import os

        path = str(req.image_path or "")
        try:
            stamp = int(os.path.getmtime(path)) if path and os.path.isfile(path) else 0
        except OSError:
            stamp = 0
        return (
            "svd",
            hashlib.sha1(path.encode("utf-8", "ignore")).hexdigest()[:12] if path else "",
            stamp,
            int(req.frames or 0), int(req.fps or 0),
            int(req.motion_bucket_id or 0), float(req.noise_aug_strength or 0.0),
            float(req.cfg_min or 0.0), float(req.cfg or 0.0),
            int(req.width or 0), int(req.height or 0), int(req.batch),
        )
