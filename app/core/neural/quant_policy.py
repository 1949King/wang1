# -*- coding: utf-8 -*-
"""精度策略（fp16 / fp8）—— 纯函数，可单测（2026-10-25）。

背景
====
设备画像（neural/device_profile.py）早已算出 usable.fp8（Ada/Hopper/Blackwell 且装 torchao），
后端注册表也声明 diffusers 支持 fp8，但引擎里 quant 恒 fp16 ⇒ 声明与执行脱节。

本模块只回答一件事：**这次该用什么精度，以及为什么**。
真正的量化执行在 diffusers_image.load()（torchao Float8WeightOnlyConfig）；
没有 torchao 时本模块会给出 fallback 原因，由引擎决定「回落」还是「严格失败」。

口径
====
· 默认 fp16（不改变任何既有行为）；
· 请求 fp8 且（能力位 + torchao + 显存下限）都满足 ⇒ fp8；
· 不满足 ⇒ 默认**回落 fp16 并带原因**；严格模式（SHIGUANG_FP8_STRICT=1）⇒ ok=False，
  绝不静默降级成「你以为在用 fp8」。
"""
from __future__ import annotations

from typing import Any, Dict

PRECISION_FP16 = "fp16"
PRECISION_FP8 = "fp8"

#: fp8 在本项目的最低显存门槛（GB）——低于此连权重都不够，量化也救不了
FP8_MIN_VRAM_GB = 6.0
#: 支持 fp8 的 GPU 代际（仅作说明用；真正的判定在 device_profile 的 usable.fp8，
#: 它把「架构代际 + 是否装 torchao」合并了。注意画像里的 arch 是 "sm89" 这类形态，
#: 不能再按 "ada" 字符串二次比较——2026-10-25 踩过这个坑。）
FP8_ARCHS = ("ada", "hopper", "blackwell")


def normalize_requested(value: str) -> str:
    """把外部输入归一成 "" | fp16 | fp8；未知值返回 ""（= 按默认）。"""
    v = str(value or "").strip().lower()
    if v in ("", "auto", "default"):
        return ""
    if v in ("fp16", "float16", "half"):
        return PRECISION_FP16
    if v in ("fp8", "float8", "e4m3", "fp8_e4m3"):
        return PRECISION_FP8
    return ""


def resolve_precision(*, requested: str = "", usable_fp8: bool = False,
                      arch: str = "", vram_gb: float = 0.0,
                      strict: bool = False) -> Dict[str, Any]:
    """返回 {ok, precision, requested, fallback, reasons}。

    ok=False 只发生在「严格模式 + 请求 fp8 但不可用」；非严格模式一律回落 fp16。
    """
    req = normalize_requested(requested)
    reasons = []

    if req == "":
        reasons.append("未指定精度 ⇒ 默认 fp16")
        return {"ok": True, "precision": PRECISION_FP16, "requested": "",
                "fallback": "", "reasons": reasons}

    if req == PRECISION_FP16:
        reasons.append("请求 fp16 ⇒ 直接使用")
        return {"ok": True, "precision": PRECISION_FP16, "requested": req,
                "fallback": "", "reasons": reasons}

    # 以下是 fp8
    why = ""
    if not usable_fp8:
        why = "设备画像判定 fp8 不可用（需 Ada/Hopper/Blackwell 且安装 torchao）"
    elif float(vram_gb or 0.0) < FP8_MIN_VRAM_GB:
        why = "显存 %.1fGB 低于 fp8 门槛 %.1fGB" % (float(vram_gb or 0.0), FP8_MIN_VRAM_GB)
    if why:
        reasons.append(why + " ⇒ 回落 fp16")
        if strict:
            return {"ok": False, "precision": PRECISION_FP16, "requested": req,
                    "fallback": why, "reasons": reasons}
        return {"ok": True, "precision": PRECISION_FP16, "requested": req,
                "fallback": why, "reasons": reasons}

    reasons.append("fp8 条件满足（%s · %.1fGB）" % (arch, float(vram_gb or 0.0)))
    return {"ok": True, "precision": PRECISION_FP8, "requested": req,
            "fallback": "", "reasons": reasons}


def probe_usable() -> Dict[str, Any]:
    """读设备画像，给出 {usable_fp8, arch, vram_gb, torchao}（异常按不可用）。"""
    try:
        from app.core.neural import device_profile

        p = device_profile.probe()
        usable = bool((p.get("usable") or {}).get("fp8"))
        return {"usable_fp8": usable, "arch": str(p.get("arch") or ""),
                "vram_gb": float(p.get("vram_gb") or 0.0),
                "torchao": bool((p.get("libs") or {}).get("torchao"))}
    except Exception:
        return {"usable_fp8": False, "arch": "", "vram_gb": 0.0, "torchao": False}
