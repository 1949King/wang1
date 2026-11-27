# -*- coding: utf-8 -*-
"""属性面板 UI（从 editor_module 抽出）。变换 / 合成 / PiP / 速度等。"""
from __future__ import annotations

from typing import Any, Protocol

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QComboBox,
        QHBoxLayout,
        QPushButton,
        QScrollArea,
        QSlider,
        QSpinBox,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    Qt = None  # type: ignore


class _PropsPanelHost(Protocol):
    def _sect(self, title: str) -> Any: ...
    def _add_setting_row(self, layout, name, widget, suffix="") -> None: ...
    def _add_cmb_row(self, layout, name, combo) -> None: ...
    def _make_bound_slider(self, mn, mx, dv=0, style_color="#1e6bde") -> Any: ...
    def _spn(self, n: str, mn: int, mx: int, dv: int, suf: str = "") -> Any: ...
    def _on_clip_transform_live(self, *_a) -> None: ...
    def _on_clip_opacity_live(self, *_a) -> None: ...
    def _on_clip_blend_mode_changed(self, *_a) -> None: ...
    def _on_clip_crop_live(self, *_a) -> None: ...
    def _on_pip_transform_live(self, *_a) -> None: ...
    def _apply_pip(self) -> None: ...
    def _apply_chroma_key(self) -> None: ...
    def _apply_clip_speed_from_ui(self) -> None: ...
    def _apply_speed_ramp(self) -> None: ...
    def _apply_motion_track(self) -> None: ...
    def _reverse_video(self) -> None: ...
    def _mirror_h(self) -> None: ...
    def _mirror_v(self) -> None: ...


