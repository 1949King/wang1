# -*- coding: utf-8 -*-
"""设备画像（DeviceProfile）—— 让推理底座摆脱「只适配当前这块卡」。

为什么需要（用户 2026-10-24 指令：「要为后面适配其他设备着想，而不是光适配现在的 4060」）：
  · `execution_decider.detect_hardware_tier()` 用**显存阈值**(4096/16384MB)分三档，只认 CUDA
    ⇒ AMD / Apple MPS / 纯 CPU 全被当「全云档」，换设备直接失效。
  · `memory_policy` 的 offload 概念假设「权重能从 CPU 搬到 GPU」⇒ 统一内存设备上无意义。
  · 双栈（diffsynth/diffusers）优先级写死在代码里 ⇒ 某设备上 diffsynth 不可用时无法按证据换。

本模块只回答一件事：**这台设备有哪些能力位**（fp16/bf16/fp8/int4/sdpa/triton/...），
供上层（backend_registry / execution_planner / memory_policy）做分派。
**不做决策、不 import 重库**（torch 惰性导入，探测失败按 CPU 处理并如实写 reason）。

跨设备验证：环境变量 `SHIGUANG_DEVICE_PROFILE` 可注入一份 JSON 画像，
测试/CI 无需第二台机器即可覆盖 apple/amd/cpu/hopper 各档（见 tests）。
"""
from __future__ import annotations

import json
import logging
import os
import platform
from typing import Any, Dict, List

logger = logging.getLogger("AI短剧编辑器.core.neural.device_profile")

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
_CACHE = os.path.join(_APP_ROOT, "data", "device_profile.json")

_VENDOR_BY_ARCH = {
    # NVIDIA 计算能力 → 代际
    "sm75": "turing", "sm80": "ampere", "sm86": "ampere",
    "sm89": "ada", "sm90": "hopper", "sm100": "blackwell",
}


def _module_available(name: str) -> bool:
    try:
        import importlib.util as u

        return u.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _caps_from(arch: str, vendor: str) -> Dict[str, bool]:
    """按架构推导能力位（保守：不认识的一律 False，不编造支持）。"""
    gen = _VENDOR_BY_ARCH.get(arch, "")
    return {
        "fp16": vendor in ("nvidia", "amd", "apple"),
        "bf16": vendor in ("nvidia", "amd", "apple"),
        # FP8 tensor core：Ada(sm89+)/Hopper/Blackwell；AMD/Apple 暂无
        "fp8": vendor == "nvidia" and gen in ("ada", "hopper", "blackwell"),
        # INT4 快速 kernel（Nunchaku 类）：Ampere 及以上
        "int4": vendor == "nvidia" and gen in ("ampere", "ada", "hopper", "blackwell"),
        "sdpa": True,          # torch 2.x 各平台均可用（CPU 也走 math 后端）
    }


def _libs() -> Dict[str, bool]:
    """可选加速件是否可用（决定上层敢不敢选它们）。"""
    return {
        "triton": _module_available("triton"),
        "xformers": _module_available("xformers"),
        "torchao": _module_available("torchao"),
        "nunchaku": _module_available("nunchaku"),
        "diffusers": _module_available("diffusers"),
        "diffsynth_engine": _module_available("diffsynth_engine"),
    }


def _probe_cuda() -> Dict[str, Any] | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        props = torch.cuda.get_device_properties(0)
        major, minor = torch.cuda.get_device_capability(0)
        arch = "sm%d%d" % (major, minor)
        vram = round(props.total_memory / 1024 ** 3, 2)
        return {
            "vendor": "nvidia", "arch": arch, "name": props.name,
            "vram_gb": vram, "device_id": "nvidia:%s:%.1fgb" % (arch, vram),
            "reason": ["CUDA 可用：%s（%s，%.1fGB）" % (props.name, arch, vram)],
        }
    except Exception as e:
        logger.debug("[device_profile] CUDA 探测失败", exc_info=True)
        return {"vendor": "nvidia", "arch": "unknown", "name": "CUDA 探测失败",
                "vram_gb": 0.0, "device_id": "nvidia:unknown",
                "reason": ["CUDA 探测异常 %s: %s" % (type(e).__name__, e)]}


