# -*- coding: utf-8 -*-
"""帧级精剪审计/对齐计划测试（2026-10-20）。"""
from types import SimpleNamespace

from app.core.capability_dispatcher import CapabilityRequest
from app.core.capability_handlers_precision import PrecisionCapabilityHandlers
from app.core.precision_edit import (
    audit_timeline,
    plan_frame_align,
    snap_seconds,
)


def _clip(cid="c1", start=0.0, dur=1.0, track=0, **kw):
    data = {"id": cid, "start_time": start, "duration": dur, "track": track,
            "type": "video", "path": kw.pop("path", "")}
    data.update(kw)
    return data


def test_snap_seconds_modes():
    assert snap_seconds(1.01, 30) == 1.0
    assert snap_seconds(1.01, 30, "floor") == 1.0
    assert snap_seconds(1.01, 30, "ceil") == 1.0333333333333334
    assert abs(snap_seconds(0.02, 30) - 1 / 30) < 1e-12


def test_audit_off_grid_start_and_duration():
    report = audit_timeline([_clip(start=0.02, dur=1.02)], 30)
    codes = {i["code"] for i in report["issues"]}
    assert "off_grid_start" in codes
    assert "off_grid_duration" in codes
    assert report["ok"] is True  # warning 不算 error
    assert any(i["suggested"] for i in report["issues"])


def test_audit_subframe_gap_and_overlap():
    gap = audit_timeline([_clip("a", 0.0, 1.0), _clip("b", 1.01, 0.5)], 30)
    assert any(i["code"] == "subframe_gap" for i in gap["issues"])
    overlap = audit_timeline([_clip("a", 0.0, 1.0), _clip("b", 0.99, 0.5)], 30)
    assert any(i["code"] == "overlap" for i in overlap["issues"])


def test_audit_av_offset_is_info():
    report = audit_timeline([
        _clip("v", 0.0, 1.0, type="video", path="x.mp4"),
        _clip("a", 0.05, 1.0, track=1, type="audio", path="x.mp4"),
    ], 30)
    av = [i for i in report["issues"] if i["code"] == "av_offset"]
    assert av and av[0]["severity"] == "info"


def test_audit_errors():
    report = audit_timeline([
        _clip("a", -0.1, 0.0, speed=0),
        _clip("b", 0.0, 1.0, in_point=2.0, out_point=1.0),
    ], 30)
    codes = {i["code"] for i in report["issues"]}
    assert {"negative_start", "non_positive_duration", "invalid_speed",
            "bad_source_window"} <= codes
    assert report["ok"] is False


def test_plan_align_snaps_and_syncs_out_point():
    plan = plan_frame_align([
        _clip("a", start=0.02, dur=1.02, in_point=0.0, out_point=2.0),
    ], 30)
    assert plan["change_count"] == 1
    change = plan["changes"][0]
    assert abs(change["after"]["start_time"] - 1 / 30) < 1e-5
    assert abs(change["after"]["duration"] - 31 / 30) < 1e-5
    assert abs(change["after"]["out_point"] - (2.0 + (31 / 30 - 1.02))) < 1e-5


def test_plan_align_skips_if_source_window_would_break():
    plan = plan_frame_align([
        _clip("a", start=0.0, dur=1.01, in_point=1.99, out_point=2.0),
    ], 30)
    assert plan["change_count"] == 0
    assert plan["skipped"]


def test_handler_reads_editor_and_fails_when_closed():
    fake = SimpleNamespace(_clips=[_clip(start=0.02)], _timeline_widget=SimpleNamespace(_edit_fps=30))
    handlers = PrecisionCapabilityHandlers(lambda: fake)
    req = CapabilityRequest(capability_id="editor.precision_audit")
    result = handlers.precision_audit(req)
    assert result.success
    assert result.output["fps"] == 30
    assert result.output["clip_count"] == 1

    closed = PrecisionCapabilityHandlers(lambda: None)
    failed = closed.precision_audit(req)
    assert failed.success is False
    assert "未就绪" in failed.error
