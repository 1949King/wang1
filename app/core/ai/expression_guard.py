"""表情幅度守护（治「AI 生成人物表情夸张、不符合人体机能」）
=============================================================

问题（用户实测）：AI 生成的人物表情幅度失控 —— 如「鼓腮生气时整个腮帮变化
过于剧烈、过于明显，不符合人体的机能设计」。

根因：生成时没有「人体合理幅度」的约束 —— 表情权重可以被拉到极值，
且在时间轴上可以**瞬间跳变**（帧间突变比绝对幅度更刺眼）。

两道防线（与 `tts_guard` / `character_anchor` 同构）：

  * 生成前：① **参数化路径** —— 对表情权重做 clamp（绝对幅度上限 + 帧间跳变限制
    双约束）；② **提示词路径** —— 给文生视频注入「幅度克制」描述 + 防夸张负面词；
  * 生成后：对表情参数序列做幅度质检，定位**超限帧 / 超限维度 / 跳变点** → 定向重生成。

**表情维度命名采用 ARKit ``ARFaceAnchor.BlendShapeLocation`` 标准**（与项目
``app/core/lip_sync.py`` 的 blendshape 出口命名一致：jawOpen / mouthPucker / …），
用户说的「鼓腮」= ``cheekPuff``。

**幅度上限为保守经验默认**（参考 FACS 面部动作编码的强度分级 + ARKit blendshape
常见范围；**非精确人体测量**），提供 ``profile`` 缩放与 ``overrides`` 覆盖，
不写死、不随机。

设计纪律：只读只出计划、不 import app 包、失败诚实降级。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from .guard_base import to_float

logger = logging.getLogger("AI短剧编辑器.core.ai.expression_guard")

# 自然幅度上限（ARKit blendshape 名 → 0~1）。
# ⚠️ 保守经验默认，非精确人体测量；参考 FACS 强度分级(A~E)中「自然表情」落在 A~C
#    区间，以及 ARKit ARFaceAnchor 的常见有效范围。可按项目用 overrides 覆盖。
NATURAL_CAPS: Dict[str, float] = {
    "jawOpen": 0.60,
    "jawLeft": 0.40, "jawRight": 0.40,
    "mouthSmileLeft": 0.65, "mouthSmileRight": 0.65,
    "mouthFrownLeft": 0.45, "mouthFrownRight": 0.45,
    "mouthPucker": 0.55,
    "mouthClose": 0.50,
    "mouthStretchLeft": 0.40, "mouthStretchRight": 0.40,
    # ★ 鼓腮（用户痛点）：自然鼓腮幅度很有限，超过 ~0.3 就像「吹气球」
    "cheekPuff": 0.30,
    "cheekSquintLeft": 0.45, "cheekSquintRight": 0.45,
    "browDownLeft": 0.45, "browDownRight": 0.45,
    "browInnerUp": 0.50,
    "browOuterUpLeft": 0.45, "browOuterUpRight": 0.45,
    "eyeWideLeft": 0.45, "eyeWideRight": 0.45,
    "eyeSquintLeft": 0.45, "eyeSquintRight": 0.45,
    "eyeBlinkLeft": 0.85, "eyeBlinkRight": 0.85,   # 眨眼本就接近全闭
    "noseSneerLeft": 0.35, "noseSneerRight": 0.35,
    "tongueOut": 0.35,
}

# 无名维度的兜底上限（不在表内的 blendshape 也受约束，避免「漏网维度」失控）
FALLBACK_CAP = 0.60

# 幅度档位缩放：含蓄 / 自然 / 强烈
PROFILE_SCALE: Dict[str, float] = {
    "subtle": 0.65,
    "natural": 1.0,
    "intense": 1.3,
}

# 单帧到下一帧的最大变化量（治「变化过于剧烈」的帧间突变）
DEFAULT_MAX_DELTA = 0.25

_HINT_BY_PROFILE: Dict[str, str] = {
    "subtle": "表情含蓄克制，幅度轻微，面部肌肉自然放松",
    "natural": "表情自然真实，幅度符合人体常态，面部肌肉协调",
    "intense": "表情有张力但不夸张，避免面部扭曲",
}

_NEGATIVE: tuple = (
    "夸张表情", "面部扭曲", "五官变形", "过度用力", "用力过猛",
    "鼓腮过度", "腮帮异常鼓起", "脸颊夸张膨胀", "表情僵硬",
    "exaggerated expression", "face distortion", "over-acted",
)


# ═══════════════════════════════════════════════════════════
# 1) 上限解析 / 数值安全
# ═══════════════════════════════════════════════════════════


def resolve_caps(
    profile: str = "natural",
    overrides: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """解析出各维度的实际上限 = NATURAL_CAPS × profile 缩放，再叠加 overrides。

    未在 NATURAL_CAPS 中的维度走 ``FALLBACK_CAP``（避免无名维度不受约束）。
    """
    scale = PROFILE_SCALE.get(str(profile or "natural").lower(), 1.0)
    caps = {k: min(1.0, v * scale) for k, v in NATURAL_CAPS.items()}
    if overrides:
        for k, v in overrides.items():
            try:
                caps[str(k)] = min(1.0, max(0.0, float(v)))
            except (TypeError, ValueError):
                logger.debug("[expression_guard] overrides 值非法，跳过: %r", v)
    return caps


def _cap_for(key: str, caps: Dict[str, float]) -> float:
    """取某维度上限；未登记维度走兜底（兜底值同样按 profile 缩放）。

    兜底而非放行，是为了让**不在 NATURAL_CAPS 表内的维度也受约束** ——
    否则生成端新增一个 blendshape 维度就能绕过全部限制。
    """
    if key in caps:
        return caps[key]
    scale = 1.0
    if "jawOpen" in caps and NATURAL_CAPS.get("jawOpen"):
        scale = caps["jawOpen"] / NATURAL_CAPS["jawOpen"]
    return min(1.0, FALLBACK_CAP * scale)


# 兼容别名：数值安全转换已收敛到 guard_base
_to_float = to_float


# ═══════════════════════════════════════════════════════════
# 2) 生成前：参数钳制
# ═══════════════════════════════════════════════════════════


def clamp_frame(
    params: Optional[Dict[str, Any]],
    *,
    profile: str = "natural",
    overrides: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """单帧表情参数钳制：超限的维度压回上限，并记录削减明细。

    Returns::

        {"params": {key: clamped}, "reductions": [{key,before,after,cap}], "changed": bool}
    """
    caps = resolve_caps(profile, overrides)
    out: Dict[str, float] = {}
    reductions: List[Dict[str, Any]] = []
    if isinstance(params, dict):
        for key, raw in params.items():
            val = _to_float(raw)
            if val < 0.0:
                val = 0.0
            cap = _cap_for(str(key), caps)
            if val > cap:
                reductions.append({"key": str(key), "before": round(val, 4),
                                   "after": round(cap, 4), "cap": round(cap, 4)})
                val = cap
            out[str(key)] = round(val, 4)
    return {"params": out, "reductions": reductions, "changed": bool(reductions)}


def clamp_sequence(
    frames: Optional[Iterable[Dict[str, Any]]],
    *,
    profile: str = "natural",
    overrides: Optional[Dict[str, float]] = None,
    max_delta: float = DEFAULT_MAX_DELTA,
) -> Dict[str, Any]:
    """帧序列钳制：① 每帧绝对幅度 clamp；② **限制帧间跳变**（治「变化过于剧烈」）。

    帧间限制是逐维向前传递的：若某维相对上一帧变化超过 ``max_delta``，
    只允许移动 ``max_delta``（保持变化方向），从而把「瞬间鼓起来」拉成「渐变」。
    """
    caps = resolve_caps(profile, overrides)
    seq = list(frames or [])
    clamped: List[Dict[str, float]] = []
    abs_reductions: List[Dict[str, Any]] = []
    jump_reductions: List[Dict[str, Any]] = []

    prev: Optional[Dict[str, float]] = None
    for i, fr in enumerate(seq):
        if not isinstance(fr, dict):
            continue
        cur: Dict[str, float] = {}
        for key, raw in fr.items():
            k = str(key)
            val = _to_float(raw)
            if val < 0.0:
                val = 0.0
            cap = _cap_for(k, caps)
            if val > cap:
                abs_reductions.append({"frame": i, "key": k,
                                       "before": round(val, 4), "after": round(cap, 4)})
                val = cap
            if prev is not None and k in prev:
                delta = val - prev[k]
                if abs(delta) > max_delta:
                    limited = prev[k] + (max_delta if delta > 0 else -max_delta)
                    jump_reductions.append({"frame": i, "key": k,
                                            "delta": round(delta, 4),
                                            "limited_to": round(limited, 4)})
                    val = limited
            cur[k] = round(val, 4)
        clamped.append(cur)
        prev = cur

    return {
        "frames": clamped,
        "abs_reductions": abs_reductions,
        "jump_reductions": jump_reductions,
        "frame_count": len(clamped),
        "changed": bool(abs_reductions or jump_reductions),
    }


# ═══════════════════════════════════════════════════════════
# 3) 生成后：幅度质检
# ═══════════════════════════════════════════════════════════


def check_amplitude(
    frames: Optional[Iterable[Dict[str, Any]]],
    *,
    profile: str = "natural",
    overrides: Optional[Dict[str, float]] = None,
    max_delta: float = DEFAULT_MAX_DELTA,
) -> Dict[str, Any]:
    """质检：定位**超限帧 / 超限维度 / 跳变点**（只报不改）。

    Returns::

        {"ok", "over_frames": [i], "over_dims": {key: peak},
         "jumps": [{"frame","key","delta"}], "reason"}
    """
    caps = resolve_caps(profile, overrides)
    over_dims: Dict[str, float] = {}
    over_frames: List[int] = []
    jumps: List[Dict[str, Any]] = []
    prev: Optional[Dict[str, float]] = None
    n = 0
    for i, fr in enumerate(frames or []):
        if not isinstance(fr, dict):
            continue
        n += 1
        frame_over = False
        for key, raw in fr.items():
            k = str(key)
            val = _to_float(raw)
            cap = _cap_for(k, caps)
            if val > cap:
                frame_over = True
                over_dims[k] = max(over_dims.get(k, 0.0), round(val, 4))
            if prev is not None and k in prev and abs(val - prev[k]) > max_delta:
                jumps.append({"frame": i, "key": k, "delta": round(val - prev[k], 4)})
        if frame_over:
            over_frames.append(i)
        prev = {str(k): _to_float(v) for k, v in fr.items()}

    ok = not over_frames and not jumps
    reasons: List[str] = []
    if over_frames:
        reasons.append(f"{len(over_frames)} 帧幅度超限（{len(over_dims)} 个维度）")
    if jumps:
        reasons.append(f"{len(jumps)} 处帧间跳变过大")
    return {
        "ok": ok,
        "over_frames": over_frames,
        "over_dims": over_dims,
        "jumps": jumps,
        "checked": n,
        "reason": "" if ok else "；".join(reasons),
    }


def sparse_frames(
    frames: Optional[Iterable[Dict[str, Any]]],
    *,
    min_delta: float = 0.03,
) -> Dict[str, Any]:
    """关键帧稀疏化：相邻帧**各维度变化都**小于 ``min_delta`` 时丢弃后一帧。

    纯数据瘦身（**不改任何值**）：表情参数轨常有大量「几乎不变」的连续帧，
    稀疏化后下游渲染 / 传输更省。**首尾帧必保留** —— 丢了动作会被切掉一截。

    Returns::

        {"frames": [...], "kept_indices": [...], "dropped": int, "ratio": float}
    """
    seq = [f for f in (frames or []) if isinstance(f, dict)]
    n = len(seq)
    if n <= 2:
        return {"frames": seq, "kept_indices": list(range(n)), "dropped": 0, "ratio": 1.0}
    kept_idx: List[int] = [0]
    last = seq[0]
    for i in range(1, n - 1):
        cur = seq[i]
        keys = set(cur) | set(last)
        if any(abs(_to_float(cur.get(k)) - _to_float(last.get(k))) >= min_delta for k in keys):
            kept_idx.append(i)
            last = cur
    kept_idx.append(n - 1)
    kept = [seq[i] for i in kept_idx]
    return {
        "frames": kept,
        "kept_indices": kept_idx,
        "dropped": n - len(kept),
        "ratio": round(len(kept) / n, 4) if n else 0.0,
    }


# ═══════════════════════════════════════════════════════════
# 4) 生成前：提示词约束（文生视频路径）
# ═══════════════════════════════════════════════════════════


def build_expression_hint(emotion: str = "", profile: str = "natural") -> str:
    """生成「表情幅度约束」提示词片段（拼进文生视频 prompt）。"""
    base = _HINT_BY_PROFILE.get(str(profile or "natural").lower(),
                                _HINT_BY_PROFILE["natural"])
    emo = str(emotion or "").strip()
    return f"{base}（当前情绪：{emo}）" if emo else base


def expression_negative() -> List[str]:
    """防夸张负面词（并入 negative prompt）。"""
    return list(_NEGATIVE)


# ═══════════════════════════════════════════════════════════
# 5) 统一入口
# ═══════════════════════════════════════════════════════════


def plan_expression(
    frames: Optional[Iterable[Dict[str, Any]]] = None,
    *,
    emotion: str = "",
    profile: str = "natural",
    overrides: Optional[Dict[str, float]] = None,
    max_delta: float = DEFAULT_MAX_DELTA,
    sparse: bool = False,
    sparse_min_delta: float = 0.03,
) -> Dict[str, Any]:
    """生成「表情幅度守护计划」（只出计划，不改任何数据）。

    Args:
        frames: 可选，表情参数帧序列 → 触发 clamp（生成前）+ check（生成后）
        emotion: 当前情绪（写进提示词片段）
        profile: subtle / natural / intense
        overrides: 覆盖个别维度上限
        max_delta: 帧间最大变化

    Returns::

        {"ok", "profile", "caps", "clamped", "check",
         "hint", "negative", "message"}
    """
    frame_list = list(frames) if frames is not None else None
    result: Dict[str, Any] = {
        "ok": True,
        "profile": profile,
        "caps": resolve_caps(profile, overrides),
        "clamped": None,
        "check": None,
        "sparse": None,
        "hint": build_expression_hint(emotion, profile),
        "negative": expression_negative(),
        "message": "",
    }
    msgs: List[str] = []
    if frame_list is not None:
        result["clamped"] = clamp_sequence(
            frame_list, profile=profile, overrides=overrides, max_delta=max_delta)
        result["check"] = check_amplitude(
            frame_list, profile=profile, overrides=overrides, max_delta=max_delta)
        if sparse:
            result["sparse"] = sparse_frames(
                result["clamped"]["frames"], min_delta=sparse_min_delta)
            msgs.append(f"稀疏化后保留 {result['sparse']['ratio']:.0%} 帧")
        c = result["clamped"]
        if c["abs_reductions"]:
            msgs.append(f"钳制 {len(c['abs_reductions'])} 处幅度超限")
        if c["jump_reductions"]:
            msgs.append(f"限幅 {len(c['jump_reductions'])} 处帧间跳变")
        if result["check"]["ok"]:
            msgs.append("原序列幅度合规")
        else:
            msgs.append("质检：" + result["check"]["reason"])
    else:
        msgs.append("仅出提示词约束（未传表情序列）")
    result["message"] = "；".join(msgs)
    return result
