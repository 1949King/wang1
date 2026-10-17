# -*- coding: utf-8 -*-
"""§6.9-P2 小白闭环自动粗剪合链（方案 1：纯 core 层冻结区外合链，2026-10-17）

链路：入库 → 规则排轨 → 水词/长静音检测（B2）→ 波纹删除 + 合缝（B1）
      → 审核卡（确认后执行）→ 写回时间线（可撤销）→ 导出成片（委托既有精剪入口）

设计纪律（对齐 .trae/rules 与 docs/现行技术文档.md）：
  - plan() 只算不改数据；提案永远 needs_confirmation=True，
    apply() 未带 confirmed=True 一律拒绝执行——「确认后执行」纪律不可绕过。
  - 写回全部复用 B1 edit_commands（纯函数 + edit_clip steps），
    整链复合步骤合并为一条 compound 撤销条目（与 ripple_delete_intervals 同套路）。
  - 不动冻结区：小白审核卡是画布纯渲染层，Python 侧广播 CUSTOM 事件
    （subtype=rough_cut_plan_ready / rough_cut_applied）供剪辑侧栏消费，
    并经 push_to_canvas("rough_cut.review") 同 payload 推画布壳层审核卡
    （2026-10-17 接线；确认/导出回写走 /host/rough-cut/* 端点）。
  - 导出委托 EditorModule.agent_execute_pipeline_editing（既有成片输出入口），
    不在 core 层拼 FFmpeg 命令。
  - 入库复用 preview_validation_loop.load_clips_to_timeline（既有事件路径），
    时间线 id 若被编辑器重新生成，按 source_clip_id 别名回退解析。
"""
from __future__ import annotations

import copy
import logging
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence

from app.core.edit_commands import (
    close_track_gaps,
    ripple_delete_timeline_range,
)
from app.core.filler_silence_detect import (
    CleanupConfig,
    build_cleanup_plan_from_subtitles,
    build_cleanup_plan_from_whisper,
)

logger = logging.getLogger(__name__)

_EPS = 1e-4
#: 内存中最多保留的提案数（防泄漏，只留最近 N 条）
_MAX_PLANS = 20
#: 写回后磁吸合缝的默认阈值（与 B1 close_track_gaps 缺省一致）
_DEFAULT_GAP_THRESHOLD = 0.05


def _broadcast(subtype: str, payload: Dict[str, Any]) -> None:
    """广播 CUSTOM 事件（审核卡/回写通知）；无 UI 环境（守卫/测试）静默降级。

    双通道（2026-10-17 画布审核卡接线）：
      ① Qt EventBus.CUSTOM —— 剪辑侧栏既有消费路径，行为不变；
      ② 画布 SSE push_to_canvas("rough_cut.review") —— 画布壳层审核卡
         （RoughCutReviewDock）消费；桥未就绪时 push_to_canvas 内部
         静默降级，不影响 ① 与提案主流程。
    """
    try:
        from app.modules.lego.core import EventBus, EventType
        EventBus.get_instance().emit(
            EventType.CUSTOM, {"subtype": subtype, **payload}, source="RoughCutChain",
        )
    except Exception as e:
        logger.debug(f"[rough_cut] 事件广播失败（忽略）: {e}")
    try:
        from app.core.project_agent_host import push_to_canvas
        push_to_canvas("rough_cut.review", {"subtype": subtype, **payload})
    except Exception as e:
        logger.debug(f"[rough_cut] 画布 SSE 推送失败（忽略）: {e}")


def _clip_dur(clip: Dict[str, Any]) -> float:
    return max(0.0, float(clip.get("duration", 0) or 0))


def _clip_start(clip: Dict[str, Any]) -> float:
    return float(clip.get("start_time", 0) or 0)


def build_clips_from_materials(
    materials: Sequence[Dict[str, Any]],
    *,
    default_duration: float = 5.0,
    track: int = 0,
) -> List[Dict[str, Any]]:
    """materials → B1 clip dict：按出现顺序从 0 紧排（规则排轨的「规则」即顺序）。

    每项素材形如 {"clip_id"/"id", "path", "duration", "source", "prompt"}；
    缺时长用 default_duration 兜底，非法项跳过（诚实：不造幽灵片段）。
    """
    clips: List[Dict[str, Any]] = []
    cursor = 0.0
    for m in materials or []:
        if not isinstance(m, dict):
            continue
        path = str(m.get("path") or m.get("video_path") or "")
        cid = str(m.get("clip_id") or m.get("id") or f"rc_{uuid.uuid4().hex[:10]}")
        try:
            dur = float(m.get("duration") or default_duration)
        except (TypeError, ValueError):
            dur = float(default_duration)
        dur = max(0.1, dur)
        clips.append({
            "id": cid,
            "path": path,
            "duration": dur,
            "start_time": cursor,
            "track": int(m.get("track", track) or track),
            "in_point": 0.0,
            "out_point": dur,
            "type": str(m.get("type") or "video"),
        })
        cursor += dur
    return clips