def _probe_mps() -> Dict[str, Any] | None:
    try:
        import torch

        if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            return None
        # 统一内存：无独立显存概念，按物理内存的 70% 估可用（保守，且标明是估算）
        total = 0
        try:
            import subprocess

            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=3)
            total = int(out.stdout.strip()) / 1024 ** 3
        except Exception:
            total = 0.0
        est = round(total * 0.7, 2) if total else 0.0
        return {
            "vendor": "apple", "arch": "mps", "name": "Apple Silicon (MPS)",
            "vram_gb": est, "device_id": "apple:mps:%.1fgb" % est,
            "reason": ["MPS 可用（统一内存，可用量按物理内存 70%% 估算=%.1fGB）" % est],
        }
    except Exception:
        logger.debug("[device_profile] MPS 探测失败", exc_info=True)
        return None


def _probe_rocm() -> Dict[str, Any] | None:
    try:
        import torch

        if not (getattr(torch.version, "hip", None) and torch.cuda.is_available()):
            return None
        props = torch.cuda.get_device_properties(0)
        vram = round(props.total_memory / 1024 ** 3, 2)
        return {
            "vendor": "amd", "arch": "rocm", "name": props.name,
            "vram_gb": vram, "device_id": "amd:rocm:%.1fgb" % vram,
            "reason": ["ROCm 可用：%s（%.1fGB）" % (props.name, vram)],
        }
    except Exception:
        logger.debug("[device_profile] ROCm 探测失败", exc_info=True)
        return None


def _override() -> Dict[str, Any] | None:
    """测试/CI/预配置注入：SHIGUANG_DEVICE_PROFILE='{json}'。"""
    raw = os.environ.get("SHIGUANG_DEVICE_PROFILE", "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        data.setdefault("reason", ["由 SHIGUANG_DEVICE_PROFILE 注入"])
        return data
    except Exception:
        logger.warning("[device_profile] 注入画像解析失败，忽略")
        return None


def probe(*, force: bool = False, use_cache: bool = True) -> Dict[str, Any]:
    """返回设备画像（含能力位与可选加速件）。异常一律降级为 CPU，不抛。"""
    inj = _override()
    if inj is not None:
        prof = dict(inj)
    else:
        cached = None
        if use_cache and not force and os.path.exists(_CACHE):
            try:
                with open(_CACHE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
            except Exception:
                cached = None
        if cached and isinstance(cached, dict) and cached.get("device_id"):
            prof = dict(cached)
        else:
            prof = _probe_cuda() or _probe_mps() or _probe_rocm()
            if prof is None:
                prof = {
                    "vendor": "cpu", "arch": "cpu",
                    "name": platform.processor() or platform.machine() or "CPU",
                    "vram_gb": 0.0, "device_id": "cpu:cpu",
                    "reason": ["无可用 GPU 后端（CUDA/MPS/ROCm 均不可用）⇒ 按 CPU 处理"],
                }

    vendor = str(prof.get("vendor") or "cpu")
    arch = str(prof.get("arch") or "")
    caps = dict(prof.get("capabilities") or {})
    # 能力位：注入画像可显式覆盖；否则按架构推导（不认识的架构 => 全 False）
    caps = {**_caps_from(arch, vendor), **caps}
    prof["capabilities"] = caps
    prof["libs"] = {**_libs(), **(prof.get("libs") or {})}
    prof.setdefault("reason", [])
    # 统一收口：能力位与库可用性合并成「能不能用」的判据，避免上层各算一遍
    prof["usable"] = {
        "fp8": bool(caps.get("fp8")) and bool(prof["libs"].get("torchao")),
        "int4": bool(caps.get("int4")) and bool(prof["libs"].get("nunchaku")),
        "compile": bool(prof["libs"].get("triton")),
        "xformers": bool(prof["libs"].get("xformers")),
        "diffsynth": bool(prof["libs"].get("diffsynth_engine")),
        "diffusers": bool(prof["libs"].get("diffusers")),
    }
    if not force and not inj:
        try:
            os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
            with open(_CACHE, "w", encoding="utf-8") as f:
                json.dump(prof, f, ensure_ascii=False, indent=1)
        except Exception:
            logger.debug("[device_profile] 缓存写入失败（不阻断）", exc_info=True)
    return prof


def summary() -> Dict[str, Any]:
    """供 UI / 决策器回显的简短画像。"""
    p = probe()
    return {
        "device_id": p.get("device_id"), "vendor": p.get("vendor"),
        "arch": p.get("arch"), "name": p.get("name"),
        "vram_gb": p.get("vram_gb"),
        "capabilities": p.get("capabilities"), "usable": p.get("usable"),
        "reason": p.get("reason"),
    }


def invalidate() -> List[str]:
    """删除缓存（换卡/驱动更新后调用）。"""
    try:
        if os.path.exists(_CACHE):
            os.remove(_CACHE)
            return ["已清除设备画像缓存"]
    except OSError:
        logger.debug("[device_profile] 清除缓存失败", exc_info=True)
    return []
