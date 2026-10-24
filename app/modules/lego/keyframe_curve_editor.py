# -*- coding: utf-8 -*-
"""关键帧曲线编辑器（深工具补全 · 2026-09-16）

自包含 QWidget：可视化一条属性通道的关键帧曲线，支持
  - 拖拽关键帧点（改 time / value）
  - 双击点弹菜单改缓动类型
  - 右键删除点
  - 点击空白处新增点

插值后端复用 `app/core/keyframe_animation.py` 的 KeyframeAnimation
（贝塞尔 / 平滑 / 步进 + 10 种缓动），保证预览曲线与导出 bake 语义一致。

数据契约（与 editor_module.add_keyframes_to_clip 对齐）：
    keyframes = [{time_offset, value, easing?, interpolation?}, ...]
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
    from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
    from PyQt6.QtWidgets import QMenu, QWidget
except Exception:  # pragma: no cover
    Qt = QPointF = QRectF = None  # type: ignore
    QColor = QPainter = QPainterPath = QPen = None  # type: ignore
    QMenu = QWidget = None  # type: ignore
    pyqtSignal = None  # type: ignore

from app.core.keyframe_animation import (
    EasingType,
    InterpolationType,
    Keyframe,
    KeyframeAnimation,
)

_EASING_LABELS = {
    "linear": "线性",
    "ease_in": "缓入",
    "ease_out": "缓出",
    "ease_in_out": "缓入缓出",
    "bounce": "回弹",
    "elastic": "弹性",
    "back": "回退",
    "cubic_ease_in": "立方缓入",
    "cubic_ease_out": "立方缓出",
    "cubic_ease_in_out": "立方缓入缓出",
}

# 画布边距（px）
_MARGIN = 28


class KeyframeCurveEditor(QWidget):
    """单属性通道关键帧曲线编辑器。"""

    keyframes_changed = pyqtSignal(list) if pyqtSignal is not None else None

    def __init__(self, parent=None, value_range=(0.0, 1.0), fps: float = 30.0):
        if QWidget is None:
            raise RuntimeError("PyQt6 不可用")
        super().__init__(parent)
        self._keyframes: List[dict] = []
        self._value_range: Tuple[float, float] = value_range
        self._time_span: Tuple[float, float] = (0.0, 10.0)
        self._fps = fps
        self._drag_index: Optional[int] = None
        self._drag_axis: Optional[str] = None  # "xy" | "time" | "value"
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ─────────────── 数据装载 ───────────────

    def set_keyframes(self, keyframes: List[dict], time_span: Optional[Tuple[float, float]] = None):
        """装载关键帧。keyframes = [{time_offset, value, easing?, interpolation?}]。"""
        self._keyframes = [dict(k) for k in (keyframes or []) if isinstance(k, dict)]
        self._keyframes.sort(key=lambda k: float(k.get("time_offset", 0.0) or 0.0))
        if time_span is not None:
            self._time_span = (float(time_span[0]), float(time_span[1]))
        elif self._keyframes:
            t0 = float(self._keyframes[0].get("time_offset", 0.0) or 0.0)
            t1 = float(self._keyframes[-1].get("time_offset", 0.0) or 0.0)
            span = max(1.0, t1 - t0)
            self._time_span = (t0, t0 + span)
        self.update()

    def set_value_range(self, lo: float, hi: float):
        self._value_range = (float(lo), float(hi))
        self.update()

    def keyframes(self) -> List[dict]:
        return [dict(k) for k in self._keyframes]

    # ─────────────── 坐标换算 ───────────────

    def _plot_rect(self) -> QRectF:
        return QRectF(_MARGIN, _MARGIN, self.width() - 2 * _MARGIN, self.height() - 2 * _MARGIN)

    def _to_widget(self, t: float, v: float) -> QPointF:
        r = self._plot_rect()
        t0, t1 = self._time_span
        v0, v1 = self._value_range
        if t1 <= t0:
            t1 = t0 + 1.0
        if v1 <= v0:
            v1 = v0 + 1.0
        x = r.left() + (t - t0) / (t1 - t0) * r.width()
        y = r.bottom() - (v - v0) / (v1 - v0) * r.height()
        return QPointF(x, y)

    def _from_widget(self, x: float, y: float) -> Tuple[float, float]:
        r = self._plot_rect()
        t0, t1 = self._time_span
        v0, v1 = self._value_range
        if t1 <= t0:
            t1 = t0 + 1.0
        if v1 <= v0:
            v1 = v0 + 1.0
        t = t0 + (x - r.left()) / r.width() * (t1 - t0)
        v = v0 + (r.bottom() - y) / r.height() * (v1 - v0)
        return max(t0, min(t1, t)), max(v0, min(v1, v))

    # ─────────────── 曲线采样（复用后端插值）───────────────

    def _sample_curve(self, samples: int = 120) -> List[QPointF]:
        if not self._keyframes:
            return []
        anim = KeyframeAnimation(name="curve", fps=self._fps)
        for k in self._keyframes:
            kf = Keyframe(
                time=float(k.get("time_offset", 0.0) or 0.0),
                value=float(k.get("value", 0.0) or 0.0),
                interpolation=InterpolationType(k.get("interpolation", "linear")),
                easing=EasingType(k.get("easing", "linear")),
            )
            anim._keyframes.append(kf)
        t0, t1 = self._time_span
        pts = anim.get_curve_points(t0, t1, samples)
        return [self._to_widget(float(t), float(v)) for t, v in pts]

    def _point_rect(self, i: int) -> QRectF:
        k = self._keyframes[i]
        p = self._to_widget(float(k.get("time_offset", 0.0) or 0.0), float(k.get("value", 0.0) or 0.0))
        return QRectF(p.x() - 5, p.y() - 5, 10, 10)

    def _hit_index(self, pos) -> int:
        for i in range(len(self._keyframes)):
            if self._point_rect(i).contains(pos):
                return i
        return -1

    # ─────────────── 绘制 ───────────────

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#0f1115")
        p.fillRect(self.rect(), bg)

        r = self._plot_rect()
        # 网格
        grid_pen = QPen(QColor("#1f2430"), 1)
        p.setPen(grid_pen)
        for i in range(5):
            yy = r.top() + r.height() * i / 4
            p.drawLine(int(r.left()), int(yy), int(r.right()), int(yy))
        for i in range(5):
            xx = r.left() + r.width() * i / 4
            p.drawLine(int(xx), int(r.top()), int(xx), int(r.bottom()))

        # 值域/时间轴刻度文字
        p.setPen(QColor("#5a6273"))
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        v0, v1 = self._value_range
        for i in range(5):
            v = v0 + (v1 - v0) * i / 4
            yy = r.top() + r.height() * i / 4
            p.drawText(2, int(yy + 3), f"{v:.2f}")
        t0, t1 = self._time_span
        for i in range(5):
            t = t0 + (t1 - t0) * i / 4
            xx = r.left() + r.width() * i / 4
            p.drawText(int(xx - 12), self.height() - 6, f"{t:.1f}s")

        # 曲线
        pts = self._sample_curve()
        if len(pts) >= 2:
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            p.setPen(QPen(QColor("#1e6bde"), 2))
            p.drawPath(path)

        # 关键帧点
        for i, k in enumerate(self._keyframes):
            rect = self._point_rect(i)
            selected = i == self._drag_index
            p.setPen(QPen(QColor("#fff"), 1))
            p.setBrush(QColor("#22c55e" if selected else "#f59e0b"))
            p.drawEllipse(rect)

        p.end()

    # ─────────────── 交互 ───────────────

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            i = self._hit_index(event.position())
            if i >= 0:
                self._drag_index = i
                self._drag_axis = "xy"
                self.update()
                return
            # 点击空白：新增关键帧
            t, v = self._from_widget(event.position().x(), event.position().y())
            self._keyframes.append({"time_offset": round(t, 3), "value": round(v, 3), "easing": "linear"})
            self._keyframes.sort(key=lambda k: float(k.get("time_offset", 0.0) or 0.0))
            self._drag_index = next(
                (idx for idx, k in enumerate(self._keyframes)
                 if abs(float(k.get("time_offset", 0.0) or 0.0) - t) < 1e-6), len(self._keyframes) - 1
            )
            self._drag_axis = "xy"
            self._emit_change()
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            i = self._hit_index(event.position())
            if i >= 0:
                self._show_context_menu(i, event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_index is None:
            return
        t, v = self._from_widget(event.position().x(), event.position().y())
        k = self._keyframes[self._drag_index]
        k["time_offset"] = round(t, 3)
        k["value"] = round(v, 3)
        self._emit_change()
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_index is not None:
            self._drag_index = None
            self._drag_axis = None
            self.update()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        i = self._hit_index(event.position())
        if i >= 0:
            self._show_context_menu(i, event.globalPosition().toPoint())

    def _show_context_menu(self, index: int, global_pos):
        menu = QMenu(self)
        cur = self._keyframes[index].get("easing", "linear")
        for key, label in _EASING_LABELS.items():
            act = menu.addAction(("✓ " if key == cur else "") + label)
            act.setData(key)
        del_act = menu.addAction("🗑 删除该点")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is del_act:
            self._keyframes.pop(index)
            self._emit_change()
            self.update()
            return
        key = chosen.data()
        if key:
            self._keyframes[index]["easing"] = key
            self._emit_change()
            self.update()

    def _emit_change(self):
        if self.keyframes_changed is not None:
            try:
                self.keyframes_changed.emit(self.keyframes())
            except Exception as e:  # pragma: no cover
                logger.debug("关键帧变更信号发射失败: %s", e)
