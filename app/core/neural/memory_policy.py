# -*- coding: utf-8 -*-
"""显存策略（memory policy） —— W1 显存分级的**单一决策点**

为什么要有这个模块
==================
在 V4.40.23 之前，「这个模型该怎么装进显存」的判定**散在 `video_gen` 里**：
`should_offload()` 一个函数、`decode_chunk_size` 在调优表里、加载方式的选择
又在 `load()` 的 if/else 里。W1 路线图（`docs/_reports/2026-10-02-自研引擎一个月达标路线图.md`）
要求把显存管理收口成一个**可独立测试、可独立演进**的决策点，再在其上叠加
逐层磁盘卸载（layer disk offload，W2 目标）。

本模块就是那个决策点。它**只做决策，不做加载**：
  - 输入：模型 id、帧数、（可选）空闲显存 / 参数量 / 调优表条目
  - 输出：一个 dict —— 装载模式、是否 offload、VAE 解码块大小、量化档、
    显存下限估计、以及**为什么这么决定**（reasons，决策必须可见，同 R9 精神）

装载模式（mode）
================
  - ``whole_gpu``           整模型常驻显存，不 offload。
                            ⚠️ 对 SVD 实测是**危险路径**：显存随帧数 ≈0.37GB/帧 增长，
                            10 帧 7.70GB 触发 WDDM 分页 ⇒ 实测 **>600s 卡死**（正常 75.7s）。
                            仅当调优表明确说 ``offload=False`` **且**实测下限能留出
                            15% 余量时才选它（当前注册表里没有这样的模型）。
  - ``model_offload``       整模型级 CPU offload（accelerate ``enable_model_cpu_offload``）。
                            ★ **当前所有已登记模型的定稿结论**（经两次反转，见下）。
  - ``sequential_offload``  更激进的逐模块 offload（``enable_sequential_cpu_offload``）。
                            当**有实测/登记依据表明**模型超过本卡显存时才升级到这里
                            （例：Wan 系登记 vram 8.0GB > 8GB 卡 95% 水位线）。
  - ``layer_cpu_offload``   block 组级 CPU 卸载（刀2 落地，2026-10-03）。
                            粒度在 model 与 sequential 之间：UNet 逐 block 挂 hook
                            换入换出，执行端是 `layer_offload.apply_layer_cpu_offload`。
                            ★ 只返回给**显式声明 supported_modes** 的调用方
                            （见下「能力声明」节）。
                            ⚠️ **SDXL@8GB 四档实测落败（同日，bench_sdxl_modes.py，
                            R2/R3 受控两轮复现）**：72.7s / 稳态 3.96GB（v1「先整上卡
                            再下块」另有 ~6.6GB 装载瞬时峰）—— 速度不敌 model 27.9s、
                            显存优势对 sequential 3.76GB 微弱 ⇒ **不定稿 layer**，
                            SDXL 由调优表 prefer_mode 定稿 **model_offload**
                            （5.21GB / 27.9s，8GB 卡 65% 水位可接受）。
                            layer 保留给更窄显存/未来模型，再启用前必须重新实测。
  - ``layer_disk_offload``  逐层磁盘卸载（mmap 流式，对标 DiffSynth offload_to_disk）。
                            **仍不返回此模式**：宁可明说「还没做」，
                            也不假装有这个能力（诚实失败原则）。

能力声明（supported_modes，刀2 新增）
====================================
policy 决策「该用哪档」，但**只有调用方知道自己实现了哪几档**。
``supported_modes=None``（默认）⇒ 只返回旧三档（whole/model/sequential）——
否则 video_gen 拿到不认识的 ``layer_cpu_offload`` 会静默落进 model_offload
分支，造成「决策与执行不符」的语义漂移（违反诚实原则）。
刀2 起 ``diffusers_image`` 显式传 ``supported_modes=ACTIVE_MODES`` 声明四档全实现。

自适应标定档案（2026-10-28 新增，分支 -1）
==========================================
``calibration.py`` 会在本机真跑四档、记账到 ``data/calibration.json``（一个 JSON 文件）。
``pick_memory_policy()`` 现在**先查档案**，命中且过闸就用它，而不是走水位线规则：

  顺序 -1  标定档案        这台机器真跑、真记账        ← 最可信
  顺序  0  调优表 prefer_mode  人工写死的四档对比结论
  顺序1-2  水位线规则      通用设计意图（0.85 / 0.95 / 0.60）

「实测优先」不等于「实测盲目」，两道闸必须过：
  ① ``peak_gb > free_gb``        ⇒ 别的进程占了显存就降级（历史 ≠ 现在）
  ② whole_gpu 再验 15% 余量      ⇒ 历史峰值只说明「当时刚好没炸」

四条**明确不用**档案的边界：``frames > 0``（档案无帧数维度）、档位不在
ACTIVE_MODES、档位不在 supported_modes、``peak_gb <= 0``。
模块缺失或查询异常一律降级走规则 —— 标定是增强，不是前置依赖（D-A3）。
``use_calibration=False`` 可整体关掉（bench / 四档对比 / 排障）。

实测基线（2026-10-01，本机 RTX 4060 Laptop 8GB）
================================================
SVD-xt-i2v（14 步 / chunk=1）：

  ============  =================  ==========================
  帧数          offload 开（选定）  不 offload（危险，已否决）
  ============  =================  ==========================
  5             4.66 GB / 40.0s    5.84 GB / 42.5s
  8             5.58 GB / 63.9s    —
  10            6.20 GB / 75.7s    7.70 GB / **>600s 分页卡死**
  ============  =================  ==========================

★ offload 结论**经过两次反转**才定稿，别再凭直觉改：
  1. 最初判断「offload 是最大瓶颈」⇒ 想关掉。**错**：该判断在 chunk=2 下测出，
     把 chunk 的锅记到 offload 头上（混淆变量）。
  2. 固定 chunk=1 重测：offload **更快**（40.0s vs 42.5s）且**更省显存**（4.66 vs 5.84GB）。
  3. 安全性定论：不 offload 10 帧必分页卡死 ⇒ **所有帧数都 offload**。

依赖纪律
========
- **顶层零重依赖**：不 import torch / diffusers（探测在函数内、且只做 find_spec +
  import torch —— 与 `video_gen.is_available()` 同戒律，防止在 pytest 组合场景崩进程）。
- **不反向 import `video_gen` 于顶层**（循环依赖）；需要调优表时在函数内惰性解析。
"""
from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 装载模式常量（字符串即对外契约，勿改字面值）──────────────────────
MODE_WHOLE_GPU = "whole_gpu"
MODE_MODEL_OFFLOAD = "model_offload"
MODE_SEQUENTIAL_OFFLOAD = "sequential_offload"
MODE_LAYER_CPU_OFFLOAD = "layer_cpu_offload"     # 刀2 落地（2026-10-03）
MODE_LAYER_DISK_OFFLOAD = "layer_disk_offload"   # 仍预告（mmap 磁盘流式未实现）

