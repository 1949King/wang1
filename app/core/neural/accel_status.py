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
    "int8_aten_win": {"measured": True, "ok": False,
                       "note": "2026-10-27 项目 venv(torch 2.6.0+cu124) 实测：aten::_weight_int8pack_mm 在 CUDA 上 NotImplementedError（Windows 轮子未编译该 kernel）"},
    "int4_aten_win": {"measured": True, "ok": False,
                       "note": "同族结论：int4 的 _convert_weight_to_int4pack/_weight_int4pack_mm 需 torch>=2.14 的 Windows 构建才有 kernel；项目 venv 2.6.0 不具备（用户已在 torch 2.14.1+cu130 独立环境打通原生 int4，跨环境不可直接复用）"},
    "sdxl_resolution_curve": {"measured": True, "note": "SDXL 20 步实测曲线：1024²=30.7s/5.21GB · 832²=16.4s/5.10GB · 768²=14.3s/5.11GB ⇒ 峰值不变、耗时随像素线性降；整卡实测 6.58GB 后每步慢 4×（换页），LCM fast 28.1s/6.95GB 亦不划算"},
    "sdxl_whole_gpu": {"measured": True, "ok": False,
                       "note": "2026-10-27 实测：8GB 上 pipe.to(cuda) 占 6.58GB ⇒ 1024² 每步 15~18s（换页），比 offload 的 1.53s/步慢约 4×；整卡不可行"},
    "sdxl_split_residency": {"measured": True, "ok": False,
                              "note": "2026-10-29 实测（RTX 4060 Laptop 8GB / SDXL 1024² / 20步，data/sdxl_split_residency_bench.json）："
                                      "①UNet 独占整卡（4.89GB 驻留）+ 手写去噪循环 = 787ms/步，比 model_offload 基线 1.07s/步 快 1.36×，"
                                      "但产物灰图（手写循环数学不可信，已弃）；"
                                      "②产品形态（官方 pipe.__call__ 传 prompt_embeds，UNet+VAE 驻留 5.05GB）= 1.64s/步，**慢 0.60×**："
                                      "VAE 驻留后 1024² 解码激活峰值把总峰值顶到 8.96GB ⇒ 落入 WDDM 换页区（与 sdxl_whole_gpu 同根因）；"
                                      "结论：8GB 卡上『UNet 整卡驻留 + VAE 也驻留』不可行，"
                                      "理论最优解（UNet 驻留 + VAE 按需上卡解码）因官方管线不支持 decode 单独搬卡而无干净实现，"
                                      "维持 model_offload 现状。**SDXL 在本机的提速空间已穷尽，收益要等 fp8/int4 量化**"},
    "sd15_fast_8step": {"measured": True, "note": "SD1.5 512² 8 步 1.55s（基线 20 步 3.6s）"},
    "cudagraphs": {"measured": True, "speedup": 0.33,
                   "note": "2026-10-27 实测：500ms/步 vs 基线 165ms/步 ⇒ 慢 3 倍，禁止启用"},
    # ── 2026-11-01 新增：GGUF 与 SageAttention 的真机结论 ──────────────────
    "gguf_dequant_torch": {"measured": True, "ok": True,
                           "note": "GGUF 反量化**必须用 torch/GPU 版，不能用 gguf.quants 的 numpy 版**："
                                   "本机实测同一 3.28M 元素矩阵，numpy 62.08ms（≈50 M元素/s，全 SDXL UNet 22.7s/次 "
                                   "⇒ 30 步 11.4 分钟，不可用）；torch GPU 0.10~2.27ms（快 27~606×，视量化类型）。"
                                   "已逐元素对齐 numpy 权威实现：F32/F16/BF16/Q4_0/Q5_0/Q8_0/Q4_K/Q6_K 全部 rel=0。"
                                   "实现见 app/core/neural/gguf_quants_torch.py"},
    "gguf_q8_0_sd15": {"measured": True, "ok": True,
                       "note": "2026-11-01 端到端闭环：SD1.5 UNet fp16 1.72GB → Q8_0 GGUF 0.91GB（-46.9%）"
                               "→ 本项目 loader 装回 diffusers UNet，686 层 100% 装入、零缺失，"
                               "30 层抽样最大相对误差 4.05e-03，CPU 前向 std=0.88（权重生效）。"
                               "⚠️ 只省硬盘/下载量，**不省显存**（eager 模式）；未做出图 PSNR 对照。"},
    "sageattention_windows": {"measured": True, "ok": False,
                              "note": "PyPI 上的 sageattention 是**纯 Triton 实现**（py3-none-any，20KB，非官方 CUDA 扩展）。"
                                      "Windows 上跑通需要三件套：① triton-windows（3.2.0.post21 实测可装，39.7MB）"
                                      "② MSVC（本机 VS 2026 带 cl.exe）③ **CUDA Toolkit 的 cuda.h**"
                                      "（triton 的 driver.c 里 #include \"cuda.h\"；本机没有，torch 自带的 "
                                      "torch/cuda.h 不能替代）⇒ 现报 `Failed to find C compiler`。"
                                      "结论：对终端用户门槛过高，只能作为高级用户可选项，不进主路径。"},
    "torchao_env_mismatch": {"measured": True, "ok": True,
                              "note": "【2026-11-01 已修复】原问题：torchao 0.16.0 + torch 2.6.0+cu124 导入即报 "
                                      "`Skipping import of cpp extensions due to incompatible torch version`"
                                      " ⇒ fp8 声明可用但实际不可用。已降到 **torchao 0.12.0**："
                                      "警告消失、`Float8WeightOnlyConfig` 正常、`torch._scaled_mm` 在 sm89 上执行成功。"
                                      "教训：install_hint 早就写着 `>=0.12,<0.14`，环境却装了 0.16 —— 门禁没覆盖依赖版本。"},
    "fp8_sm89_net_gain": {"measured": True, "ok": True, "speedup": 0.90,
                           "note": "2026-11-01 出图级实测（SD1.5 512²·20步·whole-GPU·同 seed·torchao 0.12.0）："
                                   "**推翻 2026-10-27 的「无加速」结论**。"
                                   "耗时 3.92s → 3.54s（快 10%）；峰值显存 2.81 → 2.54GB（-9.6%）；"
                                   "画质 PSNR 17.73dB / 低频(8×) 24.56dB。"
                                   "只省 9.6% 因 Float8WeightOnlyConfig 只作用 nn.Linear，"
                                   "Conv2d（SD1.5 占 1.10GB）未被量化。结论：**Ada+ 卡上 fp8 是净收益，该默认开**。"},
    "gguf_lazy_tradeoff": {"measured": True, "ok": True,
                            "note": "2026-11-01 lazy 反量化实测（SD1.5 512²·20步·Q8_0）："
                                    "whole-GPU 峰值 2.81 → **1.07GB（省 62%）**，代价 3.72 → 9.78s（**慢 2.63×**）；"
                                    "model_offload 峰值 1.88 → **0.82GB（省 56%）**，代价 4.75 → 10.32s（慢 2.17×）。"
                                    "282 层全部替换、零遗漏，与 eager 输出**逐位相同（差值 0）**。"
                                    "定位：显存极限时（≤4GB 卡跑 SD1.5）的最后手段，不是默认选项。"},
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
        "torch_kernels": torch_kernels(),
        "measured": _MEASURED,
        "honesty": "estimated=True 的项均为行业经验区间，未在本机验证；实测过的以 measured 为准。",
    }


