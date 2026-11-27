"""时间线控件模块
================
时间线主控件（子控件/基础设施抽到 timeline_subwidgets.py，片段控件抽到 clip_widget.py）。
- TimelineWidget: 时间线主控件
- ClipWidget: 片段控件（抽到 clip_widget.py，此处 re-export）
"""
import os
import json
import logging
import threading
import time
import urllib.request
import weakref

from PySide6.QtCore import Qt, Signal, QTimer, QSize, QUrl, QPoint, QRect, QMimeData
from PySide6.QtGui import (
    QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics,
    QPolygon, QShortcut, QKeySequence, QDrag, QPixmap, QImage,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QSlider, QMenu, QToolTip
)

from .editor_timeline_tools import (
    SnapGuideController,
    RazorGuideController,
    DropTrackFeedbackController,
    TimelineSelectionMixin,
    apply_batch_start_delta,
    clip_compatible_with_track,
    compute_load_spans,
    ids_intersecting_viewport_rect,
    is_ctrl,
    is_shift,
    pick_snap as _pick_snap,
    rect_from_points,
    snap_edge_candidates as _snap_edge_candidates,
    CLIP_DRAG_THRESHOLD_PX,
    MARQUEE_DRAG_THRESHOLD_PX,
)

logger = logging.getLogger("AI短剧编辑器.timeline_widget")
# 子控件与基础设施已抽到 timeline_subwidgets.py，此处 re-export 保持外部 import 兼容
from .timeline_subwidgets import (
    AUDIO_EXTS,
    _MediaWorkerGate,
    _media_worker_gate,
    _TIMELINE_ZOOM_MIN,
    _TIMELINE_ZOOM_MAX,
    _TIMELINE_BASE_PPS,
    _TIMELINE_SNAP_PX,
    _TIMELINE_MIN_CLIP_PX,
    _DEFAULT_FPS,
    _clamp_timeline_zoom,
    _timeline_pps,
    _quantize_time,
    _ndarray_bgr_to_pixmap,
    _extract_filmstrip_frames,
    TimeRuler,
    TimelineMarkerLayer,
    TrackControlPanel,
    TrackViewport,
)
# ClipWidget 已抽到 clip_widget.py，此处 re-export 保持外部 import 兼容
from .clip_widget import ClipWidget


