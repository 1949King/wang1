"""app/tests/test_zcov_timeline.py — timeline 批次零覆盖模块补测。

覆盖四个当前 0% 覆盖的模块：
  app/core/keyframe_animation.py
  app/core/timeline_manager.py
  app/core/timeline_dsl.py
  app/core/proxy_media.py

纪律：
  * 只创建本测试文件，绝不修改 app/core/ 下的任何源文件。
  * 源码 bug 只在注释 / 最终报告中记录，不做修复，也不"顺手绕过"。
  * 不依赖网络、GPU、真实 ffmpeg 转码；需要的地方用 monkeypatch 替身。
  * 无 sleep 时序测试（异步用 threading.Event 同步）。
"""
import os
import threading
import time
from pathlib import Path

import pytest

from app.core.keyframe_animation import (
    KeyframeAnimation,
    AnimatableProperties,
    EasingType,
    InterpolationType,
)
from app.core.timeline_manager import TimelineManager
from app.core import timeline_dsl as dsl
import app.core.proxy_media as pm


# ═══════════════════════════ keyframe_animation ═══════════════════════════

ALL_EASINGS = list(EasingType)


@pytest.mark.parametrize("easing", ALL_EASINGS)
def test_easing_endpoints_zero_and_one(easing):
    """所有缓动函数必须精确经过 (0,0) 与 (1,1)。"""
    a = KeyframeAnimation()
    assert a._apply_easing(0.0, easing) == pytest.approx(0.0)
    assert a._apply_easing(1.0, easing) == pytest.approx(1.0)


@pytest.mark.parametrize("easing", ALL_EASINGS)
def test_easing_clamps_out_of_range(easing):
    """t 越界被 clamp 到 [0,1]，不得外推。"""
    a = KeyframeAnimation()
    assert a._apply_easing(-5.0, easing) == pytest.approx(0.0)
    assert a._apply_easing(5.0, easing) == pytest.approx(1.0)


def test_easing_known_midpoints():
    """逐条锁定各缓动在 t=0.5 的解析值（判别性：写错公式立刻失败）。"""
    a = KeyframeAnimation()
    assert a._apply_easing(0.5, EasingType.LINEAR) == pytest.approx(0.5)
    assert a._apply_easing(0.5, EasingType.EASE_IN) == pytest.approx(0.25)
    assert a._apply_easing(0.5, EasingType.EASE_OUT) == pytest.approx(0.75)
    assert a._apply_easing(0.5, EasingType.EASE_IN_OUT) == pytest.approx(0.5)
    assert a._apply_easing(0.5, EasingType.CUBIC_EASE_IN) == pytest.approx(0.125)
    assert a._apply_easing(0.5, EasingType.CUBIC_EASE_OUT) == pytest.approx(0.875)
    assert a._apply_easing(0.5, EasingType.CUBIC_EASE_IN_OUT) == pytest.approx(0.5)


def test_easing_back_overshoots_negative():
    """BACK 是 overshoot 曲线：中段跌到 0 以下（线性/其他不会）。"""
    a = KeyframeAnimation()
    assert a._apply_easing(0.5, EasingType.BACK) < 0.0


def test_easing_nan_does_not_crash_and_stays_in_range():
    """NaN 输入不得抛异常，clamp 后落在 [0,1]（实测 min/max 语义落点为 1.0）。"""
    a = KeyframeAnimation()
    r = a._apply_easing(float("nan"), EasingType.LINEAR)
    assert isinstance(r, float)
    assert 0.0 <= r <= 1.0
    assert r == pytest.approx(1.0)
    assert 0.0 <= a._apply_easing(float("nan"), EasingType.BACK) <= 1.0


def test_get_value_empty_returns_zero():
    assert KeyframeAnimation().get_value(3.0) == 0.0


def test_get_value_single_keyframe_constant():
    a = KeyframeAnimation()
    a.add_keyframe(5.0, 42.0)
    assert a.get_value(-100.0) == 42.0
    assert a.get_value(5.0) == 42.0
    assert a.get_value(999.0) == 42.0


def test_get_value_linear_interpolation_between_two():
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 0.0)
    a.add_keyframe(2.0, 100.0)
    assert a.get_value(1.0) == pytest.approx(50.0)
    assert a.get_value(0.5) == pytest.approx(25.0)


def test_get_value_clamps_before_first_and_after_last():
    a = KeyframeAnimation()
    a.add_keyframe(1.0, 10.0)
    a.add_keyframe(2.0, 20.0)
    assert a.get_value(0.0) == 10.0
    assert a.get_value(5.0) == 20.0


def test_get_value_mid_segment_uses_left_keyframe_easing():
    """3 关键帧时，中间段使用**左端点**的缓动（EASE_IN -> 25 而非线性的 50）。"""
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 0.0)
    a.add_keyframe(1.0, 0.0, easing=EasingType.EASE_IN)
    a.add_keyframe(2.0, 100.0)
    assert a.get_value(1.5) == pytest.approx(25.0)


def test_first_segment_easing_taken_from_second_keyframe():
    """可疑点（不修，仅锁定真实行为）：首段用的是**第二个**关键帧的 easing。

    2 关键帧 (0,0,EASE_IN)/(1,100,LINEAR)；若按左端点 EASE_IN 应为 25，
    实测 50（代码对首段取了 kf1.easing）。见 keyframe_animation.py:356。
    """
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 0.0, easing=EasingType.EASE_IN)
    a.add_keyframe(1.0, 100.0, easing=EasingType.LINEAR)
    assert a.get_value(0.5) == pytest.approx(50.0)


def test_step_interpolation_holds_left_value():
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 10.0, interpolation=InterpolationType.STEP)
    a.add_keyframe(1.0, 20.0)
    assert a.get_value(0.9) == 10.0
    assert a.get_value(0.0) == 10.0


def test_bezier_interpolation_matches_curve():
    """贝塞尔取控制点 y 分量做三次插值；端点必须精确落在 p0/p1。"""
    a = KeyframeAnimation()
    kf0 = a.add_keyframe(0.0, 0.0, interpolation=InterpolationType.BEZIER)
    kf0.bezier_control1 = (0.42, 0.0)
    kf0.bezier_control2 = (0.58, 1.0)
    a.add_keyframe(1.0, 100.0)
    # t=0.5 时: 3*0.5*0.25*1 + 0.125*100 = 0.375 + 12.5
    assert a.get_value(0.5) == pytest.approx(12.875)
    assert a.get_value(0.0) == pytest.approx(0.0)
    assert a.get_value(1.0) == pytest.approx(100.0)


def test_smooth_interpolation_uses_neighbors():
    """SMOOTH 用四邻域 Hermite 切线；非对称数据下偏离线性中点。"""
    a = KeyframeAnimation()
    for t, v in ((0.0, 0.0), (1.0, 0.0), (3.0, 100.0), (4.0, 110.0)):
        a.add_keyframe(t, v, interpolation=InterpolationType.SMOOTH)
    # 线性中点 = 50；SMOOTH 实测 ≈ 49.5833
    assert a.get_value(2.0) == pytest.approx(49.58333, abs=1e-4)


