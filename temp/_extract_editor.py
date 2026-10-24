"""Extract EditorModule from modules.py into editor_module.py"""
import os

base = r'c:\Users\Administrator\Desktop\拾光剪影\app\modules\lego'
src_path = os.path.join(base, 'modules.py')
dst_path = os.path.join(base, 'editor_module.py')

with open(src_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# EditorModule: lines 3118-9248 (0-indexed: 3117-9247)
editor_lines = lines[3117:9248]

header = '''"""
编辑器模块 (EditorModule)
=========================
从 modules.py 拆分出来的独立编辑器模块。
所有导入均为懒加载，仅在用户打开剪辑页时才加载重型库。
"""

from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
import os
import json
import random
import logging
import importlib as _importlib
from datetime import datetime
import subprocess
import sys as _sys
import threading
import queue
import time

logger = logging.getLogger("AI短剧编辑器.editor_module")

# ═══════════════════════════════════════════════════════════════
# 懒加载工具类（从 modules.py 复用）
# ═══════════════════════════════════════════════════════════════


class _LazyModuleProxy:
    """延迟加载模块代理。仅在首次访问属性或调用时才真正导入。"""
    __slots__ = ('_name', '_module')

    def __init__(self, name: str):
        object.__setattr__(self, '_name', name)
        object.__setattr__(self, '_module', None)

    def _load(self):
        if object.__getattribute__(self, '_module') is None:
            object.__setattr__(self, '_module',
                               _importlib.import_module(object.__getattribute__(self, '_name')))

    def __getattr__(self, name):
        self._load()
        return getattr(object.__getattribute__(self, '_module'), name)

    def __call__(self, *args, **kwargs):
        self._load()
        return object.__getattribute__(self, '_module')(*args, **kwargs)


class _LazyClassProxy:
    """延迟加载类代理。支持实例化：proxy() 即 Cls()。"""
    __slots__ = ('_module_name', '_class_name', '_cls')

    def __init__(self, module_name: str, class_name: str):
        object.__setattr__(self, '_module_name', module_name)
        object.__setattr__(self, '_class_name', class_name)
        object.__setattr__(self, '_cls', None)

    def _load(self):
        if object.__getattribute__(self, '_cls') is None:
            mod = _importlib.import_module(object.__getattribute__(self, '_module_name'))
            object.__setattr__(self, '_cls',
                               getattr(mod, object.__getattribute__(self, '_class_name')))

    def __call__(self, *args, **kwargs):
        self._load()
        return object.__getattribute__(self, '_cls')(*args, **kwargs)

    def __getattr__(self, name):
        self._load()
        return getattr(object.__getattribute__(self, '_cls'), name)

    def __repr__(self):
        return (f'<LazyClass({object.__getattribute__(self, "_module_name")}'
                f'.{object.__getattribute__(self, "_class_name")})>')


def _lazy_import(module_name: str):
    """便捷工厂函数：创建模块懒加载代理"""
    return _LazyModuleProxy(module_name)


# ═══════════════════════════════════════════════════════════════
# 重型第三方库懒加载
# ═══════════════════════════════════════════════════════════════

np = _lazy_import('numpy')
librosa = _lazy_import('librosa')

_moviepy_editor = _lazy_import('moviepy.editor')
VideoFileClip = None
concatenate_videoclips = None


def _get_VideoFileClip():
    return _moviepy_editor.VideoFileClip


def _get_concatenate_videoclips():
    return _moviepy_editor.concatenate_videoclips


# ═══════════════════════════════════════════════════════════════
# PyQt6 导入
# ═══════════════════════════════════════════════════════════════

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize, QUrl, QPoint, QMimeData
from PyQt6.QtGui import (
    QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics,
    QPolygon, QShortcut, QKeySequence, QDrag
)
from PyQt6.QtWidgets import (
    QDialog,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QProgressBar, QListWidget,
    QListWidgetItem, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QInputDialog, QTabWidget, QCheckBox, QSlider,
    QTreeWidget, QTreeWidgetItem, QMenu, QToolButton, QApplication, QSizePolicy,
    QFormLayout, QSpacerItem, QToolTip
)
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget

# ═══════════════════════════════════════════════════════════════
# 项目内核导入
# ═══════════════════════════════════════════════════════════════

from .core import EventBus, EventType, MasterClock, DataBus
from .skill_engine import SkillEngine, Skill
from .account_skills import (
    AccountDataCollectSkill, AccountAnalysisSkill,
    PublishContentSkill, MatrixPublishSkill, register_account_skills
)

# 确保 app/ 在 sys.path 中以兼容 core.xxx 导入
_app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _app_root not in _sys.path:
    _sys.path.insert(0, _app_root)

# Core 管理器懒加载
project_manager = _lazy_import('core.project_manager')
asset_manager = _lazy_import('core.asset_manager')
timeline_manager = _lazy_import('core.timeline_manager')
effect_manager = _lazy_import('core.effect_manager')
transition_manager = _lazy_import('core.transition_manager')

EditorScheduler = _LazyClassProxy('core.editor_scheduler', 'EditorScheduler')
AudioManager = _LazyClassProxy('core.audio_manager', 'AudioManager')
SubtitleManager = _LazyClassProxy('core.subtitle_manager', 'SubtitleManager')
PresetManager = _LazyClassProxy('core.preset_manager', 'PresetManager')
PluginManager = _LazyClassProxy('core.plugin_manager', 'PluginManager')

# TOP 0级剪辑引擎
try:
    from .top0_integration import Top0VideoProcessor
    TOP0_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"TOP 0级引擎导入失败: {e}")
    TOP0_ENGINE_AVAILABLE = False

# 爆款优化引擎
try:
    from .viral_optimization_engine import ViralOptimizationEngine, Platform, VideoFeatures
    VIRAL_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"爆款优化引擎导入失败: {e}")
    VIRAL_ENGINE_AVAILABLE = False

# 工具类
from .utils.thread_pool import ThreadPool
from .utils.hardware_monitor import (
    HardwareDetector, PerformanceMonitor,
    hardware_detector, hardware_config, performance_monitor,
)

# BaseModule —— 从 modules.py 导入（已在模块加载时定义）
from .modules import BaseModule


'''

# Write the new file
with open(dst_path, 'w', encoding='utf-8') as f:
    f.write(header)
    f.writelines(editor_lines)

print(f"Written {len(editor_lines)} lines to: {dst_path}")
print("Done!")
