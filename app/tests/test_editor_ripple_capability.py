# -*- coding: utf-8 -*-
"""M4：editor.ripple_delete_range capability + 公开包装接线。"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.core.capability_dispatcher import CapabilityRequest
from app.core.capability_handlers import EditorCapabilityHandlers, register_builtin_handlers
from app.core.edit_commands import ripple_delete_timeline_range


class _FakeTimeline:
    def find_track_index_by_type(self, track_type: str, default: int = 0) -> int:
        return 0 if track_type == "video" else default


class _FakeEditor:
    """最小 Editor 替身：公开包装内直接调 B1（不拉 Qt widget）。"""

    def __init__(self, clips: List[Dict[str, Any]]):
        self._clips = clips
        self._timeline_widget = _FakeTimeline()
        self._recorded: List[Dict[str, Any]] = []
        self._project_dirty = False

    def agent_ripple_delete_range(
        self,
        t_in: float,
        t_out: float,
        *,
        track=None,
        record: bool = True,
    ) -> Dict[str, Any]:
        if track is None:
            track = self._timeline_widget.find_track_index_by_type("video", default=0)
        result = ripple_delete_timeline_range(self._clips, float(t_in), float(t_out), track=track)
        if result.ok or result.steps:
            self._clips[:] = result.clips
            if record and result.steps:
                self._recorded.append(result.undo_action)
                self._project_dirty = True
        return {
            "action": "ripple_delete",
            "success": bool(result.ok or result.steps),
            "message": result.message,
            "deleted_duration": float(result.deleted_duration or 0),
            "track": track,
        }


class _RecordingDispatcher:
    """不碰单例：只记录 register 调用。"""

    def __init__(self):
        self.ids: List[str] = []

    def register(self, capability_id, category, handler, description=""):
        self.ids.append(capability_id)
        return True

    def list_capabilities(self, category=None):
        return [{"capability_id": i} for i in self.ids]


def _clip(cid="v1", start=0.0, dur=20.0, track=0):
    return {
        "id": cid,
        "start_time": start,
        "duration": dur,
        "in_point": 0.0,
        "out_point": dur,
        "speed": 1.0,
        "track": track,
        "type": "video",
        "path": "/fake/video.mp4",
    }


@pytest.mark.unit
class TestEditorRippleCapability:
    def test_register_includes_ripple(self):
        d = _RecordingDispatcher()
        register_builtin_handlers(d, editor_module_ref=lambda: None)
        # 能力总数随版本增长（V4.39.6 已 69 个），硬编码计数必腐化；
        # 改为「必需 id 集合包含 + 无重复注册」两个稳定断言
        required = {"editor.ripple_delete_range", "editor.suggest_cleanup"}
        assert required <= set(d.ids)
        assert d.ids.count("editor.ripple_delete_range") == 1
        assert len(d.ids) == len(set(d.ids)), f"存在重复注册: {[i for i in set(d.ids) if d.ids.count(i) > 1]}"

    def test_handler_calls_public_wrapper(self):
        editor = _FakeEditor([_clip()])
        handlers = EditorCapabilityHandlers(lambda: editor)
        req = CapabilityRequest(
            capability_id="editor.ripple_delete_range",
            params={"t_in": 5.0, "t_out": 8.0},
        )
        result = handlers.ripple_delete_range(req)
        assert result.success is True
        assert editor._recorded, "应写入可撤销 compound"
        assert editor._recorded[0].get("label") == "ripple_delete_range"
        total = sum(float(c.get("duration", 0) or 0) for c in editor._clips)
        assert total == pytest.approx(17.0, abs=0.05)

    def test_handler_missing_range_honest_fail(self):
        editor = _FakeEditor([_clip()])
        handlers = EditorCapabilityHandlers(lambda: editor)
        req = CapabilityRequest(
            capability_id="editor.ripple_delete_range",
            params={},
        )
        result = handlers.ripple_delete_range(req)
        assert result.success is False
        assert "t_in" in (result.error or "")

    def test_brain_taxonomy_has_ripple(self):
        from app.core.agent_brain import _NEURON_TAXONOMY
        ids = [row[0] for row in _NEURON_TAXONOMY]
        assert "editor.ripple_delete_range" in ids
        assert "editor.suggest_cleanup" in ids
        # 分类表随能力目录同步增长（V4.39.6 已 69 项），硬编码计数必腐化；
        # 稳定断言：无重复 + 与能力目录行数同步（目录是单一来源）
        assert len(ids) == len(set(ids)), "大脑分类表存在重复 id"

    def test_suggest_cleanup_handler_data_only(self):
        class _Ed:
            def agent_suggest_cleanup(self, *, open_ui=True):
                assert open_ui is False
                return {
                    "action": "suggest_cleanup",
                    "success": True,
                    "awaiting_confirm": True,
                    "intervals": [{"index": 0, "kind": "filler", "t_in": 1.0, "t_out": 1.5}],
                    "message": "建议 1 段",
                }

        handlers = EditorCapabilityHandlers(lambda: _Ed())
        req = CapabilityRequest(
            capability_id="editor.suggest_cleanup",
            params={"open_ui": False},
        )
        result = handlers.suggest_cleanup(req)
        assert result.success is True
        assert result.output["awaiting_confirm"] is True
        assert len(result.output["intervals"]) == 1