def test_value_cache_invalidated_on_update():
    """命中缓存后更新关键帧，必须返回新值（否则是缓存未失效的 bug）。"""
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 0.0)
    a.add_keyframe(1.0, 100.0)
    assert a.get_value(0.5) == pytest.approx(50.0)
    a.update_keyframe(1, value=200.0)
    assert a.get_value(0.5) == pytest.approx(100.0)


def test_add_get_sorted_nearest_and_index():
    a = KeyframeAnimation()
    a.add_keyframe(2.0, 20.0)
    a.add_keyframe(0.5, 5.0)
    a.add_keyframe(1.0, 10.0)
    assert [k.time for k in a.get_keyframes()] == [0.5, 1.0, 2.0]
    assert a.get_keyframe_at_time(1.0) is a.get_keyframes()[1]
    assert a.get_keyframe_index_at_time(2.0) == 2
    assert a.get_keyframe_index_at_time(9.0) == -1
    assert a.get_nearest_keyframe(0.6).value == 5.0
    assert a.get_nearest_keyframe(1.9).value == 20.0
    assert KeyframeAnimation().get_nearest_keyframe(0.0) is None


def test_remove_keyframe_at_and_in_range():
    a = KeyframeAnimation()
    for t in (0.0, 1.0, 2.0, 3.0):
        a.add_keyframe(t, t)
    assert a.remove_keyframe_at(1.0) is True
    assert a.remove_keyframe_at(1.0) is False
    assert a.remove_keyframes_in_range(1.0, 2.5) == 1
    assert [k.time for k in a.get_keyframes()] == [0.0, 3.0]


def test_update_and_remove_by_index_bounds():
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 1.0)
    assert a.update_keyframe(0, value=9.0, easing=EasingType.EASE_IN) is True
    kf = a.get_keyframes()[0]
    assert kf.value == 9.0 and kf.easing is EasingType.EASE_IN
    assert a.update_keyframe(5, value=1.0) is False
    assert a.remove_keyframe(0) is True
    assert a.remove_keyframe(0) is False


def test_shift_and_scale_keyframes_only_hit_range():
    a = KeyframeAnimation()
    for t in (0.0, 1.0, 2.0):
        a.add_keyframe(t, t * 10)
    a.shift_keyframes(0.5, 1.5, 5.0)          # 只有 t=1.0 命中
    assert [k.time for k in a.get_keyframes()] == [0.0, 2.0, 6.0]
    a.scale_keyframes(0.0, 100.0, 0.5)        # 以 start=0 为锚缩放
    assert [round(k.time, 3) for k in a.get_keyframes()] == [0.0, 1.0, 3.0]


def test_copy_keyframes_offset_and_empty():
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 0.0)
    a.add_keyframe(1.0, 10.0)
    a.add_keyframe(2.0, 20.0)
    copies = a.copy_keyframes(0.0, 1.0, 10.0)
    assert [k.time for k in copies] == [10.0, 11.0]
    assert a.get_keyframe_count() == 5
    assert a.copy_keyframes(5.0, 6.0, 0.0) == []


def test_to_list_from_list_roundtrip():
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 1.0, easing=EasingType.EASE_IN,
                   interpolation=InterpolationType.STEP, label="L")
    a.add_keyframe(1.0, 2.0)
    b = KeyframeAnimation()
    b.from_list(a.to_list())
    assert b.get_keyframe_count() == 2
    kf = b.get_keyframes()[0]
    assert kf.easing is EasingType.EASE_IN
    assert kf.interpolation is InterpolationType.STEP
    assert kf.label == "L"
    assert b.get_value(0.0) == pytest.approx(1.0)


def test_clone_is_independent_and_merge_overwrites():
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 1.0)
    a.add_keyframe(1.0, 2.0)
    c = a.clone()
    c.update_keyframe(0, value=99.0)
    assert a.get_keyframes()[0].value == 1.0
    other = KeyframeAnimation()
    other.add_keyframe(1.0, 77.0)
    other.add_keyframe(2.0, 5.0)
    a.merge(other)
    assert a.get_keyframe_count() == 3
    assert a.get_value(1.0) == pytest.approx(77.0)


def test_curve_points_count_endpoints_and_fallback():
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 0.0)
    a.add_keyframe(2.0, 20.0)
    pts = a.get_curve_points(0.0, 2.0, samples=5)
    assert len(pts) == 5
    assert pts[0][0] == pytest.approx(0.0)
    assert pts[-1][0] == pytest.approx(2.0)
    assert pts[2][1] == pytest.approx(10.0)
    # samples<=1 回退到 100
    assert len(a.get_curve_points(0.0, 1.0, samples=0)) == 100


def test_tangent_is_a_real_derivative():
    """回归锁（2026-10-09 修）：get_tangent 曾经恒返回 0.0。

    根因：get_value 的缓存键是 round(time_sec, 2)，而 get_tangent 取 t±0.001
    两点 —— 两点四舍五入到同一缓存键 -> 第二次直接命中第一次的缓存 ->
    差商恒为 0。曲线编辑器的切线永远是平的。
    修法：拆出无缓存的 _value_at 供中心差分使用。

    线性斜坡 [0,2]->[0,100] 的斜率恒为 50。判别力：改回带缓存的 get_value
    立刻变回 0.0，这条就红。
    """
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 0.0)
    a.add_keyframe(2.0, 100.0)
    assert a.get_tangent(1.0) == pytest.approx(50.0, rel=1e-3)
    # 平段：两个等值关键帧之间切线应为 0（别把"真的平"也判成 bug）
    b = KeyframeAnimation()
    b.add_keyframe(0.0, 7.0)
    b.add_keyframe(2.0, 7.0)
    assert abs(b.get_tangent(1.0)) < 1e-6
    # 缓存语义不受影响：连续两次 get_value 结果一致
    assert a.get_value(1.0) == a.get_value(1.0) == pytest.approx(50.0)


def test_animation_range_and_empty_default():
    assert KeyframeAnimation().get_animation_range() == (0.0, 1.0)
    a = KeyframeAnimation()
    a.add_keyframe(3.0, 0.0)
    a.add_keyframe(1.0, 0.0)
    assert a.get_animation_range() == (1.0, 3.0)


def test_keyframe_changed_callback_actions():
    a = KeyframeAnimation()
    events = []
    a.keyframe_changed_callback = lambda kf, action: events.append(action)
    assert a.keyframe_changed_callback is not None
    a.add_keyframe(0.0, 1.0)
    a.update_keyframe(0, value=2.0)
    a.remove_keyframe(0)
    assert events == ["added", "updated", "removed"]
    a.keyframe_changed_callback = None
    assert a.keyframe_changed_callback is None


