# -*- coding: utf-8 -*-
"""说话人分离（speaker diarization）—— 给 whisper 的 segments 打上 `speaker` 标签。

为什么需要（2026-10-09，刀 T1）
==============================
`whisper_asr.transcribe()` 只能转写"说了什么"，**不知道"谁说的"**。
短剧多角色场景里，没有说话人归属，就无法做"按角色配音 / 一键换词重配"（T4 目标态）。
本模块在 whisper 的 segment 之上**附加 `speaker` 字段**，不改动、不破坏原有字段。

方案与诚实边界（本模块的红线）
==============================
· 首选 **FunASR**（达摩院）：`paraformer-zh` 中文 ASR + `cam++` 说话人模型，
  走 **ModelScope** 下载、**本地推理**（素材不出域）。
· 依赖 / 模型不可用时**诚实失败**：返回**不带 speaker 的原始 segments**，
  并在 meta 里说明原因 —— **绝不伪造 `speaker_00/01` 这类假标签**，
  否则会污染下游多角色配音（把"无依据"当成"已分离"）。

纯逻辑与模型分离（可测性）
========================
· `assign_speakers()` 是**纯函数**（时间区间重叠 → 取重叠最长的说话人投票），可单测；
· `diarize()` 是主入口（检测 funasr → 真分离 → assign → 返回带 speaker 的 segments）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# FunASR 用到的两个 ModelScope 模型 id（模型不在 .gitignore 的 models/ 里，按需下载）
MODEL_ASR = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
MODEL_SPK = "iic/speech_campplus_speaker-diarization_common"

_DIAR_MODEL: Optional[Any] = None     # 懒加载缓存

# ── 接入统一模型仓库（V4.41.7 升级）──────────────────────────────
# 为什么：此前 _DIAR_MODEL 是模块级私缓存，加载前**不查显存**、也不会在
# 别的模型需要显存时被让位。接入 model_registry 后：
#   · acquire 前查显存水位（不足 ⇒ 诚实失败，不 OOM）；
#   · 与 CosyVoice2/MuseTalk 等共享同一套 LRU 驱逐 —— 8GB 卡上多模型轮流用。
_MODEL_ID = "funasr-campplus-diar"
_VRAM_MB = 2048  # cam++ 说话人模型峰值显存预估（保守值）


def _shared_registry():
    """拿全局共享的 ModelRegistry（懒初始化，避免 import 环）。"""
    from app.core.ai.model_registry import ModelSpec
    global _DIAR_MODEL
    reg = _get_or_create_registry()
    if not reg.is_registered(_MODEL_ID):
        reg.register(ModelSpec(
            model_id=_MODEL_ID,
            vram_mb=_VRAM_MB,
            loader=_raw_load_diar_model,
            release=lambda m: None,   # Python GC + torch 显存由进程管理
        ))
    return reg


_REGISTRY = None


def _get_or_create_registry():
    global _REGISTRY
    if _REGISTRY is None:
        from app.core.ai.model_registry import ModelRegistry
        _REGISTRY = ModelRegistry()
    return _REGISTRY


def _raw_load_diar_model():
    """真正 import funasr 并加载 cam++ 模型（供 registry 的 loader 调用）。"""
    from funasr import AutoModel
    return AutoModel(model=MODEL_SPK)


def funasr_available() -> bool:
    """FunASR 依赖是否可用（**只检测 import，不下载模型**）。"""
    try:
        import funasr  # noqa: F401
        return True
    except Exception:
        return False


def unavailable_reason() -> str:
    """诚实报告为什么不可用（给用户看的话）。"""
    if funasr_available():
        return ("funasr 已安装，但说话人模型可能未下载。"
                "首次调用会从 ModelScope 拉取（paraformer-zh + cam++，约 1–2GB），"
                "请保证网络可用。")
    return ("缺少本地说话人分离依赖（funasr）。"
            "安装：`pip install funasr`，模型首次调用自动从 ModelScope 下载。"
            "在装好之前，本功能**诚实降级**为不带说话人的转写，不会伪造标签。")


def assign_speakers(segments: List[Dict], ranges: List[Dict]) -> List[Dict]:
    """**纯函数**：把说话人时间区间映射到 segments，给每段加 `speaker` 字段。

    规则：
      · 对每个 segment，找出与它**时间重叠**的说话人区间；
      · 取**重叠时长最大**的那个（投票），写入 `speaker`；
      · 重叠时长并列最大 ⇒ 取**重叠比例**更高者（更公平的平票判定，2026-10-09 优化：
        旧版平票时固定取"先出现的区间"，顺序一变结果就变，不稳定）；
      · 完全无重叠 → `speaker=None`（诚实留空，**不猜**）。

    性能（2026-10-09 优化）：扫描线 O((n+m)·log(n+m))，替代旧版 O(n×m)。
    长视频（如 2000 段 × 5000 区间）旧版要千万次比较；扫描线只需排序一次。

    Args:
        segments: whisper 的 `[{"start", "end", "text", ...}]`
        ranges:   diarization 的 `[{"start", "end", "speaker"}]`
    Returns:
        原 segments 的浅拷贝，每项多一个 `speaker`（str 或 None）。
    """
    out: List[Dict] = []
    # 预清洗 ranges（一次），非法区间直接剔除
    clean: List[tuple] = []
    for r in ranges or []:
        try:
            r0 = float(r.get("start", 0.0) or 0.0)
            r1 = float(r.get("end", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if r1 > r0:
            clean.append((r0, r1, r.get("speaker")))
    clean.sort(key=lambda x: x[0])
    ends_sorted = [c[1] for c in clean]      # 一次构建（旧版在循环内重建，浪费）

    for seg in segments or []:
        item = dict(seg)
        try:
            s0 = float(item.get("start", 0.0) or 0.0)
            s1 = float(item.get("end", 0.0) or 0.0)
        except (TypeError, ValueError):
            item["speaker"] = None
            out.append(item)
            continue

        # 扫描线：二分定位第一个 end > s0 的区间，向后扫到 start > s1 为止
        # （clean 已按 start 排序；对于说话人区间这种几乎不重叠的数据，
        #   命中窗口通常只有 1–2 个，循环体近似 O(1)）
        import bisect
        i = bisect.bisect_left(ends_sorted, s0)   # 第一个 r1 > s0 的候选
        best_spk: Optional[str] = None
        best_overlap = 0.0
        best_ratio = 0.0
        while i < len(clean):
            r0, r1, spk = clean[i]
            if r0 >= s1:
                break
            overlap = min(s1, r1) - max(s0, r0)
            if overlap > 0:
                ratio = overlap / (r1 - r0)  # 相对该区间自身的占比（V4.41.7 修优先级 bug）
                if (overlap > best_overlap
                        or (overlap == best_overlap and ratio > best_ratio)):
                    best_overlap = overlap
                    best_ratio = ratio
                    best_spk = spk
            i += 1
        item["speaker"] = best_spk if best_overlap > 0 else None
        out.append(item)
    return out


def _load_diar_model():
    """懒加载 FunASR 说话人分离模型（V4.41.7 起走 model_registry：水位守卫 + LRU）。

    显存不足时返回 None（diarize_ranges 据此诚实降级），**不再直接 OOM**。
    """
    global _DIAR_MODEL
    if _DIAR_MODEL is not None:
        return _DIAR_MODEL
    if not funasr_available():
        return None
    reg = _shared_registry()
    result = reg.acquire(_MODEL_ID)
    if not result.ok:
        logger.warning("[speaker_diarize] 模型加载失败（显存水位守卫）: %s", result.reason)
        return None
    _DIAR_MODEL = result.model
    return _DIAR_MODEL
    return _DIAR_MODEL


def diarize_ranges(audio_path: str) -> List[Dict]:
    """用 FunASR cam++ 提取说话人时间区间 `[{"start","end","speaker"}]`。

    模型/依赖不可用 ⇒ 返回空列表（调用方据此诚实降级）。
    """
    if not funasr_available():
        return []
    try:
        model = _load_diar_model()
        res = model.generate(input=audio_path)
        if not res:
            return []
        first = res[0]
        ranges: List[Dict] = []
        for item in first.get("sentence_info", []):
            ranges.append({
                "start": float(item.get("start", 0.0) or 0.0),
                "end": float(item.get("end", 0.0) or 0.0),
                "speaker": str(item.get("spk", "speaker")),
            })
        return ranges
    except Exception as e:
        logger.warning("[speaker_diarize] 说话人分离失败: %s", e)
        return []


def diarize(video_path: str, segments: List[Dict]) -> Dict[str, Any]:
    """主入口：给 whisper segments 附加说话人标签（**诚实失败**）。

    Returns:
        {
          "ok": bool,
          "segments": [原 segments + speaker 字段],
          "available": bool,
          "reason": str,          # 不可用时说明原因
          "speaker_count": int,   # 分离出的说话人数（ok 时）
        }
    """
    if not funasr_available():
        return {"ok": False, "segments": [dict(s, speaker=None) for s in segments],
                "available": False, "reason": unavailable_reason(),
                "speaker_count": 0}
    ranges = diarize_ranges(video_path)
    if not ranges:
        return {"ok": False, "segments": [dict(s, speaker=None) for s in segments],
                "available": True, "reason": "说话人分离未产出结果（模型或音频问题）",
                "speaker_count": 0}
    segs = assign_speakers(segments, ranges)
    speakers = {s.get("speaker") for s in segs if s.get("speaker")}
    return {"ok": True, "segments": segs, "available": True,
            "reason": "", "speaker_count": len(speakers)}
