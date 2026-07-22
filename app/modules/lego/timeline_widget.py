"""
时间线控件模块
================
从 modules.py 提取的独立时间线UI组件：
- TimeRuler: 时间标尺
- TrackControlPanel: 轨道控制面板
- TimelineWidget: 时间线主控件
- ClipWidget: 片段控件
"""

import os
import json
import logging
import time
import urllib.request

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QUrl, QPoint, QMimeData
from PyQt6.QtGui import (
    QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics,
    QPolygon, QShortcut, QKeySequence, QDrag
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QSlider, QMenu
)

logger = logging.getLogger("AI短剧编辑器.timeline_widget")


def _report_timeline_widget_debug(hypothesis_id, location, msg, data=None):
    """临时调试上报：定位 TimelineWidget 片段创建链路。"""
    # #region debug-point video-import-timeline
    try:
        env_path = os.path.join(os.getcwd(), ".dbg", "video-import-timeline.env")
        debug_url = "http://127.0.0.1:7777/event"
        session_id = "video-import-timeline"
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as env_file:
                for line in env_file:
                    if line.startswith("DEBUG_SERVER_URL="):
                        debug_url = line.strip().split("=", 1)[1]
                    elif line.startswith("DEBUG_SESSION_ID="):
                        session_id = line.strip().split("=", 1)[1]
        payload = json.dumps({
            "sessionId": session_id,
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "msg": f"[DEBUG] {msg}",
            "data": data or {},
            "ts": int(time.time() * 1000),
        }, ensure_ascii=False).encode("utf-8")
        urllib.request.urlopen(
            urllib.request.Request(debug_url, data=payload, headers={"Content-Type": "application/json"}),
            timeout=0.8,
        ).read()
    except Exception:
        logger.debug("timeline widget debug report failed", exc_info=True)
    # #endregion