def test_clear_notifies_each_keyframe():
    a = KeyframeAnimation()
    a.add_keyframe(0.0, 1.0)
    a.add_keyframe(1.0, 2.0)
    events = []
    a.keyframe_changed_callback = lambda kf, act: events.append(act)
    a.clear()
    assert a.get_keyframe_count() == 0
    assert events == ["removed", "removed"]


# ─────────────────────── AnimatableProperties ───────────────────────

def test_invalid_property_raises():
    p = AnimatableProperties()
    with pytest.raises(ValueError):
        p.add_keyframe("not_a_property", 0.0, 1.0)


def test_property_defaults_by_name():
    p = AnimatableProperties()
    assert p.get_property_value("opacity", 0.0) == 1.0
    assert p.get_property_value("scale_x", 0.0) == 1.0
    assert p.get_property_value("volume", 0.0) == 1.0
    assert p.get_property_value("position_x", 0.0) == 0.0
    assert p.get_property_value("blur", 0.0) == 0.0


def test_channel_creation_interpolation_and_active_values():
    p = AnimatableProperties()
    p.add_keyframe("opacity", 0.0, 0.0)
    p.add_keyframe("opacity", 1.0, 1.0)
    assert p.get_property_value("opacity", 0.5) == pytest.approx(0.5)
    assert p.get_channel_names() == ["opacity"]
    assert p.get_keyframe_count() == 2
    active = p.get_active_values(0.5)
    assert set(active.keys()) == {"opacity"}
    assert active["opacity"] == pytest.approx(0.5)
    assert p.has_animation() is True


def test_add_keyframes_to_multiple_skips_missing_values():
    p = AnimatableProperties()
    p.add_keyframes_to_multiple(["position_x", "position_y", "rotation"], 1.0,
                                {"position_x": 10.0, "position_y": 20.0})
    assert p.get_property_value("position_x", 1.0) == 10.0
    assert p.get_property_value("position_y", 1.0) == 20.0
    assert "rotation" not in p.get_channel_names()


def test_link_property_is_usable():
    """回归锁（2026-10-09 修）：link_property 曾经一用就 RecursionError。

    根因：get_property_value(link) 调 get_all_values()，后者对**每个**属性
    （含自身）再调 get_property_value —— 自引用递归。=> 链接特性完全不可用。
    修法：表达式只吃「原始值快照」_base_values()，链路断开递归。
    """
    p = AnimatableProperties()
    p.add_keyframe("position_x", 0.0, 3.0)
    p.link_property("position_y", lambda v: v["position_x"] * 2)
    assert p.is_linked("position_y") is True
    assert p.get_property_value("position_y", 0.0) == 6.0
    assert p.get_all_values(0.0)["position_y"] == 6.0, "get_all_values 也必须可用"

    # 互相引用也不能死循环
    p.link_property("position_x", lambda v: v["position_y"] * 2)
    assert p.get_property_value("position_y", 0.0) == 6.0

    # 解链后恢复正常
    p.unlink_property("position_y")
    p.unlink_property("position_x")
    assert p.is_linked("position_y") is False
    assert p.get_property_value("position_y", 0.0) == 0.0


def test_group_operations_remove_shift_scale_copy():
    p = AnimatableProperties()
    p.add_keyframe("position_x", 0.0, 0.0)
    p.add_keyframe("position_x", 1.0, 10.0)
    p.add_keyframe("opacity", 0.0, 1.0)
    assert p.get_keyframes_at_time(1.0).keys() == {"position_x"}
    assert p.remove_keyframes_at_time(1.0) == 1
    assert p.get_keyframe_count() == 2
    p.shift_all_keyframes(0.0, 10.0, 5.0)
    assert p.get_channel("position_x").get_keyframes()[0].time == 5.0
    p.copy_all_keyframes(5.0, 5.0, 20.0)
    assert p.get_channel("position_x").get_keyframe_count() == 2
    before = p.get_keyframe_count()
    assert p.remove_keyframes_in_range(0.0, 100.0) == before
    assert p.get_keyframe_count() == 0


def test_remove_keyframe_and_ranges():
    p = AnimatableProperties()
    assert p.remove_keyframe("opacity", 0) is False        # 无通道
    p.add_keyframe("opacity", 0.0, 1.0)
    assert p.remove_keyframe("opacity", 0) is True
    assert p.remove_keyframe("opacity", 0) is False


def test_group_ranges_curve_data_and_missing_channel():
    p = AnimatableProperties()
    p.add_keyframe("opacity", 2.0, 1.0)
    p.add_keyframe("opacity", 4.0, 0.0)
    assert p.get_animation_range() == (2.0, 4.0)
    assert AnimatableProperties().get_animation_range() == (0.0, 1.0)
    data = p.get_curve_data("opacity", 2.0, 4.0, samples=3)
    assert len(data) == 3 and data[0][0] == pytest.approx(2.0)
    assert p.get_curve_data("nope", 0.0, 1.0) == []


def test_clone_merge_clear_and_groups():
    p = AnimatableProperties()
    p.add_keyframe("opacity", 0.0, 1.0)
    c = p.clone()
    c.get_channel("opacity").update_keyframe(0, value=0.2)
    assert p.get_property_value("opacity", 0.0) == 1.0
    other = AnimatableProperties()
    other.add_keyframe("scale_x", 0.0, 2.0)
    p.merge(other)
    assert p.get_property_value("scale_x", 0.0) == 2.0
    assert set(p.get_property_group("transform")) == {
        "position_x", "position_y", "scale_x", "scale_y", "rotation"}
    assert p.get_property_group("nope") == []
    p.clear()
    assert p.get_channel_names() == [] and p.has_animation() is False


def test_animatable_to_dict_from_dict_roundtrip():
    p = AnimatableProperties()
    p.add_keyframe("opacity", 0.0, 1.0)
    p.add_keyframe("opacity", 1.0, 0.0)
    p.add_keyframe("rotation", 0.0, 45.0)
    data = p.to_dict()
    assert set(data["channels"].keys()) == {"opacity", "rotation"}
    q = AnimatableProperties()
    q.from_dict(data)
    assert set(q.get_channel_names()) == {"opacity", "rotation"}
    assert q.get_property_value("opacity", 0.5) == pytest.approx(0.5)
    assert q.get_property_value("rotation", 0.0) == 45.0


# ═══════════════════════════ timeline_manager ═══════════════════════════

def _mk_clip(mgr, tl, start=0.0, duration=10.0, uid=None, name=None,
             path=None, track_id=None):
    """加片段并把时间戳型 id 改写成稳定 id，便于断言。"""
    tid = track_id or tl["tracks"][0]["id"]
    info = {"start_time": start, "duration": duration}
    if name is not None:
        info["name"] = name
    if path is not None:
        info["path"] = path
    clip = mgr.add_clip(tl["id"], tid, info)
    if uid is not None:
        clip["id"] = uid
    return clip


