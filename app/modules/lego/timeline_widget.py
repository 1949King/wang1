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
import threading
import time
import urllib.request
import weakref

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QUrl, QPoint, QRect, QMimeData
from PyQt6.QtGui import (
    QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics,
    QPolygon, QShortcut, QKeySequence, QDrag, QPixmap, QImage,
)
from PyQt6.QtWidgets import (
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
    paint_marquee_overlay,
    pick_snap as _pick_snap,
    rect_from_points,
    snap_edge_candidates as _snap_edge_candidates,
    CLIP_DRAG_THRESHOLD_PX,
    MARQUEE_DRAG_THRESHOLD_PX,
)

logger = logging.getLogger("AI短剧编辑器.timeline_widget")

AUDIO_EXTS = ('.mp3', '.wav', '.aac', '.ogg', '.flac', '.m4a', '.wma')


class _MediaWorkerGate:
    """全局限流：胶片条/波形 QThread 并发不超上限，避免批量可见时线程风暴（磁盘/CPU 抖动）。

    owner 用弱引用登记；owner 已销毁的排队项会被跳过或在 cancel_owner 时清掉。
    """

    def __init__(self, max_concurrent: int = 3):
        self._max = max_concurrent
        self._active = 0
        self._queue = []  # list[tuple[weakref.ref, callable]]
        self._lock = threading.Lock()

    def request(self, owner, start_fn):
        with self._lock:
            if self._active < self._max:
                self._active += 1
                do_start = True
            else:
                self._queue.append((weakref.ref(owner), start_fn))
                do_start = False
        if do_start:
            self._run_start(start_fn)

    def _run_start(self, start_fn):
        try:
            start_fn()
        except Exception:
            logger.debug("媒体 worker 启动失败", exc_info=True)
            self.release()

    def release(self):
        next_fn = None
        with self._lock:
            self._active = max(0, self._active - 1)
            while self._queue:
                ref, fn = self._queue.pop(0)
                if ref() is None:
                    continue
                self._active += 1
                next_fn = fn
                break
        if next_fn is not None:
            self._run_start(next_fn)

    def cancel_owner(self, owner):
        with self._lock:
            self._queue = [
                (ref, fn) for (ref, fn) in self._queue
                if ref() is not None and ref() is not owner
            ]


_media_worker_gate = _MediaWorkerGate(max_concurrent=3)


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

# 时间线精细编辑常量
_TIMELINE_ZOOM_MIN = 10
_TIMELINE_ZOOM_MAX = 3000  # 3000% → ~600px/s，30fps 约 20px/帧
_TIMELINE_BASE_PPS = 20.0  # zoom=100 时的像素/秒
_TIMELINE_SNAP_PX = 8      # 吸附按像素换算秒，放大后更精细
_TIMELINE_MIN_CLIP_PX = 6  # 最短可视宽度（勿再用 40，默认缩放下会锁死 ~2s）
_DEFAULT_FPS = 30.0


def _clamp_timeline_zoom(zoom) -> int:
    try:
        z = int(round(float(zoom)))
    except (TypeError, ValueError):
        z = 100
    return max(_TIMELINE_ZOOM_MIN, min(_TIMELINE_ZOOM_MAX, z))



def _timeline_pps(zoom) -> float:
    return _TIMELINE_BASE_PPS * (float(_clamp_timeline_zoom(zoom)) / 100.0)


def _quantize_time(t: float, frame_dur: float) -> float:
    fd = max(1e-6, float(frame_dur))
    return max(0.0, round(float(t) / fd) * fd)


def _ndarray_bgr_to_pixmap(frame_bgr, target_h: int = 0) -> "QPixmap | None":
    """OpenCV BGR → QPixmap；可选按高度等比缩小。"""
    try:
        import cv2
        import numpy as np
        if frame_bgr is None or not hasattr(frame_bgr, "shape"):
            return None
        h, w = frame_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return None
        if target_h and target_h > 0 and h != target_h:
            scale = float(target_h) / float(h)
            nw = max(2, int(round(w * scale)))
            nh = max(2, int(target_h))
            nw -= nw % 2
            nh -= nh % 2
            frame_bgr = cv2.resize(frame_bgr, (nw, nh), interpolation=cv2.INTER_AREA)
            h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if not rgb.flags["C_CONTIGUOUS"]:
            rgb = np.ascontiguousarray(rgb)
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        if qimg.isNull():
            return None
        return QPixmap.fromImage(qimg)
    except Exception as e:
        logger.debug("BGR→QPixmap 失败: %s", e)
        return None


def _extract_filmstrip_frames(path, timestamps, height, is_interrupted=None):
    """单次打开视频，按时间戳批量抽帧（剪映式胶片条）。

    优先 OpenCV；失败再逐帧回退 ffmpeg_service.extract_frame。
    返回 (list[QPixmap], aspect_ratio)。
    """
    thumbs = []
    aspect = 0.0
    ts_list = [max(0.0, float(t)) for t in (timestamps or [])]
    if not path or not ts_list:
        return thumbs, aspect
    h = max(16, int(height or 96))
    interrupt = is_interrupted or (lambda: False)

    # ── OpenCV 批量 ──
    try:
        import cv2
        cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
        if cap is not None and cap.isOpened():
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 30.0
            vw = float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            vh = float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if vw > 0 and vh > 0:
                aspect = vw / vh
            # 按时间排序抽，减少乱序 seek 代价；再按原序还原
            order = sorted(range(len(ts_list)), key=lambda i: ts_list[i])
            tmp = [None] * len(ts_list)
            for oi in order:
                if interrupt():
                    cap.release()
                    return [], aspect
                t = ts_list[oi]
                frame_idx = int(round(t * fps))
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_idx))
                ok, frame = cap.read()
                if not ok or frame is None:
                    # msec 再试一次
                    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                    ok, frame = cap.read()
                if ok and frame is not None:
                    pm = _ndarray_bgr_to_pixmap(frame, target_h=h)
                    if pm is not None and not pm.isNull():
                        tmp[oi] = pm
                        if aspect <= 0 and pm.height() > 0:
                            aspect = float(pm.width()) / float(pm.height())
            cap.release()
            thumbs = [pm for pm in tmp if pm is not None]
            if thumbs:
                return thumbs, aspect
    except Exception as e:
        logger.debug("OpenCV 胶片条抽帧失败，回退 ffmpeg: %s", e)

    # ── ffmpeg 批量回退 ──
    try:
        from app.core.ffmpeg_service import ffmpeg_service
        if interrupt():
            return [], aspect
        batch = ffmpeg_service.extract_frames_batch(path, ts_list, height=h, width=0)
        for pm in batch or []:
            if pm is not None and not pm.isNull():
                thumbs.append(pm)
                if aspect <= 0 and pm.height() > 0:
                    aspect = float(pm.width()) / float(pm.height())
    except Exception as e:
        logger.debug("ffmpeg 胶片条回退失败: %s", e)
    return thumbs, aspect




