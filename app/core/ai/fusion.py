"""置信度融合器（三分架构，规格书第八篇 §42，V4.38.0 切片⑦）
====================================================================
规格书铁律：**禁止通用张量加权平均**。三类介质各有独立融合算子：

- **文本**：字段锁域 + 命名空间仲裁——被锁字段只准来自其锁域；
  未锁字段按命名空间优先级（或逐字段质量分）仲裁；
- **视频**：关键帧择优 + 片段时序拼接——按时间槽逐段选更优来源，
  拼接保持时序（本模块产出**拼接计划**，实际 ffmpeg 拼接由调用方执行）；
- **音频**：轨道分离混音 + 响度对齐——按角色（人声/配乐/音效）分配
  增益并归一化，产出**混音计划**（实际混音由调用方执行）。

**Provenance 全程保留**：每个融合结果带溯源字段（字段/片段/轨道级来源），
支持问题回溯（§42 末条）。

设计纪律：纯模块、不 import app 包、异常不抛；所有算子返回
``(result, provenance)`` 二元组。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.core.ai.fusion")

# 音频轨道角色的基础增益（人声优先，配乐垫底，音效点缀）
_ROLE_GAIN = {"voice": 1.0, "music": 0.5, "sfx": 0.7, "other": 0.6}


def _stamp() -> float:
    return time.time()


# ═══════════════════════════════════════════════════════════
# 文本：字段锁域 + 命名空间仲裁
# ═══════════════════════════════════════════════════════════

def fuse_text(local_fields: Optional[Dict[str, Any]] = None,
              cloud_fields: Optional[Dict[str, Any]] = None,
              locks: Optional[Dict[str, str]] = None,
              namespace_priority: Tuple[str, ...] = ("cloud", "local"),
              field_scores: Optional[Dict[str, Dict[str, float]]] = None
              ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """文本融合：字段锁域 + 命名空间仲裁。

    参数：
        locks: {字段: 锁域} —— 锁域∈{"local","cloud"}，被锁字段**只准**取该来源
               （如「角色名」锁本地设定、「台词」锁云端润色），仲裁无权翻越；
        namespace_priority: 未锁字段的默认仲裁顺序（前者优先）；
        field_scores: {字段: {"local": q, "cloud": q}} —— 给了就按分择优，
               优先于 namespace_priority（置信度融合的「置信度」入口）。

    Returns:: (merged, provenance)
        provenance["fields"] = {字段: {"source":…, "rule": "lock|score|priority|only"}}
    """
    lf = dict(local_fields) if isinstance(local_fields, dict) else {}
    cf = dict(cloud_fields) if isinstance(cloud_fields, dict) else {}
    lk = dict(locks) if isinstance(locks, dict) else {}
    fs = dict(field_scores) if isinstance(field_scores, dict) else {}
    sources = {"local": lf, "cloud": cf}

    merged: Dict[str, Any] = {}
    prov_fields: Dict[str, Dict[str, str]] = {}
    for key in set(lf) | set(cf):
        lock = lk.get(key)
        if lock in sources and key in sources[lock]:
            merged[key] = sources[lock][key]
            prov_fields[key] = {"source": lock, "rule": "lock"}
            continue
        scores = fs.get(key)
        if isinstance(scores, dict) and key in lf and key in cf:
            ql = float(scores.get("local", 0.0))
            qc = float(scores.get("cloud", 0.0))
            pick = "local" if ql >= qc else "cloud"
            merged[key] = sources[pick][key]
            prov_fields[key] = {"source": pick, "rule": "score"}
            continue
        picked = False
        for ns in namespace_priority:
            if key in sources.get(ns, {}):
                merged[key] = sources[ns][key]
                prov_fields[key] = {"source": ns,
                                    "rule": "priority" if (key in lf and key in cf)
                                    else "only"}
                picked = True
                break
        if not picked:  # 理论上到不了（并集遍历），防御
            continue
    provenance = {"medium": "text", "mode": "D", "fused_at": _stamp(),
                  "fields": prov_fields,
                  "locks": {k: v for k, v in lk.items()}}
    return merged, provenance


# ═══════════════════════════════════════════════════════════
# 视频：关键帧择优 + 片段时序拼接
# ═══════════════════════════════════════════════════════════

def plan_video_fusion(segments: List[Dict[str, Any]],
                      prefer: str = "cloud") -> Tuple[List[Dict[str, Any]],
                                                      Dict[str, Any]]:
    """视频融合：**拼接计划**（关键帧择优 + 时序拼接的调度层）。

    输入每个时间槽的候选段::
        {"slot": int, "source": "local"|"cloud", "path": str,
         "quality": float(0~1), "duration": float, "keyframe_ok": bool}

    规则：
      1. 同槽多来源 → 选 quality 高者（**关键帧择优**：keyframe_ok=False
         的来源质量分先打 7 折——首尾帧崩坏的片段即便整体分高也要降权）；
      2. 质量差 < 0.05 时让给 ``prefer``（稳定偏好，避免逐槽抖源）；
      3. 输出按 slot 升序（**片段时序拼接**）；实际 ffmpeg concat 由调用方
         按计划执行——本函数纯决策，不碰文件。

    Returns:: (plan, provenance)
        plan = [{"slot", "source", "path", "duration"}...]
    """
    by_slot: Dict[int, List[Dict[str, Any]]] = {}
    for seg in segments or []:
        try:
            slot = int(seg.get("slot", 0))
        except (TypeError, ValueError):
            continue
        by_slot.setdefault(slot, []).append(seg)

    plan: List[Dict[str, Any]] = []
    prov_segments: List[Dict[str, Any]] = []
    for slot in sorted(by_slot):
        cands = by_slot[slot]
        scored = []
        for c in cands:
            q = float(c.get("quality", 0.5))
            if not c.get("keyframe_ok", True):
                q *= 0.7  # 关键帧择优：帧坏降权
            scored.append((q, str(c.get("source", "")), c))
        scored.sort(key=lambda t: (-t[0], t[1]))
        best_q, _, best = scored[0]
        # 稳定偏好：差距 <0.05 且 prefer 来源在场 → 让给 prefer；
        # 但关键帧崩坏的候选**不享受**让步（关键帧择优优先于稳定偏好）
        for q, src, c in scored:
            if src == prefer and c.get("keyframe_ok", True) and best_q - q < 0.05:
                best, best_q = c, q
                break
        plan.append({"slot": slot, "source": str(best.get("source", "")),
                     "path": str(best.get("path", "")),
                     "duration": float(best.get("duration", 0.0))})
        prov_segments.append({
            "slot": slot, "chosen": str(best.get("source", "")),
            "candidates": [{"source": str(c.get("source", "")),
                            "quality": float(c.get("quality", 0.5)),
                            "keyframe_ok": bool(c.get("keyframe_ok", True))}
                           for c in cands]})
    provenance = {"medium": "video", "mode": "D", "fused_at": _stamp(),
                  "prefer": prefer, "segments": prov_segments}
    return plan, provenance


# ═══════════════════════════════════════════════════════════
# 音频：轨道分离混音 + 响度对齐
# ═══════════════════════════════════════════════════════════

def plan_audio_mix(tracks: List[Dict[str, Any]],
                   target_peak: float = 0.9) -> Tuple[List[Dict[str, Any]],
                                                      Dict[str, Any]]:
    """音频融合：**混音计划**（轨道分离 + 响度对齐的调度层）。

    输入每轨:: {"path", "role": "voice"|"music"|"sfx", "peak": float(0~1),
                "source": "local"|"cloud"}

    规则：
      1. **轨道分离**：各轨独立计增益，绝不简单平均；
      2. 角色基础增益（人声 1.0 / 音效 0.7 / 配乐 0.5）；
      3. **响度对齐**：单轨峰值×增益超过 target_peak 时压回（防爆音）；
      4. 总线安全：全部轨 (peak×gain) 之和 > 1.0 时等比压缩。

    Returns:: (plan, provenance)
        plan = [{"path", "role", "gain"}...]；实际 ffmpeg amix 由调用方执行。
    """
    plan: List[Dict[str, Any]] = []
    prov_tracks: List[Dict[str, Any]] = []
    target = min(1.0, max(0.1, float(target_peak)))
    for t in tracks or []:
        role = str(t.get("role", "other"))
        base = _ROLE_GAIN.get(role, _ROLE_GAIN["other"])
        peak = min(1.0, max(0.0, float(t.get("peak", 0.8))))
        gain = base
        if peak * gain > target:      # 响度对齐：防爆音
            gain = target / peak if peak > 0 else base
        plan.append({"path": str(t.get("path", "")), "role": role,
                     "gain": round(gain, 4)})
        prov_tracks.append({"path": str(t.get("path", "")), "role": role,
                            "source": str(t.get("source", "")),
                            "peak": peak, "base_gain": base,
                            "final_gain": round(gain, 4)})
    bus = sum(float(p["gain"]) * float(pt["peak"])
              for p, pt in zip(plan, prov_tracks))
    bus_scale = 1.0
    if bus > 1.0:                      # 总线安全：等比压缩
        bus_scale = 1.0 / bus
        for p, pt in zip(plan, prov_tracks):
            pt["pre_bus_gain"] = p["gain"]
            p["gain"] = round(p["gain"] * bus_scale, 4)
            pt["final_gain"] = p["gain"]  # 溯源与计划一致（压总线后的真值）
    provenance = {"medium": "audio", "mode": "D", "fused_at": _stamp(),
                  "target_peak": target, "bus_scale": round(bus_scale, 4),
                  "tracks": prov_tracks}
    return plan, provenance
