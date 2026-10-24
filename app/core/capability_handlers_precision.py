# -*- coding: utf-8 -*-
"""精剪能力处理器（2026-10-20 · 精剪线）

只读薄壳：取 editor → 读 `_clips` → 委托 `app.core.precision_edit` 纯函数。
**不写时间线**（对齐计划只出计划，写回动作留给下一刀并走 store API + 撤销）。
"""
from __future__ import annotations

from typing import Any, Dict

try:
    from app.core.capability_dispatcher import (
        CapabilityCategory,
        CapabilityRequest,
        CapabilityResult,
    )
    from app.core.precision_edit import audit_timeline, plan_frame_align
except ImportError:  # 兼容 `core.*` 旧导入路径
    from core.capability_dispatcher import (  # type: ignore
        CapabilityCategory,
        CapabilityRequest,
        CapabilityResult,
    )
    from core.precision_edit import audit_timeline, plan_frame_align  # type: ignore


class PrecisionCapabilityHandlers:
    """帧级精剪：审计 + 对齐计划（均只读）。"""

    def __init__(self, editor_module_ref):
        self._get_editor = editor_module_ref

    def _clips(self, req: CapabilityRequest):
        editor = self._get_editor()
        if editor is None:
            return None, None, self._fail(req, "EditorModule 未就绪（先打开剪辑模块）")
        clips = list(getattr(editor, "_clips", []) or [])
        return editor, clips, None

    @staticmethod
    def _fail(req: CapabilityRequest, msg: str) -> CapabilityResult:
        return CapabilityResult(req.request_id, False, error=msg)

    @staticmethod
    def _fps(editor: Any, params: Dict[str, Any]) -> float:
        raw = params.get("fps")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
            return float(raw)
        widget = getattr(editor, "_timeline_widget", None)
        value = getattr(widget, "_edit_fps", 0) if widget is not None else 0
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return 30.0

    def precision_audit(self, req: CapabilityRequest) -> CapabilityResult:
        """帧级精剪审计：越界/次帧缝隙/重叠/非帧网格/音画偏移。"""
        editor, clips, failure = self._clips(req)
        if failure is not None:
            return failure
        params = req.params or {}
        report = audit_timeline(
            clips,
            self._fps(editor, params),
            tolerance_frames=float(params.get("tolerance_frames", 0.1) or 0.1),
            include_av=bool(params.get("include_av", True)),
        )
        return CapabilityResult(req.request_id, True, output=report, error=None)

    def precision_align_plan(self, req: CapabilityRequest) -> CapabilityResult:
        """帧对齐计划（只算不改）：吸附 start_time/duration 并同步 out_point。"""
        editor, clips, failure = self._clips(req)
        if failure is not None:
            return failure
        params = req.params or {}
        try:
            max_changes = int(params.get("max_changes", 200) or 200)
        except (TypeError, ValueError):
            max_changes = 200
        plan = plan_frame_align(
            clips,
            self._fps(editor, params),
            max_changes=max(1, min(max_changes, 2000)),
        )
        return CapabilityResult(req.request_id, True, output=plan, error=None)


    def precision_align_apply(self, req: CapabilityRequest) -> CapabilityResult:
        """按帧对齐计划写回（store 唯一写缝 + 一条 compound 撤销）。

        边界：只写 plan 里的 start_time/duration/out_point；不修重叠/大缝隙（需波纹语义）；
        编辑主体不是 `_clips` 行本体时由 `_apply_clip_fields` 自行校验（刀8 安全带）。
        """
        editor, clips, failure = self._clips(req)
        if failure is not None:
            return failure
        if not hasattr(editor, "_apply_clip_fields") or not hasattr(editor, "_record_action"):
            return self._fail(req, "EditorModule 缺少字段写/撤销接口，拒绝无撤销写回")
        params = req.params or {}
        try:
            max_changes = int(params.get("max_changes", 200) or 200)
        except (TypeError, ValueError):
            max_changes = 200
        plan = plan_frame_align(
            clips, self._fps(editor, params),
            max_changes=max(1, min(max_changes, 2000)),
        )
        changes = plan.get("changes") or []
        if not changes:
            return CapabilityResult(
                req.request_id, True,
                output={"applied": 0, "plan": plan, "note": "无需对齐（已在帧网格）"},
                error=None,
            )
        by_id = {str(c.get("id")): c for c in clips}
        steps = []
        for change in changes:
            clip = by_id.get(str(change.get("clip_id")))
            if clip is None:
                continue
            before = {k: v for k, v in (change.get("before") or {}).items() if v is not None}
            after = {k: v for k, v in (change.get("after") or {}).items() if v is not None}
            if not after or before == after:
                continue
            editor._apply_clip_fields(clip, after)
            steps.append({
                "type": "edit_clip", "clip_id": change.get("clip_id"),
                "before": before, "after": after,
            })
        if steps:
            editor._record_action({
                "type": "compound", "label": "precision_align", "steps": steps,
            })
            if hasattr(editor, "_touch_project_dirty"):
                editor._touch_project_dirty()
        return CapabilityResult(
            req.request_id, True,
            output={
                "applied": len(steps),
                "skipped": plan.get("skipped") or [],
                "note": "已写回并可一次撤销；重叠/大缝隙未自动修（需波纹语义）",
            },
            error=None,
        )


def register_precision_handlers(dispatcher, editor_module_ref) -> None:
    """注册到中央 dispatcher（把注册细节留在能力模块，中央文件不再逐条堆）。"""
    handlers = PrecisionCapabilityHandlers(editor_module_ref)
    dispatcher.register(
        "editor.precision_audit", CapabilityCategory.EDITOR,
        handlers.precision_audit,
        "帧级精剪审计：非帧网格/次帧缝隙/重叠/音画偏移（只读）",
    )
    dispatcher.register(
        "editor.precision_align_plan", CapabilityCategory.EDITOR,
        handlers.precision_align_plan,
        "帧对齐计划：吸附 start_time/duration 并同步 out_point（只出计划，不改时间线）",
    )
    dispatcher.register(
        "editor.precision_align_apply", CapabilityCategory.EDITOR,
        handlers.precision_align_apply,
        "帧对齐写回：按计划改 store 并记一条 compound 撤销",
    )