def test_create_timeline_structure():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T1", resolution="1280x720", fps=24)
    assert tl["name"] == "T1"
    assert tl["settings"] == {"resolution": "1280x720", "fps": 24, "duration": 0}
    assert [t["id"] for t in tl["tracks"]] == ["video_1", "audio_1"]
    assert mgr.current_timeline_id == tl["id"]
    assert mgr.get_timeline(tl["id"]) is tl
    assert mgr.get_current_timeline() is tl
    assert tl["markers"] == [] and tl["keyframes"] == []


def test_add_track_numbering_and_missing_timeline():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    t = mgr.add_track(tl["id"], "video", "自定义")
    assert t["id"] == "video_3" and t["name"] == "自定义" and t["clips"] == []
    # 编号按轨道**总数**而非同类型计数
    assert mgr.add_track(tl["id"], "audio")["id"] == "audio_4"
    with pytest.raises(ValueError):
        mgr.add_track("missing", "video")


def test_add_clip_defaults_and_duration_update():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    clip = mgr.add_clip(tl["id"], "video_1",
                        {"path": "/media/a/foo.mp4", "start_time": 2.0, "duration": 5.0})
    assert clip["name"] == "foo.mp4"           # 无 name 时取 basename
    assert clip["path"] == "/media/a/foo.mp4"
    assert clip["start_time"] == 2.0 and clip["duration"] == 5.0
    assert clip["in_point"] == 0 and clip["out_point"] == 5.0
    assert clip["volume"] == 1.0 and clip["opacity"] == 1.0
    assert tl["settings"]["duration"] == 7.0


def test_add_clip_error_paths():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    with pytest.raises(ValueError):
        mgr.add_clip("missing", "video_1", {})
    with pytest.raises(ValueError):
        mgr.add_clip(tl["id"], "missing_track", {})


def test_move_clip_same_track_and_cross_track():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    c = _mk_clip(mgr, tl, start=0.0, duration=4.0, uid="c1")
    assert mgr.move_clip(tl["id"], "video_1", "c1", 10.0) is True
    assert c["start_time"] == 10.0
    assert tl["settings"]["duration"] == 14.0
    assert mgr.move_clip(tl["id"], "video_1", "c1", 2.0, new_track_id="audio_1") is True
    assert tl["tracks"][0]["clips"] == []
    assert mgr.get_clip(tl["id"], "c1") in tl["tracks"][1]["clips"]
    assert mgr.move_clip("missing", "video_1", "c1", 0.0) is False


def test_move_clip_unknown_clip_or_new_track_returns_false():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, uid="c1")
    assert mgr.move_clip(tl["id"], "video_1", "ghost", 5.0) is False
    assert mgr.move_clip(tl["id"], "video_1", "c1", 5.0, new_track_id="ghost") is False


def test_resize_clip_branches():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    c = _mk_clip(mgr, tl, start=1.0, duration=10.0, uid="c1")
    # 调整出点：in_point 不变
    assert mgr.resize_clip(tl["id"], "video_1", "c1", 4.0) is True
    assert (c["duration"], c["in_point"], c["out_point"], c["start_time"]) == (4.0, 0, 4.0, 1.0)
    # 调整入点：out_point 不变，start_time 同步平移
    assert mgr.resize_clip(tl["id"], "video_1", "c1", 3.0, adjust_in_point=True) is True
    assert (c["duration"], c["in_point"], c["out_point"], c["start_time"]) == (3.0, 1.0, 4.0, 2.0)
    assert mgr.resize_clip(tl["id"], "video_1", "ghost", 5.0) is False
    assert mgr.resize_clip("missing", "video_1", "c1", 5.0) is False


def test_get_clips_at_time_half_open_boundary():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, start=1.0, duration=4.0, uid="c1")
    assert [c["id"] for c in mgr.get_clips_at_time(tl["id"], 1.0)] == ["c1"]   # 含起点
    assert [c["id"] for c in mgr.get_clips_at_time(tl["id"], 4.9)] == ["c1"]
    assert mgr.get_clips_at_time(tl["id"], 5.0) == []                          # 不含终点
    assert mgr.get_clips_at_time("missing", 1.0) == []


def test_delete_clip_success_and_failure():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, start=0.0, duration=5.0, uid="c1")
    assert mgr.delete_clip(tl["id"], "video_1", "c1") is True
    assert mgr.get_clip(tl["id"], "c1") is None
    assert mgr.delete_clip(tl["id"], "video_1", "c1") is False
    assert mgr.delete_clip(tl["id"], "ghost", "c1") is False
    assert mgr.delete_clip("missing", "video_1", "c1") is False


def test_update_clip_marker_keyframe():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, uid="c1")
    assert mgr.update_clip(tl["id"], "c1", volume=0.5, notes="hi") is True
    c = mgr.get_clip(tl["id"], "c1")
    assert c["volume"] == 0.5 and c["notes"] == "hi"
    assert mgr.update_clip(tl["id"], "ghost", volume=0.1) is False
    # 缺失时间线 -> ValueError（该分支在 id 生成之前）
    with pytest.raises(ValueError):
        mgr.add_marker("missing", 3.0)
    with pytest.raises(ValueError):
        mgr.add_keyframe("missing", "c1", 1.5, "opacity", 0.3)


def test_add_marker_and_add_keyframe_now_work():
    """回归锁（2026-10-09 修）：标记 / 关键帧写入**曾经 100% 不可用**。

    根因：两方法形参名就叫 `time`（timeline_manager.py:342 / :373），在函数体内
    遮蔽了模块级 `import time`；随后 `int(time.time())` 在 float 上取 `.time`
    -> AttributeError ⇒ 特性等于不存在。
    修法：加模块级别名 `_time`，公开签名不动。本用例断言**功能真的可用** ——
    若有人把实现改回裸 `time.time()`，这里立刻红。
    """
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, uid="c1")

    marker = mgr.add_marker(tl["id"], 3.0, name="M")
    assert marker["id"].startswith("marker_") and marker["time"] == 3.0
    assert len(tl["markers"]) == 1

    kf = mgr.add_keyframe(tl["id"], "c1", 1.5, "opacity", 0.3)
    assert kf["id"].startswith("keyframe_") and kf["value"] == 0.3
    assert len(tl["keyframes"]) == 1

    # 关键字调用（形参仍叫 time）必须继续可用 —— 证明没破坏公开签名
    assert mgr.add_marker(tl["id"], time=4.0, name="K")["time"] == 4.0


def test_get_clip_missing_returns_none():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    assert mgr.get_clip(tl["id"], "ghost") is None
    assert mgr.get_clip("missing", "ghost") is None


def test_set_and_delete_timeline():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    assert mgr.set_current_timeline("missing") is False
    mgr.current_timeline_id = None
    assert mgr.get_current_timeline() is None
    assert mgr.set_current_timeline(tl["id"]) is True
    assert mgr.delete_timeline(tl["id"]) is True
    assert mgr.current_timeline_id is None
    assert mgr.delete_timeline(tl["id"]) is False


