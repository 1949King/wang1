# -*- coding: utf-8 -*-
"""GGUF 懒反量化层 —— 真正「省显存」的那条路（2026-11-01）

为什么要有这个文件
==================
``gguf_loader.apply_to_unet()`` 是 **eager** 模式：一次性把 GGUF 反量化成 fp16 装进 UNet。
它省的是**硬盘和下载量**（SD1.5 UNet 1.72GB → 0.91GB），**显存一点没省**——
因为装完手里还是一份 fp16 权重。

本文件实现 **lazy** 模式：权重以**量化字节**持有，forward 时才在 GPU 上还原成 fp16，
用完即弃（PyTorch caching allocator 会复用同一块）。这样常驻显存 = 量化字节大小。

    SD1.5 UNet：fp16 1.72GB → Q8_0 常驻 0.91GB（-47%）
    SDXL  UNet：fp16 4.78GB → Q8_0 常驻 2.54GB / Q4_K 常驻 1.34GB（-47% / -72%）

三条纪律
========
1. **映射靠反推，不靠猜**。``build_layer_map()`` 的做法是：先 eager 装填（值已知正确），
   再用「数值完全相等」在 UNet 里定位每个模块对应的 GGUF 张量。全程走官方
   ``convert_ldm_unet_checkpoint`` 的结果，不自己写 LDM→diffusers 名字表。
2. **量化字节绝不能注册成 parameter/buffer**。否则 ``pipe.to("cuda")`` 和 accelerate 的
   offload hook 会把它一起搬走，省显存的目的直接落空。这里用普通 Python 属性持有。
3. **测不出就如实报告**。未匹配上的层保持原 fp16 权重（不静默变成空壳），
   并在报告里列出来。

代价（实测见 ``.workbuddy/tmp/bench_lazy.py``）
=============================================
每层每次 forward 都要反量化一次，Q8_0 约 0.24ms/层。686 层 ⇒ 约 +0.16s/步。
这是拿时间换显存，不是免费提速。**如果显存本来就够，别开这个模式。**
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from app.core.neural import gguf_loader as L
from app.core.neural import gguf_quants_torch as G

logger = logging.getLogger("AI短剧编辑器.core.neural.gguf_lazy")

__all__ = ["build_layer_map", "apply_to_unet_lazy", "GGUFLinear", "GGUFConv2d",
           "estimate_saving"]


def _dequant_weight(blocks: torch.Tensor, qtype: str, ggml_shape: Tuple[int, ...],
                    dtype: torch.dtype) -> torch.Tensor:
    """量化字节 (n_blocks, block_bytes) → torch 序的权重张量（在 blocks 所在设备上算）。"""
    flat = G.dequantize(blocks, qtype, dtype=dtype)
    t = flat.reshape(ggml_shape)
    if len(ggml_shape) > 1:
        t = t.permute(tuple(range(len(ggml_shape) - 1, -1, -1)))
    return t.contiguous()


class _GGUFBase(nn.Module):
    """懒反量化基类：持有量化字节 + 形状，forward 时还原。"""

    def __init__(self, blocks: torch.Tensor, qtype: str, ggml_shape: Tuple[int, ...],
                 bias: Optional[torch.Tensor], dtype: torch.dtype):
        super().__init__()
        # ★ 普通属性，不是 buffer/parameter ⇒ .to() / offload hook 都不会搬它
        self._blocks = blocks
        self._qtype = str(qtype)
        self._ggml_shape = tuple(int(d) for d in ggml_shape)
        self._wb_dtype = dtype
        if bias is not None:
            self.bias = nn.Parameter(bias.detach().clone(), requires_grad=False)
        else:
            self.register_parameter("bias", None)
        # 1 元素探针：跟随 .to() 移动，用来读「这层该在哪个设备上算」
        self.register_buffer("_dev_probe", torch.zeros(1, dtype=dtype), persistent=False)

    @property
    def weight_bytes(self) -> int:
        return int(self._blocks.numel())

    def _weight(self, device: Optional[torch.device] = None) -> torch.Tensor:
        """还原权重。

        ★ 设备优先级：调用方传入的 ``device``（= 输入的 device）> 探针 buffer 的 device。
          必须支持前者 —— 否则「模块在 CPU、输入在 GPU」时会直接把反量化结果喂给
          F.linear 导致设备不一致报错（2026-11-01 踩过）。
        """
        dev = device if device is not None else self._dev_probe.device
        blocks = self._blocks
        if blocks.device != dev:
            blocks = blocks.to(dev, non_blocking=True)
        return _dequant_weight(blocks, self._qtype, self._ggml_shape, self._wb_dtype)

    def extra_repr(self) -> str:
        return "qtype=%s, 量化字节=%.2fMB" % (self._qtype, self._blocks.numel() / 1e6)


class GGUFLinear(_GGUFBase):
    """替换 nn.Linear。"""

    def __init__(self, blocks, qtype, ggml_shape, in_features: int, out_features: int,
                 bias, dtype):
        super().__init__(blocks, qtype, ggml_shape, bias, dtype)
        self.in_features = int(in_features)
        self.out_features = int(out_features)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        w = self._weight(x.device).to(device=x.device, dtype=x.dtype)
        return F.linear(x, w, self.bias)

    def extra_repr(self) -> str:
        return "in=%d, out=%d, %s" % (self.in_features, self.out_features,
                                      super().extra_repr())


class GGUFConv2d(_GGUFBase):
    """替换 nn.Conv2d。"""

    def __init__(self, blocks, qtype, ggml_shape, in_channels: int, out_channels: int,
                 kernel_size, bias, dtype, stride=(1, 1), padding=(0, 0),
                 dilation=(1, 1), groups: int = 1):
        super().__init__(blocks, qtype, ggml_shape, bias, dtype)
        self.in_channels = int(in_channels)
        self.out_channels = int(out_channels)
        self.kernel_size = kernel_size
        self.stride = stride
        self.padding = padding
        self.dilation = dilation
        self.groups = int(groups)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        w = self._weight(x.device).to(device=x.device, dtype=x.dtype)
        return F.conv2d(x, w, self.bias, self.stride, self.padding, self.dilation,
                        self.groups)

    def extra_repr(self) -> str:
        return "in=%d, out=%d, k=%s, stride=%s, %s" % (
            self.in_channels, self.out_channels, self.kernel_size, self.stride,
            super().extra_repr())


# ── 映射反推 ─────────────────────────────────────────────────────────
def _replaceable(unet: nn.Module) -> Dict[str, nn.Module]:
    """所有可被替换的层（带 weight 的 Linear / Conv2d）。"""
    out: Dict[str, nn.Module] = {}
    for name, mod in unet.named_modules():
        if isinstance(mod, (nn.Linear, nn.Conv2d)) and getattr(mod, "weight", None) is not None:
            out[name] = mod
    return out


def build_layer_map(unet: nn.Module, idx: "L.GGUFIndex", *, dtype: torch.dtype,
                    on_progress=None) -> Tuple[Dict[str, str], List[str]]:
    """反推「UNet 模块名 → GGUF 张量名」映射。

    做法：把每个 GGUF 张量反量化一次，在**同形状**的 UNet 层里找**数值完全相等**的那个。
    这能成立的前提是 unet 的权重已经是「从该 GGUF 装填过」的值（先跑 eager）。
    好处：全程只用 diffusers 官方转换链路，不维护任何手写命名表。

    返回 ``(mapping, unmatched_module_names)``。
    """
    modules = _replaceable(unet)
    by_shape: Dict[Tuple[int, ...], List[str]] = {}
    for name, mod in modules.items():
        by_shape.setdefault(tuple(mod.weight.shape), []).append(name)

    mapping: Dict[str, str] = {}
    used: set = set()
    names = idx.names()
    for i, gname in enumerate(names, 1):
        info = idx.tensor(gname)
        cands = by_shape.get(tuple(info.shape))
        if cands:
            w = L.dequantize_tensor(idx, gname, device="cpu", dtype=dtype)
            for nm in cands:
                if nm in used:
                    continue
                # ★ 必须显式搬设备：unet 可能在 cuda（整卡模式），而 w 在 cpu。
                #   2026-11-01 实测踩过：torch.equal 跨设备直接 RuntimeError。
                cur = modules[nm].weight.detach().to(device=w.device, dtype=w.dtype)
                if torch.equal(cur, w):
                    mapping[nm] = gname
                    used.add(nm)
                    break
            del w
        if on_progress and (i % 64 == 0 or i == len(names)):
            on_progress(i, len(names))
    unmatched = sorted(set(modules) - used)
    return mapping, unmatched


def _resolve_parent(root: nn.Module, dotted: str) -> Tuple[nn.Module, str]:
    parts = dotted.split(".")
    obj = root
    for p in parts[:-1]:
        obj = getattr(obj, p)
    return obj, parts[-1]


def apply_to_unet_lazy(unet: nn.Module, gguf_path: str, *, dtype=None,
                       on_progress=None) -> Dict[str, Any]:
    """把 UNet 的 Linear/Conv2d 换成懒反量化层，权重常驻显存降到量化字节大小。

    流程：① 先 eager 装填（保证值正确、可被数值匹配）→ ② 反推映射 → ③ 逐层替换。

    ⚠️ 返回的 ``missing`` 是**未替换成懒层**的模块名 —— 它们仍是正确的 fp16 权重，
    只是不省显存。不静默、不假装全替换。
    """
    if not L.available():
        return {"ok": False, "message": L.unavailable_reason()}
    dt = dtype or getattr(unet, "dtype", torch.float16)

    # ① eager 装填
    rep = L.apply_to_unet(unet, gguf_path, dtype=dt)
    if not rep.get("ok"):
        return rep
    eager_msg = rep.get("message", "")

    # ② 反推映射
    idx = L.read_index(gguf_path)
    try:
        mapping, unmatched = build_layer_map(
            unet, idx, dtype=dt,
            on_progress=(lambda i, n: on_progress("map", i, n)) if on_progress else None)
        if not mapping:
            return {"ok": False,
                    "message": "映射反推失败：没有任何 UNet 层与 GGUF 张量数值相等"
                               "（先确认 eager 装填成功、dtype 一致）",
                    "eager": eager_msg}

        # ③ 替换
        modules = _replaceable(unet)
        swapped = 0
        saved_bytes = 0
        for nm, gname in mapping.items():
            mod = modules[nm]
            info = idx.tensor(gname)
            blocks = torch.from_numpy(_copy_blocks(idx, gname))   # CPU uint8，独立内存
            bias = mod.bias.detach().clone() if mod.bias is not None else None
            fp16_bytes = int(mod.weight.numel() * (2 if dt == torch.float16 else 4))
            if isinstance(mod, nn.Linear):
                new: nn.Module = GGUFLinear(blocks, info.qtype, info.ggml_shape,
                                            mod.in_features, mod.out_features, bias, dt)
            else:
                new = GGUFConv2d(blocks, info.qtype, info.ggml_shape,
                                 mod.in_channels, mod.out_channels, mod.kernel_size,
                                 bias, dt, mod.stride, mod.padding, mod.dilation,
                                 mod.groups)
            parent, child = _resolve_parent(unet, nm)
            setattr(parent, child, new)
            swapped += 1
            saved_bytes += fp16_bytes - int(blocks.numel())
            del mod
    finally:
        idx.close()

    total_fp16 = sum(int(m.weight.numel()) * (2 if dt == torch.float16 else 4)
                     for m in _replaceable(unet).values()
                     if not isinstance(m, _GGUFBase))
    report = {
        "ok": True,
        "message": "已转为懒反量化：%d 层（%s），每步按需还原"
                   % (swapped, "Q8_0/Q4_K 等" if swapped else "-"),
        "swapped": swapped,
        "weights_saved_mb": round(saved_bytes / 1e6, 1),
        "still_fp16_mb": round(total_fp16 / 1e6, 1),
        "missing": unmatched[:20],
        "missing_n": len(unmatched),
        "eager": eager_msg,
    }
    logger.info("[gguf_lazy] %s（省 %.1fMB 权重）", report["message"], report["weights_saved_mb"])
    return report


def _copy_blocks(idx: "L.GGUFIndex", name: str):
    """取一份**可写、独立**的字节副本（避免持有 memmap，关掉 reader 后仍可用）。"""
    import numpy as np

    return np.array(idx.raw(name), copy=True)


def estimate_saving(gguf_path: str, *, dtype_bytes: int = 2) -> Dict[str, Any]:
    """不加载模型，估算懒模式下省多少显存。"""
    try:
        idx = L.read_index(gguf_path)
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    try:
        quant_bytes = sum(int(i.n_bytes) for i in idx.tensors.values())
        elems = 0
        for i in idx.tensors.values():
            n = 1
            for d in i.shape:
                n *= d
            elems += n
    finally:
        idx.close()
    fp_bytes = elems * dtype_bytes
    return {
        "ok": True,
        "quant_gb": round(quant_bytes / 1e9, 2),
        "fp_gb": round(fp_bytes / 1e9, 2),
        "saved_gb": round((fp_bytes - quant_bytes) / 1e9, 2),
        "saved_pct": round(100.0 * (1 - quant_bytes / max(fp_bytes, 1)), 1),
    }