class TimelineWidget(TimelineSelectionMixin, QWidget):
    """时间线主控件：轨道 / 片段 / 吸附 / 多选。"""

    clip_selected = Signal(object)
    playhead_moved = Signal(float)
    # 补短 P1#8：转发 ClipWidget 的关键帧点击，方便 EditorModule 直接监听
    clip_keyframe_clicked = Signal(object, dict)
    files_dropped = Signal(list)
    clip_context_action = Signal(str, object)  # action, clip_data
    clip_trim_committed = Signal(object)  # 松手后规范化的 clip_data
    razor_cut_at = Signal(float)  # 刀片工具：在时间线绝对时间切开
    razor_mode_changed = Signal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks = []
        self._clips = []
        self._timeline_store = None  # 刀8 形态A：set_store 注入的真相源；缺省 None 直写 fallback（测试替身兼容）
        self._current_clip = None
        self._zoom = 100
        self._playhead_pos = 0
        self._total_duration = 600
        self._is_playing = False
        self._timer = None
        self._selected_track = None
        # Track drag reorder state
        self._drag_track = None
        self._drag_orig_index = -1
        self._drag_start_y = 0
        self._drag_active = False
        self._drag_indicator = None
        self._drag_press_global_y = None
        self._snap_enabled = True
        self._snap_threshold_px = _TIMELINE_SNAP_PX
        self._edit_fps = _DEFAULT_FPS
        self._snap_guide_time = None
        self._clip_interaction_active = False  # 拖片/trim 中降低后台负载
        self._active_drag_clip = None
        self._snap_guide = SnapGuideController(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._drop_feedback = DropTrackFeedbackController(self)
        self._razor_mode = False
        self._razor_hover_t = None
        self._razor_guide = RazorGuideController(self)
        self._init_selection_state()
        # 框选
        self._marquee_origin = None  # QPoint in viewport
        self._marquee_rect = None
        self._marquee_active = False
        self._marquee_additive = False
        self.setAcceptDrops(True)
        self._setup_ui()
        try:
            self._track_viewport.setMouseTracking(True)
        except Exception:
            pass

    def px_per_sec(self) -> float:
        return _timeline_pps(self._zoom)

    def frame_duration(self) -> float:
        fps = float(getattr(self, "_edit_fps", _DEFAULT_FPS) or _DEFAULT_FPS)
        return 1.0 / max(1.0, fps)

    def snap_threshold_sec(self) -> float:
        """吸附阈值：按像素换算，放大后更精细；Alt 按下时关闭吸附。"""
        from PySide6.QtWidgets import QApplication
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.AltModifier:
            return 0.0
        pps = max(1e-6, self.px_per_sec())
        px = float(getattr(self, "_snap_threshold_px", _TIMELINE_SNAP_PX) or _TIMELINE_SNAP_PX)
        # 上限 0.25s 避免缩小时吸附过松；下限约半帧
        return max(self.frame_duration() * 0.5, min(0.25, px / pps))

    def iter_track_clip_widgets(self, track):
        container = track.get("clip_container") if isinstance(track, dict) else None
        if container is None:
            return
        for child in container.children():
            if isinstance(child, ClipWidget):
                yield child

    def all_clip_widgets(self):
        for track in self._tracks:
            yield from self.iter_track_clip_widgets(track)

    def position_clip_widget(self, clip_widget):
        """按 start_time 绝对定位片段（弱化 HBox 管位置）。"""
        if clip_widget is None:
            return
        px = self.px_per_sec()
        st = float(clip_widget.clip_data.get("start_time", 0) or 0)
        dur = max(0.05, float(clip_widget.clip_data.get("duration", 10) or 10))
        x = max(0, int(st * px))
        w = max(_TIMELINE_MIN_CLIP_PX, int(dur * px))
        # 片段高度 = 轨道行高度，y=0，彻底去掉轨内上下黑边
        track_h = 48
        parent = clip_widget.parent()
        if parent is not None and parent.height() > 0:
            track_h = int(parent.height())
        clip_h = max(6, track_h)
        clip_widget.setFixedWidth(w)
        clip_widget.setFixedHeight(clip_h)
        clip_widget.move(x, 0)
        clip_widget.show()
        clip_widget.raise_()
        # 缩放/布局后宽度变化 → 胶片条按需重采
        try:
            if hasattr(clip_widget, "_request_thumbnail_refresh"):
                clip_widget._request_thumbnail_refresh()
        except Exception as e:
            logger.debug("position 后缩略图刷新跳过: %s", e)

    def relayout_clips(self):
        for track in self._tracks:
            for w in self.iter_track_clip_widgets(track):
                self.position_clip_widget(w)
        self._update_track_min_width()

    def track_index_at_global_y(self, global_y: int) -> int:
        """根据全局 Y 命中轨道索引。"""
        for i, track in enumerate(self._tracks):
            w = track.get("widget")
            if w is None:
                continue
            top = w.mapToGlobal(w.rect().topLeft()).y()
            bottom = top + w.height()
            if top <= global_y <= bottom:
                return i
        return 0

    def set_snap_guide(self, t):
        """拖拽/trim 吸附命中时显示竖直指示线；t=None 立即清除。"""
        self._snap_guide_time = None if t is None else float(t)
        guide = getattr(self, "_snap_guide", None)
        if guide is not None:
            guide.set_guide(self._snap_guide_time)

    def clear_snap_guide(self, fade: bool = True):
        guide = getattr(self, "_snap_guide", None)
        if guide is not None:
            guide.clear_guide(fade=fade)
        if not fade:
            self._snap_guide_time = None
        elif getattr(self, "_snap_guide_time", None) is not None:
            # 淡出结束后 controller 会清；此处同步属性
            pass

    def snap_start_time(
        self, clip_data, proposed_start: float, exclude_id=None, track_i=None
    ) -> float:
        """吸附到播放头与同轨其它片缘；红线画在实际对齐边。"""
        if not getattr(self, "_snap_enabled", False):
            self.set_snap_guide(None)
            return max(0.0, proposed_start)
        thr = self.snap_threshold_sec()
        if thr <= 0:
            self.set_snap_guide(None)
            return max(0.0, proposed_start)
        ti = int(track_i) if track_i is not None else int(clip_data.get("track", 0) or 0)
        dur = float(clip_data.get("duration", 0) or 0)
        exclude = {exclude_id} if exclude_id is not None else set()
        cands = _snap_edge_candidates(self, proposed_start, dur, ti, exclude)
        best, guide = _pick_snap(proposed_start, cands, thr)
        self.set_snap_guide(guide)
        return max(0.0, best)

    def snap_time(self, proposed: float, exclude_id=None, track_i=None) -> float:
        """吸附任意时间点（片头/片尾/播放头），用于 trim 边缘；命中时更新吸附红线。"""
        if not getattr(self, "_snap_enabled", False):
            self.set_snap_guide(None)
            return max(0.0, proposed)
        thr = self.snap_threshold_sec()
        if thr <= 0:
            self.set_snap_guide(None)
            return max(0.0, proposed)
        # trim：对齐点即红线位置
        cands = [(0.0, 0.0), (float(getattr(self, "_playhead_pos", 0) or 0),
                              float(getattr(self, "_playhead_pos", 0) or 0))]
        for c in self._clips:
            if exclude_id and c.get("id") == exclude_id:
                continue
            if track_i is not None and int(c.get("track", 0) or 0) != int(track_i):
                continue
            st = float(c.get("start_time", 0) or 0)
            cd = float(c.get("duration", 0) or 0)
            cands.append((st, st))
            cands.append((st + cd, st + cd))
        best, guide = _pick_snap(proposed, cands, thr)
        self.set_snap_guide(guide)
        return max(0.0, best)

    def set_drop_track_feedback(self, track_index, compatible: bool = True):
        fb = getattr(self, "_drop_feedback", None)
        if fb is not None:
            fb.set_feedback(track_index, compatible)

    def clear_drop_track_feedback(self):
        fb = getattr(self, "_drop_feedback", None)
        if fb is not None:
            fb.clear()

    def resolve_drop_track(self, global_y: int, clip_data) -> tuple:
        """
        指针下轨道落点：返回 (track_index|None, compatible)。
        同类型才可落；不兼容仍返回索引供红色反馈。
        """
        ti = self.track_index_at_global_y(global_y)
        if ti < 0 or ti >= len(self._tracks):
            return None, False
        ok = clip_compatible_with_track(clip_data, self._tracks[ti])
        return ti, ok
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # === 顶部：时间标尺 ===
        self._time_ruler = TimeRuler(self)
        self._time_ruler.clicked.connect(self.set_playhead_position)
        layout.addWidget(self._time_ruler)

        # === 标记层（高光区域 + 线性补帧节点） ===
        self._marker_layer = TimelineMarkerLayer(self)
        self._marker_layer.setFixedHeight(16)
        self._marker_layer.setStyleSheet("background-color: transparent;")
        layout.addWidget(self._marker_layer)

        # === 轨道区 ===
        # 浮动控制栏 — 绝对定位，跟随选中轨道
        self._track_ctrl_panel = TrackControlPanel(self)
        self._track_ctrl_panel.mute_toggled.connect(self._on_track_mute)
        self._track_ctrl_panel.solo_toggled.connect(self._on_track_solo)
        self._track_ctrl_panel.lock_toggled.connect(self._on_track_lock)
        self._track_ctrl_panel.volume_changed.connect(self._on_track_volume)
        self._track_ctrl_panel.collapse_toggled.connect(self._on_track_collapse)
        self._track_ctrl_panel.hide()

        # === 轨道滚动区（左侧留100px给控制栏） ===
        self._track_scroll = QScrollArea()
        self._track_scroll.setWidgetResizable(False)
        self._track_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._track_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._track_scroll.setStyleSheet("""
            QScrollArea { background-color: #0d0d0d; border: none; }
            QScrollBar:vertical { background-color: #151515; width: 8px; margin: 0; }
            QScrollBar::handle:vertical { background-color: #3a3a3a; border-radius: 4px; min-height: 30px; }
            QScrollBar::handle:vertical:hover { background-color: #555; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { background-color: #151515; height: 8px; margin: 0; }
            QScrollBar::handle:horizontal { background-color: #3a3a3a; border-radius: 4px; min-width: 30px; }
            QScrollBar::handle:horizontal:hover { background-color: #555; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            QScrollBar::corner { background-color: #151515; }
        """)
        self._track_scroll.setViewportMargins(100, 0, 0, 0)

        self._track_viewport = TrackViewport(self)
        self._track_viewport.setStyleSheet("background-color: #0d0d0d;")
        self._track_viewport.playhead_dragged.connect(self.set_playhead_position)
        self._track_layout = QVBoxLayout(self._track_viewport)
        self._track_layout.setContentsMargins(0, 0, 0, 0)
        self._track_layout.setSpacing(0)
        self._track_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 播放头
        self._track_playhead = QFrame(self._track_viewport)
        self._track_playhead.setStyleSheet("background-color: #ff4757; width: 2px;")
        self._track_playhead.setFixedWidth(2)
        self._track_playhead.move(0, 0)

        self._track_scroll.setWidget(self._track_viewport)
        self._track_scroll.horizontalScrollBar().valueChanged.connect(
            self._on_timeline_scroll_changed
        )
        # 垂直滚动时更新控制栏位置 + 视口懒加载
        self._track_scroll.verticalScrollBar().valueChanged.connect(
            self._on_timeline_scroll_changed
        )

        layout.addWidget(self._track_scroll, 1)
        
        self._add_track("视频轨", "video")
        self._add_track("音频轨", "audio")
        self._add_track("字幕轨", "subtitle")
        self._update_track_min_width()
    
    def _update_time_ruler(self):
        """ """
        self._time_ruler.set_zoom(self._zoom)

    def _on_timeline_scroll_changed(self, *_args):
        """滚动：重绘标尺 + 刷新控制栏 + 唤醒视口内缩略图/波形。"""
        try:
            self._time_ruler.update()
        except Exception:
            pass
        try:
            self._update_ctrl_panel_position()
        except Exception:
            pass
        # 合并唤醒，避免滚动刷屏
        t = getattr(self, "_viewport_wake_timer", None)
        if t is None:
            self._viewport_wake_timer = QTimer(self)
            self._viewport_wake_timer.setSingleShot(True)
            self._viewport_wake_timer.setInterval(120)
            self._viewport_wake_timer.timeout.connect(self._wake_visible_clip_media)
            t = self._viewport_wake_timer
        t.start()

    def _wake_visible_clip_media(self):
        for w in self.all_clip_widgets():
            try:
                if self.is_clip_widget_visible(w) and hasattr(w, "wake_media_workers"):
                    # 仅在尚未有缓存时唤醒，避免重复解码
                    need_thumb = (
                        not w._is_audio_clip()
                        and not getattr(w, "_thumbnail_cache", None)
                    )
                    need_wave = (
                        w._is_audio_clip()
                        and getattr(w, "_waveform_peaks", None) is None
                        and not getattr(w, "_waveform_failed", False)
                    )
                    if need_thumb or need_wave:
                        w.wake_media_workers()
            except Exception:
                continue

    def is_clip_widget_visible(self, clip_widget, margin_px: int = 120) -> bool:
        """片段是否与滚动视口相交（含预取边距）。"""
        scroll = getattr(self, "_track_scroll", None)
        if scroll is None or clip_widget is None:
            return True
        try:
            vp = scroll.viewport()
            top_left = clip_widget.mapTo(vp, QPoint(0, 0))
            rect = QRect(top_left, clip_widget.size()).adjusted(
                -margin_px, -margin_px, margin_px, margin_px
            )
            return rect.intersects(vp.rect())
        except Exception:
            return True

    def update_in_out_markers(self, in_point, out_point):
        """序列级 I/O 标记画到标尺。"""
        try:
            self._time_ruler.set_in_out(in_point, out_point)
        except Exception as e:
            logger.debug("更新 I/O 标记失败: %s", e)

    def refresh_load_spans(self, clips=None):
        """根据片段特效/转场等刷新标尺红线。"""
        src = clips if clips is not None else getattr(self, "_clips", None)
        try:
            spans = compute_load_spans(src or [])
            self._time_ruler.set_load_spans(spans)
        except Exception as e:
            logger.debug("刷新负载标尺失败: %s", e)
    
    def _add_track(self, name, track_type):
        """ """
        TRACK_H = 48
        
        track_widget = QFrame()
        track_widget.setFixedHeight(TRACK_H)
        track_widget.setStyleSheet(
            "QFrame { background:#111; border:none; border-bottom:1px solid #1e1e1e; border-radius:0; }"
            "QFrame:hover { background:#161616; }"
        )
        track_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        track_widget.setMouseTracking(True)
        track_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        track_widget.customContextMenuRequested.connect(
            lambda pos: self._show_track_menu(track_widget)
        )
        track_row = QHBoxLayout(track_widget)
        track_row.setContentsMargins(0, 0, 0, 0)
        track_row.setSpacing(0)
        
        # ---- 轨道标识 (28px) ----
        identifier = QFrame()
        identifier.setFixedSize(28, TRACK_H)
        identifier.setStyleSheet("background:#151515; border-right:1px solid #1e1e1e;")
        identifier.setMouseTracking(True)
        identifier.setCursor(Qt.CursorShape.SizeVerCursor)
        id_lay = QVBoxLayout(identifier)
        id_lay.setContentsMargins(0, 0, 0, 0)
        id_lay.setSpacing(0)
        
        icons = {"video": "V", "audio": "A", "subtitle": "T"}
        colors = {"video": "#4fc3f7", "audio": "#81c784", "subtitle": "#ffb74d"}
        icon_lbl = QLabel(icons.get(track_type, "?"))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        icon_lbl.setStyleSheet(
            f"color:{colors.get(track_type,'#aaa')};font-size:11px;font-weight:bold;"
            "background:transparent;border:none;"
        )
        id_lay.addWidget(icon_lbl)
        track_row.addWidget(identifier)
        
        # ---- 片段区域 ----
        clip_container = QWidget()
        clip_container.setStyleSheet("background:#111;")
        clip_container.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        clip_container.customContextMenuRequested.connect(
            lambda pos: self._show_track_menu(track_widget)
        )
        clip_layout = QHBoxLayout(clip_container)
        # 片段绝对定位铺满行高，边距会制造轨内「黑边」错觉，故为 0
        clip_layout.setContentsMargins(0, 0, 0, 0)
        clip_layout.setSpacing(0)
        clip_layout.addStretch()
        track_row.addWidget(clip_container, 1)
        
        self._track_layout.addWidget(track_widget)
        
        track = {
            'id': len(self._tracks) + 1,
            'name': name,
            'type': track_type,
            'widget': track_widget,
            'identifier': identifier,
            'clip_container': clip_container,
            'content_layout': clip_layout,
            'muted': False,
            'solo': False,
            'locked': False,
            'volume': 1.0,
        }
        
        # Left-click: select (short press) / drag reorder (long press + move)
        # identifier / track_widget → 轨重排；clip_container → 框选（不抢轨重排）
        identifier.mousePressEvent = lambda e: self._drag_press(track, e)
        identifier.mouseMoveEvent = lambda e: self._drag_move(track, e)
        identifier.mouseReleaseEvent = lambda e: self._drag_release(track, e)
        
        track_widget.mousePressEvent = lambda e: self._drag_press(track, e)
        track_widget.mouseMoveEvent = lambda e: self._drag_move(track, e)
        track_widget.mouseReleaseEvent = lambda e: self._drag_release(track, e)
        
        clip_container.mousePressEvent = lambda e, tr=track: self._marquee_press(tr, e)
        clip_container.mouseMoveEvent = lambda e, tr=track: self._marquee_move(tr, e)
        clip_container.mouseReleaseEvent = lambda e, tr=track: self._marquee_release(tr, e)
        
        self._tracks.append(track)
        return track
    
    def _select_track(self, track):
        """选中轨道，更新左侧控制栏浮动位置"""
        if self._selected_track == track:
            return
        
        self._selected_track = track
        
        for t in self._tracks:
            if t == track:
                t['widget'].setStyleSheet(
                    "QFrame { background:#1a2a3a; border:none; border-bottom:1px solid #1e6bde; border-radius:0; }"
                )
                t['identifier'].setStyleSheet("background:#1e3a5f; border-right:1px solid #1e6bde;")
            else:
                t['widget'].setStyleSheet(
                    "QFrame { background:#111; border:none; border-bottom:1px solid #1e1e1e; border-radius:0; }"
                    "QFrame:hover { background:#161616; }"
                )
                t['identifier'].setStyleSheet("background:#151515; border-right:1px solid #1e1e1e;")
        
        self._update_ctrl_panel_position()
    
    def _update_ctrl_panel_position(self):
        """更新左侧控制栏浮动位置，使其与选中轨道垂直对齐"""
        track = self._selected_track
        if track is None:
            self._track_ctrl_panel.bind_track(None, 0)
            return
        
        ruler_h = self._time_ruler.height()
        scroll_offset = self._track_scroll.verticalScrollBar().value()
        track_y = track['widget'].pos().y()
        # 绝对Y = 标尺高度 + 轨道在viewport中位置 - 滚动偏移
        y_pos = ruler_h + track_y - scroll_offset
        self._track_ctrl_panel.bind_track(track, y_pos)
    
    def _drag_press(self, track, event):
        """Left mouse press: always select track, prepare for possible drag"""
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            self._show_track_menu(
                track['widget'],
                event.globalPosition().toPoint(),
            )
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        event.accept()
        
        # Always select the track
        self._select_track(track)
        
        # Prepare drag state (locked tracks cannot be dragged)
        if track.get('locked', False):
            return
        
        self._drag_track = track
        self._drag_orig_index = self._tracks.index(track)
        self._drag_start_y = track['widget'].pos().y()
        self._drag_active = False
        self._drag_press_global_y = event.globalPosition().y()
        
        if self._drag_indicator is None:
            self._drag_indicator = QFrame(self._track_viewport)
            self._drag_indicator.setStyleSheet("background-color: #1e6bde;")
            self._drag_indicator.setFixedHeight(3)
            self._drag_indicator.hide()
    
    def _drag_move(self, track, event):
        """Left mouse move: detect drag threshold, move track widget"""
        if self._drag_track != track or self._drag_press_global_y is None:
            return
        event.accept()
        
        widget = track['widget']
        delta = event.globalPosition().y() - self._drag_press_global_y
        
        if not self._drag_active:
            if abs(delta) > 8:
                self._drag_active = True
                widget.raise_()
                widget.setStyleSheet(
                    "QFrame { background:#2a3a4a; border:1px solid #1e6bde; border-radius:2px; }"
                )
                if self._drag_indicator:
                    self._drag_indicator.show()
                    self._drag_indicator.raise_()
        else:
            new_y = self._drag_start_y + int(delta)
            new_y = max(0, new_y)
            widget.move(0, new_y)
            self._update_drag_indicator()
    
    def _drag_release(self, track, event):
        """Left mouse release: finalize drag if active"""
        if self._drag_active and self._drag_track == track:
            self._finalize_drag(track)
        self._drag_track = None
        self._drag_active = False
        self._drag_press_global_y = None
        if self._drag_indicator:
            self._drag_indicator.hide()
    
    def _update_drag_indicator(self):
        """Position the insertion indicator between tracks"""
        if not self._drag_track or not self._drag_indicator:
            return
        
        dragged = self._drag_track
        dragged_y = dragged['widget'].pos().y()
        dragged_h = dragged['widget'].height()
        dragged_center = dragged_y + dragged_h // 2
        
        target_index = self._drag_orig_index
        for i, t in enumerate(self._tracks):
            if t == dragged:
                continue
            ty = t['widget'].pos().y()
            th = t['widget'].height()
            tc = ty + th // 2
            if dragged_center > tc:
                target_index = i + 1 if i >= self._drag_orig_index else i
            else:
                target_index = i if i < self._drag_orig_index else i - 1
        
        if target_index < self._drag_orig_index:
            indicator_y = self._tracks[target_index]['widget'].pos().y()
        else:
            idx = min(target_index, len(self._tracks) - 1)
            track_h = self._tracks[idx]['widget'].height()
            indicator_y = self._tracks[idx]['widget'].pos().y() + track_h
        
        self._drag_indicator.setFixedWidth(self._track_viewport.width())
        self._drag_indicator.move(0, indicator_y)
    
    def _finalize_drag(self, track):
        """Finalize drag: reorder the track in layout and list"""
        if not track:
            return
        
        dragged_y = track['widget'].pos().y()
        dragged_h = track['widget'].height()
        dragged_center = dragged_y + dragged_h // 2
        
        # Calculate target index
        new_index = 0
        for i, t in enumerate(self._tracks):
            if t == track:
                continue
            ty = t['widget'].pos().y()
            th = t['widget'].height()
            if dragged_center > ty + th // 2:
                new_index = i + 1
        
        old_index = self._drag_orig_index
        if new_index == old_index:
            self._restore_track_positions()
            return
        
        # Reorder in layout
        widget = track['widget']
        self._track_layout.removeWidget(widget)
        self._track_layout.insertWidget(new_index, widget)
        
        # Reorder in list
        self._tracks.pop(old_index)
        self._tracks.insert(new_index, track)
        
        # Update IDs
        for i, t in enumerate(self._tracks):
            t['id'] = i + 1
        
        self._restore_track_positions()
    
    def _restore_track_positions(self):
        """Restore all track widgets to their layout positions"""
        for t in self._tracks:
            w = t['widget']
            w.move(0, 0)
        self._track_layout.invalidate()
        self._track_viewport.updateGeometry()
        self._track_viewport.update()
    
    def _show_track_menu(self, track_widget, global_pos=None):
        """轨道空白区右键菜单"""
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#1e1e1e;border:1px solid #333;padding:4px;}"
            "QMenu::item{padding:5px 20px;color:#ccc;font-size:11px;}"
            "QMenu::item:selected{background:#1e6bde;color:#fff;}"
            "QMenu::separator{height:1px;background:#333;margin:4px 8px;}"
        )
        
        add_track = menu.addAction("➕ 添加轨道")
        add_clip = menu.addAction("➕ 添加片段")
        menu.addSeparator()
        rename = menu.addAction("✏ 重命名")
        duplicate = menu.addAction("📋 复制轨道")
        menu.addSeparator()
        lock_action = menu.addAction("🔒 锁定/解锁轨道")
        hide_action = menu.addAction("👁 隐藏/显示轨道")
        menu.addSeparator()
        paste_action = menu.addAction("📋 粘贴片段")
        menu.addSeparator()
        delete = menu.addAction("🗑 删除轨道")
        
        pos = global_pos if global_pos is not None else track_widget.mapToGlobal(QPoint(10, 10))
        action = menu.exec(pos)
        if not action:
            return
        
        target_track = None
        for t in self._tracks:
            if t['widget'] is track_widget:
                target_track = t
                break
        if not target_track:
            return
        
        if action == add_track:
            self.add_track("New Track", "video")
        elif action == add_clip:
            pass  # Clip adding is handled by the import/素材 panel
        elif action == delete:
            self.remove_track(target_track['id'])
        elif action == rename:
            self._rename_track(target_track)
        elif action == duplicate:
            self._duplicate_track(target_track)
        elif action == lock_action:
            target_track['locked'] = not target_track['locked']
            if self._selected_track == target_track:
                self._track_ctrl_panel._lock_btn.setChecked(target_track['locked'])
        elif action == hide_action:
            target_track['widget'].setVisible(not target_track['widget'].isVisible())
        elif action == paste_action:
            self.clip_context_action.emit("paste", None)

    def show_clip_context_menu(self, clip_data, global_pos):
        """片段右键菜单"""
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#1e1e1e;border:1px solid #333;padding:4px;}"
            "QMenu::item{padding:5px 20px;color:#ccc;font-size:11px;}"
            "QMenu::item:selected{background:#1e6bde;color:#fff;}"
            "QMenu::separator{height:1px;background:#333;margin:4px 8px;}"
        )
        split_act = menu.addAction("✂️ 在播放头分割")
        copy_act = menu.addAction("📋 复制")
        dup_act = menu.addAction("📄 复制一份")
        paste_act = menu.addAction("📋 粘贴")
        menu.addSeparator()
        close_gap_act = menu.addAction("🧲 合缝（消除间隙）")
        delete_act = menu.addAction("🗑 删除")
        seek_act = menu.addAction("⏩ 跳转到片段起点")
        action = menu.exec(global_pos)
        if not action:
            return
        if action == split_act:
            self.clip_context_action.emit("split", clip_data)
        elif action == copy_act:
            self.clip_context_action.emit("copy", clip_data)
        elif action == dup_act:
            self.clip_context_action.emit("duplicate", clip_data)
        elif action == paste_act:
            self.clip_context_action.emit("paste", clip_data)
        elif action == close_gap_act:
            self.clip_context_action.emit("close_gap", clip_data)
        elif action == delete_act:
            self.clip_context_action.emit("delete", clip_data)
        elif action == seek_act:
            start = float(clip_data.get("start_time", 0))
            self.set_playhead_position(start)
    
    def _on_track_mute(self, track, checked):
        """轨道静音：视觉半透明。走 clip_container 子控件，避免 content_layout 已销毁。"""
        if not isinstance(track, dict):
            return
        track['muted'] = checked
        try:
            widgets = list(self.iter_track_clip_widgets(track))
        except RuntimeError:
            return
        for widget in widgets:
            if not isinstance(widget, ClipWidget):
                continue
            try:
                widget.setGraphicsEffect(None)
                if checked:
                    from PySide6.QtWidgets import QGraphicsOpacityEffect
                    eff = QGraphicsOpacityEffect(widget)
                    eff.setOpacity(0.3)
                    widget.setGraphicsEffect(eff)
            except RuntimeError:
                continue
    
    def _on_track_solo(self, track, checked):
        """ """
        track['solo'] = checked
        if checked:
            for t in self._tracks:
                if t != track and t['type'] == track['type']:
                    t['solo'] = False
    
    def _on_track_lock(self, track, checked):
        """ """
        track['locked'] = checked

    def _on_track_volume(self, track, volume):
        """轨道音量调整"""
        if track is None:
            return
        track['volume'] = volume
        # 通知外层编辑器立刻刷新听感（若已挂回调）
        cb = getattr(self, "_track_volume_changed_cb", None)
        if callable(cb):
            try:
                cb(track, volume)
            except Exception as e:
                logger.info(f'track volume callback failed: {e}')

    def _on_track_collapse(self, track, collapsed):
        """轨道折叠/展开；折叠时休眠波形/缩略图线程，展开再懒加载。"""
        if track is None:
            return
        track['collapsed'] = collapsed
        if collapsed:
            track['clip_container'].setVisible(False)
            track['widget'].setFixedHeight(8)
            track['identifier'].setFixedHeight(8)
            # 休眠：停掉该轨片段后台 worker，避免折叠轨仍占 CPU
            try:
                for w in list(self.iter_track_clip_widgets(track)):
                    if hasattr(w, "sleep_media_workers"):
                        w.sleep_media_workers()
            except Exception as e:
                logger.debug("折叠轨休眠 worker 失败: %s", e)
        else:
            track['clip_container'].setVisible(True)
            track['widget'].setFixedHeight(48)
            track['identifier'].setFixedHeight(48)
            # 展开：按需重新调度缩略图/波形
            try:
                for w in list(self.iter_track_clip_widgets(track)):
                    if hasattr(w, "wake_media_workers"):
                        w.wake_media_workers()
            except Exception as e:
                logger.debug("展开轨唤醒 worker 失败: %s", e)
        self._update_track_min_width()
        if self._selected_track == track:
            self._update_ctrl_panel_position()

    def set_clip_interaction_active(self, active: bool):
        """片段拖拽/trim 中：标记交互，降低重绘与后台任务。"""
        was = bool(getattr(self, "_clip_interaction_active", False))
        self._clip_interaction_active = bool(active)
        if active:
            self._active_drag_clip = None  # 由 ClipWidget 自行登记
        elif was:
            # 松手后立刻唤醒视口内胶片条/波形（不必等滚动）
            try:
                self._wake_visible_clip_media()
            except Exception as e:
                logger.debug("拖拽结束后唤醒媒体失败: %s", e)

    def is_clip_interaction_active(self) -> bool:
        return bool(getattr(self, "_clip_interaction_active", False))

    def register_active_drag_clip(self, clip_widget):
        self._active_drag_clip = clip_widget

    def cancel_active_clip_interaction(self) -> bool:
        """Esc：取消进行中的片段拖拽/trim，还原按下时状态。"""
        w = getattr(self, "_active_drag_clip", None)
        if w is not None and hasattr(w, "cancel_edit_drag"):
            try:
                if w.cancel_edit_drag():
                    return True
            except Exception as e:
                logger.debug("取消拖拽失败: %s", e)
        # 回退：扫描正在拖的片
        for cw in self.all_clip_widgets():
            if getattr(cw, "_did_edit_drag", False) or (
                getattr(cw, "_drag_start_pos", None) is not None
            ):
                if hasattr(cw, "cancel_edit_drag") and cw.cancel_edit_drag():
                    return True
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.cancel_active_clip_interaction():
                event.accept()
                return
            if self.is_razor_mode():
                self.set_razor_mode(False)
                event.accept()
                return
        super().keyPressEvent(event)
    
    def _rename_track(self, track):
        """ """
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "Rename Track", "Track name:",
            text=track['name']
        )
        if ok and new_name.strip():
            track['name'] = new_name.strip()
    
    def _duplicate_track(self, track):
        """Duplicate track with same clips"""
        new_track = self._add_track(track['name'] + " (copy)", track['type'])
        self._update_track_min_width()
        try:
            widgets = list(self.iter_track_clip_widgets(track))
        except RuntimeError:
            widgets = []
        for widget in widgets:
            if isinstance(widget, ClipWidget):
                clip_data = dict(widget.clip_data)
                self.add_clip(clip_data, new_track['id'] - 1)
        return new_track
    
    # 已移除自定义设置相关方法
    
    def add_track(self, name, track_type):
        """ """
        track = self._add_track(name, track_type)
        self._update_track_min_width()
        return track

    def find_track_index_by_type(self, track_type: str, default: int = 0) -> int:
        """返回首个指定类型轨道的索引；找不到则回退 default。"""
        for i, t in enumerate(self._tracks):
            if t.get("type") == track_type:
                return i
        return default
    
    def remove_track(self, track_id):
        """ """
        for i, track in enumerate(self._tracks):
            if track['id'] == track_id:
                track['widget'].deleteLater()
                self._tracks.pop(i)
                for j, t in enumerate(self._tracks):
                    t['id'] = j + 1
                self._update_track_min_width()
                return True
        return False
    
    def set_store(self, store) -> None:
        """注入 TimelineStore 真相源引用（刀8 形态A：widget 层字段写全部经 store 收口）。"""
        self._timeline_store = store

    def _write_clip_fields(self, clip, **kv) -> None:
        """片段字段写统一入口：store 在册且 clip 即真相源行本体时按 id 走 set_fields，
        否则直写 fallback（未注入 store 的测试替身、或与真相源不共对象的私有副本）。

        本体校验是形态 A 的安全带：如复制轨等路径产生的同 id 副本，绝不允许经 store
        误写回原行；行本体则原地 update，对象同一性与拖拽跟手/还原/撤销恢复语义不变。
        """
        store = getattr(self, "_timeline_store", None)
        if store is not None and isinstance(clip, dict) and clip.get("id") is not None:
            if store.find_by_id(clip.get("id")) is clip:
                store.set_fields(clip.get("id"), **kv)
                return
        for k, v in kv.items():
            clip[k] = v

    def reset_clips_projection(self) -> None:
        """清空片段行镜像（投影）：外部清镜像唯一入口（刀8 镜像维护 API 化，禁外部直绑）。"""
        self._clips = []

    def sync_clips_projection(self, rows) -> None:
        """镜像重绑到真相源行列表并刷新活引用（吸收原外部 `tw._clips = list(...)` 直绑语义）。"""
        self._clips = list(rows)

    def add_clip(self, clip_data, track_index=0):
        """按 start_time 绝对定位添加到指定轨道。"""
        if track_index < 0 or track_index >= len(self._tracks):
            track_index = 0

        # 在创建 ClipWidget 之前就设置 track 字段，这样 ClipWidget 构造时就能正确识别轨道类型
        self._write_clip_fields(clip_data, track=track_index)
        # 同步 type，便于 ClipWidget 不依赖写死的 track==1
        track_type = self._tracks[track_index].get("type", "video")
        if "type" not in clip_data or not clip_data.get("type"):
            self._write_clip_fields(clip_data, type=track_type)

        track = self._tracks[track_index]
        container = track["clip_container"]
        clip_widget = ClipWidget(clip_data, container)
        clip_widget.clicked.connect(self._on_clip_clicked)
        clip_widget.keyframe_clicked.connect(self.clip_keyframe_clicked.emit)
        clip_widget.trim_committed.connect(self.clip_trim_committed.emit)

        if clip_data not in self._clips:
            self._clips.append(clip_data)
        self.position_clip_widget(clip_widget)
        return clip_widget

    def remove_clip_widget_by_id(self, clip_id) -> bool:
        for track in self._tracks:
            for w in list(self.iter_track_clip_widgets(track)):
                if w.clip_data.get("id") == clip_id:
                    try:
                        if hasattr(w, "sleep_media_workers"):
                            w.sleep_media_workers()
                        elif hasattr(w, "_cleanup_workers"):
                            w._cleanup_workers()
                    except Exception as e:
                        logger.debug("删片前停 worker 失败: %s", e)
                    w.setParent(None)
                    w.deleteLater()
                    self._clips = [c for c in self._clips if c.get("id") != clip_id]
                    return True
        return False

    def reparent_clip_to_track(self, clip_widget, track_index: int):
        if clip_widget is None or track_index < 0 or track_index >= len(self._tracks):
            return
        track = self._tracks[track_index]
        clip_widget.setParent(track["clip_container"])
        self._write_clip_fields(clip_widget.clip_data, track=track_index)
        self.position_clip_widget(clip_widget)
    
    def is_razor_mode(self) -> bool:
        return bool(getattr(self, "_razor_mode", False))

    def _clear_marquee_state(self):
        """取消框选橡胶筋状态（刀片切换 / 避免与 razor 冲突）。"""
        self._marquee_origin = None
        self._marquee_rect = None
        self._marquee_active = False
        self._marquee_additive = False
        grab_w = getattr(self, "_marquee_grab_widget", None)
        if grab_w is not None:
            try:
                grab_w.releaseMouse()
            except Exception as e:
                # 释放失败会让该 widget 继续吃掉鼠标事件 → 表现为"框选卡死"
                logger.debug("框选：释放抓取 widget 鼠标失败（可能卡死输入）: %s", e, exc_info=True)
            self._marquee_grab_widget = None
        try:
            self._apply_selection_visual()
        except Exception as e:
            logger.debug("框选：复位选中态视觉失败: %s", e, exc_info=True)
        vp = getattr(self, "_track_viewport", None)
        if vp is not None:
            vp.update()

    def set_razor_mode(self, enabled: bool):
        """剪映式刀片工具态：悬停切开线 + 点击切开。"""
        on = bool(enabled)
        prev = bool(getattr(self, "_razor_mode", False))
        self._razor_mode = on
        if prev != on:
            self._clear_marquee_state()
        if not on:
            self._razor_hover_t = None
            try:
                self._razor_guide.set_guide(None)
            except Exception:
                pass
        cur = Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor
        try:
            self.setCursor(cur)
            vp = getattr(self, "_track_viewport", None)
            if vp is not None:
                vp.setCursor(cur)
                vp.setMouseTracking(True)
            for track in getattr(self, "_tracks", []) or []:
                cc = track.get("clip_container")
                if cc is not None:
                    cc.setCursor(cur)
                    cc.setMouseTracking(True)
            for w in self.all_clip_widgets():
                w.setCursor(cur)
                w.setMouseTracking(True)
        except Exception as e:
            logger.debug("刀片光标设置失败: %s", e)
        if prev != on:
            try:
                self.razor_mode_changed.emit(on)
            except Exception:
                pass

    def toggle_razor_mode(self) -> bool:
        self.set_razor_mode(not self.is_razor_mode())
        return self.is_razor_mode()

    def time_at_global_pos(self, global_pos) -> float:
        """全局坐标 → 时间线秒（与片缘 X 对齐）。"""
        vp = getattr(self, "_track_viewport", None)
        if vp is None:
            return 0.0
        try:
            from PySide6.QtCore import QPoint as _QP
            if not isinstance(global_pos, _QP):
                global_pos = _QP(int(global_pos.x()), int(global_pos.y()))
            local = vp.mapFromGlobal(global_pos)
            # 反解 content_x_for_time：找 clip_container 原点
            pps = max(1e-6, self.px_per_sec())
            origin_x = 100
            for track in getattr(self, "_tracks", []) or []:
                cc = track.get("clip_container")
                if cc is None:
                    continue
                try:
                    origin_x = int(cc.mapTo(vp, QPoint(0, 0)).x())
                    break
                except Exception:
                    continue
            t = (float(local.x()) - float(origin_x)) / pps
            t = max(0.0, t)
            return _quantize_time(t, self.frame_duration())
        except Exception:
            return 0.0

    def _update_razor_hover(self, global_pos):
        if not self.is_razor_mode():
            return
        t = self.time_at_global_pos(global_pos)
        self._razor_hover_t = t
        try:
            self._razor_guide.set_guide(t)
        except Exception as e:
            logger.debug("刀片悬停线失败: %s", e)

    def _razor_cut_at_global(self, global_pos) -> bool:
        """刀片点击：发信号给 Editor；返回是否已处理。"""
        if not self.is_razor_mode():
            return False
        t = self.time_at_global_pos(global_pos)
        self._razor_hover_t = t
        try:
            self._razor_guide.set_guide(t)
        except Exception:
            pass
        self.razor_cut_at.emit(float(t))
        return True

    def _marquee_press(self, track, event):
        """空白处按下：选轨 + 准备框选（Shift 追加）。刀片模式改为切开。"""
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            self._show_track_menu(
                track["widget"],
                event.globalPosition().toPoint(),
            )
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.is_razor_mode():
            event.accept()
            self._razor_cut_at_global(event.globalPosition().toPoint())
            return
        event.accept()
        self._select_track(track)
        vp = self._track_viewport
        origin = vp.mapFromGlobal(event.globalPosition().toPoint())
        self._marquee_origin = origin
        self._marquee_rect = QRect(origin, origin)
        self._marquee_active = False
        self._marquee_additive = is_shift() or is_ctrl()
        if not self._marquee_additive:
            # 点击空白清选并通知 Editor，避免幽灵 Delete
            self.clear_selection(emit=True)
        # 跨轨拖框：抓住 viewport，避免移出本轨丢事件
        try:
            cc = track.get("clip_container")
            if cc is not None:
                cc.grabMouse()
                self._marquee_grab_widget = cc
            else:
                self._marquee_grab_widget = None
        except Exception:
            self._marquee_grab_widget = None

    def _marquee_move(self, track, event):
        if self.is_razor_mode():
            event.accept()
            self._update_razor_hover(event.globalPosition().toPoint())
            return
        if self._marquee_origin is None:
            return
        event.accept()
        vp = self._track_viewport
        cur = vp.mapFromGlobal(event.globalPosition().toPoint())
        rect = rect_from_points(self._marquee_origin, cur)
        if not self._marquee_active:
            if (
                abs(cur.x() - self._marquee_origin.x()) > MARQUEE_DRAG_THRESHOLD_PX
                or abs(cur.y() - self._marquee_origin.y()) > MARQUEE_DRAG_THRESHOLD_PX
            ):
                self._marquee_active = True
        if self._marquee_active:
            self._marquee_rect = rect
            # 拖动中即时高亮将命中的片（追加模式合并已有选区）
            hits = ids_intersecting_viewport_rect(self, rect)
            if self._marquee_additive:
                preview = self.get_selected_ids() | hits
            else:
                preview = hits
            self.preview_selection_ids(preview)
            vp.update()

    def _marquee_release(self, track, event):
        if self.is_razor_mode():
            return
        if self._marquee_origin is None:
            return
        event.accept()
        vp = self._track_viewport
        if self._marquee_active and self._marquee_rect is not None:
            hits = ids_intersecting_viewport_rect(self, self._marquee_rect)
            if self._marquee_additive:
                self.add_to_selection(hits, emit=True)
            else:
                self.set_selection(hits, emit=True)
        else:
            # 未形成框选：还原 press 后的真实选区视觉
            self._apply_selection_visual()
        # 纯点击空白（无拖动）已在 press 清选
        self._marquee_origin = None
        self._marquee_rect = None
        self._marquee_active = False
        self._marquee_additive = False
        grab_w = getattr(self, "_marquee_grab_widget", None)
        if grab_w is not None:
            try:
                grab_w.releaseMouse()
            except Exception:
                pass
            self._marquee_grab_widget = None
        vp.update()

    def _on_clip_clicked(self, clip_data):
        """点选：普通单选 / Ctrl 切换 / Shift 同轨时间重叠范围；保持多选集可批量拖。"""
        self.handle_clip_click(clip_data)
    
    def set_zoom(self, zoom, anchor_time=None, anchor_viewport_x=None):
        """缩放；可指定锚点时间，使该时刻尽量停在同一视口 X（剪映式）。"""
        old_pps = max(1e-6, self.px_per_sec())
        try:
            bar = self._track_scroll.horizontalScrollBar()
            old_scroll = int(bar.value())
        except Exception:
            bar = None
            old_scroll = 0
        if anchor_time is None:
            anchor_time = float(self._playhead_pos or 0)
        if anchor_viewport_x is None:
            anchor_viewport_x = 100  # 轨道内容区起点附近
        # 缩放前：锚点在内容坐标中的 X
        old_content_x = 100 + float(anchor_time) * old_pps

        self._zoom = _clamp_timeline_zoom(zoom)
        self._update_time_ruler()
        self._update_track_min_width()
        self._marker_layer.set_zoom(self._zoom)
        self.relayout_clips()
        # 刷新播放头位置（不二次 emit 跟镜抖动）
        ph_x = self.playhead_x_for_time(self._playhead_pos)
        self._track_playhead.move(ph_x, 0)
        self._track_playhead.setFixedHeight(self._track_viewport.height())

        if bar is not None:
            new_pps = max(1e-6, self.px_per_sec())
            new_content_x = 100 + float(anchor_time) * new_pps
            # 保持锚点相对视口位置：new_scroll + viewport_x ≈ new_content_x
            new_scroll = int(round(new_content_x - float(anchor_viewport_x)))
            bar.setValue(max(0, new_scroll))

    def wheelEvent(self, event):
        """Ctrl+滚轮：以指针下时间为锚缩放；普通滚轮横向轻移。"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta != 0:
                z = int(self._zoom)
                step = 25 if z < 200 else (50 if z < 800 else 100)
                # 指针相对滚动视口的 X → 锚点时间
                try:
                    vp = self._track_scroll.viewport()
                    local = vp.mapFromGlobal(event.globalPosition().toPoint())
                    scroll = int(self._track_scroll.horizontalScrollBar().value())
                    content_x = scroll + local.x()
                    pps = max(1e-6, self.px_per_sec())
                    anchor_t = max(0.0, (content_x - 100) / pps)
                    self.set_zoom(
                        z + step if delta > 0 else z - step,
                        anchor_time=anchor_t,
                        anchor_viewport_x=local.x(),
                    )
                except Exception:
                    self.set_zoom(z + step if delta > 0 else z - step)
            event.accept()
            return
        # Shift+滚轮或触控板水平：平移时间线
        dx = event.angleDelta().x()
        dy = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            dx = dy
            dy = 0
        if abs(dx) > abs(dy) and dx != 0:
            try:
                bar = self._track_scroll.horizontalScrollBar()
                bar.setValue(bar.value() - int(dx))
                event.accept()
                return
            except Exception:
                pass
        super().wheelEvent(event)
    
    def _update_track_min_width(self):
        """ """
        px_per_sec = self.px_per_sec()
        min_width = int(self._total_duration * px_per_sec + 120)
        track_count = max(3, len(self._tracks))
        min_height = track_count * 48 + 20
        self._track_viewport.setMinimumSize(min_width, min_height)
        # 更新标记层最小宽度
        self._marker_layer.setMinimumWidth(min_width)
        self._marker_layer.set_total_duration(self._total_duration)
    
    def content_x_for_time(self, position: float) -> int:
        """时间 → 视口 X，与 clip_container 内片缘对齐。"""
        pps = max(1e-6, self.px_per_sec())
        vp = getattr(self, "_track_viewport", None)
        for track in getattr(self, "_tracks", []) or []:
            cc = track.get("clip_container")
            if cc is None or vp is None:
                continue
            try:
                origin = cc.mapTo(vp, QPoint(0, 0))
                return int(origin.x() + float(position) * pps)
            except Exception:
                continue
        return 100 + int(float(position) * pps)

    def playhead_x_for_time(self, position: float) -> int:
        return self.content_x_for_time(position)

    def ensure_playhead_visible(self, margin_px: int = 48):
        """播放头靠近视口边缘时横向跟随（剪映式跟镜）。"""
        try:
            bar = self._track_scroll.horizontalScrollBar()
            x = self.playhead_x_for_time(self._playhead_pos)
            view_w = max(1, self._track_scroll.viewport().width())
            left = int(bar.value())
            right = left + view_w
            if x < left + margin_px:
                bar.setValue(max(0, x - margin_px))
            elif x > right - margin_px:
                bar.setValue(max(0, x - view_w + margin_px))
        except Exception:
            pass

    def set_playhead_position(self, position, follow: bool = True):
        """设置播放头；默认跟镜滚动。"""
        pos = max(0.0, float(position))
        try:
            pos = _quantize_time(pos, self.frame_duration())
        except Exception:
            pass
        self._playhead_pos = pos
        self._time_ruler.set_playhead(pos)
        playhead_x = self.playhead_x_for_time(pos)
        self._track_playhead.move(playhead_x, 0)
        self._track_playhead.setFixedHeight(self._track_viewport.height())
        self._track_playhead.setStyleSheet("background-color: #ff4757; width: 2px;")
        if follow and not getattr(self, "_is_playing", False):
            self.ensure_playhead_visible()
        self.playhead_moved.emit(pos)
    
    def play(self):
        """ """
        if not self._is_playing:
            self._is_playing = True
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._on_playback_tick)
            self._timer.start(33)  # 约30fps
    
    def pause(self):
        """ """
        if self._is_playing:
            self._is_playing = False
            if self._timer:
                self._timer.stop()
                self._timer.deleteLater()
                self._timer = None
    
    def stop(self):
        """ """
        self.pause()
        self.set_playhead_position(0)
    
    def _on_playback_tick(self):
        """ """
        if self._is_playing:
            new_position = self._playhead_pos + 0.033  # 约30fps
            if new_position <= self._total_duration:
                self.set_playhead_position(new_position)
            else:
                self.stop()

    def dragEnterEvent(self, event):
        """处理拖放进入事件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        """处理拖放移动事件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """处理拖放放下事件，导入媒体文件"""
        if not event.mimeData().hasUrls():
            return

        file_paths = []
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if local_path and os.path.exists(local_path):
                ext = os.path.splitext(local_path)[1].lower()
                if ext in ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.mp3', '.wav', '.aac', '.ogg', '.flac', '.m4a', '.jpg', '.jpeg', '.png', '.bmp', '.webp'):
                    file_paths.append(local_path)

        if file_paths:
            self.files_dropped.emit(file_paths)

        event.acceptProposedAction()