def test_virtual_window_scale_clamp_and_clips():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, start=5.0, duration=4.0, uid="c1")
    _mk_clip(mgr, tl, start=20.0, duration=2.0, uid="c2")
    mgr.set_virtual_scale(99.0)
    assert mgr.virtual_scale == 10.0                # 上限
    mgr.set_virtual_scale(0.0)
    assert mgr.virtual_scale == 0.1                 # 下限
    mgr.set_virtual_scale(1.0)
    mgr.set_virtual_window(0.0, 10.0)
    assert {c["id"] for c in mgr.get_virtual_clips()} == {"c1"}
    win = mgr.get_virtual_window()
    assert win["duration"] == pytest.approx(10.0)
    assert win["scale"] == 1.0 and win["offset"] == 0.0


def test_virtual_timeline_mapping_and_cache_clear():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, start=4.0, duration=6.0, uid="c1")
    mgr.set_virtual_scale(2.0)
    mgr.set_virtual_offset(0.0)
    mgr.set_virtual_window(0.0, 100.0)
    entry = mgr.virtual_timeline["c1"]
    assert entry["virtual_start"] == pytest.approx(2.0)    # 4/2
    assert entry["virtual_end"] == pytest.approx(5.0)      # 10/2
    assert entry["virtual_duration"] == pytest.approx(3.0)
    assert entry["original_clip"]["id"] == "c1"
    assert len(mgr.timeline_cache) >= 1
    mgr.clear_timeline_cache()
    assert mgr.timeline_cache == {} and mgr.virtual_timeline == {}


def test_timeline_stats():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, start=0.0, duration=3.0, uid="c1")
    _mk_clip(mgr, tl, start=10.0, duration=2.0, uid="c2")
    st = mgr.get_timeline_stats(tl["id"])
    assert st["total_clips"] == 2 and st["total_tracks"] == 2
    assert st["video_tracks"] == 1 and st["audio_tracks"] == 1
    assert st["total_duration"] == pytest.approx(12.0)
    assert mgr.get_timeline_stats("missing") == {}
    mgr.current_timeline_id = None
    assert mgr.get_timeline_stats() == {}


def test_ripple_delete_shifts_following_clips():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, start=0.0, duration=2.0, uid="c1")
    _mk_clip(mgr, tl, start=2.0, duration=3.0, uid="c2")
    _mk_clip(mgr, tl, start=5.0, duration=1.0, uid="c3")
    assert mgr.ripple_delete_clip(tl["id"], "video_1", "c2") is True
    assert mgr.get_clip(tl["id"], "c2") is None
    assert mgr.get_clip(tl["id"], "c1")["start_time"] == 0.0
    assert mgr.get_clip(tl["id"], "c3")["start_time"] == 2.0     # 5 - 3
    assert tl["settings"]["duration"] == pytest.approx(3.0)
    assert mgr.ripple_delete_clip("missing", "video_1", "c1") is False
    assert mgr.ripple_delete_clip(tl["id"], "ghost", "c1") is False
    assert mgr.ripple_delete_clip(tl["id"], "video_1", "ghost") is False


def test_insert_clip_shifts_later_clips():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, start=2.0, duration=2.0, uid="c1")   # [2,4]
    _mk_clip(mgr, tl, start=0.0, duration=1.0, uid="c0")   # [0,1]
    new = mgr.insert_clip(tl["id"], "video_1", {"start_time": 1.0, "duration": 3.0})
    assert new is not None
    assert mgr.get_clip(tl["id"], "c1")["start_time"] == 5.0   # 2+3
    assert mgr.get_clip(tl["id"], "c0")["start_time"] == 0.0   # 未受影响
    assert mgr.insert_clip("missing", "video_1", {}) is None
    assert mgr.insert_clip(tl["id"], "ghost", {}) is None


def test_overwrite_clip_removes_overlaps():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, start=0.0, duration=2.0, uid="a")    # [0,2]
    _mk_clip(mgr, tl, start=3.0, duration=2.0, uid="b")    # [3,5]
    _mk_clip(mgr, tl, start=10.0, duration=1.0, uid="d")   # [10,11]
    new = mgr.overwrite_clip(tl["id"], "video_1", {"start_time": 1.0, "duration": 3.0})
    assert new is not None
    remaining = {c["id"] for c in tl["tracks"][0]["clips"]}
    assert "a" not in remaining and "b" not in remaining   # [1,4] 命中重叠
    assert "d" in remaining
    assert mgr.overwrite_clip("missing", "video_1", {}) is None
    assert mgr.overwrite_clip(tl["id"], "ghost", {}) is None


def test_lift_clip_keeps_gap():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, start=0.0, duration=2.0, uid="c1")
    _mk_clip(mgr, tl, start=4.0, duration=2.0, uid="c2")
    assert mgr.lift_clip(tl["id"], "video_1", "c1") is True
    assert mgr.get_clip(tl["id"], "c2")["start_time"] == 4.0   # 空隙保留
    assert mgr.lift_clip(tl["id"], "video_1", "ghost") is False


def test_ripple_move_clip_forward_and_left_clamp():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    _mk_clip(mgr, tl, start=0.0, duration=2.0, uid="a")
    _mk_clip(mgr, tl, start=4.0, duration=2.0, uid="b")
    assert mgr.ripple_move_clip(tl["id"], "video_1", "b", 6.0) is True
    assert mgr.get_clip(tl["id"], "b")["start_time"] == 6.0
    # 向左挪会被左侧片段末端(2.0)顶住
    assert mgr.ripple_move_clip(tl["id"], "video_1", "b", 1.5) is True
    assert mgr.get_clip(tl["id"], "b")["start_time"] == 2.0
    assert mgr.ripple_move_clip("missing", "video_1", "b", 0.0) is False
    assert mgr.ripple_move_clip(tl["id"], "ghost", "b", 0.0) is False
    assert mgr.ripple_move_clip(tl["id"], "video_1", "ghost", 0.0) is False


def test_slip_clip_adjusts_in_out_and_rejects_negative():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    c = _mk_clip(mgr, tl, start=1.0, duration=4.0, uid="c1")   # in=0,out=4
    assert mgr.slip_clip(tl["id"], "video_1", "c1", 2.0) is True
    assert c["in_point"] == 2.0 and c["out_point"] == 6.0
    assert mgr.slip_clip(tl["id"], "video_1", "c1", -5.0) is False   # new_in<0
    assert c["in_point"] == 2.0                                      # 未被改动
    assert mgr.slip_clip(tl["id"], "video_1", "ghost", 1.0) is False


