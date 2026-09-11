# -*- coding: utf-8 -*-
"""Agent Policy Engine（对照 AI Canvas 会话模式，不引入 Tauri）。

产品边界（可执行子集）：
- Plan：只暴露/允许 read
- B 协作：read 自动；canvas/timeline/file/media/memory 写需确认
- C 自主：已注册工具自动执行；付费/写操作零自动重试
- 预算：12 轮模型 / 24 次工具 / 只读最多 3 次重试
- 策略不信任模型自称的风险等级
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

from app.core.agent_action_registry import canvas_action_effect_paid

# 会话模式（新对话默认 B）
MODE_PLAN = "plan"
MODE_COLLABORATIVE = "collaborative"
MODE_AUTONOMOUS = "autonomous"
VALID_MODES: FrozenSet[str] = frozenset({MODE_PLAN, MODE_COLLABORATIVE, MODE_AUTONOMOUS})

EFFECT_READ = "read"
EFFECT_CANVAS_WRITE = "canvas_write"
EFFECT_FILE_WRITE = "file_write"
EFFECT_MEDIA_WRITE = "media_write"
EFFECT_MEMORY_WRITE = "memory_write"

WRITE_EFFECTS: FrozenSet[str] = frozenset(
    {EFFECT_CANVAS_WRITE, EFFECT_FILE_WRITE, EFFECT_MEDIA_WRITE, EFFECT_MEMORY_WRITE}
)

DECISION_ALLOW = "allow"
DECISION_REQUIRE_APPROVAL = "require_approval"
DECISION_DENY = "deny"

MAX_MODEL_ROUNDS = 12
MAX_TOOL_CALLS = 24
MAX_PARALLEL_READS = 3
MAX_READ_RETRIES = 3

# capability_id → (effect, paid)
_CAPABILITY_EFFECTS: Dict[str, Tuple[str, bool]] = {
    "editor.get_timeline_context": (EFFECT_READ, False),
    "editor.suggest_cleanup": (EFFECT_READ, False),
    "editor.send_selected_to_canvas": (EFFECT_CANVAS_WRITE, False),
    "editor.suggest_canvas_roundtrip": (EFFECT_READ, False),
    "model.list_models": (EFFECT_READ, False),
    "ext.list_tools": (EFFECT_READ, False),
    "model.chat": (EFFECT_READ, True),
    "model.chat_with_fallback": (EFFECT_READ, True),
    "editor.split_clip": (EFFECT_CANVAS_WRITE, False),
    "editor.apply_filter": (EFFECT_CANVAS_WRITE, False),
    "editor.add_transition": (EFFECT_CANVAS_WRITE, False),
    "editor.ripple_delete_range": (EFFECT_CANVAS_WRITE, False),
    "canvas.open": (EFFECT_READ, False),
    "canvas.sync_models": (EFFECT_READ, False),
    "canvas.list_actions": (EFFECT_READ, False),
    "ext.run_extension": (EFFECT_FILE_WRITE, False),
    "ext.run_skill": (EFFECT_FILE_WRITE, False),
    "workflow.start": (EFFECT_FILE_WRITE, False),
    "workflow.submit_batch": (EFFECT_FILE_WRITE, False),
    "account.collect_data": (EFFECT_READ, False),
    "account.optimize_strategy": (EFFECT_READ, False),
    "account.publish": (EFFECT_FILE_WRITE, False),
    "pipeline.route": (EFFECT_READ, False),
    "pipeline.preview_validate": (EFFECT_READ, False),
    "pipeline.score": (EFFECT_READ, False),
    "pipeline.generate_script": (EFFECT_READ, True),
    "pipeline.generate": (EFFECT_MEDIA_WRITE, True),
    "pipeline.regenerate_clip": (EFFECT_MEDIA_WRITE, True),
    "pipeline.execute_editing": (EFFECT_CANVAS_WRITE, False),
    "pipeline.run_full": (EFFECT_FILE_WRITE, True),
    "memory.suggest": (EFFECT_MEMORY_WRITE, False),
}

# 画布前端 executeRemoteTask action → (effect, paid)
# 由 agent_action_registry._CANVAS_ACTION_ROWS 派生，保持「同一套 Agent 单一动作清单」，
# 避免两端各自维护一份越改越分裂。
_CANVAS_TOOL_EFFECTS: Dict[str, Tuple[str, bool]] = canvas_action_effect_paid()

# 对话 action → effect（timeline 变更视同 canvas_write）
_EDITOR_ACTION_EFFECTS: Dict[str, Tuple[str, bool]] = {
    "answer": (EFFECT_READ, False),
    "info": (EFFECT_READ, False),
    "get_media": (EFFECT_READ, False),
    "inspect_media": (EFFECT_READ, False),
    "add_track": (EFFECT_CANVAS_WRITE, False),
    "duplicate_clip": (EFFECT_CANVAS_WRITE, False),
    "trim_clip": (EFFECT_CANVAS_WRITE, False),
    "split_clip": (EFFECT_CANVAS_WRITE, False),
    "add_transition": (EFFECT_CANVAS_WRITE, False),
    "transition": (EFFECT_CANVAS_WRITE, False),
    "add_effect": (EFFECT_CANVAS_WRITE, False),
    "apply_filter": (EFFECT_CANVAS_WRITE, False),
    "call_extension": (EFFECT_FILE_WRITE, False),
    "call_model": (EFFECT_READ, True),
    "start_workflow": (EFFECT_FILE_WRITE, False),
    "account_optimize": (EFFECT_READ, False),
    "suggest_cleanup": (EFFECT_READ, False),
    "canvas_sync_models": (EFFECT_READ, False),
    "canvas_open": (EFFECT_READ, False),
    "remove_clip": (EFFECT_CANVAS_WRITE, False),
    "ripple_delete": (EFFECT_CANVAS_WRITE, False),
    "ripple_delete_range": (EFFECT_CANVAS_WRITE, False),
    "move_clip": (EFFECT_CANVAS_WRITE, False),
    "change_speed": (EFFECT_CANVAS_WRITE, False),
    "add_keyframe": (EFFECT_CANVAS_WRITE, False),
    "set_keyframes": (EFFECT_CANVAS_WRITE, False),
}

_SECRET_KEYS = frozenset(
    {"api_key", "apikey", "token", "password", "secret", "authorization", "access_key"}
)


@dataclass(frozen=True)
class PolicyDecision:
    action: str  # allow | require_approval | deny
    effect: str
    paid: bool
    reason: str
    mode: str
    tool_id: str = ""


def normalize_mode(mode: Optional[str]) -> str:
    raw = (mode or "").strip().lower()
    if raw in ("execute", "b", "collab", "collaborative"):
        return MODE_COLLABORATIVE
    if raw in ("c", "auto", "autonomous"):
        return MODE_AUTONOMOUS
    if raw in ("plan", "planning", "readonly"):
        return MODE_PLAN
    if raw in VALID_MODES:
        return raw
    return MODE_COLLABORATIVE


def lookup_tool(tool_id: str) -> Tuple[str, bool]:
    tid = (tool_id or "").strip()
    if tid in _CANVAS_TOOL_EFFECTS:
        return _CANVAS_TOOL_EFFECTS[tid]
    if tid in _CAPABILITY_EFFECTS:
        return _CAPABILITY_EFFECTS[tid]
    if tid in _EDITOR_ACTION_EFFECTS:
        return _EDITOR_ACTION_EFFECTS[tid]
    # 未登记工具：按写操作处理，避免模型自报「只读」越权
    return EFFECT_FILE_WRITE, False


def decide(
    *,
    tool_id: str,
    mode: Optional[str] = None,
    approved: bool = False,
    effect: Optional[str] = None,
    paid: Optional[bool] = None,
) -> PolicyDecision:
    """策略引擎：不信任调用方声称的风险，只认注册表 + 模式。"""
    m = normalize_mode(mode)
    registered_effect, registered_paid = lookup_tool(tool_id)
    eff = effect if effect in WRITE_EFFECTS or effect == EFFECT_READ else registered_effect
    is_paid = registered_paid if paid is None else bool(paid)

    if m == MODE_PLAN and eff != EFFECT_READ:
        if approved:
            return PolicyDecision(
                action=DECISION_ALLOW,
                effect=eff,
                paid=is_paid,
                reason="Plan 已由用户确认执行",
                mode=m,
                tool_id=tool_id,
            )
        return PolicyDecision(
            action=DECISION_DENY,
            effect=eff,
            paid=is_paid,
            reason="Plan 模式禁止非只读工具",
            mode=m,
            tool_id=tool_id,
        )
    if m == MODE_AUTONOMOUS or eff == EFFECT_READ:
        return PolicyDecision(
            action=DECISION_ALLOW,
            effect=eff,
            paid=is_paid,
            reason="自主模式自动执行" if m == MODE_AUTONOMOUS else "只读自动执行",
            mode=m,
            tool_id=tool_id,
        )
    # B：写操作需确认
    if approved:
        return PolicyDecision(
            action=DECISION_ALLOW,
            effect=eff,
            paid=is_paid,
            reason="协作模式已确认",
            mode=m,
            tool_id=tool_id,
        )
    return PolicyDecision(
        action=DECISION_REQUIRE_APPROVAL,
        effect=eff,
        paid=is_paid,
        reason="协作模式：写操作需用户确认",
        mode=m,
        tool_id=tool_id,
    )


def can_auto_retry(*, effect: str, paid: bool, attempt: int) -> bool:
    """只读且非付费：最多 3 次。画布写 / 文件写 / 媒体 / 付费：永不自动重试。"""
    if paid or effect in WRITE_EFFECTS:
        return False
    return 0 <= attempt < MAX_READ_RETRIES


def list_canvas_tools_for_mode(mode: Optional[str] = None) -> list:
    m = normalize_mode(mode)
    rows = []
    for action, (eff, paid) in _CANVAS_TOOL_EFFECTS.items():
        if m == MODE_PLAN and eff != EFFECT_READ:
            continue
        rows.append(
            {
                "tool_id": action,
                "tool_name": action,
                "extension_id": "canvas",
                "extension_name": "导演台画布",
                "extension_type": "canvas",
                "description": f"画布工具 · {eff}",
                "effect": eff,
                "paid": paid,
            }
        )
    return rows


def tools_visible_to_model(mode: Optional[str] = None) -> FrozenSet[str]:
    m = normalize_mode(mode)
    ids = set(_CANVAS_TOOL_EFFECTS) | set(_CAPABILITY_EFFECTS) | set(_EDITOR_ACTION_EFFECTS)
    if m != MODE_PLAN:
        return frozenset(ids)
    keep = set()
    for tid in ids:
        eff, _ = lookup_tool(tid)
        if eff == EFFECT_READ:
            keep.add(tid)
    return frozenset(keep)


def sanitize_for_log(payload) -> object:
    """脱敏：去掉密钥字段与过长绝对路径，供任务日志/记忆。"""
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            lk = str(k).lower()
            if lk in _SECRET_KEYS or "api_key" in lk or lk.endswith("_token"):
                out[k] = "[redacted]"
            else:
                out[k] = sanitize_for_log(v)
        return out
    if isinstance(payload, list):
        return [sanitize_for_log(x) for x in payload[:40]]
    if isinstance(payload, str):
        s = payload
        if len(s) > 400:
            s = s[:400] + "…"
        if len(s) > 3 and (s[1:3] == ":\\" or s.startswith("/home/") or s.startswith("/Users/")):
            return "[path]"
        return s
    return payload


def memory_content_allowed(content: dict) -> Tuple[bool, str]:
    """长期记忆禁止：全文网页、API Key、绝对路径、临时工具结果。"""
    blob = str(content or "")
    low = blob.lower()
    if "api_key" in low or "sk-" in low or "bearer " in low:
        return False, "记忆不得包含密钥"
    if ":\\" in blob or blob.count("/home/") + blob.count("/Users/") > 0:
        return False, "记忆不得包含绝对路径"
    if len(blob) > 4000:
        return False, "记忆正文过长（疑似全文）"
    return True, ""


def mode_prompt_block(mode: Optional[str] = None) -> str:
    m = normalize_mode(mode)
    if m == MODE_PLAN:
        return (
            "\n[Agent 模式 · Plan]\n"
            "只分析、规划、只读查询。不要输出会改时间线/画布/生成媒体的指令。"
            "规划用 {\"plan\":[...],\"commands\":[...]}，commands 须可被用户确认后执行。\n"
        )
    if m == MODE_AUTONOMOUS:
        return (
            "\n[Agent 模式 · 自主 C]\n"
            "可输出白名单内的执行指令，系统将自动落地。"
            "付费生成失败不要暗示会自动重试；破坏性删除仍须合法 action。\n"
        )
    return (
        "\n[Agent 模式 · 协作 B]\n"
        "只读查询可直接做；改时间线/画布/生成媒体前先给出计划，等用户确认。"
        "删除类用 ripple_delete_range / remove_clip，系统会二次确认。\n"
    )


def canvas_tools_prompt_block(mode: Optional[str] = None) -> str:
    m = normalize_mode(mode)
    if m == MODE_PLAN:
        return "不要输出 canvas_tools JSON。\n"
    return (
        "需要改画布时，在中文说明后追加 JSON："
        '{"canvas_tools":[{"action":"addNode","params":{"kind":"shot","title":"镜头"}}]}。'
        "允许 action：queryNodes,selectNode,addNode,updateNode,connectNodes,deleteNode,"
        "duplicateNode,groupNodes,runGenerate,undo,redo,setNodeImage,importImage,"
        "breakdown,fillStoryboardCell。"
        "收到剧本文本并需要拆解为分镜时，必须用 breakdown 并携带剧本："
        '{"action":"breakdown","params":{"script":"完整剧本文本"}}。'
        "不要编造未列出的 action。\n"
    )
