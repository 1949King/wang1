# -*- coding: utf-8 -*-
"""加速能力报告（2026-10-27）：fp8 / int4 / compile / tensorrt 到底能不能用。

为什么单独成模块
================
用户问「C++ 重写会不会更快 / 量化能不能提速」。答案必须**可查、可复现**，而不是口号：
本模块只读探测（find_spec + 设备画像），输出每一项的 {ok, lib, reason, expected}。
expected 一律标注为「估算」，并注明是否本机实测过——没测过就不写成结论。

纪律
====
· 顶层零重依赖（不 import torch/diffusers），画布 HTTP 线程可安全调用；
· 缺库 ⇒ ok=False + 明确 reason（含 pip 包名），绝不假装可用；
· 已实测的收益写进 _MEASURED，未实测的只给区间且带 estimated 标记。
"""
from __future__ import annotations

import importlib.util as _u
import logging
from typing import Any, Dict

logger = logging.getLogger("AI短剧编辑器.core.neural.accel_status")

#: 本机实测过的收益（只有跑过才登记；键与 status() 对齐）
_MEASURED: Dict[str, Dict[str, Any]] = {
    "sd15_fast_8step": {"measured": True, "note": "SD1.5 512² 8 步 1.55s（基线 20 步 3.6s）"},
    "cudagraphs": {"measured": True, "speedup": 0.33,
                   "note": "2026-10-27 实测：500ms/步 vs 基线 165ms/步 ⇒ 慢 3 倍，禁止启用"},
}


def _has(mod: str) -> bool:
    try:
        return _u.find_spec(mod) is not None
    except Exception:
        return False


def _device() -> Dict[str, Any]:
    """设备画像；画像缺失（缓存空/探测失败）时用 torch 直查兜底，避免显示 unknown。"""
    info: Dict[str, Any] = {"arch": "", "vram_gb": 0.0, "usable": {}, "libs": {}}
    try:
        from app.core.neural import device_profile

        p = device_profile.probe()
        info = {"arch": p.get("arch"), "vram_gb": float(p.get("vram_gb") or 0.0),
                "usable": p.get("usable") or {}, "libs": p.get("libs") or {}}
    except Exception:
        logger.debug("[accel_status] 设备画像不可用", exc_info=True)
    if not info.get("vram_gb"):
        try:
            import torch

            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                cap = torch.cuda.get_device_capability(0)
                info["vram_gb"] = round(props.total_memory / (1024 ** 3), 1)
                info["arch"] = info.get("arch") or f"sm{cap[0]}{cap[1]}"
                info["device_name"] = props.name
        except Exception:
            logger.debug("[accel_status] torch 兜底查询失败", exc_info=True)
    return info


def status() -> Dict[str, Any]:
    """四项加速能力的**真实**可用性 + 缺什么。"""
    d = _device()
    libs = d.get("libs") or {}
    usable = d.get("usable") or {}
    vram = float(d.get("vram_gb") or 0.0)

    fp8_ok = bool(usable.get("fp8"))
    int4_ok = bool(usable.get("int4"))
    triton = bool(libs.get("triton")) or _has("triton")
    trt = _has("tensorrt") and _has("torch_tensorrt")

    return {
        "device": {"arch": d.get("arch"), "vram_gb": vram},
        "fp8": {
            "ok": fp8_ok,
            "lib": "torchao",
            "reason": "" if fp8_ok else ("需 Ada/Hopper/Blackwell 且安装 torchao"
                                         if not libs.get("torchao")
                                         else "硬件代际不支持 fp8"),
            "expected": "估算 1.4~1.8×（SDXL 权重减半后可能整卡驻留）；本机未实测",
            "estimated": True,
        },
        "int4": {
            "ok": int4_ok,
            "lib": "nunchaku",
            "reason": "" if int4_ok else "需安装 nunchaku 且为 Ampere+ 显卡",
            "expected": "估算 1.6~2.2× + 显存减半；本机未实测",
            "estimated": True,
        },
        "compile": {
            "ok": bool(triton),
            "lib": "triton",
            "reason": "" if triton else "缺 triton（Windows 需安装 triton-windows；无 triton 时 inductor 不可用）",
            "expected": "估算 1.1~1.3×；**cudagraphs 后端已实测负收益（0.33×），不采用**",
            "measured": _MEASURED["cudagraphs"],
            "estimated": True,
        },
        "tensorrt": {
            "ok": bool(trt),
            "lib": "tensorrt + torch_tensorrt",
            "reason": "" if trt else "缺 tensorrt / torch_tensorrt（需 NVIDIA 账号下载匹配 CUDA 12.4 的版本）",
            "expected": "估算 1.2~1.4×（kernel 融合，工程量大、每次换模型要重编译）",
            "estimated": True,
        },
        "measured": _MEASURED,
        "honesty": "estimated=True 的项均为行业经验区间，未在本机验证；实测过的以 measured 为准。",
    }


def install_hint() -> Dict[str, str]:
    """给出「网络恢复后」该装什么（版本与 torch 2.6.0+cu124 对齐）。"""
    return {
        "fp8": 'pip install "torchao>=0.12,<0.14"',
        "int4": 'pip install nunchaku',
        "compile": 'pip install triton-windows  # Windows 上的 triton 包名',
        "tensorrt": 'pip install "tensorrt==10.7.*" --extra-index-url https://pypi.nvidia.com && '
                    'pip install "torch-tensorrt==2.6.*"',
    }