class TimeRuler(QWidget):
    """时间标尺"""

    clicked = pyqtSignal(float)  # 点击位置（秒）
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._zoom = 100
        self._total_duration = 60
        self._playhead_pos = 0
        self._left_margin = 100  # 左侧轨道控制区宽度
        self._load_spans = []  # [(start, end), ...] 高负载红线
        self._in_point = None
        self._out_point = None
        self.setFixedHeight(45)
        self.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
    
    def set_zoom(self, zoom):
        self._zoom = _clamp_timeline_zoom(zoom)
        self.update()
    
    def set_playhead(self, pos):
        self._playhead_pos = pos
        self.update()

    def set_load_spans(self, spans):
        self._load_spans = list(spans or [])
        self.update()

    def set_in_out(self, in_point, out_point):
        self._in_point = in_point
        self._out_point = out_point
        self.update()
    
    def _px_per_second(self):
        """ """
        return _timeline_pps(self._zoom)
    
    def _time_to_x(self, t):
        """ """
        return self._left_margin + int(t * self._px_per_second())
    
    def _x_to_time(self, x):
        """ """
        return max(0, (x - self._left_margin) / self._px_per_second())
    
    def _format_time_label(self, t):
        """ """
        if t < 0.001:
            return "0"
        if t < 1:
            ms = t * 1000
            return f"{ms:.0f}ms" if ms >= 10 else f"{ms:.1f}ms"
        elif t < 60:
            return f"{t:g}s"
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

        # 入出点区间高亮（半透明蓝）
        try:
            tin = self._in_point
            tout = self._out_point
            if tin is not None and tout is not None and float(tout) > float(tin):
                x0 = max(self._left_margin, self._time_to_x(float(tin)))
                x1 = min(width, self._time_to_x(float(tout)))
                if x1 > x0:
                    painter.fillRect(x0, 0, x1 - x0, rect.height(), QColor(30, 107, 222, 40))
            for t, color in ((tin, QColor("#4fc3f7")), (tout, QColor("#ffb74d"))):
                if t is None:
                    continue
                x = self._time_to_x(float(t))
                if self._left_margin <= x <= width:
                    painter.setPen(QPen(color, 2))
                    painter.drawLine(x, 0, x, rect.height())
        except Exception:
            pass

        # 高负载区红线（底边 3px，对标达芬奇「未缓存」提示的轻量版）
        try:
            for span in self._load_spans or []:
                if not span or len(span) < 2:
                    continue
                x0 = max(self._left_margin, self._time_to_x(float(span[0])))
                x1 = min(width, self._time_to_x(float(span[1])))
                if x1 > x0:
                    painter.fillRect(x0, rect.height() - 3, x1 - x0, 3, QColor(229, 57, 53, 200))
        except Exception:
            pass
        
        # 根据 pps 自动选择刻度间隔（含帧级，便于精细剪辑）
        candidates = [
            1 / 60, 1 / 30, 1 / 15, 1 / 10, 0.1, 0.2, 0.5,
            1, 2, 5, 10, 15, 30, 60,
        ]
        major_step = 1.0
        minor_step = 0.5
        for c in candidates:
            pixel_dist = c * pps
            if 40 <= pixel_dist <= 220:
                major_step = c
                minor_step = c / (5.0 if c >= 0.5 else 2.0)
                break
        else:
            # 极端放大：主刻度至少 1 帧宽
            major_step = max(1 / 60, 50.0 / max(pps, 1e-6))
            minor_step = major_step / 2.0
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

    def mouseMoveEvent(self, event):
        """拖动标尺精细 scrub"""
        if event.buttons() & Qt.MouseButton.LeftButton:
            t = self._x_to_time(event.pos().x())
            self.clicked.emit(t)


