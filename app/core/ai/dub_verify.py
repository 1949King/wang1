# -*- coding: utf-8 -*-
"""配音听写回环验证（2026-10-15，配音一致性方案 P1①）

解决什么
========
用户痛点①：AI 生成的配音「发音和字幕/字对不上」，而且**经常性**出现。
本模块把「说出来的到底是不是那行字」变成**可测量**的相似度，低于阈值**一律红标**，
绝不静默放行（同 YuE 诚实降级纪律：宁可红标，不做假成功）。

怎么做（全部离线、确定性）
========================
1. 用 `whisper_asr.transcribe(audio_path, word_timestamps=True)` 听配音音频 → 得到
   **实际说出来的文本**（音 → 字），带词级时间戳；
2. 与**期望台词**做**拼音级**归一化比对 —— 用 `pinyin_dict.annotate()` 把两边都转成
   带声调拼音序列，再用 `difflib.SequenceMatcher` 算相似度。拼音级比对能区分
   「同音不同字」（多音字/同音字，发音其实是对的）与「真·读错音」。

诚实边界
========
- ASR 组件（faster-whisper/openai-whisper）未装 ⇒ `verdict="unavailable"` + 人话安装说明，
  **不伪造相似度**；
- 音频不存在/无声 ⇒ `verdict="error"`；
- 拼音库不可用 ⇒ 退化为**字符级**比对（仍给相似度，但 `normalized_by="char"` 明示精度下降）。
"""
from __future__ import annotations

import logging
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# 判定阈值（拼音级相似度）。低于 warn 线一律 fail ⇒ 前端红标。
PASS_THRESHOLD = 0.85
WARN_THRESHOLD = 0.60

# 非内容字符（标点/空白/符号）：归一化时剔除，避免「，」影响相似度
_NOISE_RE = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)


def _norm_tokens(text: str) -> tuple:
    """把文本归一成**拼音 token 序列**（失败退化为字符 token 序列）。

    Returns: (tokens: List[str], normalized_by: str)
    """
    raw = text or ""
    try:
        from app.core.ai.pinyin_dict import annotate, is_available

        ready, _ = is_available()
        if ready:
            res = annotate(raw)
            pinyin_list = res.get("pinyin_list") or []
            toks = [str(x) for x in pinyin_list if str(x).strip()]
            if toks:
                return toks, "pinyin"
    except Exception as exc:  # 拼音库异常不应阻断验证
        logger.debug("[dub_verify] 拼音归一化失败，退化字符级: %s", exc)
    # 退化：按字符（只保留字词，去标点/空白）
    return list(_NOISE_RE.sub("", raw)), "char"


def _similarity(a: str, b: str) -> float:
    """拼音/字符 token 序列相似度（0~1）。两边都空 ⇒ 0（不给"看起来成功"的分）。"""
    ta, _ = _norm_tokens(a)
    tb, _ = _norm_tokens(b)
    if not ta or not tb:
        return 0.0
    return round(SequenceMatcher(None, ta, tb).ratio(), 4)


def verify_dubbing(
    audio_path: str,
    expected_text: str,
    language: str = "zh",
    model_size: str = "base",
) -> Dict[str, Any]:
    """对一段配音音频做听写回环验证（**不落盘、不改文件**）。

    Args:
        audio_path: 配音音频文件路径。
        expected_text: 期望台词（剧本原句）。
        language: 识别语言，默认中文。
        model_size: Whisper 模型大小（tiny/base/small/medium/large）。

    Returns:
        {
          "available": bool,          # ASR 是否真的跑起来
          "verdict": "pass"|"warn"|"fail"|"unavailable"|"error",
          "similarity": float,        # 拼音级相似度 0~1
          "normalized_by": "pinyin"|"char",
          "asr_text": str,            # **实际听到的**（音→字）
          "expected_text": str,
          "word_timestamps": [...],   # 词级时间戳（供字幕强制对齐复用）
          "red_flag": bool,           # True = 需要人工复核（warn/fail/error）
          "reason": str,              # 人话说明
        }
    """
    result: Dict[str, Any] = {
        "available": False,
        "verdict": "error",
        "similarity": 0.0,
        "normalized_by": "pinyin",
        "asr_text": "",
        "expected_text": expected_text or "",
        "word_timestamps": [],
        "red_flag": True,
        "reason": "",
    }
    if not audio_path or not os.path.isfile(audio_path):
        result["reason"] = "音频文件不存在"
        return result

    try:
        from app.core.ai import whisper_asr
    except ImportError:
        from core.ai import whisper_asr  # type: ignore

    if not whisper_asr.is_available():
        result["verdict"] = "unavailable"
        result["reason"] = whisper_asr.unavailable_reason()
        return result

    segments = whisper_asr.transcribe(
        audio_path, model_size=model_size, language=language, word_timestamps=True
    )
    if not segments:
        result["verdict"] = "unavailable"
        result["reason"] = "语音识别未返回结果（模型不可用或音频无声）"
        return result

    asr_text = "".join(str(s.get("text") or "") for s in segments).strip()
    words: List[Dict[str, Any]] = []
    for s in segments:
        for w in (s.get("words") or []):
            words.append({"text": w.get("text", ""), "start": w.get("start", 0.0), "end": w.get("end", 0.0)})

    # 归一化口径记录（拼音 vs 字符），便于 UI 说明精度
    _, normalized_by = _norm_tokens("探测")
    sim = _similarity(asr_text, expected_text)

    if sim >= PASS_THRESHOLD:
        verdict = "pass"
        reason = f"发音与台词一致（相似度 {sim:.2f}）"
    elif sim >= WARN_THRESHOLD:
        verdict = "warn"
        reason = f"发音基本一致但有偏差（相似度 {sim:.2f}），建议人工复核"
    else:
        verdict = "fail"
        reason = f"发音与台词明显不符（相似度 {sim:.2f}），**需要重配或修正**"

    result.update({
        "available": True,
        "verdict": verdict,
        "similarity": sim,
        "normalized_by": normalized_by,
        "asr_text": asr_text,
        "word_timestamps": words,
        "red_flag": verdict != "pass",
        "reason": reason,
    })
    logger.info("[dub_verify] verdict=%s sim=%.2f audio=%s", verdict, sim, os.path.basename(audio_path))
    return result


def transcribe_for_subtitles(
    audio_path: str,
    language: str = "zh",
    model_size: str = "base",
) -> List[Dict[str, Any]]:
    """从**音频**生成字幕 segments（音 → 字，**禁止用剧本回填**）。

    P1③ 的字幕真相源：TTS 配音的字幕时间轴必须来自**实际音频的 ASR 结果**，
    而不是剧本文本的估算排布 —— 剧本只是"意图"，音频才是"真相"。

    Returns: `[{"start", "end", "text"}]`；ASR 不可用/无声时返回空列表（调用方如实降级）。
    """
    try:
        from app.core.ai import whisper_asr
    except ImportError:
        from core.ai import whisper_asr  # type: ignore

    if not audio_path or not os.path.isfile(audio_path) or not whisper_asr.is_available():
        return []
    try:
        segments = whisper_asr.transcribe(
            audio_path, model_size=model_size, language=language, word_timestamps=False
        )
    except Exception as exc:
        logger.warning("[dub_verify] 字幕转写失败 %s: %s", audio_path, exc)
        return []
    return [
        {"start": float(s.get("start") or 0.0), "end": float(s.get("end") or 0.0),
         "text": str(s.get("text") or "").strip()}
        for s in segments
        if str(s.get("text") or "").strip()
    ]