def test_slide_clip_moves_position_only():
    mgr = TimelineManager()
    tl = mgr.create_timeline("T")
    c = _mk_clip(mgr, tl, start=2.0, duration=3.0, uid="c1")
    assert mgr.slide_clip(tl["id"], "video_1", "c1", 5.0) is True
    assert c["start_time"] == 7.0
    assert c["in_point"] == 0 and c["out_point"] == 3.0
    assert mgr.slide_clip(tl["id"], "video_1", "ghost", 1.0) is False


# ═══════════════════════════ timeline_dsl ═══════════════════════════

def test_timerange_duration_overlaps_contains():
    r = dsl.TimeRange(1.0, 4.0)
    assert r.duration == pytest.approx(3.0)
    assert dsl.TimeRange(4.0, 1.0).duration == 0.0          # 反向 -> max(0,负)
    assert r.overlaps(dsl.TimeRange(3.0, 5.0)) is True
    assert r.overlaps(dsl.TimeRange(4.0, 5.0)) is False     # 端点相触不算重叠
    assert r.contains(1.0) and r.contains(4.0)              # 闭区间
    assert r.contains(0.99) is False


def test_resolution_aspect_and_vertical():
    assert dsl.Resolution(1920, 1080).aspect_ratio == pytest.approx(1920 / 1080)
    assert dsl.Resolution(1080, 1920).is_vertical is True
    assert dsl.Resolution(1920, 1080).is_vertical is False
    assert dsl.Resolution(100, 0).aspect_ratio == 1.0       # 高度为 0 兜底


def test_clipproperty_get_value_at():
    assert dsl.ClipProperty("opacity", 0.5).get_value_at(1.0) == 0.5
    p = dsl.ClipProperty("opacity", 1.0,
                         [dsl.Keyframe(0.0, 0.0), dsl.Keyframe(2.0, 10.0)])
    assert p.get_value_at(-1.0) == 0.0      # 早于首帧
    assert p.get_value_at(5.0) == 10.0      # 晚于末帧
    assert p.get_value_at(1.0) == pytest.approx(5.0)


def test_track_add_sorts_remove_get_and_duration():
    tr = dsl.Track(id="tr1")
    late = dsl.Clip(id="late", range=dsl.TimeRange(5.0, 7.0))
    early = dsl.Clip(id="early", range=dsl.TimeRange(0.0, 2.0))
    assert tr.add_clip(late) is True and tr.add_clip(early) is True
    assert [c.id for c in tr.clips] == ["early", "late"]    # 按 start 排序
    assert tr.total_duration == pytest.approx(7.0)
    assert tr.get_clip_at(1.0).id == "early"
    assert tr.get_clip_at(3.0) is None
    assert tr.remove_clip("early") is True
    assert tr.remove_clip("early") is False
    assert dsl.Track(id="e").total_duration == 0.0


def test_timeline_create_default():
    tl = dsl.Timeline.create_default("我的", width=1080, height=1920, fps=25.0)
    assert tl.name == "我的"
    assert tl.settings.resolution.width == 1080
    assert tl.settings.resolution.is_vertical is True
    assert tl.settings.fps == 25.0
    assert [t.id for t in tl.tracks] == ["track_v_1", "track_a_1", "track_s_1"]
    assert tl.id.startswith("timeline_")


def test_timeline_track_operations():
    tl = dsl.Timeline.create_default()
    t = tl.add_track("叠加", dsl.TrackType.OVERLAY)
    assert t.type is dsl.TrackType.OVERLAY
    assert tl.get_track(t.id) is t
    assert tl.move_track(t.id, 0) is True
    assert tl.tracks[0] is t
    assert tl.move_track("ghost", 0) is False
    assert tl.remove_track(t.id) is True
    assert tl.remove_track(t.id) is False


def test_timeline_clip_add_move_trim():
    tl = dsl.Timeline.create_default()
    clip = dsl.Clip(id="c1", source="s.mp4",
                    range=dsl.TimeRange(0.0, 10.0),
                    source_range=dsl.TimeRange(0.0, 10.0))
    assert tl.add_clip_to_track("track_v_1", clip) is True
    assert tl.add_clip_to_track("ghost", clip) is False
    assert tl.get_clip("c1") is clip
    assert tl.settings.duration == pytest.approx(10.0)      # _update_duration
    assert tl.move_clip("c1", 5.0) is True
    assert clip.range.start == 5.0 and clip.range.end == 15.0
    assert tl.move_clip("ghost", 1.0) is False
    assert tl.trim_clip("c1", 5.0, 5.0) is False            # start>=end 非法
    assert tl.trim_clip("ghost", 0.0, 1.0) is False
    assert tl.trim_clip("c1", 1.0, 4.0) is True
    assert clip.range.start == 1.0 and clip.range.end == 4.0


def test_timeline_add_clip_by_index_and_remove():
    tl = dsl.Timeline.create_default()
    c = dsl.Clip(id="c1", range=dsl.TimeRange(0.0, 6.0))
    assert tl.add_clip(0, c) is True
    assert tl.add_clip(99, c) is False                      # 越界
    assert tl.settings.duration == pytest.approx(6.0)
    assert tl.remove_clip("c1") is True
    assert tl.remove_clip("c1") is False
    assert tl.settings.duration == 0.0


def test_split_clip_math():
    tl = dsl.Timeline.create_default()
    clip = dsl.Clip(id="c1", name="源", source="s",
                    range=dsl.TimeRange(0.0, 10.0),
                    source_range=dsl.TimeRange(0.0, 10.0))
    tl.add_clip_to_track("track_v_1", clip)
    assert tl.split_clip("ghost", 1.0) is None
    assert tl.split_clip("c1", 99.0) is None                # 不在范围内
    right = tl.split_clip("c1", 4.0)
    assert right is not None
    assert (clip.range.start, clip.range.end) == (0.0, 4.0)
    assert clip.source_range.end == pytest.approx(4.0)
    assert (right.range.start, right.range.end) == (4.0, 10.0)
    assert (right.source_range.start, right.source_range.end) == (4.0, 10.0)
    assert right.type is dsl.ClipType.VIDEO
    assert len(tl.tracks[0].clips) == 2


def test_json_roundtrip_preserves_structure():
    tl = dsl.Timeline.create_default("RT")
    clip = dsl.Clip(
        id="c1", name="片段", source="s.mp4",
        range=dsl.TimeRange(1.0, 5.0), source_range=dsl.TimeRange(0.0, 4.0),
        volume=0.7, blend_mode=dsl.BlendMode.MULTIPLY,
        transform=dsl.ClipTransform(x=3.0, opacity=0.5),
        properties=[dsl.ClipProperty("opacity", 1.0, [dsl.Keyframe(0.0, 1.0)])],
    )
    tl.add_clip_to_track("track_v_1", clip)
    tl.markers.append(dsl.Marker(id="m1", time=2.0, name="M"))
    tl.add_track("叠加", dsl.TrackType.OVERLAY)

    back = dsl.Timeline.from_json(tl.to_json())
    assert back.name == "RT"
    assert [t.id for t in back.tracks] == [t.id for t in tl.tracks]
    c2 = back.get_clip("c1")
    assert c2.source == "s.mp4"
    assert (c2.range.start, c2.range.end) == (1.0, 5.0)
    assert c2.blend_mode is dsl.BlendMode.MULTIPLY
    assert c2.transform.x == 3.0 and c2.transform.opacity == 0.5
    assert c2.properties[0].name == "opacity"
    assert c2.properties[0].keyframes[0].value == 1.0
    assert back.markers[0].id == "m1" and back.markers[0].time == 2.0
    assert back.tracks[-1].type is dsl.TrackType.OVERLAY
    # from_json 也接受 dict
    assert dsl.Timeline.from_json(tl.to_dict()).id == tl.id