#: 全部已实现的模式（layer_disk_offload 只是**预告**，绝不假装有）
ACTIVE_MODES = (MODE_WHOLE_GPU, MODE_MODEL_OFFLOAD, MODE_SEQUENTIAL_OFFLOAD,
                MODE_LAYER_CPU_OFFLOAD)
PLANNED_MODES = (MODE_LAYER_DISK_OFFLOAD,)

#: 未声明 supported_modes 的调用方允许返回的模式（向后兼容层）。
#: layer 档只给**显式声明已实现**的引擎 —— 见模块 docstring「能力声明」节。
_LEGACY_MODES = (MODE_WHOLE_GPU, MODE_MODEL_OFFLOAD, MODE_SEQUENTIAL_OFFLOAD)

# ── 实测基线：显存下限估计 = base + per_frame × frames ────────────────
# 数字全部来自本机实测（SVD 见模块 docstring 的表；SDXL 见下方注释），用**线性拟合**，
# 不是为了精确预测，而是为了「帧数翻倍时决策不翻车」的量级判断。
_MEASURED: Dict[str, Dict[str, Dict[str, float]]] = {
    "svd-xt-i2v": {
        # offload 开：5f 4.66 / 8f 5.58 / 10f 6.20 ⇒ 斜率 ≈0.31 GB/帧
        MODE_MODEL_OFFLOAD: {"base_gb": 3.10, "per_frame_gb": 0.31},
        # 不 offload：5f 5.84 / 10f 7.70 ⇒ 斜率 ≈0.37 GB/帧（危险路径，仅作回归参照）
        MODE_WHOLE_GPU: {"base_gb": 3.98, "per_frame_gb": 0.37},
    },
    # 图像模型 frames=0 ⇒ 下限=base。2026-10-03 SDXL 四档实测（bench_sdxl_modes.py，
    # 20 步 1024² fp16，R2/R3 受控两轮复现）：whole_gpu 420s 超时已杀（WDDM 分页）；
    # model 5.21GB/27.9s（★ 定稿档；⚠️ R1 曾测出 220s = 被杀 whole_gpu 的污染，已证伪）；
    # sequential 3.76GB/61.6s（更省显存但慢 2.2×，6GB 卡备选）；layer_cpu v1 72.7s（留档）。
    "sdxl-t2i": {
        MODE_MODEL_OFFLOAD: {"base_gb": 5.21, "per_frame_gb": 0.0},
        MODE_SEQUENTIAL_OFFLOAD: {"base_gb": 3.76, "per_frame_gb": 0.0},
    },
}

