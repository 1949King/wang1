"""
设置面板可复用控件 (Settings Widgets)
=====================================

直抄 AI-Canvas-tauri settings.css 的组件视觉:
- ToggleSwitch      = `.sidebar-pref-switch`（iOS 风格 38×22 开关，带弹簧动画）
- SegmentedControl  = 节点工具栏「极简图标 / 图标+文本」分段控件
- MiniPreview       = `.sidebar-pref-window`（88×52 迷你界面预览，6 种形态）
- PreferenceCard    = `.sidebar-pref-card`（预览 + 标题/描述 + 开关）
- PresetCard        = 外观预设卡（中央节点卡 + 真实画布背景渐变 + 名称 + 当前使用徽标）
- AppearancePreview = 大预览（节点卡 + 虚线连接 + 当前主题圆点，跟随当前 preset 切换背景）

设计纪律（见 MEMORY 核心不变量第 8/9 条）:
- 颜色一律走 ThemeManager.get_colors() / theme_tokens，禁止内联 hex
- 自绘控件在 set_theme() 里 update() 重绘，跟随主程序明暗
- 动画用 QPropertyAnimation + parent=self 防 GC（floating_sidebar 同款教训）

V4.43.4 任务 #288
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import (
    Qt, Signal, Property, QPropertyAnimation, QEasingCurve, QRectF, QPointF,
)
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QRadialGradient
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from app.modules.lego.theme_manager import ThemeManager

logger = logging.getLogger("AI短剧编辑器.settings_widgets")


def _c(key: str, fallback: str = "#888888") -> QColor:
    """从当前主题取色 → QColor（自绘控件用）"""
    try:
        hexv = ThemeManager.instance().get_colors().get(key, fallback)
        return QColor(hexv)
    except Exception:
        return QColor(fallback)


def _rgb(hexv: str, alpha: int = 255) -> QColor:
    col = QColor(hexv)
    col.setAlpha(alpha)
    return col


# ═══════════════════════════════════════════════════════════════
# iOS 风格开关（直抄 .sidebar-pref-switch / .sidebar-pref-switch span）
# ═══════════════════════════════════════════════════════════════
class ToggleSwitch(QWidget):
    """38×22 圆角开关，旋钮 18×18，开=brand 色，弹簧过渡（对应 --ease-spring）"""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(40, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = bool(checked)
        self._pos = 1.0 if checked else 0.0   # 0=左(关) 1=右(开)

        # parent=self 防 GC（floating_sidebar 教训）
        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)  # 近似 --ease-spring 过冲

    # ── 可动画属性 ──
    def _get_pos(self) -> float:
        return self._pos

    def _set_pos(self, v: float) -> None:
        self._pos = max(0.0, min(1.0, float(v)))
        self.update()

    knobPos = Property(float, _get_pos, _set_pos)

    # ── 状态 ──
    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, animate: bool = True) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        target = 1.0 if checked else 0.0
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._set_pos(target)
        self.toggled.emit(checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            event.accept()
        else:
            super().mousePressEvent(event)

    # ── 绘制 ──
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        radius = h / 2.0

        # 轨道
        if self._checked:
            track = _c("brand", "#6366f1")
        else:
            track = _c("bg_hover", "#252535")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(track))
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        # 旋钮（18×18，左右内边距 3px）
        knob_d = h - 6
        left_x = 3.0
        right_x = w - knob_d - 3.0
        knob_x = left_x + (right_x - left_x) * self._pos
        p.setBrush(QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor(0, 0, 0, 40), 1))
        p.drawEllipse(QRectF(knob_x, 3.0, knob_d, knob_d))
        p.end()

    def set_theme(self, _theme: str) -> None:
        self.update()


# ═══════════════════════════════════════════════════════════════
# 分段控件（节点工具栏「极简图标 / 图标 + 文本」）
# ═══════════════════════════════════════════════════════════════
class SegmentedControl(QFrame):
    """多选一分段控件（对应 AI-Canvas 的 grid grid-cols-N 单选组）"""

    changed = Signal(str)

    def __init__(
        self,
        options: list[tuple[str, str]],   # [(id, label)]
        current: str = "",
        height: int = 38,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("segmentedBar")
        self._options = options
        self._current = current or (options[0][0] if options else "")
        self._buttons: dict[str, QPushButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        for oid, label in options:
            btn = QPushButton(label)
            btn.setObjectName("segmentedBtn")
            btn.setCheckable(True)
            btn.setChecked(oid == self._current)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(height - 10)
            btn.clicked.connect(lambda _c, o=oid: self._select(o))
            self._buttons[oid] = btn
            layout.addWidget(btn, stretch=1)

    def current(self) -> str:
        return self._current

    def set_current(self, oid: str) -> None:
        self._select(oid, emit=False)

    def _select(self, oid: str, emit: bool = True) -> None:
        if oid == self._current:
            # 保持单选态：重新点击当前项时纠正回选中态
            for k, b in self._buttons.items():
                b.setChecked(k == self._current)
            return
        self._current = oid
        for k, b in self._buttons.items():
            b.setChecked(k == oid)
        if emit:
            self.changed.emit(oid)

    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for b in self._buttons.values():
            b.setProperty("theme", theme)


# ═══════════════════════════════════════════════════════════════
# 迷你界面预览（直抄 .sidebar-pref-window，6 种形态）
# ═══════════════════════════════════════════════════════════════
class MiniPreview(QWidget):
    """88×52 迷你界面示意图（自绘，6 种形态对应不同偏好卡）"""

    def __init__(self, kind: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._kind = kind
        self._active = True
        self.setFixedSize(88, 52)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        surface = _c("bg_secondary", "#14141c")
        border = _c("border", "#2a2a3a")
        brand = _c("brand", "#6366f1")
        text_muted = _c("text_muted", "#7d7d91")
        alpha_mul = 1.0 if self._active else 0.35

        # 外框（迷你窗口）
        p.setPen(QPen(border, 1))
        p.setBrush(QBrush(surface))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)

        if self._kind == "note_toolbar":
            # 底部居中的三枚小工具
            cy = h - 12
            shapes = [("rect", brand), ("rect", border), ("circle", border)]
            total_w = 3 * 11 + 2 * 3
            sx = (w - total_w) / 2
            for i, (shape, col) in enumerate(shapes):
                p.setPen(QPen(col, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                col2 = QColor(col)
                col2.setAlpha(int(255 * (0.65 if i == 0 else 0.9) * alpha_mul))
                p.setPen(QPen(col2, 1))
                x = sx + i * 14
                if shape == "rect":
                    p.drawRoundedRect(QRectF(x, cy, 11, 11), 3, 3)
                else:
                    p.drawEllipse(QRectF(x, cy, 11, 11))

        elif self._kind == "auto_ref":
            # "--→ @素材"
            mid_y = h / 2
            p.setPen(QPen(text_muted, 1))
            p.drawLine(QPointF(14, mid_y), QPointF(40, mid_y))
            # 箭头
            p.drawLine(QPointF(36, mid_y - 3), QPointF(40, mid_y))
            p.drawLine(QPointF(36, mid_y + 3), QPointF(40, mid_y))
            # @素材 chip
            chip = QColor(brand)
            chip.setAlpha(int(200 * alpha_mul))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(chip))
            p.drawRoundedRect(QRectF(46, mid_y - 8, 30, 16), 6, 6)
            p.setPen(QPen(QColor("#ffffff")))
            f = QFont()
            f.setPointSize(7)
            p.setFont(f)
            p.drawText(QRectF(46, mid_y - 8, 30, 16), Qt.AlignmentFlag.AlignCenter, "@素材")

        elif self._kind == "node_title":
            # 顶部小标签 + 节点卡片
            nx = w / 2 - 26
            # 标签
            lbl = QColor(brand)
            lbl.setAlpha(int(180 * alpha_mul))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(lbl))
            p.drawRoundedRect(QRectF(nx, 8, 4, 4), 1, 1)
            line = _c("border", "#2a2a3a")
            line.setAlpha(int(255 * alpha_mul))
            p.setBrush(QBrush(line))
            p.drawRoundedRect(QRectF(nx + 6, 9, 40, 2), 1, 1)
            # 节点
            p.setPen(QPen(border, 1))
            p.setBrush(QBrush(surface))
            p.drawRoundedRect(QRectF(nx, 16, 52, 28), 5, 5)

        elif self._kind == "glass_frame":
            # 玻璃外框：内缩 5px 的玻璃带
            inset = 5 if self._active else 0
            p.setPen(QPen(border, 1))
            p.setBrush(QBrush(surface))
            p.drawRoundedRect(QRectF(inset, inset, w - inset * 2, h - inset * 2), 6, 6)
            # 内部左侧色条 + 线
            bar = QColor(brand)
            bar.setAlpha(90)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(bar))
            p.drawRoundedRect(QRectF(inset + 8, h / 2 - 6, 3, 12), 1, 1)
            line = _c("border", "#2a2a3a")
            p.setBrush(QBrush(line))
            p.drawRoundedRect(QRectF(inset + 16, h / 2 - 1, 40, 2), 1, 1)

        elif self._kind == "perf_mode":
            # 空预览（性能模式无图形预览）
            p.setPen(QPen(border, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)

        elif self._kind == "sidebar_floating":
            # 侧边栏竖条 + 内容线
            bar_x = -6 if self._active else 7   # 悬浮时半露出左缘
            grad = QColor(brand)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(bar_x, h / 2 - 16, 9, 32), 5, 5)
            # 内容线（靠右）
            line = _c("text_muted", "#7d7d91")
            line.setAlpha(60)
            p.setBrush(QBrush(line))
            for i, wf in enumerate((1.0, 0.75, 0.55)):
                p.drawRoundedRect(
                    QRectF(24, 11 + i * 10, (w - 34) * wf, 4), 2, 2
                )
        p.end()

    def set_theme(self, _theme: str) -> None:
        self.update()


# ═══════════════════════════════════════════════════════════════
# 外观大预览（节点卡片 + 虚线连接 + 当前主题，对齐截图 1）
# ═══════════════════════════════════════════════════════════════
class AppearancePreview(QFrame):
    """外观页顶部大预览（V4.43.4 复刻开源）

    视觉 1:1 对齐截图：
        ┌─────────────────────────────────────┐
        │ ┌─ 节点预览 ─┐ ┄┄┄┄┄┄┄ ● 当前主题  │
        │ │ 输入提示词  │       深色          │
        │ │ 🖼  IMG/MP4│                     │
        │ └────────────┘                     │
        └─────────────────────────────────────┘
    整个大预览的**背景 = 当前预设的画布渐变**（与画布端 CSS 完全对应）。
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("appearancePreview")
        self.setMinimumHeight(150)
        self._theme_label = "深色"
        self._preset_id = "dark"  # 默认 dark —— 与截图一致

    def set_theme_label(self, label: str) -> None:
        self._theme_label = label
        self.update()

    def set_preset_id(self, preset_id: str) -> None:
        """根据当前预设 id 切换大预览背景"""
        self._preset_id = preset_id
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # ── ① 整块背景：按 preset_id 渲染真实画布渐变 ──
        self._paint_big_bg(p, w, h)

        # 文字色根据当前 preset 深浅自适应
        is_light_bg = self._preset_id in ("light", "frosted-glass")
        text = QColor("#1a1a26") if is_light_bg else QColor("#f0f1f6")
        muted = QColor("#475569" if is_light_bg else "#94a3b8")
        border = QColor(0, 0, 0, 30) if is_light_bg else QColor(255, 255, 255, 30)
        card_bg = QColor(255, 255, 255, 90) if is_light_bg else QColor(20, 20, 28, 90)

        # ── ② 左：节点预览卡 ──
        card_x, card_y = 28, 26
        card_w, card_h = min(190, w * 0.34), 96
        p.setPen(QPen(border, 1))
        p.setBrush(QBrush(card_bg))
        p.drawRoundedRect(QRectF(card_x, card_y, card_w, card_h), 10, 10)

        # 标题行：「节点预览」+ 右侧"● 绿点"（截图里的右上角小绿点）
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(text)
        p.drawText(QRectF(card_x + 12, card_y + 10, card_w - 36, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "节点预览")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#22c55e")))  # 截图小绿点
        p.drawEllipse(QRectF(card_x + card_w - 18, card_y + 14, 8, 8))

        # 输入行
        p.setPen(QPen(border, 1))
        p.setBrush(QBrush(QColor(0, 0, 0, 25) if is_light_bg else QColor(255, 255, 255, 20)))
        p.drawRoundedRect(QRectF(card_x + 12, card_y + 32, card_w - 24, 22), 6, 6)
        p.setPen(muted)
        f.setBold(False)
        f.setPointSize(8)
        p.setFont(f)
        p.drawText(QRectF(card_x + 18, card_y + 32, card_w - 60, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "输入提示词...")
        p.drawText(QRectF(card_x + card_w - 40, card_y + 32, 28, 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "12字")
        # 媒体占位
        p.setPen(QPen(border, 1))
        p.setBrush(QBrush(QColor(0, 0, 0, 25) if is_light_bg else QColor(255, 255, 255, 20)))
        p.drawRoundedRect(QRectF(card_x + 12, card_y + 60, card_w - 24, 26), 6, 6)
        p.setPen(muted)
        p.drawText(QRectF(card_x + 12, card_y + 60, card_w - 24, 26),
                   Qt.AlignmentFlag.AlignCenter, "🖼  IMG / MP4")

        # ── ③ 中：虚线连接 ──
        p.setPen(QPen(muted, 1, Qt.PenStyle.DashLine))
        start_x = card_x + card_w + 18
        end_x = w - 120
        mid_y = card_y + card_h / 2
        if end_x > start_x:
            p.drawLine(int(start_x), int(mid_y), int(end_x), int(mid_y))

        # ── ④ 右：主题圆点 + 文案（截图里是紫光大圆环+中央小白点）──
        dot_x = w - 96
        # 紫色大圆环（accent #a855f7）
        ring_col = QColor("#a855f7")
        p.setPen(QPen(ring_col, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(dot_x - 8, mid_y - 18, 36, 36))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(ring_col))
        p.drawEllipse(QRectF(dot_x, mid_y - 10, 20, 20))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QRectF(dot_x + 7, mid_y - 3, 6, 6))

        p.setPen(muted)
        f.setPointSize(9)
        f.setBold(False)
        p.setFont(f)
        p.drawText(QRectF(dot_x + 28, mid_y - 22, 70, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "当前主题")
        p.setPen(text)
        f.setPointSize(12)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(dot_x + 28, mid_y - 4, 70, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._theme_label)
        p.end()

    def _paint_big_bg(self, p: QPainter, w: float, h: float) -> None:
        """整块背景：与画布端 CSS 真实对应"""
        # 底色 + 渐变（按 preset_id）
        if self._preset_id == "solar-system":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#0a0a12")))
            p.drawRoundedRect(QRectF(0, 0, w, h), 12, 12)
            _stack_radials(p, w, h, [
                (0.78, 0.30, "#f97316", 0.22),
                (0.72, 0.34, "#a855f7", 0.30),
                (0.20, 0.80, "#6366f1", 0.16),
            ])
        elif self._preset_id == "dark":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#0a0e14")))
            p.drawRoundedRect(QRectF(0, 0, w, h), 12, 12)
            # 截图大预览的行星蓝晕（中心靠右）
            _stack_radials(p, w, h, [
                (0.78, 0.50, "#1e3a8a", 0.32),
                (0.82, 0.55, "#3b82f6", 0.22),
            ])
        elif self._preset_id == "frosted-glass":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#EEF1F8")))
            p.drawRoundedRect(QRectF(0, 0, w, h), 12, 12)
            _paint_linear(p, w, h, "#fdfbf7", "#eef1f8", angle_deg=160)
            _paint_dot_grid(p, w, h, color=QColor(0, 0, 0, 14))
        else:  # light / off-white
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#F4F6FB")))
            p.drawRoundedRect(QRectF(0, 0, w, h), 12, 12)
            _paint_dot_grid(p, w, h, color=QColor(0, 0, 0, 22))

    def set_theme(self, _theme: str) -> None:
        self.update()
class PreferenceCard(QFrame):
    """[迷你预览] + [标题/描述] + [开关]

    对应 AI-Canvas .sidebar-pref-card（含 .is-floating 选中态）
    """

    toggled = Signal(str, bool)   # (key, value)
    clicked = Signal(str)         # (key)  —— 仅点卡片主体

    def __init__(
        self,
        setting_key: str,
        title: str,
        description: str,
        preview_kind: str,
        on_desc: str = "",
        off_desc: str = "",
        default_value: bool = True,
        badge: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._key = setting_key
        self._on_desc = on_desc or description
        self._off_desc = off_desc or description
        self.setObjectName("prefCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(10)

        # 迷你预览
        self._preview = MiniPreview(preview_kind)
        layout.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignVCenter)

        # 标题 + 描述
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self._title = QLabel(title)
        self._title.setObjectName("prefTitle")
        title_row.addWidget(self._title)
        if badge:
            self._badge = QLabel(badge)
            self._badge.setObjectName("chipAmber")
            title_row.addWidget(self._badge)
        else:
            self._badge = None
        title_row.addStretch(1)
        text_layout.addLayout(title_row)

        self._desc = QLabel(description)
        self._desc.setObjectName("prefDesc")
        self._desc.setWordWrap(True)
        text_layout.addWidget(self._desc)
        layout.addLayout(text_layout, stretch=1)

        # 开关
        self._switch = ToggleSwitch(checked=default_value)
        self._switch.toggled.connect(self._on_switch)
        layout.addWidget(self._switch, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._apply_state(default_value)

    def _on_switch(self, checked: bool) -> None:
        self._apply_state(checked)
        self.toggled.emit(self._key, checked)

    def _apply_state(self, on: bool) -> None:
        self._preview.set_active(on)
        self._desc.setText(self._on_desc if on else self._off_desc)
        self.setProperty("prefActive", "true" if on else "false")
        # 触发 QSS 重算（[prefActive="true"] 选择器）
        self.style().unpolish(self)
        self.style().polish(self)

    def is_checked(self) -> bool:
        return self._switch.isChecked()

    def set_checked(self, checked: bool, animate: bool = False) -> None:
        self._switch.setChecked(checked, animate=animate)

    def mousePressEvent(self, event):
        # 点非开关区域 → 切换（整卡可点，与 AI-Canvas button 语义一致）
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._switch.geometry().contains(event.position().toPoint()):
                self._switch.setChecked(not self._switch.isChecked())
            event.accept()
        else:
            super().mousePressEvent(event)

    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)
            if hasattr(child, "set_theme") and child is not self:
                try:
                    child.set_theme(theme)
                except Exception as e:
                    logger.debug("子控件主题刷新失败 %s: %s", type(child).__name__, e)


# ═══════════════════════════════════════════════════════════════
# 外观预设卡（借鉴外观页「外观预设」2×2 卡墙）
# ═══════════════════════════════════════════════════════════════
class PresetCard(QFrame):
    """外观预设卡：2×2 大卡（V4.43.4 复刻开源）

    视觉 1:1 对齐截图：
        ┌─ 类型图标 chip ─ 类型名 + #序号 ─┐ ← 顶部
        │                                   │
        │   ┌─── 迷你节点卡 ───┐              │
        │   │ 紫边圆环 + 内容  │              │
        │   └────────────────┘              │
        │                                   │
        ├─ 圆点 + 预设名 + 当前使用 chip ─┤ ← 底部
    """

    activated = Signal(str)

    def __init__(
        self,
        preset_id: str,
        label: str,
        swatch: str,           # 预览底色
        accent: str = "#6366f1",
        node_kind: str = "video",   # audio / video / animation / director
        chip_text: str = "",         # 顶部右上 chip：生成音频/视频/动画/3D 导演台
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._preset_id = preset_id
        self._label = label
        self._swatch = swatch
        self._accent = accent
        self._active = False
        self.setObjectName("presetCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 截图里卡的高度明显更大（约 150×220），拉高
        self.setMinimumHeight(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 自绘预览：背景渐变 + 中央节点卡
        self._preview = _PresetPreview(preset_id, swatch, accent, node_kind, chip_text)
        layout.addWidget(self._preview, stretch=1)

        # 底部名称行：圆点 + 预设名 + 当前使用
        name_row = QHBoxLayout()
        name_row.setSpacing(4)
        dot = QLabel("●")
        dot.setObjectName("presetDot")
        dot.setStyleSheet(f"color: {accent};")
        name_row.addWidget(dot)
        self._name = QLabel(label)
        self._name.setObjectName("presetName")
        name_row.addWidget(self._name)
        name_row.addStretch(1)
        self._badge = QLabel("当前使用")
        self._badge.setObjectName("chipBrand")
        self._badge.setVisible(False)
        name_row.addWidget(self._badge)
        layout.addLayout(name_row)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._badge.setVisible(self._active)
        self.setProperty("presetActive", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self._preview.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._preset_id)
        super().mousePressEvent(event)

    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        self._preview.update()
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)


class _PresetPreview(QWidget):
    """预设卡内部真实背景 + 中央节点卡（V4.43.4 复刻开源截图）

    整体结构：
    ┌──────────────────────────────────┐
    │  ◯ chip_text            #N       │ ← 顶部行：左 icon chip，右 "#序号"
    │                                  │
    │      ┌─── 节点卡 ────┐           │
    │      │ 紫边圆环 + 内容 │           │
    │      └───────────────┘           │
    │                                  │
    │  [节点类型] 右侧连接手柄          │ ← 节点卡周围
    └──────────────────────────────────┘

    节点卡内容按 node_kind 切换：
      - audio      → 紫边圆 + 00:15 时间码 + 波形柱状图
      - video      → 紫边圆 + 输入框 + 「等待生成视频」按钮
      - animation  → 紫边圆 + 输入框 + 文本预览
      - director   → 紫边圆 + 输入框
    """

    def __init__(
        self,
        preset_id: str,
        swatch: str,
        accent: str,
        node_kind: str = "video",
        chip_text: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._preset_id = preset_id
        self._swatch = swatch
        self._accent = accent
        self._node_kind = node_kind
        self._chip_text = chip_text
        self.setMinimumHeight(140)
        # V4.43.7 修复（重要）：本控件是**自绘 QWidget**、覆盖了预设卡绝大部分面积。
        # QWidget 默认会接受 mousePressEvent，于是点击被它吞掉、**不冒泡**到父级
        # PresetCard ⇒ PresetCard.mousePressEvent 收不到 ⇒ activated 信号永不发射
        # ⇒ 用户「点预设卡没反应 / 点深色不切换」。设为鼠标穿透即修好。
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # ① 卡片底色（按 preset 真实背景渐变）
        self._paint_bg(p, w, h)

        # ② 顶部行：左 icon chip + chip_text，右 "#序号"
        self._paint_top_chip(p, w)

        # ③ 中央节点卡（按 node_kind 渲染不同内容）
        if self._node_kind == "audio":
            self._paint_audio_node(p, w, h)
        elif self._node_kind == "animation":
            self._paint_animation_node(p, w, h)
        elif self._node_kind == "director":
            self._paint_director_node(p, w, h)
        else:  # video / fallback
            self._paint_video_node(p, w, h)

        p.end()

    # ─── 背景 ───
    def _paint_bg(self, p: QPainter, w: float, h: float) -> None:
        """按 preset_id 渲染真实画布背景（与画布端 CSS 完全对应）"""
        # ① 底色
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(self._swatch)))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        # ② 渐变叠加（与画布端 backgroundOptions.ts 一一对应）
        if self._preset_id == "solar-system":
            _stack_radials(p, w, h, [
                (0.78, 0.30, "#f97316", 0.22),
                (0.72, 0.34, "#a855f7", 0.30),
                (0.20, 0.80, "#6366f1", 0.16),
            ])
        elif self._preset_id == "dark":
            # 深色 = 默认暗色 + 行星蓝色光晕（截图大预览就是这种）
            _stack_radials(p, w, h, [
                (0.70, 0.28, "#1e3a8a", 0.28),
                (0.78, 0.32, "#3b82f6", 0.18),
            ])
        elif self._preset_id == "light":
            # 浅色 = 米白 + 极小点阵
            _paint_dot_grid(p, w, h, color=QColor(0, 0, 0, 20))
        elif self._preset_id == "frosted-glass":
            # 磨砂曝光 = 160° 渐变 + 极小点阵
            _paint_linear(p, w, h, "#fdfbf7", "#eef1f8", angle_deg=160)
            _paint_dot_grid(p, w, h, color=QColor(0, 0, 0, 12))

    # ─── 顶部 chip ───
    def _paint_top_chip(self, p: QPainter, w: float) -> None:
        """顶部行：左侧 icon + chip_text，右侧 #序号"""
        pad = 10
        chip_h = 20
        icon_size = 18

        # 左：icon + chip 文本（圆角浅底）
        is_light = QColor(self._swatch).lightness() > 128
        chip_bg = QColor(255, 255, 255, 18) if not is_light else QColor(0, 0, 0, 10)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(chip_bg))
        p.drawRoundedRect(QRectF(pad, pad, 6, chip_h), 3, 3)
        # icon（不同节点不同 emoji）
        icons = {"audio": "🔊", "video": "🎬", "animation": "🎞", "director": "📐"}
        f = QFont()
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff") if not is_light else QColor("#1a1a26"), 1))
        p.drawText(QRectF(pad - 4, pad - 1, icon_size + 4, chip_h),
                   Qt.AlignmentFlag.AlignCenter, icons.get(self._node_kind, "🎬"))
        # chip_text
        if self._chip_text:
            f2 = QFont()
            f2.setPointSize(8)
            p.setFont(f2)
            p.setPen(QPen(QColor("#ffffff" if not is_light else "#1a1a26"), 1))
            p.drawText(QRectF(pad + icon_size, pad - 1, 90, chip_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._chip_text)

        # 右：#序号（小数字标签）
        f3 = QFont()
        f3.setPointSize(8)
        p.setFont(f3)
        p.setPen(QPen(QColor(255, 255, 255, 140) if not is_light else QColor(0, 0, 0, 100), 1))
        seed = abs(hash(self._preset_id)) % 100
        p.drawText(QRectF(w - 40, pad - 1, 30, chip_h),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"#{10 + seed % 8}")

    # ─── 节点类型：audio ───
    def _paint_audio_node(self, p: QPainter, w: float, h: float) -> None:
        """音频节点：紫边圆环 + 时间码 00:15 + 波形柱状图 + 连接柄"""
        card_w = w * 0.66
        card_h = h * 0.34
        cx, cy = w / 2, h * 0.60
        card_x, card_y = cx - card_w / 2, cy - card_h / 2

        # 紫边大圆环（截图中央的圆环形状）
        ring_d = min(card_h, card_w) * 0.66
        ring_x = cx - ring_d / 2
        ring_y = cy - ring_d / 2
        # 外圆
        p.setPen(QPen(QColor("#a855f7"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(ring_x, ring_y, ring_d, ring_d))
        # 内圆
        p.setPen(QPen(QColor("#a855f7"), 2))
        p.drawEllipse(QRectF(ring_x + 6, ring_y + 6, ring_d - 12, ring_d - 12))
        # 中心小实心点
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#a855f7")))
        p.drawEllipse(QRectF(cx - 5, cy - 5, 10, 10))

        # 时间码（左下）
        f = QFont()
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(QColor("#a855f7"), 1))
        p.drawText(QRectF(card_x + 4, card_y + card_h - 14, 50, 12),
                   Qt.AlignmentFlag.AlignLeft, "00:15")

        # 波形柱状图（右下）
        bar_x = card_x + card_w - 60
        bar_y = card_y + card_h - 14
        heights = [6, 10, 14, 12, 8, 14, 16, 12, 8, 6]
        p.setBrush(QBrush(QColor("#a855f7")))
        p.setPen(Qt.PenStyle.NoPen)
        for i, hh in enumerate(heights):
            x = bar_x + i * 5
            p.drawRoundedRect(QRectF(x, bar_y + (14 - hh) / 2, 3, hh), 1, 1)

    # ─── 节点类型：video ───
    def _paint_video_node(self, p: QPainter, w: float, h: float) -> None:
        """视频节点：紫边圆环 + 输入框 + 等待生成视频按钮"""
        card_w = w * 0.72
        card_h = h * 0.42
        cx, cy = w / 2, h * 0.58
        card_x, card_y = cx - card_w / 2, cy - card_h / 2

        # 紫边圆环
        ring_d = min(card_h, card_w) * 0.45
        ring_x = cx - ring_d / 2
        ring_y = cy - ring_d / 2
        p.setPen(QPen(QColor("#a855f7"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(ring_x, ring_y, ring_d, ring_d))
        p.setPen(QPen(QColor("#a855f7"), 2))
        p.drawEllipse(QRectF(ring_x + 5, ring_y + 5, ring_d - 10, ring_d - 10))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#a855f7")))
        p.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))

        # 输入框
        in_w = card_w - 16
        in_x = card_x + 8
        in_y = card_y + card_h - 28
        is_light = QColor(self._swatch).lightness() > 128
        bg = QColor(255, 255, 255, 70) if not is_light else QColor(0, 0, 0, 20)
        p.setPen(QPen(QColor("#a855f7"), 1))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(in_x, in_y, in_w, 22), 4, 4)
        # 占位文字
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff" if not is_light else "#1a1a26"), 1))
        p.drawText(QRectF(in_x + 6, in_y, in_w - 40, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "输入视频运镜描述...")
        # 右侧 5s 字样
        f2 = QFont()
        f2.setPointSize(7)
        p.setFont(f2)
        p.setPen(QPen(QColor("#ffffff" if not is_light else "#1a1a26"), 1))
        p.drawText(QRectF(in_x + in_w - 26, in_y, 20, 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "5s")

        # 「等待生成视频」按钮（中央文字）
        btn_y = in_y + 28
        btn_h = 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#a855f7")))
        p.drawRoundedRect(QRectF(in_x, btn_y, in_w, btn_h), 4, 4)
        f3 = QFont()
        f3.setPointSize(7)
        p.setFont(f3)
        p.setPen(QPen(QColor("#ffffff"), 1))
        p.drawText(QRectF(in_x, btn_y, in_w, btn_h),
                   Qt.AlignmentFlag.AlignCenter, "🎬 等待生成视频")

    # ─── 节点类型：animation ───
    def _paint_animation_node(self, p: QPainter, w: float, h: float) -> None:
        """动画节点：紫边圆环 + 输入框 + 文本预览条 + 生成动画 chip"""
        card_w = w * 0.72
        card_h = h * 0.42
        cx, cy = w / 2, h * 0.58
        card_x, card_y = cx - card_w / 2, cy - card_h / 2

        # 紫边圆环
        ring_d = min(card_h, card_w) * 0.45
        ring_x = cx - ring_d / 2
        ring_y = cy - ring_d / 2
        p.setPen(QPen(QColor("#a855f7"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(ring_x, ring_y, ring_d, ring_d))
        p.setPen(QPen(QColor("#a855f7"), 2))
        p.drawEllipse(QRectF(ring_x + 5, ring_y + 5, ring_d - 10, ring_d - 10))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#a855f7")))
        p.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))

        # 输入框（更小）
        in_w = card_w - 16
        in_x = card_x + 8
        in_y = card_y + card_h - 28
        is_light = QColor(self._swatch).lightness() > 128
        bg = QColor(255, 255, 255, 70) if not is_light else QColor(0, 0, 0, 20)
        p.setPen(QPen(QColor("#a855f7"), 1))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(in_x, in_y, in_w, 22), 4, 4)
        f = QFont()
        f.setPointSize(6)
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff" if not is_light else "#1a1a26"), 1))
        p.drawText(QRectF(in_x + 6, in_y, in_w - 30, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "2D俯视危源戏鱼色...")
        # 右侧 Text 字样
        p.drawText(QRectF(in_x + in_w - 22, in_y, 16, 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "Text")

        # 文本预览条（中央偏下，3 行 placeholder）
        prev_y = in_y - 18
        prev_w = in_w
        for i in range(2):
            w_factor = 1.0 if i == 0 else 0.7
            p.setPen(Qt.PenStyle.NoPen)
            # 注意：PySide6 的 QColor 没有 (str, alpha) 重载 —— 必须用 _rgb() 走
            # QColor(name) + setAlpha()。V4.43.4 曾误写成 QColor("#fff", 80)，
            # 真机一渲染 paintEvent 就抛 TypeError（静态门禁查不出来）。
            p.setBrush(QBrush(_rgb("#ffffff" if not is_light else "#1a1a26", 80)))
            p.drawRoundedRect(
                QRectF(in_x + 2, prev_y + i * 6, prev_w * w_factor - 4, 3), 1, 1
            )

    # ─── 节点类型：director ───
    def _paint_director_node(self, p: QPainter, w: float, h: float) -> None:
        """3D 导演台节点：紫边圆环 + 输入框（与 video 类似但中央按钮换成"3D 导演台"）"""
        # 与 video 同结构，但提示文字不同
        card_w = w * 0.72
        card_h = h * 0.42
        cx, cy = w / 2, h * 0.58
        card_x, card_y = cx - card_w / 2, cy - card_h / 2

        ring_d = min(card_h, card_w) * 0.45
        ring_x = cx - ring_d / 2
        ring_y = cy - ring_d / 2
        p.setPen(QPen(QColor("#a855f7"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(ring_x, ring_y, ring_d, ring_d))
        p.setPen(QPen(QColor("#a855f7"), 2))
        p.drawEllipse(QRectF(ring_x + 5, ring_y + 5, ring_d - 10, ring_d - 10))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#a855f7")))
        p.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))

        in_w = card_w - 16
        in_x = card_x + 8
        in_y = card_y + card_h - 28
        is_light = QColor(self._swatch).lightness() > 128
        bg = QColor(255, 255, 255, 70) if not is_light else QColor(0, 0, 0, 20)
        p.setPen(QPen(QColor("#a855f7"), 1))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(in_x, in_y, in_w, 22), 4, 4)
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff" if not is_light else "#1a1a26"), 1))
        p.drawText(QRectF(in_x + 6, in_y, in_w - 36, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "输入文本提示词...")
        p.drawText(QRectF(in_x + in_w - 24, in_y, 18, 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "Text")

        btn_y = in_y + 28
        btn_h = 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#a855f7")))
        p.drawRoundedRect(QRectF(in_x, btn_y, in_w, btn_h), 4, 4)
        f2 = QFont()
        f2.setPointSize(7)
        p.setFont(f2)
        p.setPen(QPen(QColor("#ffffff"), 1))
        p.drawText(QRectF(in_x, btn_y, in_w, btn_h),
                   Qt.AlignmentFlag.AlignCenter, "📐 3D 导演台")

    def set_theme(self, _theme: str) -> None:
        self.update()


def _stack_radials(p: QPainter, w: float, h: float, layers: list[tuple]) -> None:
    """叠加多层 QRadialGradient（模拟 CSS radial-gradient(circle at X% Y%, …)）。

    每层：(cx 比例, cy 比例, hex, alpha 0-1)  透明度按 alpha 衰减到 0 的距离固定半径。
    """
    for cx, cy, hex_color, alpha in layers:
        grad = QRadialGradient(QPointF(w * cx, h * cy), max(w, h) * 0.55)
        col = QColor(hex_color)
        col.setAlpha(int(255 * alpha))
        grad.setColorAt(0.0, col)
        col0 = QColor(col)
        col0.setAlpha(0)
        grad.setColorAt(1.0, col0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(QRectF(0, 0, w, h))


def _paint_dot_grid(p: QPainter, w: float, h: float, color: QColor, step: int = 8, dot_size: int = 1) -> None:
    """极小点阵背景（浅色卡/磨砂曝光卡用，模拟 CSS radial-gradient 风格的纹理）"""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    for y in range(0, int(h), step):
        for x in range(0, int(w), step):
            p.drawEllipse(QRectF(x, y, dot_size, dot_size))


def _paint_linear(p: QPainter, w: float, h: float, c1: str, c2: str, angle_deg: float = 160) -> None:
    """线性渐变（160deg 与画布 frosted-glass 的 linear-gradient(160deg, …) 对齐）"""
    import math
    a = math.radians(angle_deg)
    # 渐变从左上到右下
    x1 = w * 0.5 - math.cos(a) * w * 0.6
    y1 = h * 0.5 - math.sin(a) * h * 0.6
    x2 = w * 0.5 + math.cos(a) * w * 0.6
    y2 = h * 0.5 + math.sin(a) * h * 0.6
    grad = QLinearGradient(QPointF(x1, y1), QPointF(x2, y2))
    grad.setColorAt(0.0, QColor(c1))
    grad.setColorAt(1.0, QColor(c2))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRect(QRectF(0, 0, w, h))
