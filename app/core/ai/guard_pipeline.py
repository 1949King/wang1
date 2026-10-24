"""生成管线 · 守护适配层（让守护真正挂进管线，并与已接入的 LLM 联动）
=========================================================================

四个守护（`tts_guard` / `character_anchor` / `expression_guard` / `prop_guard`）此前是
`pipeline.*` **Agent 能力** —— 要人 / Agent 主动调用才生效。本层把它们**接进生成管线**，
让 `AIVideoGenerationPipeline` 的「生成前 → 生成 → 质检 → 修订 → 重生成」闭环**自动**调用：

| 管线时机 | 本层函数 | 做什么 |
|---|---|---|
| 生成前（提示词成型） | `enhance_prompt` | 注入守护约束：角色卡 / 道具结构 / 表情幅度 + 防漂移防畸形负面词 |
| 生成后（初检） | `augment_inspection` | 在 LLM 泛泛初检之上，叠加守护的**结构化质检 + 明确修订提示** |
| 修订 | `revise_hint` | 把守护问题转成明确的 avoid 提示（补 `_revise_prompt` 的粗糙拼接） |
| 通用 | `make_llm` | **LLM 联动**：把项目 `ai_engine` 包成守护需要的 `(prompt)->str` 回调 |

**与 Agent 能力的区别**：Agent 能力是「人能想起来才调」；本层是「管线必调」——
这是把守护从「工具」变成「守门人」的关键一步。

**LLM 联动**体现在两处：① `make_llm()` 让守护能真正调用项目接入的大模型
（如多音字消歧、`tts_guard.detect_polyphones_batch`）；② `augment_inspection` 的
LLM 层让大模型**针对守护维度聚焦审核**（角色一致性 / 表情幅度 / 道具结构 / 手部），
比管线原有的泛泛「穿模/畸形」初检更精准。

设计纪律：本层**只做编排 + 适配**，不重复任何守护逻辑；LLM 不可用一律诚实降级。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.core.ai.guard_pipeline")

# 与「视频画面」相关的守护（tts 属配音链路，不在画面管线里）
VIDEO_GUARD_KINDS: tuple = ("character", "expression", "prop")

_JSON_OBJ = re.compile(r"\{.*\}", re.S)

# 让大模型**针对守护维度**聚焦审核（区别于管线原有的泛泛初检）
_GUARD_INSPECT_PROMPT = (
    "你是 AI 生成视频的『质量守护』审核员。请针对以下**具体维度**审核这段生成提示词，"
    "**只报确实存在的问题**，没有问题就返回空数组：\n"
    "① 角色一致性：角色长相/发型/服装是否可能跨镜头漂移；\n"
    "② 表情幅度：表情是否可能夸张、不符合人体机能设计；\n"
    "③ 道具结构：手持武器是否可能长出多余分支 / 三通结构 / 与手融合；\n"
    "④ 手部：手指是否可能融合 / 多指 / 穿透武器。\n"
    "只输出 JSON：{\"issues\": [\"…\"], \"suggestion\": \"…\"}，不要任何解释、不要 markdown。\n\n"
    "生成提示词：{prompt}\n"
    "{context}"
)


# ═══════════════════════════════════════════════════════════
# LLM 联动
# ═══════════════════════════════════════════════════════════


def make_llm() -> Optional[Callable[[str], str]]:
    """把项目 `ai_engine` 包成守护需要的 ``(prompt)->str`` 回调 —— **LLM 联动**入口。

    守护侧的 LLM 能力（多音字批量消歧、聚焦质检）都通过这个回调调用**项目已接入的大模型**，
    而不是各写一套 HTTP 客户端。

    不可用时返回 ``None`` —— 守护会诚实地降级（不注音 / 跳过 LLM 层），绝不崩。
    """
    try:
        from app.core.ai_engine import ai_engine
    except Exception:
        logger.debug("[guard_pipeline] ai_engine 不可用，LLM 联动降级", exc_info=True)
        return None

    def _call(prompt: str) -> str:
        chunks = list(ai_engine.chat_with_fallback(
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        ))
        return "".join(chunks) if chunks else ""

    return _call


# ═══════════════════════════════════════════════════════════
# 生成前：注入守护约束
# ═══════════════════════════════════════════════════════════


def enhance_prompt(prompt: str, *, guards: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """生成前：把守护约束注进提示词。

    Args:
        prompt: 管线生成的原始提示词
        guards: 守护上下文，如::

            {
              "character": {"name": "林晚", "appearance": "长发红衣"},   # 角色条目
              "prop": {"prop_type": "spear", "grip": "two_hand", "hand": "both"},
              "expression": {"profile": "natural", "emotion": "愤怒"},
            }

    Returns::

        {"prompt": 增强后提示词, "negative": [全量负面词], "parts": [注入的约束片段],
         "guards": {各守护明细}, "changed": bool}
    """
    base = str(prompt or "")
    g = guards if isinstance(guards, dict) else {}
    parts: List[str] = []
    detail: Dict[str, Any] = {}

    # ① 角色一致性锚定
    ch = g.get("character")
    if isinstance(ch, dict):
        try:
            from .character_anchor import build_anchor

            a = build_anchor(ch)
            if a.get("ok") and a.get("prompt"):
                parts.append(str(a["prompt"]))
                detail["character"] = {"name": a.get("name"), "fingerprint": a.get("fingerprint")}
        except Exception:
            logger.debug("[guard_pipeline] 角色锚定失败，跳过", exc_info=True)

    # ② 道具结构
    pg = g.get("prop")
    if isinstance(pg, dict):
        try:
            from .prop_guard import build_prop_prompt

            pp = build_prop_prompt(
                str(pg.get("prop_type") or ""),
                grip=str(pg.get("grip") or "single_hand"),
                hand=str(pg.get("hand") or "right"),
                custom_structure=str(pg.get("custom_structure") or ""),
                off_prop_type=str(pg.get("off_prop_type") or ""),
            )
            if pp:
                parts.append(pp)
                detail["prop"] = {"prompt": pp}
        except Exception:
            logger.debug("[guard_pipeline] 道具结构注入失败，跳过", exc_info=True)

    # ③ 表情幅度
    eg = g.get("expression")
    if isinstance(eg, dict):
        try:
            from .expression_guard import build_expression_hint

            h = build_expression_hint(
                str(eg.get("emotion") or ""), str(eg.get("profile") or "natural"))
            if h:
                parts.append(h)
                detail["expression"] = {"hint": h}
        except Exception:
            logger.debug("[guard_pipeline] 表情约束注入失败，跳过", exc_info=True)

    # ④ 全量负面词（一次拼齐，不必逐个能力取）
    negative: List[str] = []
    try:
        from .guards import guard_negative_all

        negative = guard_negative_all()
    except Exception:
        logger.debug("[guard_pipeline] 负面词合并失败", exc_info=True)

    # ⑤ 评分簿回写闭环（P0-2）：同风格（style_dna）历史高分组合优先
    #    —— 负面词改用历史验证过的组合（而非固定全量），增益词注进提示词
    style_dna = str(g.get("style_dna") or "").strip()
    if style_dna:
        try:
            from .score_book import get_score_book

            combo = get_score_book().best_combo(style_dna)
            if combo:
                if combo.get("negatives"):
                    negative = list(combo["negatives"])
                if combo.get("gains"):
                    parts.append("，".join(str(x) for x in combo["gains"]))
                detail["score_book"] = {
                    "style_dna": style_dna,
                    "score": combo.get("score"),
                    "samples": combo.get("samples"),
                }
        except Exception:
            logger.debug("[guard_pipeline] 评分簿查询失败，跳过", exc_info=True)

    # 拼接：空 prompt 时**不留 " | " 前缀**（否则会以分隔符开头，污染下游提示词）
    joined = "，".join(parts)
    if not joined:
        enhanced = base
    elif base.strip():
        enhanced = f"{base} | {joined}"
    else:
        enhanced = joined
    return {
        "prompt": enhanced,
        "negative": negative,
        "parts": parts,
        "guards": detail,
        "changed": bool(parts),
    }


# ═══════════════════════════════════════════════════════════
# 生成后：守护质检（规则层 + LLM 层）
# ═══════════════════════════════════════════════════════════


def _extract_json_obj(text: Any) -> Dict[str, Any]:
    """从 LLM 回复提取 JSON 对象（容忍 markdown / 前后废话）。"""
    if not text:
        return {}
    m = _JSON_OBJ.search(str(text))
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _llm_guard_inspect(llm: Callable[[str], str], prompt: str,
                       guards: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """LLM 层：让大模型针对守护维度聚焦审核。失败返回 None（诚实降级）。"""
    ctx_lines: List[str] = []
    ch = guards.get("character")
    if isinstance(ch, dict) and ch.get("appearance"):
        ctx_lines.append(f"角色设定：{ch.get('appearance')}")
    pg = guards.get("prop")
    if isinstance(pg, dict) and pg.get("prop_type"):
        ctx_lines.append(f"道具类型：{pg.get('prop_type')}（握法 {pg.get('grip') or 'single_hand'}）")
    ctx = ("\n".join(ctx_lines) + "\n") if ctx_lines else ""
    try:
        reply = llm(_GUARD_INSPECT_PROMPT.replace("{prompt}", prompt).replace("{context}", ctx))
    except Exception:
        logger.debug("[guard_pipeline] 守护 LLM 审核调用失败，跳过 LLM 层", exc_info=True)
        return None
    data = _extract_json_obj(reply)
    return data or None


def augment_inspection(
    prompt: str,
    *,
    guards: Optional[Dict[str, Any]] = None,
    prop: Optional[Dict[str, Any]] = None,
    anchor: Optional[Dict[str, Any]] = None,
    character: Optional[Dict[str, Any]] = None,
    use_llm: bool = False,
    llm: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """生成后：守护的**结构化质检**（叠加在管线 LLM 初检之上）。

    两层：
      * **规则层**（永远跑、零 LLM 成本）：道具特征漂移 / 角色特征漂移 —— 定位到具体特征项；
      * **LLM 层**（``use_llm=True`` 且 LLM 可用才跑）：让大模型针对守护维度聚焦审核（更精准）。

    ⚠️ ``use_llm`` **默认 False**（V4.33.5 起）：本函数会被管线**每轮**调用，
    默认调 LLM 意味着 12 轮循环 = 12 次额外费用。需要更精准时显式开。

    Returns::

        {"ok", "issues": [...], "suggestion", "revise_hint", "layers": {"rule","llm"},
         "details": {...}}
    """
    g = guards if isinstance(guards, dict) else {}
    issues: List[str] = []
    layers: Dict[str, Any] = {"rule": False, "llm": False}
    details: Dict[str, Any] = {}

    # ── 规则层 ①：道具漂移 ──
    prop_data = prop if isinstance(prop, dict) else g.get("prop")
    if isinstance(anchor, dict) and anchor.get("traits") and isinstance(prop_data, dict):
        try:
            from .prop_guard import diff_prop_anchor

            d = diff_prop_anchor(anchor, prop_data)
            layers["rule"] = True
            details["prop_drift"] = d
            if not d["ok"]:
                issues.append(f"道具特征漂移（{d['reason']}）")
        except Exception:
            logger.debug("[guard_pipeline] 道具漂移检测失败", exc_info=True)

    # ── 规则层 ②：角色漂移 ──
    ch_data = character if isinstance(character, dict) else g.get("character")
    ch_anchor = g.get("character_anchor")
    if isinstance(ch_anchor, dict) and ch_anchor.get("traits") and isinstance(ch_data, dict):
        try:
            from .character_anchor import diff_anchor

            d = diff_anchor(ch_anchor, ch_data)
            layers["rule"] = True
            details["character_drift"] = d
            if not d["ok"]:
                issues.append(f"角色特征漂移（{d['reason']}）")
        except Exception:
            logger.debug("[guard_pipeline] 角色漂移检测失败", exc_info=True)

    # ── LLM 层：针对守护维度聚焦审核 ──
    # use_llm=False 时**绝不调**（即使显式传了 llm）—— 开关优先，避免「传了 llm 就误烧」。
    _llm = (llm if llm is not None else make_llm()) if use_llm else None
    if _llm is not None:
        verdict = _llm_guard_inspect(_llm, prompt, g)
        if verdict is not None:
            layers["llm"] = True
            details["llm_verdict"] = verdict
            for it in (verdict.get("issues") or []):
                s = str(it).strip()
                if s:
                    issues.append(s)

    suggestion = str((details.get("llm_verdict") or {}).get("suggestion") or "")
    return {
        "ok": not issues,
        "issues": issues,
        "suggestion": suggestion,
        "revise_hint": revise_hint(issues, suggestion),
        "layers": layers,
        "details": details,
    }


def revise_hint(issues: Any, suggestion: str = "") -> str:
    """把守护问题转成**明确的** avoid 提示（补 `_revise_prompt` 的粗糙拼接）。

    返回纯提示串（不含 ``avoid:`` 前缀），调用方自行拼接。
    """
    items = [str(x).strip() for x in (issues or []) if str(x).strip()]
    if not items:
        return str(suggestion or "").strip()
    return "；".join(items)[:160]


# ═══════════════════════════════════════════════════════════
# 守护上下文自动装配（免手填 JSON）
# ═══════════════════════════════════════════════════════════

# 角色库路径 —— 与 character_management_module.CharacterStore 的默认值保持一致
# （⚠️ 那个模块在 stage3d-core 冻结区，故此处**只按路径读 JSON**，不 import 它）
_DEFAULT_CHAR_LIBRARY = ("~", ".video_editor_cache", "characters", "library.json")

# 强情绪词 —— 命中则把表情档位提到 intense
_STRONG_EMOTIONS = ("愤怒", "暴怒", "震怒", "惊恐", "狂喜", "崩溃", "绝望", "嘶吼")


def load_character_from_library(
    name: str,
    *,
    library_path: str = "",
) -> Optional[Dict[str, Any]]:
    """从**角色库**按名字取一个角色条目（只读 JSON）。

    刻意不 import `character_management_module`（它在 stage3d-core 冻结区）——
    直接按 CharacterStore 的默认路径读 ``library.json``，零耦合、零解冻。

    读不到（文件缺失 / 名字不匹配 / JSON 损坏）一律返回 ``None``（诚实降级）。
    """
    import json
    import os

    nm = str(name or "").strip()
    if not nm:
        return None
    path = library_path or os.path.join(
        os.path.expanduser(_DEFAULT_CHAR_LIBRARY[0]), *_DEFAULT_CHAR_LIBRARY[1:])
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        logger.debug("[guard_pipeline] 角色库不可读（%s），跳过自动装配", path, exc_info=True)
        return None
    if not isinstance(data, list):
        return None
    for c in data:
        if isinstance(c, dict) and str(c.get("name") or "").strip() == nm:
            return c
    return None


def build_guards_from_context(
    *,
    character_name: str = "",
    character: Optional[Dict[str, Any]] = None,
    library_path: str = "",
    prop_type: str = "",
    grip: str = "single_hand",
    hand: str = "right",
    off_prop_type: str = "",
    profile: str = "natural",
    emotions: Optional[Any] = None,
    use_llm: bool = False,
    style_dna: str = "",
) -> Dict[str, Any]:
    """**自动装配** guards 上下文 —— 免去手工抄 ``{"character": {...}}`` 这类 JSON。

    来源与优先级：

    ==========  ==========================================================
    角色        ``character``（显式）> ``character_name`` 查**角色库**
    道具        ``prop_type`` 给了才装配（含 grip / hand / 副武器）
    表情        由 ``emotions``（场景情绪列表）推断档位：命中强情绪词 → ``intense``
    风格基因    ``style_dna``（如 "都市逆袭|冷色调"）—— 评分簿按它查历史高分组合
    LLM 开关    ``use_llm`` 写进 guards（默认 False，见 `augment_inspection` 说明）
    ==========  ==========================================================

    Returns 的 dict 可直接传 ``enhance_prompt`` / ``augment_inspection``；
    另附 ``"_sources"`` 说明各项来源 —— 便于排查「为什么某个守护没生效」。
    """
    guards: Dict[str, Any] = {}
    sources: Dict[str, str] = {}

    # ① 角色：显式 > 角色库
    ch = character if isinstance(character, dict) and character else None
    if ch:
        sources["character"] = "explicit"
    elif str(character_name or "").strip():
        ch = load_character_from_library(character_name, library_path=library_path)
        sources["character"] = "library" if ch else "library_miss"
    if ch:
        guards["character"] = ch

    # ② 道具
    if str(prop_type or "").strip():
        prop: Dict[str, Any] = {"prop_type": prop_type, "grip": grip, "hand": hand}
        if str(off_prop_type or "").strip():
            prop["off_prop_type"] = off_prop_type
        guards["prop"] = prop
        sources["prop"] = "params"

    # ③ 表情：由场景情绪推断档位
    emos = [str(e).strip() for e in (emotions or []) if str(e or "").strip()]
    strong = any(k in e for e in emos for k in _STRONG_EMOTIONS)
    if emos or profile:
        guards["expression"] = {
            "profile": "intense" if strong else (profile or "natural"),
            "emotion": emos[0] if emos else "",
        }
        sources["expression"] = (
            f"script({len(emos)} 场景" + ("，强情绪→intense)" if strong else ")")
            if emos else "default"
        )

    guards["use_llm"] = bool(use_llm)
    if str(style_dna or "").strip():
        guards["style_dna"] = str(style_dna).strip()
        sources["style_dna"] = "params"
    guards["_sources"] = sources
    return guards


def describe_guards(guards: Optional[Dict[str, Any]]) -> str:
    """把 guards 装配情况说成人话（供日志 / UI 提示）。"""
    g = guards if isinstance(guards, dict) else {}
    src = g.get("_sources") if isinstance(g.get("_sources"), dict) else {}
    parts = [f"{k}={v}" for k, v in src.items()]
    return "守护已装配：" + ("；".join(parts) if parts else "（空）")


# ═══════════════════════════════════════════════════════════
# 管线便利入口：生成前 + 生成后一次跑完（供管线 / 测试用）
# ═══════════════════════════════════════════════════════════


def run_guard_round(
    prompt: str,
    *,
    guards: Optional[Dict[str, Any]] = None,
    use_llm: bool = False,
    llm: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """跑一轮守护：生成前注入 + 生成后质检（**不真的生成视频**）。

    管线里这两步分别在提示词成型时与初检时发生；本函数把两者串起来，
    供「预览 / 测试 / 干跑（dry-run）」一次拿到完整守护结果。
    """
    before = enhance_prompt(prompt, guards=guards)
    after = augment_inspection(
        before["prompt"], guards=guards, use_llm=use_llm, llm=llm)
    return {
        "ok": after["ok"],
        "prompt": before["prompt"],
        "negative": before["negative"],
        "parts": before["parts"],
        "inspection": after,
        "message": (
            "守护通过（无需修订）" if after["ok"]
            else f"守护发现 {len(after['issues'])} 项问题：{after['revise_hint']}"
        ),
    }
