# -*- coding: utf-8 -*-
"""多角色配音编排 · 纯函数内核（2026-10-15，配音一致性方案 P0①）

为什么需要（对照用户痛点核实）
============================
用户两件事没解决：
  ① AI 视频模型自带对白「发音与字幕/字对不上」；
  ② 多角色配音 + 手工排时间线太费人工。
本模块只做**编排的纯逻辑**，把「谁说了哪句 → 用哪个音色 → 每句多长 →
拼成一条配音轨」拆成四个**可单测、零 IO** 的纯函数；真正的 TTS 合成、写盘、
入轨分别交给 `voice_generator`（既有引擎链）、路由层（`/host/dub-*`）、
与**唯一入轨通道** `POST /ingest_path`。

为什么不猜（本模块的红线）
========================
· 剧本里**没有「角色:」前缀** ⇒ `speaker=None` 归**旁白**，**绝不猜是哪个角色**。
· 查不到角色绑定的音色 ⇒ 明确标 `degraded=True` + 用默认声线，
  **绝不伪造**一个"已绑定"的假象（同 YuE 诚实降级纪律）。
· 镜头时长**只在真有对应配音音频时才覆盖**；没有音频证据就保留原估算并标
  `duration_source="estimate"`，**不假装音画已对齐**。

边界（与既有件分工）
==================
- 输入解析 / 路由 / 反推 / 拼轨：本模块（纯函数）。
- 合成：`voice_generator.AIVoiceGenerator.generate_voice()`（既有降级链，不重建）。
- 角色↔音色：`voice_clone.character_voice_id()`（旁挂字段 `voice_id`，不碰 schema）。
- 验证：`dub_verify.verify_dubbing()`（P1，见该模块）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Union

from app.core.ai.voice_clone import character_voice_id

logger = logging.getLogger(__name__)

# 默认声线（枚举型 profile id，见 voice_generator._initialize_default_profiles）。
# 查不到角色音色时的**诚实降级目标**：真实 TTS 声线，但明确标 degraded。
DEFAULT_VOICE_PROFILE = "neutral_professional"

# 旁白标签：命中即归入 `speaker=None`（旁白/画外音不是"某个角色"，不做角色路由）。
NARRATION_LABELS = frozenset(
    {"旁白", "画外音", "独白", "内心", "narration", "narrator", "vo", "v.o.", "os", "o.s."}
)

# 「说话人:」前缀（中英文冒号皆可）。说话人名限制 1~24 字，且**不含句读**，
# 避免把「他今天很好。然后……」整句误判成说话人。
_SPEAKER_COLON_RE = re.compile(r"^\s*([^：:]{1,24})\s*[：:]\s*(.+?)\s*$")
# 「【说话人】台词」/「[speaker] line」方括号形式（可选跟一个冒号）。
_SPEAKER_BRACKET_RE = re.compile(r"^\s*[【\[]\s*([^】\]]{1,24})\s*[】\]]\s*[：:]?\s*(.+?)\s*$")
# 说话人名里出现这些标点 ⇒ 不是说话人前缀（是叙述句）。
_SENTENCE_PUNCT = frozenset("。！？!?，,；;、…")

# 文本归一化：去掉空白与常见标点，只留「内容」，用于音频↔镜头时长匹配。
_NORM_STRIP_RE = re.compile(r"[\s，。！？、；：""''（）()「」【】,.!?;:'\"`~—-]+")


def _normalize_text(text: Any) -> str:
    """归一化文本（去空白/标点）用于**内容匹配**，不用于展示。"""
    return _NORM_STRIP_RE.sub("", str(text or ""))


def _clean_speaker(raw: str) -> Optional[str]:
    """清洗说话人名：去空白与括号残留；旁白标签 / 空 ⇒ None（归旁白）。"""
    name = (raw or "").strip().strip("【】[]").strip()
    # 去掉角色名后的括号注（如「小明（生气）」→「小明」）：括号内是情绪/动作，不是名字
    name = re.sub(r"[（(].*?[)）]\s*$", "", name).strip()
    if not name or name.lower() in NARRATION_LABELS:
        return None
    return name


# ── ① 剧本 → 逐句 [{speaker, text, order}] ─────────────────────────
def parse_dialogue_lines(script: str) -> List[Dict[str, Any]]:
    """剧本 → 逐句台词（**纯函数**）。

    解析规则（容错、不猜）：
      - 支持「角色：台词」「角色: 台词」「【角色】台词」「[speaker] line」四种前缀；
      - 无前缀 / 说话人含句读 / 说话人是旁白标签 ⇒ `speaker=None`（归旁白）；
      - 空行丢弃；`order` 从 1 起，与实际配音顺序一致（也是拼轨排序键）。

    Returns:
        [{"speaker": Optional[str], "text": str, "order": int}, ...]
    """
    out: List[Dict[str, Any]] = []
    for raw_line in (script or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        speaker: Optional[str] = None
        content = line
        # 先试方括号形式（更明确），再试冒号形式
        m = _SPEAKER_BRACKET_RE.match(line)
        if not m:
            m = _SPEAKER_COLON_RE.match(line)
        if m:
            cand = m.group(1)
            # 说话人里出现句读 ⇒ 这是叙述句，不是台词前缀，不猜
            if not any(ch in _SENTENCE_PUNCT for ch in cand):
                speaker = _clean_speaker(cand)
                content = m.group(2).strip()
        if not content:
            continue
        out.append({"speaker": speaker, "text": content, "order": len(out) + 1})
    return out


# ── ② 逐句路由音色 ─────────────────────────────────────────────────
def route_voices(
    lines: List[Dict[str, Any]],
    character_lookup: Union[Callable[[str], Optional[Dict[str, Any]]],
                            Dict[str, Dict[str, Any]], None] = None,
) -> List[Dict[str, Any]]:
    """给每句挂音色（**纯函数**）：复用 `voice_clone.character_voice_id`。

    Args:
        lines: `parse_dialogue_lines()` 的输出。
        character_lookup: 名字 → 角色 dict 的映射（dict）或查询函数（callable）。
            角色 dict 上若挂了 `voice_id`（`bind_character_voice()` 写入），即用它做音色。

    Returns（在原句 dict 上追加字段）:
        voice_id: 命中的音色 id（None = 未命中）
        voice_profile_id: 送给 `voice_generator` 的声线 id
        route: "character" | "narration" | "default_voice"
        degraded: True = **没拿到角色专属音色**（用默认声线，如实标注）
        degrade_reason: degraded 时的中文说明（给用户看）

    诚实边界：自定义 `voice_id` 需克隆引擎（当前未装）⇒ 若 `voice_id` 不等于任何
    枚举声线 id，则**无法合成该音色** ⇒ 降级默认声线并如实标 degraded，绝不冒充。
    """
    # 延迟取 voice_generator 已知声线 id，避免顶层循环导入
    known_profiles = _known_voice_profiles()
    out: List[Dict[str, Any]] = []
    for ln in lines or []:
        item = dict(ln)
        name = item.get("speaker")
        voice_id: Optional[str] = None
        char: Optional[Dict[str, Any]] = None
        if name:
            if callable(character_lookup):
                char = character_lookup(name)
            elif isinstance(character_lookup, dict):
                char = character_lookup.get(name)
            if char:
                voice_id = character_voice_id(char)

        # 声线选择：优先角色显式 voice_profile_id；其次 voice_id 恰好是声线 id；
        # 都没有 ⇒ 默认声线（降级）。
        profile = ""
        if isinstance(char, dict):
            profile = str(char.get("voice_profile_id") or "")
        if not profile and voice_id and voice_id in known_profiles:
            profile = voice_id

        if not name:
            route = "narration"          # 旁白用默认声线是**预期**，不算降级
            degraded = False
            reason = ""
        elif profile:
            route = "character"
            degraded = False
            reason = ""
        else:
            route = "default_voice"
            degraded = True
            if voice_id:
                reason = (f"角色「{name}」绑定了音色 {voice_id}，但克隆引擎未安装，"
                          f"无法合成该音色 ⇒ 降级默认声线")
            else:
                reason = f"角色「{name}」未绑定音色 ⇒ 降级默认声线（可在角色库为其指定）"

        item["voice_id"] = voice_id
        item["voice_profile_id"] = profile or DEFAULT_VOICE_PROFILE
        item["route"] = route
        item["degraded"] = degraded
        item["degrade_reason"] = reason
        out.append(item)
    return out


def _known_voice_profiles() -> frozenset:
    """取 `voice_generator` 预置声线 id 集合（只读常量，失败返回空集不抛）。"""
    try:
        from app.core.voice_generator import AIVoiceGenerator

        gen = AIVoiceGenerator()
        return frozenset(gen._voice_profiles.keys())  # noqa: SLF001（只读，稳定契约）
    except Exception as exc:  # 引擎模块异常不应阻断编排
        logger.debug("[dub_pipeline] 取声线清单失败: %s", exc)
        return frozenset()


# ── ③ 配音时长 → 镜头时长反推 ──────────────────────────────────────
def retime_shots_by_audio(
    shots: List[Dict[str, Any]],
    audio_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """用**配音音频的真实时长**覆盖镜头时长（**纯函数**）。

    匹配策略（先精确、再包含，都不中则保留原估算）：
      1. 归一化后 `shot.dialogue` == 某句台词 ⇒ 取该句音频时长；
      2. 否则累加所有「台词是 shot.dialogue 子串」的音频时长；
      3. 都没命中 ⇒ 保留 `shot.duration` 原值并标 `duration_source="estimate"`。

    Args:
        shots: 分镜表（含 `dialogue` / `duration`）。
        audio_results: `[{"text", "duration", ...}]`（来自 dub-execute 的合成结果）。

    Returns:
        新 shot 列表，追加 `duration_source`（"audio" | "estimate"）。
        ⚠️ 只有真拿到音频的镜头才改时长 —— **没有音频证据就不假装已对齐**。
    """
    # 内容 → 累计时长（同一句可能被切成多段 ⇒ 累加）
    by_text: Dict[str, float] = {}
    for a in audio_results or []:
        key = _normalize_text(a.get("text"))
        if not key:
            continue
        by_text[key] = by_text.get(key, 0.0) + float(a.get("duration") or 0.0)

    out: List[Dict[str, Any]] = []
    for s in shots or []:
        item = dict(s)
        key = _normalize_text(item.get("dialogue"))
        matched = False
        new_duration = float(item.get("duration") or 0.0)
        if key:
            if key in by_text:
                new_duration = by_text[key]
                matched = True
            else:
                # 包含式兜底：镜头台词里可能拼了多句
                total = 0.0
                for tkey, dur in by_text.items():
                    if tkey and tkey in key:
                        total += dur
                if total > 0:
                    new_duration = total
                    matched = True
        item["duration"] = round(new_duration, 3)
        item["duration_source"] = "audio" if matched else "estimate"
        out.append(item)
    return out


# ── ④ 多句配音拼成一条配音轨 ───────────────────────────────────────
def assemble_dialogue_track(
    audio_results: List[Dict[str, Any]],
    gap: float = 0.0,
) -> Dict[str, Any]:
    """按 `order` 把逐句配音拼成一条时间轴（**纯函数**，不落盘）。

    这是「排时间线被数据消解」的那一步：每句的 `start/end` 由**前面所有句子的
    真实音频时长**顺推，无需人工落位 —— 因为镜头时长同样由音频反推（见 ③），
    配音与画面天然同轴。

    Args:
        audio_results: `[{"order", "duration", "audio_path"}, ...]`（order 必填）。
        gap: 段间静默秒数（默认 0 = 首尾相接）。

    Returns:
        {"segments": [{"order", "start", "end", "duration", "audio_path"}...],
         "total": 总时长}
    """
    ordered = sorted(audio_results or [], key=lambda a: int(a.get("order") or 0))
    segments: List[Dict[str, Any]] = []
    cursor = 0.0
    for a in ordered:
        dur = max(0.0, float(a.get("duration") or 0.0))
        seg = {
            "order": int(a.get("order") or 0),
            "start": round(cursor, 3),
            "end": round(cursor + dur, 3),
            "duration": round(dur, 3),
            "audio_path": a.get("audio_path") or "",
        }
        segments.append(seg)
        cursor += dur + max(0.0, float(gap or 0.0))
    return {"segments": segments, "total": round(cursor, 3)}