# ── 水位线：估计占用相对**总显存**的安全比例 ─────────────────────────
# whole_gpu 要更保守（没有 offload 兜底）：15% 余量；
# model_offload 实测 10 帧 6.2GB / 8GB = 78%，给 95% 上限足够安全。
_WHOLE_GPU_HEADROOM = 0.85
_OFFLOAD_HIGH_WATER = 0.95
# 中间水位（刀2 新增）：登记占用 > 总显存 60%、且引擎声明支持 layer 档
# ⇒ layer_cpu_offload（比 model 细、比 sequential 粗）。
# ⚠️ 暂定值：依据是 SDXL fp16 权重 7.0GB 落在 (4.8, 7.6] 区间的设计意图，
#    刀2-4 四档实测后用真实数字校准并锁进测试。
_LAYER_OFFLOAD_WATER = 0.60


def probe_vram() -> Optional[Dict[str, float]]:
    """探测当前显存（free / total，单位 GB）。探测不到返回 None。

    纪律与 `video_gen.is_available()` 相同：**绝不 import diffusers**；
    torch 也只在确认存在后才 import（find_spec 纯查文件，零副作用）。

    ★ 2026-10-28 改：`free_gb` 取 **torch 与 nvidia-smi 两个读数里更小的那个**。
      原因是实测出来的（RTX 4060 Laptop 8GB / Windows WDDM）：

        | 时点 | torch `mem_get_info()` | nvidia-smi |
        |---|---|---|
        | 空载 | 6.94GB | 6.40GB |
        | Ollama 加载 qwen3.5:4b 后（实占 3.66GB） | **6.94GB（一点没动）** | 2.74GB |

      torch 的读数**对本进程之外的显存占用基本无感**，而偏乐观恰好是危险方向：
      以为够 ⇒ 不让别的进程让位 ⇒ 真加载时挤爆。这台机器上挤爆的表现不是 OOM，
      而是 **WDDM 换页**（2026-10-25 实测 68.9s/步、可用 327MB）—— 不报错、只慢 50 倍，
      比 OOM 更难发现。所以判据必须取保守值。

      两个原始读数都保留在返回里（`torch_free_gb` / `smi_free_gb`），
      便于诊断"差多少"，也便于测试锁住"确实取了较小值"。
    """
    import importlib.util as _u
    if _u.find_spec("torch") is None:
        return None
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        free_b, total_b = torch.cuda.mem_get_info()
        torch_gb = round(free_b / (1024 ** 3), 2)
        smi_gb = nvidia_smi_free_gb()
        free_gb = torch_gb if smi_gb is None else min(torch_gb, float(smi_gb))
        return {"free_gb": round(float(free_gb), 2),
                "total_gb": round(total_b / (1024 ** 3), 2),
                "torch_free_gb": torch_gb,
                "smi_free_gb": smi_gb}
    except Exception:
        logger.debug("[memory_policy] 显存探测失败", exc_info=True)
        return None


