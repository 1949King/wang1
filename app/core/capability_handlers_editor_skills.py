# -*- coding: utf-8 -*-
"""剪辑 Skill 扩容 handlers（LibTV 对标 · 第二刀，2026-10-14）
==============================================================
背景：LibTV 对外宣称 100+ 导演 Skill，本项目 ``editor.*`` 仅 15 个。
本轮按「短剧导演高频动作」补到 40+，但**不新写业务逻辑**——
每个新 Skill 都是既有 EditorModule 公开方法的薄接线：

  - 删除 / 复制 / 音量 / 静音  → ``_delete_clip_by_id`` / ``_copy_clip_data_to_timeline``
                              / ``_adjust_volume`` / 片段 volume 字段
  - 场景切分 / 卡点切镜 / 静音整理 → ``beat_split`` + ``filler_silence_detect``
  - 台词重锚 / 分镜时长          → ``agent_reanchor_clips`` / ``agent_apply_storyboard_durations``
  - 字幕 / 贴纸 / 工程快照       → ``agent_get_timeline_context`` 等既有只读面 + 写入口
  - 撤销 / 重做 / 定位播放头      → 既有 ``_undo`` / ``_redo`` / seek 入口

纪律（与 capability_handlers_media.py 一致）：
  - 复用既有实现，零行为变化；失败时诚实返回中文指引，不假成功。
  - 独立成模块：capability_handlers.py 已 1880 行，再塞会顶破 2000 行守卫。
  - 只做「参数归一化 + 委托 + 结果诚实化」，不复制算法。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from app.core.capability_dispatcher import (
    CapabilityRequest, CapabilityResult,
)

logger = logging.getLogger(__name__)


class EditorSkillHandlers:
    """剪辑 Skill 扩容：把 EditorModule 既有能力接进 Agent 能力目录。

    handler 全部是薄壳：取 editor → 归一化参数 → 委托 → 诚实化结果。
    """

    def __init__(self, editor_module_ref):
        # lazy ref：调用时才取，避免 import 时拉起 UI（与 EditorCapabilityHandlers 一致）
        self._get_editor = editor_module_ref

    # ── 内部工具 ────────────────────────────────────────────────
    def _editor(self, req: CapabilityRequest):
        editor = self._get_editor()
        if editor is None:
            return None
        return editor

    def _fail(self, req: CapabilityRequest, msg: str) -> CapabilityResult:
        return CapabilityResult(req.request_id, False, error=msg)

    def _find_clip(self, editor: Any, clip_id: str) -> Optional[Dict[str, Any]]:
        """按 id 找片段；找不到回落到当前选中片段。"""
        for clip in getattr(editor, "_clips", []) or []:
            if clip.get("id") == clip_id:
                return clip
        current = getattr(editor, "_current_clip", None)
        if current and (not clip_id or current.get("id") == clip_id):
            return current
        return None

    # ── 基础剪辑动作（LibTV Skill 目录里的高频项）────────────────

    def delete_clip(self, req: CapabilityRequest) -> CapabilityResult:
        """删除片段（默认波纹；视频片连带同起点联动音频，一次撤销）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        clip = self._find_clip(editor, clip_id)
        if not clip:
            return self._fail(req, f"未找到片段 {clip_id or '(未选中)'}")
        ripple = bool(req.params.get("ripple", True))
        ok = editor._delete_clip_by_id(clip.get("id"), ripple=ripple)
        return CapabilityResult(
            req.request_id, bool(ok),
            output={"clip_id": clip.get("id"), "ripple": ripple},
            error=None if ok else "删除片段失败（片段可能已不存在）",
        )

    def duplicate_clip(self, req: CapabilityRequest) -> CapabilityResult:
        """复制片段（默认落在原片段后 1s，可撤销）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        clip = self._find_clip(editor, clip_id)
        if not clip:
            return self._fail(req, f"未找到片段 {clip_id or '(未选中)'}")
        offset = float(req.params.get("offset", 1.0))
        before = {c.get("id") for c in getattr(editor, "_clips", []) or []}
        editor._copy_clip_data_to_timeline(clip, offset=offset)
        new_ids = [c.get("id") for c in getattr(editor, "_clips", []) or []
                   if c.get("id") not in before]
        return CapabilityResult(
            req.request_id, bool(new_ids),
            output={"source_id": clip.get("id"), "new_clip_ids": new_ids, "offset": offset},
            error=None if new_ids else "复制片段失败",
        )

    def set_clip_volume(self, req: CapabilityRequest) -> CapabilityResult:
        """设置片段音量（0–200%，与轨道/总控音量相乘）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        clip = self._find_clip(editor, clip_id)
        if not clip:
            return self._fail(req, f"未找到片段 {clip_id or '(未选中)'}")
        raw = req.params.get("volume", req.params.get("value"))
        try:
            vol = max(0.0, min(2.0, float(raw) / 100.0))
        except (TypeError, ValueError):
            return self._fail(req, f"音量参数无效：{raw!r}（应传 0–200 的百分数）")
        # 刀4：真相源字段写走 store API；片段脱离真相源（_current_clip 兜底）时写引用
        if not editor._timeline_store.set_fields(clip.get("id"), volume=vol):
            clip["volume"] = vol  # ratchet-exempt: 未入轨兜底引用
        # 复用既有音量同步入口，让改动立即作用到预览音频
        try:
            editor._sync_volume_slider_from_clip(clip)
        except Exception as e:  # 预览同步失败不影响数据落地
            logger.debug("[Skill] 音量预览同步忽略: %s", e)
        if hasattr(editor, "_touch_project_dirty"):
            editor._touch_project_dirty()
        return CapabilityResult(
            req.request_id, True,
            output={"clip_id": clip.get("id"), "volume_percent": round(vol * 100)},
        )

    def set_clip_speed(self, req: CapabilityRequest) -> CapabilityResult:
        """设置片段速度（0.1–10x，复用 EditorModule.set_clip_speed）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        clip = self._find_clip(editor, clip_id)
        if not clip:
            return self._fail(req, f"未找到片段 {clip_id or '(未选中)'}")
        try:
            speed = float(req.params.get("speed", req.params.get("value", 1.0)))
        except (TypeError, ValueError):
            return self._fail(req, "速度参数无效")
        if not (0.1 <= speed <= 10.0):
            return self._fail(req, "速度须在 0.1–10 之间")
        try:
            editor.set_clip_speed(clip.get("id"), speed)
        except Exception as e:
            return self._fail(req, f"设置速度失败：{e}")
        return CapabilityResult(
            req.request_id, True,
            output={"clip_id": clip.get("id"), "speed": speed},
        )

    def mute_clip(self, req: CapabilityRequest) -> CapabilityResult:
        """静音/取消静音片段（volume=0 的显式表达，便于 Agent 语义化调用）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        clip = self._find_clip(editor, clip_id)
        if not clip:
            return self._fail(req, f"未找到片段 {clip_id or '(未选中)'}")
        muted = bool(req.params.get("muted", True))
        # 记住原音量，取消静音时恢复（默认 100%）
        prev = clip.get("volume")
        new_vol = 0.0 if muted else (prev if isinstance(prev, (int, float)) and prev > 0 else 1.0)
        # 刀4：真相源字段写走 store API；兜底引用同 set_clip_volume
        if not editor._timeline_store.set_fields(clip.get("id"), volume=new_vol, muted=muted):
            clip["volume"] = new_vol  # ratchet-exempt: 未入轨兜底引用
            clip["muted"] = muted     # ratchet-exempt: 未入轨兜底引用
        try:
            editor._sync_volume_slider_from_clip(clip)
        except Exception as e:
            logger.debug("[Skill] 静音预览同步忽略: %s", e)
        if hasattr(editor, "_touch_project_dirty"):
            editor._touch_project_dirty()
        return CapabilityResult(
            req.request_id, True,
            output={"clip_id": clip.get("id"), "muted": muted},
        )

    def set_transition_all(self, req: CapabilityRequest) -> CapabilityResult:
        """批量加转场：给相邻片段统一加指定转场（复用 agent_apply_transition）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        ttype = str(req.params.get("transition_type", "fade"))
        try:
            duration = float(req.params.get("duration", 0.5))
        except (TypeError, ValueError):
            return self._fail(req, "转场时长无效")
        clips = list(getattr(editor, "_clips", []) or [])
        applied, failed = [], []
        for clip in clips:
            try:
                res = editor.agent_apply_transition(clip, ttype, duration)
            except Exception as e:
                failed.append({"clip_id": clip.get("id"), "error": str(e)})
                continue
            if isinstance(res, dict) and res.get("success"):
                applied.append(clip.get("id"))
            else:
                failed.append({"clip_id": clip.get("id"),
                               "error": (res or {}).get("message", "未知原因")
                               if isinstance(res, dict) else str(res)})
        return CapabilityResult(
            req.request_id, bool(applied),
            output={"applied": applied, "failed": failed,
                    "transition_type": ttype, "duration": duration},
            error=None if applied else "没有片段成功应用转场",
        )

    # ── 智能剪辑（复用既有引擎，零新算法）────────────────────────

    def suggest_beat_cut(self, req: CapabilityRequest) -> CapabilityResult:
        """卡点切镜建议：按节拍给出切点（默认只出计划，确认后才切）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        clip = self._find_clip(editor, clip_id)
        if not clip:
            return self._fail(req, f"未找到片段 {clip_id or '(未选中)'}")
        beats = req.params.get("beats") or []
        duration = float(clip.get("duration", 0) or 0)
        try:
            from app.core.beat_split import beat_split_times
        except ImportError:
            from core.beat_split import beat_split_times  # type: ignore
        try:
            every_n = int(req.params.get("every_n", 4))
        except (TypeError, ValueError):
            every_n = 4
        times = beat_split_times(beats, duration, every_n=every_n)
        if not times:
            return CapabilityResult(
                req.request_id, True,
                output={"clip_id": clip.get("id"), "cut_times": [],
                        "awaiting_confirm": False,
                        "message": "未取得有效节拍点（beats 为空或不合法），诚实返回空计划"},
            )
        return CapabilityResult(
            req.request_id, True,
            output={"clip_id": clip.get("id"), "cut_times": [round(t, 3) for t in times],
                    "every_n": every_n, "awaiting_confirm": True,
                    "message": f"建议 {len(times)} 个卡点切镜（确认后才切）"},
        )

    def suggest_scene_cut(self, req: CapabilityRequest) -> CapabilityResult:
        """场景切换建议：复用既有 AIEditingAssistant（PySceneDetect 优先、帧差法回退）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        clip = self._find_clip(editor, clip_id)
        if not clip:
            return self._fail(req, f"未找到片段 {clip_id or '(未选中)'}")
        path = clip.get("path") or ""
        if not path:
            return self._fail(req, "片段无源文件路径，无法做场景检测")
        try:
            from app.core.ai_editing_assistant import AIEditingAssistant
            scenes = AIEditingAssistant().detect_scenes(video_path=path)
        except Exception as e:
            return self._fail(req, f"场景检测失败：{e}")
        # 场景边界 = 每个场景的起点（跳过 0 秒自身）
        times = [float(getattr(s, "start_time", 0) or 0) for s in (scenes or [])
                 if float(getattr(s, "start_time", 0) or 0) > 0.05]
        return CapabilityResult(
            req.request_id, True,
            output={"clip_id": clip.get("id"),
                    "cut_times": [round(t, 3) for t in times],
                    "scene_count": len(scenes or []),
                    "awaiting_confirm": True,
                    "message": f"建议 {len(times)} 个场景切点（确认后才切）"},
        )

    def suggest_silence_trim(self, req: CapabilityRequest) -> CapabilityResult:
        """长静音整理建议：复用 filler_silence_detect，输出待删区间（确认后才删）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        clip = self._find_clip(editor, clip_id)
        if not clip:
            return self._fail(req, f"未找到片段 {clip_id or '(未选中)'}")
        # 复用既有「去水词/静音建议」链路（M5 同源），open_ui=False 只出 JSON
        res = editor.agent_suggest_cleanup(open_ui=False)
        intervals = (res or {}).get("intervals") or []
        return CapabilityResult(
            req.request_id, True,
            output={"intervals": intervals, "count": len(intervals),
                    "awaiting_confirm": True,
                    "message": f"{len(intervals)} 段待整理（确认后才删）"},
        )

    # ── 字幕 / 成片（复用既有写入口）─────────────────────────────

    def burn_subtitles(self, req: CapabilityRequest) -> CapabilityResult:
        """字幕烧录：按当前字幕配置烧到成片（复用 _burn_subtitles_if_any 语义）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        if not getattr(editor, "_ensure_subtitle_manager", None):
            return self._fail(req, "字幕管理器不可用")
        editor._ensure_subtitle_manager()
        manager = getattr(editor, "_subtitle_manager", None)
        subs = list(getattr(manager, "subtitles", []) or []) if manager else []
        if not subs:
            return self._fail(req, "当前没有字幕可烧录（请先导入/生成字幕）")
        return CapabilityResult(
            req.request_id, True,
            output={"subtitle_count": len(subs), "awaiting_confirm": True,
                    "message": f"已就绪 {len(subs)} 条字幕，导出时将自动烧录"},
        )

    # ── 只读自省（Agent 决策面，LibTV「拉片/质检」同款）──────────

    def get_playhead(self, req: CapabilityRequest) -> CapabilityResult:
        """读取播放头位置与选中片段。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        current = getattr(editor, "_current_clip", None) or {}
        return CapabilityResult(
            req.request_id, True,
            output={"playhead_position": float(getattr(editor, "_playhead_position", 0) or 0),
                    "selected_clip_id": current.get("id"),
                    "selected_clip_name": current.get("name") or "",
                    "timeline_duration": max(
                        (float(c.get("start_time", 0) or 0) + float(c.get("duration", 0) or 0))
                        for c in (getattr(editor, "_clips", []) or [{}])),
                    },
        )

    def seek_playhead(self, req: CapabilityRequest) -> CapabilityResult:
        """定位播放头到指定秒（复用既有 seek 入口）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        try:
            position = float(req.params.get("position", req.params.get("time", 0)))
        except (TypeError, ValueError):
            return self._fail(req, "位置参数无效")
        # 定位到目标时间最近的片段起点，再把播放头挪过去（复用既有刷新链路）
        clips = sorted(getattr(editor, "_clips", []) or [],
                       key=lambda c: float(c.get("start_time", 0) or 0))
        target = None
        for clip in clips:
            if float(clip.get("start_time", 0) or 0) <= position:
                target = clip
        if target is None:
            return self._fail(req, "目标时间不在时间线范围内")
        try:
            editor._playhead_position = position
            editor._current_clip = target
            editor._refresh_preview_to_current_clip()
        except Exception as e:
            return self._fail(req, f"定位播放头失败：{e}")
        return CapabilityResult(
            req.request_id, True,
            output={"position": position, "clip_id": target.get("id")},
        )

    def undo_last(self, req: CapabilityRequest) -> CapabilityResult:
        """撤销上一步（复用 EditorModule._undo）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        undo = getattr(editor, "_undo", None)
        if not callable(undo):
            return self._fail(req, "撤销栈不可用")
        try:
            undo()
        except Exception as e:
            return self._fail(req, f"撤销失败：{e}")
        toast = ""
        try:
            toast = editor.get_undo_redo_toast()
        except Exception:
            # 取不到 toast 不是失败：下面有fallback 文案。仅降级不静默。
            logger.debug("取撤销 toast 失败，降级为默认文案", exc_info=True)
        return CapabilityResult(req.request_id, True,
                                output={"message": toast or "已撤销"})

    def redo_last(self, req: CapabilityRequest) -> CapabilityResult:
        """重做（复用 EditorModule._redo）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        redo = getattr(editor, "_redo", None)
        if not callable(redo):
            return self._fail(req, "重做栈不可用")
        try:
            redo()
        except Exception as e:
            return self._fail(req, f"重做失败：{e}")
        return CapabilityResult(req.request_id, True,
                                output={"message": "已重做"})

    def list_timeline_clips(self, req: CapabilityRequest) -> CapabilityResult:
        """列出时间线片段摘要（Agent 自省入口；不返回全量字段）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clips = getattr(editor, "_clips", []) or []
        rows = [{
            "id": c.get("id"),
            "name": c.get("name") or "",
            "start_time": round(float(c.get("start_time", 0) or 0), 3),
            "duration": round(float(c.get("duration", 0) or 0), 3),
            "track": c.get("track", 0),
            "volume": c.get("volume"),
            "speed": c.get("speed", 1.0),
            "has_keyframes": bool(c.get("keyframes")),
        } for c in clips]
        return CapabilityResult(
            req.request_id, True,
            output={"clip_count": len(rows), "clips": rows},
        )

    # ── 字幕 Skill 扩容（LibTV 对标第三刀，2026-10-14）──────────
    # 全部复用 SubtitleManager 既有能力（list/split/merge/visible/import/export），
    # 不做任何字幕算法复制；UI 弹窗版在 editor_subtitle_panel.py。

    def _subtitle_manager(self, editor: Any):
        """确保字幕管理器就绪并返回（未就绪返回 None）。"""
        ensure = getattr(editor, "_ensure_subtitle_manager", None)
        if not callable(ensure):
            return None
        try:
            return ensure()
        except Exception as e:
            logger.debug("[Skill] 字幕管理器初始化忽略: %s", e)
            return None

    def list_subtitles(self, req: CapabilityRequest) -> CapabilityResult:
        """列出当前字幕条目（Agent 决策面前先自省字幕面）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        manager = self._subtitle_manager(editor)
        subs = list(getattr(manager, "subtitles", []) or []) if manager else []
        rows = [{
            "id": s.get("id"),
            "text": (s.get("text") or "")[:40],
            "start_time": round(float(s.get("start_time", 0) or 0), 3),
            "end_time": round(float(s.get("end_time", 0) or 0), 3),
            "visible": bool(s.get("visible", True)),
        } for s in subs]
        return CapabilityResult(
            req.request_id, True,
            output={"subtitle_count": len(rows), "subtitles": rows},
        )

    def split_subtitle(self, req: CapabilityRequest) -> CapabilityResult:
        """拆分字幕：在指定时间点一分为二（复用 SubtitleManager.split_subtitle）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        manager = self._subtitle_manager(editor)
        if manager is None:
            return self._fail(req, "字幕管理器不可用")
        sub_id = str(req.params.get("subtitle_id") or req.params.get("id")
                     or getattr(editor, "_selected_sub_id", "") or "")
        raw_t = req.params.get("split_time", req.params.get("time"))
        if raw_t is None:
            return self._fail(req, "需要 split_time（在该秒数处拆分）")
        try:
            split_time = float(raw_t)
        except (TypeError, ValueError):
            return self._fail(req, "split_time 参数无效")
        sub = manager.get_subtitle(sub_id) if sub_id else None
        if sub is None:
            return self._fail(req, f"未找到字幕 {sub_id or '(未选中)'}")
        if not (float(sub.get("start_time", 0)) < split_time < float(sub.get("end_time", 0))):
            return self._fail(req, "split_time 必须落在该字幕的起止时间内")
        result = manager.split_subtitle(sub_id, split_time)
        if not result:
            return self._fail(req, "拆分字幕失败")
        if hasattr(editor, "_touch_project_dirty"):
            editor._touch_project_dirty()
        try:
            from app.modules.lego.editor_subtitle_panel import refresh_subtitle_list
            refresh_subtitle_list(editor)
        except Exception as e:
            logger.debug("[Skill] 字幕列表刷新忽略: %s", e)
        return CapabilityResult(
            req.request_id, True,
            output={"subtitle_id": sub_id, "split_time": split_time,
                    "parts": len(result) if isinstance(result, list) else 2},
        )

    def merge_subtitles(self, req: CapabilityRequest) -> CapabilityResult:
        """合并两条字幕（复用 SubtitleManager.merge_subtitles，文本空格拼接）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        manager = self._subtitle_manager(editor)
        if manager is None:
            return self._fail(req, "字幕管理器不可用")
        sid1 = str(req.params.get("subtitle_id") or req.params.get("id")
                   or getattr(editor, "_selected_sub_id", "") or "")
        sid2 = str(req.params.get("other_id") or req.params.get("with_id") or "")
        if not sid1 or not sid2:
            return self._fail(req, "需要 subtitle_id 与 other_id 两条字幕")
        if sid1 == sid2:
            return self._fail(req, "不能把一条字幕和自己合并")
        merged = manager.merge_subtitles(sid1, sid2)
        if not merged:
            return self._fail(req, "合并字幕失败（两条都必须存在）")
        if hasattr(editor, "_touch_project_dirty"):
            editor._touch_project_dirty()
        try:
            from app.modules.lego.editor_subtitle_panel import refresh_subtitle_list
            refresh_subtitle_list(editor)
        except Exception as e:
            logger.debug("[Skill] 字幕列表刷新忽略: %s", e)
        return CapabilityResult(
            req.request_id, True,
            output={"merged_id": merged.get("id"),
                    "text": merged.get("text"),
                    "start_time": merged.get("start_time"),
                    "end_time": merged.get("end_time")},
        )

    def set_subtitle_visible(self, req: CapabilityRequest) -> CapabilityResult:
        """显隐单条字幕（复用 SubtitleManager.toggle_subtitle_visibility）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        manager = self._subtitle_manager(editor)
        if manager is None:
            return self._fail(req, "字幕管理器不可用")
        sub_id = str(req.params.get("subtitle_id") or req.params.get("id")
                     or getattr(editor, "_selected_sub_id", "") or "")
        if not sub_id or manager.get_subtitle(sub_id) is None:
            return self._fail(req, f"未找到字幕 {sub_id or '(未选中)'}")
        raw_v = req.params.get("visible", req.params.get("value"))
        visible = True if raw_v is None else bool(raw_v)
        ok = manager.toggle_subtitle_visibility(sub_id, visible=visible)
        if not ok:
            return self._fail(req, "设置字幕可见性失败")
        if hasattr(editor, "_touch_project_dirty"):
            editor._touch_project_dirty()
        try:
            from app.modules.lego.editor_subtitle_panel import refresh_subtitle_list
            refresh_subtitle_list(editor)
        except Exception as e:
            logger.debug("[Skill] 字幕列表刷新忽略: %s", e)
        return CapabilityResult(
            req.request_id, True,
            output={"subtitle_id": sub_id, "visible": visible},
        )

    def import_subtitles(self, req: CapabilityRequest) -> CapabilityResult:
        """导入 SRT/VTT 字幕文件（复用 SubtitleManager.import_subtitles）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        manager = self._subtitle_manager(editor)
        if manager is None:
            return self._fail(req, "字幕管理器不可用")
        path = str(req.params.get("path") or req.params.get("file_path") or "")
        if not path:
            return self._fail(req, "需要字幕文件路径（path）")
        if not os.path.isfile(path):
            return self._fail(req, f"字幕文件不存在: {path}")
        fmt = str(req.params.get("format") or "").strip().lower()
        if not fmt:
            fmt = "vtt" if path.lower().endswith(".vtt") else "srt"
        if fmt not in ("srt", "vtt"):
            return self._fail(req, f"不支持的字幕格式: {fmt}（仅 srt / vtt）")
        try:
            imported = manager.import_subtitles(path, fmt)
        except Exception as e:
            return self._fail(req, f"导入字幕失败：{e}")
        if not imported:
            return self._fail(req, "未能从该文件识别出字幕数据")
        if hasattr(editor, "_touch_project_dirty"):
            editor._touch_project_dirty()
        try:
            from app.modules.lego.editor_subtitle_panel import refresh_subtitle_list
            refresh_subtitle_list(editor)
        except Exception as e:
            logger.debug("[Skill] 字幕列表刷新忽略: %s", e)
        return CapabilityResult(
            req.request_id, True,
            output={"imported_count": len(imported), "format": fmt, "path": path,
                    "total": len(getattr(manager, "subtitles", []) or [])},
        )

    def export_subtitles(self, req: CapabilityRequest) -> CapabilityResult:
        """导出字幕为 SRT（复用 SubtitleManager.export_subtitles，空字幕诚实失败）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        manager = self._subtitle_manager(editor)
        if manager is None:
            return self._fail(req, "字幕管理器不可用")
        path = str(req.params.get("path") or req.params.get("output_path") or "")
        if not path:
            return self._fail(req, "需要导出路径（path）")
        subs = list(getattr(manager, "subtitles", []) or [])
        if not subs:
            return self._fail(req, "当前没有字幕可导出")
        try:
            ok = manager.export_subtitles(path, "srt")
        except Exception as e:
            return self._fail(req, f"导出字幕失败：{e}")
        if not ok:
            return self._fail(req, "导出字幕失败（写入被拒绝或路径不可用）")
        return CapabilityResult(
            req.request_id, True,
            output={"path": path, "subtitle_count": len(subs), "format": "srt"},
        )

    # ── 序列 / 节奏 Skill 扩容（LibTV 对标第四刀，2026-10-14）───
    # 复用既有 _ripple_delete_gaps（合缝）与入出点标记（I/O 键同源），零新算法。

    def close_track_gaps(self, req: CapabilityRequest) -> CapabilityResult:
        """磁吸合缝：同轨片段前移贴齐（复用 _ripple_delete_gaps，不删内容、可撤销）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clips = list(getattr(editor, "_clips", []) or [])
        if not clips:
            return self._fail(req, "时间线没有片段可合缝")
        track = req.params.get("track")
        try:
            track_i: Optional[int] = int(track) if track is not None else None
        except (TypeError, ValueError):
            return self._fail(req, "track 参数无效（应传轨道序号整数）")
        before_positions = {c.get("id"): float(c.get("start_time", 0) or 0) for c in clips}
        try:
            editor._ripple_delete_gaps()
        except Exception as e:
            return self._fail(req, f"合缝失败：{e}")
        moved = [{"clip_id": cid, "from": before_positions.get(cid),
                  "to": float(c.get("start_time", 0) or 0)}
                 for c in getattr(editor, "_clips", []) or []
                 for cid in [c.get("id")]
                 if before_positions.get(cid) is not None
                 and abs(float(c.get("start_time", 0) or 0) - before_positions[cid]) > 0.001]
        return CapabilityResult(
            req.request_id, True,
            output={"moved": moved, "moved_count": len(moved),
                    "scope": f"track {track_i}" if track_i is not None else "全部轨道",
                    "message": f"已合缝 {len(moved)} 个片段（一次撤销可还原）"},
        )

    def mark_sequence_in_out(self, req: CapabilityRequest) -> CapabilityResult:
        """标记序列入点/出点（I/O 键同源；不传参数时清除入出点）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        action = str(req.params.get("action") or "").strip().lower()
        if action in ("clear", "清除", "重置"):
            try:
                editor._clear_sequence_in_out()
            except Exception as e:
                return self._fail(req, f"清除入出点失败：{e}")
            return CapabilityResult(req.request_id, True,
                                    output={"cleared": True, "message": "已清除序列入出点"})
        if action in ("in", "入点", "mark_in"):
            try:
                editor._mark_sequence_in()
            except Exception as e:
                return self._fail(req, f"标记入点失败：{e}")
            return CapabilityResult(
                req.request_id, True,
                output={"in_point": getattr(editor, "_sequence_in_point", None)})
        if action in ("out", "出点", "mark_out"):
            try:
                editor._mark_sequence_out()
            except Exception as e:
                return self._fail(req, f"标记出点失败：{e}")
            return CapabilityResult(
                req.request_id, True,
                output={"in_point": getattr(editor, "_sequence_in_point", None),
                        "out_point": getattr(editor, "_sequence_out_point", None)})
        return CapabilityResult(
            req.request_id, False,
            error="需要 action ∈ {in, out, clear}（标记序列入点/出点/清除）",
        )

    # ── 关键帧 Skill 扩容（LibTV 对标第五刀，2026-10-14）────────
    # 复用既有 get_keyframes_for_clip（读）与 add_keyframe_at_playhead（写）。

    def get_keyframes(self, req: CapabilityRequest) -> CapabilityResult:
        """读取片段关键帧列表（Agent 自省：动画现状）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        clip = self._find_clip(editor, clip_id)
        if not clip:
            return self._fail(req, f"未找到片段 {clip_id or '(未选中)'}")
        target_id = clip.get("id") or ""
        try:
            kfs = editor.get_keyframes_for_clip(target_id)
        except Exception as e:
            return self._fail(req, f"读取关键帧失败：{e}")
        rows = [{
            "prop": k.get("prop") or "",
            "time_offset": round(float(k.get("time_offset", k.get("time", 0)) or 0), 3),
            "value": k.get("value"),
            "easing": k.get("easing") or "linear",
        } for k in (kfs or []) if isinstance(k, dict)]
        return CapabilityResult(
            req.request_id, True,
            output={"clip_id": target_id, "keyframe_count": len(rows), "keyframes": rows},
        )

    def add_keyframe_at_playhead(self, req: CapabilityRequest) -> CapabilityResult:
        """在播放头位置给选中片段加关键帧（复用 add_keyframe_at_playhead，同 prop 近点覆盖）。"""
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        clip = self._find_clip(editor, clip_id)
        if not clip:
            return self._fail(req, f"未找到片段 {clip_id or '(未选中)'}")
        prop = str(req.params.get("prop") or req.params.get("property") or "opacity")
        raw_v = req.params.get("value", 1.0)
        try:
            value = float(raw_v)
        except (TypeError, ValueError):
            return self._fail(req, "value 参数无效（应传数值）")
        # 目标片段即当前选中片段时才可直接委托（方法内部读 _current_clip）
        if getattr(editor, "_current_clip", None) is not clip:
            editor._current_clip = clip
        try:
            ok = bool(editor.add_keyframe_at_playhead(prop=prop, value=value))
        except Exception as e:
            return self._fail(req, f"添加关键帧失败：{e}")
        if not ok:
            return self._fail(req, "添加关键帧失败（片段可能不可写）")
        if hasattr(editor, "_touch_project_dirty"):
            editor._touch_project_dirty()
        return CapabilityResult(
            req.request_id, True,
            output={"clip_id": clip.get("id"), "prop": prop, "value": value,
                    "playhead_position": float(getattr(editor, "_playhead_position", 0) or 0)},
        )

    # ── 血缘查询（智能时间线 P1 · Agent 接线，2026-10-17）────────
    # 与 GET /host/clip-lineage 同一实现（lineage_index + get_full_clips），
    # 从 _clips 快照按需建索引、不落第二真相源；无命中诚实空返回，不猜。

    def get_clip_lineage(self, req: CapabilityRequest) -> CapabilityResult:
        """片段血缘查询：按 clip_id / node_id 查片段↔画布节点关联+生成参数（只读）。"""
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        node_id = str(req.params.get("node_id") or "")
        try:
            from app.core.editor_canvas_link import lineage_index
            from app.core.project_snapshot import get_full_clips
        except ImportError:
            from core.editor_canvas_link import lineage_index  # type: ignore
            from core.project_snapshot import get_full_clips  # type: ignore
        clips = get_full_clips()
        if clips is None:
            # 快照回调未注册时回落到 editor._clips 直读（时间线真相源，仍不落第二份）
            editor = self._editor(req)
            if editor is None:
                return self._fail(req, "剪辑模块未就绪（时间线快照不可用）")
            clips = list(getattr(editor, "_clips", []) or [])
        idx = lineage_index(clips)
        if clip_id:
            rec = idx["by_clip_id"].get(clip_id)
            records = [rec] if rec else []
        elif node_id:
            records = list(idx["by_node_id"].get(node_id) or [])
        else:
            records = list(idx["by_clip_id"].values())
        return CapabilityResult(
            req.request_id, True,
            output={"clip_id": clip_id or None, "node_id": node_id or None,
                    "record_count": len(records), "records": records,
                    "message": (f"命中 {len(records)} 条血缘记录" if records
                                else "无血缘记录（片段未关联画布节点，或查询参数不匹配）")},
        )

    # ── 小白闭环自动粗剪合链（§6.9-P2 · 方案 1，2026-10-17）──────
    # 全部薄委托 app/core/rough_cut_chain.py（B1/B2 复用 + 确认后执行纪律），
    # 本层只做参数归一化与结果诚实化；队列提交复用 pipeline_jobs 底座。

    def rough_cut_plan(self, req: CapabilityRequest) -> CapabilityResult:
        """粗剪提案：规则排轨 + 水词/静音检测 → 审核卡（只算不改数据）。"""
        from app.core.rough_cut_chain import rough_cut_chain
        clips = req.params.get("clips")
        mode = str(req.params.get("mode") or "")
        if not clips:
            editor = self._editor(req)
            if editor is None:
                return self._fail(req, "EditorModule 未就绪（或显式传入 clips）")
            clips = list(getattr(editor, "_clips", []) or [])
            mode = mode or "timeline"
        mode = mode or "timeline"
        if not clips:
            return self._fail(req, "时间线为空：没有可粗剪的片段")
        res = rough_cut_chain.plan(
            clips, mode=mode,
            asr_by_clip=req.params.get("asr_by_clip") or {},
            subtitles=req.params.get("subtitles") or [],
            label=str(req.params.get("label") or ""),
            request_id=req.request_id,
        )
        if not res.get("ok"):
            return self._fail(req, str(res.get("error") or "粗剪提案失败"))
        p = res["proposal"]
        return CapabilityResult(req.request_id, True, output={
            "plan_id": p["plan_id"],
            "needs_confirmation": True,
            "clip_count": len(p["clip_ids"]),
            "interval_count": len(p["intervals"]),
            "intervals": p["intervals"],
            "original_duration": p["original_duration"],
            "predicted_duration": p["predicted_duration"],
            "deleted_duration": p["deleted_duration"],
            "warnings": p["warnings"],
        })

    def rough_cut_apply(self, req: CapabilityRequest) -> CapabilityResult:
        """粗剪写回：确认后落时间线（排轨+波纹删除+合缝，一条 compound 撤销）。"""
        from app.core.rough_cut_chain import rough_cut_chain
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        res = rough_cut_chain.apply(
            editor, str(req.params.get("plan_id") or ""),
            confirmed=bool(req.params.get("confirmed", False)),
        )
        if not res.get("ok"):
            return self._fail(req, str(res.get("error") or "粗剪写回失败"))
        return CapabilityResult(req.request_id, True, output=res)

    def rough_cut_export(self, req: CapabilityRequest) -> CapabilityResult:
        """粗剪导出成片：委托既有精剪出片入口（未写回的提案拒绝导出）。"""
        from app.core.rough_cut_chain import rough_cut_chain
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        res = rough_cut_chain.export(
            editor, str(req.params.get("plan_id") or ""),
            session_id=str(req.params.get("session_id") or ""),
        )
        if not res.get("ok"):
            return self._fail(req, str(res.get("error") or "粗剪导出失败"))
        return CapabilityResult(req.request_id, True, output=res)

    def rough_cut_chain_submit(self, req: CapabilityRequest) -> CapabilityResult:
        """粗剪合链异步提交：一条队列跑「入库→排轨→检测→审核卡」，立即返回任务号。"""
        from app.core.ai.pipeline_jobs import submit_full_pipeline
        from app.core.rough_cut_chain import rough_cut_job_runner
        params = {
            "materials": req.params.get("materials", []),
            "asr_by_clip": req.params.get("asr_by_clip") or {},
            "subtitles": req.params.get("subtitles") or [],
            "label": str(req.params.get("label") or ""),
            "request_id": req.request_id,
        }
        n = len(params["materials"])
        if not n:
            return self._fail(req, "materials 为空：没有可入库的素材")
        job = submit_full_pipeline(params, label=f"粗剪合链：{n} 个素材",
                                   runner=rough_cut_job_runner)
        return CapabilityResult(req.request_id, bool(job.get("job_id")), output=job,
                                error=None if job.get("job_id") else "任务提交失败")

    # ── 语义轨道原型（§6.9-P3 · 质量分/高光落 clip 元数据，2026-10-17）──
    # 薄委托 app/core/clip_semantic.py（纯 clip dict 操作，B4 形态不落第二真相源）；
    # 打分盖章已由 pipeline.score 就地完成，本层只补「查询 + 人工高光标记」两个入口。

    def get_clip_semantic(self, req: CapabilityRequest) -> CapabilityResult:
        """查询片段语义元数据（五维质量分/高光标记）；无语义块如实返回空。"""
        from app.core.clip_semantic import read_semantic
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clips = list(getattr(editor, "_clips", []) or [])
        items = read_semantic(clips, str(req.params.get("clip_id") or ""))
        return CapabilityResult(req.request_id, True, output={
            "count": len(items), "items": items,
            "message": (f"命中 {len(items)} 条语义记录" if items
                        else "无语义元数据（片段未打分或未被标记）")})

    def mark_clip_highlight(self, req: CapabilityRequest) -> CapabilityResult:
        """人工/Agent 显式标记高光：覆盖自动判定，后续打分盖章不回改。"""
        from app.core.clip_semantic import mark_highlight
        editor = self._editor(req)
        if editor is None:
            return self._fail(req, "EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or "")
        if not clip_id:
            return self._fail(req, "缺少 clip_id")
        ok = mark_highlight(getattr(editor, "_clips", []) or [], clip_id,
                            bool(req.params.get("value", True)),
                            marked_by=str(req.params.get("marked_by") or "manual"),
                            note=str(req.params.get("note") or ""))
        if not ok:
            return self._fail(req, f"未找到片段 {clip_id}（请核对 clip_id）")
        if hasattr(editor, "_touch_project_dirty"):
            editor._touch_project_dirty()  # 语义变更需持久化：标脏工程
        return CapabilityResult(req.request_id, True,
                                output={"clip_id": clip_id, "marked": True})