def build_props_panel_tab(editor: _PropsPanelHost) -> Any:
    """构建属性页（逻辑仍在 EditorModule）。"""
    self = editor
    t = QWidget()
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
    c = QWidget()
    l = QVBoxLayout(c)
    l.setContentsMargins(8,8,8,8)
    l.setSpacing(6)

    tf = self._sect("变换")
    self._clip_pos_x = QSpinBox(); self._clip_pos_x.setRange(-9999, 9999); self._clip_pos_x.setValue(0)
    self._clip_pos_y = QSpinBox(); self._clip_pos_y.setRange(-9999, 9999); self._clip_pos_y.setValue(0)
    self._clip_scale_slider = self._make_bound_slider(10, 400, 100)
    self._clip_rot_slider = self._make_bound_slider(-360, 360, 0)
    for sp in (self._clip_pos_x, self._clip_pos_y):
        sp.setStyleSheet("QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}")
    self._add_setting_row(tf.layout(), "X", self._clip_pos_x, "px")
    self._add_setting_row(tf.layout(), "Y", self._clip_pos_y, "px")
    self._add_setting_row(tf.layout(), "缩放", self._clip_scale_slider, "%")
    self._add_setting_row(tf.layout(), "旋转", self._clip_rot_slider, "°")
    self._clip_scale_slider.valueChanged.connect(self._on_clip_transform_live)
    self._clip_pos_x.valueChanged.connect(self._on_clip_transform_live)
    self._clip_pos_y.valueChanged.connect(self._on_clip_transform_live)
    self._clip_rot_slider.valueChanged.connect(self._on_clip_transform_live)
    self._clip_anchor = QComboBox()
    self._clip_anchor.addItems(["中心", "左上", "右上", "左下", "右下"])
    self._clip_anchor.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
    self._add_cmb_row(tf.layout(), "锚点", self._clip_anchor)
    self._clip_anchor.currentIndexChanged.connect(self._on_clip_transform_live)
    l.addWidget(tf)

    cp = self._sect("合成")
    self._clip_opacity_slider = self._make_bound_slider(0, 100, 100)
    self._clip_opacity_slider.valueChanged.connect(self._on_clip_opacity_live)
    self._add_setting_row(cp.layout(), "不透明度", self._clip_opacity_slider, "%")
    self._blend_mode = QComboBox()
    self._blend_mode.addItems(["正常","变暗","正片叠底","颜色加深","变亮","滤色","叠加","柔光","强光","差值","排除","色相","饱和度","颜色","明度"])
    self._blend_mode.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
    self._blend_mode.setToolTip("色相/饱和度/颜色/明度仅预览生效，导出会退回“正常”叠加（FFmpeg 不支持这 4 种）")
    self._add_cmb_row(cp.layout(), "混合", self._blend_mode)
    self._blend_mode.currentTextChanged.connect(self._on_clip_blend_mode_changed)
    l.addWidget(cp)

    pip = self._sect("画中画")
    self._pip_x = QSlider(Qt.Orientation.Horizontal); self._pip_x.setRange(0,100); self._pip_x.setValue(75)
    self._pip_y = QSlider(Qt.Orientation.Horizontal); self._pip_y.setRange(0,100); self._pip_y.setValue(80)
    self._pip_size = QSlider(Qt.Orientation.Horizontal); self._pip_size.setRange(5,200); self._pip_size.setValue(35)
    self._pip_border = QSpinBox(); self._pip_border.setRange(0,20); self._pip_border.setValue(2)
    for sl in [self._pip_x, self._pip_y, self._pip_size]:
        sl.setStyleSheet("QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}QSlider::handle:horizontal{background:#1e6bde;width:10px;height:10px;border-radius:5px;margin:-3px 0;}")
    self._pip_border.setStyleSheet("QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}")
    self._add_setting_row(pip.layout(), "X位置", self._pip_x, "%")
    self._add_setting_row(pip.layout(), "Y位置", self._pip_y, "%")
    self._add_setting_row(pip.layout(), "大小", self._pip_size, "%")
    self._add_setting_row(pip.layout(), "边框", self._pip_border, "px")
    self._pip_x.valueChanged.connect(self._on_pip_transform_live)
    self._pip_y.valueChanged.connect(self._on_pip_transform_live)
    self._pip_size.valueChanged.connect(self._on_pip_transform_live)
    pipb = QPushButton("📺 应用画中画")
    pipb.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
    pipb.clicked.connect(self._apply_pip)
    pip.layout().addWidget(pipb)
    l.addWidget(pip)

    ck = self._sect("智能抠像")
    self._chroma_color = QComboBox(); self._chroma_color.addItems(["绿色","蓝色","自定义"])
    self._chroma_color.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
    self._chroma_tol = QSlider(Qt.Orientation.Horizontal); self._chroma_tol.setRange(5,70); self._chroma_tol.setValue(30)
    self._chroma_soft = QSlider(Qt.Orientation.Horizontal); self._chroma_soft.setRange(0,30); self._chroma_soft.setValue(5)
    for sl in [self._chroma_tol, self._chroma_soft]:
        sl.setStyleSheet("QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}QSlider::handle:horizontal{background:#8b5cf6;width:10px;height:10px;border-radius:5px;margin:-3px 0;}")
    self._add_cmb_row(ck.layout(), "背景色", self._chroma_color)
    self._add_setting_row(ck.layout(), "容差", self._chroma_tol, "%")
    self._add_setting_row(ck.layout(), "柔化", self._chroma_soft, "%")
    ckb = QPushButton("🎨 应用抠像")
    ckb.setStyleSheet("QPushButton{background:#8b5cf6;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#7c3aed;}")
    ckb.clicked.connect(self._apply_chroma_key)
    ck.layout().addWidget(ckb)
    l.addWidget(ck)

    sp = self._sect("速度/裁剪")
    self._speed_preset = QComboBox(); self._speed_preset.addItems(["无","0.25x慢放","0.5x慢放","2x快放","4x快放","缓入","缓出","缓入缓出","卡点变速","倒放"])
    self._speed_preset.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
    self._speed_factor = QSlider(Qt.Orientation.Horizontal); self._speed_factor.setRange(25,400); self._speed_factor.setValue(100)
    self._speed_factor.setStyleSheet("QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}QSlider::handle:horizontal{background:#f59e0b;width:10px;height:10px;border-radius:5px;margin:-3px 0;}")
    self._speed_easing = QComboBox(); self._speed_easing.addItems(["线性","缓入","缓出","缓入缓出","阶梯"])
    self._speed_easing.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
    self._add_cmb_row(sp.layout(), "变速预设", self._speed_preset)
    self._add_setting_row(sp.layout(), "速度因子", self._speed_factor, "%")
    self._add_cmb_row(sp.layout(), "缓动", self._speed_easing)
    spb = QPushButton("⚡ 应用变速")
    spb.setStyleSheet("QPushButton{background:#f59e0b;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#d97706;}")
    spb.clicked.connect(self._apply_clip_speed_from_ui)
    sp.layout().addWidget(spb)
    spb_export = QPushButton("💾 导出变速成片")
    spb_export.setStyleSheet("QPushButton{background:#2a2a2a;color:#ddd;border:1px solid #333;border-radius:4px;padding:5px;font-size:10px;}QPushButton:hover{background:#3a3a3a;}")
    spb_export.setToolTip("用 FFmpeg 渲染新文件（缓入/倒放等复杂预设）")
    spb_export.clicked.connect(self._apply_speed_ramp)
    sp.layout().addWidget(spb_export)
    self._crop_top = QSpinBox(); self._crop_top.setRange(0, 9999)
    self._crop_bottom = QSpinBox(); self._crop_bottom.setRange(0, 9999)
    self._crop_left = QSpinBox(); self._crop_left.setRange(0, 9999)
    self._crop_right = QSpinBox(); self._crop_right.setRange(0, 9999)
    for spn in (self._crop_top, self._crop_bottom, self._crop_left, self._crop_right):
        spn.setStyleSheet("QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}")
    self._add_setting_row(sp.layout(), "裁剪上", self._crop_top, "px")
    self._add_setting_row(sp.layout(), "裁剪下", self._crop_bottom, "px")
    self._add_setting_row(sp.layout(), "裁剪左", self._crop_left, "px")
    self._add_setting_row(sp.layout(), "裁剪右", self._crop_right, "px")
    for spn in (self._crop_top, self._crop_bottom, self._crop_left, self._crop_right):
        spn.valueChanged.connect(self._on_clip_crop_live)
    l.addWidget(sp)

    mt = self._sect("运动跟踪")
    self._track_type = QComboBox(); self._track_type.addItems(["平移跟踪","缩放跟踪","旋转跟踪","透视跟踪"])
    self._track_type.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
    self._add_cmb_row(mt.layout(), "跟踪类型", self._track_type)
    mtb = QPushButton("🎯 开始跟踪")
    mtb.setStyleSheet("QPushButton{background:#0891b2;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#0e7490;}")
    mtb.clicked.connect(self._apply_motion_track)
    mt.layout().addWidget(mtb)
    l.addWidget(mt)

    flip = self._sect("翻转/倒放")
    flip_row = QHBoxLayout()
    flip_row.setSpacing(4)
    rev_btn = QPushButton("🔄 倒放")
    rev_btn.setStyleSheet("QPushButton{background:#ef4444;color:#fff;border:none;border-radius:4px;padding:5px 10px;font-size:10px;font-weight:600;}QPushButton:hover{background:#dc2626;}")
    rev_btn.clicked.connect(self._reverse_video)
    flip_row.addWidget(rev_btn)
    mir_btn = QPushButton("↔ 水平镜像")
    mir_btn.setStyleSheet("QPushButton{background:#6366f1;color:#fff;border:none;border-radius:4px;padding:5px 10px;font-size:10px;font-weight:600;}QPushButton:hover{background:#4f46e5;}")
    mir_btn.clicked.connect(self._mirror_h)
    flip_row.addWidget(mir_btn)
    flv_btn = QPushButton("↕ 垂直翻转")
    flv_btn.setStyleSheet("QPushButton{background:#8b5cf6;color:#fff;border:none;border-radius:4px;padding:5px 10px;font-size:10px;font-weight:600;}QPushButton:hover{background:#7c3aed;}")
    flv_btn.clicked.connect(self._mirror_v)
    flip_row.addWidget(flv_btn)
    flip.layout().addLayout(flip_row)
    l.addWidget(flip)

    l.addStretch()
    s.setWidget(c)
    o = QVBoxLayout(t)
    o.setContentsMargins(0,0,0,0)
    o.addWidget(s)
    return t

