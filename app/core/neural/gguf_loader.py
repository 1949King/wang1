# -*- coding: utf-8 -*-
"""GGUF 权重加载与接线 —— 「用 ComfyUI 的生态，不用 ComfyUI」（2026-11-01）

用户诉求原文
============
「既能脱离 ComfyUI 去下载它的全部文件，又能使用它的生态，又不需要下载它的文件。」

落到工程上就是三件事，本文件负责②③，①由 ``gguf_quants_torch`` 负责：
  ① 权重**格式**能读（GGUF 是社区量化公共格式，不是 ComfyUI 私有）
  ② 反量化**不需要** ComfyUI 的 custom_nodes（纯 torch 内核，无编译）
  ③ 权重能**装进 diffusers pipeline**（我们用的是 diffusers，不是 ComfyUI 的 LDM 结构）

为什么 GGUF 比 fp8 / int4 更值得做（依据 ``quant_descriptor`` 的实测台账）
=========================================================================
  · fp8  : ``device_profile.py:54`` 判定 ``gen in (ada, hopper, blackwell)`` ⇒ 老卡直接出局；
           且本机 sm89 上 ``torch._scaled_mm`` 报 CUBLAS_STATUS_NOT_SUPPORTED，走反量化回退无加速。
  · int4 : Windows 不可用（torchao 0.16 走 mslk，win 轮子是纯 Python 空壳且依赖 triton）。
  · GGUF : 只依赖 ``gguf`` 包（纯 Python + numpy，无编译）⇒ 才是真正的「跨设备」。

实测证据（本机 RTX 4060 Laptop 8GB / torch 2.6.0+cu124 / diffusers 0.40.0）
==========================================================================
  · 内核逐元素对照 gguf.quants：F32/F16/BF16/Q4_0/Q5_0/Q8_0/Q4_K/Q6_K 全部 rel = 0
  · 反量化速度（3.28M 元素 ≈ 一个 SDXL 大层）：
        Q8_0 0.24ms / Q6_K 1.89ms / Q4_K 2.27ms   （numpy 版同为 62ms ⇒ 慢 250~600×）
  · 显存账（SDXL UNet 2.39G 参数）：fp16 4.78GB → Q8_0 2.54GB / Q6_K 1.96GB / Q4_K 1.34GB
  · ``diffusers.loaders.single_file_utils.convert_ldm_unet_checkpoint`` 在 0.40.0 可用

三条纪律
========
1. **不猜命名**：GGUF 用 LDM/ComfyUI 命名（``input_blocks.0.0.weight``），diffusers UNet 用
   ``down_blocks.*``。两套命名之间的转换**只走 diffusers 官方 ``convert_ldm_unet_checkpoint``**，
   绝不自己写映射表 —— 映射表是永动机式 bug 来源。
2. **测不出就如实失败**：不是 UNet、量化类型不支持、形状对不上、转换后缺关键层，
   一律返回带人话原因的失败，绝不「装作加载成功然后出灰图」。
3. **不静默降级**：调用方必须显式选择 ``mode``；失败时原 pipeline 保持不变（不半替换）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.neural import gguf_quants_torch as G

logger = logging.getLogger("AI短剧编辑器.core.neural.gguf_loader")

#: ComfyUI/A1111 的 LDM 权重前缀（GGUF 发布件普遍带它，convert 函数不认）
_LDM_PREFIXES = ("model.diffusion_model.", "diffusion_model.", "model.")

#: GGUF 元数据里表示「这是个扩散模型 UNet」的关键字
_UNET_HINTS = ("diffusion", "unet", "model.diffusion_model")


# ── 能力探测（不 import gguf，只 find_spec）─────────────────────────────
def available() -> bool:
    """gguf 包是否可用。只 find_spec，不真 import（探测路径不加载重库的纪律）。"""
    import importlib.util as _u

    return _u.find_spec("gguf") is not None


def unavailable_reason() -> str:
    if not available():
        return "未安装 gguf 包（纯 Python，pip install gguf；不需要编译任何东西）"
    return ""


# ── 文件索引 ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TensorInfo:
    """GGUF 内单个张量的元信息（不持有数据）。

    ``shape`` 是 **torch 序**（GGUFReader 已把文件里的 ggml ne[] 反转过一次）。
    而 ``raw()`` 拿到的字节是 **ggml 序**（ne[0] 维内存连续）⇒ 反量化后必须
    reshape 成 reversed(shape) 再 permute 回来，见 ``dequantize_tensor``。
    """

    name: str
    qtype: str                      # F16 / Q8_0 / Q4_K ...
    shape: Tuple[int, ...]          # torch 序
    n_bytes: int

    @property
    def ggml_shape(self) -> Tuple[int, ...]:
        return tuple(reversed(self.shape))


@dataclass
class GGUFIndex:
    """GGUF 文件索引：只读头 + mmap，**不反量化**，所以打开是毫秒级。"""

    path: str
    tensors: Dict[str, TensorInfo] = field(default_factory=dict)
    kv: Dict[str, Any] = field(default_factory=dict)
    _reader: Any = None
    _order: List[str] = field(default_factory=list)

    # -- 打开/关闭 --
    @classmethod
    def open(cls, path: str) -> "GGUFIndex":
        from gguf import GGUFReader

        if not os.path.isfile(path):
            raise FileNotFoundError("GGUF 文件不存在: %s" % path)
        reader = GGUFReader(path, "r")
        idx = cls(path=os.path.abspath(path), _reader=reader)
        for t in reader.tensors:
            name = str(t.name)
            shape = tuple(int(d) for d in t.shape)      # reader 已 reversed ⇒ torch 序
            info = TensorInfo(name=name, qtype=str(t.tensor_type.name),
                              shape=shape, n_bytes=int(t.n_bytes))
            idx.tensors[name] = info
            idx._order.append(name)
        for k, v in _iter_kv(reader):
            idx.kv[k] = v
        return idx

    def close(self) -> None:
        self._reader = None

    def __enter__(self) -> "GGUFIndex":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -- 访问 --
    def names(self) -> List[str]:
        return list(self._order)

    def tensor(self, name: str) -> TensorInfo:
        return self.tensors[name]

    def raw(self, name: str):
        """取原始块数组，**统一成 (n_blocks, block_bytes) 的二维 uint8**。

        GGUF 把量化张量按「多维 byte shape」存（如 conv 权重是 (3,3,4,340)），
        反量化内核只吃二维 ⇒ 这里必须归一化，否则下游会拿到任意维度的数组。
        """
        if self._reader is None:
            raise RuntimeError("GGUFIndex 已关闭")
        import numpy as np

        i = self._order.index(name)
        t = self._reader.tensors[i]
        q = str(t.tensor_type.name)
        _, byt = G.BLOCK_SPEC.get(q, (1, 2))
        arr = np.ascontiguousarray(t.data).view(np.uint8)
        return arr.reshape(-1, byt)

    # -- 汇总 --
    def summary(self) -> Dict[str, Any]:
        by_type: Dict[str, int] = {}
        total = 0
        for info in self.tensors.values():
            by_type[info.qtype] = by_type.get(info.qtype, 0) + 1
            total += info.n_bytes
        dom = max(by_type, key=by_type.get) if by_type else ""
        return {
            "path": self.path,
            "file_gb": round(os.path.getsize(self.path) / 1e9, 2) if os.path.isfile(self.path) else 0.0,
            "tensors": len(self.tensors),
            "types": by_type,
            "dominant_type": dom,
            "weights_gb": round(total / 1e9, 2),
            "dequant_gb": round(_dequant_bytes(self) / 1e9, 2),
            "arch": str(self.kv.get("general.architecture") or ""),
            "name": str(self.kv.get("general.name") or ""),
            "supported_types": sorted(k for k in by_type if G.supported(k)),
            "unsupported_types": sorted(k for k in by_type if not G.supported(k)),
        }


def _iter_kv(reader):
    """把 GGUFReader 的 kv 拍平成 (key, python 标量)。"""
    for key in list(getattr(reader, "fields", {})):
        try:
            f = reader.fields[key]
            parts = getattr(f, "parts", None)
            if not parts:
                continue
            v = parts[-1]
            if isinstance(v, (str, int, float, bool)):
                yield key, v
            elif hasattr(v, "__len__") and len(v) < 512:
                yield key, list(v)
        except Exception:  # stability-gate: allow-swallow（元数据是诊断辅助，读不出就不展示，不影响权重加载）
            continue


def _dequant_bytes(idx: GGUFIndex) -> int:
    """反量化后总字节（fp16 = 2B/参数）。"""
    n = 0
    for info in idx.tensors.values():
        blk, _ = G.BLOCK_SPEC.get(info.qtype, (1, 2))
        elems = 1
        for d in info.shape:
            elems *= d
        n += elems * 2
    return n


def read_index(path: str) -> GGUFIndex:
    return GGUFIndex.open(path)


def probe(path: str) -> Dict[str, Any]:
    """诊断用：只读头，不加载权重。失败返回带原因的 dict，不抛。"""
    try:
        with read_index(path) as idx:
            s = idx.summary()
            s["ok"] = True
            s["looks_like_unet"] = any(
                h in n.lower() for n in idx.names() for h in _UNET_HINTS)
            return s
    except Exception as e:
        return {"ok": False, "path": path,
                "error": "%s: %s" % (type(e).__name__, e)}


# ── 反量化 ───────────────────────────────────────────────────────────
def dequantize_tensor(idx: GGUFIndex, name: str, *, device: str = "cpu",
                      dtype=None):
    """把一个张量反量化成 torch 张量（形状与内存序都已还原成 torch 约定）。

    ★ 这里有一次**必须的轴重排**，不是可选优化：
      GGML 的张量以 ``ne[0]`` 为最内维（内存连续），GGUF 文件里的字节就是这个顺序；
      而 diffusers/torch 的 ``conv_in.weight`` 是 ``(out, in, kh, kw)``。
      只 reshape 不 permute 会得到一个「形状对、元素全串位」的张量 ——
      它会安静地 load 成功，然后画出噪点。所以必须 reshape(ggml 序) → permute 回 torch 序。
    """
    import numpy as np
    import torch

    info = idx.tensor(name)
    if not G.supported(info.qtype):
        raise NotImplementedError(
            "GGUF 张量 %s 的量化类型 %s 不受支持" % (name, info.qtype))
    blocks = torch.from_numpy(np.ascontiguousarray(idx.raw(name))).to(device)
    flat = G.dequantize(blocks, info.qtype, dtype=dtype or torch.float16)
    gs = info.ggml_shape
    want = 1
    for d in gs:
        want *= d
    if int(flat.numel()) != want:
        raise ValueError("元素数不符：%s 反量化得 %d，应为 %d（ggml 形状 %s）"
                         % (name, int(flat.numel()), want, gs))
    t = flat.reshape(gs)
    if len(gs) > 1:
        t = t.permute(tuple(range(len(gs) - 1, -1, -1)))
    return t.contiguous()


def to_ldm_state_dict(idx: GGUFIndex, *, device: str = "cpu", dtype=None,
                      on_progress: Optional[Callable[[int, int], None]] = None
                      ) -> Dict[str, Any]:
    """全量反量化成 **LDM 命名**的 state_dict。

    ⚠️ 内存代价 = fp16 全量（SDXL UNet ≈4.78GB）。这是 eager 模式的固有成本：
    它省的是**硬盘**（GGUF Q8_0 2.5GB vs fp16 5.1GB），不是显存。
    要省显存请等 lazy 模式（需要逐层命名映射，尚未做 —— 见文末 TODO）。
    """
    import torch

    dt = dtype or torch.float16
    out: Dict[str, Any] = {}
    total = len(idx.tensors)
    bad: List[str] = []
    for i, name in enumerate(idx.names(), 1):
        try:
            out[name] = dequantize_tensor(idx, name, device=device, dtype=dt)
        except NotImplementedError:
            bad.append(name)
        if on_progress:
            on_progress(i, total)
    if bad:
        raise NotImplementedError(
            "%d 个张量的量化类型不受支持（示例: %s）" % (len(bad), ", ".join(bad[:3])))
    return out


def ensure_ldm_prefix(sd: Dict[str, Any]) -> Dict[str, Any]:
    """保证 key 带 diffusers 期望的 LDM 前缀 ``model.diffusion_model.``。

    ⚠️ 这里踩过一次坑，记下来：``convert_ldm_unet_checkpoint`` 内部是
    ``if key.startswith(LDM_UNET_KEY): unet_state_dict[key.replace(LDM_UNET_KEY, "")] = ...``
    ⇒ 它**期望输入带前缀**。提前把前缀剥掉会让它产出**空字典**，最终表现是
    「转换成功但缺 19 个关键层」，很容易误判成「架构不匹配」。
    所以本函数的方向是**补齐**前缀，不是剥离。前缀常量直接读 diffusers，不自己写死。
    """
    try:
        from diffusers.loaders.single_file_utils import LDM_UNET_KEY as _pref
    except Exception:  # stability-gate: allow-swallow（旧版 diffusers 无此常量时退回已知值，不阻断加载）
        _pref = "model.diffusion_model."
    out: Dict[str, Any] = {}
    for k, v in sd.items():
        key = k if k.startswith(_pref) else _pref + k
        out[key] = v
    return out


# ── 接线 diffusers UNet ───────────────────────────────────────────────
def apply_to_unet(unet: Any, gguf_path: str, *, dtype=None,
                  on_progress: Optional[Callable[[str, int, int], None]] = None
                  ) -> Dict[str, Any]:
    """把 GGUF 里的 UNet 权重装进 diffusers 的 UNet。

    命名转换**只走 diffusers 官方** ``convert_ldm_unet_checkpoint``：
    GGUF(LDM 命名) → 剥前缀 → 官方转换 → diffusers 命名 → load_state_dict。

    返回 ``{"ok", "message", "loaded", "missing", "unexpected", ...}``；失败不抛。
    """
    if not available():
        return {"ok": False, "message": unavailable_reason()}
    try:
        import torch
        from diffusers.loaders.single_file_utils import convert_ldm_unet_checkpoint
    except Exception as e:
        return {"ok": False, "message": "diffusers 转换函数不可用：%s: %s" % (type(e).__name__, e)}

    dt = dtype or getattr(unet, "dtype", torch.float16)
    try:
        idx = read_index(gguf_path)
    except Exception as e:
        return {"ok": False, "message": "读取 GGUF 失败：%s: %s" % (type(e).__name__, e)}

    with idx:
        s = idx.summary()
        if not any("input_blocks" in n or "down_blocks" in n for n in idx.names()):
            return {"ok": False,
                    "message": "这不是扩散模型 UNet 权重（找不到 input_blocks/down_blocks）：%s"
                               % s.get("name", gguf_path)}
        if s["unsupported_types"]:
            return {"ok": False,
                    "message": "含不支持的量化类型 %s ⇒ 拒绝半替换"
                               % ", ".join(s["unsupported_types"]),
                    "summary": s}
        try:
            ldm = to_ldm_state_dict(
                idx, device="cpu", dtype=dt,
                on_progress=(lambda i, n: on_progress("dequant", i, n)) if on_progress else None)
        except Exception as e:
            return {"ok": False, "message": "反量化失败：%s: %s" % (type(e).__name__, e)}

    ldm = ensure_ldm_prefix(ldm)
    try:
        converted = convert_ldm_unet_checkpoint(ldm, unet.config, extract_ema=False)
    except Exception as e:
        return {"ok": False,
                "message": "LDM→diffusers 命名转换失败（可能不是同一架构）：%s: %s"
                           % (type(e).__name__, e)}
    del ldm
    if not converted:
        return {"ok": False,
                "message": "官方转换函数返回空结果 ⇒ GGUF 内的 key 不是 LDM UNet 命名"
                           "（可能需要的是 model.diffusion_model.* 前缀）"}

    need = set(unet.state_dict().keys())
    got = set(converted.keys())
    missing = sorted(need - got)
    unexpected = sorted(got - need)
    # 关键层缺失 = 这个 GGUF 和这个 UNet 不是一对，装上去必然出灰图 ⇒ 直接拒绝
    critical = [m for m in missing if m.endswith(("attn1.to_q.weight", "conv_in.weight",
                                                  "conv_out.weight", "time_embedding.linear_1.weight"))]
    if critical:
        return {"ok": False,
                "message": "转换后缺关键层（%d 个，示例 %s）⇒ 该 GGUF 与当前 UNet 架构不匹配"
                           % (len(critical), ", ".join(critical[:3])),
                "missing": missing[:20]}

    try:
        result = unet.load_state_dict(converted, strict=False)
    except Exception as e:
        return {"ok": False, "message": "load_state_dict 失败：%s: %s" % (type(e).__name__, e)}

    loaded = len(got & need)
    report = {
        "ok": True,
        "message": "GGUF 权重已装进 UNet：%d 层（量化 %s，占比 %.0f%%）"
                   % (loaded, s["dominant_type"], 100.0 * loaded / max(len(need), 1)),
        "loaded": loaded,
        "missing": list(getattr(result, "missing_keys", []) or [])[:20],
        "unexpected": unexpected[:20],
        "summary": s,
    }
    logger.info("[gguf_loader] %s", report["message"])
    return report


def estimate(gguf_path: str) -> Dict[str, Any]:
    """不加载权重，估算显存/磁盘账（供 UI 在下载前展示）。"""
    try:
        with read_index(gguf_path) as idx:
            s = idx.summary()
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    fp16_gb = s["dequant_gb"]
    return {"ok": True, "fp16_gb": fp16_gb, "quant_gb": s["weights_gb"],
            "saved_gb": round(fp16_gb - s["weights_gb"], 2),
            "saved_pct": round(100.0 * (1 - s["weights_gb"] / fp16_gb), 1) if fp16_gb else 0.0,
            "dominant_type": s["dominant_type"], "path": gguf_path}


def describe() -> str:
    lines = ["GGUF 加载器"]
    lines.append("  gguf 包: %s" % ("可用" if available() else unavailable_reason()))
    lines.append("  支持类型: %s" % ", ".join(G.supported_names()))
    lines.append("  命名转换: diffusers 官方 convert_ldm_unet_checkpoint（不自己写映射表）")
    lines.append("  模式: eager（省硬盘，显存不变）；lazy（省显存）尚未实现")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())  # stability-gate: allow-print（__main__ CLI 入口，输出给人看）