class TimelineMarkerLayer(QWidget):
    """时间轴标记层 - 叠加显示高光区域和线性补帧节点"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlights = []
        self._interpolation_markers = []
        self._agent_feedback_markers = []   # P1-C: Agent 反馈标记
        self._zoom = 100
        self._total_duration = 600
        self._left_margin = 100
        self._hovered_marker = None
        self._hovered_highlight = None
        self._hovered_agent_marker = None   # P1-C: hover 的 Agent 标记
        self.setMouseTracking(True)
        self._connect_manager()

    def _connect_manager(self):
        """连接高光预览管理器 + EventBus（P1-C: Agent 反馈标记）"""
        try:
            from app.core.highlight_preview import highlight_preview_manager
            highlight_preview_manager.highlights_updated.connect(self.set_highlights)
            highlight_preview_manager.interpolation_markers_updated.connect(self.set_interpolation_markers)
        except Exception as e:
            logger.debug("连接高光预览管理器失败: %s", e)
        # P1-C: 连接 EventBus 接收 Agent 反馈标记
        try:
            from app.modules.lego.core import EventBus, EventType
            bus = EventBus.get_instance()
            bus.subscribe(EventType.AGENT_MARKERS_UPDATED, self._on_agent_markers_updated)
        except Exception as e:
            logger.debug("连接 EventBus Agent 标记失败: %s", e)

    def set_highlights(self, highlights):
        """设置高光片段列表"""
        self._highlights = highlights
        self.update()

    def set_interpolation_markers(self, markers):
        """设置线性补帧节点列表"""
        self._interpolation_markers = markers
        self.update()

    # ── P1-C: Agent 反馈标记 ──

    def set_agent_feedback_markers(self, markers: list):
        """整体替换 Agent 反馈标记列表（EventBus 回调入口）。"""
        self._agent_feedback_markers = list(markers or [])
        self.update()

    def add_agent_feedback_marker(self, marker: dict):
        """追加单个 Agent 反馈标记。"""
        self._agent_feedback_markers.append(marker)
        self.update()

    def clear_agent_feedback_markers(self):
        """清空所有 Agent 反馈标记。"""
        self._agent_feedback_markers = []
        self.update()

    def _on_agent_markers_updated(self, event):
        """EventBus: AGENT_MARKERS_UPDATED 事件回调。"""
        try:
            markers = event.data.get("markers", []) if event else []
            self.set_agent_feedback_markers(markers)
        except Exception as e:
            logger.debug("TimelineMarkerLayer._on_agent_markers_updated 失败: %s", e)

    def set_zoom(self, zoom):
        """设置缩放比例"""
        self._zoom = _clamp_timeline_zoom(zoom)
        self.update()

    def set_total_duration(self, duration):
        """设置总时长"""
        self._total_duration = duration
        self.update()

    def _px_per_second(self):
        """计算每秒钟的像素数"""
        return _timeline_pps(self._zoom)

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

        # 绘制线性补帧节点
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

        # P1-C: 绘制 Agent 反馈标记（绿色圆点=success / 红色三角=failed）
        for marker in self._agent_feedback_markers:
            try:
                t = float(marker.get("time", 0))
                x = self._time_to_x(t)
                if x < self._left_margin or x >= width:
                    continue
                status = marker.get("status", "success")
                is_hovered = self._hovered_agent_marker == marker.get("id")
                if status == "success":
                    color = QColor(76, 175, 80) if not is_hovered else QColor(129, 199, 132)
                    shape = "circle"
                elif status == "failed":
                    color = QColor(244, 67, 54) if not is_hovered else QColor(239, 154, 154)
                    shape = "triangle"
                else:
                    color = QColor(255, 193, 7) if not is_hovered else QColor(255, 213, 79)
                    shape = "circle"
                painter.setBrush(QBrush(color))
                pen_width = 1.5 if is_hovered else 1
                painter.setPen(QPen(QColor(0, 0, 0, 180), pen_width))
                size = 7 if is_hovered else 5
                y_center = height // 2
                if shape == "triangle":
                    poly = QPolygon([
                        QPoint(x, y_center - size),
                        QPoint(x + size, y_center + size),
                        QPoint(x - size, y_center + size),
                    ])
                    painter.drawPolygon(poly)
                else:
                    painter.drawEllipse(x - size, y_center - size, size * 2, size * 2)
            except Exception as _e:
                logger.debug("绘制 Agent 标记失败: %s", _e)

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
                tip = f"<b>线性补帧</b><br/>" \
                      f"时间: {marker.time:.3f}s<br/>" \
                      f"类型: {marker.interpolation_type.value}<br/>" \
                      f"置信度: {marker.confidence:.2f}"
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                self.update()
                return

        # P1-C: Agent 反馈标记 tooltip
        self._hovered_agent_marker = None
        for marker in self._agent_feedback_markers:
            try:
                marker_x = self._time_to_x(float(marker.get("time", 0)))
            except (TypeError, ValueError):
                continue
            if abs(x - marker_x) <= 10:
                self._hovered_agent_marker = marker.get("id")
                action = marker.get("action", "agent_action")
                status = marker.get("status", "success")
                msg = marker.get("message", "")
                color = "🟢" if status == "success" else ("🔴" if status == "failed" else "🟡")
                tip = f"<b>{color} Agent {action}</b><br/>" \
                      f"时间: {float(marker.get('time', 0)):.2f}s<br/>" \
                      f"状态: {status}<br/>" \
                      f"{msg}"
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                self.update()
                return

        QToolTip.hideText()
        self._hovered_highlight = None
        self._hovered_marker = None
        self._hovered_agent_marker = None
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
    """轨道视图区域 - 支持播放头拖动；绘制框选橡胶筋。"""
    
    playhead_dragged = pyqtSignal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent_widget = parent
        self._is_dragging_playhead = False
        self.setMouseTracking(True)

    def paintEvent(self, event):
        super().paintEvent(event)
        parent = self._parent_widget

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            rect = self.rect()
            w = rect.width()
            h = rect.height()
            # 只按 Qt 要求重绘的脏区算网格线范围：长时间线/高缩放时避免整条循环
            dirty = event.rect()

            # ── 1. 网格背景线（每秒细线 + 每5秒粗线）──
            self._paint_grid_background(painter, parent, w, h, dirty)

            # ── 2. 轨道间隙标记灰块（>50ms 的空白）──
            self._paint_gap_markers(painter, parent, w, h)

            # ── 3. 框选橡胶筋 ──
            marquee_rect = getattr(parent, "_marquee_rect", None) if parent is not None else None
            if marquee_rect is not None:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                paint_marquee_overlay(painter, marquee_rect)
        finally:
            painter.end()

    def _paint_grid_background(self, painter, parent, w, h, dirty=None):
        """每秒一条浅灰线，每 5 秒一条稍粗线。

        长时间线/高缩放下整表宽度可达上万像素；只按 Qt 传入的脏区（dirty）
        算需要画线的时间范围，而不是从 0 循环到 total_dur，避免滚动/框选时
        每帧都重复画视口外的线。
        """
        if parent is None:
            return
        pps = getattr(parent, "px_per_sec", None)
        if pps is None:
            return
        try:
            pps_val = pps() if callable(pps) else float(pps)
        except Exception:
            return
        if pps_val <= 0:
            return
        margin = getattr(parent, "_left_margin", 0) or 0
        total_dur = float(getattr(parent, "_total_duration", 600) or 600)
        if total_dur <= 0:
            return

        # 根据 pps 自适应网格间隔：缩小时用 5s，放大用 1s，再放大用 0.5s
        sec_per_grid = 1.0
        px_per_grid = pps_val * sec_per_grid
        if px_per_grid < 30:
            sec_per_grid = 5.0
        elif px_per_grid > 300:
            sec_per_grid = 0.5

        if dirty is not None:
            x_lo = max(margin, dirty.left())
            x_hi = min(w, dirty.right() + 1)
        else:
            x_lo, x_hi = margin, w
        if x_hi <= x_lo:
            return
        # 起点向下取整对齐网格，终点留 1 格余量，防止边界漏线
        t_start = max(0.0, ((x_lo - margin) / pps_val))
        t_end = min(total_dur, ((x_hi - margin) / pps_val) + sec_per_grid)

        # 次网格
        painter.setPen(QPen(QColor(60, 60, 60, 60), 1, Qt.PenStyle.DotLine))
        t = (int(t_start / sec_per_grid)) * sec_per_grid
        while t <= t_end:
            x = margin + int(t * pps_val)
            if x_lo <= x <= x_hi:
                painter.drawLine(x, 0, x, h)
            t += sec_per_grid

        # 主网格（每 5 秒）
        if sec_per_grid < 5.0:
            painter.setPen(QPen(QColor(75, 75, 75, 100), 1))
            t = (int(t_start / 5.0)) * 5.0
            while t <= t_end:
                x = margin + int(t * pps_val)
                if x_lo <= x <= x_hi:
                    painter.drawLine(x, 0, x, h)
                t += 5.0

    def _paint_gap_markers(self, painter, parent, w, h):
        """相邻 clip 间 >50ms 的间隙 → 灰色半透明块标记。"""
        if parent is None:
            return
        tracks = getattr(parent, "_tracks", None)
        if not tracks:
            return
        pps_fn = getattr(parent, "px_per_sec", None)
        if pps_fn is None:
            return
        try:
            pps = pps_fn() if callable(pps_fn) else float(pps_fn)
        except Exception:
            return
        margin = getattr(parent, "_left_margin", 0) or 0

        GAP_THRESHOLD = 0.05  # 50ms
        gap_color = QColor(120, 120, 120, 40)

        for track_idx, track in enumerate(tracks):
            widgets = list(getattr(parent, "iter_track_clip_widgets", lambda tr: [])(track))
            if len(widgets) < 2:
                continue
            # 按 start_time 排序
            clips_sorted = sorted(
                [w.clip_data for w in widgets if hasattr(w, "clip_data")],
                key=lambda c: float(c.get("start_time", 0) or 0),
            )
            for i in range(len(clips_sorted) - 1):
                cur = clips_sorted[i]
                nxt = clips_sorted[i + 1]
                cur_end = float(cur.get("start_time", 0) or 0) + float(cur.get("duration", 0) or 0)
                nxt_start = float(nxt.get("start_time", 0) or 0)
                gap = nxt_start - cur_end
                if gap > GAP_THRESHOLD:
                    gx_start = margin + int(cur_end * pps)
                    gx_end = margin + int(nxt_start * pps)
                    if gx_end < margin or gx_start > w:
                        continue
                    gx_start = max(margin, gx_start)
                    gx_end = min(w, gx_end)
                    # 轨道 y 偏移：通过 track_idx 估算（轨道高度约等于第一个 clip 的高度）
                    # 用 widgets[0].height() 近似
                    try:
                        row_h = widgets[0].height() if widgets else 38
                    except Exception:
                        row_h = 38
                    gy = track_idx * row_h
                    painter.fillRect(gx_start, gy, gx_end - gx_start, row_h, gap_color)
    
    def mousePressEvent(self, event):
        """播放头拖 / 刀片模式点切。"""
        parent = self._parent_widget
        if event.button() == Qt.MouseButton.LeftButton:
            playhead_x = parent._track_playhead.x()
            if abs(event.pos().x() - playhead_x) <= 5:
                self._is_dragging_playhead = True
                event.accept()
                return
            self._is_dragging_playhead = False
            if (
                getattr(parent, "_razor_mode", False)
                and hasattr(parent, "_razor_cut_at_global")
                and parent._razor_cut_at_global(event.globalPosition().toPoint())
            ):
                event.accept()
                return
            super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """拖动播放头；刀片模式悬停切开线。"""
        parent = self._parent_widget
        if self._is_dragging_playhead:
            pps = parent.px_per_sec() if hasattr(parent, "px_per_sec") else _timeline_pps(getattr(parent, "_zoom", 100))
            margin = 100
            x = max(margin, min(self.width(), event.pos().x()))
            time_pos = (x - margin) / max(1e-6, pps)
            if hasattr(parent, "frame_duration"):
                time_pos = _quantize_time(time_pos, parent.frame_duration())
            self.playhead_dragged.emit(time_pos)
            event.accept()
            return
        if getattr(parent, "_razor_mode", False) and hasattr(parent, "_update_razor_hover"):
            try:
                parent._update_razor_hover(event.globalPosition().toPoint())
            except Exception:
                pass
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """处理鼠标释放事件"""
        self._is_dragging_playhead = False
        super().mouseReleaseEvent(event)


class TimelineWidget(TimelineSelectionMixin, QWidget):
    """时间线主控件：轨道 / 片段 / 吸附 / 多选。"""

    clip_selected = pyqtSignal(object)
    playhead_moved = pyqtSignal(float)
    # 补短 P1#8：转发 ClipWidget 的关键帧点击，方便 EditorModule 直接监听
    clip_keyframe_clicked = pyqtSignal(object, dict)
    files_dropped = pyqtSignal(list)
    clip_context_action = pyqtSignal(str, object)  # action, clip_data
    clip_trim_committed = pyqtSignal(object)  # 松手后规范化的 clip_data
    razor_cut_at = pyqtSignal(float)  # 刀片工具：在时间线绝对时间切开
    razor_mode_changed = pyqtSignal(bool)
    
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
        from PyQt6.QtWidgets import QApplication
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
                    from PyQt6.QtWidgets import QGraphicsOpacityEffect
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
                print(f"track volume callback failed: {e}")

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
    
    def add_clip(self, clip_data, track_index=0):
        """按 start_time 绝对定位添加到指定轨道。"""
        if track_index < 0 or track_index >= len(self._tracks):
            track_index = 0

        # 在创建 ClipWidget 之前就设置 track 字段，这样 ClipWidget 构造时就能正确识别轨道类型
        clip_data["track"] = track_index
        # 同步 type，便于 ClipWidget 不依赖写死的 track==1
        track_type = self._tracks[track_index].get("type", "video")
        if "type" not in clip_data or not clip_data.get("type"):
            clip_data["type"] = track_type

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
        clip_widget.clip_data["track"] = track_index
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
            except Exception:
                pass
            self._marquee_grab_widget = None
        try:
            self._apply_selection_visual()
        except Exception:
            pass
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
            from PyQt6.QtCore import QPoint as _QP
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
        # _report_timeline_widget_debug(  # 禁用调试报告，避免网络超时
        #     "B",
        #     "timeline_widget.ClipWidget.__init__",
        #     "clip widget init",
        #     {
        #         "module_has_os": "os" in globals(),
        #         "clip_path": clip_data.get("path") if isinstance(clip_data, dict) else None,
        #         "clip_keys": list(clip_data.keys()) if isinstance(clip_data, dict) else None,
        #     },
        # )
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

        # 缩略图（剪映式胶片条）和波形缓存
        self._thumbnail_cache = []
        self._thumb_key = None  # (path, in, out, n, thumb_h)
        self._thumb_aspect = 0.0  # 0=未知，绘制/格宽用首帧比例
        self._thumb_gen_token = 0  # 丢弃过期 worker 结果
        self._waveform_peaks = None  # None=未就绪, []=失败, list=成功
        self._waveform_failed = False
        self._waveform_scheduled = False
        self._thumbnails_generated = False
        # 胶片条绘制缓存：(thumb_h, cell_w, fast) → {src_idx: QPixmap}
        self._scaled_thumb_cache = {}
        self._scaled_thumb_cache_key = None

        # 工作线程引用 - 用于生命周期管理
        self._thumbnail_worker = None
        self._waveform_worker = None
        try:
            self.destroyed.connect(self._on_clip_widget_destroyed)
        except Exception:
            pass

        self._thumb_debounce = QTimer(self)
        self._thumb_debounce.setSingleShot(True)
        self._thumb_debounce.setInterval(120)
        self._thumb_debounce.timeout.connect(self._schedule_thumbnail_generation)

        self.setFixedHeight(48)  # 与 TRACK_H 一致；最终以 position_clip_widget 为准
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # 异步调度缩略图/波形：先让代理任务抢跑，再采胶片（长片避免与代理/预览抢解码）
        QTimer.singleShot(450, self._request_thumbnail_refresh)
        if self._is_audio_clip():
            QTimer.singleShot(200, lambda: self._schedule_waveform_generation(200))
        # 音频轨道使用不同的背景色
        is_audio = self._is_audio_clip()
        bg_color = "#1a4a3a" if is_audio else "#0d1f3a"
        hover_color = "#225a4a" if is_audio else "#132a4a"
        
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 3px;
                border: none;
            }}
            QFrame:hover {{
                background-color: {hover_color};
            }}
            QFrame[selected="true"] {{
                border: 1.5px solid #ff4757;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)

        # 音频片不显示文字标签，只显示波形
        if not is_audio:
            # 片段名称叠在缩略图上（半透明底，不占纵向空间）
            clip_text = os.path.basename(clip_data.get('path', '未命名'))
            clip_name = QLabel()
            clip_name.setStyleSheet(
                "color:#fff;font-size:10px;background:rgba(0,0,0,110);"
                "border:none;border-radius:2px;padding:1px 4px;"
            )
            clip_name.setMaximumWidth(120)
            clip_name.setText(QFontMetrics(clip_name.font()).elidedText(clip_text, Qt.TextElideMode.ElideRight, 120))
            layout.addWidget(clip_name, 0, Qt.AlignmentFlag.AlignTop)

            layout.addStretch()

            # 时长标签
            dur = clip_data.get('duration', 0)
            dur_lbl = QLabel(f"{dur:.1f}s" if dur < 60 else f"{int(dur//60)}:{int(dur%60):02d}")
            dur_lbl.setStyleSheet(
                "color:#e8f0ff;font-size:9px;background:rgba(0,0,0,110);"
                "border:none;border-radius:2px;padding:1px 4px;"
            )
            layout.addWidget(dur_lbl, 0, Qt.AlignmentFlag.AlignTop)

    def _find_timeline(self):
        """沿父链查找 TimelineWidget。"""
        w = self.parent()
        while w is not None:
            if hasattr(w, "_tracks") and hasattr(w, "find_track_index_by_type"):
                return w
            w = w.parent()
        return None

    def _is_audio_clip(self) -> bool:
        """按 type / 扩展名 / 所在轨 type 判断是否为音频片（不写死 track==1）。"""
        if str(self.clip_data.get("type", "")).lower() == "audio":
            return True
        path = self.clip_data.get("path", "") or ""
        if path and any(path.lower().endswith(e) for e in AUDIO_EXTS):
            return True
        ti = int(self.clip_data.get("track", 0) or 0)
        timeline = self._find_timeline()
        if timeline is not None and 0 <= ti < len(timeline._tracks):
            if timeline._tracks[ti].get("type") == "audio":
                return True
        return False

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
            
            clip_path = self.clip_data.get('path', '') or self.clip_data.get('name', '')
            is_audio = self._is_audio_clip()
            
            # ── 视频胶片条：一格一帧（按时间等距映射），铺满轨高 ──
            if not is_audio and self.width() > 20:
                thumb_h = max(1, self.height())
                aspect = float(getattr(self, "_thumb_aspect", 0) or 0) or (16.0 / 9.0)
                valid = [
                    pm for pm in (self._thumbnail_cache or [])
                    if pm is not None and not pm.isNull() and pm.height() > 0
                ]
                if valid:
                    aspect = float(valid[0].width()) / float(valid[0].height())
                    self._thumb_aspect = aspect
                cell_w = max(14, int(round(thumb_h * aspect)))
                segments = max(1, (self.width() + cell_w - 1) // max(1, cell_w))
                n_cache = len(valid)
                timeline = self._find_timeline_widget()
                fast = bool(
                    timeline is not None and timeline.is_clip_interaction_active()
                )
                xform = (
                    Qt.TransformationMode.FastTransformation
                    if fast
                    else Qt.TransformationMode.SmoothTransformation
                )
                scale_key = (thumb_h, cell_w, fast, id(valid[0]) if valid else 0)
                if scale_key != getattr(self, "_scaled_thumb_cache_key", None):
                    self._scaled_thumb_cache = {}
                    self._scaled_thumb_cache_key = scale_key

                if valid:
                    for i in range(segments):
                        x = i * cell_w
                        if x >= self.width():
                            break
                        # 等距映射到缓存帧，禁止 i%N 循环刷同一帧
                        if segments <= 1 or n_cache <= 1:
                            idx = 0
                        else:
                            idx = int(round(i * (n_cache - 1) / max(1, segments - 1)))
                            idx = max(0, min(n_cache - 1, idx))
                        pixmap = valid[idx]
                        draw_w = min(cell_w, self.width() - x)
                        scaled = self._scaled_thumb_cache.get(idx)
                        if scaled is None or scaled.isNull():
                            scaled = pixmap.scaledToHeight(thumb_h, xform)
                            if scaled.width() < draw_w:
                                scaled = pixmap.scaled(
                                    draw_w, thumb_h,
                                    Qt.AspectRatioMode.IgnoreAspectRatio,
                                    xform,
                                )
                            self._scaled_thumb_cache[idx] = scaled
                        if scaled.width() < draw_w:
                            painter.drawPixmap(x, 0, scaled)
                        else:
                            x_off = max(0, (scaled.width() - draw_w) // 2)
                            painter.drawPixmap(
                                x, 0, draw_w, thumb_h,
                                scaled, x_off, 0, draw_w, thumb_h,
                            )
                else:
                    for i in range(segments):
                        x = i * cell_w
                        if x >= self.width():
                            break
                        draw_w = min(cell_w, self.width() - x)
                        shade = 160 + (i % 3) * 20
                        painter.fillRect(x, 0, draw_w, thumb_h, QColor(30, 90, shade, 220))
            
            # ── 音频片段波形可视化（按轨 type / 扩展名，不写死 track==1）──
            if is_audio:
                wave_height = 28
                bar_count = max(4, self.width() // 6)
                bar_width = max(2, (self.width() - 4) // bar_count - 2)
                wave_y = (self.height() - wave_height) // 2

                if self._waveform_peaks is None and not self._waveform_failed:
                    # 加载中：浅色中线，不刷假随机波形
                    if not self._waveform_scheduled:
                        self._schedule_waveform_generation(bar_count)
                    painter.setPen(QPen(QColor(46, 204, 113, 80), 1))
                    mid = wave_y + wave_height // 2
                    painter.drawLine(2, mid, max(3, self.width() - 2), mid)
                elif self._waveform_failed or not self._waveform_peaks:
                    # 失败 / 无音轨：明确空态中线
                    painter.setPen(QPen(QColor(129, 199, 132, 100), 1, Qt.PenStyle.DashLine))
                    mid = wave_y + wave_height // 2
                    painter.drawLine(2, mid, max(3, self.width() - 2), mid)
                else:
                    peaks = self._waveform_peaks
                    peak_max = max(peaks) if peaks else 0.0
                    # 可视化增益：弱信号放大到可见，全 0 已走失败态
                    gain = (0.85 / peak_max) if peak_max > 1e-6 else 1.0
                    for i in range(bar_count):
                        x = 2 + i * (bar_width + 2)
                        peak_val = peaks[i % len(peaks)] if peaks else 0.0
                        peak_val = min(1.0, peak_val * gain)
                        h = max(4, int(peak_val * wave_height))
                        c = QColor(46, 204, 113, 200)
                        painter.fillRect(x, wave_y + (wave_height - h) // 2, bar_width, h, c)
            
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
            timeline = self._find_timeline_widget()
            if timeline is not None and timeline.is_razor_mode():
                # 刀片：点片段即在指针时间切开（含联动音画由 Editor 处理）
                event.accept()
                timeline._razor_cut_at_global(event.globalPosition().toPoint())
                return
            self._drag_start_pos = event.pos()
            self._drag_offset = self.pos()
            self._batch_drag_starts = None
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
            edge = max(8, min(18, self.width() // 8))
            if event.pos().x() < edge:
                self._is_resizing = True
                self._resize_direction = 'left'
                self._resize_snapshot = {
                    "duration": float(self.clip_data.get("duration", 0) or 0),
                    "in_point": float(self.clip_data.get("in_point", 0) or 0),
                    "out_point": float(self.clip_data.get("out_point", 0) or 0),
                    "start_time": float(self.clip_data.get("start_time", 0) or 0),
                    "direction": "left",
                }
            elif event.pos().x() > self.width() - edge:
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
                # 选区由 TimelineWidget 根据修饰键决定，此处只发点击
                self.clicked.emit(self.clip_data)
                # 多选批量拖：若本片已在选区且选区>1，记录组内起点
                self._batch_drag_starts = None
                timeline = self._find_timeline_widget()
                if timeline is not None:
                    ids = timeline.get_selected_ids()
                    cid = self.clip_data.get("id")
                    if cid not in ids:
                        # Ctrl 取消选中：不进入拖拽，避免拖走「已取消」的片
                        self._drag_start_pos = None
                        self._drag_offset = None
                    elif cid in ids and len(ids) > 1:
                        starts = {}
                        tracks0 = {}
                        for c in getattr(timeline, "_clips", []) or []:
                            if c.get("id") in ids:
                                starts[c.get("id")] = float(c.get("start_time", 0) or 0)
                                tracks0[c.get("id")] = int(c.get("track", 0) or 0)
                        self._batch_drag_starts = starts
                        self._batch_drag_tracks0 = tracks0
            if getattr(self, "_is_resizing", False):
                self._resize_global_x0 = float(event.globalPosition().x())
                self._resize_width0 = int(self.width())
                self._resize_x0 = int(self.x())
                self._batch_drag_starts = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        timeline = self._find_timeline_widget()
        if timeline is not None and timeline.is_razor_mode():
            timeline._update_razor_hover(event.globalPosition().toPoint())
            event.accept()
            return
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
            # 误触保护：片缘微抖不触发 trim
            gx0 = float(getattr(self, "_resize_global_x0", event.globalPosition().x()))
            dx_probe = float(event.globalPosition().x()) - gx0
            if not self._did_edit_drag and abs(dx_probe) < CLIP_DRAG_THRESHOLD_PX:
                return
            # 用全局 dx + 按下时宽/位置，trim 跟手不漂移
            self._did_edit_drag = True
            timeline = self._find_timeline_widget()
            if timeline is not None:
                timeline.set_clip_interaction_active(True)
                timeline.register_active_drag_clip(self)
                try:
                    self.grabKeyboard()
                except Exception:
                    pass
            pps = timeline.px_per_sec() if timeline is not None else _timeline_pps(100)
            fd = timeline.frame_duration() if timeline is not None else (1.0 / 30.0)
            w0 = int(getattr(self, "_resize_width0", self.width()))
            x0 = int(getattr(self, "_resize_x0", self.x()))
            dx = dx_probe
            snap = getattr(self, "_resize_snapshot", None) or {}
            if self._resize_direction == 'right':
                new_width = max(_TIMELINE_MIN_CLIP_PX, int(round(w0 + dx)))
                end_t = (x0 + new_width) / max(1e-6, pps)
                if timeline is not None:
                    end_t = timeline.snap_time(
                        end_t,
                        exclude_id=self.clip_data.get("id"),
                        track_i=int(self.clip_data.get("track", 0) or 0),
                    )
                st = float(snap.get("start_time", self.clip_data.get("start_time", 0)) or 0)
                new_dur = max(fd, end_t - st)
                new_width = max(_TIMELINE_MIN_CLIP_PX, int(round(new_dur * pps)))
                self.setFixedWidth(new_width)
                in_p = float(self.clip_data.get("in_point", snap.get("in_point", 0)) or 0)
                self.clip_data["duration"] = new_dur
                self.clip_data["out_point"] = in_p + new_dur
                self.resized.emit(self.clip_data)
            elif self._resize_direction == 'left':
                new_width = max(_TIMELINE_MIN_CLIP_PX, int(round(w0 - dx)))
                new_x = max(0, int(round(x0 + (w0 - new_width))))
                st = new_x / max(1e-6, pps)
                if timeline is not None:
                    st = timeline.snap_time(
                        st,
                        exclude_id=self.clip_data.get("id"),
                        track_i=int(self.clip_data.get("track", 0) or 0),
                    )
                end = float(snap.get("start_time", 0) or 0) + float(snap.get("duration", 0) or 0)
                new_dur = max(fd, end - st)
                new_x = max(0, int(round(st * pps)))
                new_width = max(_TIMELINE_MIN_CLIP_PX, int(round(new_dur * pps)))
                self.setFixedWidth(new_width)
                self.move(new_x, 0)
                dt = float(snap.get("duration", 0) or 0) - new_dur
                self.clip_data["start_time"] = st
                self.clip_data["duration"] = new_dur
                self.clip_data["in_point"] = max(0.0, float(snap.get("in_point", 0) or 0) + dt)
                self.clip_data["out_point"] = float(self.clip_data["in_point"]) + new_dur
                self.resized.emit(self.clip_data)
        elif self._drag_start_pos and self._drag_offset:
            # 误触保护：短距离移动视为点击，不挪片
            if not self._did_edit_drag:
                try:
                    if (event.pos() - self._drag_start_pos).manhattanLength() < CLIP_DRAG_THRESHOLD_PX:
                        return
                except Exception:
                    pass
            # 拖拽：允许跨轨（Y），X 映射 start_time；拖动中实时吸附
            self._did_edit_drag = True
            timeline = self._find_timeline_widget()
            if timeline is not None:
                timeline.set_clip_interaction_active(True)
                timeline.register_active_drag_clip(self)
                try:
                    self.grabKeyboard()
                except Exception:
                    pass
            parent = self.parent()
            new_pos = self.mapToParent(event.pos()) - self._drag_start_pos + self._drag_offset
            if new_pos.x() < 0:
                new_pos.setX(0)
            batch_starts = getattr(self, "_batch_drag_starts", None)
            if batch_starts and timeline is not None and len(batch_starts) > 1:
                # 多选同步平移 + 跨轨（同类型）；吸附参照指针下兼容轨
                px = max(1e-6, timeline.px_per_sec())
                proposed = max(0.0, new_pos.x() / px)
                gy = event.globalPosition().toPoint().y()
                drop_ti, drop_ok = timeline.resolve_drop_track(gy, self.clip_data)
                timeline.set_drop_track_feedback(drop_ti, drop_ok)
                snap_ti = drop_ti if (drop_ok and drop_ti is not None) else int(
                    self.clip_data.get("track", 0) or 0
                )
                apply_batch_start_delta(
                    timeline,
                    batch_starts,
                    self.clip_data.get("id"),
                    proposed,
                    exclude_ids=list(batch_starts.keys()),
                    snap_track_i=snap_ti,
                )
                if drop_ok and drop_ti is not None:
                    for cid in list(batch_starts.keys()):
                        w = next(
                            (cw for cw in timeline.all_clip_widgets()
                             if cw.clip_data.get("id") == cid),
                            None,
                        )
                        if w is None:
                            continue
                        cd = w.clip_data
                        if not clip_compatible_with_track(cd, timeline._tracks[drop_ti]):
                            continue
                        if int(cd.get("track", -1) or -1) == drop_ti:
                            continue
                        timeline.reparent_clip_to_track(w, drop_ti)
                        for c in timeline._clips:
                            if c.get("id") == cid:
                                c["track"] = drop_ti
                                break
                self.moved.emit(self.clip_data)
                return
            if timeline is not None:
                gy = event.globalPosition().toPoint().y()
                drop_ti, drop_ok = timeline.resolve_drop_track(gy, self.clip_data)
                timeline.set_drop_track_feedback(drop_ti, drop_ok)
                if drop_ok and drop_ti is not None:
                    track = timeline._tracks[drop_ti]
                    if parent is not track.get("clip_container"):
                        self.setParent(track["clip_container"])
                        self.clip_data["track"] = drop_ti
                        parent = track["clip_container"]
                        self.show()
                # 不兼容轨：不 reparent，仍可横向拖；吸附用当前轨
                px = max(1e-6, timeline.px_per_sec())
                st = max(0.0, new_pos.x() / px)
                snap_ti = int(self.clip_data.get("track", 0) or 0)
                st = timeline.snap_start_time(
                    self.clip_data,
                    st,
                    exclude_id=self.clip_data.get("id"),
                    track_i=snap_ti,
                )
                self.clip_data["start_time"] = st
                timeline.position_clip_widget(self)
                self.moved.emit(self.clip_data)
            else:
                self.move(max(0, new_pos.x()), 0)

    def mouseReleaseEvent(self, event):
        # 松手时按最终宽度规范化 in/out，保证导出与预览一致
        if self._did_edit_drag:
            try:
                timeline = self._find_timeline_widget()
                px = timeline.px_per_sec() if timeline is not None else _timeline_pps(100)
                fd = timeline.frame_duration() if timeline is not None else (1.0 / 30.0)
                batch_starts = getattr(self, "_batch_drag_starts", None)
                # ── 多选批量平移提交（一条 undo）──
                if batch_starts and timeline is not None and len(batch_starts) > 1 and not self._is_resizing:
                    items = []
                    tracks0 = getattr(self, "_batch_drag_tracks0", None) or {}
                    for cid, st0 in batch_starts.items():
                        clip = next(
                            (c for c in timeline._clips if c.get("id") == cid),
                            None,
                        )
                        if clip is None:
                            continue
                        st = _quantize_time(float(clip.get("start_time", 0) or 0), fd)
                        clip["start_time"] = st
                        w = next(
                            (cw for cw in timeline.all_clip_widgets() if cw.clip_data.get("id") == cid),
                            None,
                        )
                        if w is not None:
                            w.clip_data["start_time"] = st
                            timeline.position_clip_widget(w)
                        before = {
                            "id": cid,
                            "start_time": float(st0),
                            "duration": float(clip.get("duration", 0) or 0),
                            "in_point": float(clip.get("in_point", 0) or 0),
                            "out_point": float(clip.get("out_point", 0) or 0),
                            "track": int(tracks0.get(cid, clip.get("track", 0)) or 0),
                        }
                        after = {
                            "start_time": st,
                            "track": int(clip.get("track", 0) or 0),
                            "duration": float(clip.get("duration", 0) or 0),
                            "in_point": float(clip.get("in_point", 0) or 0),
                            "out_point": float(clip.get("out_point", 0) or 0),
                        }
                        items.append({"clip_id": cid, "before": before, "after": after, "clip": clip})
                    if timeline is not None:
                        timeline.clear_snap_guide(fade=True)
                        timeline.clear_drop_track_feedback()
                    self.trim_committed.emit({"_batch_move": True, "items": items})
                    self._batch_drag_starts = None
                    self._batch_drag_tracks0 = None
                    self._is_resizing = False
                    self._resize_direction = None
                    self._drag_start_pos = None
                    self._drag_offset = None
                    self._resize_snapshot = None
                    self._did_edit_drag = False
                    self._edit_before = None
                    if timeline is not None:
                        timeline.set_clip_interaction_active(False)
                        timeline._active_drag_clip = None
                    try:
                        self.releaseKeyboard()
                    except Exception:
                        pass
                    super().mouseReleaseEvent(event)
                    return

                dur = max(fd, self.width() / max(1e-6, px))
                # 帧量化，避免亚帧碎口
                if timeline is not None:
                    st0 = float(self.clip_data.get("start_time", 0) or 0)
                    self.clip_data["start_time"] = _quantize_time(st0, fd)
                    dur = max(fd, _quantize_time(dur, fd))
                snap = self._resize_snapshot
                if snap and snap.get("direction") == "right":
                    in_p = float(self.clip_data.get("in_point", snap.get("in_point", 0)) or 0)
                    self.clip_data["duration"] = dur
                    self.clip_data["out_point"] = in_p + dur
                    # 片尾吸附
                    if timeline is not None:
                        st = float(self.clip_data.get("start_time", 0) or 0)
                        end = timeline.snap_time(
                            st + dur,
                            exclude_id=self.clip_data.get("id"),
                            track_i=int(self.clip_data.get("track", 0) or 0),
                        )
                        new_dur = max(fd, end - st)
                        self.clip_data["duration"] = new_dur
                        self.clip_data["out_point"] = in_p + new_dur
                        timeline.position_clip_widget(self)
                elif snap and snap.get("direction") == "left":
                    end = float(snap["start_time"]) + float(snap["duration"])
                    self.clip_data["duration"] = dur
                    self.clip_data["start_time"] = max(0.0, end - dur)
                    dt = float(snap["duration"]) - dur
                    self.clip_data["in_point"] = max(0.0, float(snap["in_point"]) + dt)
                    self.clip_data["out_point"] = float(self.clip_data["in_point"]) + dur
                    # 片头吸附
                    if timeline is not None:
                        st = timeline.snap_time(
                            float(self.clip_data.get("start_time", 0) or 0),
                            exclude_id=self.clip_data.get("id"),
                            track_i=int(self.clip_data.get("track", 0) or 0),
                        )
                        new_dur = max(fd, end - st)
                        self.clip_data["start_time"] = st
                        self.clip_data["duration"] = new_dur
                        self.clip_data["in_point"] = max(0.0, float(snap["in_point"]) + (float(snap["duration"]) - new_dur))
                        self.clip_data["out_point"] = float(self.clip_data["in_point"]) + new_dur
                        timeline.position_clip_widget(self)
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
                # trim 改变 in/out → 胶片条内容随源区间移动
                self._request_thumbnail_refresh()
                if timeline is not None:
                    timeline.clear_snap_guide(fade=True)
                    timeline.clear_drop_track_feedback()
            except Exception as e:
                print(f"clip trim commit failed: {e}")
                timeline = self._find_timeline_widget()
                if timeline is not None:
                    timeline.clear_snap_guide(fade=False)
                    timeline.clear_drop_track_feedback()

        timeline = self._find_timeline_widget()
        if timeline is not None:
            timeline.clear_drop_track_feedback()
            timeline.set_clip_interaction_active(False)
            if getattr(timeline, "_active_drag_clip", None) is self:
                timeline._active_drag_clip = None
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None
        self._resize_snapshot = None
        self._did_edit_drag = False
        self._edit_before = None
        self._batch_drag_starts = None
        super().mouseReleaseEvent(event)

    def cancel_edit_drag(self) -> bool:
        """Esc：放弃本次拖拽/trim，还原按下时的时间与轨。"""
        if not getattr(self, "_did_edit_drag", False) and getattr(
            self, "_drag_start_pos", None
        ) is None:
            return False
        timeline = self._find_timeline_widget()
        before = getattr(self, "_edit_before", None)
        batch_starts = getattr(self, "_batch_drag_starts", None)
        tracks0 = getattr(self, "_batch_drag_tracks0", None) or {}
        try:
            if batch_starts and timeline is not None and len(batch_starts) > 1:
                for cid, st0 in batch_starts.items():
                    clip = next(
                        (c for c in timeline._clips if c.get("id") == cid), None
                    )
                    w = next(
                        (cw for cw in timeline.all_clip_widgets()
                         if cw.clip_data.get("id") == cid),
                        None,
                    )
                    if clip is not None:
                        clip["start_time"] = float(st0)
                        ti0 = int(tracks0.get(cid, clip.get("track", 0)) or 0)
                        clip["track"] = ti0
                    if w is not None:
                        w.clip_data["start_time"] = float(st0)
                        ti0 = int(tracks0.get(cid, w.clip_data.get("track", 0)) or 0)
                        if int(w.clip_data.get("track", -1) or -1) != ti0:
                            timeline.reparent_clip_to_track(w, ti0)
                        else:
                            w.clip_data["track"] = ti0
                        timeline.position_clip_widget(w)
            elif before and isinstance(before, dict):
                for k in ("start_time", "duration", "in_point", "out_point"):
                    if k in before:
                        self.clip_data[k] = before[k]
                ti0 = int(before.get("track", self.clip_data.get("track", 0)) or 0)
                self.clip_data["track"] = ti0
                if timeline is not None:
                    if int(self.clip_data.get("track", -1) or -1) != ti0:
                        timeline.reparent_clip_to_track(self, ti0)
                    timeline.position_clip_widget(self)
        except Exception as e:
            logger.debug("还原拖拽状态失败: %s", e)
        if timeline is not None:
            try:
                timeline.clear_snap_guide(fade=False)
                timeline.clear_drop_track_feedback()
                timeline.set_clip_interaction_active(False)
                timeline._active_drag_clip = None
            except Exception:
                pass
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None
        self._resize_snapshot = None
        self._did_edit_drag = False
        self._edit_before = None
        self._batch_drag_starts = None
        self._batch_drag_tracks0 = None
        self.update()
        return True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.cancel_edit_drag():
                event.accept()
                return
        super().keyPressEvent(event)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._is_audio_clip():
            self._request_thumbnail_refresh()

    def _source_in_out(self):
        """片段源时间窗 [in, out)。"""
        in_p = float(self.clip_data.get("in_point", 0) or 0)
        out_p = float(self.clip_data.get("out_point", 0) or 0)
        if out_p <= in_p + 1e-6:
            out_p = in_p + max(0.05, float(self.clip_data.get("duration", 10) or 10))
        return in_p, out_p

    def _filmstrip_cell_w(self, thumb_h: int = None) -> int:
        h = max(8, int(thumb_h if thumb_h is not None else (self.height() or 48)))
        aspect = float(getattr(self, "_thumb_aspect", 0) or 0) or (16.0 / 9.0)
        return max(14, int(round(h * aspect)))

    def _desired_thumb_count(self) -> int:
        cell_w = self._filmstrip_cell_w()
        w = max(1, int(self.width() or 1))
        return max(1, min(48, (w + cell_w - 1) // max(1, cell_w)))

    def _current_thumb_key(self):
        path = self._resolve_clip_media_path()
        in_p, out_p = self._source_in_out()
        n = self._desired_thumb_count()
        thumb_h = max(8, int(self.height() or 48))
        return (
            path,
            round(in_p, 3),
            round(out_p, 3),
            int(n),
            int(thumb_h),
        )

    def _should_wait_proxy_before_filmstrip(self) -> bool:
        """长视频在代理未就绪时先等一拍，避免与代理转码/预览抢开同一文件。"""
        if self._is_audio_clip():
            return False
        proxy = str(self.clip_data.get("proxy_path") or "")
        if proxy and os.path.isfile(proxy):
            return False
        if getattr(self, "_filmstrip_proxy_wait_done", False):
            return False
        dur = float(self.clip_data.get("duration", 0) or 0)
        # 短片 / 静图：不等代理
        if dur > 0 and dur < 12.0:
            return False
        ext = os.path.splitext(str(self.clip_data.get("path") or ""))[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"):
            return False
        return True

    def _on_filmstrip_proxy_wait_timeout(self):
        """代理等待结束：无论是否就绪都采一次（有代理则走代理路径）。"""
        self._filmstrip_proxy_wait_done = True
        try:
            self._request_thumbnail_refresh()
        except Exception as e:
            logger.debug("代理等待后采胶片失败: %s", e)

    def _request_thumbnail_refresh(self):
        """合并缩放/布局抖动后重采胶片条。"""
        if self._is_audio_clip():
            return
        if self._parent_track_collapsed():
            return
        timeline = self._find_timeline_widget()
        if timeline is not None and timeline.is_clip_interaction_active():
            return
        if timeline is not None and not timeline.is_clip_widget_visible(self):
            return  # 视口外懒加载，滚动后再采
        # 代理优先：长片先 defer，等 proxy_path 或超时后再采
        if self._should_wait_proxy_before_filmstrip():
            timer = getattr(self, "_filmstrip_proxy_timer", None)
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(2800)
                timer.timeout.connect(self._on_filmstrip_proxy_wait_timeout)
                self._filmstrip_proxy_timer = timer
            if not timer.isActive():
                timer.start()
            return
        timer = getattr(self, "_thumb_debounce", None)
        if timer is None:
            self._schedule_thumbnail_generation()
            return
        timer.start()

    def _schedule_thumbnail_generation(self):
        """按 in/out 均匀采样，异步生成剪映式胶片条。"""
        if self._is_audio_clip():
            self._thumbnails_generated = True
            return
        if self._parent_track_collapsed():
            return
        timeline = self._find_timeline_widget()
        if timeline is not None and timeline.is_clip_interaction_active():
            return
        if timeline is not None and not timeline.is_clip_widget_visible(self):
            return

        clip_path = self._resolve_clip_media_path()
        if not clip_path or not os.path.exists(clip_path):
            self._thumbnails_generated = True
            return

        ext = os.path.splitext(clip_path)[1].lower()
        if ext in AUDIO_EXTS:
            self._thumbnails_generated = True
            return

        key = self._current_thumb_key()
        if key == getattr(self, "_thumb_key", None) and self._thumbnail_cache:
            self._thumbnails_generated = True
            return

        # 停止旧 worker，避免结果乱序覆盖
        old = getattr(self, "_thumbnail_worker", None)
        if old is not None:
            try:
                old.thumbnails_ready.disconnect(self._on_thumbnails_ready)
            except Exception:
                pass
            try:
                if old.isRunning():
                    old.requestInterruption()
                    old.quit()
            except Exception as e:
                logger.debug("停止旧缩略图线程: %s", e)
            self._thumbnail_worker = None

        in_p, out_p = self._source_in_out()
        n = int(key[3])
        thumb_h = max(48, int(key[4]) * 2)  # 稍高分辨率，绘制再 scaledToHeight
        span = max(0.05, out_p - in_p)
        timestamps = [in_p + (i + 0.5) / n * span for i in range(n)]

        self._thumb_gen_token = int(getattr(self, "_thumb_gen_token", 0) or 0) + 1
        token = self._thumb_gen_token
        pending_key = key

        from PyQt6.QtCore import QThread, pyqtSignal

        class FilmstripWorker(QThread):
            thumbnails_ready = pyqtSignal(list, float)  # pixmaps, aspect

            def __init__(self, path, timestamps, height):
                super().__init__()
                self._path = path
                self._timestamps = list(timestamps)
                self._height = int(height)

            def run(self):
                thumbs, aspect = _extract_filmstrip_frames(
                    self._path, self._timestamps, self._height, self.isInterruptionRequested
                )
                if self.isInterruptionRequested():
                    return
                self.thumbnails_ready.emit(thumbs, aspect)

        # 排队中的旧请求（尚未真正 start）先撤销，避免同一 widget 占多个名额
        _media_worker_gate.cancel_owner(self)

        worker = FilmstripWorker(clip_path, timestamps, thumb_h)
        self._thumbnail_worker = worker
        worker.thumbnails_ready.connect(
            lambda thumbs, aspect, t=token, k=pending_key: self._on_thumbnails_ready(
                thumbs, aspect, token=t, key=k
            )
        )
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(_media_worker_gate.release)
        _media_worker_gate.request(self, worker.start)

    def _on_thumbnails_ready(self, thumbnails, aspect=0.0, token=None, key=None):
        """胶片条生成完成；丢弃过期 token。"""
        if token is not None and token != getattr(self, "_thumb_gen_token", None):
            return
        self._thumbnail_cache = list(thumbnails or [])
        if aspect and aspect > 0.05:
            self._thumb_aspect = float(aspect)
        elif self._thumbnail_cache:
            pm0 = self._thumbnail_cache[0]
            if pm0 is not None and not pm0.isNull() and pm0.height() > 0:
                self._thumb_aspect = float(pm0.width()) / float(pm0.height())
        if key is not None:
            self._thumb_key = key
        self._thumbnails_generated = True
        self._scaled_thumb_cache = {}
        self._scaled_thumb_cache_key = None
        self.update()

    def _resolve_clip_media_path(self) -> str:
        """解析片段媒体路径；胶片条优先代理（导出仍用 clip['path'] 原片）。"""
        # 预览/胶片条：代理就绪则用代理
        proxy = str(self.clip_data.get("proxy_path") or "")
        if proxy and os.path.isfile(proxy):
            return os.path.normpath(proxy)
        raw = self.clip_data.get("path", "") or ""
        if not raw:
            return ""
        if os.path.exists(raw):
            return raw
        candidates = [
            os.path.normpath(os.path.join(os.getcwd(), raw)),
            os.path.normpath(os.path.join(os.getcwd(), "app", raw)),
        ]
        # 从本文件位置推工程根
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
            candidates.append(os.path.normpath(os.path.join(project_root, raw)))
            candidates.append(os.path.normpath(os.path.join(project_root, "app", raw)))
        except Exception as e:
            logger.debug("解析片段媒体路径工程根失败: %s", e)
        for c in candidates:
            if c and os.path.exists(c):
                self.clip_data["path"] = c
                return c
        return raw

    def _on_clip_widget_destroyed(self, *_args):
        try:
            self._cleanup_workers()
        except Exception:
            pass

    def _parent_track_collapsed(self) -> bool:
        """所在轨道是否折叠（折叠轨不调度媒体后台任务）。"""
        try:
            timeline = self._find_timeline_widget()
            if timeline is None:
                return False
            ti = int(self.clip_data.get("track", 0) or 0)
            tracks = getattr(timeline, "_tracks", None) or []
            if 0 <= ti < len(tracks):
                return bool(tracks[ti].get("collapsed", False))
        except Exception:
            pass
        return False

    def sleep_media_workers(self):
        """折叠/休眠：停止缩略图与波形线程。"""
        try:
            if getattr(self, "_thumb_debounce", None) is not None:
                self._thumb_debounce.stop()
        except Exception:
            pass
        try:
            _media_worker_gate.cancel_owner(self)
        except Exception:
            pass
        try:
            self._thumb_gen_token = int(getattr(self, "_thumb_gen_token", 0) or 0) + 1
        except Exception:
            pass
        for attr in ("_thumbnail_worker", "_waveform_worker"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if hasattr(w, "requestInterruption"):
                    w.requestInterruption()
                if w.isRunning():
                    w.quit()
                    w.wait(500)
            except RuntimeError:
                pass
            except Exception as e:
                logger.debug("停媒体 worker 失败: %s", e)
            setattr(self, attr, None)
        self._waveform_scheduled = False
        self._scaled_thumb_cache = {}
        self._scaled_thumb_cache_key = None

    def wake_media_workers(self):
        """展开轨道后重新调度媒体预览。"""
        if self._parent_track_collapsed():
            return
        self._request_thumbnail_refresh()
        if self._is_audio_clip() and self._waveform_peaks is None and not self._waveform_failed:
            self._waveform_scheduled = False
            QTimer.singleShot(80, lambda: self._schedule_waveform_generation(200))

    def _schedule_waveform_generation(self, num_samples):
        """调度异步波形生成（防重入，仅音频片）。"""
        if not self._is_audio_clip():
            return
        if self._parent_track_collapsed():
            return
        timeline = self._find_timeline_widget()
        if timeline is not None and timeline.is_clip_interaction_active():
            return
        if timeline is not None and not timeline.is_clip_widget_visible(self):
            return
        if self._waveform_scheduled or self._waveform_peaks is not None or self._waveform_failed:
            return

        clip_path = self._resolve_clip_media_path()
        if not clip_path or not os.path.exists(clip_path):
            self._waveform_failed = True
            self._waveform_peaks = []
            self.update()
            return

        self._waveform_scheduled = True
        from PyQt6.QtCore import QThread, pyqtSignal
        
        class WaveformWorker(QThread):
            waveform_ready = pyqtSignal(list)
            
            def __init__(self, clip_path, num_samples):
                super().__init__()
                self._clip_path = clip_path
                self._num_samples = num_samples
            
            def run(self):
                try:
                    from app.core.waveform_generator import waveform_generator
                    data = waveform_generator.generate(self._clip_path, num_samples=self._num_samples)
                    if data and data.peaks and max(data.peaks) > 1e-6:
                        self.waveform_ready.emit(list(data.peaks))
                    else:
                        self.waveform_ready.emit([])
                except Exception as e:
                    logger.error(f"波形生成失败: {e}")
                    self.waveform_ready.emit([])
        
        _media_worker_gate.cancel_owner(self)

        self._waveform_worker = WaveformWorker(clip_path, num_samples)
        self._waveform_worker.waveform_ready.connect(self._on_waveform_ready)
        self._waveform_worker.finished.connect(self._waveform_worker.deleteLater)
        self._waveform_worker.finished.connect(_media_worker_gate.release)
        _media_worker_gate.request(self, self._waveform_worker.start)
    
    def _on_waveform_ready(self, peaks):
        """波形生成完成回调。空列表表示失败/无音轨。"""
        if peaks and max(peaks) > 1e-6:
            self._waveform_peaks = peaks
            self._waveform_failed = False
        else:
            self._waveform_peaks = []
            self._waveform_failed = True
        self.update()
    
    def _cleanup_workers(self):
        """清理所有工作线程 - 在widget销毁前调用"""
        try:
            _media_worker_gate.cancel_owner(self)
        except Exception:
            pass
        if hasattr(self, '_thumbnail_worker') and self._thumbnail_worker is not None:
            try:
                if self._thumbnail_worker.isRunning():
                    if hasattr(self._thumbnail_worker, 'requestInterruption'):
                        self._thumbnail_worker.requestInterruption()
                    self._thumbnail_worker.quit()
                    self._thumbnail_worker.wait(2000)
            except RuntimeError as e:
                logger.debug("停止缩略图工作线程失败: %s", e)
            self._thumbnail_worker = None
        if hasattr(self, '_waveform_worker') and self._waveform_worker is not None:
            try:
                if self._waveform_worker.isRunning():
                    if hasattr(self._waveform_worker, 'requestInterruption'):
                        self._waveform_worker.requestInterruption()
                    self._waveform_worker.quit()
                    self._waveform_worker.wait(2000)
            except RuntimeError as e:
                logger.debug("停止波形工作线程失败: %s", e)
            self._waveform_worker = None
    
    def closeEvent(self, event):
        """Widget关闭事件 - 确保工作线程安全终止"""
        self._cleanup_workers()
        super().closeEvent(event)