def test_validate_timeline_errors_and_pass():
    errs = dsl.validate_timeline({})
    assert any("缺失 id" in e for e in errs)
    assert any("缺失 tracks" in e for e in errs)
    ok = {
        "id": "1", "name": "n", "version": "1.0.0",
        "settings": {"resolution": {"width": 1, "height": 1}, "fps": 30},
        "tracks": [{"id": "t1", "type": "video", "clips": [{"id": "c1", "range": {}}]}],
    }
    assert dsl.validate_timeline(ok) == []
    bad = {
        "id": "1", "name": "n", "version": "1.0.0",
        "settings": {"fps": 30},                       # 缺 resolution
        "tracks": [{"type": "video", "clips": [{"id": "c1"}]}],   # 缺 track id / clip range
    }
    errs = dsl.validate_timeline(bad)
    assert "settings 缺失 resolution" in errs
    assert any("tracks[0] 缺失 id" in e for e in errs)
    assert any("缺失 range" in e for e in errs)


def test_convert_from_v1_migration():
    v1 = {
        "id": "old", "name": "旧", "last_modified": "2020",
        "settings": {"fps": 25, "duration": 12.0},
        "tracks": [{
            "id": "vt", "name": "视频", "type": "video",
            "clips": [{
                "id": "oldc", "name": "旧片段", "type": "video",
                "file_path": "a.mp4", "start_time": 1.0, "end_time": 4.0,
                "trim_start": 0.5, "trim_end": 3.5,
            }],
        }],
    }
    tl = dsl.convert_from_v1(v1)
    assert isinstance(tl, dsl.Timeline)
    assert tl.id == "old" and tl.name == "旧"
    assert tl.settings.fps == 25
    assert tl.tracks[0].id == "vt"
    c = tl.tracks[0].clips[0]
    assert c.source == "a.mp4"                          # file_path -> source
    assert (c.range.start, c.range.end) == (1.0, 4.0)   # start_time/end_time
    assert (c.source_range.start, c.source_range.end) == (0.5, 3.5)


def test_timeline_dsl_imported_but_unused_evidence():
    """timeline_dsl 唯一全库引用点 `editing_capabilities.py:57` 仅 import、零使用。

    证据：该文件对 timeline_dsl 只有一行 import，且 Timeline / validate_timeline /
    convert_from_v1 三个符号在文件内没有任何调用或实例化（Timeline 仅出现在
    import 行与 :20 的文档字符串 "- 时间轴 DSL: Timeline"）。
    """
    src = (Path(__file__).resolve().parents[1] / "core"
           / "editing_capabilities.py").read_text(encoding="utf-8")
    assert src.count("from app.core.timeline_dsl import") == 1
    assert "validate_timeline(" not in src
    assert "convert_from_v1(" not in src
    assert "Timeline(" not in src and "Timeline." not in src


# ═══════════════════════════ proxy_media ═══════════════════════════

def _pm(tmp_path, strategy=pm.ProxyStrategy.AUTO, config=None):
    return pm.ProxyMediaManager(cache_dir=str(tmp_path / "proxies"),
                                strategy=strategy, config=config)


def test_proxy_config_defaults():
    cfg = pm.ProxyConfig()
    assert (cfg.target_width, cfg.target_height) == (960, 960)
    assert cfg.codec == "libx264" and cfg.preset == "ultrafast"
    assert cfg.auto_width_threshold == 1280 and cfg.auto_height_threshold == 720
    assert cfg.auto_bitrate_threshold_kbps == 4000


def test_should_generate_proxy_matrix(tmp_path):
    dis = _pm(tmp_path, pm.ProxyStrategy.DISABLED)
    alw = _pm(tmp_path, pm.ProxyStrategy.ALWAYS)
    auto = _pm(tmp_path, pm.ProxyStrategy.AUTO)
    assert dis.enabled is False and auto.enabled is True
    assert dis.should_generate_proxy("a.mp4", 4000, 4000, 99999) is False
    assert alw.should_generate_proxy("a.mp4", 100, 100, 1) is True
    # AUTO：未知规格 -> 保守生成
    assert auto.should_generate_proxy("a.mp4", 0, 0, 0) is True
    # AUTO：恰好等于阈值 -> 不生成
    assert auto.should_generate_proxy("a.mp4", 1280, 720, 4000) is False
    # 超宽 / 超高 / 高码率 -> 生成
    assert auto.should_generate_proxy("a.mp4", 1281, 720, 0) is True
    assert auto.should_generate_proxy("a.mp4", 1280, 721, 0) is True
    assert auto.should_generate_proxy("a.mp4", 1280, 720, 4001) is True


