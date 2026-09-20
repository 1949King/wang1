# -*- coding: utf-8 -*-
"""字幕面板 UI 与操作（从 editor_module 抽出）。

字幕列表、样式、CRUD、AI 生成、去水词。EditorModule 通过薄包装调用。
不改播放/画布/变换 bake 冻结区。
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import tempfile
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFrame,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QFileDialog,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    Qt = None  # type: ignore
    QComboBox = QSpinBox = QDoubleSpinBox = QLineEdit = None  # type: ignore
    QDialog = QDialogButtonBox = None  # type: ignore


class _SubtitlePanelHost(Protocol):
    _clips: list
    _subtitle_manager: Any
    _playhead_position: float
    _project_dirty: bool
    _selected_sub_id: Optional[str]
    _current_clip: Any
    _sub_list: Any
    _sub_edit_panel: Any
    _sub_text_edit: Any
    _sub_start_spin: Any
    _sub_end_spin: Any
    _sub_color_value: str
    _sub_bg_chk: Any
    _sub_font_cmb: Any
    _sub_size_spn: Any
    _sub_outline_cmb: Any
    _sub_outline_w_spn: Any
    _sub_shadow_cmb: Any
    _sub_pos_cmb: Any
    _sub_x_spn: Any
    _sub_y_spn: Any
    _sub_anim_in_cmb: Any
    _sub_anim_out_cmb: Any
    _sub_anim_dur_spn: Any
    _timeline_widget: Any
    _clip_widgets: list
    _clip_id_to_widget: dict

    def _sect(self, title: str) -> Any: ...
    def _cmb(self, n: str, items: list, dv: int = 0) -> Any: ...
    def _spn(self, n: str, mn: int, mx: int, dv: int, suf: str = "") -> Any: ...
    def _is_export_audio_clip(self, c: Any) -> bool: ...
    def _notify_edit(self, msg: str) -> None: ...
    def _record_action(self, action: Any) -> None: ...
    def _sync_kernel_timeline(self) -> None: ...
    def _sync_timeline_widget_state(self) -> None: ...
    def _refresh_preview_to_current_clip(self) -> None: ...
    def _update_undo_redo_state(self) -> None: ...
    def _timeline_remove_clip_widget(self, clip_id: str) -> None: ...
    def _get_ffmpeg(self) -> str: ...
    def _emit_ai_progress(self, value: int, message: str) -> None: ...
    def _emit_ai_fail(self, message: str) -> None: ...
    _subtitle_generated_signal: Any


def sub_btn_style(bg: str) -> str:
    return (
        f"QPushButton{{background:{bg};color:#fff;border:none;border-radius:4px;"
        f"padding:5px 10px;font-size:10px;font-weight:600;}}"
        f"QPushButton:hover{{opacity:0.85;}}"
    )


def sub_input_style() -> str:
    return (
        "QLineEdit,QDoubleSpinBox,QSpinBox{background:#0a0a0a;color:#fff;"
        "border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}"
        "QLineEdit:focus,QDoubleSpinBox:focus,QSpinBox:focus{border:1px solid #1e6bde;}"
    )


def build_subtitle_panel_section(editor: _SubtitlePanelHost, layout: QVBoxLayout) -> None:
    """在「文字」侧栏 layout 中构建字幕列表面板（不含文案推送区）。"""
    list_title = QLabel("📋 字幕列表")
    list_title.setStyleSheet("color:#aaa;font-size:11px;font-weight:bold;")
    layout.addWidget(list_title)

    editor._sub_list = QListWidget()
    editor._sub_list.setMaximumHeight(160)
    editor._sub_list.setStyleSheet("""
        QListWidget{
            background:#0a0a0a;color:#ccc;border:1px solid #222;
            border-radius:4px;font-size:11px;
        }
        QListWidget::item{padding:5px 8px;border-bottom:1px solid #1a1a1a;}
        QListWidget::item:selected{background:#1e6bde;color:#fff;}
        QListWidget::item:hover{background:#1a1a1a;}
    """)
    editor._sub_list.currentItemChanged.connect(
        lambda cur, prev: on_subtitle_selected(editor, cur, prev)
    )
    layout.addWidget(editor._sub_list)

    lt_row = QHBoxLayout()
    lt_row.setSpacing(4)

    addb = QPushButton("➕ 添加")
    addb.setStyleSheet(sub_btn_style("#1e6bde"))
    addb.clicked.connect(lambda: add_subtitle(editor))
    lt_row.addWidget(addb)

    aib = QPushButton("🤖 AI生成")
    aib.setStyleSheet(sub_btn_style("#22c55e"))
    aib.clicked.connect(lambda: generate_ai_subtitles(editor))
    lt_row.addWidget(aib)

    fillerb = QPushButton("✂ 一键去水词")
    fillerb.setToolTip("检测填充词与长静音，波纹删除时间线对应片段（可 Ctrl+Z）")
    fillerb.setStyleSheet(sub_btn_style("#06b6d4"))
    fillerb.clicked.connect(lambda: remove_fillers_and_silence(editor))
    lt_row.addWidget(fillerb)

    impb = QPushButton("📥 导入")
    impb.setStyleSheet(sub_btn_style("#f59e0b"))
    impb.clicked.connect(lambda: import_subtitles(editor))
    lt_row.addWidget(impb)

    expb = QPushButton("📤 导出")
    expb.setStyleSheet(sub_btn_style("#8b5cf6"))
    expb.clicked.connect(lambda: export_subtitles(editor))
    lt_row.addWidget(expb)

    lt_row.addStretch()
    layout.addLayout(lt_row)

    editor._sub_edit_panel = QFrame()
    editor._sub_edit_panel.setStyleSheet(
        "QFrame{background:#121212;border:1px solid #1e1e1e;border-radius:6px;}"
    )
    editor._sub_edit_panel.setVisible(False)
    sub_el = QVBoxLayout(editor._sub_edit_panel)
    sub_el.setContentsMargins(8, 8, 8, 8)
    sub_el.setSpacing(5)

    editor._sub_text_edit = QLineEdit()
    editor._sub_text_edit.setPlaceholderText("字幕文本...")
    editor._sub_text_edit.setStyleSheet(sub_input_style())
    sub_el.addWidget(editor._sub_text_edit)

    time_row = QHBoxLayout()
    time_row.setSpacing(4)
    tl = QLabel("起始")
    tl.setStyleSheet("color:#888;font-size:10px;")
    time_row.addWidget(tl)
    editor._sub_start_spin = QDoubleSpinBox()
    editor._sub_start_spin.setRange(0, 99999)
    editor._sub_start_spin.setDecimals(1)
    editor._sub_start_spin.setSuffix("s")
    editor._sub_start_spin.setStyleSheet(sub_input_style())
    time_row.addWidget(editor._sub_start_spin, 1)
    tl2 = QLabel("结束")
    tl2.setStyleSheet("color:#888;font-size:10px;")
    time_row.addWidget(tl2)
    editor._sub_end_spin = QDoubleSpinBox()
    editor._sub_end_spin.setRange(0, 99999)
    editor._sub_end_spin.setDecimals(1)
    editor._sub_end_spin.setSuffix("s")
    editor._sub_end_spin.setStyleSheet(sub_input_style())
    time_row.addWidget(editor._sub_end_spin, 1)
    sub_el.addLayout(time_row)

    edit_btn_row = QHBoxLayout()
    edit_btn_row.setSpacing(4)
    saveb = QPushButton("✏ 保存编辑")
    saveb.setStyleSheet(sub_btn_style("#1e6bde"))
    saveb.clicked.connect(lambda: save_subtitle_edit(editor))
    edit_btn_row.addWidget(saveb)
    visb = QPushButton("👁 可见")
    visb.setStyleSheet(sub_btn_style("#4caf50"))
    visb.clicked.connect(lambda: toggle_subtitle_visibility(editor))
    edit_btn_row.addWidget(visb)
    delb = QPushButton("🗑 删除")
    delb.setStyleSheet(sub_btn_style("#c62828"))
    delb.clicked.connect(lambda: delete_subtitle(editor))
    edit_btn_row.addWidget(delb)
    edit_btn_row.addStretch()
    sub_el.addLayout(edit_btn_row)

    layout.addWidget(editor._sub_edit_panel)

    sep2 = QLabel()
    sep2.setFixedHeight(1)
    sep2.setStyleSheet("background:#222;")
    layout.addWidget(sep2)

    tx = editor._sect("文本")
    editor._sub_font_cmb = editor._cmb("字体", ["微软雅黑", "宋体", "黑体", "Arial", "楷体", "仿宋", "思源黑体"])
    tx.layout().addWidget(editor._sub_font_cmb)
    editor._sub_size_spn = editor._spn("字号", 8, 200, 36, "pt")
    tx.layout().addWidget(editor._sub_size_spn)
    cr = QWidget()
    cl = QHBoxLayout(cr)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(4)
    lb = QLabel("颜色")
    lb.setStyleSheet("color:#888;font-size:10px;")
    lb.setFixedWidth(36)
    cl.addWidget(lb)
    editor._sub_color_swatches = []
    for hc in ["#fff", "#ff0", "#f44", "#4af", "#4f4", "#f4f", "#f80", "#0ff"]:
        sw = QLabel()
        sw.setFixedSize(16, 16)
        sw.setCursor(Qt.CursorShape.PointingHandCursor)
        sw.setStyleSheet(f"background:{hc};border:1px solid #444;border-radius:2px;")
        sw.mousePressEvent = lambda e, c=hc: on_color_click(editor, c)
        cl.addWidget(sw)
        editor._sub_color_swatches.append((sw, hc))
    editor._sub_color_value = "#fff"
    cl.addStretch()
    tx.layout().addWidget(cr)
    layout.addWidget(tx)

    fp = editor._sect("花字预设")
    editor._sub_preset_cmb = QComboBox()
    editor._sub_preset_cmb.addItems(["无", "综艺黄字黑边", "综艺白字红边", "霓虹粉", "霓虹青", "大字幕", "手写体", "金色质感", "漫画冲击"])
    editor._sub_preset_cmb.setStyleSheet(sub_input_style())
    fp.layout().addWidget(editor._sub_preset_cmb)
    pset_btn = QPushButton("🎨 套用花字")
    pset_btn.setStyleSheet(sub_btn_style("#ec4899"))
    pset_btn.clicked.connect(lambda: apply_preset_style(editor))
    fp.layout().addWidget(pset_btn)
    layout.addWidget(fp)

    st = editor._sect("样式")
    editor._sub_outline_cmb = editor._cmb("描边", ["无", "黑色", "白色", "红色", "蓝色", "黄色"])
    st.layout().addWidget(editor._sub_outline_cmb)
    editor._sub_outline_w_spn = editor._spn("描边宽", 0, 20, 2, "px")
    st.layout().addWidget(editor._sub_outline_w_spn)
    editor._sub_shadow_cmb = editor._cmb("阴影", ["无", "柔和", "硬边", "发光", "投影"])
    st.layout().addWidget(editor._sub_shadow_cmb)
    editor._sub_bg_chk = QCheckBox("背景框")
    editor._sub_bg_chk.setStyleSheet("color:#888;font-size:10px;")
    st.layout().addWidget(editor._sub_bg_chk)
    layout.addWidget(st)

    ps = editor._sect("位置")
    editor._sub_pos_cmb = editor._cmb("预设", ["底部居中", "顶部居中", "居中", "左下", "右下", "自定义"])
    ps.layout().addWidget(editor._sub_pos_cmb)
    editor._sub_x_spn = editor._spn("X偏移", -9999, 9999, 0, "px")
    ps.layout().addWidget(editor._sub_x_spn)
    editor._sub_y_spn = editor._spn("Y偏移", -9999, 9999, 0, "px")
    ps.layout().addWidget(editor._sub_y_spn)
    layout.addWidget(ps)

    an = editor._sect("动画")
    editor._sub_anim_in_cmb = editor._cmb("入场", ["无", "淡入", "滑入上", "滑入下", "滑入左", "滑入右", "缩放进入", "旋转进入"])
    an.layout().addWidget(editor._sub_anim_in_cmb)
    editor._sub_anim_out_cmb = editor._cmb("出场", ["无", "淡出", "滑出上", "滑出下", "滑出左", "滑出右", "缩放退出"])
    an.layout().addWidget(editor._sub_anim_out_cmb)
    editor._sub_anim_dur_spn = editor._spn("时长", 100, 3000, 500, "ms")
    an.layout().addWidget(editor._sub_anim_dur_spn)
    layout.addWidget(an)

    op_row = QHBoxLayout()
    op_row.setSpacing(4)
    styb = QPushButton("🎨 应用样式")
    styb.setStyleSheet(sub_btn_style("#f59e0b"))
    styb.clicked.connect(lambda: apply_subtitle_style(editor))
    op_row.addWidget(styb)
    splitb = QPushButton("✂ 拆分")
    splitb.setStyleSheet(sub_btn_style("#ef4444"))
    splitb.clicked.connect(lambda: split_subtitle(editor))
    op_row.addWidget(splitb)
    mergeb = QPushButton("🔗 合并")
    mergeb.setStyleSheet(sub_btn_style("#06b6d4"))
    mergeb.clicked.connect(lambda: merge_subtitle(editor))
    op_row.addWidget(mergeb)
    op_row.addStretch()
    layout.addLayout(op_row)

    editor._selected_sub_id = None
    refresh_subtitle_list(editor)


def apply_subtitle_style(editor: _SubtitlePanelHost) -> None:
    if not editor._subtitle_manager:
        return
    sid = editor._selected_sub_id
    if not sid:
        QMessageBox.information(editor, "字幕", "请先在列表中选择一条字幕")
        return
    sub = editor._subtitle_manager.get_subtitle(sid)
    if not sub:
        return
    font_w = editor._sub_font_cmb.findChild(QComboBox)
    font = font_w.currentText() if font_w else "微软雅黑"
    size_w = editor._sub_size_spn.findChild(QSpinBox)
    size = size_w.value() if size_w else 36
    outline_w = editor._sub_outline_cmb.findChild(QComboBox)
    outline = outline_w.currentText() if outline_w else "无"
    outline_w2 = editor._sub_outline_w_spn.findChild(QSpinBox)
    outline_w_val = outline_w2.value() if outline_w2 else 2
    pos_w = editor._sub_pos_cmb.findChild(QComboBox)
    pos = pos_w.currentText() if pos_w else "底部居中"
    pos_map = {
        "底部居中": (0.5, 0.85), "顶部居中": (0.5, 0.1), "居中": (0.5, 0.5),
        "左下": (0.1, 0.85), "右下": (0.9, 0.85),
    }
    update_kwargs = {}
    if pos in pos_map:
        px, py = pos_map[pos]
        update_kwargs["position"] = {"x": px, "y": py}
    # "自定义" 不改动位置比例；X/Y 偏移（像素）始终叠加在最终位置上（预览+ASS 导出一致）
    shadow_w = editor._sub_shadow_cmb.findChild(QComboBox)
    shadow = shadow_w.currentText() if shadow_w else "无"
    x_w = editor._sub_x_spn.findChild(QSpinBox)
    y_w = editor._sub_y_spn.findChild(QSpinBox)
    anim_in_w = editor._sub_anim_in_cmb.findChild(QComboBox)
    anim_out_w = editor._sub_anim_out_cmb.findChild(QComboBox)
    anim_dur_w = editor._sub_anim_dur_spn.findChild(QSpinBox)
    update_kwargs["offset_x"] = int(x_w.value()) if x_w else 0
    update_kwargs["offset_y"] = int(y_w.value()) if y_w else 0
    update_kwargs["anim_in"] = anim_in_w.currentText() if anim_in_w else "无"
    update_kwargs["anim_out"] = anim_out_w.currentText() if anim_out_w else "无"
    update_kwargs["anim_duration_ms"] = int(anim_dur_w.value()) if anim_dur_w else 500
    editor._subtitle_manager.update_subtitle(sid, **update_kwargs)
    style_name = f"custom_{sid}"
    editor._subtitle_manager.create_subtitle_style(
        style_name,
        font=font, font_size=size, color=editor._sub_color_value,
        border_color=outline if outline != "无" else "transparent",
        border_width=outline_w_val,
        background="#000000" if editor._sub_bg_chk.isChecked() else "transparent",
        shadow=shadow,
    )
    editor._subtitle_manager.apply_style_to_subtitle(sid, style_name)
    editor._project_dirty = True
    QMessageBox.information(
        editor, "字幕",
        f"样式已应用到选中字幕：{font} {size}pt {editor._sub_color_value}",
    )


def on_color_click(editor: _SubtitlePanelHost, color: str) -> None:
    editor._sub_color_value = color


_PRESET_STYLE_MAP = {
    "综艺黄字黑边": "pop_yellow",
    "综艺白字红边": "pop_white_red",
    "霓虹粉": "neon_pink",
    "霓虹青": "neon_cyan",
    "大字幕": "big_white",
    "手写体": "handwrite",
    "金色质感": "gold",
    "漫画冲击": "comic_impact",
}


def apply_preset_style(editor: _SubtitlePanelHost) -> None:
    """一键套用花字预设（样式定义在 subtitle_manager 内置库）。"""
    if not editor._subtitle_manager:
        return
    sid = editor._selected_sub_id
    if not sid:
        QMessageBox.information(editor, "花字", "请先在列表中选择一条字幕")
        return
    combo = getattr(editor, "_sub_preset_cmb", None)
    name = combo.currentText() if combo else "无"
    if name == "无":
        return
    style_name = _PRESET_STYLE_MAP.get(name)
    if not style_name:
        return
    editor._subtitle_manager.apply_style_to_subtitle(sid, style_name)
    editor._project_dirty = True
    refresh_subtitle_list(editor)
    QMessageBox.information(editor, "花字", f"已套用花字预设：{name}")


def refresh_subtitle_list(editor: _SubtitlePanelHost) -> None:
    if not hasattr(editor, "_sub_list") or not editor._sub_list:
        return
    editor._sub_list.blockSignals(True)
    editor._sub_list.clear()
    if not editor._subtitle_manager:
        editor._sub_list.blockSignals(False)
        return
    for sub in editor._subtitle_manager.list_subtitles():
        t0 = sub.get("start_time", 0)
        text = sub.get("text", "")[:40]
        vis = "👁" if sub.get("visible", True) else "🚫"
        ts = f"{int(t0 // 60):02d}:{int(t0 % 60):02d}"
        item = QListWidgetItem(f"[{ts}] {vis} {text}")
        item.setData(Qt.ItemDataRole.UserRole, sub.get("id"))
        editor._sub_list.addItem(item)
    editor._sub_list.blockSignals(False)
    editor._sub_list.update()


def on_subtitle_selected(editor: _SubtitlePanelHost, current, previous) -> None:
    if not current:
        editor._sub_edit_panel.setVisible(False)
        editor._selected_sub_id = None
        return
    sid = current.data(Qt.ItemDataRole.UserRole)
    if not sid or not editor._subtitle_manager:
        editor._sub_edit_panel.setVisible(False)
        return
    sub = editor._subtitle_manager.get_subtitle(sid)
    if not sub:
        return
    editor._selected_sub_id = sid
    editor._sub_edit_panel.setVisible(True)
    editor._sub_text_edit.setText(sub.get("text", ""))
    editor._sub_start_spin.setValue(sub.get("start_time", 0))
    editor._sub_end_spin.setValue(sub.get("end_time", 0))
    style = editor._subtitle_manager.get_subtitle_style(sub.get("style", "default")) or {}
    shadow_w = editor._sub_shadow_cmb.findChild(QComboBox)
    if shadow_w:
        idx = shadow_w.findText(str(style.get("shadow", "无")))
        shadow_w.setCurrentIndex(idx if idx >= 0 else 0)
    x_w = editor._sub_x_spn.findChild(QSpinBox)
    if x_w:
        x_w.setValue(int(sub.get("offset_x", 0) or 0))
    y_w = editor._sub_y_spn.findChild(QSpinBox)
    if y_w:
        y_w.setValue(int(sub.get("offset_y", 0) or 0))
    anim_in_w = editor._sub_anim_in_cmb.findChild(QComboBox)
    if anim_in_w:
        idx = anim_in_w.findText(str(sub.get("anim_in", "无")))
        anim_in_w.setCurrentIndex(idx if idx >= 0 else 0)
    anim_out_w = editor._sub_anim_out_cmb.findChild(QComboBox)
    if anim_out_w:
        idx = anim_out_w.findText(str(sub.get("anim_out", "无")))
        anim_out_w.setCurrentIndex(idx if idx >= 0 else 0)
    anim_dur_w = editor._sub_anim_dur_spn.findChild(QSpinBox)
    if anim_dur_w:
        anim_dur_w.setValue(int(sub.get("anim_duration_ms", 500) or 500))


def save_subtitle_edit(editor: _SubtitlePanelHost) -> None:
    sid = editor._selected_sub_id
    if not sid or not editor._subtitle_manager:
        return
    text = editor._sub_text_edit.text().strip()
    if not text:
        QMessageBox.warning(editor, "提示", "字幕文本不能为空")
        return
    editor._subtitle_manager.update_subtitle(
        sid,
        text=text,
        start_time=editor._sub_start_spin.value(),
        end_time=editor._sub_end_spin.value(),
    )
    editor._project_dirty = True
    refresh_subtitle_list(editor)
    QMessageBox.information(editor, "字幕", "字幕已保存")


def add_subtitle(editor: _SubtitlePanelHost) -> None:
    if not editor._subtitle_manager:
        return
    text, ok = QInputDialog.getText(editor, "添加字幕", "请输入字幕文本：", text="")
    if not ok or not text.strip():
        return
    editor._subtitle_manager.add_subtitle(
        text=text.strip(),
        start_time=editor._playhead_position,
        end_time=editor._playhead_position + 3.0,
    )
    editor._project_dirty = True
    refresh_subtitle_list(editor)


def delete_subtitle(editor: _SubtitlePanelHost) -> None:
    sid = editor._selected_sub_id
    if not sid or not editor._subtitle_manager:
        return
    sub = editor._subtitle_manager.get_subtitle(sid)
    name = sub.get("text", "该字幕")[:20] if sub else "该字幕"
    r = QMessageBox.question(
        editor,
        "确认删除",
        f"确定删除「{name}」？\n\n将同步从时间线波纹删除对应片段（可 Ctrl+Z 撤销）。",
    )
    if r != QMessageBox.StandardButton.Yes:
        return
    if sub and editor._clips:
        binding = resolve_subtitle_frame_binding(editor, sub)
        if binding is not None:
            t_in = float(binding.timeline_in_sec)
            t_out = float(binding.timeline_out_sec)
        else:
            t_in = float(sub.get("start_time", 0) or 0)
            t_out = float(sub.get("end_time", 0) or 0)
        track = None
        if hasattr(editor, "_timeline_widget") and editor._timeline_widget is not None:
            if hasattr(editor._timeline_widget, "find_track_index_by_type"):
                track = editor._timeline_widget.find_track_index_by_type("video", default=0)
            else:
                track = 0
        if t_out > t_in:
            result = apply_ripple_delete_range(editor, t_in, t_out, track=track)
            if result.ok or result.steps:
                editor._notify_edit(result.message)
    editor._subtitle_manager.delete_subtitle(sid)
    editor._selected_sub_id = None
    editor._sub_edit_panel.setVisible(False)
    editor._project_dirty = True
    refresh_subtitle_list(editor)
    editor._update_undo_redo_state()


def find_clip_for_subtitle_range(editor: _SubtitlePanelHost, t_in: float, t_out: float):
    video_track = 0
    if hasattr(editor, "_timeline_widget") and editor._timeline_widget is not None:
        if hasattr(editor._timeline_widget, "find_track_index_by_type"):
            video_track = editor._timeline_widget.find_track_index_by_type("video", default=0)
    best = None
    best_overlap = 0.0
    for c in editor._clips or []:
        if str(c.get("type", "")).lower() == "audio":
            continue
        if int(c.get("track", 0) or 0) != int(video_track):
            continue
        st = float(c.get("start_time", 0) or 0)
        en = st + float(c.get("duration", 0) or 0)
        overlap = min(en, t_out) - max(st, t_in)
        if overlap > best_overlap:
            best_overlap = overlap
            best = c
    return best


def resolve_subtitle_frame_binding(editor: _SubtitlePanelHost, sub: dict):
    if not sub or not editor._subtitle_manager:
        return None
    t_in = float(sub.get("start_time", 0) or 0)
    t_out = float(sub.get("end_time", 0) or 0)
    clip = find_clip_for_subtitle_range(editor, t_in, t_out)
    if not clip:
        return None
    try:
        bindings = editor._subtitle_manager.compute_frame_bindings(clip, fps=30.0)
    except Exception:
        return None
    sid = str(sub.get("id") or "")
    for b in bindings:
        if b.entry_id and b.entry_id == sid:
            return b
    for b in bindings:
        if abs(float(b.raw_start_sec) - t_in) < 0.05 and abs(float(b.raw_end_sec) - t_out) < 0.05:
            return b
    subs = getattr(editor._subtitle_manager, "subtitles", []) or []
    try:
        idx = next(i for i, s in enumerate(subs) if s.get("id") == sid)
        if 0 <= idx < len(bindings):
            return bindings[idx]
    except StopIteration as e:
        logger.debug("未找到匹配的字幕绑定: %s", e)
    return None


def apply_ripple_delete_range(
    editor: _SubtitlePanelHost,
    t_in: float,
    t_out: float,
    *,
    track=None,
    record: bool = True,
):
    try:
        from app.core.edit_commands import ripple_delete_timeline_range
    except ImportError:
        from core.edit_commands import ripple_delete_timeline_range

    result = ripple_delete_timeline_range(editor._clips, t_in, t_out, track=track)
    if not result.ok and not result.steps:
        return result

    for step in result.steps:
        stype = step.get("type")
        if stype == "split":
            new_clip = step.get("new_clip")
            if new_clip and hasattr(editor, "_timeline_widget") and editor._timeline_widget is not None:
                widget = editor._timeline_widget.add_clip(new_clip, int(new_clip.get("track", 0)))
                if widget is not None:
                    if not hasattr(editor, "_clip_widgets"):
                        editor._clip_widgets = []
                    editor._clip_widgets.append(widget)
                    editor._clip_id_to_widget[new_clip["id"]] = widget
        elif stype == "delete":
            clip_id = (step.get("clip") or {}).get("id")
            if clip_id:
                editor._timeline_remove_clip_widget(clip_id)

    editor._clips = result.clips

    if record and result.steps:
        editor._record_action(result.undo_action)
        editor._project_dirty = True

    editor._sync_kernel_timeline()
    editor._sync_timeline_widget_state()
    editor._refresh_preview_to_current_clip()
    return result


def _format_cleanup_interval_label(iv, index: int) -> str:
    kind_zh = "填充词" if iv.kind == "filler" else "静音"
    text = (iv.text or "").strip()
    text_part = f"「{text}」" if text else ""
    return (
        f"{index}. [{kind_zh}] {iv.timeline_in:.2f}–{iv.timeline_out:.2f}s "
        f"({iv.duration:.2f}s) {text_part}"
    ).rstrip()


class CleanupChecklistDialog(QDialog if QDialog is not None else object):  # type: ignore[misc]
    """M5：去水词/静音建议勾选确认（不默认全删）。"""

    def __init__(self, parent, plan):
        if QDialog is None:
            raise RuntimeError("PyQt6 不可用")
        super().__init__(parent)
        self._plan = plan
        self.setWindowTitle("确认后执行 — 勾选要删除的区间")
        self.setMinimumWidth(480)
        self.setMinimumHeight(360)

        root = QVBoxLayout(self)
        filler_n = sum(1 for i in plan.intervals if i.kind == "filler")
        silence_n = sum(1 for i in plan.intervals if i.kind == "silence")
        head = (
            f"共 {len(plan.intervals)} 段建议，约 {plan.total_duration:.1f}s"
            f"（填充词 {filler_n} / 静音 {silence_n}）。\n"
            "勾选后点「执行选中」才会写回时间线；可 Ctrl+Z 撤销。"
        )
        if plan.is_dense_dialogue:
            head += "\n⚠ 密集对白：默认仅勾选填充词。"
        root.addWidget(QLabel(head))

        self._list = QListWidget()
        for i, iv in enumerate(plan.intervals, 1):
            item = QListWidgetItem(_format_cleanup_interval_label(iv, i))
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            # 密集对白：静音默认不勾；否则全勾
            if plan.is_dense_dialogue and iv.kind == "silence":
                item.setCheckState(Qt.CheckState.Unchecked)
            else:
                item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, iv)
            self._list.addItem(item)
        root.addWidget(self._list)

        tools = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_none = QPushButton("全不选")
        btn_filler = QPushButton("仅填充词")
        btn_all.clicked.connect(lambda: self._set_kind_checks(None, True))
        btn_none.clicked.connect(lambda: self._set_kind_checks(None, False))
        btn_filler.clicked.connect(lambda: self._set_kind_checks("filler", True))
        tools.addWidget(btn_all)
        tools.addWidget(btn_none)
        tools.addWidget(btn_filler)
        tools.addStretch(1)
        root.addLayout(tools)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("执行选中")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _set_kind_checks(self, kind, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self._list.count()):
            item = self._list.item(row)
            iv = item.data(Qt.ItemDataRole.UserRole)
            if kind is None:
                item.setCheckState(state)
            elif kind == "filler":
                item.setCheckState(
                    Qt.CheckState.Checked if iv.kind == "filler" else Qt.CheckState.Unchecked
                )

    def selected_intervals(self):
        out = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                iv = item.data(Qt.ItemDataRole.UserRole)
                if iv is not None:
                    out.append(iv)
        return out


def build_editor_cleanup_plan(editor: _SubtitlePanelHost):
    """
    构建去水词建议计划。

    返回 (plan, error_message)；成功时 error 为空字符串。
    """
    if not editor._clips:
        return None, "请先导入视频"
    if not editor._subtitle_manager:
        return None, (
            "请先使用「🤖 AI生成」识别字幕，或导入带时间轴的字幕文件。\n\n"
            "去水词依赖 ASR/字幕时间戳定位填充词与句间静音。"
        )
    subs = editor._subtitle_manager.list_subtitles()
    if not subs:
        return None, "当前没有字幕条目。请先「🤖 AI生成」或导入字幕后再试。"

    clip = getattr(editor, "_current_clip", None)
    if not clip or editor._is_export_audio_clip(clip):
        video_clips = [
            c for c in editor._clips
            if c.get("path") and not editor._is_export_audio_clip(c)
        ]
        clip = video_clips[0] if video_clips else None
    if not clip:
        return None, "没有可用的视频片段"

    try:
        from app.core.filler_silence_detect import CleanupConfig, build_cleanup_plan_from_subtitles
    except ImportError:
        from core.filler_silence_detect import CleanupConfig, build_cleanup_plan_from_subtitles

    cfg = CleanupConfig(
        silence_min_sec=0.4,
        detect_fillers=True,
        detect_silence=True,
        aggressive_fillers=False,
        skip_inter_segment_silence=False,
    )
    plan = build_cleanup_plan_from_subtitles(subs, clip, cfg)
    if plan.is_dense_dialogue:
        cfg = CleanupConfig(
            silence_min_sec=0.4,
            detect_fillers=True,
            detect_silence=False,
            skip_inter_segment_silence=True,
            aggressive_fillers=False,
        )
        plan = build_cleanup_plan_from_subtitles(subs, clip, cfg)

    if not plan.intervals:
        return None, (
            "未检测到纯填充词条目或（在短剧模式下被跳过的）长静音。\n\n"
            "提示：仅删除整句为「呃/嗯/啊」等的条目；混合句默认保留。"
        )
    return plan, ""


def suggest_cleanup_intervals_payload(plan) -> list:
    """供 Agent / capability 返回的建议列表（不写 _clips）。"""
    rows = []
    for i, iv in enumerate(plan.intervals):
        rows.append({
            "index": i,
            "kind": iv.kind,
            "text": iv.text,
            "t_in": float(iv.timeline_in),
            "t_out": float(iv.timeline_out),
            "duration": float(iv.duration),
        })
    return rows


def execute_cleanup_selection(editor: _SubtitlePanelHost, plan, selected) -> bool:
    """执行勾选子集：写 _clips + 可选字幕重对齐。返回是否执行成功。"""
    if not selected:
        QMessageBox.information(editor, "确认后执行", "未勾选任何区间，未改动时间线。")
        return False

    selected_plan = plan.with_intervals(selected)

    track = 0
    if hasattr(editor, "_timeline_widget") and editor._timeline_widget is not None:
        if hasattr(editor._timeline_widget, "find_track_index_by_type"):
            track = editor._timeline_widget.find_track_index_by_type("video", default=0)

    try:
        from app.core.filler_silence_detect import execute_cleanup_plan
    except ImportError:
        from core.filler_silence_detect import execute_cleanup_plan

    result = execute_cleanup_plan(editor._clips, selected_plan, track=track)
    if not result.ok and not result.steps:
        QMessageBox.warning(editor, "去水词", result.message or "删除失败")
        return False

    for step in result.steps:
        stype = step.get("type")
        if stype == "split":
            new_clip = step.get("new_clip")
            if new_clip and hasattr(editor, "_timeline_widget") and editor._timeline_widget is not None:
                widget = editor._timeline_widget.add_clip(new_clip, int(new_clip.get("track", 0)))
                if widget is not None:
                    if not hasattr(editor, "_clip_widgets"):
                        editor._clip_widgets = []
                    editor._clip_widgets.append(widget)
                    editor._clip_id_to_widget[new_clip["id"]] = widget
        elif stype == "delete":
            clip_id = (step.get("clip") or {}).get("id")
            if clip_id:
                editor._timeline_remove_clip_widget(clip_id)

    editor._clips = result.clips
    if result.steps:
        editor._record_action(result.undo_action)
        editor._project_dirty = True

    editor._sync_kernel_timeline()
    editor._sync_timeline_widget_state()
    editor._refresh_preview_to_current_clip()
    editor._update_undo_redo_state()
    editor._notify_edit(result.message or f"已去水词，删除约 {result.deleted_duration:.1f}s")

    align_msg = (
        f"{result.message or '完成'}\n\n"
        "是否按删除区间重对齐字幕时间轴？\n"
        "（推荐：字幕会与新时间线对齐；选「否」则保留旧时间戳，需自行重跑 AI 字幕。）"
    )
    align = QMessageBox.question(
        editor,
        "去水词完成 — 同步字幕？",
        align_msg,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if align == QMessageBox.StandardButton.Yes:
        try:
            from app.core.filler_silence_detect import (
                realign_subtitles_after_cleanup,
                replace_subtitle_manager_entries,
            )
        except ImportError:
            from core.filler_silence_detect import (
                realign_subtitles_after_cleanup,
                replace_subtitle_manager_entries,
            )
        old_subs = list(editor._subtitle_manager.list_subtitles())
        new_subs = realign_subtitles_after_cleanup(old_subs, selected_plan.intervals)
        n = replace_subtitle_manager_entries(editor._subtitle_manager, new_subs)
        editor._project_dirty = True
        refresh_subtitle_list(editor)
        editor._notify_edit(f"字幕已重对齐，剩余 {n} 条")
        QMessageBox.information(
            editor,
            "字幕已同步",
            f"已按删除区间重对齐字幕：保留 {n} 条（相交切口的条目已移除）。",
        )
    else:
        QMessageBox.information(
            editor,
            "去水词完成",
            f"{result.message or '完成'}\n\n未同步字幕。如需对齐可稍后重跑「AI生成」或再次去水词后选择同步。",
        )
    return True


def run_cleanup_checklist_flow(editor: _SubtitlePanelHost, plan) -> dict:
    """
    M5 竖切：弹出勾选对话框 → 确认后写 _clips。

    返回 {success, cancelled, selected_count, suggested_count, message}。
    """
    dlg = CleanupChecklistDialog(editor, plan)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return {
            "success": False,
            "cancelled": True,
            "selected_count": 0,
            "suggested_count": len(plan.intervals),
            "message": "用户取消，未改动时间线",
        }
    selected = dlg.selected_intervals()
    ok = execute_cleanup_selection(editor, plan, selected)
    return {
        "success": ok,
        "cancelled": False,
        "selected_count": len(selected),
        "suggested_count": len(plan.intervals),
        "message": (
            f"已执行 {len(selected)}/{len(plan.intervals)} 段"
            if ok else "未执行或执行失败"
        ),
        "intervals": suggest_cleanup_intervals_payload(plan.with_intervals(selected)) if ok else [],
    }


def remove_fillers_and_silence(editor: _SubtitlePanelHost) -> None:
    """字幕面板入口：建议列表勾选 → 确认后写 _clips（M5）。"""
    plan, err = build_editor_cleanup_plan(editor)
    if err:
        # 无字幕/无建议用 information；缺素材用 warning
        if "导入视频" in err or "视频片段" in err:
            QMessageBox.warning(editor, "操作提示", err)
        else:
            QMessageBox.information(editor, "一键去水词", err)
        return
    run_cleanup_checklist_flow(editor, plan)


def toggle_subtitle_visibility(editor: _SubtitlePanelHost) -> None:
    sid = editor._selected_sub_id
    if not sid or not editor._subtitle_manager:
        return
    editor._subtitle_manager.toggle_subtitle_visibility(sid)
    editor._project_dirty = True
    refresh_subtitle_list(editor)


def split_subtitle(editor: _SubtitlePanelHost) -> None:
    sid = editor._selected_sub_id
    if not sid or not editor._subtitle_manager:
        QMessageBox.information(editor, "拆分", "请先在列表中选择一条字幕")
        return
    sub = editor._subtitle_manager.get_subtitle(sid)
    if not sub:
        return
    mid = (sub["start_time"] + sub["end_time"]) / 2
    val, ok = QInputDialog.getDouble(
        editor, "拆分字幕",
        f"在哪个时间点拆分？(当前范围 {sub['start_time']:.1f}s - {sub['end_time']:.1f}s)",
        mid, 0, 99999, 1,
    )
    if not ok:
        return
    result = editor._subtitle_manager.split_subtitle(sid, val)
    if result:
        editor._project_dirty = True
        refresh_subtitle_list(editor)
        QMessageBox.information(editor, "拆分", "字幕已拆分为 2 条")


def merge_subtitle(editor: _SubtitlePanelHost) -> None:
    sid1 = editor._selected_sub_id
    if not sid1 or not editor._subtitle_manager:
        QMessageBox.information(editor, "合并", "请先选择第一条字幕，再输入第二条的序号")
        return
    items = []
    for i in range(editor._sub_list.count()):
        items.append(f"{i + 1}) {editor._sub_list.item(i).text()[:30]}")
    if len(items) < 2:
        QMessageBox.information(editor, "合并", "至少需要 2 条字幕才能合并")
        return
    item_str, ok = QInputDialog.getItem(
        editor, "合并字幕", "选择要和当前字幕合并的字幕：", items, 0, False,
    )
    if not ok:
        return
    idx = int(item_str.split(")")[0]) - 1
    sid2 = editor._sub_list.item(idx).data(Qt.ItemDataRole.UserRole)
    if sid1 == sid2:
        return
    result = editor._subtitle_manager.merge_subtitles(sid1, sid2)
    if result:
        editor._project_dirty = True
        refresh_subtitle_list(editor)
        QMessageBox.information(editor, "合并", "字幕已合并")


def import_subtitles(editor: _SubtitlePanelHost) -> None:
    if not editor._subtitle_manager:
        return
    path, _ = QFileDialog.getOpenFileName(editor, "导入字幕", "", "字幕文件 (*.srt *.vtt)")
    if not path:
        return
    fmt = "srt" if path.lower().endswith(".srt") else "vtt"
    imported = editor._subtitle_manager.import_subtitles(path, fmt)
    if imported:
        editor._project_dirty = True
        refresh_subtitle_list(editor)
        QMessageBox.information(editor, "导入", f"成功导入 {len(imported)} 条字幕")
    else:
        QMessageBox.warning(editor, "导入", "未能从文件中识别出字幕数据")


def export_subtitles(editor: _SubtitlePanelHost) -> None:
    if not editor._subtitle_manager:
        return
    if not editor._subtitle_manager.list_subtitles():
        QMessageBox.information(editor, "导出", "当前没有字幕可导出")
        return
    path, _ = QFileDialog.getSaveFileName(editor, "导出字幕", "subtitles.srt", "SRT 字幕 (*.srt)")
    if not path:
        return
    if editor._subtitle_manager.export_subtitles(path, "srt"):
        QMessageBox.information(editor, "导出", f"字幕已导出到:\n{path}")
    else:
        QMessageBox.warning(editor, "导出", "导出失败")


def generate_ai_subtitles(editor: _SubtitlePanelHost) -> None:
    if not editor._clips:
        QMessageBox.warning(editor, "操作提示", "请先导入视频")
        return
    clip = getattr(editor, "_current_clip", None)
    if not clip or editor._is_export_audio_clip(clip):
        video_clips = [
            c for c in editor._clips
            if c.get("path") and os.path.exists(c.get("path"))
            and not editor._is_export_audio_clip(c)
        ]
        if not video_clips:
            QMessageBox.warning(editor, "操作提示", "没有可识别的视频片段")
            return
        clip = video_clips[0]
    video_path = clip.get("path")
    if not video_path or not os.path.exists(video_path):
        QMessageBox.warning(editor, "操作提示", "视频文件不存在")
        return

    try:
        from app.core.ai.whisper_asr import is_available, unavailable_reason
    except Exception:
        try:
            from core.ai.whisper_asr import is_available, unavailable_reason
        except Exception:
            is_available = lambda: False
            unavailable_reason = lambda: (
                "未安装语音识别组件（faster-whisper）。\n\n"
                "请执行：.\\scripts\\setup_deps.ps1\n"
                "或：.\\venv312\\Scripts\\python.exe -m pip install faster-whisper"
            )
    if not is_available():
        QMessageBox.warning(editor, "AI字幕", unavailable_reason())
        return

    if not editor._subtitle_manager:
        try:
            from app.core.subtitle_manager import SubtitleManager
        except ImportError:
            from core.subtitle_manager import SubtitleManager
        editor._subtitle_manager = SubtitleManager()

    if hasattr(editor, "_ai_task_label"):
        editor._ai_task_label.setText("任务: AI字幕生成中...")
        editor._ai_task_label.setStyleSheet("color:#f59e0b;font-size:10px;font-weight:600;")
    if hasattr(editor, "_ai_progress"):
        editor._ai_progress.setValue(0)
        editor._ai_progress.show()

    in_p = float(clip.get("in_point", 0) or 0)
    out_p = float(clip.get("out_point", 0) or 0)
    start_t = float(clip.get("start_time", 0) or 0)
    clip_dur = (out_p - in_p) if out_p > in_p + 0.05 else 0.0

    def do_generate():
        audio_path = None
        try:
            editor._emit_ai_progress(5, "正在提取音频...")
            audio_path = tempfile.mktemp(suffix="_subtitle_audio.wav")
            ffmpeg = editor._get_ffmpeg()
            ffmpeg_cmd = [ffmpeg, "-y"]
            if in_p > 0.01:
                ffmpeg_cmd += ["-ss", f"{in_p:.3f}"]
            ffmpeg_cmd += ["-i", video_path]
            if clip_dur > 0.05:
                ffmpeg_cmd += ["-t", f"{clip_dur:.3f}"]
            ffmpeg_cmd += [
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                audio_path,
            ]
            r = subprocess.run(
                ffmpeg_cmd, capture_output=True, timeout=180,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if r.returncode != 0 or not os.path.exists(audio_path):
                err = (r.stderr or b"").decode("utf-8", "ignore")[-300:]
                editor._emit_ai_fail(f"音频提取失败\n{err}")
                return

            editor._emit_ai_progress(20, "正在语音识别（Whisper）...")
            segments = []
            last_err = ""
            for model_size in ("base", "tiny"):
                try:
                    from app.core.ai.whisper_asr import transcribe, _load_model
                    if _load_model(model_size) is None:
                        last_err = f"模型 {model_size} 加载失败（网络/镜像）"
                        continue
                    raw = transcribe(audio_path, model_size=model_size, language="zh")

                    class _Seg:
                        __slots__ = ("text", "start_time", "end_time")

                        def __init__(self, text, start_time, end_time):
                            self.text = text
                            self.start_time = start_time
                            self.end_time = end_time

                    for seg in raw or []:
                        text = (seg.get("text") or "").strip()
                        if not text:
                            continue
                        segments.append(_Seg(
                            text,
                            float(seg.get("start", 0) or 0),
                            float(seg.get("end", 0) or 0),
                        ))
                    if segments or raw is not None:
                        break
                except Exception as e1:
                    last_err = str(e1)
                    logger.warning("whisper %s 失败: %s", model_size, e1)
                    segments = []

            if not segments and last_err and ("加载" in last_err or "模型" in last_err):
                editor._emit_ai_fail(
                    f"语音模型未就绪：{last_err}\n\n"
                    "可设置环境变量后重试：\n"
                    "  HF_ENDPOINT=https://hf-mirror.com"
                )
                return

            if not segments:
                try:
                    try:
                        from app.core.subtitle_generator import SubtitleGenerator
                    except ImportError:
                        from core.subtitle_generator import SubtitleGenerator
                    gen = SubtitleGenerator(model_size="tiny")
                    segments = gen.generate_subtitles(
                        audio_path,
                        language="zh",
                        correct_typos=False,
                        progress_callback=lambda p, m: editor._emit_ai_progress(
                            20 + int(max(0, min(70, p)) * 0.7), m
                        ),
                    )
                except Exception as e2:
                    last_err = str(e2)

            if not segments:
                detail = f"\n详情: {last_err}" if last_err else ""
                editor._emit_ai_fail(
                    "未识别到语音内容，或识别失败。\n"
                    "请确认：① 视频有对白音轨 ② Whisper 模型已下载 "
                    "③ 网络/镜像可用（HF_ENDPOINT）。"
                    f"{detail}"
                )
                return

            editor._emit_ai_progress(92, "正在写入字幕...")
            if hasattr(editor._subtitle_manager, "subtitles"):
                editor._subtitle_manager.subtitles.clear()

            subtitle_count = 0
            for seg in segments:
                text = getattr(seg, "text", "") if hasattr(seg, "text") else str(seg)
                rel_s = float(getattr(seg, "start_time", 0) or 0)
                rel_e = float(getattr(seg, "end_time", 0) or 0)
                abs_s = start_t + rel_s
                abs_e = start_t + rel_e
                if abs_e <= abs_s:
                    abs_e = abs_s + 0.5
                text = (text or "").strip()
                if text:
                    editor._subtitle_manager.create_subtitle(text, abs_s, abs_e)
                    subtitle_count += 1

            editor._project_dirty = True
            editor._subtitle_generated_signal.emit(subtitle_count)
        except subprocess.TimeoutExpired:
            editor._emit_ai_fail("处理超时，请检查视频文件大小")
        except Exception as e:
            logger.exception("AI字幕生成失败")
            editor._emit_ai_fail(f"字幕生成失败: {e}")
        finally:
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except Exception as e:
                    logger.debug("清理AI字幕临时音频文件失败: %s", e)

    threading.Thread(target=do_generate, daemon=True).start()
