"""
帧级精确编辑器
==================
支持波纹编辑、滚动编辑、逐帧精确编辑、关键帧编辑等专业编辑功能
"""

from typing import Dict, List, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider, QSpinBox
import logging

from app.core.timeline import timeline_core

logger = logging.getLogger("AI短剧编辑器.frame_editor")


class EditMode:
    """编辑模式"""
    RIPPLE = "ripple"  # 波纹编辑
    ROLL = "roll"  # 滚动编辑
    FRAME = "frame"  # 逐帧编辑
    KEYFRAME = "keyframe"  # 关键帧编辑


class FrameEditor(QObject):
    """帧级精确编辑器"""
    
    frame_selected = pyqtSignal(str, float)
    frame_moved = pyqtSignal(str, float, float)
    frame_duration_changed = pyqtSignal(str, float)
    keyframe_added = pyqtSignal(str, float)
    
    def __init__(self):
        super().__init__()
        self._current_timeline_id = None
        self._selected_clip_id = None
        self._selected_frame_time = 0.0
        self._edit_mode = EditMode.FRAME
        self._ripple_enabled = True
        self._snap_to_frame = True
        self._snap_threshold = 0.1  # 秒
        
        self._undo_stack = []
        self._redo_stack = []
        self._max_undo_depth = 50
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 编辑模式选择
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(8)
        
        ripple_btn = QPushButton("🌊 波纹编辑")
        ripple_btn.setCheckable(True)
        ripple_btn.setChecked(self._edit_mode == EditMode.RIPPLE)
        ripple_btn.clicked.connect(lambda: self._set_edit_mode(EditMode.RIPPLE))
        mode_layout.addWidget(ripple_btn)
        
        roll_btn = QPushButton("🔄 滚动编辑")
        roll_btn.setCheckable(True)
        roll_btn.setChecked(self._edit_mode == EditMode.ROLL)
        roll_btn.clicked.connect(lambda: self._set_edit_mode(EditMode.ROLL))
        mode_layout.addWidget(roll_btn)
        
        frame_btn = QPushButton("🎯 逐帧编辑")
        frame_btn.setCheckable(True)
        frame_btn.setChecked(self._edit_mode == EditMode.FRAME)
        frame_btn.clicked.connect(lambda: self._set_edit_mode(EditMode.FRAME))
        mode_layout.addWidget(frame_btn)
        
        keyframe_btn = QPushButton("🎬 关键帧编辑")
        keyframe_btn.setCheckable(True)
        keyframe_btn.setChecked(self._edit_mode == EditMode.KEYFRAME)
        keyframe_btn.clicked.connect(lambda: self._set_edit_mode(EditMode.KEYFRAME))
        mode_layout.addWidget(keyframe_btn)
        
        mode_layout.addStretch()
        layout.addLayout(mode_layout)
        
        # 时间轴控制
        timeline_controls = QHBoxLayout()
        timeline_controls.setSpacing(8)
        
        prev_frame_btn = QPushButton("⬅️ 上一帧")
        prev_frame_btn.clicked.connect(self._go_to_prev_frame)
        timeline_controls.addWidget(prev_frame_btn)
        
        next_frame_btn = QPushButton("➡️ 下一帧")
        next_frame_btn.clicked.connect(self._go_to_next_frame)
        timeline_controls.addWidget(next_frame_btn)
        
        time_display = QLabel("00:00:000")
        time_display.setStyleSheet("font-family: monospace; font-size: 14px; color: #808080;")
        timeline_controls.addWidget(time_display)
        
        timeline_controls.addStretch()
        layout.addLayout(timeline_controls)
        
        # 编辑控制
        edit_controls = QHBoxLayout()
        edit_controls.setSpacing(8)
        
        undo_btn = QPushButton("↩️ 撤销")
        undo_btn.clicked.connect(self._undo)
        edit_controls.addWidget(undo_btn)
        
        redo_btn = QPushButton("↪️ 重做")
        redo_btn.clicked.connect(self._redo)
        edit_controls.addWidget(redo_btn)
        
        edit_controls.addStretch()
        layout.addLayout(edit_controls)
        
        # 精确控制
        precision_controls = QHBoxLayout()
        precision_controls.setSpacing(8)
        
        frame_step_label = QLabel("帧步长:")
        frame_step_spinbox = QSpinBox()
        frame_step_spinbox.setRange(1, 100)
        frame_step_spinbox.setValue(1)
        frame_step_spinbox.setSuffix(" 帧")
        precision_controls.addWidget(frame_step_label)
        precision_controls.addWidget(frame_step_spinbox)
        
        snap_to_frame_checkbox = QLabel("吸附到帧:")
        snap_to_frame_checkbox = QPushButton("启用")
        snap_to_frame_checkbox.setCheckable(True)
        snap_to_frame_checkbox.setChecked(self._snap_to_frame)
        snap_to_frame_checkbox.clicked.connect(self._toggle_snap_to_frame)
        precision_controls.addWidget(snap_to_frame_checkbox)
        
        precision_controls.addStretch()
        layout.addLayout(precision_controls)
        
        # 状态栏
        status_bar = QHBoxLayout()
        status_bar.setSpacing(16)
        
        mode_label = QLabel(f"模式: {self._get_mode_name()}")
        status_bar.addWidget(mode_label)
        
        position_label = QLabel("位置: 0.000s")
        status_bar.addWidget(position_label)
        
        status_bar.addStretch()
        layout.addLayout(status_bar)
    
    def _set_edit_mode(self, mode: EditMode) -> None:
        """设置编辑模式"""
        self._edit_mode = mode
        logger.info(f"编辑模式设置为: {self._get_mode_name()}")
    
    def _get_mode_name(self) -> str:
        """获取模式名称"""
        mode_names = {
            EditMode.RIPPLE: "波纹编辑",
            EditMode.ROLL: "滚动编辑",
            EditMode.FRAME: "逐帧编辑",
            EditMode.KEYFRAME: "关键帧编辑"
        }
        return mode_names.get(self._edit_mode, "未知模式")
    
    def _go_to_prev_frame(self) -> None:
        """跳转到上一帧"""
        if not self._current_timeline_id:
            return
        
        timeline = timeline_core.get_current_timeline()
        if not timeline:
            return
        
        current_frame = self._selected_frame_time
        target_frame = max(0, current_frame - self._snap_threshold)
        
        self._selected_frame_time = target_frame
        self.frame_selected.emit(self._selected_clip_id, target_frame)
        self._update_time_display()
        logger.info(f"跳转到上一帧: {target_frame:.3f}秒")
    
    def _go_to_next_frame(self) -> None:
        """跳转到下一帧"""
        if not self._current_timeline_id:
            return
        
        timeline = timeline_core.get_current_timeline()
        if not timeline:
            return
        
        current_frame = self._selected_frame_time
        total_duration = timeline.get('settings', {}).get('duration', 0)
        target_frame = min(total_duration, current_frame + self._snap_threshold)
        
        self._selected_frame_time = target_frame
        self.frame_selected.emit(self._selected_clip_id, target_frame)
        self._update_time_display()
        logger.info(f"跳转到下一帧: {target_frame:.3f}秒")
    
    def _update_time_display(self) -> None:
        """更新时间显示"""
        time_str = f"{self._selected_frame_time:06.3f}"
        self.findChild(QLabel, "时间显示").setText(time_str)
    
    def _toggle_snap_to_frame(self) -> None:
        """切换帧吸附"""
        self._snap_to_frame = not self._snap_to_frame
        logger.info(f"帧吸附: {'启用' if self._snap_to_frame else '禁用'}")
    
    def _undo(self) -> None:
        """撤销操作"""
        if not self._undo_stack:
            return
        
        last_state = self._undo_stack.pop()
        if last_state:
            self._redo_stack.append(last_state)
            logger.info(f"撤销操作，剩余撤销步数: {len(self._undo_stack)}")
    
    def _redo(self) -> None:
        """重做操作"""
        if not self._redo_stack:
            return
        
        next_state = self._redo_stack.pop()
        if next_state:
            self._undo_stack.append(next_state)
            logger.info(f"重做操作，剩余重做步数: {len(self._redo_stack)}")
    
    def set_timeline(self, timeline_id: str) -> None:
        """设置时间线"""
        self._current_timeline_id = timeline_id
        timeline = timeline_core.get_current_timeline()
        
        if timeline:
            self._selected_frame_time = 0.0
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._update_time_display()
            logger.info(f"设置时间线: {timeline_id}")
    
    def get_edit_state(self) -> Dict[str, Any]:
        """获取编辑状态"""
        return {
            'edit_mode': self._get_mode_name(),
            'selected_frame_time': self._selected_frame_time,
            'undo_available': len(self._undo_stack) > 0,
            'redo_available': len(self._redo_stack) > 0,
            'snap_enabled': self._snap_to_frame,
            'snap_threshold': self._snap_threshold
        }
    
    def save_state(self) -> None:
        """保存当前状态到撤销栈"""
        state = {
            'timeline_id': self._current_timeline_id,
            'clip_id': self._selected_clip_id,
            'frame_time': self._selected_frame_time,
            'edit_mode': self._edit_mode
        }
        
        if len(self._undo_stack) >= self._max_undo_depth:
            self._undo_stack.pop(0)
        
        self._undo_stack.append(state)
        logger.info(f"保存状态到撤销栈，当前深度: {len(self._undo_stack)}")