class RoughCutChain:
    """粗剪合链状态机：plan（提案，不改数据）→ apply（确认后写回）→ export（委托出片）。

    提案存内存（最近 _MAX_PLANS 条）；跨进程恢复不在本刀范围（文档 §6.9-P2 只要求
    「一条队列跑通」，落盘持久化留给后续刀，避免过度设计）。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._plans: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    # ── 提案查询 ────────────────────────────────────────────────
    def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """按 plan_id 取提案快照引用（调用方只读，勿直接改）。"""
        with self._lock:
            return self._plans.get(str(plan_id or ""))

    def list_plans(self, limit: int = 10) -> List[Dict[str, Any]]:
        """近期提案摘要列表（审核卡列表面用，只读）。"""
        with self._lock:
            items = list(self._plans.values())[-max(1, min(50, int(limit or 10))):]
        return [
            {
                "plan_id": p["plan_id"],
                "label": p["label"],
                "mode": p["mode"],
                "status": p["status"],
                "needs_confirmation": p["needs_confirmation"],
                "original_duration": p["original_duration"],
                "predicted_duration": p["predicted_duration"],
                "deleted_duration": p["deleted_duration"],
                "interval_count": len(p["intervals"]),
                "warnings": p["warnings"],
                "created_at": p["created_at"],
            }
            for p in items
        ]

    # ── ① plan：规则排轨 + B2 检测（只算不改）─────────────────────
    def plan(
        self,
        clips: Sequence[Dict[str, Any]],
        *,
        mode: str = "timeline",
        asr_by_clip: Optional[Dict[str, Sequence[Dict[str, Any]]]] = None,
        subtitles: Optional[Sequence[Dict[str, Any]]] = None,
        cleanup_config: Optional[CleanupConfig] = None,
        label: str = "",
        request_id: str = "",
    ) -> Dict[str, Any]:
        """生成粗剪提案：排轨（磁吸紧排）→ 逐片段水词/静音检测 → 模拟删除预测时长。

        参数：
            clips: B1 clip dict 列表（timeline 模式传时间线快照；
                   materials 模式传 build_clips_from_materials 的产物）
            asr_by_clip: {clip_id: whisper segments}（source_relative）
            subtitles: 时间线绝对字幕条目（{"start_time","end_time","text"}），
                       按片段覆盖范围自动分配
        返回：{"ok": True, "proposal": {...}} 或 {"ok": False, "error": "..."}
        """
        if mode not in ("timeline", "materials"):
            return {"ok": False, "error": f"未知模式 {mode}（仅支持 timeline / materials）"}
        working = [copy.deepcopy(c) for c in clips or [] if isinstance(c, dict) and c.get("id")]
        if not working:
            return {"ok": False, "error": "没有可粗剪的片段（clips 为空或缺 id）"}

        cfg = cleanup_config or CleanupConfig()
        warnings: List[str] = []

        # ① 规则排轨：同轨按 start_time 顺序紧排（复用 B1 磁吸，gap_threshold=0 ⇒ 全合缝）
        layout_res = close_track_gaps(working, gap_threshold=0.0)
        laid = layout_res.clips
        if not layout_res.ok and layout_res.message:
            warnings.append(f"排轨提示：{layout_res.message}")

        # ② B2 检测：逐片段跑水词/长静音（无 ASR/字幕数据的片段如实跳过）
        intervals: List[Dict[str, Any]] = []
        dense_hit = False
        asr_map = asr_by_clip or {}
        subs_all = [s for s in (subtitles or []) if isinstance(s, dict)]
        for clip in laid:
            cid = str(clip.get("id"))
            track = int(clip.get("track", 0) or 0)
            segs = asr_map.get(cid)
            plan_src = None
            if segs:
                plan_src = build_cleanup_plan_from_whisper(list(segs), clip, cfg)
            else:
                c_start = _clip_start(clip)
                c_end = c_start + _clip_dur(clip)
                subs_for_clip = [
                    s for s in subs_all
                    if float(s.get("end_time", 0) or 0) > c_start + _EPS
                    and float(s.get("start_time", 0) or 0) < c_end - _EPS
                ]
                if subs_for_clip:
                    plan_src = build_cleanup_plan_from_subtitles(subs_for_clip, clip, cfg)
            if plan_src is None:
                warnings.append(f"片段 {cid} 无 ASR/字幕数据，跳过水词/静音检测")
                continue
            dense_hit = dense_hit or plan_src.is_dense_dialogue
            for iv in plan_src.intervals:
                intervals.append({
                    "clip_id": cid,
                    "track": track,
                    "timeline_in": round(float(iv.timeline_in), 4),
                    "timeline_out": round(float(iv.timeline_out), 4),
                    "kind": iv.kind,
                    "text": iv.text,
                })
        if dense_hit:
            warnings.append("检测到密集对白（短剧类）：删除区间请务必人工核对")

        # ③ 模拟删除 + 合缝 → 预测成片时长（纯函数演练，不落数据）
        sim = [copy.deepcopy(c) for c in laid]
        for iv in sorted(intervals, key=lambda x: float(x["timeline_in"]), reverse=True):
            r = ripple_delete_timeline_range(
                sim, float(iv["timeline_in"]), float(iv["timeline_out"]),
                track=int(iv.get("track", 0) or 0),
            )
            sim = r.clips
        sim = close_track_gaps(sim, gap_threshold=_DEFAULT_GAP_THRESHOLD).clips
        original_duration = sum(_clip_dur(c) for c in laid)
        predicted_duration = sum(_clip_dur(c) for c in sim)

        proposal: Dict[str, Any] = {
            "plan_id": uuid.uuid4().hex[:12],
            "created_at": time.time(),
            "label": str(label or ""),
            "mode": mode,
            "request_id": str(request_id or ""),
            "needs_confirmation": True,
            "status": "pending_confirmation",
            "applied": False,
            "clip_ids": [str(c.get("id")) for c in laid],
            # 目标排轨快照：apply 时按此写 start_time（可撤销）
            "layout": [
                {
                    "id": str(c.get("id")),
                    "track": int(c.get("track", 0) or 0),
                    "start_time": round(_clip_start(c), 4),
                    "duration": round(_clip_dur(c), 4),
                }
                for c in laid
            ],
            "intervals": intervals,
            "original_duration": round(original_duration, 3),
            "predicted_duration": round(predicted_duration, 3),
            "deleted_duration": round(original_duration - predicted_duration, 3),
            "warnings": warnings,
        }
        with self._lock:
            self._plans[proposal["plan_id"]] = proposal
            while len(self._plans) > _MAX_PLANS:
                self._plans.popitem(last=False)

        # 审核卡数据广播（画布/面板纯渲染层消费；无 UI 环境静默）
        # intervals 一并带上（2026-10-17 画布审核卡）：「确认后执行」要求用户
        # 能逐条核对删除区间，只给汇总数等于没法审。
        _broadcast("rough_cut_plan_ready", {
            "plan_id": proposal["plan_id"],
            "request_id": proposal["request_id"],
            "summary": {k: proposal[k] for k in (
                "original_duration", "predicted_duration", "deleted_duration",
            )} | {"interval_count": len(intervals)},
            "intervals": intervals,
            "warnings": warnings,
            "message": "粗剪提案已生成，请审核后确认执行",
        })
        logger.info(
            "[rough_cut] 提案 %s：%d 片段 / %d 待删区间 / 预计 %.2fs→%.2fs",
            proposal["plan_id"], len(laid), len(intervals),
            original_duration, predicted_duration,
        )
        return {"ok": True, "proposal": proposal}

    # ── ② apply：确认后写回（可撤销）─────────────────────────────
    def apply(self, editor: Any, plan_id: str, *, confirmed: bool = False) -> Dict[str, Any]:
        """把提案写回 editor._clips：排轨 → 波纹删除（右→左）→ 磁吸合缝，一条 compound 撤销。

        纪律：confirmed 必须显式为 True（审核卡「确认后执行」不可绕过）；
        时间线相对提案已变化（片段增删/改时长）时拒绝执行，要求重新 plan。
        """
        if not confirmed:
            return {"ok": False, "error": "粗剪写回需显式确认（confirmed=True）：请先在审核卡核对删除区间再执行"}
        proposal = self.get_plan(plan_id)
        if proposal is None:
            return {"ok": False, "error": f"提案不存在或已过期：{plan_id}"}
        if proposal["applied"]:
            return {"ok": False, "error": "该提案已写回，不允许重复执行；如需重剪请重新生成提案"}
        if editor is None:
            return {"ok": False, "error": "EditorModule 未就绪"}
        live = getattr(editor, "_clips", None)
        if live is None:
            return {"ok": False, "error": "EditorModule 缺少 _clips 时间线真相源"}

        layout_by_id = {row["id"]: row for row in proposal["layout"]}
        # 别名索引：入库后编辑器可能重新生成 id，source_clip_id 别名兜底
        by_alias: Dict[str, Dict[str, Any]] = {}
        for c in live:
            if isinstance(c, dict) and c.get("id"):
                by_alias.setdefault(str(c["id"]), c)
                alias = c.get("source_clip_id")
                if alias:
                    by_alias.setdefault(str(alias), c)
        missing = [pid for pid in proposal["clip_ids"] if pid not in by_alias]
        if missing:
            hint = ("materials 模式请先完成入库（load_clips_to_timeline 落轨）"
                    if proposal["mode"] == "materials" else "请重新生成提案")
            return {"ok": False, "error": f"时间线与提案不一致（缺片段 {missing[:3]}），{hint}"}
        if proposal["mode"] == "timeline":
            # 陈旧守卫：片段集合与时长必须与提案一致，否则删除坐标会错位
            live_ids = {str(c.get("id")) for c in live if isinstance(c, dict) and c.get("id")}
            if live_ids != set(proposal["clip_ids"]):
                return {"ok": False, "error": "时间线已变化（片段增删），请重新生成粗剪提案再写回"}
            for pid in proposal["clip_ids"]:
                lc = by_alias.get(pid) or {}
                if abs(_clip_dur(lc) - float(layout_by_id[pid]["duration"])) > 0.01:
                    return {"ok": False, "error": f"片段 {pid} 时长已变化，请重新生成粗剪提案再写回"}

        working = [copy.deepcopy(c) for c in live]
        w_alias: Dict[str, Dict[str, Any]] = {}
        for c in working:
            if c.get("id"):
                w_alias.setdefault(str(c["id"]), c)
                alias = c.get("source_clip_id")
                if alias:
                    w_alias.setdefault(str(alias), c)
        steps: List[Dict[str, Any]] = []

        # ① 排轨：按提案 layout 写 start_time（B1 edit_clip step 格式，可撤销）
        for row in proposal["layout"]:
            wc = w_alias.get(row["id"])
            if wc is None:
                continue
            old = _clip_start(wc)
            new = float(row["start_time"])
            if abs(new - old) > _EPS:
                before = {
                    "start_time": old,
                    "track": int(wc.get("track", 0) or 0),
                    "duration": _clip_dur(wc),
                    "in_point": float(wc.get("in_point", 0) or 0),
                    "out_point": float(wc.get("out_point", 0) or 0),
                }
                wc["start_time"] = new
                after = dict(before)
                after["start_time"] = new
                steps.append({"type": "edit_clip", "clip_id": wc.get("id"),
                              "before": before, "after": after})

        # ② 波纹删除：从右向左逐区间（防坐标失效），按区间所属轨执行
        deleted_count = 0
        for iv in sorted(proposal["intervals"], key=lambda x: float(x["timeline_in"]), reverse=True):
            r = ripple_delete_timeline_range(
                working, float(iv["timeline_in"]), float(iv["timeline_out"]),
                track=int(iv.get("track", 0) or 0),
            )
            working = r.clips
            if r.ok:
                deleted_count += 1
            steps.extend(r.steps)

        # ③ 磁吸合缝兜底（删除后可能露出新缝）
        gap_res = close_track_gaps(working, gap_threshold=_DEFAULT_GAP_THRESHOLD)
        working = gap_res.clips
        steps.extend(gap_res.steps)

        undo_action = {"type": "compound", "steps": steps, "label": "rough_cut_apply"}
        live[:] = working
        recorder = getattr(editor, "_record_action", None)
        if callable(recorder):
            recorder(undo_action)

        final_duration = sum(_clip_dur(c) for c in working)
        proposal["applied"] = True
        proposal["status"] = "applied"
        # 成片顺序快照（供 export 委托精剪入口时按轨+时间排序引用）
        proposal["applied_clip_order"] = [
            str(c.get("id")) for c in
            sorted(working, key=lambda c: (int(c.get("track", 0) or 0), _clip_start(c)))
            if c.get("id")
        ]
        _broadcast("rough_cut_applied", {
            "plan_id": proposal["plan_id"],
            "request_id": proposal["request_id"],
            "deleted_count": deleted_count,
            "final_duration": round(final_duration, 3),
            "message": f"粗剪已写回：删除 {deleted_count} 段，成片时长 {final_duration:.2f}s（可撤销）",
        })
        logger.info("[rough_cut] 提案 %s 已写回（删除 %d 段，终时长 %.2fs）",
                    proposal["plan_id"], deleted_count, final_duration)
        return {
            "ok": True,
            "message": f"粗剪写回完成：删除 {deleted_count}/{len(proposal['intervals'])} 段，"
                       f"成片时长 {final_duration:.2f}s（可撤销）",
            "plan_id": proposal["plan_id"],
            "deleted_count": deleted_count,
            "final_duration": round(final_duration, 3),
        }

    # ── ③ export：委托既有精剪出片入口 ──────────────────────────
    def export(self, editor: Any, plan_id: str, *, session_id: str = "") -> Dict[str, Any]:
        """导出粗剪成片：委托 EditorModule.agent_execute_pipeline_editing（零新渲染路径）。"""
        proposal = self.get_plan(plan_id)
        if proposal is None:
            return {"ok": False, "error": f"提案不存在或已过期：{plan_id}"}
        if not proposal["applied"]:
            return {"ok": False, "error": "粗剪提案尚未写回：请先审核后确认 apply，再导出"}
        if editor is None:
            return {"ok": False, "error": "EditorModule 未就绪"}
        handler = getattr(editor, "agent_execute_pipeline_editing", None)
        if not callable(handler):
            return {"ok": False, "error": "EditorModule 未实现精剪入口，请手动导出成片"}
        order = list(proposal.get("applied_clip_order") or [])
        if not order:
            return {"ok": False, "error": "写回后片段顺序为空，无法导出"}
        try:
            out = handler({"clip_order": order}, session_id or proposal.get("request_id", ""))
        except Exception as e:
            logger.exception("[rough_cut] 导出异常")
            return {"ok": False, "error": f"粗剪导出异常：{e}"}
        path = str(out or "")
        if not path:
            return {"ok": False, "error": "精剪未产出成片，请检查剪辑模块（时间线/素材路径）"}
        # 与 pipeline.execute_editing 同口径：UI 统一读 final_video_path
        return {"ok": True, "final_video_path": path, "output_path": path}


#: 模块级单例（提案状态跨能力调用共享；与 preview_validation_loop 同套路）
rough_cut_chain = RoughCutChain()


def rough_cut_job_runner(params: Dict[str, Any], report: Any) -> Dict[str, Any]:
    """粗剪合链队列任务体：入库 → 规则排轨 + B2 检测 → 审核卡（暂停待确认）。

    与 _default_runner 同纪律：「等待人工确认」是正常暂停不是失败（ok=True + paused），
    确认后由 Agent/UI 调 editor.rough_cut_apply + editor.rough_cut_export 收尾。
    """
    from app.core.ai.pipeline_jobs import pipeline_progress, pipeline_stage, raise_if_cancelled

    raise_if_cancelled()
    pipeline_stage("rough_cut.load", "素材入库到时间线")
    materials = params.get("materials") or []
    clips = build_clips_from_materials(materials)
    if not clips:
        return {"ok": False, "error": "没有可用素材（materials 为空或缺 path）"}

    # 入库：复用既有事件路径（editor_module 监听 MATERIAL_TO_TIMELINE 落轨）
    items = [
        {"clip_id": c["id"], "path": c["path"], "duration": c["duration"],
         "source": "rough_cut", "prompt": ""}
        for c in clips
    ]
    try:
        from app.core.preview_validation_loop import preview_validation_loop
        preview_validation_loop.load_clips_to_timeline(
            items, request_id=str(params.get("request_id") or ""))
    except Exception as e:
        logger.warning("[rough_cut] 入库事件广播失败（提案照常生成，落轨需人工检查）: %s", e)

    raise_if_cancelled()
    pipeline_stage("rough_cut.plan", "规则排轨 + 水词/静音检测")
    pipeline_progress(None)
    res = rough_cut_chain.plan(
        clips,
        mode="materials",
        asr_by_clip=params.get("asr_by_clip") or {},
        subtitles=params.get("subtitles") or [],
        label=str(params.get("label") or ""),
        request_id=str(params.get("request_id") or ""),
    )
    if not res.get("ok"):
        return {"ok": False, "error": str(res.get("error") or "粗剪提案失败")}
    proposal = res["proposal"]
    return {
        "ok": True,
        "paused": True,
        "stage": "waiting_for_review",
        "plan_id": proposal["plan_id"],
        "summary": {
            "clip_count": len(proposal["clip_ids"]),
            "interval_count": len(proposal["intervals"]),
            "original_duration": proposal["original_duration"],
            "predicted_duration": proposal["predicted_duration"],
            "warnings": proposal["warnings"],
        },
        "message": "粗剪提案已生成并广播审核卡，确认后请调用 editor.rough_cut_apply 写回、"
                   "editor.rough_cut_export 导出成片",
    }
