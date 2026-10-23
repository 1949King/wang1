# -*- coding: utf-8 -*-
"""推理后端注册表 —— 「装得上才在册，在册才可能被选中」。

设计意图（2026-10-24 用户指令：为适配其他设备着想）：
  · 引擎优先级**不写死在代码里**：diffsynth / diffusers / nunchaku / tensorrt 各自登记
    能力声明，决策器只从本表查候选 ⇒ 换设备时表现为「某个后端不在册」，而非报错。
  · 每个后端必须声明：支持哪些模型架构、精度、最小显存、需要哪些库。
  · 本模块**不 import 重库**（torch/diffusers），只用 importlib.util.find_spec 探测，
    避免「探测即加载 4GB 权重」的老坑。
  · 与 execution_planner 的分工：本表回答「谁可用」，planner 回答「这次选谁 + 为什么」。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.core.neural.backend_registry")

# ── 后端声明表（单一事实源）────────────────────────────────────────────
# libs: 该后端运行所需的可选依赖（与 device_profile 的 libs 同名对齐）
# model_archs: 支持的模型架构（与 diffusers_image/diffsynth_image 的 arch 对齐）
_BACKENDS: Dict[str, Dict[str, Any]] = {
    "diffusers": {
        "label": "diffusers（自研栈）",
        "libs": ("diffusers",),
        "model_archs": ("sd15", "sdxl"),
        "precisions": ("fp16", "fp8"),
        "min_vram_gb": {"sd15": 2.5, "sdxl": 5.0},
        "accelerators": ("cache", "fp8"),
        "note": "官方生态、SDXL 首图快；fp8 需 torchao",
    },
    "diffsynth": {
        "label": "DiffSynth（主选栈）",
        "libs": ("diffsynth_engine",),
        # svd：本机视频是 SVD i2v（stabilityai img2vid-xt 权重在盘，diffsynth 支持）
        # ★ 2026-10-24 回归修复：这里漏登记 svd 曾让执行层把「视频本地可做」误判为不可用。
        "model_archs": ("sd15", "sdxl", "svd"),
        "precisions": ("fp16",),
        "min_vram_gb": {"sd15": 2.5, "sdxl": 5.0, "svd": 5.0},
        "accelerators": ("cache",),
        "note": "SD1.5 首图快；SDXL 首次推理有长编译（实测 415s）；SVD 视频 i2v",
    },
    # 以下为「部署期可选」后端：不装就自然不在册，代码里无需 if
    "nunchaku": {
        "label": "Nunchaku（INT4 量化）",
        "libs": ("nunchaku",),
        "model_archs": ("sdxl",),      # 支持面需按版本核实，先只声明 sdxl
        "precisions": ("int4",),
        "min_vram_gb": {"sdxl": 3.0},
        "accelerators": ("int4", "cache"),
        "note": "4bit kernel；模型支持面以安装版本为准（未在本机核实）",
    },
    "tensorrt": {
        "label": "TensorRT",
        "libs": ("tensorrt",),
        "model_archs": ("sd15", "sdxl"),
        "precisions": ("fp16", "int8"),
        "min_vram_gb": {"sd15": 2.5, "sdxl": 5.0},
        "accelerators": ("compiled",),
        "note": "按卡/驱动构建 engine，升级驱动需重建",
    },
}


def _lib_ok(name: str, profile: Optional[Dict[str, Any]]) -> bool:
    if profile and isinstance(profile.get("libs"), dict) and name in profile["libs"]:
        return bool(profile["libs"][name])
    try:
        import importlib.util as u

        return u.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def candidates(*, model_arch: str, profile: Optional[Dict[str, Any]] = None
               ) -> List[Dict[str, Any]]:
    """返回该模型架构下**可用**的后端列表（含不可用原因，便于排障）。

    判据三条：① 声明的依赖库都在 ② 支持该 arch ③ 设备显存 ≥ 声明下限（无 vram 的
    画像视为未知，不因未知而排除——交由上层决策）。
    """
    vram = None
    if profile and isinstance(profile.get("vram_gb"), (int, float)):
        vram = float(profile["vram_gb"]) or None
    out: List[Dict[str, Any]] = []
    for bid, spec in _BACKENDS.items():
        reasons: List[str] = []
        ok = True
        if model_arch not in spec["model_archs"]:
            ok = False
            reasons.append("不支持架构 %s（支持 %s）" % (model_arch, "/".join(spec["model_archs"])))
        missing = [lib for lib in spec["libs"] if not _lib_ok(lib, profile)]
        if missing:
            ok = False
            reasons.append("缺少依赖：%s" % ",".join(missing))
        need = float((spec.get("min_vram_gb") or {}).get(model_arch) or 0.0)
        if vram is not None and need and vram < need:
            ok = False
            reasons.append("显存不足：需 %.1fGB，本机 %.1fGB" % (need, vram))
        out.append({"id": bid, "label": spec["label"], "available": ok,
                    "spec": spec, "reasons": reasons or ["可用"]})
    return out


def available_ids(*, model_arch: str, profile: Optional[Dict[str, Any]] = None) -> List[str]:
    return [c["id"] for c in candidates(model_arch=model_arch, profile=profile)
            if c["available"]]


def describe() -> List[Dict[str, Any]]:
    """全量后端声明（供 UI/文档/排障）。"""
    return [{"id": k, **dict(v)} for k, v in _BACKENDS.items()]
