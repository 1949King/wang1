# -*- coding: utf-8 -*-
"""帧级语义镜头表（适配 A）—— 把"看懂"变成"可寻址"。

为什么需要这一层
----------------
``canvas_shot_vision.enrich_shot_table`` 已经能按 start/end 抽帧并解析景别/运镜/画面，
``media_perception.perceive`` 已经能拿场景切分 / ASR / 质量分。但两者的产出是**散落的
自然语言与分数**，决策层无法据此定位到帧 —— 于是 LLM 只能输出「把第 3 段剪短一点」，
最后又落回 ffmpeg 切片拼接（``llm_clipper.py`` 的现状）。

本模块做一次收拢：所有感知结果汇成带 ``frame_in/frame_out`` 的**结构化镜头表**，
坐标系直接复用 ``text_frame_map.map_sec_range_to_frames``（SAFE_WORD 半开区间），
不另造时间基准。模型从此只需要引用 ``shot_id``，**永不输出帧号**。

铁律
----
· 纯数据 + 纯函数，不抽帧、不联网、不碰时间线、不写撤销条目（可离线单测）。
· 感知失败如实记 ``source`` 与 ``warnings``，绝不填默认值伪装成模型判断。
· 一条 shot 的帧区间保证至少 1 帧宽（继承 B0 的零宽删除防线）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from app.core.text_frame_map import FrameBoundaryPolicy, map_sec_range_to_frames
except ImportError:  # 打包/副库路径兜底，与项目既有先例一致
    from core.text_frame_map import FrameBoundaryPolicy, map_sec_range_to_frames  # type: ignore

from .intent import EditIntent

__all__ = [
    "SemanticShot",
    "SemanticTable",
    "build_semantic_table",
    "compile_interval",
    "merge_intervals",
]

_SHOT_SIZE_FALLBACK = "中景"
_CAMERA_FALLBACK = "固定"


@dataclass(frozen=True)
class SemanticShot:
    """一个可被 EDL 寻址的镜头单元。时间基准 = 时间线绝对秒。"""

    shot_id: str
    timeline_in: float
    timeline_out: float
    frame_in: int
    frame_out: int                     # exclusive
    fps: float
    shot_size: str = _SHOT_SIZE_FALLBACK
    camera: str = _CAMERA_FALLBACK
    tone: str = "中性"
    description: str = ""
    asr_text: str = ""
    asr_words: Tuple[Dict[str, Any], ...] = ()
    quality_score: Optional[float] = None   # None = 没测，不填 70 基线
    highlight: bool = False
    vision_used: bool = False
    clip_id: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.timeline_out - self.timeline_in)

    def evidence(self) -> Dict[str, Any]:
        """复核用的证据指针：能定位到具体帧 / 具体 ASR 条目，可被证伪。"""
        return {
            "shot_id": self.shot_id,
            "frame_in": self.frame_in,
            "frame_out": self.frame_out,
            "fps": self.fps,
            "timeline_in": round(self.timeline_in, 4),
            "timeline_out": round(self.timeline_out, 4),
            "asr_text": self.asr_text,
            "quality_score": self.quality_score,
            "vision_used": self.vision_used,
        }

    def to_dict(self) -> Dict[str, Any]:
        d = self.evidence()
        d.update({
            "shot_size": self.shot_size,
            "camera": self.camera,
            "tone": self.tone,
            "description": self.description,
            "highlight": self.highlight,
            "clip_id": self.clip_id,
            "asr_words": [dict(w) for w in self.asr_words],
        })
        return d


@dataclass
class SemanticTable:
    """一次精剪任务的感知快照。"""

    video_path: str = ""
    fps: float = 30.0
    shots: List[SemanticShot] = field(default_factory=list)
    source: str = "heuristic"          # heuristic / local_vision / cloud_vision / mixed
    vision_model: str = ""
    warnings: List[str] = field(default_factory=list)

    def shot_by_id(self, shot_id: str) -> Optional[SemanticShot]:
        key = str(shot_id or "").strip()
        for s in self.shots:
            if s.shot_id == key:
                return s
        return None

    def to_llm_payload(self, intent: EditIntent) -> Dict[str, Any]:
        """给决策 LLM 的紧凑输入。1M 上下文模型可一次读完整片。

       刻意不带画面字节、不带 base64；只带可寻址的结构化语义 + 目标函数。
       """
        return {
            "intent": intent.to_dict(),
            "fps": self.fps,
            "source": self.source,
            "vision_model": self.vision_model,
            "warnings": list(self.warnings),
            "shots": [
                {
                    "shot_id": s.shot_id,
                    "timeline_in": round(s.timeline_in, 4),
                    "timeline_out": round(s.timeline_out, 4),
                    "frame_in": s.frame_in,
                    "frame_out": s.frame_out,
                    "shot_size": s.shot_size,
                    "camera": s.camera,
                    "description": s.description,
                    "asr_text": s.asr_text,
                    "quality_score": s.quality_score,
                    "highlight": s.highlight,
                }
                for s in self.shots
            ],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "video_path": self.video_path,
            "fps": self.fps,
            "source": self.source,
            "vision_model": self.vision_model,
            "warnings": list(self.warnings),
            "shots": [s.to_dict() for s in self.shots],
        }


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _pick_sec(row: Mapping[str, Any]) -> Tuple[float, float]:
    """兼容分镜表 / ASR / 字幕三种常见字段名，取不到就 0（不猜）。"""
    start = row.get("start", row.get("start_time", row.get("timeline_in", 0.0)))
    end = row.get("end", row.get("end_time", row.get("timeline_out", start)))
    return _as_float(start), _as_float(end)


def _collect_asr(
    segments: Iterable[Mapping[str, Any]],
    start: float,
    end: float,
) -> Tuple[str, Tuple[Dict[str, Any], ...]]:
    """按时间重叠把 ASR 条目挂到镜头上。重叠即收录（半开区间）。"""
    words: List[Dict[str, Any]] = []
    texts: List[str] = []
    for seg in segments or ():
        a, b = _pick_sec(seg)
        if b <= a or a >= end or b <= start:
            continue
        text = str(seg.get("text") or seg.get("word") or "").strip()
        if text:
            texts.append(text)
        words.append({"start": a, "end": b, "text": text})
    words.sort(key=lambda w: w["start"])
    return "".join(texts) if any("\u4e00" <= ch <= "\u9fff" for ch in "".join(texts)) else " ".join(texts), tuple(words)


def build_semantic_table(
    shots: Sequence[Mapping[str, Any]],
    *,
    fps: float = 30.0,
    asr_segments: Sequence[Mapping[str, Any]] = (),
    quality_by_shot: Optional[Mapping[str, float]] = None,
    source: str = "heuristic",
    vision_model: str = "",
    video_path: str = "",
    warnings: Sequence[str] = (),
) -> SemanticTable:
    """把已有感知结果收成帧级语义镜头表。**不抽帧、不联网、不改任何既有模块**。

    shots 形状与 ``canvas_shot_vision`` 的分镜表一致：
      ``{"start","end","shot","camera","tone","description","id"/"shot_id",...}``
    """
    table = SemanticTable(
        video_path=str(video_path or ""),
        fps=fps,
        source=source,
        vision_model=str(vision_model or ""),
        warnings=list(warnings),
    )
    qmap = dict(quality_by_shot or {})
    for idx, row in enumerate(shots or ()):
        a, b = _pick_sec(row)
        if b <= a:
            table.warnings.append(f"第 {idx} 镜时间区间无效（{a}~{b}），已跳过")
            continue
        fr = map_sec_range_to_frames(a, b, fps, FrameBoundaryPolicy.SAFE_WORD)
        sid = str(row.get("shot_id") or row.get("id") or f"s{idx + 1:03d}")
        asr_text, asr_words = _collect_asr(asr_segments, fr.in_sec, fr.out_sec)
        q = qmap.get(sid)
        score: Optional[float] = None
        if q is not None:
            try:
                score = float(q)
            except (TypeError, ValueError):
                score = None
        table.shots.append(SemanticShot(
            shot_id=sid,
            timeline_in=fr.in_sec,
            timeline_out=fr.out_sec,
            frame_in=fr.frame_in,
            frame_out=fr.frame_out,
            fps=fr.fps,
            shot_size=str(row.get("shot") or row.get("shot_size") or _SHOT_SIZE_FALLBACK),
            camera=str(row.get("camera") or _CAMERA_FALLBACK),
            tone=str(row.get("tone") or "中性"),
            description=str(row.get("description") or ""),
            asr_text=asr_text,
            asr_words=asr_words,
            quality_score=score,
            highlight=bool(row.get("highlight")) or (score is not None and score >= 80.0),
            vision_used=bool(row.get("vision") or row.get("vision_used")),
            clip_id=str(row.get("clip_id") or ""),
        ))
    return table


def compile_interval(
    shot: SemanticShot,
    op: Mapping[str, Any],
    intent: EditIntent,
    *,
    track: int = 0,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """把一条模型决策编译成 ``rough_cut_chain.apply()`` 认识的 interval。

    **模型只给 shot_id / portion / sec / reason，坐标一律由本函数从语义表算**，
    这是防止幻觉坐标改坏时间线的关键防线。

    op 形状::
        {"op":"ripple_delete","shot_id":"s003","portion":"all"|"head"|"tail",
         "sec":1.2,"reason":"...","evidence":{...}}
    """
    portion = str(op.get("portion") or "all").lower()
    if portion not in ("all", "head", "tail"):
        return None, f"非法 portion={portion!r}（可选 all/head/tail）"
    a, b = shot.timeline_in, shot.timeline_out
    if portion == "head":
        b = min(b, a + max(0.0, _as_float(op.get("sec"))))
    elif portion == "tail":
        a = max(a, b - max(0.0, _as_float(op.get("sec"))))
    if b <= a:
        return None, f"镜头 {shot.shot_id} 编译出零宽区间，已丢弃"
    if intent.is_protected(a, b):
        return None, f"镜头 {shot.shot_id} 命中禁改区间，已拒绝"
    if shot.clip_id and intent.is_protected_clip(shot.clip_id):
        return None, f"镜头 {shot.shot_id} 所属片段 {shot.clip_id} 被保护，已拒绝"
    for line in intent.keep_lines:
        if line and line in shot.asr_text:
            return None, f"镜头 {shot.shot_id} 含必须保留台词「{line}」，已拒绝"
    return {
        "timeline_in": round(a, 4),
        "timeline_out": round(b, 4),
        "track": int(track or 0),
        "shot_id": shot.shot_id,
        "reason": str(op.get("reason") or ""),
        "evidence": {**shot.evidence(), **(dict(op.get("evidence") or {}))},
    }, None


def merge_intervals(
    intervals: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """合并同轨重叠区间，避免一次决策里重复删除造成时长预测失真。

    只合并坐标，保留先出现的 reason/evidence（决策依据不丢）。
    """
    by_track: Dict[int, List[Dict[str, Any]]] = {}
    for iv in intervals:
        t = int(iv.get("track", 0) or 0)
        by_track.setdefault(t, []).append(dict(iv))
    out: List[Dict[str, Any]] = []
    for t in sorted(by_track):
        rows = sorted(by_track[t], key=lambda r: float(r["timeline_in"]))
        for row in rows:
            if out and out[-1]["track"] == t and float(row["timeline_in"]) <= float(out[-1]["timeline_out"]):
                prev = out[-1]
                prev["timeline_out"] = max(float(prev["timeline_out"]), float(row["timeline_out"]))
                if row.get("reason") and not prev.get("reason"):
                    prev["reason"] = row["reason"]
            else:
                out.append(row)
    return out
