"""角色一致性锚定守护（治「AI 生成人物跨镜头漂移」）
=====================================================

问题：AI 生成的同一角色在不同镜头 / 不同片段里长相不一致（人物漂移）。
根因是生成模型缺乏「角色身份保持」能力 —— 但**有一半根因在我们自己**：
每次生成时如果角色描述拼得不一致（这次写短发、下次写长发；这次拼了外貌、下次漏了），
漂移就必然发生。本模块先守住「我们能控的那一半」。

两道防线：

  * 生成前：把角色关键特征固化成**锚定卡**（prompt 片段 + 防漂移负面词 + 特征指纹），
    每次生成复用同一张卡，杜绝描述漂移；
  * 生成后：用特征指纹与锚定卡比对，检测漂移并**定位到具体特征项**；
    校验各镜头的生成 prompt 是否**漏拼**了角色关键特征（漏拼 = 必然漂移）。

**边界**：本模块只做**文本层**（可脱离模型单测）。真正的「生成结果人脸相似度比对」
需要视觉 / 人脸模型，属独立后端，不在本模块（见 docstring 末尾"后续"）。

设计纪律：只读只出计划、不 import app 包、失败诚实降级。

字段来源单一事实来源：应保持稳定的特征项对齐
`character_management_module.CHARACTER_FIELD_SCHEMA` 的 **visual 组 + 关键 base 字段**
（生产路径的 prompt 派生仍以 `canvas_bridge.build_character_prompt` 为准，
本模块的 `render_anchor_prompt` 仅作独立测试 / 无桥接环境下的兜底）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from .guard_base import diff_traits, normalize_text, normalize_traits, stable_fingerprint

logger = logging.getLogger("AI短剧编辑器.core.ai.character_anchor")

# 应跨镜头保持稳定的特征项（对齐 CHARACTER_FIELD_SCHEMA：visual 组 + 关键 base）
ANCHOR_TRAITS: tuple = (
    "name", "gender", "age_range",
    "appearance", "temperament", "memory_anchors", "personality",
)

# 「强特征」：最影响辨识度、最易被漏拼，镜头对齐校验只盯这两项
STRONG_TRAITS: tuple = ("appearance", "memory_anchors")

# 防漂移固定负面词（生成时并入 negative prompt）
_DEFAULT_NEGATIVE: tuple = (
    "面部特征变化", "换脸", "五官变形", "发型突变", "服装突变",
    "年龄忽大忽小", "长相不一致", "identity drift", "face swap",
)

# 兼容别名：`_norm` 原为模块内私有归一化，现统一收敛到 guard_base（保留以免破坏既有引用点）
_norm = normalize_text


# ═══════════════════════════════════════════════════════════
# 1) 特征提取 + 指纹（实现已收敛到 guard_base，此处只做字段绑定）
# ═══════════════════════════════════════════════════════════


def extract_traits(character: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """提取应保持稳定的特征项；**空值不收录**（空字段不该参与漂移判定）。

    >>> extract_traits({"name": "林晚", "appearance": "长发红衣"})
    {'name': '林晚', 'appearance': '长发红衣'}
    """
    return normalize_traits(character, ANCHOR_TRAITS)


def fingerprint(traits: Dict[str, str]) -> str:
    """特征指纹：对 traits 排序后取 sha1 前 12 位。内容变则指纹变。"""
    return stable_fingerprint(traits)


# ═══════════════════════════════════════════════════════════
# 2) 锚定卡：组装 / 渲染 / 负面词
# ═══════════════════════════════════════════════════════════


def build_anchor(
    character: Optional[Dict[str, Any]],
    *,
    prompt: str = "",
    reference_image: str = "",
) -> Dict[str, Any]:
    """从一个角色条目派生「一致性锚定卡」（生成前防线）。

    Args:
        character: 角色条目（通常来自角色库 library.json）
        prompt: 调用方已派生的角色 prompt（**优先复用**，保持派生单一来源）；
                留空则用 ``render_anchor_prompt`` 兜底渲染
        reference_image: 定妆照 / 参考图路径（锚定人脸用，可为空）

    Returns::

        {"ok", "character_id", "name", "traits", "fingerprint",
         "prompt", "negative", "reference_image", "has_reference"}
    """
    character = character if isinstance(character, dict) else {}
    traits = extract_traits(character)
    cid = _norm(character.get("id")) or _norm(character.get("name"))
    anchor: Dict[str, Any] = {
        "ok": bool(traits),
        "character_id": cid,
        "name": traits.get("name", ""),
        "traits": traits,
        "fingerprint": fingerprint(traits),
        "prompt": prompt or "",
        "negative": list(_DEFAULT_NEGATIVE),
        "reference_image": reference_image or "",
        "has_reference": bool(reference_image),
    }
    if not anchor["prompt"]:
        anchor["prompt"] = render_anchor_prompt(anchor)
    return anchor


def render_anchor_prompt(anchor: Optional[Dict[str, Any]]) -> str:
    """把锚定卡渲染成固定角色描述片段（兜底实现）。

    与 ``canvas_bridge.build_character_prompt`` 字段语义一致（同一份 schema 的
    visual 组 + 关键 base）；此处独立实现的原因：**不 import 冻结区模块**，
    且让本模块可脱离 app 包单测。生产路径若已有桥接派生的 prompt，应优先用那个。
    """
    t = (anchor or {}).get("traits") or {}
    if not t:
        return ""
    parts: List[str] = []
    if t.get("name"):
        parts.append(f"角色「{t['name']}」")
    if t.get("gender"):
        parts.append(t["gender"])
    if t.get("age_range"):
        parts.append(f"年龄感{t['age_range']}")
    if t.get("appearance"):
        parts.append("外貌:" + t["appearance"][:240])
    if t.get("temperament"):
        parts.append("气质倾向:" + t["temperament"][:80])
    if t.get("memory_anchors"):
        parts.append("标志性符号:" + t["memory_anchors"][:120])
    if t.get("personality"):
        parts.append("性格:" + t["personality"][:120])
    return "，".join(parts)


def anchor_negative() -> List[str]:
    """防漂移固定负面词（生成时并入 negative prompt）。"""
    return list(_DEFAULT_NEGATIVE)


# ═══════════════════════════════════════════════════════════
# 3) 漂移检测（生成后 · 文本层）
# ═══════════════════════════════════════════════════════════


def diff_anchor(
    anchor: Optional[Dict[str, Any]],
    character: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """比对角色当前数据与锚定卡，列出**漂移的特征项**。

    用途：角色库被改动后（用户改了设定 / 误操作），一次调用即可知道
    「哪几个特征变了、从什么变成什么」，避免带着不一致的设定继续批量生成。

    Returns::

        {"ok", "drifted": [key...], "detail": {key: {"before","after"}},
         "fingerprint_before", "fingerprint_after", "reason"}
    """
    if not isinstance(anchor, dict) or not anchor.get("traits"):
        return {
            "ok": False, "drifted": [], "detail": {},
            "fingerprint_before": "", "fingerprint_after": "",
            "reason": "锚定卡为空或缺少 traits",
        }
    return diff_traits(anchor["traits"], extract_traits(character))


def check_shot_alignment(
    anchor: Optional[Dict[str, Any]],
    shot_prompts: Optional[Iterable[str]],
    *,
    min_prefix: int = 6,
) -> Dict[str, Any]:
    """校验各镜头的生成 prompt 是否**漏拼**了角色强特征（漏拼 = 必然漂移）。

    只盯 ``STRONG_TRAITS``（appearance / memory_anchors）——它们最影响辨识度、
    也最容易在「逐镜头手写 prompt」时被漏掉。用特征值前 ``min_prefix`` 个字做子串匹配
    （不要求整段一致，避免因截断/改写而误报）。

    Returns::

        {"ok", "shots": [{"index","ok","missing":[key...]}],
         "retry_indices": [镜头下标], "checked", "reason"}
    """
    t = (anchor or {}).get("traits") or {}
    must = {k: t[k] for k in STRONG_TRAITS if t.get(k)}
    prompts = list(shot_prompts or [])
    if not t:
        return {"ok": False, "shots": [], "retry_indices": [],
                "checked": 0, "reason": "锚定卡为空或缺少 traits"}
    if not must:
        return {"ok": True, "shots": [{"index": i, "ok": True, "missing": []}
                                      for i in range(len(prompts))],
                "retry_indices": [], "checked": len(prompts),
                "reason": "无强特征可校验（appearance / memory_anchors 均空）"}

    shots: List[Dict[str, Any]] = []
    retry: List[int] = []
    for i, p in enumerate(prompts):
        pn = _norm(p)
        missing = [k for k, v in must.items() if v[:min_prefix] not in pn]
        ok = not missing
        shots.append({"index": i, "ok": ok, "missing": missing})
        if not ok:
            retry.append(i)
    return {
        "ok": not retry,
        "shots": shots,
        "retry_indices": retry,
        "checked": len(prompts),
        "reason": "" if not retry else f"{len(retry)} 个镜头漏拼角色特征",
    }


# ═══════════════════════════════════════════════════════════
# 4) 统一入口
# ═══════════════════════════════════════════════════════════


def plan_anchor(
    character: Optional[Dict[str, Any]],
    *,
    prompt: str = "",
    reference_image: str = "",
    shot_prompts: Optional[Iterable[str]] = None,
    anchor: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """生成「角色一致性锚定计划」（只出计划，不改任何数据）。

    Args:
        character: 角色条目
        prompt: 调用方已派生的角色 prompt（优先复用）
        reference_image: 定妆照路径
        shot_prompts: 可选，各镜头生成 prompt → 触发漏拼校验
        anchor: 可选，已有锚定卡（用于 diff 而非重建）

    Returns::

        {"ok", "anchor", "drift", "alignment", "message"}
    """
    anchor = anchor if isinstance(anchor, dict) and anchor.get("traits") else build_anchor(
        character, prompt=prompt, reference_image=reference_image)
    result: Dict[str, Any] = {
        "ok": bool(anchor.get("ok")),
        "anchor": anchor,
        "drift": None,
        "alignment": None,
        "message": "",
    }
    if character is not None:
        result["drift"] = diff_anchor(anchor, character)
    if shot_prompts is not None:
        result["alignment"] = check_shot_alignment(anchor, shot_prompts)

    msgs: List[str] = []
    if not anchor.get("ok"):
        msgs.append("角色特征为空，无法建立锚定卡")
    else:
        msgs.append(f"锚定卡已建立（指纹 {anchor.get('fingerprint')}）")
    if result["drift"] and not result["drift"]["ok"]:
        msgs.append(result["drift"]["reason"])
    if result["alignment"] and not result["alignment"]["ok"]:
        msgs.append(result["alignment"]["reason"])
    result["message"] = "；".join(msgs)
    return result


def plan_multi_anchor(
    characters: Optional[Iterable[Dict[str, Any]]],
    *,
    prompts: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """多角色批量锚定：一次建多个角色卡 + 跨角色冲突检查。

    两个真实用途：
      1. **批量建卡** —— 一部短剧十几个角色，逐个调太碎；
      2. **冲突检查** —— 揪出「同名不同设定」（复制粘贴错误）与
         「不同名但特征完全相同」（疑似复用未改 → 两个角色会长成一样）。

    Args:
        characters: 角色条目列表
        prompts: 可选 ``{角色名: 已派生的 prompt}``（优先复用，保 SSOT）

    Returns::

        {"ok", "anchors": [...], "conflicts": [{"type", ...}], "count", "message"}
    """
    chars = [c for c in (characters or []) if isinstance(c, dict)]
    pmap = prompts if isinstance(prompts, dict) else {}
    anchors: List[Dict[str, Any]] = []
    for c in chars:
        name = str(c.get("name") or "")
        anchors.append(build_anchor(c, prompt=str(pmap.get(name) or "")))

    by_name: Dict[str, List[Dict[str, Any]]] = {}
    by_fp: Dict[str, List[Dict[str, Any]]] = {}
    for a in anchors:
        if a.get("name"):
            by_name.setdefault(str(a["name"]), []).append(a)
        if a.get("fingerprint"):
            by_fp.setdefault(str(a["fingerprint"]), []).append(a)

    conflicts: List[Dict[str, Any]] = []
    for nm, lst in by_name.items():
        if len(lst) > 1:
            conflicts.append({"type": "duplicate_name", "name": nm, "count": len(lst)})
    for fp, lst in by_fp.items():
        if len(lst) > 1:
            conflicts.append({
                "type": "identical_traits", "fingerprint": fp,
                "names": [x.get("name") for x in lst],
            })

    ok_n = sum(1 for a in anchors if a.get("ok"))
    msgs = [f"已建 {ok_n}/{len(anchors)} 张锚定卡"]
    if conflicts:
        msgs.append(f"发现 {len(conflicts)} 处跨角色冲突")
    return {
        "ok": bool(anchors) and not conflicts,
        "anchors": anchors,
        "conflicts": conflicts,
        "count": len(anchors),
        "message": "；".join(msgs),
    }
