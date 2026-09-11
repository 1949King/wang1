"""
多轨道编辑器
==================
基于track_manager.py扩展多轨道管理，支持无限轨道、轨道锁定、磁吸对齐
"""

from typing import Dict, List, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea
from PyQt6.QtWidgets import QPushButton, QLabel, QCheckBox, QSlider, QComboBox
import logging

from ..core.timeline import timeline_core

logger = logging.getLogger("AI短剧编辑器.multi_track_editor")


class TrackType:
    """轨道类型"""
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


class TrackInfo:
    """轨道信息"""
    
    def __init__(self, track_id: str, track_type: str, name: str, is_muted: bool = False, is_locked: bool = False):
        self.track_id = track_id
        self.track_type = track_type
        self.name = name
        self.is_muted = is_muted
        self.is_locked = is_locked
        self.clips = []
        self.volume = 1.0
        self.opacity = 1.0


class ClipInfo:
    """片段信息"""
    
    def __init__(self, clip_id: str, track_id: str, start_time: float, duration: float, media_path: str = ""):
        self.clip_id = clip_id
        self.track_id = track_id
        self.start_time = start_time
        self.duration = duration
        self.media_path = media_path
        self.effects = []
        self.selected = False


class MultiTrackEditor(QWidget):
    """多轨道编辑器"""
    
    track_added = pyqtSignal(str)
    track_removed = pyqtSignal(str)
    track_muted = pyqtSignal(str, bool)
    track_locked = pyqtSignal(str, bool)
    clip_added = pyqtSignal(str, str)
    clip_removed = pyqtSignal(str, str)
    clip_selected = pyqtSignal(str, str)
    clip_moved = pyqtSignal(str, str, float, float)
    
    def __init__(self):
        super().__init__()
        self._tracks: Dict[str, TrackInfo] = {}
        self._current_timeline_id: None
        self._selected_track_id: Optional[str] = None
        self._selected_clip_id: Optional[str] = None
        self._is_dragging = False
        self._drag_start_track_id = None
        self._drag_start_clip_id = None
        self._snap_enabled = True
        self._snap_threshold = 0.1  # 秒
        self._magnet_strength = 0.5  # 磁吸强度
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 轨道控制栏
        track_controls = QHBoxLayout()
        track_controls.setContentsMargins(8, 8, 8, 8)
        track_controls.setSpacing(8)
        
        add_video_track_btn = QPushButton("+ 视频轨道")
        add_video_track_btn.clicked.connect(self._add_video_track)
        track_controls.addWidget(add_video_track_btn)
        
        add_audio_track_btn = QPushButton("+ 音频轨道")
        add_audio_track_btn.clicked.connect(self._add_audio_track)
        track_controls.addWidget(add_audio_track_btn)
        
        add_subtitle_track_btn = QPushButton("+ 字幕轨道")
        add_subtitle_track_btn.clicked.connect(self._add_subtitle_track)
        track_controls.addWidget(add_subtitle_track_btn)
        
        track_controls.addStretch()
        layout.addLayout(track_controls)
        
        # 轨道列表区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        self._track_list_widget = QWidget()
        self._track_list_layout = QVBoxLayout(self._track_list_widget)
        self._track_list_layout.setContentsMargins(8, 8, 8, 8)
        self._track_list_layout.setSpacing(4)
        
        scroll_area.setWidget(self._track_list_widget)
        layout.addWidget(scroll_area)
        
        # 底部控制栏
        bottom_controls = QHBoxLayout()
        bottom_controls.setContentsMargins(8, 8, 8, 8)
        bottom_controls.setSpacing(8)
        
        snap_checkbox = QCheckBox("磁吸对齐")
        snap_checkbox.setChecked(self._snap_enabled)
        snap_checkbox.toggled.connect(self._set_snap_enabled)
        bottom_controls.addWidget(snap_checkbox)
        
        snap_threshold_label = QLabel("磁吸阈值:")
        snap_threshold_slider = QSlider(Qt.Orientation.Horizontal)
        snap_threshold_slider.setRange(1, 100)  # 0.01-1.0秒
        snap_threshold_slider.setValue(int(self._snap_threshold * 100))
        snap_threshold_slider.valueChanged.connect(self._set_snap_threshold)
        bottom_controls.addWidget(snap_threshold_label)
        bottom_controls.addWidget(snap_threshold_slider)
        
        magnet_strength_label = QLabel("磁吸强度:")
        magnet_strength_slider = QSlider(Qt.Orientation.Horizontal)
        magnet_strength_slider.setRange(1, 100)  # 0.01-1.0
        magnet_strength_slider.setValue(int(self._magnet_strength * 100))
        magnet_strength_slider.valueChanged.connect(self._set_magnet_strength)
        bottom_controls.addWidget(magnet_strength_label)
        bottom_controls.addWidget(magnet_strength_slider)
        
        bottom_controls.addStretch()
        layout.addLayout(bottom_controls)
        
        self._update_track_list()
    
    def _add_video_track(self):
        """添加视频轨道"""
        track_id = f"video_{len([t for t in self._tracks.values() if t.track_type == TrackType.VIDEO]) + 1}"
        track_info = TrackInfo(
            track_id=track_id,
            track_type=TrackType.VIDEO,
            name=f"视频轨道 {len([t for t in self._tracks.values() if t.track_type == TrackType.VIDEO]) + 1}",
            is_muted=False,
            is_locked=False
        )
        
        self._tracks[track_id] = track_info
        self.track_added.emit(track_id)
        self._update_track_list()
        logger.info(f"添加视频轨道: {track_id}")
    
    def _add_audio_track(self):
        """添加音频轨道"""
        track_id = f"audio_{len([t for t in self._tracks.values() if t.track_type == TrackType.AUDIO]) + 1}"
        track_info = TrackInfo(
            track_id=track_id,
            track_type=TrackType.AUDIO,
            name=f"音频轨道 {len([t for t in self._tracks.values() if t.track_type == TrackType.AUDIO]) + 1}",
            is_muted=False,
            is_locked=False
        )
        
        self._tracks[track_id] = track_info
        self.track_added.emit(track_id)
        self._update_track_list()
        logger.info(f"添加音频轨道: {track_id}")
    
    def _add_subtitle_track(self):
        """添加字幕轨道"""
        track_id = f"subtitle_{len([t for t in self._tracks.values() if t.track_type == TrackType.SUBTITLE]) + 1}"
        track_info = TrackInfo(
            track_id=track_id,
            track_type=TrackType.SUBTITLE,
            name=f"字幕轨道 {len([t for t in self._tracks.values() if t.track_type == TrackType.SUBTITLE]) + 1}",
            is_muted=False,
            is_locked=False
        )
        
        self._tracks[track_id] = track_info
        self.track_added.emit(track_id)
        self._update_track_list()
        logger.info(f"添加字幕轨道: {track_id}")
    
    def _set_snap_enabled(self, enabled: bool):
        """设置磁吸对齐"""
        self._snap_enabled = enabled
        logger.info(f"磁吸对齐: {'启用' if enabled else '禁用'}")
    
    def _set_snap_threshold(self, value: int):
        """设置磁吸阈值"""
        self._snap_threshold = value / 100.0
        logger.info(f"磁吸阈值: {self._snap_threshold:.2f}秒")
    
    def _set_magnet_strength(self, value: int):
        """设置磁吸强度"""
        self._magnet_strength = value / 100.0
        logger.info(f"磁吸强度: {self._magnet_strength:.2f}")
    
    def _update_track_list(self):
        """更新轨道列表UI"""
        # 清空现有轨道项
        while self._track_list_layout.count():
            child = self._track_list_layout.takeAt(0)
            if child:
                child.deleteLater()
        
        # 添加轨道项
        for track_id, track_info in self._tracks.items():
            track_widget = self._create_track_widget(track_info)
            self._track_list_layout.addWidget(track_widget)
        
        logger.info(f"更新轨道列表: {len(self._tracks)} 个轨道")
    
    def _create_track_widget(self, track_info: TrackInfo) -> QWidget:
        """创建轨道控件"""
        widget = QWidget()
        widget.setFixedHeight(60)
        
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 轨道类型图标
        type_icon = "🎬" if track_info.track_type == TrackType.VIDEO else "🎵" if track_info.track_type == TrackType.AUDIO else "📝"
        
        type_label = QLabel(type_icon)
        type_label.setFixedWidth(30)
        layout.addWidget(type_label)
        
        # 轨道名称
        name_label = QLabel(track_info.name)
        name_label.setMinimumWidth(120)
        layout.addWidget(name_label)
        
        # 轨道控制按钮
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(4)
        
        # 静音按钮
        mute_btn = QPushButton("🔇" if track_info.is_muted else "🔊")
        mute_btn.setFixedWidth(28)
        mute_btn.setCheckable(True)
        mute_btn.setChecked(track_info.is_muted)
        mute_btn.clicked.connect(lambda: self._toggle_track_mute(track_info.track_id))
        controls_layout.addWidget(mute_btn)
        
        # 锁定按钮
        lock_btn = QPushButton("🔓" if track_info.is_locked else "🔓")
        lock_btn.setFixedWidth(28)
        lock_btn.setCheckable(True)
        lock_btn.setChecked(track_info.is_locked)
        lock_btn.clicked.connect(lambda: self._toggle_track_lock(track_info.track_id))
        controls_layout.addWidget(lock_btn)
        
        # 删除按钮
        delete_btn = QPushButton("🗑️")
        delete_btn.setFixedWidth(28)
        delete_btn.clicked.connect(lambda: self._remove_track(track_info.track_id))
        controls_layout.addWidget(delete_btn)
        
        layout.addLayout(controls_layout)
        
        return widget
    
    def _toggle_track_mute(self, track_id: str):
        """切换轨道静音"""
        if track_id in self._tracks:
            self._tracks[track_id].is_muted = not self._tracks[track_id].is_muted
            self.track_muted.emit(track_id, self._tracks[track_id].is_muted)
            self._update_track_list()
            logger.info(f"轨道静音切换: {track_id}, 静音: {self._tracks[track_id].is_muted}")
    
    def _toggle_track_lock(self, track_id: str):
        """切换轨道锁定"""
        if track_id in self._tracks:
            self._tracks[track_id].is_locked = not self._tracks[track_id].is_locked
            self.track_locked.emit(track_id, self._tracks[track_id].is_locked)
            self._update_track_list()
            logger.info(f"轨道锁定切换: {track_id}, 锁定: {self._tracks[track_id].is_locked}")
    
    def _remove_track(self, track_id: str):
        """删除轨道"""
        if track_id in self._tracks:
            del self._tracks[track_id]
            self.track_removed.emit(track_id)
            self._update_track_list()
            logger.info(f"删除轨道: {track_id}")
    
    def get_tracks(self) -> Dict[str, TrackInfo]:
        """获取所有轨道"""
        return self._tracks.copy()
    
    def get_track(self, track_id: str) -> Optional[TrackInfo]:
        """获取指定轨道"""
        return self._tracks.get(track_id)
    
    def set_current_timeline(self, timeline_id: str) -> None:
        """设置当前时间线"""
        self._current_timeline_id = timeline_id
        self._tracks.clear()
        self._update_track_list()
        logger.info(f"设置当前时间线: {timeline_id}")
    
    def get_track_count(self) -> Dict[str, int]:
        """获取轨道统计"""
        video_count = len([t for t in self._tracks.values() if t.track_type == TrackType.VIDEO])
        audio_count = len([t for t in self._tracks.values() if t.track_type == TrackType.AUDIO])
        subtitle_count = len([t for t in self._tracks.values() if t.track_type == TrackType.SUBTITLE])
        
        return {
            'total': len(self._tracks),
            'video': video_count,
            'audio': audio_count,
            'subtitle': subtitle_count
        }