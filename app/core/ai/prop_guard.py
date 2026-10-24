"""手持道具一致性守护（治「AI 生成人物手持武器结构畸形」）
=============================================================

问题（用户实图诊断，**关键**）：AI 生成的人物手持武器，**结构本身畸形** ——
画面里那把长杆武器在握持处长出了「一横一竖」的 **三通 / T 形交叉结构**，
而它本应是一根**连续贯通、无分支**的长杆（长枪 / 长矛）。

⇒ 重点不是「手有没有握稳」，而是**道具结构拓扑错了**。

两类畸形，主次分明：

  1. **结构拓扑错误（主症）** —— 多余分支 / 横向凸起 / T 形接口 / 十字交叉 / 分叉；
  2. **手-道具接触畸形（次症）** —— 手指与武器融合、武器穿过手掌、多指少指。

两道防线（与 `tts_guard` / `character_anchor` / `expression_guard` 同构）：

  * 生成前：① **结构描述规范化** —— 明确「单一主干、连续贯通、无分支」；
    ② **握持姿态描述** —— 说清「哪只手、怎么握」；③ 防畸形负面词；
  * 生成后：① 道具特征漂移检测（这次长枪下次变刀）；② 手部关键点合理性规则
    （21 点，MediaPipe Hands 格式，供上游接 `mediapipe` 后直接调用）。

设计纪律：只读只出计划、不 import app 包、失败诚实降级。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .guard_base import diff_traits, normalize_text, normalize_traits, stable_fingerprint

logger = logging.getLogger("AI短剧编辑器.core.ai.prop_guard")

# 道具正确结构模板：key → (中文名, 结构描述)
# ⚠️ 每一条都刻意写明「单一主干 / 连续贯通 / 无分支」——直击实图里看到的「三通结构」。
PROP_STRUCTURE_TEMPLATES: Dict[str, Tuple[str, str]] = {
    "spear": ("长枪 / 长矛",
              "一柄笔直的长枪：枪杆贯通连续、单一主干、无任何分支，"
              "枪头与杆身一体衔接，握持处无横向凸起或多余接口"),
    "staff": ("法杖 / 长棍",
              "一根笔直的长棍：全长等径、贯通连续、无分支无凸起，两端为简单圆头"),
    "sword": ("长剑",
              "一柄直剑：剑身与剑柄同轴连续、单一主干无分支，护手为单一横向护格，剑尖收束"),
    "greatsword": ("巨剑",
                "一柄宽刃巨剑：剑身笔直连续、两面收刃，护手简单，无多余结构"),
    "axe": ("战斧",
            "一柄战斧：斧柄笔直贯通，斧头单侧固定于柄端，斧柄本身无分叉"),
    "bow": ("长弓",
            "一张长弓：弓臂为单一弧线连续材质，弓弦为直线连接两端，无多余枝节"),
    "staff_magic": ("魔法法杖",
                    "一根魔法法杖：杖身笔直贯通无分支，杖顶为单一体块（宝石 / 雕塑），"
                    "杖身与杖顶衔接自然"),
}

# 握持姿态模板：key → 描述
GRIP_TEMPLATES: Dict[str, str] = {
    "single_hand": "单手握持，五指环握柄部，拇指压于前方，其余四指环扣、指尖分明",
    "two_hand": "双手握持，主导手握于柄部、辅助手握于前段，左右手手指各自分明不重叠",
    "raised": "单手举握，手臂上举，五指环握柄部，手指与武器边界清晰",
    "shouldered": "肩扛握持，手掌握于柄部近端，手指环扣清晰",
    "pointing": "单手持械前指，手指与武器分离可见、不粘连",
    # 双持：两件武器须**各自结构完整**且互不融合（AI 双持时最易长成一团）
    "dual": "双手各持一件武器，主导手握持主武器、辅助手握持副武器，"
            "两件武器各自独立、互不穿插，两手手指各自分明",
}

# 道具应保持稳定的特征项
PROP_TRAITS: tuple = ("prop_type", "prop_color", "prop_material", "prop_length", "structure")

# 防畸形负面词（前 4 组针对「结构拓扑」主症，后 3 组针对「手-道具接触」次症）
_PROP_NEGATIVE: tuple = (
    # ── 结构拓扑（主症 · 直击实图的「三通」）──
    "多余分支", "横向凸起", "三通结构", "T 形接口", "十字交叉", "武器分叉",
    "管道状连接", "多余接口", "结构粘连", "武器结构混乱",
    "extra branch", "forked weapon", "T-junction", "cross fitting",
    # ── 手-道具接触（次症）──
    "手指融合", "手指粘连", "多指", "少指", "六指",
    "武器穿过手", "武器与手融合", "握持不实",
    "fused fingers", "extra fingers", "weapon clipping through hand",
)

_STRONG_TRAITS: tuple = ("prop_type", "structure")

# ── 手部关键点（MediaPipe Hands 21 点）索引 ──
_WRIST = 0
_HAND_TIP_IDX = (4, 8, 12, 16, 20)   # 拇指~小指的指尖
_MIDDLE_MCP = 9                       # 中指根（用于归一化手掌尺度）
_HAND_POINT_COUNT = 21


# 兼容别名：`_norm` 原为模块内私有归一化，现统一收敛到 guard_base
_norm = normalize_text


# ═══════════════════════════════════════════════════════════
# 1) 生成前：结构 + 握持描述（治「生成端不知道怎么握、结构该怎么长」）
# ═══════════════════════════════════════════════════════════


def structure_hint(prop_type: str = "spear", *, custom: str = "") -> str:
    """取道具结构描述；未知类型回退到「单一主干无分支」的通用约束。

    回退而非放行是刻意的：**结构约束宁可有、不可无** —— 没有约束才是畸形之源。
    """
    if custom and custom.strip():
        return custom.strip()
    key = str(prop_type or "spear").strip()
    hit = PROP_STRUCTURE_TEMPLATES.get(key)
    if hit:
        return hit[1]
    return ("一件结构清晰的武器道具：单一主干、材质连续、无多余分支或横向接口，"
            "各部件衔接符合物理与功能逻辑")


def prop_negative() -> List[str]:
    """防畸形负面词（结构拓扑 + 手-道具接触）。"""
    return list(_PROP_NEGATIVE)


def build_prop_prompt(
    prop_type: str = "spear",
    *,
    grip: str = "single_hand",
    hand: str = "right",
    custom_structure: str = "",
    off_prop_type: str = "",
) -> str:
    """组合出「道具结构约束 + 握持姿态」的完整描述片段（拼进生图 / 生视频 prompt）。

    传 ``off_prop_type``（副手武器）+ ``hand="dual"`` 时产出**双持**描述 ——
    两件武器**各自写明结构约束**（双持最易「长成一团」，结构约束尤其关键）。

    >>> build_prop_prompt("spear", grip="two_hand", hand="both")[:24]
    '角色双手握持一柄笔直的长枪'
    """
    h = str(hand or "right").strip()
    g = str(grip or "single_hand").strip()
    struct = PROP_STRUCTURE_TEMPLATES.get(str(prop_type or "").strip())
    name = struct[0] if struct else "武器道具"
    hand_cn = {"right": "右手", "left": "左手", "both": "双手", "dual": "双手"}.get(h, "单手")
    grip_desc = GRIP_TEMPLATES.get(g, GRIP_TEMPLATES["single_hand"])

    off = str(off_prop_type or "").strip()
    if h == "dual" and off:
        off_struct = PROP_STRUCTURE_TEMPLATES.get(off)
        off_name = off_struct[0] if off_struct else "副手武器"
        return (
            f"角色双手各持一件武器：主导手握持{name}"
            f"（{structure_hint(prop_type, custom=custom_structure)}），"
            f"辅助手握持{off_name}（{structure_hint(off)}），{grip_desc}"
        )
    return f"角色{hand_cn}握持{name}，{structure_hint(prop_type, custom=custom_structure)}，{grip_desc}"


# ═══════════════════════════════════════════════════════════
# 2) 生成后：道具特征锚定 + 漂移检测（治「这次长枪下次变刀」）
# ═══════════════════════════════════════════════════════════


def extract_prop_traits(prop: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """提取道具应保持稳定的特征（空值不收录）。"""
    return normalize_traits(prop, PROP_TRAITS)


def prop_fingerprint(traits: Dict[str, str]) -> str:
    """道具特征指纹（sha1 前 12 位）。"""
    return stable_fingerprint(traits)


def build_prop_anchor(prop: Optional[Dict[str, Any]], *, prompt: str = "") -> Dict[str, Any]:
    """建立道具锚定卡（生成前防线：跨镜头保持同一柄武器）。"""
    prop = prop if isinstance(prop, dict) else {}
    traits = extract_prop_traits(prop)
    return {
        "ok": bool(traits),
        "traits": traits,
        "fingerprint": prop_fingerprint(traits),
        "prompt": prompt or "",
        "negative": prop_negative(),
    }


def diff_prop_anchor(
    anchor: Optional[Dict[str, Any]],
    prop: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """比对道具当前数据与锚定卡，列出漂移的特征项。"""
    if not isinstance(anchor, dict) or not anchor.get("traits"):
        return {"ok": False, "drifted": [], "detail": {},
                "fingerprint_before": "", "fingerprint_after": "",
                "reason": "道具锚定卡为空"}
    return diff_traits(anchor["traits"], extract_prop_traits(prop))


# ═══════════════════════════════════════════════════════════
# 3) 生成后：手部关键点合理性规则（21 点 · MediaPipe Hands 格式）
# ═══════════════════════════════════════════════════════════


def _pt_xy(p: Any) -> Optional[Tuple[float, float]]:
    if isinstance(p, dict):
        try:
            return float(p.get("x")), float(p.get("y"))
        except (TypeError, ValueError):
            return None
    if isinstance(p, (list, tuple)) and len(p) >= 2:
        try:
            return float(p[0]), float(p[1])
        except (TypeError, ValueError):
            return None
    return None


def _pt_conf(p: Any) -> float:
    if isinstance(p, dict):
        for k in ("confidence", "visibility", "score", "conf"):
            if k in p:
                try:
                    return float(p[k])
                except (TypeError, ValueError):
                    return 1.0
        return 1.0
    return 1.0


def check_hand_keypoints(
    points: Optional[Iterable[Any]],
    *,
    min_conf: float = 0.5,
    close_ratio: float = 0.35,
) -> Dict[str, Any]:
    """手部关键点合理性规则（判「手指是否融合/粘连」）。

    Args:
        points: 21 个关键点（dict 带 x/y/confidence 或 [x,y]）
        min_conf: 置信度下限，低于此的点判为不可信（= 手指糊了）
        close_ratio: 相邻指尖距离 / 掌尺度 低于此 → 判为手指粘连

    Returns::

        {"ok", "valid", "low_conf": [idx], "fused": bool,
         "min_tip_gap_ratio": float, "reason"}
    """
    pts = list(points or [])
    if len(pts) != _HAND_POINT_COUNT:
        return {"ok": False, "valid": False, "low_conf": [], "fused": False,
                "min_tip_gap_ratio": 0.0,
                "reason": f"关键点数 {len(pts)} ≠ {_HAND_POINT_COUNT}，无法判定"}

    xy = [_pt_xy(p) for p in pts]
    if any(p is None for p in xy):
        return {"ok": False, "valid": False, "low_conf": [], "fused": False,
                "min_tip_gap_ratio": 0.0, "reason": "存在非法坐标"}

    low_conf = [i for i, p in enumerate(pts) if _pt_conf(p) < min_conf]

    # 手掌尺度 = 腕 → 中指根 距离（用作归一化基准，避免受分辨率影响）
    wx, wy = xy[_WRIST]          # type: ignore[misc]
    mx, my = xy[_MIDDLE_MCP]     # type: ignore[misc]
    palm = ((wx - mx) ** 2 + (wy - my) ** 2) ** 0.5
    if palm <= 1e-6:
        return {"ok": False, "valid": False, "low_conf": low_conf, "fused": False,
                "min_tip_gap_ratio": 0.0, "reason": "手掌尺度为 0（关键点塌缩）"}

    gaps: List[float] = []
    for a in range(len(_HAND_TIP_IDX)):
        for b in range(a + 1, len(_HAND_TIP_IDX)):
            ax, ay = xy[_HAND_TIP_IDX[a]]   # type: ignore[misc]
            bx, by = xy[_HAND_TIP_IDX[b]]   # type: ignore[misc]
            gaps.append((((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5) / palm)
    min_gap = min(gaps) if gaps else 0.0
    fused = min_gap < close_ratio

    issues: List[str] = []
    if low_conf:
        issues.append(f"{len(low_conf)} 个关键点置信度过低（可能手指融合）")
    if fused:
        issues.append(f"相邻指尖间距过小（{min_gap:.2f} < {close_ratio}，疑似粘连）")
    return {
        "ok": not issues,
        "valid": True,
        "low_conf": low_conf,
        "fused": fused,
        "min_tip_gap_ratio": round(min_gap, 4),
        "reason": "" if not issues else "；".join(issues),
    }


# ═══════════════════════════════════════════════════════════
# 4) 统一入口
# ═══════════════════════════════════════════════════════════


def plan_prop(
    prop: Optional[Dict[str, Any]] = None,
    *,
    prop_type: str = "",
    grip: str = "single_hand",
    hand: str = "right",
    custom_structure: str = "",
    off_prop_type: str = "",
    anchor: Optional[Dict[str, Any]] = None,
    hand_points: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """生成「手持道具守护计划」（只出计划，不改任何数据）。

    Returns::

        {"ok", "prompt", "negative", "anchor", "drift", "hand", "message"}
    """
    result: Dict[str, Any] = {"ok": True, "prompt": "", "negative": prop_negative(),
                              "anchor": None, "drift": None, "hand": None, "message": ""}
    msgs: List[str] = []

    # 道具类型：优先 prop.prop_type，其次显式参数
    ptype = prop_type or (str(prop.get("prop_type") or "") if isinstance(prop, dict) else "")
    if not ptype:
        ptype = "spear"
    result["prompt"] = build_prop_prompt(
        ptype, grip=grip, hand=hand, custom_structure=custom_structure,
        off_prop_type=off_prop_type)

    if prop is not None:
        if isinstance(anchor, dict) and anchor.get("traits"):
            result["anchor"] = anchor
            result["drift"] = diff_prop_anchor(anchor, prop)
            if not result["drift"]["ok"]:
                msgs.append(result["drift"]["reason"])
        else:
            result["anchor"] = build_prop_anchor(prop, prompt=result["prompt"])
            msgs.append(f"道具锚定卡已建立（指纹 {result['anchor']['fingerprint']}）")

    if hand_points is not None:
        result["hand"] = check_hand_keypoints(hand_points)
        if not result["hand"]["ok"]:
            msgs.append("手部关键点：" + result["hand"]["reason"])

    if not msgs:
        msgs.append("已出结构 + 握持描述与防畸形负面词")
    result["message"] = "；".join(msgs)
    return result
