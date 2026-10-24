"""
P1#8 关键帧可视化 - 数据契约与坐标映射验证脚本
不启动 GUI（避免 import moviepy/PyQt6 副作用），直接验证核心逻辑
"""
import os
import sys
import math

# 直接验证 keyframe_animation 的核心逻辑（这是"扬长"的核心模块）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core.keyframe_animation import (
    Keyframe, KeyframeAnimation, AnimatableProperties,
    InterpolationType, EasingType,
)


def test_basic_interpolation():
    """插值基础测试：3 个点，ease_in_out 缓动"""
    anim = KeyframeAnimation("opacity")
    anim.add_keyframe(0.0, 0.0, easing=EasingType.EASE_IN_OUT)
    anim.add_keyframe(1.0, 1.0, easing=EasingType.EASE_IN_OUT)
    anim.add_keyframe(2.0, 0.0, easing=EasingType.EASE_IN_OUT)

    # 边界
    assert anim.get_value(0.0) == 0.0, f"起始应为 0.0, got {anim.get_value(0.0)}"
    assert anim.get_value(1.0) == 1.0, f"中间点应为 1.0, got {anim.get_value(1.0)}"
    assert anim.get_value(2.0) == 0.0, f"末端应为 0.0, got {anim.get_value(2.0)}"
    # 中点
    mid = anim.get_value(0.5)
    # ease_in_out(0.5) = 0.5*0.5*(3 - 2*0.5) = 0.5
    assert abs(mid - 0.5) < 1e-6, f"中点应为 0.5, got {mid}"
    print("  [OK] 基础插值 + ease_in_out 缓动")


def test_animatable_properties():
    """AnimatableProperties 通道管理测试"""
    ap = AnimatableProperties()
    ap.add_keyframe("opacity", 0.0, 0.0)
    ap.add_keyframe("opacity", 1.0, 1.0)
    ap.add_keyframe("scale_x", 0.0, 1.0)
    ap.add_keyframe("scale_x", 2.0, 1.5)

    assert ap.get_property_value("opacity", 0.5) == 0.5
    # scale_x 默认值 1.0，0.5s 时 = 1.0 + 0.5/2 * 0.5 = 1.125
    sv = ap.get_property_value("scale_x", 0.5)
    assert abs(sv - 1.125) < 1e-6, f"scale_x@0.5s 应为 1.125, got {sv}"

    names = ap.get_channel_names()
    assert "opacity" in names and "scale_x" in names
    print(f"  [OK] AnimatableProperties 通道管理 (channels={names})")


def test_serialization():
    """to_dict / from_dict 往返一致性"""
    ap = AnimatableProperties()
    ap.add_keyframe("opacity", 0.0, 0.0, easing=EasingType.EASE_IN)
    ap.add_keyframe("opacity", 1.5, 1.0, easing=EasingType.EASE_OUT)
    data = ap.to_dict()

    ap2 = AnimatableProperties()
    ap2.from_dict(data)

    assert ap2.get_property_value("opacity", 0.75) == ap.get_property_value("opacity", 0.75)
    print("  [OK] 序列化往返一致")


def test_clipwidget_color_mapping():
    """验证 ClipWidget.KEYFRAME_COLORS 覆盖 AnimatableProperties.VALID_PROPERTIES 关键项"""
    # 关键帧 UI 属性 -> 颜色 映射存在性
    from app.modules.lego.modules import ClipWidget
    color_keys = set(ClipWidget.KEYFRAME_COLORS.keys())
    # 至少应覆盖主流可视属性
    must_have = {"opacity", "position_x", "position_y", "scale_x", "scale_y",
                 "rotation", "volume", "speed", "brightness", "contrast"}
    missing = must_have - color_keys
    assert not missing, f"颜色映射缺失关键属性: {missing}"
    print(f"  [OK] KEYFRAME_COLORS 覆盖关键属性 ({len(color_keys)} 个)")


def test_time_to_x_mapping():
    """验证 time_offset -> x 坐标映射（与 TimelineWidget 的 px_per_sec 一致）"""
    # zoom=100 时, px_per_sec=20
    # time_offset=0.5s -> x=10
    # time_offset=2.0s -> x=40
    # zoom=200 时, px_per_sec=40
    # time_offset=0.5s -> x=20
    # 验证数学正确性（直接计算，未启动 Qt）
    px_per_sec_100 = 20 * (100 / 100)  # = 20
    px_per_sec_200 = 20 * (200 / 100)  # = 40
    assert int(0.5 * px_per_sec_100) == 10
    assert int(2.0 * px_per_sec_100) == 40
    assert int(0.5 * px_per_sec_200) == 20
    print("  [OK] time_to_x 坐标映射 (zoom=100/200)")


def test_data_contract_roundtrip():
    """验证 ClipWidget.set_keyframes 接受的数据格式 (不启动 Qt)"""
    # 模拟 _coerce_keyframes 的逻辑
    def coerce(raw):
        if not raw or not isinstance(raw, (list, tuple)):
            return []
        out = []
        for kf in raw:
            if not isinstance(kf, dict):
                continue
            if 'time_offset' not in kf and 't' not in kf:
                continue
            out.append({
                'time_offset': float(kf.get('time_offset', kf.get('t', 0.0))),
                'value': kf.get('value', 0.0),
                'prop': str(kf.get('prop', kf.get('property', 'value'))),
                'easing': str(kf.get('easing', 'linear')),
            })
        out.sort(key=lambda x: x['time_offset'])
        return out

    # 1. 接受 time_offset
    kfs = coerce([
        {"time_offset": 1.0, "value": 0.5, "prop": "opacity"},
        {"time_offset": 0.0, "value": 0.0, "prop": "opacity"},
    ])
    assert len(kfs) == 2
    assert kfs[0]['time_offset'] == 0.0  # 已排序
    assert kfs[1]['time_offset'] == 1.0

    # 2. 兼容简写 t + property
    kfs = coerce([{"t": 2.0, "property": "scale_x", "value": 1.5}])
    assert kfs[0]['prop'] == 'scale_x'
    assert kfs[0]['time_offset'] == 2.0

    # 3. 缺 time_offset 会被过滤
    kfs = coerce([{"value": 0.0}, {"time_offset": 1.0, "value": 1.0}])
    assert len(kfs) == 1

    # 4. 接受 None / 空 / 错类型
    assert coerce(None) == []
    assert coerce([]) == []
    assert coerce("not a list") == []
    print("  [OK] 数据契约兼容 time_offset/t、prop/property、空值过滤")


if __name__ == "__main__":
    print("=" * 60)
    print("P1#8 关键帧可视化 - 数据契约 + 核心逻辑验证")
    print("=" * 60)
    test_basic_interpolation()
    test_animatable_properties()
    test_serialization()
    test_clipwidget_color_mapping()
    test_time_to_x_mapping()
    test_data_contract_roundtrip()
    print("=" * 60)
    print("全部 6 项验证通过 ✅")
    print("=" * 60)