class TimeRuler(QWidget):
    """ """
    
    clicked = pyqtSignal(float)  # 点击位置（秒）
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._zoom = 100
        self._total_duration = 60
        self._playhead_pos = 0
        self._left_margin = 100  # 左侧轨道控制区宽度
        self.setFixedHeight(45)
        self.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
    
    def set_zoom(self, zoom):
        self._zoom = max(10, min(500, zoom))
        self.update()
    
    def set_playhead(self, pos):
        self._playhead_pos = pos
        self.update()
    
    def _px_per_second(self):
        """ """
        return 20 * (self._zoom / 100)
    
    def _time_to_x(self, t):
        """ """
        return self._left_margin + int(t * self._px_per_second())
    
    def _x_to_time(self, x):
        """ """
        return max(0, (x - self._left_margin) / self._px_per_second())
    
    def _format_time_label(self, t):
        """ """
        if t < 1:
            return f"{int(t * 1000)}ms" if t > 0 else "0"
        elif t < 60:
            return f"{t:g}s"  # 使用 :g 去除多余的小数位
        else:
            m, s = divmod(int(t), 60)
            return f"{m}:{s:02d}"
    
    def paintEvent(self, event):
        """ """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        painter.fillRect(rect, QColor("#1a1a1a"))
        
        pps = self._px_per_second()
        width = rect.width()
        # 根据可见宽度动态计算当前可见的最大时长
        visible_duration = int((width - self._left_margin) / pps) if pps > 0 else 60
        # 总时长取可见时长和 _total_duration 的较大值，确保至少能显示当前内容
        max_t = max(self._total_duration, visible_duration)
        
        # 根据 pps 自动选择刻度间隔
        candidates = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60]
        major_step = 1.0
        minor_step = 0.5
        for c in candidates:
            pixel_dist = c * pps
            if 60 <= pixel_dist <= 200:
                major_step = c
                minor_step = c / (5.0 if c >= 1 else 2.0)
                break
        
        # 绘制次刻度
        painter.setPen(QColor("#333333"))
        t = 0
        while t <= max_t:
            x = self._time_to_x(t)
            if x >= self._left_margin and x <= width:
                painter.drawLine(x, 33, x, 40)
            t += minor_step
        
        # 绘制主刻度
        painter.setPen(QPen(QColor("#555555"), 2))
        t = 0
        while t <= max_t:
            x = self._time_to_x(t)
            if x >= self._left_margin and x <= width:
                painter.drawLine(x, 22, x, 40)
            t += major_step
        
        # 绘制时间标签
        painter.setPen(QColor("#cccccc"))
        font = QFont("Arial", 10, QFont.Weight.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)
        
        t = 0
        while t <= max_t:
            x = self._time_to_x(t)
            if x >= self._left_margin and x <= width:
                lbl = self._format_time_label(t)
                tw = fm.horizontalAdvance(lbl)
                painter.drawText(x - tw // 2, 18, lbl)
            t += major_step
        
        # 绘制播放头
        ph_x = self._time_to_x(self._playhead_pos)
        if ph_x >= self._left_margin and ph_x <= width:
            painter.setPen(QPen(QColor("#ff4757"), 2))
            painter.drawLine(ph_x, 0, ph_x, 40)
            painter.setBrush(QColor("#ff4757"))
            painter.drawPolygon(QPolygon([
                QPoint(ph_x - 5, 0), QPoint(ph_x + 5, 0), QPoint(ph_x, 8)
            ]))
    
    def mousePressEvent(self, event):
        """ """
        if event.button() == Qt.MouseButton.LeftButton:
            t = self._x_to_time(event.pos().x())
            self.clicked.emit(t)


class TimelineMarkerLayer(QWidget):
    """时间轴标记层 - 叠加显示高光区域和AI插帧节点"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlights = []
        self._interpolation_markers = []
        self._zoom = 100
        self._total_duration = 600
        self._left_margin = 100
        self._hovered_marker = None
        self._hovered_highlight = None
        self.setMouseTracking(True)
        self._connect_manager()

    def _connect_manager(self):
        """连接高光预览管理器"""
        try:
            from app.core.highlight_preview import highlight_preview_manager
            highlight_preview_manager.highlights_updated.connect(self.set_highlights)
            highlight_preview_manager.interpolation_markers_updated.connect(self.set_interpolation_markers)
        except Exception:
            pass

    def set_highlights(self, highlights):
        """设置高光片段列表"""
        self._highlights = highlights
        self.update()

    def set_interpolation_markers(self, markers):
        """设置AI插帧节点列表"""
        self._interpolation_markers = markers
        self.update()

    def set_zoom(self, zoom):
        """设置缩放比例"""
        self._zoom = zoom
        self.update()

    def set_total_duration(self, duration):
        """设置总时长"""
        self._total_duration = duration
        self.update()

    def _px_per_second(self):
        """计算每秒钟的像素数"""
        return 20 * (self._zoom / 100)

    def _time_to_x(self, time_sec):
        """时间转X坐标"""
        return self._left_margin + int(time_sec * self._px_per_second())

    def paintEvent(self, event):
        """绘制标记层"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        width = rect.width()
        height = rect.height()

        # 绘制高光区域色块
        for highlight in self._highlights:
            start_x = self._time_to_x(highlight.start_time)
            end_x = self._time_to_x(highlight.end_time)
            
            if end_x <= self._left_margin or start_x >= width:
                continue
            
            start_x = max(start_x, self._left_margin)
            end_x = min(end_x, width)
            
            highlight_color = QColor(highlight.color)
            highlight_color.setAlpha(40)
            
            painter.setBrush(QBrush(highlight_color))
            painter.setPen(Qt.PenStyle.NoPen)
            
            segment_height = 8
            segment_y = 0
            painter.fillRect(start_x, segment_y, end_x - start_x, segment_height, highlight_color)

        # 绘制AI插帧节点
        for marker in self._interpolation_markers:
            x = self._time_to_x(marker.time)
            
            if x < self._left_margin or x >= width:
                continue
            
            marker_color = QColor(marker.color)
            is_hovered = self._hovered_marker == marker.id
            
            painter.setBrush(QBrush(marker_color))
            if is_hovered:
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                size = 6
            else:
                painter.setPen(QPen(QColor(0, 0, 0, 150), 1))
                size = 4

            y_center = height // 2
            poly = QPolygon([
                QPoint(x, y_center - size),
                QPoint(x + size, y_center),
                QPoint(x, y_center + size),
                QPoint(x - size, y_center),
            ])
            painter.drawPolygon(poly)

        painter.end()

    def mouseMoveEvent(self, event):
        """处理鼠标移动，显示tooltip"""
        from PyQt6.QtWidgets import QToolTip
        
        x = event.pos().x()
        time_sec = max(0, (x - self._left_margin) / self._px_per_second())

        self._hovered_highlight = None
        for highlight in self._highlights:
            if highlight.start_time <= time_sec <= highlight.end_time:
                self._hovered_highlight = highlight
                tip = f"<b>{highlight.label}</b><br/>" \
                      f"时间: {highlight.start_time:.1f}s - {highlight.end_time:.1f}s<br/>" \
                      f"评分: {highlight.score:.2f}"
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                self.update()
                return

        self._hovered_marker = None
        for marker in self._interpolation_markers:
            marker_x = self._time_to_x(marker.time)
            if abs(x - marker_x) <= 10:
                self._hovered_marker = marker.id
                tip = f"<b>AI插帧</b><br/>" \
                      f"时间: {marker.time:.3f}s<br/>" \
                      f"类型: {marker.interpolation_type.value}<br/>" \
                      f"置信度: {marker.confidence:.2f}"
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                self.update()
                return

        QToolTip.hideText()
        self._hovered_highlight = None
        self._hovered_marker = None
        self.update()


class TrackControlPanel(QWidget):
    """统一控制栏 - 100px固定宽度，位于轨道区左侧非滚动区域"""

    mute_toggled = pyqtSignal(object, bool)
    solo_toggled = pyqtSignal(object, bool)
    lock_toggled = pyqtSignal(object, bool)
    volume_changed = pyqtSignal(object, float)
    collapse_toggled = pyqtSignal(object, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 48)
        self.setStyleSheet("background:#151515; border-right:1px solid #1e1e1e; border-bottom:1px solid #1e1e1e;")
        self._track = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 1, 4, 1)
        lay.setSpacing(1)

        # 占位提示
        self._placeholder = QLabel("选择轨道\n进行操作")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet("color:#444;font-size:10px;background:transparent;border:none;")
        lay.addWidget(self._placeholder)

        # 轨道名称
        self._track_name = QLabel("")
        self._track_name.setStyleSheet("color:#888;font-size:9px;font-weight:500;background:transparent;border:none;")
        self._track_name.hide()
        lay.addWidget(self._track_name)

        # M/S/L 按钮行
        btn_style = (
            "QPushButton{background:transparent;color:#555;border:1px solid #333;border-radius:3px;"
            "font-size:9px;font-weight:bold;}"
            "QPushButton:hover{background:#2a2a2a;color:#aaa;}"
        )

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(2)

        self._mute_btn = QPushButton("M")
        self._mute_btn.setFixedSize(20, 20)
        self._mute_btn.setCheckable(True)
        self._mute_btn.setToolTip("静音")
        self._mute_btn.setStyleSheet(btn_style + "QPushButton:checked{background:#d32f2f;color:#fff;border-color:#d32f2f;}")
        self._mute_btn.toggled.connect(lambda checked: self.mute_toggled.emit(self._track, checked))
        btn_row.addWidget(self._mute_btn)

        self._solo_btn = QPushButton("S")
        self._solo_btn.setFixedSize(20, 20)
        self._solo_btn.setCheckable(True)
        self._solo_btn.setToolTip("独奏")
        self._solo_btn.setStyleSheet(btn_style + "QPushButton:checked{background:#ff9800;color:#fff;border-color:#ff9800;}")
        self._solo_btn.toggled.connect(lambda checked: self.solo_toggled.emit(self._track, checked))
        btn_row.addWidget(self._solo_btn)

        self._lock_btn = QPushButton("L")
        self._lock_btn.setFixedSize(20, 20)
        self._lock_btn.setCheckable(True)
        self._lock_btn.setToolTip("锁定")
        self._lock_btn.setStyleSheet(btn_style + "QPushButton:checked{background:#555;color:#fff;border-color:#777;}")
        self._lock_btn.toggled.connect(lambda checked: self.lock_toggled.emit(self._track, checked))
        btn_row.addWidget(self._lock_btn)

        self._fold_btn = QPushButton("⊟")
        self._fold_btn.setFixedSize(20, 20)
        self._fold_btn.setCheckable(True)
        self._fold_btn.setToolTip("折叠/展开")
        self._fold_btn.setStyleSheet(btn_style + "QPushButton:checked{background:#1e6bde;color:#fff;border-color:#1e6bde;}")
        self._fold_btn.toggled.connect(lambda checked: self.collapse_toggled.emit(self._track, checked))
        btn_row.addWidget(self._fold_btn)

        btn_row.addStretch()
        lay.addLayout(btn_row)

        # 音量滑条 (仅音频轨显示)
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 200)
        self._volume_slider.setValue(100)
        self._volume_slider.setFixedHeight(12)
        self._volume_slider.setToolTip("音量")
        self._volume_slider.setStyleSheet("""
            QSlider::groove:horizontal{background:#333;height:3px;border-radius:1px;}
            QSlider::handle:horizontal{background:#81c784;width:8px;height:8px;margin:-3px 0;border-radius:4px;}
            QSlider::handle:horizontal:hover{background:#a5d6a7;}
            QSlider::sub-page:horizontal{background:#81c784;height:3px;border-radius:1px;}
        """)
        self._volume_slider.valueChanged.connect(
            lambda v: self.volume_changed.emit(self._track, v / 100.0)
        )
        self._volume_slider.hide()
        lay.addWidget(self._volume_slider)

        self._btn_row = btn_row
        self._hide_controls()

    def _hide_controls(self):
        """隐藏所有控件"""
        self._track_name.hide()
        self._volume_slider.hide()
        for i in range(self._btn_row.count()):
            w = self._btn_row.itemAt(i).widget()
            if w:
                w.hide()

    def _show_controls(self):
        """显示所有控件"""
        self._track_name.show()
        self._volume_slider.show()
        for i in range(self._btn_row.count()):
            w = self._btn_row.itemAt(i).widget()
            if w:
                w.show()

    def bind_track(self, track, y_pos):
        """绑定轨道"""
        self._track = track
        if track is None:
            self._placeholder.show()
            self._hide_controls()
            self.hide()
            return

        self.move(0, y_pos)
        self._placeholder.hide()
        self._show_controls()

        colors = {"video": "#4fc3f7", "audio": "#81c784", "subtitle": "#ffb74d"}
        lbls = {"video": "视频轨", "audio": "音频轨", "subtitle": "字幕轨"}
        track_type = track.get('type', 'video')
        self._track_name.setText(lbls.get(track_type, track.get('name', '')))
        self._track_name.setStyleSheet(
            f"color:{colors.get(track_type,'#aaa')};font-size:9px;font-weight:bold;background:transparent;border:none;"
        )

        # M/S/L 状态同步
        self._mute_btn.blockSignals(True)
        self._mute_btn.setChecked(track.get('muted', False))
        self._mute_btn.blockSignals(False)
        self._solo_btn.blockSignals(True)
        self._solo_btn.setChecked(track.get('solo', False))
        self._solo_btn.blockSignals(False)
        self._lock_btn.blockSignals(True)
        self._lock_btn.setChecked(track.get('locked', False))
        self._lock_btn.blockSignals(False)
        self._fold_btn.blockSignals(True)
        self._fold_btn.setChecked(track.get('collapsed', False))
        self._fold_btn.blockSignals(False)

        # 音量滑条 - 仅音频轨道显示
        if track_type == "audio":
            self._volume_slider.show()
            self._volume_slider.blockSignals(True)
            self._volume_slider.setValue(int(track.get('volume', 1.0) * 100))
            self._volume_slider.blockSignals(False)
        else:
            self._volume_slider.hide()

        self.show()
        self.raise_()


