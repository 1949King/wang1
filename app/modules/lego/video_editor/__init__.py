"""
视频编辑器集成模块
==================
将所有新开发的编辑器集成到主窗口，提供统一的专业编辑界面
"""

from typing import Dict, Any, Optional
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter
from PyQt6.QtWidgets import QTabWidget, QPushButton, QLabel, QStackedWidget
import logging

from .multi_track_editor import MultiTrackEditor
from .frame_editor import FrameEditor
from .professional_editor import ProfessionalEditor
from .timeline_ui import TimelineView
from .undo_manager import undo_manager

logger = logging.getLogger("AI短剧编辑器.video_editor_integration")