#: nvidia-smi 读数的缓存时长（秒）。每次决策起一个 subprocess（~150ms）太贵；
#: 而显存格局不会在 1s 内反复变化，真有变化下一个窗口就能看到。
_SMI_TTL_S = 1.0
_smi_cache: Dict[str, Any] = {"t": -1e9, "v": None}


def nvidia_smi_free_gb(force: bool = False) -> Optional[float]:
    """nvidia-smi 视角的可用显存（GB）；不可用（非 NVIDIA / 未装驱动 / 超时）返回 None。

    为什么不能只用 torch：见 `probe_vram()` docstring 里的实测表 ——
    torch 在 WDDM 下对别的进程占用无感，必须有一个"外部视角"来兜底。

    非 NVIDIA 环境（如 MUSA）返回 None，`probe_vram` 会退回 torch 单读数，
    这不是失败，是**如实降级**：不假装有两个读数。
    """
    now = time.monotonic()
    if not force and (now - float(_smi_cache["t"])) < _SMI_TTL_S:
        return _smi_cache["v"]

    val: Optional[float] = None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, timeout=4,
        )
        if out.returncode == 0:
            lines = (out.stdout or b"").decode("utf-8", "ignore").strip().splitlines()
            if lines:
                # 多卡取第一张：与本项目单卡假设一致；取不到就是 None，不猜
                val = round(float(lines[0].strip()) / 1024, 2)
    except Exception:  # stability-gate: allow-swallow（nvidia-smi 缺失/超时是常态：退回 torch 单读数并记 smi_free_gb=None）
        logger.debug("[memory_policy] nvidia-smi 探测失败（按不可用处理）", exc_info=True)

    _smi_cache["t"] = now
    _smi_cache["v"] = val
    return val


def estimate_floor_gb(model_id: str, frames: int, mode: str,
                      params_b: Optional[float] = None) -> Optional[float]:
    """估计某模式下的显存下限（GB）。无依据时返回 None（**不编数字**）。

    优先级：
      1. 实测拟合表（`_MEASURED`）—— 最可信；
      2. 注册表登记的 ``vram_gb``（由调用方通过 `params_b` 之外的渠道传入时不适用，
         登记值走 `pick_memory_policy` 内部查表）；
      3. 参数量粗估：fp16 权重 ≈ 2 字节/参 × 1.3 推理开销。
    """
    fr = max(0, int(frames))
    m = _MEASURED.get(model_id, {}).get(mode)
    if m:
        return round(m["base_gb"] + m["per_frame_gb"] * fr, 2)
    if params_b and params_b > 0:
        return round(params_b * 2 * 1.3, 2)
    return None