class TrackViewport(QWidget):
    """轨道视图区域 - 支持播放头拖动"""
    
    playhead_dragged = pyqtSignal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent_widget = parent
        self._is_dragging_playhead = False
        self.setMouseTracking(True)
    
    def mousePressEvent(self, event):
        """处理鼠标按下事件 - 检测是否点击播放头"""
        if event.button() == Qt.MouseButton.LeftButton:
            playhead_x = self._parent_widget._track_playhead.x()
            if abs(event.pos().x() - playhead_x) <= 5:
                self._is_dragging_playhead = True
                event.accept()
            else:
                self._is_dragging_playhead = False
                super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """处理鼠标移动事件 - 拖动播放头"""
        if self._is_dragging_playhead:
            x = max(100, min(self.width(), event.pos().x()))
            scale_factor = self._parent_widget._zoom / 100
            time_pos = (x - 100) / (20 * scale_factor)
            self.playhead_dragged.emit(time_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """处理鼠标释放事件"""
        self._is_dragging_playhead = False
        super().mouseReleaseEvent(event)


class TimelineWidget(QWidget):
    """ """

    clip_selected = pyqtSignal(object)
    playhead_moved = pyqtSignal(float)
    # 补短 P1#8：转发 ClipWidget 的关键帧点击，方便 EditorModule 直接监听
    clip_keyframe_clicked = pyqtSignal(object, dict)
    files_dropped = pyqtSignal(list)
    clip_context_action = pyqtSignal(str, object)  # action, clip_data
    clip_trim_committed = pyqtSignal(object)  # 松手后规范化的 clip_data
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks = []
        self._clips = []
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
        self._snap_threshold_sec = 0.25
        self.setAcceptDrops(True)
        self._setup_ui()

    def px_per_sec(self) -> float:
        return 20.0 * (float(self._zoom) / 100.0)

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
        w = max(40, int(dur * px))
        clip_widget.setFixedWidth(w)
        clip_widget.setFixedHeight(38)
        clip_widget.move(x, 4)
        clip_widget.show()
        clip_widget.raise_()

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

    def snap_start_time(self, clip_data, proposed_start: float, exclude_id=None) -> float:
        """吸附到播放头与同轨其它片缘。"""
        if not getattr(self, "_snap_enabled", False):
            return max(0.0, proposed_start)
        thr = float(getattr(self, "_snap_threshold_sec", 0.25) or 0.25)
        candidates = [0.0, float(getattr(self, "_playhead_pos", 0) or 0)]
        track_i = int(clip_data.get("track", 0) or 0)
        dur = float(clip_data.get("duration", 0) or 0)
        for c in self._clips:
            if exclude_id and c.get("id") == exclude_id:
                continue
            if int(c.get("track", 0) or 0) != track_i:
                continue
            st = float(c.get("start_time", 0) or 0)
            cd = float(c.get("duration", 0) or 0)
            candidates.extend([st, st + cd, st - dur, st + cd - dur])
        best = proposed_start
        best_d = thr + 1.0
        for t in candidates:
            d = abs(proposed_start - t)
            if d < best_d and d <= thr:
                best_d = d
                best = t
        return max(0.0, best)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # === 顶部：时间标尺 ===
        self._time_ruler = TimeRuler(self)
        self._time_ruler.clicked.connect(self.set_playhead_position)
        layout.addWidget(self._time_ruler)

        # === 标记层（高光区域 + AI插帧节点） ===
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
            lambda v: self._time_ruler.update()
        )
        # 垂直滚动时更新控制栏位置
        self._track_scroll.verticalScrollBar().valueChanged.connect(
            lambda v: self._update_ctrl_panel_position()
        )

        layout.addWidget(self._track_scroll, 1)
        
        self._add_track("视频轨", "video")
        self._add_track("音频轨", "audio")
        self._add_track("字幕轨", "subtitle")
        self._update_track_min_width()
    
    def _update_time_ruler(self):
        """ """
        self._time_ruler.set_zoom(self._zoom)
    
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
        clip_layout.setContentsMargins(4, 4, 4, 4)
        clip_layout.setSpacing(2)
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
        # All sub-widgets route to the same drag handlers
        identifier.mousePressEvent = lambda e: self._drag_press(track, e)
        identifier.mouseMoveEvent = lambda e: self._drag_move(track, e)
        identifier.mouseReleaseEvent = lambda e: self._drag_release(track, e)
        
        track_widget.mousePressEvent = lambda e: self._drag_press(track, e)
        track_widget.mouseMoveEvent = lambda e: self._drag_move(track, e)
        track_widget.mouseReleaseEvent = lambda e: self._drag_release(track, e)
        
        clip_container.mousePressEvent = lambda e: self._drag_press(track, e)
        clip_container.mouseMoveEvent = lambda e: self._drag_move(track, e)
        clip_container.mouseReleaseEvent = lambda e: self._drag_release(track, e)
        
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
        elif action == delete_act:
            self.clip_context_action.emit("delete", clip_data)
        elif action == seek_act:
            start = float(clip_data.get("start_time", 0))
            self.set_playhead_position(start)
    
    def _on_track_mute(self, track, checked):
        """ """
        track['muted'] = checked
        opacity = 0.3 if checked else 1.0
        for i in range(track['content_layout'].count()):
            widget = track['content_layout'].itemAt(i).widget()
            if isinstance(widget, ClipWidget):
                widget.setGraphicsEffect(None)
                if checked:
                    from PyQt6.QtWidgets import QGraphicsOpacityEffect
                    eff = QGraphicsOpacityEffect()
                    eff.setOpacity(opacity)
                    widget.setGraphicsEffect(eff)
    
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

    def _on_track_collapse(self, track, collapsed):
        """轨道折叠/展开"""
        if track is None:
            return
        track['collapsed'] = collapsed
        if collapsed:
            track['clip_container'].setVisible(False)
            track['widget'].setFixedHeight(8)
            track['identifier'].setFixedHeight(8)
        else:
            track['clip_container'].setVisible(True)
            track['widget'].setFixedHeight(48)
            track['identifier'].setFixedHeight(48)
        self._update_track_min_width()
        if self._selected_track == track:
            self._update_ctrl_panel_position()
    
    def _rename_track(self, track):
        """ """
        from PyQt6.QtWidgets import QInputDialog
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
        # Copy clips from original track
        for i in range(track['content_layout'].count()):
            widget = track['content_layout'].itemAt(i).widget()
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
    
    def add_clip(self, clip_data, track_index=0):
        """按 start_time 绝对定位添加到指定轨道。"""
        if track_index < 0 or track_index >= len(self._tracks):
            track_index = 0

        track = self._tracks[track_index]
        container = track["clip_container"]
        clip_widget = ClipWidget(clip_data, container)
        clip_widget.clicked.connect(self._on_clip_clicked)
        clip_widget.keyframe_clicked.connect(self.clip_keyframe_clicked.emit)
        clip_widget.trim_committed.connect(self.clip_trim_committed.emit)

        clip_data["track"] = track_index
        if clip_data not in self._clips:
            self._clips.append(clip_data)
        self.position_clip_widget(clip_widget)
        return clip_widget

    def remove_clip_widget_by_id(self, clip_id) -> bool:
        for track in self._tracks:
            for w in list(self.iter_track_clip_widgets(track)):
                if w.clip_data.get("id") == clip_id:
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
        clip_widget.clip_data["track"] = track_index
        self.position_clip_widget(clip_widget)
    
    def _on_clip_clicked(self, clip_data):
        """ """
        if self._current_clip:
            for w in self.all_clip_widgets():
                if w.clip_data.get("id") == self._current_clip.get("id"):
                    w.set_selected(False)
        self._current_clip = clip_data
        for w in self.all_clip_widgets():
            if w.clip_data.get("id") == clip_data.get("id"):
                w.set_selected(True)
                break
        self.clip_selected.emit(clip_data)
    
    def set_zoom(self, zoom):
        """ """
        self._zoom = max(10, min(500, zoom))
        self._update_time_ruler()
        self._update_track_min_width()
        self._marker_layer.set_zoom(self._zoom)
        self.relayout_clips()
    
    def _update_track_min_width(self):
        """ """
        px_per_sec = 20 * (self._zoom / 100)
        min_width = int(self._total_duration * px_per_sec + 120)
        track_count = max(3, len(self._tracks))
        min_height = track_count * 48 + 20
        self._track_viewport.setMinimumSize(min_width, min_height)
        # 更新标记层最小宽度
        self._marker_layer.setMinimumWidth(min_width)
        self._marker_layer.set_total_duration(self._total_duration)
    
    def set_playhead_position(self, position):
        """ """
        self._playhead_pos = position
        # 更新时间标尺中的播放头
        self._time_ruler.set_playhead(position)
        # 更新轨道区域中的播放头（viewport 内）
        scale_factor = self._zoom / 100
        playhead_x = 100 + int(position * 20 * scale_factor)
        self._track_playhead.move(playhead_x, 0)
        self._track_playhead.setFixedHeight(self._track_viewport.height())
        self._track_playhead.setStyleSheet("background-color: #ff4757; width: 2px;")
        self.playhead_moved.emit(position)
    
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