def test_get_proxy_path_deterministic_and_mtime_sensitive(tmp_path):
    m = _pm(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    p1 = m.get_proxy_path(str(src))
    assert p1 == m.get_proxy_path(str(src))
    assert p1.endswith(".mp4")
    assert Path(p1).parent == Path(m.cache_dir)
    assert len(Path(p1).stem) == 16
    old = os.path.getmtime(str(src))
    os.utime(str(src), (old + 100, old + 100))
    assert m.get_proxy_path(str(src)) != p1                # mtime 变化 -> 失效
    # 源不存在：mtime 兜底 0，仍返回可用路径
    assert m.get_proxy_path(str(tmp_path / "nope.mp4")).endswith(".mp4")


def test_has_proxy_and_resolve_for_preview(tmp_path):
    m = _pm(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    assert m.has_proxy(str(src)) is False
    assert m.resolve_for_preview(str(src)) == str(src)
    proxy = Path(m.get_proxy_path(str(src)))
    proxy.write_bytes(b"proxy")
    assert m.has_proxy(str(src)) is True
    assert m.resolve_for_preview(str(src)) == str(proxy)
    proxy.write_bytes(b"")
    assert m.has_proxy(str(src)) is False                  # 空文件不算命中
    dis = _pm(tmp_path, pm.ProxyStrategy.DISABLED)
    proxy.write_bytes(b"proxy")
    assert dis.resolve_for_preview(str(src)) == str(src)   # 禁用 -> 永远源
    assert dis.resolve_for_preview("") == ""


def test_get_status_pending_and_done(tmp_path):
    m = _pm(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    st = m.get_status(str(src))
    assert st["status"] == "pending" and st["progress"] == 0.0
    assert st["proxy_path"] == "" and st["error"] == ""
    Path(m.get_proxy_path(str(src))).write_bytes(b"p")
    st2 = m.get_status(str(src))
    assert st2["status"] == "done" and st2["progress"] == 1.0
    assert st2["proxy_path"] == m.get_proxy_path(str(src))


def test_set_cache_dir_and_strategy(tmp_path):
    m = _pm(tmp_path)
    new = tmp_path / "other_dir"
    m.set_cache_dir(str(new))
    assert Path(m.cache_dir).name == "other_dir"
    assert Path(m.cache_dir).is_dir()
    m.set_cache_dir("")
    assert Path(m.cache_dir).name == "other_dir"           # 空路径被忽略
    m.set_strategy(pm.ProxyStrategy.DISABLED)
    assert m.enabled is False
    m.set_strategy(pm.ProxyStrategy.ALWAYS)
    assert m.enabled is True


def test_build_ffmpeg_cmd_structure(tmp_path, monkeypatch):
    m = _pm(tmp_path)
    monkeypatch.setattr(m, "_find_ffmpeg", lambda: "ffmpeg")
    cmd = m._build_ffmpeg_cmd("in.mp4", "out.mp4")
    assert cmd[0] == "ffmpeg"
    assert "-vf" in cmd and "-preset" in cmd and "ultrafast" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-b:a") + 1] == "128k"
    assert "+faststart" in cmd
    assert cmd[-1] == "out.mp4"
    assert any("min(960,iw)" in a for a in cmd)            # 默认长边 960
    assert "-r" not in cmd                                 # fps=0 不写 -r


def test_build_ffmpeg_cmd_adds_fps_and_long_edge(tmp_path, monkeypatch):
    cfg = pm.ProxyConfig(fps=24, target_width=1280, target_height=720)
    m = _pm(tmp_path, config=cfg)
    monkeypatch.setattr(m, "_find_ffmpeg", lambda: "ffmpeg")
    cmd = m._build_ffmpeg_cmd("in.mp4", "out.mp4")
    assert cmd[cmd.index("-r") + 1] == "24"
    assert any("min(1280,iw)" in a for a in cmd)           # long_edge=max(1280,720)


def test_cache_listing_size_and_clear(tmp_path):
    m = _pm(tmp_path)
    Path(m.cache_dir, "a.mp4").write_bytes(b"12345")
    Path(m.cache_dir, "b.mp4").write_bytes(b"1234567890")
    Path(m.cache_dir, "note.txt").write_bytes(b"x")         # 非 mp4 忽略
    assert {i["name"] for i in m.list_cached()} == {"a.mp4", "b.mp4"}
    assert m.get_cache_size_mb() == pytest.approx(15 / (1024 * 1024))
    assert m.clear_cache() == 2
    assert m.list_cached() == []


def test_clear_cache_lru_removes_oldest_first(tmp_path):
    m = _pm(tmp_path)
    for i, (name, size) in enumerate((("old.mp4", 1000), ("mid.mp4", 2000),
                                      ("new.mp4", 3000))):
        p = Path(m.cache_dir, name)
        p.write_bytes(b"\0" * size)
        os.utime(p, (1000.0 + i, 1000.0 + i))               # 越小越老
    keep = (6000 / (1024 * 1024)) * 0.5
    assert m.clear_cache_lru(keep_mb=keep) == 2
    assert {i["name"] for i in m.list_cached()} == {"new.mp4"}


def test_clear_idle_cache(tmp_path):
    m = _pm(tmp_path)
    old = Path(m.cache_dir, "old.mp4")
    recent = Path(m.cache_dir, "recent.mp4")
    old.write_bytes(b"x" * 10)
    recent.write_bytes(b"y" * 10)
    now = time.time()
    os.utime(old, (now - 40 * 86400, now - 40 * 86400))
    os.utime(recent, (now - 3600, now - 3600))
    assert m.clear_idle_cache(max_age_days=14.0) == 1
    assert not old.exists() and recent.exists()


def test_generate_sync_missing_source(tmp_path):
    m = _pm(tmp_path)
    assert m.generate_sync(str(tmp_path / "nope.mp4")) is False


def test_generate_sync_success_with_fake_ffmpeg(tmp_path, monkeypatch):
    m = _pm(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x" * 100)

    class FakeProc:
        stderr = [b"frame=1 time=00:00:01.00 bitrate=2kbps\n", b"time=00:00:02.00\n"]

        def wait(self):
            return 0

    def fake_popen(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"proxy-bytes-here")      # 模拟产出非空文件
        return FakeProc()

    monkeypatch.setattr(pm.subprocess, "Popen", fake_popen)
    prog = []
    assert m.generate_sync(str(src), on_progress=prog.append) is True
    assert m.has_proxy(str(src)) is True
    assert prog == [0.5, 0.5]                               # 两条含 time= 的日志
    st = m.get_status(str(src))
    assert st["status"] == "done" and st["progress"] == 1.0
    assert st["proxy_path"] == m.get_proxy_path(str(src))
    # 已有代理直接命中，不再起进程
    assert m.generate_sync(str(src)) is True


def test_generate_sync_failure_records_error(tmp_path, monkeypatch):
    m = _pm(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x" * 100)

    class FakeProc:
        stderr = [b"boom failure reason\n"]

        def wait(self):
            return 1

    monkeypatch.setattr(pm.subprocess, "Popen", lambda cmd, **kw: FakeProc())
    assert m.generate_sync(str(src)) is False
    st = m.get_status(str(src))
    assert st["status"] == "failed" and "boom" in st["error"]


def test_generate_async_invokes_callback(tmp_path, monkeypatch):
    m = _pm(tmp_path)
    monkeypatch.setattr(m, "generate_sync", lambda p, on_progress=None: True)
    got = {}
    ev = threading.Event()

    def on_done(ok, path):
        got["ok"] = ok
        got["path"] = path
        ev.set()

    src = str(tmp_path / "src.mp4")
    t = m.generate_async(src, on_done=on_done)
    assert t.daemon is True
    assert ev.wait(timeout=5.0)
    assert got["ok"] is True
    assert got["path"] == m.get_proxy_path(src)


def test_get_proxy_manager_singleton(monkeypatch):
    pm.reset_proxy_manager()
    created = []

    class Stub:
        def __init__(self, strategy=None, config=None):
            created.append((strategy, config))

    monkeypatch.setattr(pm, "ProxyMediaManager", Stub)
    a = pm.get_proxy_manager()
    b = pm.get_proxy_manager()
    assert a is b and len(created) == 1
    pm.reset_proxy_manager()
    c = pm.get_proxy_manager()
    assert c is not a and len(created) == 2
    pm.reset_proxy_manager()
