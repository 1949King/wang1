"""时间线控件 — 子控件与基础设施
================================
从 timeline_widget.py 抽取的底层共享符号：
- AUDIO_EXTS 音频扩展名列表
- _MediaWorkerGate 全局限流（胶片条/波形 QThread 并发上限）
- 时间线常量与工具函数（缩放、吸附、时间量化、帧转 QPixmap、胶片条抽帧）
- TimeRuler 时间标尺
- TimelineMarkerLayer 时间轴标记层
- TrackControlPanel 轨道控制面板
- TrackViewport 轨道视图区域
"""
import logging
import threading
import weakref

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush, QFontMetrics,
    QPolygon, QPixmap, QImage,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider,
)

from .editor_timeline_tools import paint_marquee_overlay

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

    clicked = Signal(float)  # 点击位置（秒）
    
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
        from PySide6.QtWidgets import QToolTip
        
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

    mute_toggled = Signal(object, bool)
    solo_toggled = Signal(object, bool)
    lock_toggled = Signal(object, bool)
    volume_changed = Signal(object, float)
    collapse_toggled = Signal(object, bool)

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
    
    playhead_dragged = Signal(float)
    
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