class ClipWidget(QFrame):
    """ """

    clicked = pyqtSignal(object)
    resized = pyqtSignal(object)
    moved = pyqtSignal(object)
    keyframe_clicked = pyqtSignal(object, dict)  # (clip_data, keyframe)
    trim_committed = pyqtSignal(object)  # 拖拽/裁剪松手后发出

    # 补短 P1#8：关键帧可视化 - 属性->颜色 映射
    KEYFRAME_COLORS = {
        'position_x': '#00d4ff', 'position_y': '#00d4ff',
        'scale_x': '#ff9500', 'scale_y': '#ff9500',
        'rotation': '#9c27b0',
        'opacity': '#ffffff',
        'volume': '#4caf50',
        'speed': '#f44336',
        'brightness': '#ffeb3b', 'contrast': '#ffeb3b',
        'saturation': '#ffeb3b', 'hue': '#ffeb3b',
        'blur': '#9e9e9e', 'vignette': '#9e9e9e', 'sharpen': '#9e9e9e',
        'crop_top': '#795548', 'crop_bottom': '#795548',
        'crop_left': '#795548', 'crop_right': '#795548',
    }

    def __init__(self, clip_data, parent=None):
        super().__init__(parent)
        _report_timeline_widget_debug(
            "B",
            "timeline_widget.ClipWidget.__init__",
            "clip widget init",
            {
                "module_has_os": "os" in globals(),
                "clip_path": clip_data.get("path") if isinstance(clip_data, dict) else None,
                "clip_keys": list(clip_data.keys()) if isinstance(clip_data, dict) else None,
            },
        )
        self.clip_data = clip_data
        self._is_selected = False
        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None
        self._resize_snapshot = None
        self._did_edit_drag = False

        # 补短 P1#8：关键帧数据 - 数据契约见 _get_keyframes()/set_keyframes()
        # 期望格式（clip_data['keyframes'] 或显式调用 set_keyframes 传入）：
        #   [
        #     {"time_offset": 1.2, "value": 0.5, "prop": "opacity", "easing": "linear"},
        #     ...
        #   ]
        # 没有数据时不做任何绘制 - 完全不影响现有 clip 外观
        self._keyframes = self._coerce_keyframes(clip_data.get('keyframes'))
        self._kf_hit_radius = 7  # 命中半径（px），与绘制点尺寸匹配

        # 缩略图和波形缓存
        self._thumbnail_cache = []
        self._waveform_peaks = None
        self._thumbnails_generated = False

        self.setFixedHeight(38)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        
        # 异步调度缩略图生成
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self._schedule_thumbnail_generation)
        self.setStyleSheet("""
            QFrame {
                background-color: #1e6bde;
                border-radius: 3px;
                border: none;
            }
            QFrame:hover {
                background-color: #2575e0;
            }
            QFrame[selected="true"] {
                border: 1.5px solid #ff4757;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        # 片段名称（省略号处理）
        clip_text = os.path.basename(clip_data.get('path', '未命名'))
        clip_name = QLabel()
        clip_name.setStyleSheet("color: #eee; font-size: 10px; background:transparent; border:none;")
        clip_name.setMaximumWidth(100)
        clip_name.setText(QFontMetrics(clip_name.font()).elidedText(clip_text, Qt.TextElideMode.ElideRight, 100))
        layout.addWidget(clip_name)

        layout.addStretch()

        # 时长标签
        dur = clip_data.get('duration', 0)
        dur_lbl = QLabel(f"{dur:.1f}s" if dur < 60 else f"{int(dur//60)}:{int(dur%60):02d}")
        dur_lbl.setStyleSheet("color: #bcd4f5; font-size: 9px; background:transparent; border:none;")
        layout.addWidget(dur_lbl)

    # ------------------------------------------------------------------
    # 补短 P1#8：关键帧数据接入（最小侵入 - 不影响无关键帧的 clip）
    # ------------------------------------------------------------------
    @staticmethod
    def _coerce_keyframes(raw):
        """
        规整关键帧数据：
          - 接受 None / 缺失 / 非 list 都返回空列表
          - 过滤掉缺 time_offset 的项
        """
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
        # 按时间排序，方便绘制与命中
        out.sort(key=lambda x: x['time_offset'])
        return out

    def set_keyframes(self, keyframes):
        """
        公开 API：更新关键帧数据并触发重绘。

        用法：
            clip_widget.set_keyframes([
                {"time_offset": 1.2, "value": 0.5, "prop": "opacity"},
            ])
        """
        self._keyframes = self._coerce_keyframes(keyframes)
        # 同步回 clip_data，保证序列化和撤销栈一致
        self.clip_data['keyframes'] = [
            {**kf, 'time_offset': kf['time_offset']} for kf in self._keyframes
        ]
        self.update()  # 触发 paintEvent

    def get_keyframes(self):
        """返回当前关键帧数据副本（防止外部误改内部状态）"""
        return [dict(kf) for kf in self._keyframes]

    def _color_for_prop(self, prop_name):
        return self.KEYFRAME_COLORS.get(prop_name, '#ffffff')

    def _time_to_x(self, time_offset):
        """关键帧时间偏移 -> clip 内 x 坐标（与 TimelineWidget 的 px_per_sec 算法保持一致）"""
        try:
            scale_factor = self.parent()._zoom / 100
        except (AttributeError, TypeError):
            scale_factor = 1.0
        return int(time_offset * 20 * scale_factor)

    def _keyframe_rects(self):
        """
        返回所有关键帧点的 (x, y_center, color, kf_dict)，
        x 会被裁剪到 [2, width-2]，保证不出 clip 边界。
        """
        rects = []
        w = self.width()
        h = self.height()
        # 关键帧点固定画在底部 6px 高的条带上（不与顶部 QLabel 文字冲突）
        band_top = h - 7
        y_center = band_top + 3
        for kf in self._keyframes:
            x = self._time_to_x(kf['time_offset'])
            if x < 2:
                x = 2
            elif x > w - 2:
                x = w - 2
            rects.append((x, y_center, self._color_for_prop(kf['prop']), kf))
        return rects

    def paintEvent(self, event):
        """
        补短 P1#8：在 QFrame 原样式（stylesheet 背景）之上叠加关键帧菱形点。

        关键设计：
          1. 先 super().paintEvent() 让 QFrame 走自己的 stylesheet，保持原样
          2. 再用 QPainter 叠加绘制 - 不修改 QSS、不增加子控件
          3. 无关键帧时直接走 super().paintEvent，零开销零影响
          4. 选中态点稍大、描边亮；非选中态点 5x5、描边半透明
          5. 视频片段显示缩略图预览条，音频片段显示波形可视化
        """
        super().paintEvent(event)
        
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            
            # 根据文件扩展名判断片段类型
            clip_path = self.clip_data.get('path', '') or self.clip_data.get('name', '')
            is_audio = clip_path and any(clip_path.lower().endswith(ext) for ext in ('.mp3', '.wav', '.aac', '.ogg', '.flac', '.m4a', '.wma'))
            
            # ── 视频片段缩略图条 ──
            if not is_audio and self.width() > 60:
                thumb_height = 8
                thumb_y = self.height() - thumb_height - 2
                segments = max(3, self.width() // 12)
                
                if self._thumbnail_cache and len(self._thumbnail_cache) >= segments:
                    for i in range(segments):
                        x = 2 + i * 12
                        pixmap = self._thumbnail_cache[i % len(self._thumbnail_cache)]
                        if pixmap:
                            scaled_pixmap = pixmap.scaled(10, thumb_height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                            painter.drawPixmap(x, thumb_y, scaled_pixmap)
                        else:
                            colors = [QColor(30, 107, 222, 180), QColor(37, 117, 224, 160), QColor(25, 97, 220, 140)]
                            painter.fillRect(x, thumb_y, 10, thumb_height, colors[i % 3])
                else:
                    colors = [
                        QColor(30, 107, 222, 180),
                        QColor(37, 117, 224, 160),
                        QColor(25, 97, 220, 140)
                    ]
                    for i in range(segments):
                        x = 2 + i * 12
                        c = colors[i % 3]
                        painter.fillRect(x, thumb_y, 10, thumb_height, c)
            
            # ── 音频片段波形可视化 ──
            if is_audio:
                wave_height = 14
                bar_count = max(4, self.width() // 6)
                bar_width = max(2, (self.width() - 4) // bar_count - 2)
                
                # 尝试获取真实波形数据
                peaks = None
                if not hasattr(self, '_waveform_peaks') or self._waveform_peaks is None:
                    try:
                        from app.core.waveform_generator import waveform_generator
                        data = waveform_generator.generate(clip_path, num_samples=bar_count)
                        if data and data.peaks:
                            self._waveform_peaks = data.peaks
                        else:
                            self._waveform_peaks = []
                    except Exception:
                        self._waveform_peaks = []
                
                if self._waveform_peaks and len(self._waveform_peaks) >= bar_count:
                    peaks = self._waveform_peaks
                else:
                    peaks = None
                
                if peaks:
                    for i in range(bar_count):
                        x = 2 + i * (bar_width + 2)
                        peak_val = peaks[i % len(peaks)] if peaks else 0.5
                        h = max(2, int(peak_val * wave_height))
                        c = QColor(76, 175, 80, 160 + i * 3 % 90)
                        painter.fillRect(x, self.height() // 2 - h // 2, bar_width, h, c)
                else:
                    import random
                    random.seed(hash(clip_path) % 10000)
                    for i in range(bar_count):
                        x = 2 + i * (bar_width + 2)
                        h = random.randint(4, wave_height)
                        c = QColor(76, 175, 80, 160 + i * 3 % 90)
                        painter.fillRect(x, self.height() // 2 - h // 2, bar_width, h, c)
                    random.seed()
            
            # ── 关键帧绘制 ──
            if not self._keyframes:
                painter.end()
                return

            # 选中时画一层底部高亮带（提示用户该 clip 有动画）
            if self._is_selected and self._keyframes:
                band_color = QColor(0, 0, 0, 60)
                painter.fillRect(0, self.height() - 7, self.width(), 7, band_color)

            size = 5 if self._is_selected else 4
            for x, y, color_hex, _kf in self._keyframe_rects():
                color = QColor(color_hex)
                # 填充菱形
                if self._is_selected:
                    painter.setBrush(QBrush(color))
                    painter.setPen(QPen(QColor(255, 255, 255), 1.2))
                else:
                    # 非选中：半透明 + 深色描边
                    fill = QColor(color)
                    fill.setAlpha(200)
                    painter.setBrush(QBrush(fill))
                    painter.setPen(QPen(QColor(0, 0, 0, 180), 1))

                # 菱形（4 个顶点） - 用 QPolygon 即可
                half = size
                poly = QPolygon([
                    QPoint(x, y - half),
                    QPoint(x + half, y),
                    QPoint(x, y + half),
                    QPoint(x - half, y),
                ])
                painter.drawPolygon(poly)
        finally:
            painter.end()

    def _hit_test_keyframe(self, pos):
        """
        鼠标位置命中关键帧点测试。命中返回 kf dict，否则返回 None。
        使用曼哈顿距离（菱形近似），半径 = self._kf_hit_radius。
        """
        for x, y, _color, kf in self._keyframe_rects():
            if abs(pos.x() - x) + abs(pos.y() - y) <= self._kf_hit_radius:
                return kf
        return None
        
    def _find_timeline_widget(self):
        w = self.parent()
        while w is not None:
            if isinstance(w, TimelineWidget):
                return w
            w = w.parent()
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            timeline = self._find_timeline_widget()
            if timeline is not None:
                timeline.show_clip_context_menu(
                    self.clip_data,
                    event.globalPosition().toPoint(),
                )
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self._drag_offset = self.pos()
            try:
                import copy
                self._edit_before = copy.deepcopy({
                    "id": self.clip_data.get("id"),
                    "start_time": float(self.clip_data.get("start_time", 0) or 0),
                    "duration": float(self.clip_data.get("duration", 0) or 0),
                    "in_point": float(self.clip_data.get("in_point", 0) or 0),
                    "out_point": float(self.clip_data.get("out_point", 0) or 0),
                    "track": int(self.clip_data.get("track", 0) or 0),
                })
            except Exception:
                self._edit_before = None
            # 检查是否点击在边缘(调整大小)
            if event.pos().x() < 10:
                self._is_resizing = True
                self._resize_direction = 'left'
                self._resize_snapshot = {
                    "duration": float(self.clip_data.get("duration", 0) or 0),
                    "in_point": float(self.clip_data.get("in_point", 0) or 0),
                    "out_point": float(self.clip_data.get("out_point", 0) or 0),
                    "start_time": float(self.clip_data.get("start_time", 0) or 0),
                    "direction": "left",
                }
            elif event.pos().x() > self.width() - 10:
                self._is_resizing = True
                self._resize_direction = 'right'
                self._resize_snapshot = {
                    "duration": float(self.clip_data.get("duration", 0) or 0),
                    "in_point": float(self.clip_data.get("in_point", 0) or 0),
                    "out_point": float(self.clip_data.get("out_point", 0) or 0),
                    "start_time": float(self.clip_data.get("start_time", 0) or 0),
                    "direction": "right",
                }
            else:
                # 补短 P1#8：若点击命中关键帧点，发 keyframe_clicked 而非切换选中
                # 这样不打断用户的"先看 clip 再细看关键帧"的操作流
                kf_hit = self._hit_test_keyframe(event.pos())
                if kf_hit is not None:
                    self.keyframe_clicked.emit(self.clip_data, kf_hit)
                    # 不进入选中/拖拽流程，但仍消费事件
                    super().mousePressEvent(event)
                    return

                self._is_resizing = False
                # 切换选择状态
                self._is_selected = not self._is_selected
                self.setProperty('selected', str(self._is_selected).lower())
                self.style().unpolish(self)
                self.style().polish(self)
                # 补短 P1#8：选中态变化需触发 paintEvent 重新画关键帧大小
                self.update()
                self.clicked.emit(self.clip_data)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 补短 P1#8：未在拖拽/调整大小时，命中关键帧点 -> 显示 tooltip
        if not self._is_resizing and not (self._drag_start_pos and self._drag_offset):
            kf_hit = self._hit_test_keyframe(event.pos())
            if kf_hit is not None:
                tip = self._format_keyframe_tooltip(kf_hit)
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                QToolTip.hideText()
                # 不强制重置 cursor，避免和 track 拖拽的 cursor 冲突
            # tooltip 处理完直接返回，不影响原有拖拽/调整大小逻辑
            return

        if self._is_resizing:
            # 调整大小逻辑
            self._did_edit_drag = True
            timeline = self._find_timeline_widget()
            zoom = getattr(timeline, "_zoom", 100) if timeline else 100
            scale_factor = zoom / 100
            delta = event.pos().x() - self._drag_start_pos.x()
            if self._resize_direction == 'right':
                new_width = max(40, self.width() + delta)
                self.setFixedWidth(new_width)
                if 'duration' in self.clip_data:
                    self.clip_data['duration'] = new_width / (20 * scale_factor)
                    self.resized.emit(self.clip_data)
            elif self._resize_direction == 'left':
                new_width = max(40, self.width() - delta)
                new_x = self.x() + delta
                if new_x >= 0:
                    self.setFixedWidth(new_width)
                    self.move(new_x, self.y())
                    if 'start_time' in self.clip_data and 'duration' in self.clip_data:
                        self.clip_data['start_time'] += delta / (20 * scale_factor)
                        self.clip_data['duration'] = new_width / (20 * scale_factor)
                        self.resized.emit(self.clip_data)
        elif self._drag_start_pos and self._drag_offset:
            # 拖拽：允许跨轨（Y），X 映射 start_time
            self._did_edit_drag = True
            timeline = self._find_timeline_widget()
            parent = self.parent()
            new_pos = self.mapToParent(event.pos()) - self._drag_start_pos + self._drag_offset
            if new_pos.x() < 0:
                new_pos.setX(0)
            # 跨轨：跟随鼠标全局 Y 落到其它轨道容器
            if timeline is not None:
                gy = event.globalPosition().toPoint().y()
                ti = timeline.track_index_at_global_y(gy)
                track = timeline._tracks[ti] if 0 <= ti < len(timeline._tracks) else None
                if track and parent is not track.get("clip_container"):
                    self.setParent(track["clip_container"])
                    self.clip_data["track"] = ti
                    parent = track["clip_container"]
                    self.show()
            self.move(max(0, new_pos.x()), 4)
            if 'start_time' in self.clip_data and timeline is not None:
                px = timeline.px_per_sec()
                self.clip_data['start_time'] = max(0.0, self.x() / px) if px > 0 else 0.0
                self.moved.emit(self.clip_data)

    def mouseReleaseEvent(self, event):
        # 松手时按最终宽度规范化 in/out，保证导出与预览一致
        if self._did_edit_drag:
            try:
                timeline = self._find_timeline_widget()
                zoom = getattr(timeline, "_zoom", 100) if timeline is not None else 100
                scale = max(0.01, float(zoom) / 100.0)
                px = 20.0 * scale
                dur = max(0.05, self.width() / px)
                snap = self._resize_snapshot
                if snap and snap.get("direction") == "right":
                    in_p = float(self.clip_data.get("in_point", snap.get("in_point", 0)) or 0)
                    self.clip_data["duration"] = dur
                    self.clip_data["out_point"] = in_p + dur
                elif snap and snap.get("direction") == "left":
                    end = float(snap["start_time"]) + float(snap["duration"])
                    self.clip_data["duration"] = dur
                    self.clip_data["start_time"] = max(0.0, end - dur)
                    dt = float(snap["duration"]) - dur
                    self.clip_data["in_point"] = max(0.0, float(snap["in_point"]) + dt)
                    self.clip_data["out_point"] = float(self.clip_data["in_point"]) + dur
                else:
                    # 纯平移：吸附播放头 / 邻片
                    st = float(self.clip_data.get("start_time", 0) or 0)
                    if timeline is not None:
                        st = timeline.snap_start_time(
                            self.clip_data, st, exclude_id=self.clip_data.get("id"))
                        self.clip_data["start_time"] = st
                        timeline.position_clip_widget(self)
                # 附带 before 供撤销
                payload = self.clip_data
                if getattr(self, "_edit_before", None):
                    payload = dict(self.clip_data)
                    payload["_edit_before"] = self._edit_before
                self.trim_committed.emit(payload)
            except Exception as e:
                print(f"clip trim commit failed: {e}")

        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None
        self._resize_snapshot = None
        self._did_edit_drag = False
        self._edit_before = None
        super().mouseReleaseEvent(event)

    def set_selected(self, selected):
        self._is_selected = selected
        self.setProperty('selected', str(selected).lower())
        self.style().unpolish(self)
        self.style().polish(self)
        # 补短 P1#8：选中态变化需重绘关键帧
        self.update()

    # ------------------------------------------------------------------
    # 补短 P1#8：内部辅助
    # ------------------------------------------------------------------
    def _format_keyframe_tooltip(self, kf):
        """关键帧 tooltip 文案：属性 @ 时间 = 值 (缓动)"""
        try:
            value = kf.get('value', 0.0)
            value_str = f"{float(value):.3f}".rstrip('0').rstrip('.')
        except Exception:
            value_str = str(value)
        t = kf.get('time_offset', 0.0)
        return (
            f"◆ {kf.get('prop', 'value')}\n"
            f"  @ {t:.2f}s = {value_str}\n"
            f"  easing: {kf.get('easing', 'linear')}"
        )

    def _schedule_thumbnail_generation(self):
        """调度异步缩略图生成"""
        clip_path = self.clip_data.get('path', '')
        if not clip_path or not os.path.exists(clip_path):
            self._thumbnails_generated = True
            return
        
        # 检查是否是视频文件
        ext = os.path.splitext(clip_path)[1].lower()
        if ext in ('.mp3', '.wav', '.aac', '.ogg', '.flac', '.m4a', '.wma'):
            self._thumbnails_generated = True
            return
        
        # 使用线程池异步生成缩略图
        from PyQt6.QtCore import QThread, pyqtSignal
        
        class ThumbnailWorker(QThread):
            thumbnails_ready = pyqtSignal(list)
            
            def __init__(self, clip_path, duration, num_thumbnails):
                super().__init__()
                self._clip_path = clip_path
                self._duration = duration
                self._num_thumbnails = num_thumbnails
            
            def run(self):
                try:
                    from app.core.ffmpeg_service import ffmpeg_service
                    thumbnails = []
                    for i in range(self._num_thumbnails):
                        timestamp = (i / self._num_thumbnails) * self._duration
                        pixmap = ffmpeg_service.extract_frame(self._clip_path, timestamp, width=60, height=36)
                        thumbnails.append(pixmap)
                    self.thumbnails_ready.emit(thumbnails)
                except Exception:
                    self.thumbnails_ready.emit([])
        
        duration = self.clip_data.get('duration', 10.0)
        num_thumbnails = max(3, self.width() // 12) if self.width() > 60 else 3
        
        self._thumbnail_worker = ThumbnailWorker(clip_path, duration, num_thumbnails)
        self._thumbnail_worker.thumbnails_ready.connect(self._on_thumbnails_ready)
        self._thumbnail_worker.finished.connect(self._thumbnail_worker.deleteLater)
        self._thumbnail_worker.start()
    
    def _on_thumbnails_ready(self, thumbnails):
        """缩略图生成完成回调"""
        self._thumbnail_cache = thumbnails
        self._thumbnails_generated = True
        self.update()


