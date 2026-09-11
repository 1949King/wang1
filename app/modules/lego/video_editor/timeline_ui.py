"""
优化时间轴UI组件
==================
整合timeline_core，提供专业级时间轴UI，支持虚拟化、缩放、精确编辑
"""

from typing import Dict, List, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal, Qt, QTimer, QProperty
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QLabel, QPushButton, QSlider, QSpinBox, QCheckBox, QStyleOptionPainter
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsPixmapItem, QGraphicsRectItem
from PyQt6.QtGui import QColor, QFont, QTransform
import logging
import math

from app.core.timeline import timeline_core

logger = logging.getLogger("AI短剧编辑器.timeline_ui")


class TimelineView(QGraphicsView):
    """时间轴视图 - 专业级图形化时间轴"""
    
    frame_selected = pyqtSignal(str, float)
    frame_moved = pyqtSignal(str, float, float)
    timeline_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._timeline_id = None
        self._zoom_level = 1.0
        self._snap_enabled = True
        self._snap_threshold = 0.1
        self._show_waveform = False
        self._ruler_visible = True
        
        self._setup_scene()
        self._setup_ui()
    
    def _setup_scene(self):
        """设置场景"""
        self._scene = QGraphicsScene()
        self._scene.setSceneRect(0, 0, 10000, 10000)
        
        # 设置渲染优化
        self._scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self._scene.setBspTreeDepth(24)
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 时间轴控制栏
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(8)
        
        # 缩放控制
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedWidth(24)
        zoom_in_btn.clicked.connect(lambda: self._set_zoom(self._zoom_level * 1.2))
        controls_layout.addWidget(zoom_in_btn)
        
        zoom_out_btn = QPushButton("-")
        zoom_out_btn.setFixedWidth(24)
        zoom_out_btn.clicked.connect(lambda: self._set_zoom(self._zoom_level / 1.2))
        controls_layout.addWidget(zoom_out_btn)
        
        zoom_label = QLabel(f"{self._zoom_level * 100:.0f}%")
        zoom_label.setFixedWidth(60)
        controls_layout.addWidget(zoom_label)
        
        # 吸附控制
        snap_checkbox = QCheckBox("磁吸")
        snap_checkbox.setChecked(self._snap_enabled)
        snap_checkbox.toggled.connect(self._set_snap_enabled)
        controls_layout.addWidget(snap_checkbox)
        
        snap_threshold_label = QLabel("阈值:")
        snap_threshold_slider = QSlider(Qt.Orientation.Horizontal)
        snap_threshold_slider.setRange(1, 100)
        snap_threshold_slider.setValue(int(self._snap_threshold * 100))
        snap_threshold_slider.valueChanged.connect(self._set_snap_threshold)
        controls_layout.addWidget(snap_threshold_label)
        controls_layout.addWidget(snap_threshold_slider)
        
        # 视图控制
        view_mode_btn = QPushButton("波形")
        view_mode_btn.setCheckable(True)
        view_mode_btn.clicked.connect(self._toggle_waveform)
        controls_layout.addWidget(view_mode_btn)
        
        ruler_checkbox = QCheckBox("标尺")
        ruler_checkbox.setChecked(self._ruler_visible)
        ruler_checkbox.toggled.connect(self._toggle_ruler)
        controls_layout.addWidget(ruler_checkbox)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # 时间轴区域
        self._timeline_view = QGraphicsView()
        self._timeline_view.setScene(self._scene)
        self._timeline_view.setRenderHint(QGraphicsView.RenderHint.Antialiasing)
        self._timeline_view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._timeline_view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        
        layout.addWidget(self._timeline_view)
        
        # 时间码显示
        timecode_layout = QHBoxLayout()
        timecode_layout.setContentsMargins(8, 8, 8, 8)
        timecode_layout.setSpacing(8)
        
        timecode_label = QLabel("00:00:00.000")
        timecode_label.setStyleSheet("font-family: monospace; font-size: 12px; color: #808080; background: rgba(0,0,0,0.1); padding: 4px 8px;")
        timecode_layout.addWidget(timecode_label)
        
        layout.addLayout(timecode_layout)
    
    def set_timeline(self, timeline_id: str) -> None:
        """设置时间线"""
        self._timeline_id = timeline_id
        timeline = timeline_core.get_current_timeline()
        
        if timeline:
            self._update_timeline_display(timeline)
            self.timeline_changed.emit(timeline_id)
            logger.info(f"设置时间线: {timeline_id}")
    
    def _update_timeline_display(self, timeline: Dict[str, Any]) -> None:
        """更新时间线显示"""
        self._scene.clear()
        
        tracks = timeline.get('tracks', [])
        for track in tracks:
            self._create_track_display(track)
        
        self._update_timecode()
    
    def _create_track_display(self, track: Dict[str, Any]) -> None:
        """创建轨道显示"""
        track_id = track.get('id')
        track_type = track.get('type', 'video')
        track_name = track.get('name', '')
        clips = track.get('clips', [])
        
        # 轨道背景
        track_height = 80
        track_rect = QGraphicsRectItem(0, 0, 10000, track_height)
        track_rect.setBrush(QColor("#1a1a1a" if track_type == 'video' else QColor("#2a2a2a")))
        
        # 轨道标签
        track_label = QGraphicsSimpleTextItem(f"{track_name}")
        track_label.setDefaultTextColor(QColor("#ffffff"))
        track_label.setFont(QFont("Arial", 10))
        track_label.setPos(10, track_height / 2)
        
        self._scene.addItem(track_rect)
        self._scene.addItem(track_label)
        
        # 创建片段
        for clip in clips:
            self._create_clip_display(clip, track_height, track_type)
    
    def _create_clip_display(self, clip: Dict[str, Any], track_height: int, track_type: str) -> None:
        """创建片段显示"""
        clip_id = clip.get('id')
        start_time = clip.get('start_time', 0.0)
        duration = clip.get('duration', 5.0)
        
        # 计算位置和尺寸
        total_duration = timeline_core.get_current_timeline().get('settings', {}).get('duration', 0)
        if total_duration > 0:
            clip_x = (start_time / total_duration) * 10000
            clip_width = (duration / total_duration) * 10000
        else:
            clip_x = 100
            clip_width = 500
        
        clip_height = track_height - 10
        clip_rect = QGraphicsRectItem(clip_x, 0, clip_width, clip_height)
        
        # 设置颜色
        if track_type == 'video':
            clip_rect.setBrush(QColor("#4CAF50"))
        else:
            clip_rect.setBrush(QColor("#50C878"))
        
        # 片段标签
        clip_label = QGraphicsSimpleTextItem(f"{clip_id}")
        clip_label.setDefaultTextColor(QColor("#ffffff"))
        clip_label.setFont(QFont("Arial", 9))
        clip_label.setPos(clip_x + clip_width / 2, clip_height / 2)
        
        self._scene.addItem(clip_rect)
        self._scene.addItem(clip_label)
    
    def _update_timecode(self) -> None:
        """更新时间码"""
        timeline = timeline_core.get_current_timeline()
        if not timeline:
            return
        
        current_time = timeline.get('settings', {}).get('current_time', 0.0)
        total_duration = timeline.get('settings', {}).get('duration', 0)
        
        if total_duration > 0:
            timecode = self._format_timecode(current_time)
        else:
            timecode = "00:00:00.000"
        
        self.findChild(QLabel, "时间码").setText(timecode)
    
    def _format_timecode(self, seconds: float) -> str:
        """格式化时间码"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{int((seconds * 100) % 100):03d}"
    
    def _set_zoom(self, level: float) -> None:
        """设置缩放级别"""
        self._zoom_level = max(0.1, min(10.0, level))
        self._timeline_view.setTransform(self._calculate_transform())
        logger.info(f"缩放级别设置为: {self._zoom_level:.2f}x")
    
    def _calculate_transform(self) -> QTransform:
        """计算变换矩阵"""
        scale = self._zoom_level
        transform = QTransform()
        transform.scale(scale, scale)
        return transform
    
    def _set_snap_enabled(self, enabled: bool) -> None:
        """设置磁吸对齐"""
        self._snap_enabled = enabled
        logger.info(f"磁吸对齐: {'启用' if enabled else '禁用'}")
    
    def _set_snap_threshold(self, value: int) -> None:
        """设置磁吸阈值"""
        self._snap_threshold = value / 100.0
        logger.info(f"磁吸阈值: {self._snap_threshold:.2f}秒")
    
    def _toggle_waveform(self) -> None:
        """切换波形显示"""
        self._show_waveform = not self._show_waveform
        logger.info(f"波形显示: {'启用' if self._show_waveform else '禁用'}")
    
    def _toggle_ruler(self, visible: bool) -> None:
        """切换标尺显示"""
        self._ruler_visible = visible
        logger.info(f"标尺显示: {'启用' if visible else '禁用'}")
    
    def get_timeline_view(self) -> QGraphicsView:
        """获取时间轴视图"""
        return self._timeline_view
    
    def get_zoom_level(self) -> float:
        """获取缩放级别"""
        return self._zoom_level
    
    def get_snap_settings(self) -> Dict[str, Any]:
        """获取吸附设置"""
        return {
            'enabled': self._snap_enabled,
            'threshold': self._snap_threshold
        }
    
    def get_view_settings(self) -> Dict[str, Any]:
        """获取视图设置"""
        return {
            'zoom_level': self._zoom_level,
            'waveform_visible': self._show_waveform,
            'ruler_visible': self._ruler_visible
        }