# -*- coding: utf-8 -*-
"""音频面板 UI（从 editor_module 抽出）。

音量 / 淡入淡出 / 均衡器 / 效果 / 踩点；逻辑仍在 EditorModule。
不改 playback-av 冻结区。
"""
from __future__ import annotations

from typing import Any, Protocol

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QCheckBox,
        QHBoxLayout,
        QListWidget,
        QPushButton,
        QScrollArea,
        QSlider,
        QSpinBox,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    Qt = None  # type: ignore


class _AudioPanelHost(Protocol):
    _clip_volume_slider: Any
    _master_volume_slider: Any
    _beat_sensitivity: Any
    _beat_list: Any

    def _sect(self, title: str) -> Any: ...
    def _add_setting_row(self, layout, name, widget, suffix="") -> None: ...
    def _spn(self, n: str, mn: int, mx: int, dv: int, suf: str = "") -> Any: ...
    def _slr(self, n: str, mn: int, mx: int, dv: int, suf: str = "") -> Any: ...
    def _cmb(self, n: str, items: list, dv: int = 0) -> Any: ...
    def _enhance_audio(self) -> None: ...
    def _denoise_audio(self) -> None: ...
    def _crop_audio(self) -> None: ...
    def _add_bgm(self) -> None: ...
    def _extract_vocal(self) -> None: ...
    def _on_clip_volume_live(self, value: int) -> None: ...
    def _on_clip_volume_pressed(self) -> None: ...
    def _on_clip_volume_committed(self) -> None: ...
    def _adjust_volume(self, *_a) -> None: ...
    def _apply_fade_effects(self) -> None: ...
    def _detect_beats(self) -> None: ...
    def _split_on_beats(self, every_n: int = 4) -> None: ...


