# -*- coding: utf-8 -*-
"""调色面板 UI 与操作（从 editor_module 抽出）。

基础校正 / LUT / HSL；EditorModule 薄包装调用。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QComboBox,
        QFileDialog,
        QHBoxLayout,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSlider,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    Qt = None  # type: ignore


LUT_NAME_MAP = {
    "无": None,
    "电影胶片": "cinema_warm",
    "复古暖调": "vintage",
    "青橙色调": "teal_orange",
    "黑白经典": "bw",
    "日系清新": "jp_fresh",
    "赛博朋克": "cyberpunk",
    "废土风格": "wasteland",
    "糖果色": "candy",
    "暗夜蓝调": "night_blue",
}


class _ColorPanelHost(Protocol):
    _color_sliders: dict
    _lut_combo: Any
    _lut_intensity: Any
    _color_params: dict
    _current_clip: Any
    _user_lut_entries: list
    _project_dirty: bool

    def _sect(self, title: str) -> Any: ...
    def _add_setting_row(self, layout, name, widget, suffix="") -> None: ...
    def _add_cmb_row(self, layout, name, combo) -> None: ...
    def _make_bound_slider(self, mn, mx, dv=0, style_color="#1e6bde") -> Any: ...
    def _property_target_clips(self) -> list: ...
    def _schedule_preview_refresh(self) -> None: ...
    def _refresh_preview_with_effects(self) -> None: ...
    def _record_action(self, action: Any) -> None: ...
    def _notify_edit(self, msg: str) -> None: ...
    def _sync_timeline_widget_state(self) -> None: ...
    def _apply_curves(self) -> None: ...
    def _on_color_slider_live(self, *_args) -> None: ...
    def _import_lut_file(self) -> None: ...
    def _apply_lut_preset(self) -> None: ...
    def _preview_lut_live(self) -> None: ...
    def _reset_color_grading(self) -> None: ...
    def _apply_color_grading(self) -> None: ...


def build_color_panel_tab(editor: _ColorPanelHost) -> Any:
    """构建调色页。"""
    t = QWidget()
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
    c = QWidget()
    l = QVBoxLayout(c)
    l.setContentsMargins(8, 8, 8, 8)
    l.setSpacing(6)

    editor._color_sliders = {}
    slider_ss = "#1e6bde"

    bs = editor._sect("基础校正")
    for key, nm, mn, mx in [
        ("exposure", "曝光", -100, 100),
        ("contrast", "对比度", -100, 100),
        ("highlight", "高光", -100, 100),
        ("shadow", "阴影", -100, 100),
        ("white", "白色", -100, 100),
        ("black", "黑色", -100, 100),
    ]:
        sl = editor._make_bound_slider(mn, mx, 0, slider_ss)
        editor._color_sliders[key] = sl
        sl.valueChanged.connect(editor._on_color_slider_live)
        editor._add_setting_row(bs.layout(), nm, sl, "")
    l.addWidget(bs)

    cs = editor._sect("色彩调整")
    for key, nm, mn, mx in [
        ("saturation", "饱和度", -100, 100),
        ("vibrance", "自然饱和度", -100, 100),
        ("temperature", "色温", -100, 100),
        ("tint", "色调", -100, 100),
        ("sharpen", "锐度", -100, 100),
    ]:
        sl = editor._make_bound_slider(mn, mx, 0, slider_ss)
        editor._color_sliders[key] = sl
        sl.valueChanged.connect(editor._on_color_slider_live)
        editor._add_setting_row(cs.layout(), nm, sl, "")
    l.addWidget(cs)

    lu = editor._sect("预设LUT")
    editor._lut_combo = QComboBox()
    editor._lut_combo.setStyleSheet(
        "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;"
        "border-radius:4px;padding:3px 6px;font-size:10px;}"
    )
    rebuild_lut_combo(editor)
    editor._lut_intensity = QSlider(Qt.Orientation.Horizontal)
    editor._lut_intensity.setRange(0, 100)
    editor._lut_intensity.setValue(70)
    editor._lut_intensity.setStyleSheet(
        "QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}"
        "QSlider::handle:horizontal{background:#1e6bde;width:10px;height:10px;"
        "border-radius:5px;margin:-3px 0;}"
    )
    editor._add_cmb_row(lu.layout(), "LUT", editor._lut_combo)
    editor._add_setting_row(lu.layout(), "强度", editor._lut_intensity, "%")
    lut_row = QHBoxLayout()
    lut_imp = QPushButton("📂 导入.cube")
    lut_imp.setStyleSheet(
        "QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:4px;"
        "padding:5px;font-size:10px;font-weight:600;}"
        "QPushButton:hover{background:#3a3a3a;}"
    )
    lut_imp.clicked.connect(editor._import_lut_file)
    lut_btn = QPushButton("🎨 应用LUT")
    lut_btn.setStyleSheet(
        "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;"
        "padding:5px;font-size:10px;font-weight:600;}"
        "QPushButton:hover{background:#1557b0;}"
    )
    lut_btn.clicked.connect(editor._apply_lut_preset)
    lut_row.addWidget(lut_imp)
    lut_row.addWidget(lut_btn)
    lu.layout().addLayout(lut_row)
    editor._lut_combo.currentIndexChanged.connect(lambda *_: editor._preview_lut_live())
    editor._lut_intensity.valueChanged.connect(lambda *_: editor._preview_lut_live())
    l.addWidget(lu)

    hsl = editor._sect("HSL调整")
    for key, nm, mn, mx, suf in [
        ("hsl_h", "色相", -180, 180, "°"),
        ("hsl_s", "饱和度", -100, 100, "%"),
        ("hsl_l", "明度", -100, 100, "%"),
    ]:
        sl = editor._make_bound_slider(mn, mx, 0, slider_ss)
        editor._color_sliders[key] = sl
        sl.valueChanged.connect(editor._on_color_slider_live)
        editor._add_setting_row(hsl.layout(), nm, sl, suf)
    l.addWidget(hsl)

    cv = editor._sect("曲线调色")
    editor._curve_channel = QComboBox()
    editor._curve_channel.addItems(["RGB", "红色", "绿色", "蓝色"])
    editor._curve_channel.setStyleSheet(
        "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;"
        "border-radius:4px;padding:3px 6px;font-size:10px;}"
    )
    editor._curve_shadows = QSlider(Qt.Orientation.Horizontal)
    editor._curve_shadows.setRange(-100, 100)
    editor._curve_shadows.setValue(0)
    editor._curve_midtones = QSlider(Qt.Orientation.Horizontal)
    editor._curve_midtones.setRange(-100, 100)
    editor._curve_midtones.setValue(0)
    editor._curve_highlights = QSlider(Qt.Orientation.Horizontal)
    editor._curve_highlights.setRange(-100, 100)
    editor._curve_highlights.setValue(0)
    for sl in [editor._curve_shadows, editor._curve_midtones, editor._curve_highlights]:
        sl.setStyleSheet(
            "QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}"
            "QSlider::handle:horizontal{background:#dc2626;width:10px;height:10px;"
            "border-radius:5px;margin:-3px 0;}"
        )
    editor._add_cmb_row(cv.layout(), "通道", editor._curve_channel)
    editor._add_setting_row(cv.layout(), "暗部", editor._curve_shadows, "")
    editor._add_setting_row(cv.layout(), "中间调", editor._curve_midtones, "")
    editor._add_setting_row(cv.layout(), "亮部", editor._curve_highlights, "")
    cvb = QPushButton("📈 应用曲线")
    cvb.setStyleSheet(
        "QPushButton{background:#dc2626;color:#fff;border:none;border-radius:4px;"
        "padding:5px;font-size:10px;font-weight:600;}"
        "QPushButton:hover{background:#b91c1c;}"
    )
    cvb.clicked.connect(editor._apply_curves)
    cv.layout().addWidget(cvb)
    l.addWidget(cv)

    arb = QHBoxLayout()
    rsc = QPushButton("↺ 重置")
    rsc.setStyleSheet(
        "QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:4px;"
        "padding:5px;font-size:10px;font-weight:600;}"
        "QPushButton:hover{background:#3a3a3a;}"
    )
    rsc.clicked.connect(editor._reset_color_grading)
    arb.addWidget(rsc)
    apc = QPushButton("✅ 应用调色")
    apc.setStyleSheet(
        "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;"
        "padding:5px;font-size:10px;font-weight:600;}"
        "QPushButton:hover{background:#1557b0;}"
    )
    apc.clicked.connect(editor._apply_color_grading)
    arb.addWidget(apc)
    l.addLayout(arb)

    l.addStretch()
    s.setWidget(c)
    o = QVBoxLayout(t)
    o.setContentsMargins(0, 0, 0, 0)
    o.addWidget(s)
    return t


def rebuild_lut_combo(editor: _ColorPanelHost) -> None:
    combo = getattr(editor, "_lut_combo", None)
    if combo is None:
        return
    prev = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("无", None)
    for label, key in (
        ("电影胶片", "cinema_warm"),
        ("复古暖调", "vintage"),
        ("青橙色调", "teal_orange"),
        ("黑白经典", "bw"),
        ("日系清新", "jp_fresh"),
        ("赛博朋克", "cyberpunk"),
        ("废土风格", "wasteland"),
        ("糖果色", "candy"),
        ("暗夜蓝调", "night_blue"),
    ):
        combo.addItem(label, key)
    for path, label in getattr(editor, "_user_lut_entries", None) or []:
        combo.addItem(label, path)
    if prev is not None:
        idx = combo.findData(prev)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    combo.blockSignals(False)


def resolve_lut_key_from_ui(editor: _ColorPanelHost):
    combo = getattr(editor, "_lut_combo", None)
    if combo is None:
        return None
    data = combo.currentData()
    if data is not None and data != "":
        return str(data)
    name = combo.currentText()
    if name.startswith("📁 "):
        for path, label in getattr(editor, "_user_lut_entries", None) or []:
            if label == name:
                return path
    return LUT_NAME_MAP.get(name)


def import_lut_file(editor: _ColorPanelHost) -> None:
    path, _ = QFileDialog.getOpenFileName(
        editor,
        "导入 LUT",
        "",
        "LUT 文件 (*.cube *.3dl);;Adobe CUBE (*.cube);;3DL (*.3dl);;所有文件 (*.*)",
    )
    if not path:
        return
    try:
        from app.core.lut_loader import lut_loader
    except Exception:
        from core.lut_loader import lut_loader
    lut = lut_loader.register_file(path)
    if lut is None or getattr(lut, "data", None) is None:
        QMessageBox.warning(editor, "LUT", "无法解析该 LUT 文件（需有效 .cube / .3dl）")
        return
    abspath = os.path.normpath(os.path.abspath(path))
    title = (
        getattr(lut, "title", None)
        or getattr(lut, "name", None)
        or os.path.basename(abspath)
    )
    label = f"📁 {title}"
    entries = list(getattr(editor, "_user_lut_entries", None) or [])
    entries = [(p, lb) for p, lb in entries if p != abspath]
    entries.append((abspath, label))
    editor._user_lut_entries = entries
    rebuild_lut_combo(editor)
    idx = editor._lut_combo.findData(abspath)
    if idx >= 0:
        editor._lut_combo.setCurrentIndex(idx)
    preview_lut_live(editor)
    editor._notify_edit(f"已导入 LUT：{title}")


def preview_lut_live(editor: _ColorPanelHost) -> None:
    targets = editor._property_target_clips()
    if not targets and not editor._current_clip:
        return
    intens = (
        editor._lut_intensity.value() if hasattr(editor, "_lut_intensity") else 70
    ) / 100.0
    key = resolve_lut_key_from_ui(editor)
    editor._color_params = dict(getattr(editor, "_color_params", None) or {})
    if key:
        editor._color_params["lut"] = key
        editor._color_params["lut_intensity"] = intens
        editor._color_params["lut_fast"] = True
    else:
        editor._color_params.pop("lut", None)
        editor._color_params.pop("lut_intensity", None)
        editor._color_params.pop("lut_fast", None)
    editor._schedule_preview_refresh()


def apply_lut_preset(editor: _ColorPanelHost) -> None:
    targets = editor._property_target_clips()
    if not targets:
        QMessageBox.warning(editor, "LUT", "请先选择一个片段")
        return
    name = editor._lut_combo.currentText() if hasattr(editor, "_lut_combo") else "无"
    intens = (
        editor._lut_intensity.value() if hasattr(editor, "_lut_intensity") else 70
    ) / 100.0
    key = resolve_lut_key_from_ui(editor)
    steps = []
    for clip in targets:
        effects = clip.get("effects") or {}
        if not isinstance(effects, dict):
            effects = {}
        effects = dict(effects)
        cp = dict(effects.get("color_params") or {})
        if key:
            cp["lut"] = key
            cp["lut_intensity"] = intens
            cp.pop("lut_fast", None)
        else:
            cp.pop("lut", None)
            cp.pop("lut_intensity", None)
            cp.pop("lut_fast", None)
        effects["color_params"] = cp
        before = {"effects": dict(clip.get("effects") or {})}
        clip["effects"] = effects
        steps.append({
            "type": "edit_clip",
            "clip_id": clip.get("id"),
            "before": before,
            "after": {"effects": effects},
        })
    editor._color_params = dict(getattr(editor, "_color_params", None) or {})
    if key:
        editor._color_params["lut"] = key
        editor._color_params["lut_intensity"] = intens
        editor._color_params.pop("lut_fast", None)
    else:
        editor._color_params.pop("lut", None)
        editor._color_params.pop("lut_intensity", None)
        editor._color_params.pop("lut_fast", None)
    if len(steps) == 1:
        editor._record_action(steps[0])
    elif steps:
        editor._record_action({"type": "compound", "steps": steps, "label": "batch_lut"})
    editor._project_dirty = True
    editor._sync_timeline_widget_state()
    editor._refresh_preview_with_effects()
    n = len(steps)
    msg = f"已应用 LUT：{name}" if key else "已清除 LUT"
    if n > 1:
        msg = f"{msg}（{n} 个片段）"
    editor._notify_edit(msg)


def sv(editor: _ColorPanelHost, key: str, default: int = 0) -> int:
    sl = (getattr(editor, "_color_sliders", None) or {}).get(key)
    try:
        return int(sl.value()) if sl is not None else default
    except Exception:
        return default


def gather_color_params_from_ui(editor: _ColorPanelHost) -> dict:
    exp = sv(editor, "exposure")
    contrast = sv(editor, "contrast")
    sat = sv(editor, "saturation")
    hsl_s = sv(editor, "hsl_s")
    if hsl_s != 0:
        sat = hsl_s
    vibrance = sv(editor, "vibrance")
    if vibrance != 0 and sat == 0:
        sat = int(vibrance * 0.7)
    hue = sv(editor, "hsl_h")
    tint = sv(editor, "tint")
    if tint != 0 and hue == 0:
        hue = int(tint * 0.5)
    light = sv(editor, "hsl_l")
    highlight = sv(editor, "highlight")
    shadow = sv(editor, "shadow")
    white = sv(editor, "white")
    black = sv(editor, "black")
    sharpen = sv(editor, "sharpen")
    temp = sv(editor, "temperature")

    brightness = exp / 100.0 * 0.3 + light / 100.0 * 0.2
    brightness += highlight / 100.0 * 0.08 + white / 100.0 * 0.05
    brightness += shadow / 100.0 * 0.06 + black / 100.0 * 0.04

    cp = {
        "brightness": round(brightness, 3),
        "contrast": round(1.0 + contrast / 100.0 * 0.5, 3),
        "saturation": round(1.0 + sat / 100.0 * 0.5, 3),
        "hue": float(hue),
        "exposure": round(exp / 100.0, 3),
    }
    if sharpen != 0:
        cp["sharpen"] = round(sharpen / 100.0 * 2.0, 3)
    if temp != 0:
        cp["temperature"] = float(temp)
    old = dict(getattr(editor, "_color_params", None) or {})
    for k in ("lut", "lut_intensity", "lut_fast"):
        if k in old:
            cp[k] = old[k]
    return cp


def on_color_slider_live(editor: _ColorPanelHost, *_args) -> None:
    editor._color_params = gather_color_params_from_ui(editor)
    if editor._color_params.get("lut"):
        editor._color_params["lut_fast"] = True
    editor._schedule_preview_refresh()


def apply_color_grading(editor: _ColorPanelHost) -> None:
    targets = editor._property_target_clips()
    if not targets:
        QMessageBox.warning(editor, "调色", "请先选择一个片段")
        return
    cp = gather_color_params_from_ui(editor)
    cp.pop("lut_fast", None)
    steps = []
    for clip in targets:
        effects = clip.get("effects") or {}
        if not isinstance(effects, dict):
            effects = {}
        effects = dict(effects)
        merged = dict(effects.get("color_params") or {})
        lut = merged.get("lut")
        lut_i = merged.get("lut_intensity")
        merged.update(cp)
        if lut and "lut" not in cp:
            merged["lut"] = lut
            if lut_i is not None:
                merged["lut_intensity"] = lut_i
        effects["color_params"] = merged
        for k in ("brightness", "contrast", "saturation", "hue", "exposure", "sharpen"):
            if k in merged:
                effects[k] = merged[k]
        before = {"effects": dict(clip.get("effects") or {})}
        clip["effects"] = effects
        steps.append({
            "type": "edit_clip",
            "clip_id": clip.get("id"),
            "before": before,
            "after": {"effects": effects},
        })
    editor._color_params = cp
    if len(steps) == 1:
        editor._record_action(steps[0])
    elif steps:
        editor._record_action({"type": "compound", "steps": steps, "label": "batch_color"})
    editor._project_dirty = True
    editor._sync_timeline_widget_state()
    editor._refresh_preview_with_effects()
    n = len(steps)
    editor._notify_edit(
        "已应用调色到当前片段" if n <= 1 else f"已应用调色到 {n} 个片段"
    )


def reset_color_grading(editor: _ColorPanelHost) -> None:
    for sl in (getattr(editor, "_color_sliders", None) or {}).values():
        try:
            sl.blockSignals(True)
            sl.setValue(0)
            sl.blockSignals(False)
        except Exception as e:
            logger.debug("重置色彩滑块失败: %s", e)
    keep_lut = {}
    old = dict(getattr(editor, "_color_params", None) or {})
    for k in ("lut", "lut_intensity"):
        if k in old:
            keep_lut[k] = old[k]
    editor._color_params = dict(keep_lut)
    if editor._current_clip:
        effects = editor._current_clip.get("effects") or {}
        if isinstance(effects, dict):
            cp = dict(effects.get("color_params") or {})
            for k in list(cp.keys()):
                if k not in ("lut", "lut_intensity"):
                    cp.pop(k, None)
            if keep_lut:
                cp.update(keep_lut)
            effects["color_params"] = cp
            for k in ("brightness", "contrast", "saturation", "hue", "exposure", "sharpen"):
                effects.pop(k, None)
            editor._current_clip["effects"] = effects
            editor._project_dirty = True
    editor._refresh_preview_with_effects()
    editor._notify_edit("已重置调色")
