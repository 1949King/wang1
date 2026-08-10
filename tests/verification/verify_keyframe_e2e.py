"""
P1#8 关键帧可视化 - 端到端集成测试（offscreen 模式）
验证：
  1. 不带 keyframes 的 clip 仍正常工作
  2. 带 keyframes 的 clip 可正常渲染（不抛异常）
  3. set_keyframes / get_keyframes 数据流一致
  4. mousePress 命中关键帧 -> keyframe_clicked 信号发出
  5. TimelineWidget.add_clip 桥接 clip_keyframe_clicked 信号
"""
import os
import sys

# 必须在 import PyQt6 之前设置 offscreen
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 让脚本作为模块被 import 时也能找到 app/
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint

app = QApplication.instance() or QApplication(sys.argv)


def test_clipwidget_no_keyframes():
    """无 keyframes：paintEvent 应走 super().paintEvent，不做任何额外绘制"""
    from app.modules.lego.modules import ClipWidget
    cw = ClipWidget({"path": "/tmp/a.mp4", "duration": 5.0})
    cw.resize(200, 38)
    cw.show()
    app.processEvents()
    assert cw.get_keyframes() == [], "无 keyframes 数据时应返回空列表"
    print("  [OK] 无 keyframes clip 正常工作")


def test_clipwidget_with_keyframes():
    """带 keyframes：paintEvent 应能调用而不抛异常"""
    from app.modules.lego.modules import ClipWidget
    cw = ClipWidget({"path": "/tmp/b.mp4", "duration": 5.0})
    cw.resize(200, 38)
    cw.show()
    cw.set_keyframes([
        {"time_offset": 0.0, "value": 0.0, "prop": "opacity", "easing": "ease_in"},
        {"time_offset": 1.0, "value": 1.0, "prop": "opacity", "easing": "ease_out"},
        {"time_offset": 2.5, "value": 1.5, "prop": "scale_x", "easing": "linear"},
    ])
    app.processEvents()
    kfs = cw.get_keyframes()
    assert len(kfs) == 3, f"应有 3 个关键帧, got {len(kfs)}"
    # clip_data['keyframes'] 同步
    assert cw.clip_data.get('keyframes') and len(cw.clip_data['keyframes']) == 3
    # 选中态 -> 再次 paint
    cw.set_selected(True)
    app.processEvents()
    print("  [OK] 带 keyframes clip 正常渲染 + clip_data 同步")


def test_clipwidget_coerce_filters():
    """脏数据：None / 缺 time_offset / 错类型 都被过滤"""
    from app.modules.lego.modules import ClipWidget
    cw = ClipWidget({"path": "/tmp/c.mp4", "duration": 5.0, "keyframes": [
        {"value": 0.0},  # 缺 time_offset -> 过滤
        {"time_offset": 1.0, "value": 1.0, "prop": "opacity"},
        "not a dict",   # 错类型 -> 过滤
        {"t": 2.0, "property": "scale_x", "value": 1.5},  # t + property 简写
    ]})
    cw.show()
    app.processEvents()
    kfs = cw.get_keyframes()
    assert len(kfs) == 2, f"过滤后应剩 2 个, got {len(kfs)}"
    # 简写 t 已被规整成 time_offset
    assert kfs[1]['time_offset'] == 2.0
    assert kfs[1]['prop'] == 'scale_x'
    print("  [OK] 脏数据过滤 + 简写兼容")


def test_clipwidget_keyframe_clicked_signal():
    """点击关键帧点 -> keyframe_clicked 信号被发出"""
    from app.modules.lego.modules import ClipWidget
    cw = ClipWidget({"path": "/tmp/d.mp4", "duration": 5.0})
    cw.resize(300, 38)
    cw.show()
    cw.set_keyframes([
        {"time_offset": 1.0, "value": 1.0, "prop": "opacity"},
    ])
    app.processEvents()

    captured = []
    cw.keyframe_clicked.connect(lambda clip, kf: captured.append((clip, kf)))

    # zoom 默认 100 -> px_per_sec=20 -> time_offset=1.0 -> x=20
    # y 在底部条带: h=38, band_top=31, y_center=34
    # 鼠标位置要 (20, 34)，但 mousePressEvent 需要 QMouseEvent
    from PyQt6.QtGui import QMouseEvent, QGuiApplication
    me = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPoint(20, 34),
        cw.mapToGlobal(QPoint(20, 34)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    cw.mousePressEvent(me)
    app.processEvents()

    assert len(captured) == 1, f"关键帧点击信号未发出, got {len(captured)}"
    clip, kf = captured[0]
    assert kf['prop'] == 'opacity'
    assert kf['time_offset'] == 1.0
    # 命中关键帧不应切换选中态（保持 False）
    assert cw._is_selected is False, "点击关键帧不应切换选中态"
    print("  [OK] 关键帧点击信号 + 命中不打断选中流")


def test_timeline_widget_bridges_signal():
    """TimelineWidget.add_clip 后应能接收到关键帧点击的桥接信号"""
    from app.modules.lego.modules import TimelineWidget
    tl = TimelineWidget()
    tl.resize(800, 300)
    tl.show()
    app.processEvents()

    captured = []
    tl.clip_keyframe_clicked.connect(lambda clip, kf: captured.append((clip, kf)))

    clip_data = {"id": "test_clip_1", "path": "/tmp/e.mp4", "duration": 5.0}
    cw = tl.add_clip(clip_data, 0)
    assert cw is not None, "add_clip 应返回 ClipWidget"

    # 注入关键帧
    cw.set_keyframes([{"time_offset": 0.5, "value": 0.8, "prop": "volume"}])
    app.processEvents()

    # 模拟点击关键帧点
    from PyQt6.QtGui import QMouseEvent
    me = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPoint(10, 34),  # x=10 对应 time_offset=0.5
        cw.mapToGlobal(QPoint(10, 34)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    cw.mousePressEvent(me)
    app.processEvents()

    assert len(captured) == 1, f"TimelineWidget 未桥接关键帧信号, got {len(captured)}"
    clip, kf = captured[0]
    assert clip['id'] == "test_clip_1"
    assert kf['prop'] == 'volume'
    print("  [OK] TimelineWidget 桥接 keyframe_clicked -> clip_keyframe_clicked")


if __name__ == "__main__":
    print("=" * 60)
    print("P1#8 关键帧可视化 - 端到端集成测试 (offscreen)")
    print("=" * 60)
    test_clipwidget_no_keyframes()
    test_clipwidget_with_keyframes()
    test_clipwidget_coerce_filters()
    test_clipwidget_keyframe_clicked_signal()
    test_timeline_widget_bridges_signal()
    print("=" * 60)
    print("全部 5 项集成测试通过 ✅")
    print("=" * 60)
