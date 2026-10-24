# -*- coding: utf-8 -*-
"""Media Engine 统一感知门面（§6.9 · 感知能力收拢，2026-10-18）
====================================================

解决的问题：感知能力散落各处——场景切分在 ``ai_editing_assistant.SceneAnalyzer``、
转写在 ``ai.whisper_asr``、五维打分在 ``five_dimension_scorer``、OCR 内嵌在
``copywriting_module`` 里、人脸只有修复（``neural.face_restore``）没有检测。
调用方（Agent / 粗剪链 / 画布端点）想「看看这个素材」得挨个找入口、各写各的
异常处理，失败还经常静默。

本模块是**薄门面**（照 `ai/guards.py` 门面先例：只分发、不重写算法）：
  - ``list_capabilities()`` —— 能力清单自描述（wired / not_wired 如实标注）；
  - ``perceive(video_path, kinds=...)`` —— 统一入口分发到既有实现，
    单能力失败**绝不**拖垮其它能力，失败原因如实回传；
  - ``record_perception(video_path, result)`` —— 感知结果写进
    ``gen_task_registry`` AssetNode 的 ``perception`` 字段（§6.9 统一数据模型
    的感知落点，e4 预留的接口由本模块首次接通）。

诚实红线（对齐 §8）
-------------------
1. **不造假能力**：face/ocr/silence/vision 当前没有可复用的纯文件级实现，
   一律标 ``not_wired`` 并说明真实原因，绝不拿近似实现冒充。
2. **空结果≠成功**：``whisper_asr.transcribe`` 失败返回空列表、门面按
   契约如实报 ``ok=False``（无法区分「没说话」与「模型不可用」时，宁可保守）。
3. **门面绝不抛异常**：所有失败进 ``results[kind]["error"]``，
   调用方永远拿到结构完整的 dict。

分发去向（唯一真相源，勿在别处复制这些调用形态）
------------------------------------------------
  scenes  → ``ai_editing_assistant.SceneAnalyzer().analyze_scenes(video_path=)``
            （主链路口径：capability_handlers / canvas_aigc 同用它）
  asr     → ``ai.whisper_asr.transcribe(path, language=)``
  quality → ``five_dimension_scorer.five_dimension_scorer``
            （extract_features_from_clip → score → to_dict；clip_meta 缺省时
            以 ``{"path": video_path}`` 起算，估算维度由评分器如实标注）
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 能力登记表（kind 为唯一键；status 只有 wired/not_wired 两态，诚实二值）
_CAPABILITIES: List[Dict[str, Any]] = [
    {"kind": "scenes", "title": "场景/镜头切分", "status": "wired",
     "impl": "ai_editing_assistant.SceneAnalyzer",
     "note": "PySceneDetect 优先，帧差法降级（既有实现自带）"},
    {"kind": "asr", "title": "语音转写（带时间戳）", "status": "wired",
     "impl": "ai.whisper_asr.transcribe",
     "note": "faster-whisper / openai-whisper 后端自动探测"},
    {"kind": "quality", "title": "五维质量打分", "status": "wired",
     "impl": "five_dimension_scorer",
     "note": "clip_meta 缺省以文件路径起算；估算维度如实标注"},
    {"kind": "face", "title": "人脸检测", "status": "not_wired",
     "impl": "", "note": "现仅有 GFPGAN 人脸**修复**（neural.face_restore），"
     "无可复用的人脸检测实现"},
    {"kind": "ocr", "title": "画面文字识别", "status": "not_wired",
     "impl": "", "note": "easyocr 调用内嵌在 copywriting_module，"
     "未抽成可复用入口，不冒充门面能力"},
    {"kind": "silence", "title": "静音/语气词检测", "status": "not_wired",
     "impl": "", "note": "filler_silence_detect 依赖时间线 ClipContext，"
     "不是纯文件级感知，接入需先解耦"},
    {"kind": "vision", "title": "镜头语言视觉解析", "status": "not_wired",
     "impl": "", "note": "canvas_shot_vision 需要既有镜头表作输入，"
     "属拉片管线环节而非单文件感知"},
]

_WIRED = tuple(c["kind"] for c in _CAPABILITIES if c["status"] == "wired")


def list_capabilities() -> List[Dict[str, Any]]:
    """能力清单自描述（供 UI / Agent / 调试）。返回副本，勿改内部表。"""
    return [dict(c) for c in _CAPABILITIES]


# ────────────── 各能力分发（懒导入：门面加载绝不拖垮启动） ──────────────

def _run_scenes(video_path: str) -> List[Dict[str, Any]]:
    """场景切分：SceneAnalyzer 主链路口径，SceneAnalysis → 纯 dict。"""
    try:
        from app.core.ai_editing_assistant import SceneAnalyzer
    except ImportError:  # 项目先例：兼容非包内运行
        from core.ai_editing_assistant import SceneAnalyzer  # type: ignore
    scenes = SceneAnalyzer().analyze_scenes(video_path=video_path)
    out: List[Dict[str, Any]] = []
    for s in scenes or []:
        st = getattr(s, "scene_type", None)
        out.append({
            "start_time": float(getattr(s, "start_time", 0.0) or 0.0),
            "end_time": float(getattr(s, "end_time", 0.0) or 0.0),
            "scene_type": getattr(st, "value", str(st or "")),
            "emotion": str(getattr(s, "emotion", "") or ""),
            "confidence": float(getattr(s, "confidence", 0.0) or 0.0),
            "description": str(getattr(s, "description", "") or ""),
            "suggested_actions": list(getattr(s, "suggested_actions", None) or []),
        })
    return out


def _run_asr(video_path: str, language: str) -> List[Dict[str, Any]]:
    """转写：whisper_asr 契约「失败返回空列表」→ 空列表如实报不可用。"""
    try:
        from app.core.ai.whisper_asr import transcribe
    except ImportError:
        from ai.whisper_asr import transcribe  # type: ignore
    segments = transcribe(video_path, language=language) or []
    if not segments:
        raise RuntimeError("转写无结果（后端/模型不可用或音频无人声，无法区分）")
    return list(segments)


def _run_quality(video_path: str, clip_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """五维打分：clip_meta 缺省以文件路径起算（估算维度由评分器如实标注）。"""
    try:
        from app.core.five_dimension_scorer import five_dimension_scorer
    except ImportError:
        from core.five_dimension_scorer import five_dimension_scorer  # type: ignore
    meta = dict(clip_meta) if isinstance(clip_meta, dict) else {}
    meta.setdefault("path", video_path)
    features = five_dimension_scorer.extract_features_from_clip(meta)
    return five_dimension_scorer.score(features).to_dict()


# ────────────── 统一入口 ──────────────

def perceive(video_path: str, kinds: Optional[List[str]] = None, *,
             clip_meta: Optional[Dict[str, Any]] = None,
             language: str = "zh") -> Dict[str, Any]:
    """对单个媒体文件跑感知能力，返回结构完整、**绝不抛异常**的结果。

    ``kinds`` 缺省 = 全部 wired 能力；指定 not_wired 能力会得到
    ``ok=False + error="能力未接入"``（诚实拒绝而非静默跳过）。

    返回形状::
        {"path": ..., "file_exists": bool,
         "results": {kind: {"ok": bool, "data": ..., "error": str}}}
    """
    video_path = str(video_path or "").strip()
    requested = list(kinds) if kinds else list(_WIRED)
    file_exists = bool(video_path) and os.path.isfile(video_path)
    results: Dict[str, Any] = {}

    for kind in requested:
        entry: Dict[str, Any] = {"ok": False, "data": None, "error": ""}
        cap = next((c for c in _CAPABILITIES if c["kind"] == kind), None)
        if cap is None:
            entry["error"] = f"未知能力：{kind}"
        elif cap["status"] != "wired":
            entry["error"] = f"能力未接入（{cap['note']}）"
        elif not file_exists:
            entry["error"] = "文件不存在"
        else:
            try:
                if kind == "scenes":
                    entry["data"] = _run_scenes(video_path)
                elif kind == "asr":
                    entry["data"] = _run_asr(video_path, language)
                else:  # quality
                    entry["data"] = _run_quality(video_path, clip_meta)
                entry["ok"] = True
            except Exception as e:  # 单能力失败绝不外溢（门面纪律）
                logger.debug("[perception] %s 失败：%s", kind, e, exc_info=True)
                entry["error"] = f"{type(e).__name__}: {e}"
        results[kind] = entry

    return {"path": video_path, "file_exists": file_exists, "results": results}


# ────────────── 感知落点：AssetNode.perception ──────────────

def record_perception(video_path: str, result: Dict[str, Any], *,
                      asset_id: str = "") -> bool:
    """把 perceive 结果中 ok 的能力数据写入 AssetNode.perception。

    血缘优先：显式 ``asset_id`` > 按路径反查既有资产。
    查不到资产 ⇒ 返回 False（**不造无主记录**，对齐 gen_task_registry 纪律）。
    持久化失败由账本内部吞掉，本函数只如实回传是否命中资产。
    """
    try:
        from app.core.gen_task_registry import get_store
    except ImportError:
        from core.gen_task_registry import get_store  # type: ignore
    if not isinstance(result, dict):
        return False
    try:
        store = get_store()
        rec = None
        if asset_id:
            rec = store.get_asset(str(asset_id).strip())
        if rec is None:
            rec = store.find_asset_by_path(str(result.get("path") or video_path))
        if rec is None:
            logger.debug("[perception] 无对应资产，感知不落账：%s", video_path)
            return False
        payload = {k: v["data"] for k, v in (result.get("results") or {}).items()
                   if isinstance(v, dict) and v.get("ok") and v.get("data") is not None}
        if not payload:
            return False
        store.record_asset(rec["asset_id"], path=rec.get("path", ""),
                           perception=payload)
        return True
    except Exception:
        logger.debug("[perception] 感知落账失败（不阻断主链路）", exc_info=True)
        return False