def _resolve_tuned(model_id: str, tuned: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """取调优表条目。优先用调用方传入的（避免循环 import），否则惰性解析。

    惰性解析失败（极不可能，但测试环境可能把 video_gen 摘出去）时退回
    **保守默认** —— 与 `video_gen._DEFAULT_TUNED` 同值，宁可慢不可炸。
    """
    if tuned:
        return dict(tuned)
    try:
        from app.core.neural import video_gen  # 惰性：避免顶层循环依赖
        return video_gen.tuned_for(model_id)
    except Exception:
        logger.debug("[memory_policy] 调优表惰性解析失败，用保守默认", exc_info=True)
        return {"steps": 25, "decode_chunk_size": 2, "offload": True}


def _calibration_lookup(model_id: str, width: int, height: int, frames: int,
                        free_gb: Optional[float],
                        total_gb: Optional[float],
                        modes: tuple) -> Tuple[Optional[str], Optional[Any], str]:
    """查自适应标定档案，返回 ``(mode, entry, reason)``；无命中 mode 为 None。

    设计要点
    --------
    · **实测优先于规则**：标定是本机真跑出来的，比任何水位线规则都准。
    · **但绝不盲用**：档案是历史结论，当前显存可能已被别的进程占走，
      所以必须过「安全闸」——档案记录的占用要放得进**当前空闲**。
    · **任何异常都降级为无命中**：标定是增强，不是前置依赖（D-A3 精神），
      档案坏了不能把档位决策搞挂。
    · **reasons 永不为空**：无论命中与否都返回一句人话，决策必须可见（R9）。
    """
    # ── 已知边界：档案没有「帧数」维度 ────────────────────────────
    # 标定条目记录的是「某模型在某分辨率下的峰值」，视频的显存随帧数线性增长
    # （SVD 实测 ≈0.31GB/帧），拿一次 5 帧的档案去决策 25 帧会**严重低估**。
    # 所以在视频内核算子落地前，这里**明确不用档案**——诚实失败，不猜。
    if int(frames) > 0:
        return None, None, (
            f"视频路径（{int(frames)} 帧）：标定档案尚无帧数维度 ⇒ "
            f"走规则决策（宁慢勿炸）")

    try:
        from app.core.neural import calibration as CAL
        from app.core.neural import device_profile as DP
    except Exception:
        return None, None, "标定模块不可用 ⇒ 跳过档案"

    try:
        store = CAL.default_store()
        prof = DP.probe()
        hit = CAL.lookup(store, prof, model_id, width, height)
    except Exception:
        logger.debug("[memory_policy] 标定档案查询失败", exc_info=True)
        return None, None, "标定档案查询失败 ⇒ 跳过（不影响决策）"

    if hit is None:
        return None, None, "无匹配标定档案 ⇒ 走规则决策"

    key, entry = hit
    mode = str(getattr(entry, "mode", "") or "")
    raw_peak = float(getattr(entry, "peak_gb", 0.0) or 0.0)
    # ★ 分辨率换算：档案可能是 512² 探针测的，本次要出 1024² 就按外推系数放大，
    #   否则安全闸判的是「当时那个尺寸」，不是「这次这个尺寸」（低估 ⇒ 撞 OOM）。
    #   拿不到尺寸/非数字 res_class 时原样返回（不编比例）。
    try:
        peak = float(CAL.peak_for_resolution(entry, key, width, height))
    except Exception:
        peak = raw_peak
    peak_note = "" if abs(peak - raw_peak) < 1e-6 else (
        f"（{raw_peak:.2f}GB @探针分辨率 → {peak:.2f}GB @本次 {max(int(width or 0), int(height or 0))}px，"
        f"外推系数 {CAL.EXTRAPOLATE_COEF_4X} 换算）")

    if mode not in ACTIVE_MODES:
        return None, entry, (
            f"档案 {key} 的档位 {mode} 不在 ACTIVE_MODES ⇒ 忽略")
    if mode not in modes:
        return None, entry, (
            f"档案 {key} 建议 {mode}，但引擎未声明支持该档 ⇒ 忽略")
    if peak <= 0:
        return None, entry, f"档案 {key} 无有效 peak_gb ⇒ 忽略（不拿 0 当依据）"

    # ★ 安全闸 1：历史实测 ≠ 当前可用（别的进程可能已占走显存）
    if free_gb is not None and peak > float(free_gb):
        return None, entry, (
            f"档案 {key} 需 {peak:.2f}GB{peak_note}，但当前空闲仅 "
            f"{float(free_gb):.2f}GB ⇒ **降级走规则决策**（不盲用历史结论）")

    # ★ 安全闸 2：whole_gpu 永远保留 15% 余量（与分支 1 同一条线）
    # 历史实测峰值是「当时刚好没炸」，不是「还有余量」；WDDM 分页的代价是
    # >600s 卡死（SVD 10 帧实测），所以即使档案说 whole_gpu 也要复验余量。
    if mode == MODE_WHOLE_GPU:
        if total_gb is None:
            return None, entry, (
                f"档案 {key} 建议 whole_gpu，但总显存未知 ⇒ 无法复验 15% 余量，"
                f"保守改走规则决策")
        if peak > float(total_gb) * _WHOLE_GPU_HEADROOM:
            return None, entry, (
                f"档案 {key} 建议 whole_gpu，但峰值 {peak:.2f}GB{peak_note} > 总显存 "
                f"{float(total_gb):.2f}GB × {_WHOLE_GPU_HEADROOM}（15% 余量线）"
                f" ⇒ 降级走规则决策")

    # 命中时把**换算后**的峰值带回 entry：调用方拿 `peak_gb` 当 floor_gb 用，
    # 那个数字必须是「本次尺寸的估计」而不是「探针尺寸的实测」。
    eff_entry = entry if abs(peak - raw_peak) < 1e-6 else replace(entry, peak_gb=peak)
    return mode, eff_entry, (
        f"★ 标定档案命中 {key}：{mode}，本机实测峰值 {raw_peak:.2f}GB{peak_note} / "
        f"{float(getattr(entry, 'seconds', 0.0) or 0.0):.2f}s"
        f"（source={getattr(entry, 'source', '?')}，"
        f"verdict={getattr(entry, 'verdict', '?')}）⇒ 采用（实测优先于水位线规则）")


def pick_memory_policy(model_id: str, frames: int = 0,
                       free_vram_gb: Optional[float] = None,
                       total_vram_gb: Optional[float] = None,
                       params_b: Optional[float] = None,
                       tuned: Optional[Dict[str, Any]] = None,
                       registered_vram_gb: Optional[float] = None,
                       supported_modes: Optional[tuple] = None,
                       width: int = 0, height: int = 0,
                       use_calibration: bool = True) -> Dict[str, Any]:
    """为一次加载/生成**决定**显存策略。纯函数，无副作用，可独立测试。

    参数
    ----
    model_id            注册表模型 id（未登记也可以，走保守路径）
    frames              本次要生成的帧数（显存随帧数增长，是决策主变量）
    free_vram_gb        空闲显存；None ⇒ 现场探测；探测不到 ⇒ 按调优表保守决策
    total_vram_gb       总显存；None ⇒ 现场探测
    params_b            模型参数量（十亿），用于无实测数据时的粗估
    tuned               调优表条目（video_gen.tuned_for 的结果）；None ⇒ 惰性解析
    registered_vram_gb  注册表登记的 vram_gb（有登记依据的超显存判定用它）
    supported_modes     ★ 调用方引擎**实际实现**的装载模式（刀2 新增）。
                        None ⇒ 兼容旧行为（只返回 _LEGACY_MODES 三档），
                        layer_cpu_offload 只给显式声明支持它的引擎
                        （见模块 docstring「能力声明」节）。
    width / height      本次出图/出帧尺寸（像素）。**只给标定档案查表用**：
                        档案按 ``res_class`` 分桶，0 ⇒ 走「取同模型最大峰值」的
                        保守兜底（见 `calibration.lookup`）。
    use_calibration     ★ 是否查自适应标定档案（2026-10-28 新增，默认 True）。
                        False ⇒ 完全走规则决策 —— 给 bench / 四档对比 / 排障用，
                        也保证「关掉增强也能跑」这条纪律可被测试验证。

    返回
    ----
    dict：
      ``mode``              装载模式（仅 ACTIVE_MODES 之一；layer_disk_offload 是预告）
      ``offload``           是否 offload（bool，兼容旧接口语义）
      ``decode_chunk_size`` VAE 解码块大小（★ SVD 实测必须 1，比 2 快约 6 倍）
      ``quant``             量化档（当前恒 "fp16"；FP8/NF4 是 W2 目标）
      ``floor_gb``          该模式下的显存下限估计（无依据为 None，不编数字）
      ``free_vram_gb`` / ``total_vram_gb``   决策时看到的显存（可见性）
      ``reasons``           ★ 决策依据列表，**永不为空**（决策必须可见，同 R9）
      ``planned_modes``     尚未实现的模式预告（诚实：明说还没做）
    """
    reasons: List[str] = []
    tun = _resolve_tuned(model_id, tuned)
    fr = max(0, int(frames))
    # 能力声明：未声明 ⇒ 兼容旧三档（layer 档绝不静默落入不认识的引擎）
    modes = tuple(supported_modes) if supported_modes else _LEGACY_MODES

    # ── 显存探测（注入优先，其次现场探测，最后承认不知道）────────────
    if free_vram_gb is not None and total_vram_gb is not None:
        vram = {"free_gb": float(free_vram_gb), "total_gb": float(total_vram_gb)}
    else:
        vram = probe_vram()

    if vram:
        free_gb = float(vram["free_gb"])
        total_gb = float(vram["total_gb"])
        reasons.append(f"显存探测：空闲 {free_gb:.2f}GB / 总 {total_gb:.2f}GB")
    else:
        free_gb = None
        total_gb = None
        reasons.append("无法探测显存（无 CUDA 或探测失败）⇒ 按调优表保守决策")

    chunk = int(tun.get("decode_chunk_size", 2))
    quant = str(tun.get("quant", "fp16"))

    # ── 分支 -1：自适应标定档案（2026-10-28，**实测优先于一切规则**）──────
    # 为什么排在最前：分支 0 的 prefer_mode 是**人工写死的**四档对比结论，
    # 通用性靠注释保证；而标定档案是**这台机器**真跑出来、真记账的。
    # 机器换了/驱动换了/别的进程占了显存，档案会被安全闸拦下并自动降级，
    # 所以「实测优先」不会变成「实测盲目」。
    # 关闭开关：use_calibration=False（bench 脚本、四档对比、故障排查用）。
    if use_calibration:
        cal_mode, cal_entry, cal_reason = _calibration_lookup(
            model_id, width, height, fr, free_gb, total_gb, modes)
        reasons.append(cal_reason)
        if cal_mode:
            # floor 用**实测峰值**，比 estimate_floor_gb 的拟合外推更硬
            return _policy(cal_mode, chunk, quant,
                           round(float(cal_entry.peak_gb), 2), vram, reasons)
    else:
        reasons.append("调用方显式关闭标定档案（use_calibration=False）⇒ 走规则决策")

    # ── 分支 0：调优表**实测指定** prefer_mode（刀2 新增，SDXL 四档实测产物）──
    # 依据必须写在调优表/注册表注释里（四档对比数字），不许凭空指定。
    # 安全约束：prefer_mode 只在「引擎声明支持 ∩ 已实现」时采纳；
    # 绝不许用它绕过 whole_gpu 的余量检查（whole_gpu 只能走分支 1 的双条件）。
    preferred = str(tun.get("prefer_mode") or "")
    if preferred and preferred != MODE_WHOLE_GPU:
        if preferred in ACTIVE_MODES and preferred in modes:
            reasons.append(
                f"调优表实测指定 prefer_mode={preferred}（四档对比依据见注册表注释）⇒ 采用")
            return _policy(preferred, chunk, quant,
                           estimate_floor_gb(model_id, fr, preferred), vram, reasons)
        reasons.append(
            f"调优表指定 prefer_mode={preferred} 但" +
            ("尚未实现（PLANNED）" if preferred in PLANNED_MODES else "引擎未声明支持") +
            " ⇒ 忽略，走常规模态分支")

    # ── 分支 1：调优表说**不** offload（当前注册表没有这样的模型）─────
    if not bool(tun.get("offload", True)):
        floor = estimate_floor_gb(model_id, fr, MODE_WHOLE_GPU, params_b)
        if floor is not None and total_gb is not None and floor <= total_gb * _WHOLE_GPU_HEADROOM:
            reasons.append(
                f"调优表 offload=False 且整卡下限 {floor}GB ≤ 总显存 {total_gb}GB × "
                f"{_WHOLE_GPU_HEADROOM}（15% 余量）⇒ 整模型上卡")
            return _policy(MODE_WHOLE_GPU, chunk, quant, floor, vram, reasons)
        reasons.append(
            "调优表虽 offload=False，但" +
            (f"整卡下限 {floor}GB 超出 15% 余量线" if floor is not None else "无整卡下限实测依据") +
            " ⇒ **诚实改判** model_offload（宁慢勿炸，与 SVD 两次反转发结论一致）")
        return _policy(MODE_MODEL_OFFLOAD, chunk, quant,
                       estimate_floor_gb(model_id, fr, MODE_MODEL_OFFLOAD, params_b),
                       vram, reasons)

    # ── 分支 2：调优表说 offload（当前全部已登记模型的定稿结论）──────
    floor = estimate_floor_gb(model_id, fr, MODE_MODEL_OFFLOAD, params_b)

    # 2a. 有**登记依据**表明模型超显存 ⇒ 升级 sequential（例：Wan 登记 8.0GB > 8GB×95%）
    if registered_vram_gb is not None and total_gb is not None \
            and float(registered_vram_gb) > total_gb * _OFFLOAD_HIGH_WATER:
        reasons.append(
            f"登记 vram {registered_vram_gb}GB > 总显存 {total_gb}GB × {_OFFLOAD_HIGH_WATER}"
            f"（95% 水位线）⇒ 升级 sequential_offload（逐模块卸载）")
        return _policy(MODE_SEQUENTIAL_OFFLOAD, chunk, quant, floor, vram, reasons)

    # 2a'. 登记占用超 60% 中间水位、且引擎**显式声明**支持 layer 档
    #      ⇒ layer_cpu_offload（刀2 新档：UNet 逐 block 换入换出）。
    #      floor 暂无实测依据 ⇒ None（不拿 params_b 粗估 —— 那套「全量驻留」
    #      语义对 layer 档不成立；刀2-4 四档实测后补登记）。
    if MODE_LAYER_CPU_OFFLOAD in modes and registered_vram_gb is not None \
            and total_gb is not None \
            and float(registered_vram_gb) > total_gb * _LAYER_OFFLOAD_WATER:
        reasons.append(
            f"登记 vram {registered_vram_gb}GB > 总显存 {total_gb}GB × {_LAYER_OFFLOAD_WATER}"
            f"（60% 中间水位）且引擎声明支持 ⇒ layer_cpu_offload（block 组逐层卸载，"
            f"阈值暂定，刀2-4 实测校准）")
        return _policy(MODE_LAYER_CPU_OFFLOAD, chunk, quant, None, vram, reasons)

    # 2b. 有实测下限且超水位 ⇒ 同样升级 sequential（按本次帧数的外推，不是登记值）
    if floor is not None and total_gb is not None and floor > total_gb * _OFFLOAD_HIGH_WATER:
        reasons.append(
            f"按 {fr} 帧外推下限 {floor}GB > 总显存 {total_gb}GB × {_OFFLOAD_HIGH_WATER}"
            f" ⇒ 升级 sequential_offload")
        return _policy(MODE_SEQUENTIAL_OFFLOAD, chunk, quant, floor, vram, reasons)

    # 2c. 正常路径：model_offload（SVD 定稿结论 —— 又稳又快，见模块 docstring 反转史）
    if floor is not None:
        reasons.append(
            f"model_offload 下限估计 {floor}GB（{fr} 帧，实测拟合）在水位线内 ⇒ 整模型级 offload")
    else:
        reasons.append("无实测下限（未登记模型）⇒ 保守取 model_offload（与调优表默认一致）")
    if model_id == "svd-xt-i2v":
        reasons.append(
            "SVD 实测定稿：offload 全帧数开启（40.0s/4.66GB@5帧 vs 关 offload 42.5s/5.84GB，"
            "且 10 帧关 offload 必 WDDM 分页卡死 >600s）")
    return _policy(MODE_MODEL_OFFLOAD, chunk, quant, floor, vram, reasons)


def _policy(mode: str, chunk: int, quant: str, floor: Optional[float],
            vram: Optional[Dict[str, float]], reasons: List[str]) -> Dict[str, Any]:
    """组装返回 dict（单点组装，保证键集合稳定）。"""
    return {
        "mode": mode,
        "offload": mode != MODE_WHOLE_GPU,
        "decode_chunk_size": int(chunk),
        "quant": quant,
        "floor_gb": floor,
        "free_vram_gb": (vram or {}).get("free_gb"),
        "total_vram_gb": (vram or {}).get("total_gb"),
        "reasons": list(reasons),
        "planned_modes": list(PLANNED_MODES),
    }