def torch_kernels() -> Dict[str, Any]:
    """探测 torch 自带低精度 GEMM kernel 在本机是否真能执行（只信真调用，不信 hasattr）。

    2026-10-27 本项目实测：hasattr 为 True 但 CUDA 后端没注册实现 ⇒ NotImplementedError。
    dispatcher 失败会往 fd2 打整张 backends 表，这里临时重定向到 devnull，避免污染画布日志。
    """
    res: Dict[str, Any] = {"available": False, "reason": "", "kernels": {}}
    try:
        import torch

        if not torch.cuda.is_available():
            res["reason"] = "无 CUDA"
            return res
        res["available"] = True
        w = torch.randn(256, 256, device="cuda", dtype=torch.bfloat16)
        x = torch.randn(1, 256, device="cuda", dtype=torch.bfloat16)
        import os as _os

        devnull = _os.open(_os.devnull, _os.O_WRONLY)
        old = _os.dup(2)
        try:
            _os.dup2(devnull, 2)
            for name in ("_weight_int8pack_mm", "_convert_weight_to_int4pack"):
                fn = getattr(torch, name, None)
                if fn is None:
                    res["kernels"][name] = "missing"
                    continue
                try:
                    if name == "_weight_int8pack_mm":
                        amax = w.abs().amax(dim=1).clamp_min(1e-8)
                        scale = amax / 127.0
                        wq = torch.round(w / scale.unsqueeze(1)).clamp(-127, 127).to(torch.int8)
                        fn(x, wq, scale)
                    else:
                        fn(torch.zeros(256, 32, device="cuda", dtype=torch.int32), 8)
                    res["kernels"][name] = "ok"
                except Exception as e:
                    res["kernels"][name] = type(e).__name__
        finally:
            _os.dup2(old, 2)
            _os.close(devnull)
            _os.close(old)
    except Exception as e:
        res["reason"] = f"{type(e).__name__}: {e}"
    return res


def install_hint() -> Dict[str, str]:
    """给出「网络恢复后」该装什么（版本与 torch 2.6.0+cu124 对齐）。

    ⚠️ 2026-11-01 实录：本机曾装 torchao 0.16.0（超出本函数建议上限 0.14），
    报 `Skipping import of cpp extensions due to incompatible torch version` ⇒ fp8 假可用。
    已降到 **0.12.0** 并复测通过（出图快 10% / 显存 -9.6%）。装之前仍要
    `pip list | findstr torchao` 核对，别信「装上就算通」。
    """
    return {
        "fp8": 'pip install "torchao>=0.12,<0.14"   # 与 torch 2.6 匹配；0.16.x 会报 cpp extensions 不兼容',
        "int4": 'pip install nunchaku',
        "compile": 'pip install triton-windows  # Windows 上的 triton 包名；'
                   '注意还要 MSVC + CUDA Toolkit 的 cuda.h 才能真正编译 kernel',
        "tensorrt": 'pip install "tensorrt==10.7.*" --extra-index-url https://pypi.nvidia.com && '
                    'pip install "torch-tensorrt==2.6.*"',
        "gguf": 'pip install gguf   # 纯 Python，无编译；反量化内核在本项目 gguf_quants_torch.py',
    }
