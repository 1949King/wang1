# -*- coding: utf-8 -*-
"""Agent 主动建议引擎（状态 → 建议规则表）。

与 ``agent_brain.suggest_next`` 的分工（勿混用）：
  - ``suggest_next(from_id, candidates, ...)`` 是**被动决策**：调用方喂候选，
    大脑按突触权重在候选里选最优。
  - 本模块是**主动建议**：根据时间线/项目**状态快照**生成「下一步该做什么」的
    候选清单（规则表驱动，确定性、无随机），再交 UI 展示，用户点「采纳」执行。

规则表是唯一事实源；新增建议只需往 ``_RULES`` 加一行。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# 建议执行类型
KIND_CAPABILITY = "capability"     # 走 capability dispatcher（_agent_dispatch）
KIND_EDITOR_METHOD = "editor_method"  # 走 editor 直接方法（如 apply_aesthetic_pack）


def _clip_count(state: Dict[str, Any]) -> int:
    try:
        return int(state.get("clip_count", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _has(state: Dict[str, Any], key: str) -> bool:
    return bool(state.get(key))


# ── 规则表 ──────────────────────────────────────────────────
# 每条规则：id 唯一；condition(state) 命中才产出建议；
# priority 越大越靠前；suggest() 对同一 id 只取一条。
_RULES: List[Dict[str, Any]] = [
    {
        "id": "apply_aesthetic_pack",
        "title": "为当前片段套用美学预设包",
        "description": "一键叠加 LUT + 调色 + 转场，快速统一风格",
        "kind": KIND_EDITOR_METHOD,
        "target": "apply_aesthetic_pack",
        "params": {"pack_id": "aesthetic_pack_cinema"},
        "icon": "🎬",
        "priority": 100,
        "condition": lambda s: _clip_count(s) > 0 and not _has(s, "selected_has_color"),
    },
    {
        "id": "add_transition",
        "title": "片段间补充转场",
        "description": "多片段拼接处缺转场，建议加淡入淡出过渡",
        "kind": KIND_CAPABILITY,
        "target": "editor.add_transition",
        "params": {"transition_type": "fade", "duration": 0.5},
        "icon": "🔁",
        "priority": 90,
        "condition": lambda s: _clip_count(s) >= 2 and not _has(s, "has_transition"),
    },
    {
        "id": "color_grade",
        "title": "给当前片段做基础调色",
        "description": "提升画面质感（对比度 / 饱和度 / 曝光）",
        "kind": KIND_CAPABILITY,
        "target": "editor.apply_filter",
        "params": {"filter_name": "电影", "intensity": 0.7},
        "icon": "🎨",
        "priority": 80,
        "condition": lambda s: _clip_count(s) > 0 and not _has(s, "selected_has_color"),
    },
    {
        "id": "add_subtitle",
        "title": "为成片添加字幕",
        "description": "提升完播率与可看性，建议识别对白加字幕",
        "kind": KIND_CAPABILITY,
        "target": "editor.suggest_cleanup",
        "params": {"open_ui": True},
        "icon": "💬",
        "priority": 70,
        "condition": lambda s: _clip_count(s) > 0 and not _has(s, "has_subtitle"),
    },
    {
        "id": "export",
        "title": "导出成片",
        "description": "素材已就绪，可进入导出流程",
        "kind": KIND_CAPABILITY,
        "target": "pipeline.export",
        "params": {},
        "icon": "📤",
        "priority": 60,
        "condition": lambda s: _clip_count(s) > 0 and _has(s, "is_export_ready"),
    },
]


def suggest_next_actions(state: Optional[Dict[str, Any]],
                         limit: int = 5) -> List[Dict[str, Any]]:
    """根据项目状态快照生成「下一步建议」清单（确定性、无随机）。

    Args:
        state: 状态快照，字段见 ``collect_proactive_state``（clip_count /
            has_transition / has_subtitle / selected_has_color / is_export_ready 等）。
        limit: 最多返回几条（按 priority 降序）。

    Returns:
        建议列表，每条含 id/title/description/kind/target/params/icon/priority。
    """
    state = state or {}
    hits: List[Dict[str, Any]] = []
    seen = set()
    for rule in sorted(_RULES, key=lambda r: -int(r.get("priority", 0))):
        rid = rule["id"]
        if rid in seen:
            continue
        try:
            matched = bool(rule["condition"](state))
        except Exception:
            matched = False
        if not matched:
            continue
        seen.add(rid)
        hits.append({
            "id": rid,
            "title": rule["title"],
            "description": rule["description"],
            "kind": rule["kind"],
            "target": rule["target"],
            "params": dict(rule.get("params") or {}),
            "icon": rule.get("icon", "✨"),
            "priority": int(rule.get("priority", 0)),
        })
    return hits[:max(0, int(limit))]


def collect_proactive_state(editor) -> Dict[str, Any]:
    """从 EditorModule 收集主动建议所需的状态快照。

    刻意只读、不写、不 import UI 层；editor 为 None 或缺字段时返回空快照。
    """
    if editor is None:
        return {}
    clips = list(getattr(editor, "_clips", []) or [])
    state: Dict[str, Any] = {
        "clip_count": len(clips),
        "has_transition": any(c.get("transition") for c in clips if isinstance(c, dict)),
        "has_subtitle": bool(getattr(editor, "_subtitles", None)),
        "selected_has_color": False,
        "is_export_ready": len(clips) > 0,
    }
    current = getattr(editor, "_current_clip", None)
    if isinstance(current, dict):
        effects = current.get("effects") or {}
        if isinstance(effects, dict):
            cp = effects.get("color_params") or {}
            state["selected_has_color"] = bool(
                cp or effects.get("filter")
            )
        state["selected_has_color"] = state["selected_has_color"] or bool(current.get("filter"))
    return state