def build_audio_panel_tab(editor: _AudioPanelHost) -> Any:
    """构建音频页（逻辑仍在 EditorModule）。"""
    self = editor
    t = QWidget()
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
    c = QWidget()
    l = QVBoxLayout(c)
    l.setContentsMargins(8, 8, 8, 8)
    l.setSpacing(6)

    btns = QHBoxLayout()
    enh = QPushButton("🔊 增强")
    enh.setStyleSheet(
        "QPushButton{background:#22c55e;color:#fff;border:none;border-radius:4px;"
        "padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#16a34a;}"
    )
    enh.clicked.connect(self._enhance_audio)
    btns.addWidget(enh)
    dnz = QPushButton("🎤 降噪")
    dnz.setStyleSheet(
        "QPushButton{background:#f59e0b;color:#fff;border:none;border-radius:4px;"
        "padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#d97706;}"
    )
    dnz.clicked.connect(self._denoise_audio)
    btns.addWidget(dnz)
    crp = QPushButton("✂ 截取")
    crp.setStyleSheet(
        "QPushButton{background:#ef4444;color:#fff;border:none;border-radius:4px;"
        "padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#dc2626;}"
    )
    crp.clicked.connect(self._crop_audio)
    btns.addWidget(crp)
    l.addLayout(btns)

    btns2 = QHBoxLayout()
    bgm = QPushButton("🎵 添加BGM")
    bgm.setStyleSheet(
        "QPushButton{background:#6366f1;color:#fff;border:none;border-radius:4px;"
        "padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#4f46e5;}"
    )
    bgm.clicked.connect(self._add_bgm)
    btns2.addWidget(bgm)
    ext = QPushButton("🔊 提取人声")
    ext.setStyleSheet(
        "QPushButton{background:#8b5cf6;color:#fff;border:none;border-radius:4px;"
        "padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#7c3aed;}"
    )
    ext.clicked.connect(self._extract_vocal)
    btns2.addWidget(ext)
    l.addLayout(btns2)

    vl = self._sect("音量")
    self._clip_volume_slider = QSlider(Qt.Orientation.Horizontal)
    self._clip_volume_slider.setRange(0, 200)
    self._clip_volume_slider.setValue(100)
    self._clip_volume_slider.setStyleSheet(
        "QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}"
        "QSlider::handle:horizontal{background:#1e6bde;width:10px;height:10px;"
        "border-radius:5px;margin:-3px 0;}"
    )
    self._clip_volume_slider.valueChanged.connect(self._on_clip_volume_live)
    self._clip_volume_slider.sliderPressed.connect(self._on_clip_volume_pressed)
    self._clip_volume_slider.sliderReleased.connect(self._on_clip_volume_committed)
    self._add_setting_row(vl.layout(), "片段", self._clip_volume_slider, "%")
    self._master_volume_slider = QSlider(Qt.Orientation.Horizontal)
    self._master_volume_slider.setRange(0, 200)
    self._master_volume_slider.setValue(100)
    self._master_volume_slider.setStyleSheet(
        "QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}"
        "QSlider::handle:horizontal{background:#22c55e;width:10px;height:10px;"
        "border-radius:5px;margin:-3px 0;}"
    )
    self._master_volume_slider.valueChanged.connect(self._adjust_volume)
    self._add_setting_row(vl.layout(), "总控", self._master_volume_slider, "%")
    l.addWidget(vl)

    fd = self._sect("淡入淡出")
    self._fade_in_row = self._spn("淡入", 0, 10000, 500, "ms")
    fd.layout().addWidget(self._fade_in_row)
    self._fade_out_row = self._spn("淡出", 0, 10000, 500, "ms")
    fd.layout().addWidget(self._fade_out_row)
    fadeb = QPushButton("🎵 应用音频效果")
    fadeb.setToolTip("按当前面板的淡入淡出/均衡器/降噪/压缩器/混响一次性处理并加入时间线")
    fadeb.setStyleSheet(
        "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;"
        "padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}"
    )
    fadeb.clicked.connect(self._apply_fade_effects)
    fd.layout().addWidget(fadeb)
    l.addWidget(fd)

    eq = self._sect("均衡器")
    self._eq_low_row = self._slr("低频", -12, 12, 0, "dB")
    eq.layout().addWidget(self._eq_low_row)
    self._eq_mid_row = self._slr("中频", -12, 12, 0, "dB")
    eq.layout().addWidget(self._eq_mid_row)
    self._eq_high_row = self._slr("高频", -12, 12, 0, "dB")
    eq.layout().addWidget(self._eq_high_row)
    l.addWidget(eq)

    fx = self._sect("效果")
    self._denoise_chk = QCheckBox("降噪")
    self._denoise_chk.setStyleSheet("color:#888;font-size:10px;")
    fx.layout().addWidget(self._denoise_chk)
    self._denoise_strength_row = self._slr("降噪强度", 0, 100, 50, "%")
    fx.layout().addWidget(self._denoise_strength_row)
    self._compressor_chk = QCheckBox("压缩器")
    self._compressor_chk.setStyleSheet("color:#888;font-size:10px;")
    fx.layout().addWidget(self._compressor_chk)
    self._compressor_ratio_row = self._slr("压缩比", 0, 100, 50, "%")
    fx.layout().addWidget(self._compressor_ratio_row)
    self._reverb_row = self._cmb("混响", ["无", "小房间", "中厅", "大教堂", "板式", "弹簧"])
    fx.layout().addWidget(self._reverb_row)
    l.addWidget(fx)

    bt = self._sect("音乐踩点")
    self._beat_sensitivity = QSpinBox()
    self._beat_sensitivity.setRange(1, 10)
    self._beat_sensitivity.setValue(5)
    self._beat_sensitivity.setStyleSheet(
        "QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;"
        "border-radius:4px;padding:3px 5px;font-size:10px;}"
    )
    self._add_setting_row(bt.layout(), "灵敏度", self._beat_sensitivity, "")
    btn_detect = QPushButton("🥁 自动检测节拍")
    btn_detect.setStyleSheet(
        "QPushButton{background:#a855f7;color:#fff;border:none;border-radius:4px;"
        "padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#9333ea;}"
    )
    btn_detect.clicked.connect(self._detect_beats)
    bt.layout().addWidget(btn_detect)
    beat_cut_row = QHBoxLayout()
    b4 = QPushButton("每 4 拍切开")
    b4.setToolTip("先检测节拍，再勾选切点；不自动加转场")
    b4.clicked.connect(lambda: self._split_on_beats(4))
    b8 = QPushButton("每 8 拍切开")
    b8.clicked.connect(lambda: self._split_on_beats(8))
    beat_cut_row.addWidget(b4)
    beat_cut_row.addWidget(b8)
    bt.layout().addLayout(beat_cut_row)
    self._beat_list = QListWidget()
    self._beat_list.setMaximumHeight(120)
    self._beat_list.setStyleSheet(
        "QListWidget{background:#0a0a0a;color:#ccc;border:1px solid #222;"
        "border-radius:4px;font-size:10px;}"
    )
    bt.layout().addWidget(self._beat_list)
    l.addWidget(bt)

    l.addStretch()
    s.setWidget(c)
    o = QVBoxLayout(t)
    o.setContentsMargins(0, 0, 0, 0)
    o.addWidget(s)
    return t
