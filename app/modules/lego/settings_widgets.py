"""
设置面板可复用控件 (Settings Widgets)
=====================================

直抄 AI-Canvas-tauri settings.css 的组件视觉:
- ToggleSwitch      = `.sidebar-pref-switch`（iOS 风格 38×22 开关，带弹簧动画）
- SegmentedControl  = 节点工具栏「极简图标 / 图标+文本」分段控件
- MiniPreview       = `.sidebar-pref-window`（88×52 迷你界面预览，6 种形态）
- PreferenceCard    = `.sidebar-pref-card`（预览 + 标题/描述 + 开关）
- PresetCard        = 外观预设卡（迷你节点预览 + 名称 + 当前使用徽标）

设计纪律（见 MEMORY 核心不变量第 8/9 条）:
- 颜色一律走 ThemeManager.get_colors() / theme_tokens，禁止内联 hex
- 自绘控件在 set_theme() 里 update() 重绘，跟随主程序明暗
- 动画用 QPropertyAnimation + parent=self 防 GC（floating_sidebar 同款教训）

V4.43.1 任务 #286
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import (
    Qt, pyqtSignal, pyqtProperty, QPropertyAnimation, QEasingCurve, QRectF, QPointF,
)
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PyQt6.QtWidgets import (
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

    toggled = pyqtSignal(bool)

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

    knobPos = pyqtProperty(float, _get_pos, _set_pos)

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

    changed = pyqtSignal(str)

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
    """外观页顶部大预览（自绘：节点卡 + 虚线 + 主题圆点）"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("appearancePreview")
        self.setMinimumHeight(150)
        self._theme_label = "深色"

    def set_theme_label(self, label: str) -> None:
        self._theme_label = label
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        c = ThemeManager.instance().get_colors()
        brand = QColor(c.get("brand", "#6366f1"))
        text = QColor(c.get("text_primary", "#dddde4"))
        muted = QColor(c.get("text_muted", "#7d7d91"))
        card_bg = QColor(c.get("bg_tertiary", "#1a1a26"))
        border = QColor(c.get("border", "#2a2a3a"))

        # ── 左：节点卡片 ──
        card_x, card_y = 28, 26
        card_w, card_h = min(190, w * 0.34), 96
        p.setPen(QPen(border, 1))
        p.setBrush(QBrush(card_bg))
        p.drawRoundedRect(QRectF(card_x, card_y, card_w, card_h), 10, 10)

        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(text)
        p.drawText(QRectF(card_x + 12, card_y + 10, card_w - 24, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "节点预览")
        # 输入行
        p.setPen(QPen(border, 1))
        p.setBrush(QBrush(QColor(c.get("bg_secondary", "#14141c"))))
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
        p.setBrush(QBrush(QColor(c.get("bg_secondary", "#14141c"))))
        p.drawRoundedRect(QRectF(card_x + 12, card_y + 60, card_w - 24, 26), 6, 6)
        p.setPen(muted)
        p.drawText(QRectF(card_x + 12, card_y + 60, card_w - 24, 26),
                   Qt.AlignmentFlag.AlignCenter, "🖼  IMG / MP4")

        # ── 中：虚线连接 ──
        p.setPen(QPen(muted, 1, Qt.PenStyle.DashLine))
        start_x = card_x + card_w + 18
        end_x = w - 120
        mid_y = card_y + card_h / 2
        if end_x > start_x:
            p.drawLine(int(start_x), int(mid_y), int(end_x), int(mid_y))

        # ── 右：主题圆点 + 文案 ──
        dot_x = w - 96
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(brand))
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

    def set_theme(self, _theme: str) -> None:
        self.update()
class PreferenceCard(QFrame):
    """[迷你预览] + [标题/描述] + [开关]

    对应 AI-Canvas .sidebar-pref-card（含 .is-floating 选中态）
    """

    toggled = pyqtSignal(str, bool)   # (key, value)
    clicked = pyqtSignal(str)         # (key)  —— 仅点卡片主体

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
    """外观预设卡：迷你节点预览 + 名称 + （当前使用时）徽标

    信号:
        activated(str)  — 点击 → 预设 id
    """

    activated = pyqtSignal(str)

    def __init__(
        self,
        preset_id: str,
        label: str,
        swatch: str,           # 预览底色（dark: #0a0a0f / light: #F4F6FB / 等）
        accent: str = "#6366f1",
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
        self.setFixedHeight(150)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 预览（自绘）
        self._preview = _PresetPreview(swatch, accent)
        layout.addWidget(self._preview, stretch=1)

        # 名称行
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
    """预设卡内部迷你节点预览（自绘）"""

    def __init__(self, swatch: str, accent: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._swatch = swatch
        self._accent = accent
        self.setMinimumHeight(84)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # 底色块
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(self._swatch)))
        p.drawRoundedRect(QRectF(0, 0, w, h), 6, 6)

        # 一个迷你节点（顶部标题行 + 内容行）
        card_w = w * 0.72
        card_x = (w - card_w) / 2
        card_y = h * 0.22
        card_h = h * 0.48
        is_light = QColor(self._swatch).lightness() > 128
        card_bg = QColor("#FFFFFF") if is_light else QColor("#1a1a26")
        card_border = QColor(0, 0, 0, 40) if is_light else QColor(255, 255, 255, 40)
        p.setPen(QPen(card_border, 1))
        p.setBrush(QBrush(card_bg))
        p.drawRoundedRect(QRectF(card_x, card_y, card_w, card_h), 5, 5)
        # 标题行（accent 色点 + 灰线）
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(self._accent)))
        p.drawRoundedRect(QRectF(card_x + 6, card_y + 6, 4, 4), 1, 1)
        line_col = QColor(0, 0, 0, 30) if is_light else QColor(255, 255, 255, 40)
        p.setBrush(QBrush(line_col))
        p.drawRoundedRect(QRectF(card_x + 13, card_y + 7, card_w * 0.5, 2.5), 1, 1)
        # 连接手柄（左侧小圆）
        p.setPen(QPen(QColor(self._accent), 1))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QRectF(card_x - 10, card_y + card_h / 2 - 4, 8, 8))
        p.end()

    def set_theme(self, _theme: str) -> None:
        self.update()
