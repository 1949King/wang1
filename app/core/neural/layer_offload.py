# -*- coding: utf-8 -*-
"""block 组级 CPU 卸载（layer_cpu_offload 的**执行端**） —— 一个月路线图刀2（2026-10-03）

定位
====
`memory_policy` 只做决策（「该用哪档」），本模块只做执行（「怎么装」）。
layer_cpu_offload 的粒度介于两档既有模式之间：

  - ``model_offload``      整组件换入换出（UNet 整体 5.2GB 在卡 + 激活）
  - ``layer_cpu_offload``  **本模块**：block 组挂 forward hook，块算完立刻回 CPU
  - ``sequential_offload`` 逐叶子模块（最省显存，搬运开销最大）

为什么 SDXL 需要它
==================
SDXL fp16 权重 ≈7.0GB（UNet 5.2 + TE-G 1.4 + TE-L 0.24 + VAE 0.16）。
model_offload 峰值 ≈ 最大组件 UNet 5.2GB + 1024² 激活 ~2.5GB ≈ 7.7GB，
贴脸 8GB 卡（95% 水位线 7.6GB）。layer 档把 UNet 拆成 block 组：
峰值 ≈ 常驻小件 + 最大单块（~1GB）+ 激活 ≈ 4.5~5.5GB —— 显著低于 model 档。
代价是搬运：每步去噪要把全部 block 换入一遍（SDXL ≈5.2GB/步，
PCIe ~15GB/s ⇒ 每步 +0.3~0.5s，20 步 ≈ +7~10s）—— 刀2-4 四档实测校准。

三条实现纪律
============
1. **先 ``pipe.to(device)`` 整上卡，再把挂 hook 的块移回 CPU**。
   这样 ``pipe.device == cuda``，pipeline 中间张量全在卡上，hook 块收到的
   输入设备一致。不整上卡的话 pipe.device=cpu，prompt_embeds/latents 全线错配。
2. **hook 必须挂在「forward 真的会被调用」的模块上**：
   - UNet.forward 逐个调 ``down_blocks[i] / mid_block / up_blocks[i]`` ✅
   - pipeline 直接调 ``text_encoder(...)``（CLIP forward）✅
   - ⚠️ ``vae.decode()/encode()`` **不走 vae.forward**（是普通方法）
     ⇒ hook 要挂在 ``vae.decoder / vae.encoder`` 上，**不是 vae 本体**；
     quant_conv / post_quant_conv 仅 MB 级，常驻 GPU 不挂。
3. **绝不与 accelerate offload 叠加**：本函数与 ``enable_model_cpu_offload`` /
   ``enable_sequential_cpu_offload`` 互斥（由引擎 load() 的分支结构保证）。

参考：DiffSynth ``AutoWrappedModule`` 的换入换出思路，但只实现推理必需的最小面 ——
不引入包装类，直接用 PyTorch 原生 forward hook（阻塞式搬运；pinned memory /
流式预取是后续优化项，先保证正确）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_CPU = "cpu"


def _swap_hooks(device: str):
    """生成一对「换入 / 换出」hook。阻塞式 .to()：先正确，后优化。"""
    def _pre(mod, _args):                  # forward_pre_hook：块要算了 ⇒ 换上卡
        mod.to(device)

    def _post(mod, _args, _output):        # forward hook：块算完 ⇒ 立刻回 CPU
        mod.to(_CPU)

    return _pre, _post


def apply_layer_cpu_offload(pipe, device: str = "cuda") -> Dict[str, Any]:
    """给 diffusers pipeline 装 block 组级 CPU 卸载。返回挂接报告（决策可见性同 R9）。

    对 SD1.5 / SDXL 均适用（SD1.5 无 text_encoder_2，getattr 跳过）。
    挂接清单：
      - ``unet.down_blocks[i]`` / ``unet.mid_block`` / ``unet.up_blocks[i]``
      - ``text_encoder`` / ``text_encoder_2``（整体；encode 只跑一次）
      - ``vae.decoder`` / ``vae.encoder``（⚠️ 不是 vae 本体，见纪律 2）
    常驻 GPU：UNet 小件（conv_in/out、time_embed、norm）、quant 卷积、scheduler。
    """
    import torch  # 函数内重依赖（顶层零重依赖纪律，同 memory_policy）
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用，layer_cpu_offload 无意义")

    hooked: List[str] = []
    handles: List[Any] = []

    def _hook(module, name: str) -> None:
        pre, post = _swap_hooks(device)
        handles.append(module.register_forward_pre_hook(pre))
        handles.append(module.register_forward_hook(post))
        module.to(_CPU)      # 初始态 = 已卸载（首次 forward 时 pre-hook 换入）
        hooked.append(name)

    # ① 整上卡（纪律 1）：pipe.device ⇒ cuda，中间张量设备一致
    pipe.to(device)

    # ② UNet：逐 block 挂 hook（UNet.forward 会逐个调用它们）
    unet = getattr(pipe, "unet", None)
    if unet is not None:
        for i, blk in enumerate(getattr(unet, "down_blocks", None) or []):
            _hook(blk, f"unet.down_blocks[{i}]")
        if getattr(unet, "mid_block", None) is not None:
            _hook(unet.mid_block, "unet.mid_block")
        for i, blk in enumerate(getattr(unet, "up_blocks", None) or []):
            _hook(blk, f"unet.up_blocks[{i}]")
    else:
        logger.warning("[layer_offload] pipe 无 unet 属性，只挂了文本/VAE 侧")

    # ③ 文本编码器：整体挂（pipeline 直接调其 forward；SDXL 的 TE-G 1.4GB 必须挂）
    for name in ("text_encoder", "text_encoder_2"):
        comp = getattr(pipe, name, None)
        if comp is not None:
            _hook(comp, name)

    # ④ VAE：decode/encode 不触发 vae.forward ⇒ 挂 decoder/encoder 本体（纪律 2）
    vae = getattr(pipe, "vae", None)
    if vae is not None:
        if getattr(vae, "decoder", None) is not None:
            _hook(vae.decoder, "vae.decoder")
        if getattr(vae, "encoder", None) is not None:
            _hook(vae.encoder, "vae.encoder")

    # 标记：引擎/排查时可确认本管道走的是 layer 档而非 accelerate offload
    pipe._shiguang_layer_cpu_offload = True
    report = {"hooked": hooked, "n_modules": len(hooked), "device": device}
    logger.info("[layer_offload] 已挂 %d 个 block 组: %s", len(hooked), ", ".join(hooked))
    return report
