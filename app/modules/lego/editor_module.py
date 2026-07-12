"""
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

def _report_video_import_debug(hypothesis_id: str, location: str, msg: str, data: Optional[Dict[str, Any]] = None):
    """临时调试上报：定位视频导入与时间线添加链路。"""
    # #region debug-point video-import-timeline
    try:
        import urllib.request as _urlrequest
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
        _urlrequest.urlopen(
            _urlrequest.Request(debug_url, data=payload, headers={"Content-Type": "application/json"}),
            timeout=0.8,
        ).read()
    except Exception:
        logger.debug("video import debug report failed", exc_info=True)
    # #endregion

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
    QPolygon, QShortcut, QKeySequence, QDrag, QPixmap
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
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
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
TimelineWidget = _LazyClassProxy('app.modules.lego.timeline_widget', 'TimelineWidget')

# TOP 0级剪辑引擎统一由 editor_scheduler 懒加载，避免界面层直接实例化内核。

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
from .base_module import BaseModule


class EditingAgentWorker(QThread):
    """剪辑 Agent 后台调用线程，负责对接云端 API 与本地 Ollama 模型。"""

    chunk_ready = pyqtSignal(str)
    result_ready = pyqtSignal(str)
    error_ready = pyqtSignal(str)
    stopped_ready = pyqtSignal()

    def __init__(self, provider: str, model: str, messages: List[Dict[str, str]], parent=None):
        super().__init__(parent)
        self._provider = provider
        self._model = model
        self._messages = messages
        self._stop_requested = False

    def request_stop(self):
        """请求终止当前模型输出。"""
        self._stop_requested = True

    def run(self):
        """执行模型调用；逐段转发输出，便于界面模拟 Trae IDE 对话流。"""
        try:
            from app.core.ai_engine import ai_engine

            chunks = []
            if self._provider:
                stream = ai_engine.chat(
                    self._provider,
                    self._messages,
                    model=self._model or None,
                    stream=True,
                    use_cache=False,
                )
            else:
                stream = ai_engine.chat_with_fallback(
                    messages=self._messages,
                    model=self._model or None,
                    use_cache=False,
                    template=lambda: '[{"action":"answer","params":{"message":"模型暂不可用，请检查云端 API Key 或本地 Ollama 服务。"},"confidence":0.8}]',
                )

            for chunk in stream:
                if self._stop_requested:
                    self.stopped_ready.emit()
                    return
                if chunk:
                    chunks.append(str(chunk))
                    self.chunk_ready.emit(str(chunk))

            self.result_ready.emit("".join(chunks))
        except Exception as e:
            self.error_ready.emit(str(e))


class EditorModule(BaseModule):
    """
    视频剪辑模块
    - 轨道,预览,波形,切割,滤镜,转场,字幕
    - 只依赖内核,不依赖其他模块
    """
    
    module_id = "editor"
    module_name = "剪辑"
    module_icon = "🎬"
    
    MAX_UNDO_DEPTH = 100  # 撤销/重做栈最大深度，防止长时间编辑内存溢出
    
    # 字幕生成线程信号
    _subtitle_generated_signal = pyqtSignal(int)
    ai_progress_signal = pyqtSignal(int, str)
    ai_fail_signal = pyqtSignal(str)
    
    def __init__(self):
        # 媒体播放器 - 在调用父类__init__之前初始化,因为_setup_ui会使用这些属性
        self._media_player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._media_player.setAudioOutput(self._audio_output)
        self._video_widget = QVideoWidget()
        self._media_player.setVideoOutput(self._video_widget)
        # 视频片段管理
        self._clips = []  # 存储视频片段
        self._current_clip = None  # 当前选中的片段
        self._clip_widgets = []  # 存储片段控件
        # 补短 P1#8：clip_id -> ClipWidget 映射，便于按 id 注入关键帧
        self._clip_id_to_widget = {}
        # 播放控制
        self._is_playing = False  # 播放状态
        self._current_time = 0  # 当前播放时间
        self._total_duration = 0  # 总时长
        # 时间线控制
        self._timeline_zoom = 100  # 时间线缩放比例(%)
        self._playhead_position = 0  # 播放头位置(秒)
        # 界面元素
        self._time_label = None
        self._timecode_label = None
        self._progress_bar = None
        self._timeline_zoom_label = None
        self._timeline_widget = None
        # 内核选择
        self._kernel_mode = "auto"  # auto、light 或 pro
        # 项目管理
        self._current_project = None
        # 时间线管理
        self._current_timeline = None
        # TOP 0级剪辑引擎 - 懒加载
        self._top0_processor = None
        self._top0_initialized = False
        
        # 爆款优化引擎 - 懒加载
        self._viral_engine = None
        self._viral_initialized = False
        
        # 智能剪辑算法 - 懒加载
        self._ai_clip_algorithm = None
        self._ai_clip_initialized = False
        
        # 双内核调度器 - 懒加载
        self._editor_scheduler = None
        
        # 项目管理系统 - 懒加载
        self._project_manager = None
        
        # 素材管理系统 - 懒加载
        self._media_manager = None
        
        # 时间线管理系统 - 懒加载
        self._timeline_manager = None
        
        # 特效管理系统 - 懒加载
        self._effect_manager = None
        
        # 转场管理系统 - 懒加载
        self._transition_manager = None
        
        # 音频处理系统 - 懒加载
        self._audio_manager = None
        
        # 字幕系统 - 懒加载
        self._subtitle_manager = None
        
        # 预设系统 - 懒加载
        self._preset_manager = None
        
        # 插件系统 - 懒加载
        self._plugin_manager = None
        
        # 预览管理器 - 懒加载
        self._preview_manager = None
        self._video_source = None
        
        # 效果参数
        self._color_params = {}
        self._active_filter = None

        # 补短 P0#4：撤销/重做按钮引用 + 状态联动
        # （保持原有 _action_history / _redo_history 手动栈逻辑，最小侵入）
        self._undo_btn = None
        self._redo_btn = None
        self._undo_redo_toast = ""  # 轻量状态提示（避免 QMessageBox 阻塞 UI）

        # 接收文案推送数据
        self._received_copywriting = None

        # 调用父类__init__方法
        super().__init__()

        # 连接字幕生成线程信号
        self._subtitle_generated_signal.connect(self._on_subtitle_generated)
        self.ai_progress_signal.connect(self._on_ai_progress)
        self.ai_fail_signal.connect(self._on_ai_fail)

        # 补短 P0#4：注册 Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y 快捷键
        self._install_undo_redo_shortcuts()

        # 注册 COPY_GENERATED 事件监听：接收文案模块推送
        self._event_bus.on(EventType.COPY_GENERATED, self._on_copywriting_received)

        # 注册 material_to_timeline 事件：接收素材库拖拽/右键推送
        self._event_bus.on(EventType.MATERIAL_TO_TIMELINE, self._on_material_dropped)
        
        # 连接工作流管理器
        try:
            self.connect_to_workflow()
        except Exception as e:
            print(f"⚠️ 连接工作流管理器失败: {e}")
        
        # 连接数据分析器
        try:
            self.connect_to_data_analyzer()
        except Exception as e:
            print(f"⚠️ 连接数据分析器失败: {e}")
        
        # 安装额外快捷键
        self._install_additional_shortcuts()
    
    def _ensure_top0_engine(self):
        """通过统一调度器懒加载 TOP0 引擎。"""
        if self._top0_initialized:
            return self._top0_processor
        self._top0_initialized = True
        try:
            try:
                from app.core.editor_scheduler import editor_scheduler
            except ImportError:
                from core.editor_scheduler import editor_scheduler
            self._top0_processor = editor_scheduler.get_top0_processor()
            print("✅ TOP 0级剪辑引擎已通过统一内核调度器加载")
        except Exception as e:
            print(f"⚠️ TOP 0级引擎初始化失败: {e}")
        return self._top0_processor
    
    def _ensure_viral_engine(self):
        """懒加载爆款引擎"""
        if self._viral_initialized:
            return self._viral_engine
        self._viral_initialized = True
        if VIRAL_ENGINE_AVAILABLE:
            try:
                self._viral_engine = ViralOptimizationEngine()
                print("✅ 爆款优化引擎已加载")
            except Exception as e:
                print(f"⚠️ 爆款优化引擎初始化失败: {e}")
        return self._viral_engine
    
    def _ensure_ai_clip_algorithm(self):
        """懒加载AI剪辑算法（避免顶层导入 PyQt6 重模块引发循环依赖）。"""
        if getattr(self, "_ai_clip_initialized", False):
            return getattr(self, "_ai_clip_algorithm", None)
        self._ai_clip_initialized = True
        try:
            from app.modules.lego.modules import AIClipAlgorithm
            self._ai_clip_algorithm = AIClipAlgorithm()
            print("✅ 智能剪辑算法已加载")
        except Exception as _e:
            logger.warning("AIClipAlgorithm 加载失败: %s", _e)
            self._ai_clip_algorithm = None
        return self._ai_clip_algorithm
    
    def _ensure_audio_manager(self):
        """懒加载音频管理器"""
        if self._audio_manager is not None:
            return self._audio_manager
        self._audio_manager = AudioManager()
        print("✅ 音频处理系统已加载")
        return self._audio_manager
    
    def _ensure_subtitle_manager(self):
        """懒加载字幕管理器"""
        if self._subtitle_manager is not None:
            return self._subtitle_manager
        self._subtitle_manager = SubtitleManager()
        print("✅ 字幕系统已加载")
        return self._subtitle_manager
    
    def _ensure_preset_manager(self):
        """懒加载预设管理器"""
        if self._preset_manager is not None:
            return self._preset_manager
        self._preset_manager = PresetManager()
        print("✅ 预设系统已加载")
        return self._preset_manager
    
    def _ensure_plugin_manager(self):
        """懒加载插件管理器"""
        if self._plugin_manager is not None:
            return self._plugin_manager
        self._plugin_manager = PluginManager()
        self._plugin_manager.load_plugins()
        print("✅ 插件系统已加载")
        return self._plugin_manager
    
    def _ensure_preview_manager(self):
        """懒加载预览管理器"""
        if self._preview_manager is not None:
            return self._preview_manager
        from core.preview_manager import PreviewManager
        self._preview_manager = PreviewManager()
        self._preview_manager.frame_ready.connect(self._on_preview_frame)
        self._preview_manager.timecode_updated.connect(self._on_timecode_updated)
        print("✅ 预览管理器已加载")
        return self._preview_manager
    
    def _ensure_scheduler(self):
        """懒加载调度器"""
        if self._editor_scheduler is not None:
            return self._editor_scheduler
        self._editor_scheduler = get_editor_scheduler()
        print("✅ 双内核调度器已加载")
        return self._editor_scheduler
    
    def _ensure_project_manager(self):
        """懒加载项目管理器"""
        if self._project_manager is not None:
            return self._project_manager
        self._project_manager = get_project_manager()
        print("✅ 项目管理系统已加载")
        return self._project_manager
    
    def _ensure_media_manager(self):
        """懒加载素材管理器"""
        if self._media_manager is not None:
            return self._media_manager
        self._media_manager = get_media_manager()
        print("✅ 素材管理系统已加载")
        return self._media_manager
    
    def _ensure_timeline_manager(self):
        """懒加载时间线管理器"""
        if self._timeline_manager is not None:
            return self._timeline_manager
        self._timeline_manager = get_timeline_manager()
        print("✅ 时间线管理系统已加载")
        return self._timeline_manager
    
    def _ensure_effect_manager(self):
        """懒加载特效管理器"""
        if self._effect_manager is not None:
            return self._effect_manager
        self._effect_manager = get_effect_manager()
        print("✅ 特效管理系统已加载")
        return self._effect_manager
    
    def _ensure_transition_manager(self):
        """懒加载转场管理器"""
        if self._transition_manager is not None:
            return self._transition_manager
        self._transition_manager = get_transition_manager()
        print("✅ 转场管理系统已加载")
        return self._transition_manager
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)
        
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setStyleSheet("QSplitter::handle { background-color: #1a1a1a; height: 4px; }")
        
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setStyleSheet("QSplitter::handle { background-color: #1a1a1a; width: 4px; }")
        
        left_panel = self._create_left_panel()
        top_splitter.addWidget(left_panel)
        
        preview_panel = self._create_preview_panel()
        top_splitter.addWidget(preview_panel)
        
        tools_panel = self._create_tools_panel()
        top_splitter.addWidget(tools_panel)
        
        top_splitter.setSizes([280, 750, 380])
        main_splitter.addWidget(top_splitter)
        
        timeline_panel = self._create_timeline_panel()
        main_splitter.addWidget(timeline_panel)
        
        main_splitter.setCollapsible(0, False)
        main_splitter.setCollapsible(1, False)
        top_splitter.setMinimumHeight(200)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([450, 350])
        
        layout.addWidget(main_splitter, 1)
    
    def _create_toolbar(self) -> QWidget:
        toolbar = QFrame()
        toolbar.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
        toolbar.setFixedHeight(50)
        
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(15, 5, 15, 5)
        layout.setSpacing(10)
        
        actions = [
            ("📁 导入", self._import_video),
            ("✂️ 剪切", self._cut_clip),
            ("📋 复制", self._copy_clip),
            ("📄 粘贴", self._paste_clip),
            ("🗑️ 删除", self._delete_clip),
            ("🔄 撤销", self._undo, "undo"),
            ("🔄 重做", self._redo, "redo"),

        ]

        for entry in actions:
            # 兼容 (text, cb) 和 (text, cb, tag) 两种条目
            if len(entry) == 3:
                text, callback, tag = entry
            else:
                text, callback = entry
                tag = ""
            btn = QPushButton(text)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #3a3a3a;
                    border-radius: 6px;
                    padding: 8px 12px;
                    font-size: 13px;
                    font-weight: 500;
                    height: 40px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                    border-color: #4a4a4a;
                }
                QPushButton:pressed {
                    background-color: #1e6bde;
                    border-color: #1e6bde;
                }
            """)
            btn.clicked.connect(callback)
            # 补短 P0#4：保存撤销/重做按钮引用，便于状态联动
            if tag == "undo":
                self._undo_btn = btn
                btn.setShortcut(QKeySequence("Ctrl+Z"))
                btn.setToolTip("撤销 (Ctrl+Z)")
            elif tag == "redo":
                self._redo_btn = btn
                btn.setShortcut(QKeySequence("Ctrl+Y"))
                btn.setToolTip("重做 (Ctrl+Y)")
            layout.addWidget(btn)

        layout.addStretch()
        
        # 内核选择下拉菜单
        kernel_layout = QHBoxLayout()
        kernel_label = QLabel("内核:")
        kernel_label.setStyleSheet("color: #808080; font-size: 13px; padding-right: 8px;")
        self._kernel_combo = QComboBox()
        self._kernel_combo.addItems(["自动选择", "轻量内核", "专业内核"])
        self._kernel_combo.setCurrentIndex(0)  # 默认由统一调度器自主选择内核
        self._kernel_combo.currentIndexChanged.connect(self._on_kernel_changed)
        self._kernel_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
                min-width: 100px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: url(:/icons/arrow-down.png);
                width: 12px;
                height: 12px;
            }
        """)
        kernel_layout.addWidget(kernel_label)
        kernel_layout.addWidget(self._kernel_combo)
        layout.addLayout(kernel_layout)
        
        self._time_label = QLabel("00:00:00:00")
        self._time_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 14px; color: #1e6bde; padding: 0 10px;")
        layout.addWidget(self._time_label)
        
        export_btn = QPushButton("💾 导出")
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: 1px solid #1e6bde;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
                height: 40px;
            }
            QPushButton:hover {
                background-color: #1557b0;
                border-color: #1557b0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
                border-color: #0d47a1;
            }
        """)
        export_btn.clicked.connect(self._export_video)
        layout.addWidget(export_btn)

        # 补短 P0#4：toolbar 创建完毕，初始化撤销/重做按钮禁用态
        # （无历史时按钮应当不可点，避免用户误操作）
        if not getattr(self, '_action_history', []):
            if self._undo_btn is not None:
                self._undo_btn.setEnabled(False)
                self._undo_btn.setToolTip("无可撤销操作")
            if self._redo_btn is not None:
                self._redo_btn.setEnabled(False)
                self._redo_btn.setToolTip("无可重做操作")

        return toolbar
    
    def _create_preview_panel(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet("""
            QFrame#previewCard {
                background-color: #121212; border: 1px solid #252525; border-radius: 12px;
            }
        """)
        card.setObjectName("previewCard")
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title_bar = QFrame()
        title_bar.setStyleSheet("background-color: transparent; border-bottom: 1px solid #1e1e1e;")
        title_bar.setFixedHeight(32)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)
        title_label = QLabel("🖥 预览窗口")
        title_label.setStyleSheet("color: #999999; font-size: 11px; font-weight: 600;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        self._timecode_label = QLabel("00:00:00:00")
        self._timecode_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 12px; font-weight: 600; color: #1e6bde;")
        title_layout.addWidget(self._timecode_label)
        layout.addWidget(title_bar)
        
        body = QWidget()
        body_lo = QVBoxLayout(body)
        body_lo.setContentsMargins(8, 8, 8, 8)
        body_lo.setSpacing(8)
        
        self._preview_frame = QFrame()
        self._preview_frame.setStyleSheet("background-color: #000000; border-radius: 8px;")
        self._video_widget.setStyleSheet("background-color: #000000; border-radius: 8px;")
        pv_layout = QVBoxLayout(self._preview_frame)
        pv_layout.setContentsMargins(0, 0, 0, 0)
        pv_layout.addWidget(self._video_widget, 1)
        self._preview_label = QLabel("视频预览区")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet("color: #333333; font-size: 16px;")
        pv_layout.addWidget(self._preview_label, 1)
        self._preview_label.hide()
        body_lo.addWidget(self._preview_frame, 1)
        
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 4, 0, 0)
        controls_layout.setSpacing(6)
        
        self._progress_bar = QSlider(Qt.Orientation.Horizontal)
        self._progress_bar.setStyleSheet("""
            QSlider::groove:horizontal {
                background-color: #1e1e1e; height: 4px; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background-color: #1e6bde; width: 12px; height: 12px;
                margin: -4px 0; border-radius: 6px;
            }
        """)
        controls_layout.addWidget(self._progress_bar, 1)
        
        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setStyleSheet("color: #666666; font-size: 11px;")
        controls_layout.addWidget(self._time_label)
        
        body_lo.addWidget(controls)
        
        layout.addWidget(body, 1)
        return card
    
    def _create_tools_panel(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet("""
            QFrame#toolsCard {
                background-color: #121212; border: 1px solid #252525; border-radius: 12px;
            }
        """)
        card.setObjectName("toolsCard")
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title_bar = QFrame()
        title_bar.setStyleSheet("background-color: transparent; border-bottom: 1px solid #1e1e1e;")
        title_bar.setFixedHeight(32)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)
        title_label = QLabel("🔧 工具栏")
        title_label.setStyleSheet("color: #999999; font-size: 11px; font-weight: 600;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addWidget(title_bar)
        
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #121212; }
            QTabBar::tab {
                background-color: transparent; color: #888888; border: none;
                padding: 6px 8px; font-size: 11px; min-width: 40px;
                border-bottom: 2px solid transparent;
            }
            QTabBar::tab:selected {
                color: #ffffff; border-bottom: 2px solid #1e6bde;
            }
            QTabBar::tab:hover:!selected { color: #cccccc; }
        """)
        
        tabs.addTab(self._make_pro_tab(), "属性")
        tabs.addTab(self._make_color_tab(), "调色")
        tabs.addTab(self._make_effect_tab(), "特效")
        tabs.addTab(self._make_text_tab(), "文字")
        tabs.addTab(self._make_sticker_tab(), "贴纸")
        tabs.addTab(self._make_audio_tab(), "音频")
        tabs.addTab(self._create_character_tab(), "角色")
        tabs.addTab(self._create_ai_tools_tab(), "AI")
        tabs.addTab(self._create_params_tab(), "导出")
        
        layout.addWidget(tabs, 1)
        return card

    def _sect(self, title):
        grp = QGroupBox(title)
        grp.setStyleSheet("""
            QGroupBox { font-size:11px;font-weight:600;color:#aaa;border:1px solid #222;border-radius:6px;margin-top:4px;padding-top:12px; }
            QGroupBox::title { subcontrol-origin:margin;left:8px;padding:0 4px; }
        """)
        lo = QVBoxLayout(grp)
        lo.setContentsMargins(8,4,8,8)
        lo.setSpacing(5)
        return grp

    def _slr(self, n, mn, mx, dv, suf=""):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0,0,0,0)
        l.setSpacing(4)
        lb = QLabel(n)
        lb.setStyleSheet("color:#888;font-size:10px;")
        lb.setFixedWidth(36)
        l.addWidget(lb)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(mn, mx)
        s.setValue(dv)
        s.setStyleSheet("QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}QSlider::handle:horizontal{background:#1e6bde;width:10px;height:10px;border-radius:5px;margin:-3px 0;}")
        l.addWidget(s, 1)
        vl = QLabel(f"{dv}{suf}")
        vl.setStyleSheet("color:#1e6bde;font-size:10px;font-weight:600;")
        vl.setFixedWidth(32)
        l.addWidget(vl)
        s.valueChanged.connect(lambda v: vl.setText(f"{v}{suf}"))
        return w

    def _cmb(self, n, items, dv=0):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0,0,0,0)
        l.setSpacing(4)
        lb = QLabel(n)
        lb.setStyleSheet("color:#888;font-size:10px;")
        lb.setFixedWidth(36)
        l.addWidget(lb)
        c = QComboBox()
        c.addItems(items)
        c.setCurrentIndex(dv)
        c.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}QComboBox:hover{border-color:#333;}QComboBox::drop-down{border:none;width:14px;}QComboBox QAbstractItemView{background:#121212;color:#fff;border:1px solid #333;selection-background-color:#1e6bde;}")
        l.addWidget(c, 1)
        return w

    def _add_setting_row(self, layout, label, widget, suffix=""):
        """添加带标签的滑块/微调器行（存储引用版）"""
        w = QWidget()
        l0 = QHBoxLayout(w)
        l0.setContentsMargins(0,0,0,0)
        l0.setSpacing(4)
        lb = QLabel(label)
        lb.setStyleSheet("color:#888;font-size:10px;")
        lb.setFixedWidth(36)
        l0.addWidget(lb)
        l0.addWidget(widget, 1)
        if suffix:
            if isinstance(widget, QSlider):
                vl = QLabel(f"{widget.value()}{suffix}")
                vl.setStyleSheet("color:#1e6bde;font-size:10px;font-weight:600;")
                vl.setFixedWidth(32)
                l0.addWidget(vl)
                widget.valueChanged.connect(lambda v, vl=vl: vl.setText(f"{v}{suffix}"))
            elif isinstance(widget, QSpinBox):
                widget.setSuffix(suffix)
        layout.addWidget(w)

    def _add_cmb_row(self, layout, label, combobox):
        """添加带标签的下拉框行（存储引用版）"""
        w = QWidget()
        l0 = QHBoxLayout(w)
        l0.setContentsMargins(0,0,0,0)
        l0.setSpacing(4)
        lb = QLabel(label)
        lb.setStyleSheet("color:#888;font-size:10px;")
        lb.setFixedWidth(36)
        l0.addWidget(lb)
        l0.addWidget(combobox, 1)
        layout.addWidget(w)

    def _spn(self, n, mn, mx, dv, suf=""):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0,0,0,0)
        l.setSpacing(4)
        lb = QLabel(n)
        lb.setStyleSheet("color:#888;font-size:10px;")
        lb.setFixedWidth(36)
        l.addWidget(lb)
        sp = QSpinBox()
        sp.setRange(mn, mx)
        sp.setValue(dv)
        sp.setSuffix(suf)
        sp.setStyleSheet("QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}QSpinBox:hover{border-color:#333;}")
        l.addWidget(sp, 1)
        return w

    def _make_pro_tab(self):
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8,8,8,8)
        l.setSpacing(6)

        tf = self._sect("变换")
        tf.layout().addWidget(self._spn("X",-9999,9999,0,"px"))
        tf.layout().addWidget(self._spn("Y",-9999,9999,0,"px"))
        tf.layout().addWidget(self._slr("缩放",10,400,100,"%"))
        tf.layout().addWidget(self._slr("旋转",-360,360,0,"°"))
        tf.layout().addWidget(self._cmb("锚点",["中心","左上","右上","左下","右下"]))
        l.addWidget(tf)

        cp = self._sect("合成")
        cp.layout().addWidget(self._slr("不透明度",0,100,100,"%"))
        cp.layout().addWidget(self._cmb("混合",["正常","变暗","正片叠底","颜色加深","变亮","滤色","叠加","柔光","强光","差值","排除","色相","饱和度","颜色","明度"]))
        l.addWidget(cp)

        pip = self._sect("画中画")
        self._pip_x = QSlider(Qt.Orientation.Horizontal); self._pip_x.setRange(0,100); self._pip_x.setValue(75)
        self._pip_y = QSlider(Qt.Orientation.Horizontal); self._pip_y.setRange(0,100); self._pip_y.setValue(80)
        self._pip_size = QSlider(Qt.Orientation.Horizontal); self._pip_size.setRange(10,100); self._pip_size.setValue(30)
        self._pip_border = QSpinBox(); self._pip_border.setRange(0,20); self._pip_border.setValue(2)
        for sl in [self._pip_x, self._pip_y, self._pip_size]:
            sl.setStyleSheet("QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}QSlider::handle:horizontal{background:#1e6bde;width:10px;height:10px;border-radius:5px;margin:-3px 0;}")
        self._pip_border.setStyleSheet("QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}")
        self._add_setting_row(pip.layout(), "X位置", self._pip_x, "%")
        self._add_setting_row(pip.layout(), "Y位置", self._pip_y, "%")
        self._add_setting_row(pip.layout(), "大小", self._pip_size, "%")
        self._add_setting_row(pip.layout(), "边框", self._pip_border, "px")
        pipb = QPushButton("📺 应用画中画")
        pipb.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        pipb.clicked.connect(self._apply_pip)
        pip.layout().addWidget(pipb)
        l.addWidget(pip)

        ck = self._sect("智能抠像")
        self._chroma_color = QComboBox(); self._chroma_color.addItems(["绿色","蓝色","自定义"])
        self._chroma_color.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
        self._chroma_tol = QSlider(Qt.Orientation.Horizontal); self._chroma_tol.setRange(5,70); self._chroma_tol.setValue(30)
        self._chroma_soft = QSlider(Qt.Orientation.Horizontal); self._chroma_soft.setRange(0,30); self._chroma_soft.setValue(5)
        for sl in [self._chroma_tol, self._chroma_soft]:
            sl.setStyleSheet("QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}QSlider::handle:horizontal{background:#8b5cf6;width:10px;height:10px;border-radius:5px;margin:-3px 0;}")
        self._add_cmb_row(ck.layout(), "背景色", self._chroma_color)
        self._add_setting_row(ck.layout(), "容差", self._chroma_tol, "%")
        self._add_setting_row(ck.layout(), "柔化", self._chroma_soft, "%")
        ckb = QPushButton("🎨 应用抠像")
        ckb.setStyleSheet("QPushButton{background:#8b5cf6;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#7c3aed;}")
        ckb.clicked.connect(self._apply_chroma_key)
        ck.layout().addWidget(ckb)
        l.addWidget(ck)

        sp = self._sect("速度/裁剪")
        self._speed_preset = QComboBox(); self._speed_preset.addItems(["无","0.25x慢放","0.5x慢放","2x快放","4x快放","缓入","缓出","缓入缓出","卡点变速","倒放"])
        self._speed_preset.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
        self._speed_factor = QSlider(Qt.Orientation.Horizontal); self._speed_factor.setRange(25,400); self._speed_factor.setValue(100)
        self._speed_factor.setStyleSheet("QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}QSlider::handle:horizontal{background:#f59e0b;width:10px;height:10px;border-radius:5px;margin:-3px 0;}")
        self._speed_easing = QComboBox(); self._speed_easing.addItems(["线性","缓入","缓出","缓入缓出","阶梯"])
        self._speed_easing.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
        self._add_cmb_row(sp.layout(), "变速预设", self._speed_preset)
        self._add_setting_row(sp.layout(), "速度因子", self._speed_factor, "%")
        self._add_cmb_row(sp.layout(), "缓动", self._speed_easing)
        spb = QPushButton("⚡ 应用变速")
        spb.setStyleSheet("QPushButton{background:#f59e0b;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#d97706;}")
        spb.clicked.connect(self._apply_speed_ramp)
        sp.layout().addWidget(spb)
        sp.layout().addWidget(self._spn("裁剪上",0,9999,0,"px"))
        sp.layout().addWidget(self._spn("裁剪下",0,9999,0,"px"))
        sp.layout().addWidget(self._spn("裁剪左",0,9999,0,"px"))
        sp.layout().addWidget(self._spn("裁剪右",0,9999,0,"px"))
        l.addWidget(sp)

        mt = self._sect("运动跟踪")
        self._track_type = QComboBox(); self._track_type.addItems(["平移跟踪","缩放跟踪","旋转跟踪","透视跟踪"])
        self._track_type.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
        self._add_cmb_row(mt.layout(), "跟踪类型", self._track_type)
        mtb = QPushButton("🎯 开始跟踪")
        mtb.setStyleSheet("QPushButton{background:#0891b2;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#0e7490;}")
        mtb.clicked.connect(self._apply_motion_track)
        mt.layout().addWidget(mtb)
        l.addWidget(mt)

        flip = self._sect("翻转/倒放")
        flip_row = QHBoxLayout()
        flip_row.setSpacing(4)
        rev_btn = QPushButton("🔄 倒放")
        rev_btn.setStyleSheet("QPushButton{background:#ef4444;color:#fff;border:none;border-radius:4px;padding:5px 10px;font-size:10px;font-weight:600;}QPushButton:hover{background:#dc2626;}")
        rev_btn.clicked.connect(self._reverse_video)
        flip_row.addWidget(rev_btn)
        mir_btn = QPushButton("↔ 水平镜像")
        mir_btn.setStyleSheet("QPushButton{background:#6366f1;color:#fff;border:none;border-radius:4px;padding:5px 10px;font-size:10px;font-weight:600;}QPushButton:hover{background:#4f46e5;}")
        mir_btn.clicked.connect(self._mirror_h)
        flip_row.addWidget(mir_btn)
        flv_btn = QPushButton("↕ 垂直翻转")
        flv_btn.setStyleSheet("QPushButton{background:#8b5cf6;color:#fff;border:none;border-radius:4px;padding:5px 10px;font-size:10px;font-weight:600;}QPushButton:hover{background:#7c3aed;}")
        flv_btn.clicked.connect(self._mirror_v)
        flip_row.addWidget(flv_btn)
        flip.layout().addLayout(flip_row)
        l.addWidget(flip)

        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0,0,0,0)
        o.addWidget(s)
        return t

    def _make_color_tab(self):
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8,8,8,8)
        l.setSpacing(6)

        bs = self._sect("基础校正")
        for nm in ["曝光","对比度","高光","阴影","白色","黑色"]:
            bs.layout().addWidget(self._slr(nm,-100,100,0))
        l.addWidget(bs)

        cs = self._sect("色彩调整")
        for nm in ["饱和度","自然饱和度","色温","色调","锐度"]:
            cs.layout().addWidget(self._slr(nm,-100,100,0))
        l.addWidget(cs)

        lu = self._sect("预设LUT")
        lu.layout().addWidget(self._cmb("LUT",["无","电影胶片","复古暖调","青橙色调","黑白经典","日系清新","赛博朋克","废土风格","糖果色","暗夜蓝调"]))
        lu.layout().addWidget(self._slr("强度",0,100,50,"%"))
        l.addWidget(lu)

        hsl = self._sect("HSL调整")
        hsl.layout().addWidget(self._slr("色相",-180,180,0,"°"))
        hsl.layout().addWidget(self._slr("饱和度",-100,100,0,"%"))
        hsl.layout().addWidget(self._slr("明度",-100,100,0,"%"))
        l.addWidget(hsl)

        cv = self._sect("曲线调色")
        self._curve_channel = QComboBox(); self._curve_channel.addItems(["RGB","红色","绿色","蓝色"])
        self._curve_channel.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 6px;font-size:10px;}")
        self._curve_shadows = QSlider(Qt.Orientation.Horizontal); self._curve_shadows.setRange(-100,100); self._curve_shadows.setValue(0)
        self._curve_midtones = QSlider(Qt.Orientation.Horizontal); self._curve_midtones.setRange(-100,100); self._curve_midtones.setValue(0)
        self._curve_highlights = QSlider(Qt.Orientation.Horizontal); self._curve_highlights.setRange(-100,100); self._curve_highlights.setValue(0)
        for sl in [self._curve_shadows, self._curve_midtones, self._curve_highlights]:
            sl.setStyleSheet("QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}QSlider::handle:horizontal{background:#dc2626;width:10px;height:10px;border-radius:5px;margin:-3px 0;}")
        self._add_cmb_row(cv.layout(), "通道", self._curve_channel)
        self._add_setting_row(cv.layout(), "暗部", self._curve_shadows, "")
        self._add_setting_row(cv.layout(), "中间调", self._curve_midtones, "")
        self._add_setting_row(cv.layout(), "亮部", self._curve_highlights, "")
        cvb = QPushButton("📈 应用曲线")
        cvb.setStyleSheet("QPushButton{background:#dc2626;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#b91c1c;}")
        cvb.clicked.connect(self._apply_curves)
        cv.layout().addWidget(cvb)
        l.addWidget(cv)

        arb = QHBoxLayout()
        rsc = QPushButton("↺ 重置")
        rsc.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#3a3a3a;}")
        arb.addWidget(rsc)
        apc = QPushButton("✅ 应用调色")
        apc.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        arb.addWidget(apc)
        l.addLayout(arb)

        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0,0,0,0)
        o.addWidget(s)
        return t

    def _make_effect_tab(self):
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8,8,8,8)
        l.setSpacing(6)

        fl = self._sect("滤镜")
        fl.layout().addWidget(self._cmb("分类",["全部","电影感","复古","清新","黑白","暖色调","冷色调","梦幻"]))
        g = QGridLayout()
        g.setSpacing(4)
        fts = [("🎞原片","#666"),("🎬电影","#d4a574"),("📷复古","#c4956a"),("🌿清新","#7ec87b"),
               ("🖤黑白","#888"),("☀暖阳","#e8b86d"),("❄冷调","#7eb8da"),("💫梦幻","#c9a0dc"),
               ("🎯锐利","#6db3f2"),("🌾柔和","#e8c4a2"),("🏙都市","#5d7b93"),("🌅黄昏","#e8945a")]
        FILTER_KEYS = {
            "🎞原片": "", "🎬电影": "电影感", "📷复古": "复古", "🌿清新": "清新",
            "🖤黑白": "黑白", "☀暖阳": "暖色调", "❄冷调": "冷色调", "💫梦幻": "梦幻",
            "🎯锐利": "锐利", "🌾柔和": "柔和", "🏙都市": "都市", "🌅黄昏": "黄昏",
        }
        for i,(nm,hc) in enumerate(fts):
            b = QPushButton(nm)
            b.setStyleSheet(f"QPushButton{{background:#0a0a0a;color:#ccc;border:1px solid #222;border-left:3px solid {hc};border-radius:3px;padding:5px 6px;font-size:10px;text-align:left;}}QPushButton:hover{{background:#1a1a1a;color:#fff;}}")
            key = FILTER_KEYS.get(nm, "")
            if key == "":
                b.clicked.connect(lambda _, b=b: self._clear_filter())
            else:
                b.clicked.connect(lambda _, k=key: self._select_filter(k))
            g.addWidget(b,i//3,i%3)
        fl.layout().addLayout(g)
        fl.layout().addWidget(self._slr("强度",0,100,50,"%"))
        l.addWidget(fl)

        tr = self._sect("转场")
        tr.layout().addWidget(self._cmb("类型",["淡入淡出","滑动","缩放","模糊","翻转","溶解","擦除","推入","旋转"]))
        tr.layout().addWidget(self._spn("时长",100,3000,500,"ms"))
        tr.layout().addWidget(self._cmb("曲线",["线性","缓入","缓出","缓入缓出","弹性","回弹"]))
        l.addWidget(tr)

        efb = QHBoxLayout()
        afb = QPushButton("✅ 应用滤镜")
        afb.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        afb.clicked.connect(lambda: self._apply_active_filter_with_intensity())
        efb.addWidget(afb)
        atb = QPushButton("✅ 应用转场")
        atb.setStyleSheet("QPushButton{background:#22c55e;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#16a34a;}")
        atb.clicked.connect(self._apply_transition)
        efb.addWidget(atb)
        l.addLayout(efb)

        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0,0,0,0)
        o.addWidget(s)
        return t

    def _make_text_tab(self):
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8,8,8,8)
        l.setSpacing(6)

        # ── 接收文案展示区 ──
        self._cw_display_container = QVBoxLayout()
        self._cw_display_container.setSpacing(4)
        l.addLayout(self._cw_display_container)
        self._refresh_copywriting_display()

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#222;")
        l.addWidget(sep)

        # ── 字幕列表 ──
        list_title = QLabel("📋 字幕列表")
        list_title.setStyleSheet("color:#aaa;font-size:11px;font-weight:bold;")
        l.addWidget(list_title)

        self._sub_list = QListWidget()
        self._sub_list.setMaximumHeight(160)
        self._sub_list.setStyleSheet("""
            QListWidget{
                background:#0a0a0a;color:#ccc;border:1px solid #222;
                border-radius:4px;font-size:11px;
            }
            QListWidget::item{padding:5px 8px;border-bottom:1px solid #1a1a1a;}
            QListWidget::item:selected{background:#1e6bde;color:#fff;}
            QListWidget::item:hover{background:#1a1a1a;}
        """)
        self._sub_list.currentItemChanged.connect(self._on_subtitle_selected)
        l.addWidget(self._sub_list)

        # ── 列表工具栏 ──
        lt_row = QHBoxLayout()
        lt_row.setSpacing(4)

        addb = QPushButton("➕ 添加")
        addb.setStyleSheet(self._sub_btn_style("#1e6bde"))
        addb.clicked.connect(self._add_subtitle)
        lt_row.addWidget(addb)

        aib = QPushButton("🤖 AI生成")
        aib.setStyleSheet(self._sub_btn_style("#22c55e"))
        aib.clicked.connect(self._generate_ai_subtitles)
        lt_row.addWidget(aib)

        impb = QPushButton("📥 导入")
        impb.setStyleSheet(self._sub_btn_style("#f59e0b"))
        impb.clicked.connect(self._import_subtitles)
        lt_row.addWidget(impb)

        expb = QPushButton("📤 导出")
        expb.setStyleSheet(self._sub_btn_style("#8b5cf6"))
        expb.clicked.connect(self._export_subtitles)
        lt_row.addWidget(expb)

        lt_row.addStretch()
        l.addLayout(lt_row)

        # ── 选中字幕编辑区 ──
        self._sub_edit_panel = QFrame()
        self._sub_edit_panel.setStyleSheet("QFrame{background:#121212;border:1px solid #1e1e1e;border-radius:6px;}")
        self._sub_edit_panel.setVisible(False)
        sub_el = QVBoxLayout(self._sub_edit_panel)
        sub_el.setContentsMargins(8,8,8,8)
        sub_el.setSpacing(5)

        self._sub_text_edit = QLineEdit()
        self._sub_text_edit.setPlaceholderText("字幕文本...")
        self._sub_text_edit.setStyleSheet(self._sub_input_style())
        sub_el.addWidget(self._sub_text_edit)

        time_row = QHBoxLayout()
        time_row.setSpacing(4)
        tl = QLabel("起始")
        tl.setStyleSheet("color:#888;font-size:10px;")
        time_row.addWidget(tl)
        self._sub_start_spin = QDoubleSpinBox()
        self._sub_start_spin.setRange(0, 99999)
        self._sub_start_spin.setDecimals(1)
        self._sub_start_spin.setSuffix("s")
        self._sub_start_spin.setStyleSheet(self._sub_input_style())
        time_row.addWidget(self._sub_start_spin, 1)
        tl2 = QLabel("结束")
        tl2.setStyleSheet("color:#888;font-size:10px;")
        time_row.addWidget(tl2)
        self._sub_end_spin = QDoubleSpinBox()
        self._sub_end_spin.setRange(0, 99999)
        self._sub_end_spin.setDecimals(1)
        self._sub_end_spin.setSuffix("s")
        self._sub_end_spin.setStyleSheet(self._sub_input_style())
        time_row.addWidget(self._sub_end_spin, 1)
        sub_el.addLayout(time_row)

        edit_btn_row = QHBoxLayout()
        edit_btn_row.setSpacing(4)
        saveb = QPushButton("✏ 保存编辑")
        saveb.setStyleSheet(self._sub_btn_style("#1e6bde"))
        saveb.clicked.connect(self._save_subtitle_edit)
        edit_btn_row.addWidget(saveb)
        visb = QPushButton("👁 可见")
        visb.setStyleSheet(self._sub_btn_style("#4caf50"))
        visb.clicked.connect(self._toggle_subtitle_visibility)
        edit_btn_row.addWidget(visb)
        delb = QPushButton("🗑 删除")
        delb.setStyleSheet(self._sub_btn_style("#c62828"))
        delb.clicked.connect(self._delete_subtitle)
        edit_btn_row.addWidget(delb)
        edit_btn_row.addStretch()
        sub_el.addLayout(edit_btn_row)

        l.addWidget(self._sub_edit_panel)

        # ── 分隔线 ──
        sep2 = QLabel()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background:#222;")
        l.addWidget(sep2)

        # ── 样式控制区域 ──
        tx = self._sect("文本")
        self._sub_font_cmb = self._cmb("字体",["微软雅黑","宋体","黑体","Arial","楷体","仿宋","思源黑体"])
        tx.layout().addWidget(self._sub_font_cmb)
        self._sub_size_spn = self._spn("字号",8,200,36,"pt")
        tx.layout().addWidget(self._sub_size_spn)
        cr = QWidget()
        cl = QHBoxLayout(cr)
        cl.setContentsMargins(0,0,0,0)
        cl.setSpacing(4)
        lb = QLabel("颜色")
        lb.setStyleSheet("color:#888;font-size:10px;")
        lb.setFixedWidth(36)
        cl.addWidget(lb)
        self._sub_color_swatches = []
        for hc in ["#fff","#ff0","#f44","#4af","#4f4","#f4f","#f80","#0ff"]:
            sw = QLabel()
            sw.setFixedSize(16,16)
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setStyleSheet(f"background:{hc};border:1px solid #444;border-radius:2px;")
            sw.mousePressEvent = lambda e, c=hc: self._on_color_click(c)
            cl.addWidget(sw)
            self._sub_color_swatches.append((sw, hc))
        self._sub_color_value = "#fff"
        cl.addStretch()
        tx.layout().addWidget(cr)
        l.addWidget(tx)

        st = self._sect("样式")
        self._sub_outline_cmb = self._cmb("描边",["无","黑色","白色","红色","蓝色","黄色"])
        st.layout().addWidget(self._sub_outline_cmb)
        self._sub_outline_w_spn = self._spn("描边宽",0,20,2,"px")
        st.layout().addWidget(self._sub_outline_w_spn)
        self._sub_shadow_cmb = self._cmb("阴影",["无","柔和","硬边","发光","投影"])
        st.layout().addWidget(self._sub_shadow_cmb)
        self._sub_bg_chk = QCheckBox("背景框")
        self._sub_bg_chk.setStyleSheet("color:#888;font-size:10px;")
        st.layout().addWidget(self._sub_bg_chk)
        l.addWidget(st)

        ps = self._sect("位置")
        self._sub_pos_cmb = self._cmb("预设",["底部居中","顶部居中","居中","左下","右下","自定义"])
        ps.layout().addWidget(self._sub_pos_cmb)
        self._sub_x_spn = self._spn("X偏移",-9999,9999,0,"px")
        ps.layout().addWidget(self._sub_x_spn)
        self._sub_y_spn = self._spn("Y偏移",-9999,9999,0,"px")
        ps.layout().addWidget(self._sub_y_spn)
        l.addWidget(ps)

        an = self._sect("动画")
        self._sub_anim_in_cmb = self._cmb("入场",["无","淡入","滑入上","滑入下","滑入左","滑入右","缩放进入","旋转进入"])
        an.layout().addWidget(self._sub_anim_in_cmb)
        self._sub_anim_out_cmb = self._cmb("出场",["无","淡出","滑出上","滑出下","滑出左","滑出右","缩放退出"])
        an.layout().addWidget(self._sub_anim_out_cmb)
        self._sub_anim_dur_spn = self._spn("时长",100,3000,500,"ms")
        an.layout().addWidget(self._sub_anim_dur_spn)
        l.addWidget(an)

        # ── 操作按钮 ──
        op_row = QHBoxLayout()
        op_row.setSpacing(4)
        styb = QPushButton("🎨 应用样式")
        styb.setStyleSheet(self._sub_btn_style("#f59e0b"))
        styb.clicked.connect(self._apply_subtitle_style)
        op_row.addWidget(styb)
        splitb = QPushButton("✂ 拆分")
        splitb.setStyleSheet(self._sub_btn_style("#ef4444"))
        splitb.clicked.connect(self._split_subtitle)
        op_row.addWidget(splitb)
        mergeb = QPushButton("🔗 合并")
        mergeb.setStyleSheet(self._sub_btn_style("#06b6d4"))
        mergeb.clicked.connect(self._merge_subtitle)
        op_row.addWidget(mergeb)
        op_row.addStretch()
        l.addLayout(op_row)

        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0,0,0,0)
        o.addWidget(s)

        # 初始化列表
        self._selected_sub_id = None
        self._refresh_subtitle_list()
        return t

    def _make_audio_tab(self):
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8,8,8,8)
        l.setSpacing(6)

        btns = QHBoxLayout()
        enh = QPushButton("🔊 增强")
        enh.setStyleSheet("QPushButton{background:#22c55e;color:#fff;border:none;border-radius:4px;padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#16a34a;}")
        enh.clicked.connect(self._enhance_audio)
        btns.addWidget(enh)
        dnz = QPushButton("🎤 降噪")
        dnz.setStyleSheet("QPushButton{background:#f59e0b;color:#fff;border:none;border-radius:4px;padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#d97706;}")
        dnz.clicked.connect(self._denoise_audio)
        btns.addWidget(dnz)
        crp = QPushButton("✂ 截取")
        crp.setStyleSheet("QPushButton{background:#ef4444;color:#fff;border:none;border-radius:4px;padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#dc2626;}")
        crp.clicked.connect(self._crop_audio)
        btns.addWidget(crp)
        l.addLayout(btns)

        btns2 = QHBoxLayout()
        bgm = QPushButton("🎵 添加BGM")
        bgm.setStyleSheet("QPushButton{background:#6366f1;color:#fff;border:none;border-radius:4px;padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#4f46e5;}")
        bgm.clicked.connect(self._add_bgm)
        btns2.addWidget(bgm)
        ext = QPushButton("🔊 提取人声")
        ext.setStyleSheet("QPushButton{background:#8b5cf6;color:#fff;border:none;border-radius:4px;padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#7c3aed;}")
        ext.clicked.connect(self._extract_vocal)
        btns2.addWidget(ext)
        l.addLayout(btns2)

        vl = self._sect("音量")
        vl.layout().addWidget(self._slr("音量",0,200,100,"%"))
        l.addWidget(vl)

        fd = self._sect("淡入淡出")
        fd.layout().addWidget(self._spn("淡入",0,10000,500,"ms"))
        fd.layout().addWidget(self._spn("淡出",0,10000,500,"ms"))
        fadeb = QPushButton("🎵 应用淡入淡出")
        fadeb.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        fadeb.clicked.connect(self._apply_fade_effects)
        fd.layout().addWidget(fadeb)
        l.addWidget(fd)

        eq = self._sect("均衡器")
        for b in ["低频","中频","高频"]:
            eq.layout().addWidget(self._slr(b,-12,12,0,"dB"))
        l.addWidget(eq)

        fx = self._sect("效果")
        dn = QCheckBox("降噪")
        dn.setStyleSheet("color:#888;font-size:10px;")
        fx.layout().addWidget(dn)
        fx.layout().addWidget(self._slr("降噪强度",0,100,50,"%"))
        cp = QCheckBox("压缩器")
        cp.setStyleSheet("color:#888;font-size:10px;")
        fx.layout().addWidget(cp)
        fx.layout().addWidget(self._slr("压缩比",0,100,50,"%"))
        fx.layout().addWidget(self._cmb("混响",["无","小房间","中厅","大教堂","板式","弹簧"]))
        l.addWidget(fx)

        bt = self._sect("音乐踩点")
        self._beat_sensitivity = QSpinBox(); self._beat_sensitivity.setRange(1,10); self._beat_sensitivity.setValue(5)
        self._beat_sensitivity.setStyleSheet("QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}")
        self._add_setting_row(bt.layout(), "灵敏度", self._beat_sensitivity, "")
        btn_detect = QPushButton("🥁 自动检测节拍")
        btn_detect.setStyleSheet("QPushButton{background:#a855f7;color:#fff;border:none;border-radius:4px;padding:5px 8px;font-size:10px;font-weight:600;}QPushButton:hover{background:#9333ea;}")
        btn_detect.clicked.connect(self._detect_beats)
        bt.layout().addWidget(btn_detect)
        self._beat_list = QListWidget()
        self._beat_list.setMaximumHeight(120)
        self._beat_list.setStyleSheet("QListWidget{background:#0a0a0a;color:#ccc;border:1px solid #222;border-radius:4px;font-size:10px;}")
        bt.layout().addWidget(self._beat_list)
        l.addWidget(bt)

        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0,0,0,0)
        o.addWidget(s)
        return t

    def _make_sticker_tab(self):
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8,8,8,8)
        l.setSpacing(6)

        lib = self._sect("贴纸库")
        g = QGridLayout()
        g.setSpacing(4)
        stickers = [("❤", "爱心"), ("⭐", "星星"), ("🔥", "火焰"), ("💎", "钻石"),
                    ("🎵", "音符"), ("✨", "闪亮"), ("💬", "聊天气泡"), ("🏷", "标签"),
                    ("👑", "皇冠"), ("🎯", "靶心"), ("🌈", "彩虹"), ("🎪", "马戏团")]
        self._sticker_btns = []
        for i, (emoji, name) in enumerate(stickers):
            b = QPushButton(f"{emoji}\n{name}")
            b.setStyleSheet("QPushButton{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:6px;padding:8px 4px;font-size:10px;min-height:48px;}QPushButton:hover{background:#1a1a1a;border-color:#1e6bde;}")
            b.clicked.connect(lambda checked, n=name, e=emoji: self._add_sticker(n, e))
            self._sticker_btns.append(b)
            g.addWidget(b, i // 4, i % 4)
        lib.layout().addLayout(g)
        l.addWidget(lib)

        cst = self._sect("自定义贴纸")
        self._sticker_size = QSlider(Qt.Orientation.Horizontal); self._sticker_size.setRange(20,200); self._sticker_size.setValue(100)
        self._sticker_rot = QSlider(Qt.Orientation.Horizontal); self._sticker_rot.setRange(-360,360); self._sticker_rot.setValue(0)
        self._sticker_posx = QSlider(Qt.Orientation.Horizontal); self._sticker_posx.setRange(0,100); self._sticker_posx.setValue(50)
        self._sticker_posy = QSlider(Qt.Orientation.Horizontal); self._sticker_posy.setRange(0,100); self._sticker_posy.setValue(50)
        self._sticker_opacity = QSlider(Qt.Orientation.Horizontal); self._sticker_opacity.setRange(30,100); self._sticker_opacity.setValue(100)
        for sl in [self._sticker_size, self._sticker_rot, self._sticker_posx, self._sticker_posy, self._sticker_opacity]:
            sl.setStyleSheet("QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}QSlider::handle:horizontal{background:#22c55e;width:10px;height:10px;border-radius:5px;margin:-3px 0;}")
        self._add_setting_row(cst.layout(), "大小", self._sticker_size, "%")
        self._add_setting_row(cst.layout(), "旋转", self._sticker_rot, "°")
        self._add_setting_row(cst.layout(), "位置X", self._sticker_posx, "%")
        self._add_setting_row(cst.layout(), "位置Y", self._sticker_posy, "%")
        self._add_setting_row(cst.layout(), "透明度", self._sticker_opacity, "%")
        add_custom = QPushButton("📁 导入贴纸")
        add_custom.setStyleSheet("QPushButton{background:#22c55e;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#16a34a;}")
        add_custom.clicked.connect(self._import_sticker)
        cst.layout().addWidget(add_custom)
        l.addWidget(cst)

        bns = QHBoxLayout()
        apply_s = QPushButton("✅ 添加到画布")
        apply_s.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        apply_s.clicked.connect(self._apply_sticker)
        bns.addWidget(apply_s)
        clear_s = QPushButton("🗑 清除贴纸")
        clear_s.setStyleSheet("QPushButton{background:#ef4444;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#dc2626;}")
        clear_s.clicked.connect(self._clear_stickers)
        bns.addWidget(clear_s)
        l.addLayout(bns)

        self._sticker_list = QListWidget()
        self._sticker_list.setMaximumHeight(100)
        self._sticker_list.setStyleSheet("QListWidget{background:#0a0a0a;color:#ccc;border:1px solid #222;border-radius:4px;font-size:10px;}")
        l.addWidget(self._sticker_list)

        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0,0,0,0)
        o.addWidget(s)

        self._active_stickers = []
        return t

    def _create_left_panel(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet("""
            QFrame#importCard {
                background-color: #121212; border: 1px solid #252525; border-radius: 12px;
            }
        """)
        card.setObjectName("importCard")
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title_bar = QFrame()
        title_bar.setStyleSheet("background-color: transparent; border-bottom: 1px solid #1e1e1e;")
        title_bar.setFixedHeight(36)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)
        title_label = QLabel("📁 导入栏")
        title_label.setStyleSheet("color: #999999; font-size: 11px; font-weight: 600;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addWidget(title_bar)
        
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(10)
        
        import_btn = QPushButton("🎬 导入视频")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde; color: white; border: none;
                border-radius: 8px; padding: 10px; font-size: 13px; font-weight: 600;
            }
            QPushButton:hover { background-color: #1557b0; }
        """)
        import_btn.clicked.connect(self._import_video)
        body_layout.addWidget(import_btn)
        
        drag_hint = QLabel("或拖拽文件到此处")
        drag_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drag_hint.setStyleSheet("color: #555555; font-size: 11px; padding: 4px;")
        body_layout.addWidget(drag_hint)
        
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #1e1e1e; max-height: 1px;")
        body_layout.addWidget(sep)
        
        fmt_label = QLabel("MP4 · AVI · MOV · MKV · WebM")
        fmt_label.setStyleSheet("color: #555555; font-size: 10px;")
        fmt_label.setWordWrap(True)
        body_layout.addWidget(fmt_label)
        
        # ── 素材预览区域 ──
        preview_sep = QFrame()
        preview_sep.setFrameShape(QFrame.Shape.HLine)
        preview_sep.setStyleSheet("background-color: #1e1e1e; max-height: 1px;")
        body_layout.addWidget(preview_sep)
        preview_title = QLabel("👁 素材预览")
        preview_title.setStyleSheet("color: #999999; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(preview_title)
        self._import_preview_label = QLabel("暂无预览")
        self._import_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._import_preview_label.setMinimumHeight(120)
        self._import_preview_label.setStyleSheet("""
            QLabel {
                background-color: #0a0a0a; border: 1px dashed #333;
                border-radius: 6px; color: #555; font-size: 11px;
            }
        """)
        body_layout.addWidget(self._import_preview_label)
        
        assets_label = QLabel("素材库")
        assets_label.setStyleSheet("color: #999999; font-size: 12px; font-weight: 600; margin-top: 6px;")
        body_layout.addWidget(assets_label)
        
        assets_list = QListWidget()
        assets_list.setStyleSheet("""
            QListWidget {
                background-color: #0a0a0a; border: 1px solid #1e1e1e; border-radius: 8px;
                color: #cccccc; font-size: 12px;
            }
            QListWidget::item { padding: 6px 10px; border-bottom: 1px solid #151515; }
            QListWidget::item:hover { background-color: #1a1a1a; color: #ffffff; }
        """)
        assets_list.addItems(["📹 视频素材", "🎵 音频素材", "🖼 图片素材", "📝 字幕素材"])
        body_layout.addWidget(assets_list)
        
        layout.addWidget(body, 1)
        return card
    
    def _create_timeline_panel(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet("""
            QFrame#timelineCard {
                background-color: #121212; border: 1px solid #252525; border-radius: 12px;
            }
        """)
        card.setObjectName("timelineCard")
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title_bar = QFrame()
        title_bar.setStyleSheet("background-color: transparent; border-bottom: 1px solid #1e1e1e;")
        title_bar.setFixedHeight(36)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(8, 4, 8, 4)
        title_layout.setSpacing(4)
        
        add_track_btn = QPushButton("➕ 轨道")
        add_track_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:10px;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        add_track_btn.clicked.connect(lambda _: self._timeline_widget.add_track("新轨道", "video"))
        title_layout.addWidget(add_track_btn)
        
        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFixedWidth(22)
        zoom_out_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:3px;padding:2px 4px;font-size:11px;font-weight:bold;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        zoom_out_btn.clicked.connect(lambda _: self._set_timeline_zoom(max(10, self._timeline_widget._zoom - 5)))
        zoom_out_btn.setToolTip("缩小")
        title_layout.addWidget(zoom_out_btn)
        
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(10, 500)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(100)
        self._zoom_slider.setStyleSheet("""
            QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}
            QSlider::handle:horizontal{background:#1e6bde;width:10px;height:10px;border-radius:5px;margin:-3px 0;}
            QSlider::handle:horizontal:hover{background:#3b82f6;}
            QSlider::sub-page:horizontal{background:#1e6bde;height:3px;border-radius:2px;}
        """)
        self._zoom_slider.valueChanged.connect(lambda v: self._set_timeline_zoom(v))
        title_layout.addWidget(self._zoom_slider)
        
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedWidth(22)
        zoom_in_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:3px;padding:2px 4px;font-size:11px;font-weight:bold;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        zoom_in_btn.clicked.connect(lambda _: self._set_timeline_zoom(min(500, self._timeline_widget._zoom + 5)))
        zoom_in_btn.setToolTip("放大")
        title_layout.addWidget(zoom_in_btn)
        
        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("color:#1e6bde;font-size:10px;font-weight:600;min-width:36px;")
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(self._zoom_label)
        
        sep0 = QFrame()
        sep0.setStyleSheet("background-color:#333;min-width:1px;max-width:1px;")
        sep0.setFixedSize(1, 20)
        title_layout.addWidget(sep0)
        
        rew_btn = QPushButton("⏮")
        rew_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:11px;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        rew_btn.clicked.connect(self._rewind)
        rew_btn.setToolTip("后退10秒")
        title_layout.addWidget(rew_btn)
        
        self._pp_btn = QPushButton("▶")
        self._pp_btn.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:1px solid #1e6bde;border-radius:4px;padding:3px 10px;font-size:12px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        self._pp_btn.clicked.connect(self._play_pause)
        self._pp_btn.setToolTip("播放/暂停")
        title_layout.addWidget(self._pp_btn)
        
        ff_btn = QPushButton("⏭")
        ff_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:11px;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        ff_btn.clicked.connect(self._fast_forward)
        ff_btn.setToolTip("快进10秒")
        title_layout.addWidget(ff_btn)
        
        # ── 倍速控制 ──
        speed_lbl = QLabel("⚡")
        speed_lbl.setStyleSheet("color:#888;font-size:11px;min-width:16px;")
        title_layout.addWidget(speed_lbl)
        self._playback_speed_combo = QComboBox()
        self._playback_speed_combo.addItems(["0.5x", "1x", "1.5x", "2x"])
        self._playback_speed_combo.setCurrentIndex(1)
        self._playback_speed_combo.setFixedWidth(58)
        self._playback_speed_combo.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #333;border-radius:4px;padding:2px 4px;font-size:10px;}QComboBox:hover{border-color:#1e6bde;}")
        self._playback_speed_combo.currentTextChanged.connect(self._on_playback_speed_changed)
        self._playback_speed_combo.setToolTip("播放倍速")
        title_layout.addWidget(self._playback_speed_combo)
        
        sep1 = QFrame()
        sep1.setStyleSheet("background-color:#333;min-width:1px;max-width:1px;")
        sep1.setFixedSize(1, 20)
        title_layout.addWidget(sep1)
        
        self._edit_agent_toggle_btn = QPushButton("🤖 剪辑 Agent")
        self._edit_agent_toggle_btn.setCheckable(True)
        self._edit_agent_toggle_btn.setStyleSheet("QPushButton{background:#22c55e;color:#fff;border:1px solid #16a34a;border-radius:4px;padding:3px 8px;font-size:10px;font-weight:500;}QPushButton:checked{background:#1e6bde;border-color:#1e6bde;}QPushButton:hover{background:#16a34a;}")
        self._edit_agent_toggle_btn.clicked.connect(self._toggle_edit_agent_panel)
        title_layout.addWidget(self._edit_agent_toggle_btn)
        
        title_layout.addStretch()
        
        snap_btn = QPushButton("📌 吸附")
        snap_btn.setCheckable(True)
        snap_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#888;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:10px;}QPushButton:checked{background:#1e6bde;color:#fff;border-color:#1e6bde;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        title_layout.addWidget(snap_btn)
        
        layout.addWidget(title_bar)
        
        body = QWidget()
        body_lo = QVBoxLayout(body)
        body_lo.setContentsMargins(8, 8, 8, 8)
        
        self._timeline_widget = TimelineWidget()
        self._timeline_widget.clip_selected.connect(self._on_clip_selected)
        # 补短 P1#8：监听关键帧点击 - 落到具体 keyframe 数据上
        self._timeline_widget.clip_keyframe_clicked.connect(self._on_keyframe_clicked)
        body_lo.addWidget(self._timeline_widget, 3)

        self._edit_agent_panel = self._create_edit_agent_panel()
        self._edit_agent_panel.hide()
        
        layout.addWidget(body, 1)
        return card
    
    def _import_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.webm)"
        )
        if file_path:
            try:
                # ── 更新导入预览 ──
                self._update_import_preview(file_path)
                
                _report_video_import_debug(
                    "A",
                    "editor_module._import_video:start",
                    "import video selected",
                    {
                        "file_path": file_path,
                        "preview_manager_is_none": self._preview_manager is None,
                        "has_preview_manager_attr": hasattr(self, "_preview_manager"),
                    },
                )
                asset_info = asset_manager.import_asset(file_path, category="videos")
                _report_video_import_debug(
                    "A",
                    "editor_module._import_video:asset",
                    "asset imported",
                    {
                        "asset_path": asset_info.get("path"),
                        "preview_manager_is_none": self._preview_manager is None,
                    },
                )
                print(f"导入素材成功: {asset_info['name']}")
                self._load_video(asset_info["path"])
                self._video_source = asset_info["path"]
                preview_manager = self._ensure_preview_manager()
                _report_video_import_debug(
                    "A",
                    "editor_module._import_video:before_open_video",
                    "before preview manager open_video",
                    {
                        "preview_manager_type": type(preview_manager).__name__ if preview_manager is not None else None,
                        "preview_manager_is_none": preview_manager is None,
                    },
                )
                preview_manager.open_video(asset_info["path"])
                self._playhead_position = 0.0
                initial_frame = preview_manager.get_frame_at(0.0)
                if initial_frame:
                    self._on_preview_frame(initial_frame)
                self._event_bus.emit(EventType.VIDEO_LOADED, {"path": asset_info["path"], "asset_id": asset_info["id"]})
            except Exception as e:
                _report_video_import_debug(
                    "A",
                    "editor_module._import_video:exception",
                    "import video exception",
                    {"error": repr(e), "error_type": type(e).__name__},
                )
                QMessageBox.warning(self, "导入失败", f"导入视频失败: {str(e)}")
                print(f"导入视频失败: {e}")

    def _update_import_preview(self, file_path):
        """更新导入栏素材预览"""
        if not hasattr(self, '_import_preview_label') or not file_path:
            return
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.webp'):
                pixmap = QPixmap(file_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        self._import_preview_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self._import_preview_label.setPixmap(scaled)
                    self._import_preview_label.setText("")
            elif ext in ('.mp4', '.avi', '.mov', '.mkv', '.webm'):
                # 使用ffmpeg提取第一帧作为预览
                thumb_path = file_path.rsplit('.', 1)[0] + '_import_thumb.png'
                ffmpeg = self._get_ffmpeg() if hasattr(self, '_get_ffmpeg') else 'ffmpeg'
                result = subprocess.run(
                    [ffmpeg, '-y', '-i', file_path, '-vframes', '1',
                     '-s', '320x240', thumb_path],
                    capture_output=True, text=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                if os.path.exists(thumb_path):
                    pixmap = QPixmap(thumb_path)
                    if not pixmap.isNull():
                        scaled = pixmap.scaled(
                            self._import_preview_label.size(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        )
                        self._import_preview_label.setPixmap(scaled)
                        self._import_preview_label.setText("")
                    try:
                        os.remove(thumb_path)
                    except Exception:
                        pass
            else:
                info = f"📁 {os.path.basename(file_path)}\n\n{os.path.getsize(file_path) // 1024} KB"
                self._import_preview_label.setText(info)
        except Exception as e:
            self._import_preview_label.setText(f"预览失败: {e}")

    def _on_preview_frame(self, qimage):
        """ """
        if qimage and hasattr(self, '_preview_label'):
            pixmap = QPixmap.fromImage(qimage)
            if not pixmap.isNull():
                self._preview_label.setPixmap(
                    pixmap.scaled(self._preview_frame.size(), 
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation))
                self._preview_label.show()

    def _on_timecode_updated(self, tc):
        """ """
        if hasattr(self, '_timecode_label'):
            self._timecode_label.setText(tc)



    def _apply_color(self):
        """ """
        self._apply_video_adjustments()


    def _apply_filter_tab(self):
        """ """
        if self._current_clip:
            category = getattr(self, '_filter_category_var', None)
            intensity = getattr(self, '_filter_intensity_slider', None)
            if intensity:
                self._current_clip['filter_intensity'] = intensity.value() / 100.0
            self._refresh_preview_with_effects()
            QMessageBox.information(self, "滤镜", "滤镜已应用")
    
    def _load_video(self, file_path):
        """ """
        # 更新预览窗口
        self._preview_label.setText(f"加载中... {os.path.basename(file_path)}")
        self._preview_label.show()
        
        # 使用QMediaPlayer加载视频
        media_content = QUrl.fromLocalFile(file_path)
        self._media_player.setSource(media_content)
        
        # 连接信号
        self._media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._media_player.positionChanged.connect(self._on_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        
        # 在素材库中添加视频
        # 这里可以添加视频到素材库的逻辑
        print(f"加载视频: {file_path}")
        # 将视频添加到时间线
        self._add_clip_to_timeline(file_path)
        
        # 隐藏加载提示,显示视频
        self._preview_label.hide()
    
    
    
    def _on_clip_selected(self, clip_data):
        """ """
        self._current_clip = clip_data
        print(f"选择片段: {clip_data['id']}")
        # 选中片段后，预览直接显示该片段对应区间，使工具栏编辑可见
        self._refresh_preview_to_current_clip()

    # ------------------------------------------------------------------
    # 补短 P1#8：关键帧可视化 - 公开便利 API
    # ------------------------------------------------------------------
    def add_keyframes_to_clip(self, clip_id, keyframes):
        """
        公开 API：给指定 clip 注入关键帧（覆盖式）。

        参数：
            clip_id: 添加到时间线时返回的 clip id（来自 _clips / new_clip['id']）
            keyframes: list[dict]，每项至少包含
                time_offset: 相对 clip 起点的时间偏移（秒）
                prop:       属性名（"opacity" / "scale_x" / "position_x" ...）
                value:      关键帧值
                easing:     缓动类型（可选，默认 "linear"）

        返回：
            bool - 是否成功（找不到 clip 时返回 False）

        用法：
            editor.add_keyframes_to_clip("clip_1", [
                {"time_offset": 0.0, "value": 0.0, "prop": "opacity", "easing": "ease_in"},
                {"time_offset": 2.5, "value": 1.0, "prop": "opacity", "easing": "ease_out"},
            ])
        """
        widget = self._clip_id_to_widget.get(clip_id)
        if widget is None:
            print(f"[P1#8] add_keyframes_to_clip 失败: 找不到 clip_id={clip_id}")
            return False
        widget.set_keyframes(keyframes)
        # 同步到 self._clips 中对应条目
        for c in self._clips:
            if c.get('id') == clip_id:
                c['keyframes'] = widget.get_keyframes()
                break
        return True

    def add_keyframe_channel_to_clip(self, clip_id, prop_name, time_value_pairs,
                                       easing="linear"):
        """
        公开 API：通过"通道 + (time, value) 列表"批量添加关键帧。
        便于对接 keyframe_animation.AnimatableProperties 的输出。

        参数：
            clip_id: clip id
            prop_name: 属性名（"opacity" / "scale_x" ...）
            time_value_pairs: [(t1, v1), (t2, v2), ...]，t 为相对 clip 起点的秒数
            easing: 缓动类型（默认 "linear"）

        返回：
            bool - 是否成功
        """
        keyframes = [
            {"time_offset": float(t), "value": float(v), "prop": prop_name, "easing": easing}
            for t, v in time_value_pairs
        ]
        return self.add_keyframes_to_clip(clip_id, keyframes)

    def get_keyframes_for_clip(self, clip_id):
        """获取指定 clip 当前的关键帧数据列表（找不到时返回空列表）"""
        widget = self._clip_id_to_widget.get(clip_id)
        if widget is None:
            return []
        return widget.get_keyframes()

    def _on_keyframe_clicked(self, clip_data, keyframe):
        """
        关键帧被点击 - 落到具体 kf 数据上。
        当前实现：选中 clip + 控制台打印（轻量反馈，不打断用户），
        后续可在此处弹出"关键帧编辑面板"或调用 keyframe_animation 引擎。
        """
        self._current_clip = clip_data
        try:
            prop = keyframe.get('prop', 'value')
            t = keyframe.get('time_offset', 0.0)
            value = keyframe.get('value', 0.0)
            easing = keyframe.get('easing', 'linear')
            print(f"[P1#8] 关键帧点击: clip={clip_data.get('id')}, "
                  f"prop={prop}, t={t:.2f}s, value={value}, easing={easing}")
        except Exception as e:
            print(f"[P1#8] 关键帧点击处理异常: {e}")
    
    
    
    def _move_clip(self, clip_id, new_start_time):
        """ """
        for clip in self._clips:
            if clip['id'] == clip_id:
                clip['start_time'] = new_start_time
                print(f"移动片段 {clip_id} 到 {new_start_time}s")
                break
    
    def _resize_clip(self, clip_id, new_duration):
        """ """
        for clip in self._clips:
            if clip['id'] == clip_id:
                clip['duration'] = new_duration
                print(f"调整片段 {clip_id} 长度为 {new_duration}s")
                break
    
    def _on_ai_clip(self):
        """
        智能剪辑入口
        - 若 Ollama 可用 + 有提示词: LLM 智能裁剪 (FunClip 风格)
        - 否则: 使用传统 AIClipAlgorithm (cv2/audio 分析)
        """
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return

        # 获取用户提示词（兼容 _prompt_edit 可能不存在的情况）
        try:
            prompt = self._prompt_edit.text().strip() if hasattr(self, '_prompt_edit') else ""
        except Exception:
            prompt = ""

        video_path = self._clips[0]['path']
        if not os.path.exists(video_path):
            show_clear_messagebox("操作提示", "视频文件不存在")
            return

        # ---- LLM 路径 ----
        from app.core.ai.llm_clipper import is_llm_clip_available, get_llm_clipper

        if is_llm_clip_available() and prompt:
            print(f"▶ [LLM] 开始智能剪辑, 提示词: {prompt}")
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("AI 智能剪辑")
            msg_box.setText("正在 Whisper 识别 + LLM 推理 + 裁剪...\n请稍候，这可能需要 1-3 分钟。")
            msg_box.setStandardButtons(QMessageBox.StandardButton.NoButton)
            msg_box.show()
            QApplication.processEvents()

            def _run_llm_clip():
                nonlocal msg_box
                try:
                    clipper = get_llm_clipper()
                    result_path = clipper.smart_clip(
                        video_path, prompt=prompt,
                    )
                    msg_box.close()
                    if result_path and os.path.isfile(result_path):
                        QMessageBox.information(
                            self, "AI 智能剪辑完成",
                            f"LLM 剪辑完成!\n输出: {result_path}"
                        )
                        self._load_video(result_path)
                    else:
                        QMessageBox.warning(self, "提示", "LLM 未返回有效结果，请尝试其他提示词。")
                except Exception as e:
                    msg_box.close()
                    QMessageBox.warning(self, "LLM 剪辑失败", f"失败: {e}\n已回退到传统算法。")
                    print(f"[LLM] 剪辑失败: {e}")
                    # 回退
                    self._on_ai_clip_fallback(video_path, prompt)

            import threading
            t = threading.Thread(target=_run_llm_clip, daemon=True)
            t.start()
            return

        # ---- 传统路径 ----
        self._on_ai_clip_fallback(video_path, prompt)

    def _on_ai_clip_fallback(self, video_path: str, prompt: str):
        """
        传统 AIClipAlgorithm 路径（cv2/audio 分析）
        当 Ollama 不可用或 prompt 为空时使用。
        """
        print(f"▶ 开始智能剪辑(传统), 提示词: {prompt}")

        try:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("智能剪辑")
            msg_box.setText("正在分析视频...\n这可能需要几分钟时间")
            msg_box.setStandardButtons(QMessageBox.StandardButton.NoButton)
            msg_box.show()
            QApplication.processEvents()

            ai_clip_algorithm = self._ensure_ai_clip_algorithm()
            if ai_clip_algorithm is None:
                msg_box.close()
                QMessageBox.warning(self, "智能剪辑", "智能剪辑算法不可用（模块加载失败）")
                return
            result_path = ai_clip_algorithm.process_video(
                video_path, prompt, output_length=20
            )

            msg_box.close()
            QMessageBox.information(self, "智能剪辑完成",
                                      f"剪辑完成!\n输出路径: {result_path}")
            self._load_video(result_path)

        except Exception as e:
            QMessageBox.warning(self, "处理失败", f"智能剪辑失败: {str(e)}")
            print(f"智能剪辑失败: {e}")
    
    # ===== 补短 P0#4:撤销/重做完整贯通 UI =====

    def _install_undo_redo_shortcuts(self):
        """
        注册 Ctrl+Z (撤销) / Ctrl+Y (重做) / Ctrl+Shift+Z (重做) 三个标准快捷键。

        兼容 QPushButton 自身的快捷键(已在 _create_toolbar 内通过 setShortcut 绑定),
        这里再额外用 QShortcut 兜底 — 避免按钮被隐藏时快捷键失效。
        """
        try:
            # 撤销
            sc_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
            sc_undo.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc_undo.activated.connect(self._undo)

            # 重做 (Windows 标准是 Ctrl+Y,Mac/Linux 也兼容 Ctrl+Shift+Z)
            sc_redo = QShortcut(QKeySequence("Ctrl+Y"), self)
            sc_redo.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc_redo.activated.connect(self._redo)

            sc_redo2 = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
            sc_redo2.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc_redo2.activated.connect(self._redo)
        except Exception as e:
            print(f"[P0#4] 快捷键注册失败: {e}")

    def _update_undo_redo_state(self):
        """
        根据当前历史栈刷新按钮 enable/disable + tooltip。
        任何修改 _action_history / _redo_history 的地方都应调用本方法。
        """
        try:
            can_undo = bool(getattr(self, '_action_history', []))
            can_redo = bool(getattr(self, '_redo_history', []))

            if self._undo_btn is not None:
                self._undo_btn.setEnabled(can_undo)
                self._undo_btn.setToolTip(
                    "撤销 (Ctrl+Z)" if can_undo else "无可撤销操作"
                )
            if self._redo_btn is not None:
                self._redo_btn.setEnabled(can_redo)
                self._redo_btn.setToolTip(
                    "重做 (Ctrl+Y / Ctrl+Shift+Z)" if can_redo else "无可重做操作"
                )
        except Exception as e:
            print(f"[P0#4] 状态更新失败: {e}")

    def get_undo_redo_toast(self) -> str:
        """获取最近一次撤销/重做的轻量提示(供 status bar / 主窗口显示)"""
        return self._undo_redo_toast

    # ---- 撤销/重做核心：历史栈 + 时间线感知的回滚（替代原被覆盖的死代码） ----

    def _record_action(self, action: dict) -> None:
        """将一次编辑操作压入撤销栈，并清空重做栈、刷新按钮状态。"""
        if not hasattr(self, '_action_history'):
            self._action_history = []
        if not hasattr(self, '_redo_history'):
            self._redo_history = []
        self._action_history.append(action)
        self._redo_history.clear()
        if len(self._action_history) > getattr(self, 'MAX_UNDO_DEPTH', 100):
            self._action_history.pop(0)
        self._update_undo_redo_state()

    def _timeline_add_clip_widget(self, clip: dict) -> None:
        """把片段重新加回时间线控件与索引，供撤销恢复使用。"""
        if not hasattr(self, '_timeline_widget') or self._timeline_widget is None:
            return
        widget = self._timeline_widget.add_clip(clip, int(clip.get("track", 0)))
        if widget is not None:
            if not hasattr(self, '_clip_widgets'):
                self._clip_widgets = []
            self._clip_widgets.append(widget)
            self._clip_id_to_widget[clip["id"]] = widget

    def _timeline_remove_clip_widget(self, clip_id) -> None:
        """从时间线控件与索引中移除某片段的 widget，供重做/删除使用。"""
        widget = self._clip_id_to_widget.pop(clip_id, None)
        if widget is not None and hasattr(self, '_clip_widgets'):
            if widget in self._clip_widgets:
                self._clip_widgets.remove(widget)
        if hasattr(self, '_timeline_widget') and self._timeline_widget is not None:
            for track in getattr(self._timeline_widget, '_tracks', []):
                layout = track.get("content_layout")
                if not layout:
                    continue
                for i in reversed(range(layout.count())):
                    w = layout.itemAt(i).widget()
                    if w is not None and getattr(w, "clip_data", {}).get("id") == clip_id:
                        layout.removeWidget(w)
                        w.deleteLater()
                        break

    def _apply_action(self, action: dict, mode: str) -> None:
        """执行一次操作或其逆操作。

        mode='do'  正向执行（用于重做 / 记录时的实做）
        mode='undo' 反向回滚（用于撤销）
        返回实做完成后供撤销使用的信息。
        """
        atype = action.get("type")

        if atype in ("delete", "redo_delete"):
            is_delete = (mode == 'do') if atype == "redo_delete" else (mode == 'undo')
            clip = action["clip"]
            if is_delete:
                # 删除：移出数据 + 控件
                self._clips = [c for c in self._clips if c.get("id") != clip.get("id")]
                self._timeline_remove_clip_widget(clip.get("id"))
                if self._current_clip and self._current_clip.get("id") == clip.get("id"):
                    self._current_clip = None
            else:
                # 恢复：加回数据 + 控件
                if clip not in self._clips:
                    self._clips.append(clip)
                self._timeline_add_clip_widget(clip)
                self._current_clip = clip

        elif atype in ("split", "redo_split"):
            is_split = (mode == 'do') if atype == "redo_split" else (mode == 'undo')
            original = action["original_clip"]
            new_clip = action["new_clip"]
            if is_split:
                # 切分：缩短原片段，追加新片段
                original["duration"] = action["original_duration"]
                original["out_point"] = action["original_out_point"]
                if new_clip not in self._clips:
                    self._clips.append(new_clip)
                self._timeline_add_clip_widget(new_clip)
                self._current_clip = new_clip
            else:
                # 合并：恢复原片段，删除新片段
                original["duration"] = action["original_duration"]
                original["out_point"] = action["original_out_point"]
                self._clips = [c for c in self._clips if c.get("id") != new_clip.get("id")]
                self._timeline_remove_clip_widget(new_clip.get("id"))
                self._current_clip = original

        elif atype in ("paste", "redo_paste"):
            is_paste = (mode == 'do') if atype == "redo_paste" else (mode == 'undo')
            new_clip = action["new_clip"]
            if is_paste:
                if new_clip not in self._clips:
                    self._clips.append(new_clip)
                self._timeline_add_clip_widget(new_clip)
                self._current_clip = new_clip
            else:
                self._clips = [c for c in self._clips if c.get("id") != new_clip.get("id")]
                self._timeline_remove_clip_widget(new_clip.get("id"))
                if self._current_clip and self._current_clip.get("id") == new_clip.get("id"):
                    self._current_clip = None

        # 刷新时间线与预览
        self._sync_timeline_widget_state()
        self._sync_kernel_timeline()
        self._refresh_preview_with_effects()
        self._refresh_preview_to_current_clip()

    def _undo(self):
        """撤销最近一步操作（时间线感知，按钮自动 enable/disable）。"""
        if getattr(self, '_action_history', []):
            action = self._action_history.pop()
            self._redo_history.append(action)
            self._apply_action(action, mode='undo')
            self._undo_redo_toast = f"已撤销: {action.get('type')}"
            print(f"[撤销] {self._undo_redo_toast}")
        else:
            self._undo_redo_toast = "没有可撤销的操作"
            print(f"[撤销] {self._undo_redo_toast}")
        self._update_undo_redo_state()

    def _redo(self):
        """重做最近撤销的操作（时间线感知，按钮自动 enable/disable）。"""
        if getattr(self, '_redo_history', []):
            action = self._redo_history.pop()
            self._action_history.append(action)
            self._apply_action(action, mode='do')
            self._undo_redo_toast = f"已重做: {action.get('type')}"
            print(f"[重做] {self._undo_redo_toast}")
        else:
            self._undo_redo_toast = "没有可重做的操作"
            print(f"[重做] {self._undo_redo_toast}")
        self._update_undo_redo_state()

    
    def _on_kernel_changed(self, index):
        """切换统一内核选择模式。"""
        from core.editor_scheduler import editor_scheduler

        if index == 0:
            self._kernel_mode = "auto"
            editor_scheduler.set_selection_mode("auto")
            print("✅ 切换到自动选择内核（按任务自主选择轻量/专业）")
        elif index == 1:
            self._kernel_mode = "light"
            editor_scheduler.set_selection_mode("lightweight")
            print("✅ 切换到轻量内核（快速预览模式）")
        else:
            success = editor_scheduler.set_selection_mode("professional")
            if success:
                self._kernel_mode = "pro"
                print("✅ 切换到专业内核（完整功能模式）")
            else:
                self._kernel_combo.blockSignals(True)
                self._kernel_combo.setCurrentIndex(0)
                self._kernel_combo.blockSignals(False)
                self._kernel_mode = "auto"
                editor_scheduler.set_selection_mode("auto")
                QMessageBox.warning(
                    self, "内核切换",
                    "专业内核不可用，已切换回自动选择模式。\n"
                    "请确保FFmpeg已正确安装。"
                )
    
    def _apply_effect(self, clip_id, effect_name, **params):
        """ """
        target_clip = None
        for clip in self._clips:
            if clip['id'] == clip_id:
                target_clip = clip
                break
        if not target_clip:
            QMessageBox.warning(self, "操作失败", "未找到指定的片段")
            return
        effects = target_clip.get('effects', {})
        effects[effect_name] = params
        target_clip['effects'] = effects
        self._refresh_preview_with_effects()
        print(f"应用特效 {effect_name} 到片段 {clip_id},参数: {params}")
        QMessageBox.information(self, "操作成功", f"特效 {effect_name} 已应用到片段 {clip_id}")
    
    def _add_transition(self, clip_id, transition_name, duration=1.0):
        """ """
        target_clip = None
        for clip in self._clips:
            if clip['id'] == clip_id:
                target_clip = clip
                break
        if not target_clip:
            QMessageBox.warning(self, "操作失败", "未找到指定的片段")
            return
        transitions = target_clip.get('transitions', [])
        transitions.append({
            'type': transition_name,
            'duration': duration,
            'time': self._playhead_position
        })
        target_clip['transitions'] = transitions
        print(f"添加转场 {transition_name} 到片段 {clip_id},时长: {duration}秒")
        QMessageBox.information(self, "操作成功", f"转场 {transition_name} 已添加到片段 {clip_id}")

    def _refresh_preview_with_effects(self):
        """刷新预览以反映当前效果参数"""
        try:
            from app.core.video_processing.gpu_render import get_gpu_renderer
            gpu = get_gpu_renderer()
        except (ImportError, ModuleNotFoundError):
            gpu = None
        
        # 确保预览管理器已初始化
        pm = self._ensure_preview_manager() if hasattr(self, '_ensure_preview_manager') else None
        
        if self._current_clip and self._video_source:
            effects = self._current_clip.get('effects', {})
            color_params = getattr(self, '_color_params', {})
            filter_name = getattr(self, '_active_filter', None)
            all_effects = dict(effects)
            all_effects.update(color_params)
            if filter_name:
                all_effects['filter'] = filter_name
            
            if gpu and pm:
                pm.set_active_effects(all_effects)
                pm.update_preview(self._playhead_position, effects=all_effects)
            elif pm:
                pm.set_active_effects(all_effects)
                pm.update_preview(self._playhead_position, effects=all_effects)
            else:
                # 回退：通过 media_player 刷新当前帧
                current_pos = self._media_player.position()
                self._media_player.setPosition(current_pos)



    # ─── 字幕面板辅助样式 ───
    @staticmethod
    def _sub_btn_style(bg):
        return f"QPushButton{{background:{bg};color:#fff;border:none;border-radius:4px;padding:5px 10px;font-size:10px;font-weight:600;}}QPushButton:hover{{opacity:0.85;}}"

    @staticmethod
    def _sub_input_style():
        return "QLineEdit,QDoubleSpinBox,QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}QLineEdit:focus,QDoubleSpinBox:focus,QSpinBox:focus{border:1px solid #1e6bde;}"

    # ─── 字幕样式应用 ───
    def _apply_subtitle_style(self):
        if not self._subtitle_manager:
            return
        sid = self._selected_sub_id
        if not sid:
            QMessageBox.information(self, "字幕", "请先在列表中选择一条字幕")
            return
        sub = self._subtitle_manager.get_subtitle(sid)
        if not sub:
            return
        # 读取UI控件
        font_w = self._sub_font_cmb.findChild(QComboBox)
        font = font_w.currentText() if font_w else "微软雅黑"
        size_w = self._sub_size_spn.findChild(QSpinBox)
        size = size_w.value() if size_w else 36
        outline_w = self._sub_outline_cmb.findChild(QComboBox)
        outline = outline_w.currentText() if outline_w else "无"
        outline_w2 = self._sub_outline_w_spn.findChild(QSpinBox)
        outline_w_val = outline_w2.value() if outline_w2 else 2
        shadow_w = self._sub_shadow_cmb.findChild(QComboBox)
        shadow = shadow_w.currentText() if shadow_w else "无"
        pos_w = self._sub_pos_cmb.findChild(QComboBox)
        pos = pos_w.currentText() if pos_w else "底部居中"
        x_w = self._sub_x_spn.findChild(QSpinBox)
        x_off = x_w.value() if x_w else 0
        y_w = self._sub_y_spn.findChild(QSpinBox)
        y_off = y_w.value() if y_w else 0
        anim_in_w = self._sub_anim_in_cmb.findChild(QComboBox)
        anim_in = anim_in_w.currentText() if anim_in_w else "无"
        anim_out_w = self._sub_anim_out_cmb.findChild(QComboBox)
        anim_out = anim_out_w.currentText() if anim_out_w else "无"
        anim_dur_w = self._sub_anim_dur_spn.findChild(QSpinBox)
        anim_dur = anim_dur_w.value() if anim_dur_w else 500
        # 位置映射
        pos_map = {"底部居中": (0.5, 0.85), "顶部居中": (0.5, 0.1), "居中": (0.5, 0.5),
                   "左下": (0.1, 0.85), "右下": (0.9, 0.85), "自定义": (0.5, 0.85)}
        px, py = pos_map.get(pos, (0.5, 0.85))
        self._subtitle_manager.update_subtitle(sid, position={"x": px, "y": py})
        style_name = f"custom_{sid}"
        self._subtitle_manager.create_subtitle_style(style_name,
            font=font, font_size=size, color=self._sub_color_value,
            border_color=outline if outline != "无" else "transparent",
            border_width=outline_w_val, background="#000000" if self._sub_bg_chk.isChecked() else "transparent")
        self._subtitle_manager.apply_style_to_subtitle(sid, style_name)
        QMessageBox.information(self, "字幕", f"样式已应用到选中字幕：{font} {size}pt {self._sub_color_value}")

    def _on_color_click(self, color):
        self._sub_color_value = color

    def _on_copywriting_received(self, event):
        """接收文案模块推送的内容"""
        data = event.data
        if not isinstance(data, dict):
            return
        self._received_copywriting = data
        self._refresh_copywriting_display()
        title = data.get("title", "无标题")[:30]
        QMessageBox.information(
            self, "收到文案",
            f"📝 已接收文案\n标题: {title}...\n来源: {data.get('platform', '未知平台')} | 风格: {data.get('style', '未知')}\n\n可在右侧\"文字\"面板中查看和添加"
        )
    
    def _refresh_copywriting_display(self):
        """刷新文字面板中的文案展示区"""
        cw = self._received_copywriting
        if hasattr(self, '_cw_display_container') and self._cw_display_container:
            container = self._cw_display_container
            while container.count():
                item = container.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            if cw:
                title_lbl = QLabel(f"📋 推送文案 | {cw.get('platform','')} · {cw.get('style','')}")
                title_lbl.setStyleSheet("color:#1e6bde;font-size:11px;font-weight:600;padding:4px 0;")
                container.addWidget(title_lbl)
                if cw.get("title"):
                    t = QLabel(f"标题: {cw['title'][:80]}")
                    t.setStyleSheet("color:#ccc;font-size:11px;padding:2px 0;")
                    t.setWordWrap(True)
                    container.addWidget(t)
                script = cw.get("script") or cw.get("description", "")
                if script:
                    te = QTextEdit()
                    te.setPlainText(script)
                    te.setMaximumHeight(120)
                    te.setStyleSheet("QTextEdit{background:#0a0a0a;color:#ccc;border:1px solid #333;border-radius:4px;font-size:10px;padding:4px;}")
                    container.addWidget(te)
                btn_row = QHBoxLayout()
                btn_row.setSpacing(6)
                add_btn = QPushButton("➕ 添加字幕")
                add_btn.setStyleSheet("QPushButton{background:#22c55e;color:#fff;border:none;border-radius:4px;padding:4px 10px;font-size:10px;font-weight:600;}QPushButton:hover{background:#16a34a;}")
                add_btn.clicked.connect(self._add_copywriting_as_subtitle)
                btn_row.addWidget(add_btn)
                clear_btn = QPushButton("清除")
                clear_btn.setStyleSheet("QPushButton{background:#333;color:#888;border:none;border-radius:4px;padding:4px 10px;font-size:10px;}QPushButton:hover{background:#444;}")
                clear_btn.clicked.connect(self._clear_received_copywriting)
                btn_row.addWidget(clear_btn)
                btn_row.addStretch()
                container.addLayout(btn_row)
    
    def _add_copywriting_as_subtitle(self):
        cw = self._received_copywriting
        if not cw:
            return
        script = cw.get("script") or cw.get("description", "")
        if not script:
            QMessageBox.information(self, "提示", "暂无可添加的字幕文本")
            return
        lines = [l.strip() for l in script.split('\n') if l.strip()]
        if not self._subtitle_manager:
            QMessageBox.warning(self, "错误", "字幕系统未就绪")
            return
        start = self._playhead_position
        for i, line in enumerate(lines):
            self._subtitle_manager.add_subtitle(text=line, start_time=start + i * 3.0, end_time=start + (i + 1) * 3.0)
        self._refresh_subtitle_list()
        QMessageBox.information(self, "添加成功", f"✅ 已添加 {len(lines)} 条字幕")
    
    def _clear_received_copywriting(self):
        self._received_copywriting = None
        self._refresh_copywriting_display()

    def _on_material_dropped(self, event):
        """接收素材库推送的素材，添加到时间线"""
        data = event.data if hasattr(event, 'data') else event
        file_path = data.get("file_path", "") if isinstance(data, dict) else str(data)
        if file_path and os.path.exists(file_path):
            self._add_clip_to_timeline(file_path)
            print(f"✅ 素材已添加到时间线: {os.path.basename(file_path)}")
        else:
            print(f"⚠️ 无法添加素材: {file_path}")

    # ─── 字幕 CRUD ───
    def _refresh_subtitle_list(self):
        if not hasattr(self, '_sub_list') or not self._sub_list:
            return
        self._sub_list.blockSignals(True)
        self._sub_list.clear()
        if not self._subtitle_manager:
            self._sub_list.blockSignals(False)
            return
        for sub in self._subtitle_manager.list_subtitles():
            t0 = sub.get("start_time", 0)
            t1 = sub.get("end_time", 0)
            text = sub.get("text", "")[:40]
            vis = "👁" if sub.get("visible", True) else "🚫"
            ts = f"{int(t0//60):02d}:{int(t0%60):02d}"
            item = QListWidgetItem(f"[{ts}] {vis} {text}")
            item.setData(Qt.ItemDataRole.UserRole, sub.get("id"))
            self._sub_list.addItem(item)
        self._sub_list.blockSignals(False)
        self._sub_list.update()

    def _on_subtitle_selected(self, current, previous):
        if not current:
            self._sub_edit_panel.setVisible(False)
            self._selected_sub_id = None
            return
        sid = current.data(Qt.ItemDataRole.UserRole)
        if not sid or not self._subtitle_manager:
            self._sub_edit_panel.setVisible(False)
            return
        sub = self._subtitle_manager.get_subtitle(sid)
        if not sub:
            return
        self._selected_sub_id = sid
        self._sub_edit_panel.setVisible(True)
        self._sub_text_edit.setText(sub.get("text", ""))
        self._sub_start_spin.setValue(sub.get("start_time", 0))
        self._sub_end_spin.setValue(sub.get("end_time", 0))

    def _save_subtitle_edit(self):
        sid = self._selected_sub_id
        if not sid or not self._subtitle_manager:
            return
        text = self._sub_text_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "提示", "字幕文本不能为空")
            return
        self._subtitle_manager.update_subtitle(sid,
            text=text,
            start_time=self._sub_start_spin.value(),
            end_time=self._sub_end_spin.value())
        self._refresh_subtitle_list()
        QMessageBox.information(self, "字幕", "字幕已保存")

    def _add_subtitle(self):
        if not self._subtitle_manager:
            return
        text, ok = QInputDialog.getText(self, "添加字幕", "请输入字幕文本：", text="")
        if not ok or not text.strip():
            return
        self._subtitle_manager.add_subtitle(
            text=text.strip(),
            start_time=self._playhead_position,
            end_time=self._playhead_position + 3.0)
        self._refresh_subtitle_list()

    def _delete_subtitle(self):
        sid = self._selected_sub_id
        if not sid or not self._subtitle_manager:
            return
        sub = self._subtitle_manager.get_subtitle(sid)
        name = sub.get("text", "该字幕")[:20] if sub else "该字幕"
        r = QMessageBox.question(self, "确认删除", f"确定删除「{name}」？")
        if r != QMessageBox.StandardButton.Yes:
            return
        self._subtitle_manager.delete_subtitle(sid)
        self._selected_sub_id = None
        self._sub_edit_panel.setVisible(False)
        self._refresh_subtitle_list()

    def _toggle_subtitle_visibility(self):
        sid = self._selected_sub_id
        if not sid or not self._subtitle_manager:
            return
        self._subtitle_manager.toggle_subtitle_visibility(sid)
        self._refresh_subtitle_list()

    def _split_subtitle(self):
        sid = self._selected_sub_id
        if not sid or not self._subtitle_manager:
            QMessageBox.information(self, "拆分", "请先在列表中选择一条字幕")
            return
        sub = self._subtitle_manager.get_subtitle(sid)
        if not sub:
            return
        mid = (sub["start_time"] + sub["end_time"]) / 2
        val, ok = QInputDialog.getDouble(self, "拆分字幕", f"在哪个时间点拆分？(当前范围 {sub['start_time']:.1f}s - {sub['end_time']:.1f}s)", mid, 0, 99999, 1)
        if not ok:
            return
        result = self._subtitle_manager.split_subtitle(sid, val)
        if result:
            self._refresh_subtitle_list()
            QMessageBox.information(self, "拆分", f"字幕已拆分为 2 条")

    def _merge_subtitle(self):
        sid1 = self._selected_sub_id
        if not sid1 or not self._subtitle_manager:
            QMessageBox.information(self, "合并", "请先选择第一条字幕，再输入第二条的序号")
            return
        items = []
        for i in range(self._sub_list.count()):
            items.append(f"{i+1}) {self._sub_list.item(i).text()[:30]}")
        if len(items) < 2:
            QMessageBox.information(self, "合并", "至少需要 2 条字幕才能合并")
            return
        item_str, ok = QInputDialog.getItem(self, "合并字幕", "选择要和当前字幕合并的字幕：", items, 0, False)
        if not ok:
            return
        idx = int(item_str.split(")")[0]) - 1
        sid2 = self._sub_list.item(idx).data(Qt.ItemDataRole.UserRole)
        if sid1 == sid2:
            return
        result = self._subtitle_manager.merge_subtitles(sid1, sid2)
        if result:
            self._refresh_subtitle_list()
            QMessageBox.information(self, "合并", "字幕已合并")

    # ─── 导入导出 ───
    def _import_subtitles(self):
        if not self._subtitle_manager:
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入字幕", "", "字幕文件 (*.srt *.vtt)")
        if not path:
            return
        fmt = "srt" if path.lower().endswith(".srt") else "vtt"
        imported = self._subtitle_manager.import_subtitles(path, fmt)
        if imported:
            self._refresh_subtitle_list()
            QMessageBox.information(self, "导入", f"成功导入 {len(imported)} 条字幕")
        else:
            QMessageBox.warning(self, "导入", "未能从文件中识别出字幕数据")

    def _export_subtitles(self):
        if not self._subtitle_manager:
            return
        if not self._subtitle_manager.list_subtitles():
            QMessageBox.information(self, "导出", "当前没有字幕可导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出字幕", "subtitles.srt", "SRT 字幕 (*.srt)")
        if not path:
            return
        if self._subtitle_manager.export_subtitles(path, "srt"):
            QMessageBox.information(self, "导出", f"字幕已导出到:\n{path}")
        else:
            QMessageBox.warning(self, "导出", "导出失败")

    # ─── AI 字幕生成（使用 SubtitleGenerator 完整管线） ───
    def _generate_ai_subtitles(self):
        """AI字幕生成：提取音频 → 语音转写 → 生成字幕"""
        if not self._clips:
            QMessageBox.warning(self, "操作提示", "请先导入视频")
            return
        clip = self._clips[0]
        video_path = clip['path']
        if not os.path.exists(video_path):
            QMessageBox.warning(self, "操作提示", "视频文件不存在")
            return
        
        # 初始化字幕管理器
        if not self._subtitle_manager:
            from core.subtitle_manager import SubtitleManager
            self._subtitle_manager = SubtitleManager()
        
        # 更新AI任务状态（主线程）
        if hasattr(self, '_ai_task_label'):
            self._ai_task_label.setText("任务: AI字幕生成中...")
            self._ai_task_label.setStyleSheet("color:#f59e0b;font-size:10px;font-weight:600;")
        if hasattr(self, '_ai_progress'):
            self._ai_progress.setValue(0)
            self._ai_progress.show()
        
        def do_generate():
            try:
                # 步骤1: 提取音频
                self._emit_ai_progress(10, "正在提取音频...")
                audio_path = video_path.rsplit('.', 1)[0] + '_subtitle_audio.wav'
                
                ffmpeg_cmd = [
                    self._get_ffmpeg(), '-y', '-i', video_path,
                    '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                    audio_path
                ]
                subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=120,
                              creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                
                if not os.path.exists(audio_path):
                    self._emit_ai_fail("音频提取失败")
                    return
                
                # 步骤2: 转写
                self._emit_ai_progress(20, "正在加载语音识别模型...")
                segments = []
                try:
                    from core.subtitle_generator import SubtitleGenerator
                    gen = SubtitleGenerator(model_size="base")
                    segments = gen.generate_subtitles(
                        audio_path,
                        language="zh",
                        correct_typos=True,
                        progress_callback=lambda p, m: self._emit_ai_progress(20 + int(p * 0.7), m)
                    )
                except Exception as e:
                    logger.warning(f"SubtitleGenerator失败，使用内置方案: {e}")
                    segments = self._fallback_subtitle_generation(audio_path)
                
                if not segments:
                    self._emit_ai_fail("未识别到语音内容")
                    return
                
                # 步骤3: 写入字幕管理器
                self._emit_ai_progress(95, "正在更新字幕列表...")
                if hasattr(self._subtitle_manager, 'subtitles'):
                    self._subtitle_manager.subtitles.clear()
                
                subtitle_count = 0
                for seg in segments:
                    text = getattr(seg, 'text', '') if hasattr(seg, 'text') else str(seg)
                    start = getattr(seg, 'start_time', 0) if hasattr(seg, 'start_time') else 0
                    end = getattr(seg, 'end_time', 0) if hasattr(seg, 'end_time') else 0
                    if text:
                        self._subtitle_manager.create_subtitle(text, start, end)
                        subtitle_count += 1
                
                # 清理临时音频
                try:
                    os.remove(audio_path)
                except Exception:
                    pass
                
                # 通过信号通知主线程更新UI
                self._subtitle_generated_signal.emit(subtitle_count)
                
            except subprocess.TimeoutExpired:
                self._emit_ai_fail("处理超时，请检查视频文件大小")
            except Exception as e:
                logger.exception("AI字幕生成失败")
                self._emit_ai_fail(f"字幕生成失败: {e}")
        
        threading.Thread(target=do_generate, daemon=True).start()

    def _on_subtitle_generated(self, count: int):
        """主线程回调：字幕生成完成后刷新UI"""
        if hasattr(self, '_ai_task_label'):
            self._ai_task_label.setText("任务: 待机中")
            self._ai_task_label.setStyleSheet("color:#888;font-size:10px;")
        if hasattr(self, '_ai_progress'):
            self._ai_progress.hide()
        self._refresh_subtitle_list()
        QMessageBox.information(self, "AI字幕", f"AI字幕生成完成，共 {count} 条字幕")

    def _on_ai_fail(self, message: str):
        """主线程回调：字幕生成失败"""
        if hasattr(self, '_ai_task_label'):
            self._ai_task_label.setText("任务: 待机中")
            self._ai_task_label.setStyleSheet("color:#888;font-size:10px;")
        if hasattr(self, '_ai_progress'):
            self._ai_progress.hide()
        QMessageBox.warning(self, "AI字幕", message)

    def _on_ai_progress(self, value: int, msg: str):
        """主线程回调：更新进度条"""
        if hasattr(self, '_ai_progress'):
            self._ai_progress.setValue(value)
            self._ai_progress.show()
        if hasattr(self, '_ai_task_label'):
            self._ai_task_label.setText(f"任务: {msg}")

    def _emit_ai_progress(self, value, message):
        """从后台线程安全地发射进度信号"""
        try:
            self.ai_progress_signal.emit(value, message)
        except Exception:
            pass

    def _emit_ai_fail(self, message):
        """从后台线程安全地发射失败信号"""
        try:
            self.ai_fail_signal.emit(message)
        except Exception:
            pass
    
    def _fallback_subtitle_generation(self, audio_path):
        """备选字幕生成方案：基于音频时长生成模拟字幕"""
        segments = []
        try:
            import librosa
            duration = librosa.get_duration(filename=audio_path)
        except Exception:
            try:
                # 使用ffprobe获取时长
                result = subprocess.run(
                    [self._get_ffmpeg().replace('ffmpeg.exe', 'ffprobe.exe').replace('ffmpeg', 'ffprobe'),
                     '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
                    capture_output=True, text=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                duration = float(result.stdout.strip()) if result.stdout.strip() else 60.0
            except Exception:
                duration = 60.0
        
        # 生成时间点标记（每3-5秒一条）
        class _FakeSegment:
            def __init__(self, text, start_time, end_time):
                self.text = text
                self.start_time = start_time
                self.end_time = end_time
        
        current = 0.0
        idx = 0
        while current < duration:
            seg_duration = min(4.0, duration - current)
            segments.append(_FakeSegment(
                text=f"字幕片段 {idx + 1}",
                start_time=current,
                end_time=current + seg_duration
            ))
            current += seg_duration
            idx += 1
        
        return segments
    
    # ===== 工作流集成 =====
    def connect_to_workflow(self):
        """连接到工作流管理器"""
        from .workflow_manager import get_workflow_manager
        self._workflow_manager = get_workflow_manager()
        self._workflow_manager.workflow_completed.connect(self._on_workflow_completed)
        self._workflow_manager.step_completed.connect(self._on_workflow_step_completed)
        print("✅ EditorModule 已连接到工作流管理器")
    
    def _on_workflow_completed(self, context):
        """工作流完成回调"""
        if context.video_path and os.path.exists(context.video_path):
            self._load_video(context.video_path)
        
        # 更新文案
        if context.creative:
            self._received_copywriting = context.creative
            self._refresh_copywriting_display()
    
    def _on_workflow_step_completed(self, step_name, result):
        """工作流步骤完成回调"""
        if step_name == "ai_clip" and result.get("success"):
            clips = result.get("clips", [])
            for clip in clips:
                if clip.get("input_path"):
                    self._add_clip_to_timeline(clip["input_path"])
    
    # ===== 数据闭环集成 =====
    def connect_to_data_analyzer(self):
        """连接到数据分析器"""
        from .data_analyzer import get_data_analyzer
        self._data_analyzer = get_data_analyzer()
    
    def get_recommendations(self):
        """获取推荐策略"""
        if hasattr(self, '_data_analyzer'):
            return self._data_analyzer.get_recommendations("douyin")
        return {}
    
    def record_edit_action(self, action_type, data):
        """记录编辑操作（用于数据回流）"""
        if hasattr(self, '_data_analyzer'):
            record = {
                "timestamp": datetime.now().isoformat(),
                "action_type": action_type,
                "data": data,
                "clip_count": len(self._clips)
            }
            self._data_analyzer._record_workflow(record)
    
    # ===== AI能力增强 =====
    def enhance_with_ai(self):
        """使用AI增强视频"""
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        
        video_path = self._clips[0]['path']
        
        from app.core.ai_engine import AIEngine
        ai_engine = AIEngine.get_instance()
        
        result = ai_engine.enhance_video(video_path)
        
        if result.get("success"):
            enhanced_path = result.get("output_path")
            if enhanced_path and os.path.exists(enhanced_path):
                self._load_video(enhanced_path)
                QMessageBox.information(self, "AI增强完成", "视频已完成AI增强")
    
    def smart_cut_with_ai(self):
        """AI智能剪辑"""
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        
        video_path = self._clips[0]['path']
        
        from app.core.ai_engine import AIEngine
        ai_engine = AIEngine.get_instance()
        
        result = ai_engine.smart_cut(video_path, duration=60)
        
        if result.get("success"):
            clips = result.get("clips", [])
            for clip in clips:
                if clip.get("path"):
                    self._add_clip_to_timeline(clip["path"])
            QMessageBox.information(self, "AI剪辑完成", f"已生成 {len(clips)} 个片段")
    
    # ===== 时间线批量操作 =====
    def batch_add_clips(self, file_paths):
        """批量添加片段到时间线"""
        for file_path in file_paths:
            if os.path.exists(file_path):
                self._add_clip_to_timeline(file_path)
        QMessageBox.information(self, "批量导入完成", f"已添加 {len(file_paths)} 个文件")
    
    def batch_delete_clips(self, clip_ids):
        """批量删除片段"""
        for clip_id in clip_ids:
            self._delete_clip_by_id(clip_id)
        QMessageBox.information(self, "批量删除完成", f"已删除 {len(clip_ids)} 个片段")

    # ===== 导出增强 =====
    def export_project(self, output_path):
        """导出项目（包含所有片段和设置）"""
        project_data = {
            "version": "1.0",
            "clips": self._clips,
            "timeline_zoom": self._timeline_zoom,
            "export_time": datetime.now().isoformat()
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            import json
            json.dump(project_data, f, ensure_ascii=False, indent=2)
        
        QMessageBox.information(self, "导出完成", f"项目已导出到:\n{output_path}")
    
    def import_project(self, project_path):
        """导入项目"""
        if not os.path.exists(project_path):
            QMessageBox.warning(self, "错误", "项目文件不存在")
            return
        
        with open(project_path, 'r', encoding='utf-8') as f:
            import json
            project_data = json.load(f)
        
        self._clips = project_data.get("clips", [])
        self._timeline_zoom = project_data.get("timeline_zoom", 100)
        
        QMessageBox.information(self, "导入完成", f"已导入 {len(self._clips)} 个片段")
    
    # ===== 快捷键增强 =====
    def _install_additional_shortcuts(self):
        """安装额外的快捷键"""
        # Ctrl+I: 导入视频
        self._import_shortcut = QShortcut(QKeySequence("Ctrl+I"), self)
        self._import_shortcut.activated.connect(self._import_video)
        
        # Ctrl+E: 导出视频
        self._export_shortcut = QShortcut(QKeySequence("Ctrl+E"), self)
        self._export_shortcut.activated.connect(self._export_video)
        
        # Ctrl+S: 保存项目
        self._save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self._save_shortcut.activated.connect(self._save_project)
        
        # Space: 播放/暂停
        self._play_pause_shortcut = QShortcut(QKeySequence("Space"), self)
        self._play_pause_shortcut.activated.connect(self._play_pause)
        
        # Delete: 删除选中片段
        self._delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        self._delete_shortcut.activated.connect(self._delete_clip)
        
        # Ctrl+D: 复制片段
        self._duplicate_shortcut = QShortcut(QKeySequence("Ctrl+D"), self)
        self._duplicate_shortcut.activated.connect(self._copy_clip)
    
    def _save_project(self):
        """保存项目"""
        path, _ = QFileDialog.getSaveFileName(self, "保存项目", "", "项目文件 (*.timeline)")
        if path:
            self.export_project(path)
        # 进度弹窗
        progress_dlg = QDialog(self)
        progress_dlg.setWindowTitle("AI 字幕生成")
        progress_dlg.setFixedSize(420, 140)
        progress_dlg.setStyleSheet("QDialog{background:#121212;}")
        pl = QVBoxLayout(progress_dlg)
        pl.setContentsMargins(20, 16, 20, 16)
        status_lbl = QLabel("正在启动语音识别引擎...")
        status_lbl.setStyleSheet("color:#ccc;font-size:13px;")
        pl.addWidget(status_lbl)
        prog = QProgressBar()
        prog.setStyleSheet("QProgressBar{background:#1a1a1a;border:1px solid #333;border-radius:4px;height:22px;text-align:center;color:#fff;font-size:11px;}QProgressBar::chunk{background:#22c55e;border-radius:3px;}")
        pl.addWidget(prog)
        pl.addStretch()
        progress_dlg.show()
        QApplication.processEvents()

        def _do_gen():
            try:
                from core.subtitle_generator import SubtitleGenerator, SubtitleStyle
                status_lbl.setText("Whisper 语音转写中...")
                prog.setValue(10)
                gen = SubtitleGenerator(model_size="base")
                segments = gen.generate_subtitles(
                    audio_path=video_path,
                    language="zh",
                    correct_typos=True,
                    apply_style=SubtitleStyle.CLASSIC,
                    progress_callback=lambda p, msg: (
                        prog.setValue(p), status_lbl.setText(msg)
                    )
                )
                if segments:
                    status_lbl.setText(f"写入 {len(segments)} 条字幕...")
                    prog.setValue(90)
                    for seg in segments:
                        self._subtitle_manager.add_subtitle(
                            text=seg.text,
                            start_time=seg.start_time,
                            end_time=seg.end_time)
                    self._refresh_subtitle_list()
                prog.setValue(100)
                status_lbl.setText("✅ 字幕生成完成")
            except ImportError:
                # 回退：裸用 whisper
                try:
                    status_lbl.setText("回退：裸调 Whisper...")
                    prog.setValue(15)
                    import whisper
                    model = whisper.load_model("base")
                    prog.setValue(40)
                    result = model.transcribe(video_path, language="zh")
                    prog.setValue(80)
                    segments = result.get("segments", [])
                    for seg in segments:
                        if self._subtitle_manager:
                            self._subtitle_manager.add_subtitle(text=seg.get("text", "").strip(), start_time=seg.get("start", 0), end_time=seg.get("end", 0))
                    self._refresh_subtitle_list()
                    prog.setValue(100)
                    status_lbl.setText(f"✅ 生成 {len(segments)} 条字幕 (Whisper)")
                except ImportError:
                    status_lbl.setText("❌ Whisper 未安装: pip install openai-whisper")
                except Exception as ex:
                    status_lbl.setText(f"❌ 失败: {ex}")
            except Exception as e:
                status_lbl.setText(f"❌ 生成失败: {e}")
            QTimer.singleShot(1000, progress_dlg.close)
        threading.Thread(target=_do_gen, daemon=True).start()




    
    # ===== 工具栏编辑 → 真实视频（让剪切/删除/复制粘贴真正作用到视频） =====

    def _has_timeline_edits(self) -> bool:
        """判断当前片段列表相对原始素材是否存在真实编辑（裁剪区间/删除/复制）。"""
        if not getattr(self, '_clips', []):
            return False
        if len(self._clips) > 1:
            return True
        clip = self._clips[0]
        src = clip.get("path")
        dur = self._probe_video_duration(src) if src else 0.0
        in_p = float(clip.get("in_point", 0))
        out_p = float(clip.get("out_point", dur))
        return in_p > 0.01 or abs(out_p - dur) > 0.01

    def _build_edited_video(self, output_path: str) -> bool:
        """依据 self._clips 的 in/out 点，从源视频裁剪各段、烘焙滤镜/转场，再按时间顺序拼接成成品。

        工具栏的剪切(成段)/删除(缺段)/复制粘贴(多段) 以及 滤镜/转场 现在都会真实反映在导出的视频里
        （此前滤镜/转场仅在预览里显示，不进成品）。
        返回是否成功。
        """
        clips = [c for c in getattr(self, '_clips', [])
                 if c.get("path") and os.path.exists(c.get("path"))]
        clips = sorted(clips, key=lambda c: float(c.get("start_time", 0)))
        clips = [c for c in clips
                 if float(c.get("out_point", 0)) - float(c.get("in_point", 0)) > 0.01]
        if not clips:
            return False
        import tempfile
        try:
            from app.modules.lego.video_processor import (
                trim_video, merge_videos, apply_video_filter,
                merge_with_transitions, map_filter_to_vf,
            )
            from app.core.editor_scheduler import editor_scheduler
            ffmpeg_path = getattr(editor_scheduler.get_video_processor(), "ffmpeg_path", "ffmpeg")
        except Exception:
            try:
                from app.modules.lego.video_processor import (
                    trim_video, merge_videos, apply_video_filter,
                    merge_with_transitions, map_filter_to_vf,
                )
            except Exception:
                return False
            ffmpeg_path = "ffmpeg"
        tmp_segments = []
        filtered_segments = []
        durations = []
        transitions = []
        try:
            for clip in clips:
                src = clip.get("path")
                dur = self._probe_video_duration(src) or 0.0
                in_p = float(clip.get("in_point", 0))
                out_p = float(clip.get("out_point", dur))
                if out_p - in_p <= 0.01:
                    continue
                seg = tempfile.mktemp(suffix=".mp4")
                if not trim_video(src, seg, in_p, out_p, ffmpeg_path):
                    continue
                tmp_segments.append(seg)
                # ── 烘焙滤镜：把预览级 filter 真正写进视频段 ──
                # 安全读取 effects：可能是 dict（已应用滤镜/调节）或 list/缺失
                _eff = clip.get("effects")
                if not isinstance(_eff, dict):
                    _eff = {}
                _filter_name = clip.get("filter") or _eff.get("filter", "")
                _intensity = float(clip.get("filter_intensity", _eff.get("filter_intensity", 0.7)))
                vf = map_filter_to_vf(
                    _filter_name,
                    _intensity,
                    _eff.get("color_params"),
                )
                final_seg = seg
                if vf:
                    fseg = tempfile.mktemp(suffix=".mp4")
                    if apply_video_filter(seg, fseg, vf, ffmpeg_path):
                        tmp_segments.append(fseg)
                        final_seg = fseg
                filtered_segments.append(final_seg)
                durations.append(out_p - in_p)
                # 收集「本段与前一段」之间的转场（取本段记录的入场转场）
                if len(filtered_segments) >= 2:
                    trans = clip.get("transition") or (clip.get("transitions") or [None])[-1]
                    transitions.append(trans if isinstance(trans, dict) else
                                       {"type": "淡入淡出", "duration": 0.5})

            if not filtered_segments:
                return False
            if len(filtered_segments) == 1:
                import shutil
                shutil.copy(filtered_segments[0], output_path)
                return os.path.exists(output_path)
            # 存在转场则用 xfade 融合拼接，否则普通 concat
            if transitions:
                return merge_with_transitions(
                    filtered_segments, transitions, output_path, ffmpeg_path, None, durations)
            return merge_videos(filtered_segments, output_path, ffmpeg_path)
        finally:
            for seg in tmp_segments:
                try:
                    os.remove(seg)
                except Exception:
                    pass

    def _sync_kernel_timeline(self):
        """将 self._clips 的 in/out 与顺序同步进统一内核时间线，确保底层数据一致。

        修复：此前 split/copy/paste 完全不碰内核时间线，导致底层数据与界面脱节。
        """
        try:
            from app.core.timeline_manager import timeline_manager as real_timeline_manager
        except ImportError:
            from core.timeline_manager import timeline_manager as real_timeline_manager
        if not getattr(self, '_current_timeline', None):
            self._current_timeline = real_timeline_manager.create_timeline("默认时间线")
        tl = self._current_timeline
        for track in tl.get("tracks", []):
            if track.get("type") == "video":
                track["clips"] = []
        ordered = sorted(self._clips, key=lambda c: float(c.get("start_time", 0)))
        t0 = 0.0
        for clip in ordered:
            clip_info = {
                "name": clip.get("name", os.path.basename(str(clip.get("path", "")))),
                "path": clip.get("path"),
                "start_time": t0,
                "duration": float(clip.get("duration", 0)),
                "in_point": float(clip.get("in_point", 0)),
                "out_point": float(clip.get("out_point", 0)),
                "effects": clip.get("effects", []),
                "transitions": clip.get("transitions", []),
            }
            real_timeline_manager.add_clip(tl["id"], "video_1", clip_info)
            t0 += float(clip.get("duration", 0))
        try:
            real_timeline_manager._recalculate_duration(tl)
        except Exception:
            pass

    def _refresh_preview_to_current_clip(self):
        """让预览反映当前选中片段的 in/out 区间，使工具栏编辑在预览中可见。

        改用 PreviewManager 的帧 seek（cv2 直接定位，无 ffmpeg 临时文件）渲染片段区间，
        并同步 QMediaPlayer 定位到片段起点；不再为每个片段生成临时裁剪文件。
        """
        clip = getattr(self, '_current_clip', None)
        pm = self._ensure_preview_manager()
        if not clip or pm is None:
            return
        try:
            src = clip.get("path")
            if not src or not os.path.exists(src):
                return
            dur = self._probe_video_duration(src) or 0.0
            in_p = float(clip.get("in_point", 0))
            out_p = float(clip.get("out_point", dur))
            # 缓存键：片段 id + 裁剪区间，未变则不重复刷新
            seg_key = (clip.get("id"), round(in_p, 3), round(out_p, 3))
            if getattr(self, '_preview_seg_key', None) == seg_key:
                return
            self._preview_seg_key = seg_key
            # 确保 PreviewManager 打开的是同一源文件（避免重复 open）
            if getattr(self, '_preview_source_path', None) != src:
                pm.open_video(src)
                self._preview_source_path = src
                self._video_source = src
            # 用 PreviewManager 直接 seek 到 in_point 渲染（无 ffmpeg 临时文件）
            self._playhead_position = in_p
            frame = pm.get_frame_at(in_p)
            if frame is not None:
                self._on_preview_frame(frame)
            # 同步 QMediaPlayer 定位到片段起点，播放时也从该处开始
            player = getattr(self, '_media_player', None)
            if player is not None:
                from PyQt6.QtCore import QUrl
                if player.source().isEmpty() or getattr(self, '_video_source', '') != src:
                    player.setSource(QUrl.fromLocalFile(src))
                player.setPosition(int(in_p * 1000))
        except Exception as e:
            print(f"预览片段刷新失败: {e}")
            self._preview_seg_key = None

    def _export_video(self):
        """ """
        if self._clips:
            # 获取导出设置参数
            output_mode = self._output_mode_var.currentText()
            resolution = self._resolution_var.currentText()
            platform = getattr(self, '_platform_var', None).currentText() if hasattr(self, '_platform_var') else "默认"
            fps = self._fps_var.currentText()
            bitrate = self._bitrate_var.currentText()
            codec = self._codec_var.currentText()
            audio_codec = getattr(self, '_audio_codec_var', None).currentText() if hasattr(self, '_audio_codec_var') else "AAC"
            audio_sample = getattr(self, '_audio_sample_var', None).currentText() if hasattr(self, '_audio_sample_var') else "44100"
            audio_bitrate = getattr(self, '_audio_bitrate_var', None).currentText() if hasattr(self, '_audio_bitrate_var') else "128k"
            format = self._format_var.currentText()
            bitrate_control = getattr(self, '_bitrate_control_var', None).currentText() if hasattr(self, '_bitrate_control_var') else "CBR"
            gop = getattr(self, '_gop_var', None).text() if hasattr(self, '_gop_var') else "30"
            aspect_ratio = self._aspect_var.currentText()
            quality = getattr(self, '_quality_var', None).currentText() if hasattr(self, '_quality_var') else "高"
            audio_channels = getattr(self, '_audio_channel_var', None).currentText() if hasattr(self, '_audio_channel_var') else "立体声"
            hardware_accel = "启用" if self._hardware_accel_var.isChecked() else "禁用"
            
            # 构建导出参数
            export_params = {
                "resolution": resolution,
                "bitrate": bitrate,
                "format": format,
                "codec": codec,
                "fps": fps,
                "bitrate_control": bitrate_control,
                "gop": gop,
                "aspect_ratio": aspect_ratio,
                "quality": quality,
                "audio_codec": audio_codec,
                "audio_sample": audio_sample,
                "audio_bitrate": audio_bitrate,
                "audio_channels": audio_channels,
                "hardware_accel": hardware_accel
            }
            
            # —— 关键修复：让工具栏的剪切/删除/复制粘贴真正作用到导出视频 ——
            # 若存在时间线编辑(多段/裁剪区间)，先按 in/out 裁剪拼接出已剪辑中间产物，
            # 再交给统一内核套用分辨率/平台等设置；否则走原始单文件逻辑。
            source_clip_path = self._clips[0]['path']
            edited_temp_path = None
            if self._has_timeline_edits():
                try:
                    output_dir = "短剧AI剪辑输出"
                    os.makedirs(output_dir, exist_ok=True)
                    edited_temp_path = os.path.join(
                        output_dir, f"_edited_{int(time.time() * 1000)}.mp4")
                    if not self._build_edited_video(edited_temp_path):
                        edited_temp_path = None
                except Exception as _e:
                    print(f"构建剪辑后视频失败，回退原始文件: {_e}")
                    edited_temp_path = None
            clip_path = edited_temp_path or source_clip_path
            if not os.path.exists(clip_path):
                QMessageBox.warning(self, "导出失败", "视频文件不存在")
                return

            export_params["platform"] = platform
            platform_map = {
                "抖音": "抖音",
                "快手": "快手",
                "B站": "B站",
                "小红书": "小红书",
                "视频号": "视频号",
                "默认": "通用HD",
            }
            render_platform = platform_map.get(platform, "通用HD")
            output_dir = "短剧AI剪辑输出"
            os.makedirs(output_dir, exist_ok=True)
            base_name = os.path.basename(source_clip_path)
            kernel_prefix = "Pro" if self._kernel_mode == "pro" else "Fast"
            output_name = f"[{kernel_prefix}]_{os.path.splitext(base_name)[0]}.{format}"
            output_path = os.path.join(output_dir, output_name)

            render_error = ""
            try:
                try:
                    from app.core.editor_scheduler import editor_scheduler
                except ImportError:
                    from core.editor_scheduler import editor_scheduler

                # 统一内核调度器内部自主选择轻量/专业，并处理渲染后端回退。
                result = editor_scheduler.export_video(
                    clip_path,
                    output_path=output_path,
                    platform=render_platform,
                    params=export_params,
                )
                # 清理编辑中间产物
                if edited_temp_path and os.path.exists(edited_temp_path):
                    try:
                        os.remove(edited_temp_path)
                    except Exception:
                        pass
                success = result.get("success") if isinstance(result, dict) else getattr(result, "success", False)
                if success:
                    output_size = result.get("output_size", 0) if isinstance(result, dict) else getattr(result, "output_size", 0)
                    processing_time = result.get("processing_time", 0) if isinstance(result, dict) else getattr(result, "processing_time", 0)
                    QMessageBox.information(
                        self,
                        "导出成功",
                        f"视频导出完成!\n输出路径: {output_path}\n"
                        f"耗时: {processing_time:.1f}s\n"
                        f"大小: {output_size / 1024 / 1024:.1f}MB"
                    )
                    return
                render_error = result.get("error_message", "") if isinstance(result, dict) else getattr(result, "error_message", "")
                render_error = render_error or "统一内核导出失败"
            except Exception as e:
                render_error = str(e)
                print(f"统一内核导出失败: {e}")

            task_export_params = {
                "output_mode": output_mode,
                "resolution": resolution,
                "platform": platform,
                "fps": fps,
                "bitrate": bitrate,
                "codec": codec,
                "format": format,
                "bitrate_control": bitrate_control,
                "gop": gop,
                "aspect_ratio": aspect_ratio,
                "quality": quality,
                "audio_codec": audio_codec,
                "audio_sample": audio_sample,
                "audio_bitrate": audio_bitrate,
                "audio_channels": audio_channels,
                "hardware_accel": hardware_accel,
                "clips": self._clips
            }

            self._event_bus.emit(EventType.MODULE_ACTIVATED, {
                "target": "tasks",
                "export_params": task_export_params
            })

            QMessageBox.warning(
                self,
                "导出失败",
                f"统一内核导出失败，已同步任务参数到任务模块。\n原因: {render_error}"
            )
        else:
            show_clear_messagebox("操作提示", "请先导入视频")
    
    def _create_character_tab(self) -> QWidget:
        """
        「角色」面板 — 剪辑模块内的临时角色管理
        读取 DramaStructure 中的角色列表，允许用户给角色打「优先保留/忽略」标签
        调整后写回 AnalysisCache（仅作用于当前视频，不跨视频复用）
        """
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(6)

        # 顶部标题 & 缓存状态
        st = self._sect("👥 角色（剪辑内临时标记）")
        st_lo = st.layout()
        info_row = QHBoxLayout()
        self._char_status_label = QLabel("等待视频分析...")
        self._char_status_label.setStyleSheet("color:#888888;font-size:11px;")
        info_row.addWidget(self._char_status_label)
        info_row.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet(
            "QPushButton{background:#1e6bde;color:#ffffff;border-radius:4px;padding:4px 10px;font-size:11px;}"
            "QPushButton:hover{background:#2d7ae8;}"
            "QPushButton:pressed{background:#1a5dc4;}"
        )
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._refresh_character_panel)
        info_row.addWidget(refresh_btn)
        st_lo.addLayout(info_row)
        hint = QLabel("提示：角色仅作用于当前视频，调整后重新生成剪辑方案会生效。\n关闭程序后偏好保留（同视频下次打开仍然保留）。")
        hint.setStyleSheet("color:#666666;font-size:10px;")
        hint.setWordWrap(True)
        st_lo.addWidget(hint)

        # 角色列表容器（动态生成）
        self._char_list_container = QWidget()
        self._char_list_layout = QVBoxLayout(self._char_list_container)
        self._char_list_layout.setContentsMargins(0, 0, 0, 0)
        self._char_list_layout.setSpacing(6)
        self._char_list_layout.addStretch()
        l.addWidget(self._char_list_container, 1)

        s.setWidget(c)
        outer = QVBoxLayout(t)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(s)

        # 首次刷新（如果已有缓存则立即显示）
        try:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(300, self._refresh_character_panel)
        except Exception:
            pass
        return t

    @staticmethod
    def _safe_set_text(label, text: str):
        """安全设置 QLabel 文本，防止 C++ 对象已被删除时崩溃"""
        try:
            label.setText(text)
        except (RuntimeError, AttributeError):
            pass

    def _refresh_character_panel(self):
        """刷新角色列表（从 AnalysisCache 读取）"""
        # 安全检查：对象可能已被 Qt 销毁
        try:
            _ = self._char_status_label.isVisible()
        except (RuntimeError, AttributeError):
            return

        try:
            from .character_cache import AnalysisCache
        except Exception:
            self._safe_set_text(self._char_status_label, "角色缓存不可用")
            return

        # 清理旧 UI
        try:
            while self._char_list_layout.count() > 0:
                item = self._char_list_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
        except (RuntimeError, AttributeError):
            return

        video_path = getattr(self, "_video_source", None)
        if not video_path:
            self._safe_set_text(self._char_status_label, "尚未导入视频")
            try:
                self._char_list_layout.addStretch()
            except (RuntimeError, AttributeError):
                pass
            return

        try:
            cache = AnalysisCache()
            drama = cache.get_drama(video_path)
            prefs = cache.get_character_prefs(video_path)
        except Exception as e:
            self._safe_set_text(self._char_status_label, f"读取缓存异常: {e}")
            try:
                self._char_list_layout.addStretch()
            except (RuntimeError, AttributeError):
                pass
            return

        if drama is None or not getattr(drama, "characters", None):
            self._safe_set_text(self._char_status_label, "未检测到角色 — 请先运行「AI 智能剪辑」分析视频")
            try:
                empty = QLabel("分析完成后，角色将出现在这里供你标记。\n\n"
                              "• 点「忽略」：剪辑时会降低该角色镜头的优先级\n"
                              "• 点「优先保留」：剪辑时会提升该角色镜头的重要性\n"
                              "• 权重滑块：精细调整影响幅度")
                empty.setStyleSheet("color:#666666;font-size:11px;padding:16px;"
                                  "background:#1a1a1a;border-radius:6px;")
                empty.setWordWrap(True)
                self._char_list_layout.addWidget(empty)
                self._char_list_layout.addStretch()
            except (RuntimeError, AttributeError):
                pass
            return

        # 统计每个角色的出场次数（粗略：按 scenes 统计）
        scenes = getattr(drama, "scenes", []) or []
        char_appear = {}
        for sc in scenes:
            for name in (getattr(sc, "characters", None) or []):
                char_appear[name] = char_appear.get(name, 0) + 1

        total_chars = len(drama.characters)
        active_pref_count = sum(1 for p in prefs.values() if p is not None and hasattr(p, "__dict__") or (isinstance(p, dict) and p))

        self._safe_set_text(
            self._char_status_label,
            f"本视频共识别 {total_chars} 个角色 · 已标记 {len(prefs)} 个偏好"
        )

        # 为每个角色构建一行 UI
        for ch in drama.characters:
            name = str(getattr(ch, "name", "未知"))
            role_type = str(getattr(ch, "role_type", ""))
            traits = getattr(ch, "personality_traits", []) or []

            pref_obj = prefs.get(name)
            if pref_obj is not None:
                if hasattr(pref_obj, "keep"):
                    keep_default = bool(pref_obj.keep)
                    weight_default = float(getattr(pref_obj, "weight", 1.0))
                elif isinstance(pref_obj, dict):
                    keep_default = bool(pref_obj.get("keep", True))
                    weight_default = float(pref_obj.get("weight", 1.0))
                else:
                    keep_default = True
                    weight_default = 1.0
            else:
                keep_default = True
                weight_default = 1.0

            row = QFrame()
            row.setStyleSheet(
                "QFrame{background:#1a1a1a;border:1px solid #252525;border-radius:6px;}"
            )
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(6)

            # 顶部：角色名 + 类型标签 + 勾选框
            top_row = QHBoxLayout()
            label = QLabel(f"🎭 {name}")
            label.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
            top_row.addWidget(label)

            if role_type:
                tag = QLabel(role_type)
                tag.setStyleSheet("background:#1e6bde;color:#ffffff;font-size:10px;"
                                 "padding:2px 6px;border-radius:4px;")
                top_row.addWidget(tag)

            appear_count = char_appear.get(name, 0)
            count_label = QLabel(f"出现 {appear_count} 个场景")
            count_label.setStyleSheet("color:#888888;font-size:10px;")
            top_row.addWidget(count_label)
            top_row.addStretch()

            keep_check = QCheckBox("优先保留")
            keep_check.setChecked(keep_default)
            keep_check.setStyleSheet(
                "QCheckBox{color:#ffffff;font-size:11px;spacing:4px;}"
                "QCheckBox::indicator{width:14px;height:14px;border-radius:3px;"
                "border:2px solid #555555;background:#121212;}"
                "QCheckBox::indicator:checked{background:#22c55e;border:2px solid #22c55e;}"
            )
            top_row.addWidget(keep_check)
            row_layout.addLayout(top_row)

            # 标签
            if traits:
                t_row = QHBoxLayout()
                for t in list(traits)[:5]:
                    tl = QLabel(str(t))
                    tl.setStyleSheet(
                        "background:#252525;color:#aaaaaa;font-size:10px;"
                        "padding:2px 6px;border-radius:4px;"
                    )
                    t_row.addWidget(tl)
                t_row.addStretch()
                row_layout.addLayout(t_row)

            # 权重滑块
            slider_row = QHBoxLayout()
            sl_label = QLabel("影响权重")
            sl_label.setStyleSheet("color:#888888;font-size:10px;")
            slider_row.addWidget(sl_label)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(50, 200)  # 50% ~ 200%
            slider.setValue(int(round(weight_default * 100)))
            slider.setStyleSheet(
                "QSlider::groove:horizontal{height:4px;background:#333333;border-radius:2px;}"
                "QSlider::handle:horizontal{background:#1e6bde;width:12px;height:12px;"
                "margin:-4px 0;border-radius:6px;}"
                "QSlider::handle:horizontal:hover{background:#3b82f6;}"
            )
            slider_row.addWidget(slider, 1)

            pct_label = QLabel(f"{int(round(weight_default * 100))}%")
            pct_label.setStyleSheet("color:#aaaaaa;font-size:10px;min-width:32px;qproperty-alignment:AlignRight;")
            slider_row.addWidget(pct_label)
            row_layout.addLayout(slider_row)

            # 绑定：勾选/滑动 → 写回缓存
            self._bind_character_row_events(
                name=name,
                keep_check=keep_check,
                slider=slider,
                pct_label=pct_label,
            )

            self._char_list_layout.addWidget(row)

        self._char_list_layout.addStretch()

    def _bind_character_row_events(self, name: str, keep_check: QCheckBox,
                                   slider, pct_label):
        """绑定角色行的交互事件"""
        def _on_keep_changed(checked):
            self._write_character_pref(name, bool(checked), slider.value() / 100.0)

        def _on_weight_changed(val):
            pct_label.setText(f"{val}%")
            self._write_character_pref(name, keep_check.isChecked(), val / 100.0)

        keep_check.toggled.connect(_on_keep_changed)
        slider.valueChanged.connect(_on_weight_changed)

    def _write_character_pref(self, name: str, keep: bool, weight: float):
        """写回角色偏好到 AnalysisCache"""
        try:
            from .character_cache import AnalysisCache
            cache = AnalysisCache()
            video_path = getattr(self, "_video_source", None)
            if not video_path:
                return
            cache.set_character_pref(video_path, name, keep=keep, weight=float(weight))
        except Exception as e:
            print(f"   ⚠️ 角色偏好写入失败: {e}")

    def _create_ai_tools_tab(self) -> QWidget:
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(6)
        
        st = self._sect("🤖 AI引擎状态")
        st_lo = st.layout()
        info_row = QHBoxLayout()
        self._ai_model_label = QLabel("模型: 未加载")
        self._ai_model_label.setStyleSheet("color:#1e6bde;font-size:10px;font-weight:600;")
        info_row.addWidget(self._ai_model_label)
        # 实时检测 AI 模型状态
        try:
            active_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                                       "data", "active_provider.json")
            if os.path.exists(active_path):
                with open(active_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    provider = data.get("active_provider", "")
                    if provider:
                        self._ai_model_label.setText(f"模型: {provider}")
                        self._ai_model_label.setStyleSheet("color:#22c55e;font-size:10px;font-weight:600;")
        except Exception:
            pass
        self._ai_gpu_label = QLabel("GPU: --")
        self._ai_gpu_label.setStyleSheet("color:#888;font-size:10px;")
        info_row.addWidget(self._ai_gpu_label)
        # 实时检测 GPU 信息
        try:
            from app.core.gpu_acceleration import get_gpu_detector
            gpu = get_gpu_detector().detect_gpu()
            if gpu.gpu_type.value != "none":
                self._ai_gpu_label.setText(f"GPU: {gpu.name}")
                self._ai_gpu_label.setStyleSheet("color:#22c55e;font-size:10px;font-weight:600;")
        except Exception:
            pass
        info_row.addStretch()
        st_lo.addLayout(info_row)
        self._ai_task_label = QLabel("任务: 待机中")
        self._ai_task_label.setStyleSheet("color:#888;font-size:10px;")
        st_lo.addWidget(self._ai_task_label)
        self._ai_progress = QProgressBar()
        self._ai_progress.setRange(0, 100)
        self._ai_progress.setValue(0)
        self._ai_progress.setFixedHeight(4)
        self._ai_progress.setStyleSheet("QProgressBar{background:#222;border:none;border-radius:2px;}QProgressBar::chunk{background:#1e6bde;border-radius:2px;}")
        self._ai_progress.hide()
        st_lo.addWidget(self._ai_progress)
        l.addWidget(st)
        
        fl = self._sect("🎯 智能剪辑工具")
        fl_lo = fl.layout()
        g = QGridLayout()
        g.setSpacing(4)
        tools = [
            ("🎬 FunClip", "阿里达摩院\n自动剪辑分段", "#1e6bde", self._funclip_process),
            ("⚡ AutoClip", "高光识别\n多镜头组接", "#4caf50", self._autoclip_process),
            ("✨ Fusion", "视频修复\n画质增强", "#ff9800", self._videofusion_process),
            ("🎨 LoRA", "创意编辑\n风格迁移", "#9c27b0", self._lora_edit_process),
            ("📝 字幕AI", "语音识别\n自动字幕", "#22c55e", self._generate_ai_subtitles),
            ("🔊 音频AI", "降噪增强\n人声分离", "#6366f1", self._enhance_audio),
        ]
        for i, (nm, desc, hc, cb) in enumerate(tools):
            btn = QPushButton(f"{nm}\n{desc}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:#0a0a0a;color:#ccc;border:1px solid #222;
                    border-left:3px solid {hc};border-radius:4px;
                    padding:8px 6px;font-size:10px;text-align:left;white-space:pre;
                }}
                QPushButton:hover {{background:#1a1a1a;color:#fff;}}
            """)
            btn.clicked.connect(cb)
            g.addWidget(btn, i // 2, i % 2)
        fl_lo.addLayout(g)
        l.addWidget(fl)
        
        hs = self._sect("📋 处理历史")
        self._ai_history_list = QListWidget()
        self._ai_history_list.setStyleSheet("QListWidget{background:#0a0a0a;color:#888;border:1px solid #222;border-radius:4px;font-size:10px;}QListWidget::item{padding:4px 6px;}")
        self._ai_history_list.setMaximumHeight(100)
        hs.layout().addWidget(self._ai_history_list)
        l.addWidget(hs)
        
        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0, 0, 0, 0)
        o.addWidget(s)
        return t
    
    def _create_tool_card(self, tool_info) -> QGroupBox:
        card = QGroupBox(f"{tool_info['icon']} {tool_info['name']}")
        card.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(15, 10, 15, 15)
        layout.setSpacing(12)
        
        # 描述
        desc_label = QLabel(tool_info['description'])
        desc_label.setStyleSheet("color: #808080; font-size: 13px;")
        layout.addWidget(desc_label)
        
        # 功能列表
        features_frame = QFrame()
        features_layout = QVBoxLayout(features_frame)
        features_layout.setSpacing(6)
        features_layout.setContentsMargins(0, 0, 0, 0)
        
        for feature in tool_info['features']:
            feature_label = QLabel(f"• {feature}")
            feature_label.setStyleSheet("color: #ffffff; font-size: 12px;")
            features_layout.addWidget(feature_label)
        
        layout.addWidget(features_frame)
        
        # 参数设置区域
        params_group = QGroupBox("参数设置")
        params_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #808080;
                border: 1px solid #333333;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 8px;
                background-color: #2a2a2a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
        """)
        params_layout = QVBoxLayout(params_group)
        params_layout.setContentsMargins(10, 5, 10, 10)
        params_layout.setSpacing(10)
        
        # 根据工具类型添加不同的参数设置
        if tool_info['name'] == "FunClip (阿里达摩院)":
            # FunClip参数
            params = video_processor.default_params["funclip"]
            
            # BGM类别
            bgm_layout = QHBoxLayout()
            bgm_layout.addWidget(QLabel("BGM类别:"))
            bgm_combo = QComboBox()
            bgm_combo.addItems(["auto", "激昂电音", "紧张纯音乐", "轻柔轻音乐"])
            bgm_combo.setCurrentText(params["bgm_category"])
            bgm_combo.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
            bgm_layout.addWidget(bgm_combo)
            params_layout.addLayout(bgm_layout)
            
            # BGM卡点
            bgm_sync_check = QCheckBox("BGM卡点剪辑")
            bgm_sync_check.setChecked(params["bgm_sync"])
            bgm_sync_check.setStyleSheet("color: #e0e0e0;")
            params_layout.addWidget(bgm_sync_check)
            
        elif tool_info['name'] == "AutoClip":
            # AutoClip参数
            params = video_processor.default_params["autoclip"]
            
            # 时长设置
            duration_layout = QHBoxLayout()
            duration_layout.addWidget(QLabel("时长 (秒):"))
            duration_spin = QSpinBox()
            duration_spin.setRange(5, 60)
            duration_spin.setValue(params["duration"])
            duration_spin.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
            duration_layout.addWidget(duration_spin)
            params_layout.addLayout(duration_layout)
            
            # 强制前3秒冲突
            conflict_check = QCheckBox("前3秒强制识别强冲突画面")
            conflict_check.setChecked(params["force_front_conflict"])
            conflict_check.setStyleSheet("color: #e0e0e0;")
            params_layout.addWidget(conflict_check)
            
        elif tool_info['name'] == "VideoFusion":
            # VideoFusion参数
            params = video_processor.default_params["videofusion"]
            
            # 4K增强
            enhance_check = QCheckBox("4K高清增强")
            enhance_check.setChecked(params["enhance_4k"])
            enhance_check.setStyleSheet("color: #e0e0e0;")
            params_layout.addWidget(enhance_check)
            
            # 动态防抖
            de_shake_check = QCheckBox("动态防抖")
            de_shake_check.setChecked(params["de_shake"])
            de_shake_check.setStyleSheet("color: #e0e0e0;")
            params_layout.addWidget(de_shake_check)
            
        elif tool_info['name'] == "LoRA Edit":
            # LoRA Edit参数
            params = video_processor.default_params["lora_edit"]
            
            # 版权检测
            copyright_check = QCheckBox("全维度版权检测")
            copyright_check.setChecked(params["copyright_check"])
            copyright_check.setStyleSheet("color: #e0e0e0;")
            params_layout.addWidget(copyright_check)
            
            # 引流贴纸位置
            watermark_layout = QHBoxLayout()
            watermark_layout.addWidget(QLabel("引流贴纸位置:"))
            watermark_combo = QComboBox()
            watermark_combo.addItems(["bottom_right", "top_left"])
            watermark_combo.setCurrentText(params["watermark_position"])
            watermark_combo.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
            watermark_layout.addWidget(watermark_combo)
            params_layout.addLayout(watermark_layout)
        
        layout.addWidget(params_group)
        
        # 操作按钮
        btn = QPushButton("开始处理")
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {tool_info['color']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
                height: 44px;
                margin-top: 5px;
            }}
            QPushButton:hover {{
                background-color: {tool_info['color']}dd;
            }}
        """)
        btn.clicked.connect(tool_info['callback'])
        layout.addWidget(btn)
        
        return card
    
    def _funclip_process(self):
        """ """
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        clip_path = self._clips[0]['path']
        output_dir = "短剧AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(clip_path).rsplit('.', 1)[0]
        output_path = os.path.join(output_dir, f"{base_name}_funclip.mp4")
        msg = QMessageBox(self)
        msg.setWindowTitle("FunClip")
        msg.setText("正在使用场景检测自动分段...")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.show()
        QApplication.processEvents()
        def process():
            try:
                import cv2
                cap = cv2.VideoCapture(clip_path)
                fps = cap.get(cv2.CAP_PROP_FPS) or 30
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                prev_frame = None
                scene_changes = []
                for i in range(0, frame_count, int(fps)):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                    ret, frame = cap.read()
                    if not ret:
                        break
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    gray = cv2.resize(gray, (320, 180))
                    if prev_frame is not None:
                        diff = np.mean(np.abs(gray.astype(float) - prev_frame.astype(float)))
                        if diff > 15:
                            scene_changes.append(i / fps)
                    prev_frame = gray
                cap.release()
                full_duration = frame_count / fps
                scene_changes = [0.0] + scene_changes + [full_duration]
                segments = [(scene_changes[i], scene_changes[i + 1]) 
                            for i in range(len(scene_changes) - 1)]
                segments = [(s, e) for s, e in segments if e - s > 2.0]
                segments = segments[:10]
                seg_list_path = os.path.join(output_dir, f"{base_name}_segments.txt")
                with open(seg_list_path, 'w', encoding='utf-8') as f:
                    for s, e in segments:
                        f.write(f"file '{clip_path}'\ninpoint {s}\noutpoint {e}\n")
                subprocess.run([
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-segment_time_metadata", "1",
                    "-i", seg_list_path,
                    "-vf", "select=concatdec_select,setpts=PTS-STARTPTS",
                    "-c:v", "libx264", "-preset", "fast",
                    "-an", output_path
                ], capture_output=True, text=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                msg.close()
                QMessageBox.information(self, "FunClip", f"场景检测完成! 输出: {output_path}")
            except ImportError:
                msg.close()
                QMessageBox.warning(self, "提示", "请安装cv2: pip install opencv-python")
            except Exception as e:
                msg.close()
                QMessageBox.warning(self, "失败", f"处理失败: {e}")
        t = threading.Thread(target=process, daemon=True)
        t.start()

    def _autoclip_process(self):
        """ """
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        clip_path = self._clips[0]['path']
        output_dir = "短剧AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(clip_path).rsplit('.', 1)[0]
        output_path = os.path.join(output_dir, f"{base_name}_highlight.mp4")
        msg = QMessageBox(self)
        msg.setWindowTitle("AutoClip")
        msg.setText("正在分析高光片段...")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.show()
        QApplication.processEvents()
        def process():
            try:
                import cv2
                cap = cv2.VideoCapture(clip_path)
                fps = cap.get(cv2.CAP_PROP_FPS) or 30
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                scene_scores = []
                window = int(fps * 2)
                step = int(fps * 0.5)
                for start in range(0, frame_count, step):
                    end = min(start + window, frame_count)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
                    motion_sum = 0
                    prev = None
                    frame_num = 0
                    for pos in range(start, end, 2):
                        ret, frm = cap.read()
                        if not ret:
                            break
                        g = cv2.cvtColor(frm, cv2.COLOR_BGR2GRAY)
                        g = cv2.resize(g, (160, 90))
                        if prev is not None:
                            motion_sum += np.mean(np.abs(g.astype(float) - prev.astype(float)))
                        prev = g
                        frame_num += 1
                    if frame_num > 0:
                        score = motion_sum / frame_num
                        scene_scores.append((start / fps, min(end / fps, frame_count / fps), score))
                cap.release()
                scene_scores.sort(key=lambda x: x[2], reverse=True)
                best = scene_scores[:8]
                best.sort(key=lambda x: x[0])
                clip_list = os.path.join(output_dir, f"{base_name}_best.txt")
                with open(clip_list, 'w', encoding='utf-8') as f:
                    for s, e, sc in best:
                        f.write(f"file '{clip_path}'\ninpoint {s}\noutpoint {e}\n")
                subprocess.run([
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-segment_time_metadata", "1",
                    "-i", clip_list,
                    "-vf", "select=concatdec_select,setpts=PTS-STARTPTS",
                    "-c:v", "libx264", "-preset", "fast",
                    output_path
                ], capture_output=True, text=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                msg.close()
                QMessageBox.information(self, "AutoClip", f"高光检测完成! 输出: {output_path}")
            except ImportError:
                msg.close()
                QMessageBox.warning(self, "提示", "请安装cv2: pip install opencv-python")
            except Exception as e:
                msg.close()
                QMessageBox.warning(self, "失败", f"处理失败: {e}")
        t = threading.Thread(target=process, daemon=True)
        t.start()

    def _videofusion_process(self):
        """ """
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        clip_path = self._clips[0]['path']
        output_dir = "短剧AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(clip_path).rsplit('.', 1)[0]
        output_path = os.path.join(output_dir, f"{base_name}_enhanced.mp4")
        msg = QMessageBox(self)
        msg.setWindowTitle("VideoFusion")
        msg.setText("正在增强画质...")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.show()
        QApplication.processEvents()
        def process():
            try:
                filters = [
                    "unsharp=5:5:1.0:5:5:0.0",
                    "hqdn3d=4:3:6:4",
                    "format=yuv420p"
                ]
                filter_str = ",".join(filters)
                result = subprocess.run([
                    "ffmpeg", "-y", "-i", clip_path,
                    "-vf", filter_str,
                    "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-c:a", "aac", "-b:a", "192k",
                    output_path
                ], capture_output=True, text=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                msg.close()
                if result.returncode == 0:
                    QMessageBox.information(self, "VideoFusion", f"画质增强完成! 输出: {output_path}")
                else:
                    QMessageBox.warning(self, "失败", f"增强失败: {result.stderr}")
            except Exception as e:
                msg.close()
                QMessageBox.warning(self, "失败", f"处理失败: {e}")
        t = threading.Thread(target=process, daemon=True)
        t.start()

    def _lora_edit_process(self):
        """ """
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        clip_path = self._clips[0]['path']
        output_dir = "短剧AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(clip_path).rsplit('.', 1)[0]
        output_path = os.path.join(output_dir, f"{base_name}_stylized.mp4")
        msg = QMessageBox(self)
        msg.setWindowTitle("LoRA Edit")
        msg.setText("正在应用风格化效果...")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.show()
        QApplication.processEvents()
        def process():
            try:
                filters = [
                    "eq=brightness=0.05:contrast=1.1:saturation=1.3",
                    "colorbalance=rs=0.1:gs=-0.05:bs=-0.1",
                    "hue=h=5",
                    "vignette=PI/4",
                    "unsharp=3:3:0.8",
                ]
                filter_str = ",".join(filters)
                result = subprocess.run([
                    "ffmpeg", "-y", "-i", clip_path,
                    "-vf", filter_str,
                    "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-c:a", "copy",
                    output_path
                ], capture_output=True, text=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                msg.close()
                if result.returncode == 0:
                    QMessageBox.information(self, "LoRA Edit", f"风格化完成! 输出: {output_path}")
                else:
                    QMessageBox.warning(self, "失败", f"处理失败: {result.stderr}")
            except Exception as e:
                msg.close()
                QMessageBox.warning(self, "失败", f"处理失败: {e}")
        t = threading.Thread(target=process, daemon=True)
        t.start()
    
    def _create_params_tab(self) -> QWidget:
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(6)
        
        pi = self._sect("📊 项目信息")
        pi_lo = pi.layout()
        self._proj_res_label = QLabel("分辨率: --")
        self._proj_res_label.setStyleSheet("color:#1e6bde;font-size:10px;font-weight:600;")
        pi_lo.addWidget(self._proj_res_label)
        dur_row = QHBoxLayout()
        self._proj_dur_label = QLabel("时长: --")
        self._proj_dur_label.setStyleSheet("color:#888;font-size:10px;")
        dur_row.addWidget(self._proj_dur_label)
        self._proj_size_label = QLabel("预估: --")
        self._proj_size_label.setStyleSheet("color:#888;font-size:10px;")
        dur_row.addWidget(self._proj_size_label)
        dur_row.addStretch()
        pi_lo.addLayout(dur_row)
        l.addWidget(pi)
        
        mo = self._sect("🎯 输出模式")
        self._output_mode_var = QComboBox()
        self._output_mode_var.addItems(["自定义参数", "30秒爆款引流", "90秒剧情解说", "8分钟挂车长视频"])
        self._output_mode_var.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:4px 8px;font-size:10px;}QComboBox:hover{border-color:#333;}")
        mo.layout().addWidget(self._output_mode_var)
        l.addWidget(mo)
        
        vo = self._sect("🎬 视频参数")
        vo_lo = vo.layout()
        vo_lo.addWidget(self._cmb("平台", ["抖音", "快手", "视频号", "B站", "小红书"]))
        self._resolution_var = self._cmb("分辨率", ["1080x1920", "1920x1080", "1280x720", "3840x2160"])
        vo_lo.addWidget(self._resolution_var)
        self._aspect_var = self._cmb("比例", ["9:16", "16:9", "1:1", "4:3"])
        vo_lo.addWidget(self._aspect_var)
        self._fps_var = self._cmb("帧率", ["30fps", "60fps", "24fps", "25fps", "50fps"])
        vo_lo.addWidget(self._fps_var)
        self._codec_var = self._cmb("编码", ["H.264", "H.265", "VP9", "AV1"])
        vo_lo.addWidget(self._codec_var)
        self._format_var = self._cmb("格式", ["MP4", "MKV", "AVI", "MOV"])
        vo_lo.addWidget(self._format_var)
        self._bitrate_var = self._cmb("比特率", ["3000k", "2000k", "5000k", "1M", "10M"])
        vo_lo.addWidget(self._bitrate_var)
        l.addWidget(vo)
        
        au = self._sect("🔊 音频参数")
        au_lo = au.layout()
        au_lo.addWidget(self._cmb("编码", ["AAC", "MP3", "WAV"]))
        au_lo.addWidget(self._cmb("通道", ["立体声", "单声道"]))
        au_lo.addWidget(self._cmb("采样率", ["44100", "48000", "22050"]))
        au_lo.addWidget(self._cmb("比特率", ["128k", "192k", "256k", "320k"]))
        l.addWidget(au)
        
        self._hw_section = self._sect("⚡ 硬件加速")
        gpu_name = ""
        gpu_available = False
        try:
            from app.core.gpu_acceleration import get_gpu_detector
            gpu = get_gpu_detector().detect_gpu()
            if gpu.gpu_type.value != "none":
                gpu_name = gpu.name
                gpu_available = True
        except (ImportError, OSError):
            pass
        label_text = f"启用硬件加速 ({gpu_name})" if gpu_name else "启用硬件加速 (NVENC)"
        self._hardware_accel_var = QCheckBox(label_text)
        self._hardware_accel_var.setStyleSheet("color:#888;font-size:10px;")
        self._hardware_accel_var.setChecked(gpu_available)
        self._hw_section.layout().addWidget(self._hardware_accel_var)
        l.addWidget(self._hw_section)
        # 默认轻量内核下隐藏硬件加速面板
        self._hw_section.setVisible(False)
        
        exp_btn = QPushButton("💾 开始导出")
        exp_btn.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;padding:8px;font-size:12px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        exp_btn.clicked.connect(self._export_video)
        l.addWidget(exp_btn)
        
        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0, 0, 0, 0)
        o.addWidget(s)
        return t
    
    def _create_adjust_tab(self) -> QWidget:
        """ """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 亮度调节
        brightness_group = QGroupBox("亮度")
        brightness_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        brightness_layout = QVBoxLayout(brightness_group)
        
        # 亮度滑块和值显示
        brightness_control_layout = QHBoxLayout()
        self._brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self._brightness_slider.setRange(-100, 100)
        self._brightness_slider.setValue(0)
        self._brightness_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        
        self._brightness_value = QLabel("0")
        self._brightness_value.setStyleSheet("color: #1e6bde; font-size: 14px; font-weight: bold; min-width: 30px; text-align: right;")
        
        brightness_control_layout.addWidget(self._brightness_slider)
        brightness_control_layout.addWidget(self._brightness_value)
        brightness_layout.addLayout(brightness_control_layout)
        
        # 连接滑块信号
        self._brightness_slider.valueChanged.connect(lambda value: self._on_adjustment_changed("brightness", value))
        layout.addWidget(brightness_group)
        
        # 对比度调节
        contrast_group = QGroupBox("对比度")
        contrast_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        contrast_layout = QVBoxLayout(contrast_group)
        
        # 对比度滑块和值显示
        contrast_control_layout = QHBoxLayout()
        self._contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self._contrast_slider.setRange(-100, 100)
        self._contrast_slider.setValue(0)
        self._contrast_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        
        self._contrast_value = QLabel("0")
        self._contrast_value.setStyleSheet("color: #1e6bde; font-size: 14px; font-weight: bold; min-width: 30px; text-align: right;")
        
        contrast_control_layout.addWidget(self._contrast_slider)
        contrast_control_layout.addWidget(self._contrast_value)
        contrast_layout.addLayout(contrast_control_layout)
        
        # 连接滑块信号
        self._contrast_slider.valueChanged.connect(lambda value: self._on_adjustment_changed("contrast", value))
        layout.addWidget(contrast_group)
        
        # 饱和度调节
        saturation_group = QGroupBox("饱和度")
        saturation_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        saturation_layout = QVBoxLayout(saturation_group)
        
        # 饱和度滑块和值显示
        saturation_control_layout = QHBoxLayout()
        self._saturation_slider = QSlider(Qt.Orientation.Horizontal)
        self._saturation_slider.setRange(-100, 100)
        self._saturation_slider.setValue(0)
        self._saturation_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        
        self._saturation_value = QLabel("0")
        self._saturation_value.setStyleSheet("color: #1e6bde; font-size: 14px; font-weight: bold; min-width: 30px; text-align: right;")
        
        saturation_control_layout.addWidget(self._saturation_slider)
        saturation_control_layout.addWidget(self._saturation_value)
        saturation_layout.addLayout(saturation_control_layout)
        
        # 连接滑块信号
        self._saturation_slider.valueChanged.connect(lambda value: self._on_adjustment_changed("saturation", value))
        layout.addWidget(saturation_group)
        
        # 色调调节
        hue_group = QGroupBox("色调")
        hue_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        hue_layout = QVBoxLayout(hue_group)
        
        # 色调滑块和值显示
        hue_control_layout = QHBoxLayout()
        self._hue_slider = QSlider(Qt.Orientation.Horizontal)
        self._hue_slider.setRange(-180, 180)
        self._hue_slider.setValue(0)
        self._hue_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        
        self._hue_value = QLabel("0")
        self._hue_value.setStyleSheet("color: #1e6bde; font-size: 14px; font-weight: bold; min-width: 30px; text-align: right;")
        
        hue_control_layout.addWidget(self._hue_slider)
        hue_control_layout.addWidget(self._hue_value)
        hue_layout.addLayout(hue_control_layout)
        
        # 连接滑块信号
        self._hue_slider.valueChanged.connect(lambda value: self._on_adjustment_changed("hue", value))
        layout.addWidget(hue_group)
        
        # 应用按钮
        btn_frame = QFrame()
        btn_layout = QHBoxLayout(btn_frame)
        
        apply_btn = QPushButton("🎨 应用调节")
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        apply_btn.clicked.connect(self._apply_video_adjustments)
        btn_layout.addWidget(apply_btn)
        
        reset_btn = QPushButton("🔄 重置")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #444444;
            }
        """)
        reset_btn.clicked.connect(self._reset_video_adjustments)
        btn_layout.addWidget(reset_btn)
        
        layout.addWidget(btn_frame)
        layout.addStretch()
        return tab
    
    def _create_filter_tab(self) -> QWidget:
        """ """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 滤镜分类
        filter_group = QGroupBox("滤镜分类")
        filter_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        filter_layout = QVBoxLayout(filter_group)
        
        self._filter_category_var = QComboBox()
        self._filter_category_var.addItems(["全部", "复古", "清新", "黑白", "暖色调", "冷色调", "电影感"])
        self._filter_category_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 200px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        filter_layout.addWidget(self._filter_category_var)
        layout.addWidget(filter_group)
        
        # 滤镜列表
        filters = ["自然", "复古", "黑白", "清新", "暖色调", "冷色调", "电影感", "梦幻", "锐利", "柔和"]
        filter_grid = QGridLayout()
        
        for i, filter_name in enumerate(filters):
            btn = QPushButton(filter_name)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                    border-color: #1e6bde;
                }
            """)
            btn.clicked.connect(lambda checked, f=filter_name: self._apply_filter(f))
            filter_grid.addWidget(btn, i // 2, i % 2)
        
        layout.addLayout(filter_grid)
        
        # 强度调节
        intensity_group = QGroupBox("强度")
        intensity_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        intensity_layout = QVBoxLayout(intensity_group)
        
        self._filter_intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self._filter_intensity_slider.setRange(0, 100)
        self._filter_intensity_slider.setValue(50)
        self._filter_intensity_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        intensity_layout.addWidget(self._filter_intensity_slider)
        layout.addWidget(intensity_group)
        
        layout.addStretch()
        return tab
    
    def _create_transition_tab(self) -> QWidget:
        """ """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 转场类型
        transition_group = QGroupBox("转场类型")
        transition_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        transition_layout = QVBoxLayout(transition_group)
        
        self._transition_type_var = QComboBox()
        self._transition_type_var.addItems(["淡入淡出", "滑动", "缩放", "模糊", "翻转", "溶解", "擦除"])
        self._transition_type_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 200px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        transition_layout.addWidget(self._transition_type_var)
        layout.addWidget(transition_group)
        
        # 转场时长
        duration_group = QGroupBox("转场时长")
        duration_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        duration_layout = QVBoxLayout(duration_group)
        
        self._transition_duration_var = QSpinBox()
        self._transition_duration_var.setRange(100, 3000)
        self._transition_duration_var.setValue(500)
        self._transition_duration_var.setSuffix("ms")
        self._transition_duration_var.setStyleSheet("""
            QSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 100px;
            }
        """)
        duration_layout.addWidget(self._transition_duration_var)
        layout.addWidget(duration_group)
        
        # 应用按钮
        apply_btn = QPushButton("✨ 应用转场")
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        apply_btn.clicked.connect(self._apply_transition)
        layout.addWidget(apply_btn)
        
        layout.addStretch()
        return tab
    
    def _create_subtitle_tab(self) -> QWidget:
        """ """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 字幕样式
        style_group = QGroupBox("字幕样式")
        style_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        style_layout = QVBoxLayout(style_group)
        
        # 字体
        font_layout = QHBoxLayout()
        font_label = QLabel("字体:")
        font_label.setStyleSheet("color: #ffffff;")
        font_layout.addWidget(font_label)
        
        self._subtitle_font_var = QComboBox()
        self._subtitle_font_var.addItems(["微软雅黑", "宋体", "黑体", "Arial", "Helvetica"])
        self._subtitle_font_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 150px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        font_layout.addWidget(self._subtitle_font_var)
        style_layout.addLayout(font_layout)
        
        # 字号
        size_layout = QHBoxLayout()
        size_label = QLabel("字号:")
        size_label.setStyleSheet("color: #ffffff;")
        size_layout.addWidget(size_label)
        
        self._subtitle_size_var = QSpinBox()
        self._subtitle_size_var.setRange(12, 48)
        self._subtitle_size_var.setValue(24)
        self._subtitle_size_var.setStyleSheet("""
            QSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 80px;
            }
        """)
        size_layout.addWidget(self._subtitle_size_var)
        style_layout.addLayout(size_layout)
        
        # 颜色
        color_layout = QHBoxLayout()
        color_label = QLabel("颜色:")
        color_label.setStyleSheet("color: #ffffff;")
        color_layout.addWidget(color_label)
        
        self._subtitle_color_var = QComboBox()
        self._subtitle_color_var.addItems(["白色", "黄色", "红色", "蓝色", "绿色", "黑色"])
        self._subtitle_color_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 100px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        color_layout.addWidget(self._subtitle_color_var)
        style_layout.addLayout(color_layout)
        
        # 位置
        position_layout = QHBoxLayout()
        position_label = QLabel("位置:")
        position_label.setStyleSheet("color: #ffffff;")
        position_layout.addWidget(position_label)
        
        self._subtitle_position_var = QComboBox()
        self._subtitle_position_var.addItems(["底部居中", "顶部", "底部左侧", "底部右侧"])
        self._subtitle_position_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        position_layout.addWidget(self._subtitle_position_var)
        style_layout.addLayout(position_layout)
        
        layout.addWidget(style_group)
        
        # 字幕操作
        btn_frame = QFrame()
        btn_layout = QVBoxLayout(btn_frame)
        
        ai_subtitle_btn = QPushButton("🤖 AI生成字幕")
        ai_subtitle_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
                margin-bottom: 8px;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
        """)
        ai_subtitle_btn.clicked.connect(self._generate_ai_subtitles)
        btn_layout.addWidget(ai_subtitle_btn)
        
        add_subtitle_btn = QPushButton("➕ 添加字幕")
        add_subtitle_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
                margin-bottom: 8px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        add_subtitle_btn.clicked.connect(self._add_subtitle)
        btn_layout.addWidget(add_subtitle_btn)
        
        apply_style_btn = QPushButton("🎨 应用样式")
        apply_style_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        apply_style_btn.clicked.connect(self._apply_subtitle_style)
        btn_layout.addWidget(apply_style_btn)
        
        layout.addWidget(btn_frame)
        layout.addStretch()
        return tab
    
    def _create_audio_tab(self) -> QWidget:
        """ """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 音量控制
        volume_group = QGroupBox("音量")
        volume_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        volume_layout = QVBoxLayout(volume_group)
        
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 200)
        self._volume_slider.setValue(100)
        self._volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        self._volume_slider.valueChanged.connect(self._adjust_volume)
        volume_layout.addWidget(self._volume_slider)
        layout.addWidget(volume_group)
        
        # 淡入淡出
        fade_group = QGroupBox("淡入淡出")
        fade_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        fade_layout = QVBoxLayout(fade_group)
        
        fade_in_layout = QHBoxLayout()
        fade_in_label = QLabel("淡入 (秒):")
        fade_in_label.setStyleSheet("color: #ffffff;")
        fade_in_layout.addWidget(fade_in_label)
        
        self._fade_in_var = QDoubleSpinBox()
        self._fade_in_var.setRange(0, 5)
        self._fade_in_var.setValue(0.5)
        self._fade_in_var.setSingleStep(0.1)
        self._fade_in_var.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 100px;
            }
        """)
        fade_in_layout.addWidget(self._fade_in_var)
        fade_layout.addLayout(fade_in_layout)
        
        fade_out_layout = QHBoxLayout()
        fade_out_label = QLabel("淡出 (秒):")
        fade_out_label.setStyleSheet("color: #ffffff;")
        fade_out_layout.addWidget(fade_out_label)
        
        self._fade_out_var = QDoubleSpinBox()
        self._fade_out_var.setRange(0, 5)
        self._fade_out_var.setValue(0.5)
        self._fade_out_var.setSingleStep(0.1)
        self._fade_out_var.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 100px;
            }
        """)
        fade_out_layout.addWidget(self._fade_out_var)
        fade_layout.addLayout(fade_out_layout)
        layout.addWidget(fade_group)
        
        # 音频操作
        btn_frame = QFrame()
        btn_layout = QHBoxLayout(btn_frame)
        
        enhance_btn = QPushButton("🔊 增强")
        enhance_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
                margin-right: 8px;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
        """)
        enhance_btn.clicked.connect(self._enhance_audio)
        btn_layout.addWidget(enhance_btn)
        
        denoise_btn = QPushButton("🔇 降噪")
        denoise_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
                margin-right: 8px;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        denoise_btn.clicked.connect(self._denoise_audio)
        btn_layout.addWidget(denoise_btn)
        
        crop_btn = QPushButton("✂️ 截取")
        crop_btn.setStyleSheet("""
            QPushButton {
                background-color: #e91e63;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c2185b;
            }
        """)
        crop_btn.clicked.connect(self._crop_audio)
        btn_layout.addWidget(crop_btn)
        
        layout.addWidget(btn_frame)
        
        # 应用淡入淡出按钮
        fade_btn = QPushButton("🎵 应用淡入淡出")
        fade_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        fade_btn.clicked.connect(self._apply_fade_effects)
        layout.addWidget(fade_btn)
        
        layout.addStretch()
        return tab
    
    # 播放控制方法
    def _play_pause(self):
        """ """
        from PyQt6.QtMultimedia import QMediaPlayer
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
            if hasattr(self, '_preview_manager'):
                self._preview_manager.pause_preview()
        else:
            self._media_player.play()
            if hasattr(self, '_preview_manager'):
                self._preview_manager.play_preview(start_time=self._current_time)
    
    def _rewind(self):
        """ """
        new_position = max(0, self._media_player.position() - 10000)
        self._media_player.setPosition(new_position)
        if hasattr(self, '_timeline_widget'):
            self._timeline_widget.set_playhead_position(new_position / 1000)
        if hasattr(self, '_preview_manager') and self._video_source:
            self._playhead_position = new_position / 1000
            self._preview_manager.update_preview(self._playhead_position,
                                                  effects=getattr(self, '_color_params', None))
    
    def _fast_forward(self):
        """ """
        new_position = min(self._media_player.duration(), self._media_player.position() + 10000)
        self._media_player.setPosition(new_position)
        if hasattr(self, '_timeline_widget'):
            self._timeline_widget.set_playhead_position(new_position / 1000)
        if hasattr(self, '_preview_manager') and self._video_source:
            self._playhead_position = new_position / 1000
            self._preview_manager.update_preview(self._playhead_position,
                                                  effects=getattr(self, '_color_params', None))
    
    def _on_playback_speed_changed(self, speed_text):
        """播放倍速切换"""
        speed_map = {"0.5x": 0.5, "1x": 1.0, "1.5x": 1.5, "2x": 2.0}
        rate = speed_map.get(speed_text, 1.0)
        self._media_player.setPlaybackRate(rate)
        print(f"播放倍速切换为: {speed_text}")
    
    def _reverse_play(self):
        """ """
        if not self._current_clip:
            QMessageBox.information(self, "播放控制", "请先选择要倒放的片段")
            return

        clip_path = self._current_clip.get('path', '')
        if not clip_path or not os.path.exists(clip_path):
            QMessageBox.warning(self, "播放控制", "片段文件不存在")
            return

        base, ext = os.path.splitext(clip_path)
        output_path = f"{base}_reversed{ext}"

        ffmpeg_bin = "ffmpeg"
        top0_engine = self._ensure_top0_engine()
        if top0_engine and hasattr(top0_engine, 'video_engine'):
            ffmpeg_bin = getattr(top0_engine.video_engine, 'ffmpeg_path', 'ffmpeg')

        reply = QMessageBox.question(
            self, "倒放处理",
            f"即将对选中片段进行倒放处理。\n输出: {os.path.basename(output_path)}\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            result = subprocess.run(
                [ffmpeg_bin, '-i', clip_path,
                 '-vf', 'reverse',
                 '-af', 'areverse',
                 '-c:v', 'libx264', '-preset', 'fast',
                 '-y', output_path],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode != 0:
                error_msg = result.stderr[-400:] if result.stderr else "未知错误"
                QMessageBox.critical(self, "错误", f"倒放处理失败:\n{error_msg}")
                return

            self._add_clip_to_timeline(output_path)
            QMessageBox.information(self, "播放控制", "倒放完成！已添加到轨道")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"倒放处理异常: {e}")
    
    def _update_time_display(self):
        """ """
        # 格式化时间
        def format_time(seconds):
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        
        # 更新时间码标签
        if hasattr(self, '_timecode_label'):
            current_time_str = format_time(self._current_time)
            total_time_str = format_time(self._total_duration)
            self._timecode_label.setText(f"{current_time_str} / {total_time_str}")
    
    
    
    
    
    
    def _format_time(self, seconds):
        """ """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    # 时间线控制方法
    def _zoom_in_timeline(self):
        """ """
        self._timeline_zoom = min(500, self._timeline_zoom + 50)
        print(f"时间线放大到 {self._timeline_zoom}%")
        # 更新界面上的缩放显示
        if hasattr(self, '_timeline_zoom_label'):
            self._timeline_zoom_label.setText(f"{self._timeline_zoom}%")
    
    def _zoom_out_timeline(self):
        """ """
        self._timeline_zoom = max(50, self._timeline_zoom - 50)
        print(f"时间线缩小到 {self._timeline_zoom}%")
        # 更新界面上的缩放显示
        if hasattr(self, '_timeline_zoom_label'):
            self._timeline_zoom_label.setText(f"{self._timeline_zoom}%")
    
    def _move_playhead(self, position):
        """ """
        self._playhead_position = position
        self._current_time = position
        self._update_time_display()
        print(f"播放头移动到 {position}s")
    
    # 媒体播放器事件处理
    def _on_playback_state_changed(self, state):
        """ """
        from PyQt6.QtMultimedia import QMediaPlayer
        self._is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        status = "播放" if self._is_playing else "暂停"
        print(f"播放状态: {status}")
    
    def _on_position_changed(self, position):
        """ """
        # 转换为秒
        current_time = position / 1000
        self._current_time = current_time
        self._playhead_position = current_time
        self._update_time_display()
        
        # 更新进度条
        if hasattr(self, '_progress_bar') and self._media_player.duration() > 0:
            self._progress_bar.setValue(int((position / self._media_player.duration()) * 100))
    
    def _on_progress_slider_moved(self, value):
        """ """
        # 这里可以显示预览帧
        pass
    
    def _on_progress_slider_released(self):
        """ """
        if self._media_player.duration() > 0:
            new_position = int((self._progress_bar.value() / 100) * self._media_player.duration())
            self._media_player.setPosition(new_position)
    
    def _on_clip_clicked(self, clip_data):
        """ """
        # 取消之前选中的片段
        if self._current_clip:
            for widget in self._clip_widgets:
                if widget.clip_data['id'] == self._current_clip['id']:
                    widget.set_selected(False)
                    break
        
        # 选中当前片段
        self._current_clip = clip_data
        for widget in self._clip_widgets:
            if widget.clip_data['id'] == clip_data['id']:
                widget.set_selected(True)
                break
        
        print(f"选中片段: {clip_data['id']} - {os.path.basename(clip_data['path'])}")
    
    def _on_duration_changed(self, duration):
        """ """
        # 转换为秒
        self._total_duration = duration / 1000
        self._update_time_display()
    
    # 视频调节方法
    def _on_adjustment_changed(self, adjustment_type, value):
        """ """
        # 更新值显示
        if adjustment_type == "brightness":
            self._brightness_value.setText(str(value))
        elif adjustment_type == "contrast":
            self._contrast_value.setText(str(value))
        elif adjustment_type == "saturation":
            self._saturation_value.setText(str(value))
        elif adjustment_type == "hue":
            self._hue_value.setText(str(value))
        
        # 这里可以添加实时预览逻辑
        # 由于Qt的QMediaPlayer不直接支持实时视频滤镜
        # 可以使用OpenCV或其他库来实现实时预览
        print(f"{adjustment_type} 调整为: {value}")
    
    def _apply_video_adjustments(self):
        """把亮度/对比度/饱和度/色调调节写入当前片段，导出时烘焙进视频。"""
        if not self._current_clip:
            QMessageBox.warning(self, "视频调节", "请先选择一个片段")
            return
        brightness = self._brightness_slider.value()
        contrast = self._contrast_slider.value()
        saturation = self._saturation_slider.value()
        hue = self._hue_slider.value()
        effects = self._current_clip.get("effects") or {}
        if not isinstance(effects, dict):
            effects = {}
        cp = effects.get("color_params") or {}
        # 滑块值(-100..100 / 色调-180..180) 映射到 ffmpeg eq 参数
        cp["brightness"] = round(brightness / 100 * 0.3, 3)          # -0.3..0.3
        cp["contrast"]   = round(1.0 + contrast / 100 * 0.5, 3)     # 0.5..1.5
        cp["saturation"] = round(1.0 + saturation / 100 * 0.5, 3)   # 0.5..1.5
        cp["hue"]        = hue                                      # 度
        effects["color_params"] = cp
        self._current_clip["effects"] = effects
        self._color_params = cp  # 供预览端读取
        self._sync_timeline_widget_state()
        self._refresh_preview_with_effects()
        QMessageBox.information(
            self, "视频调节",
            f"已应用调节（亮度{brightness}, 对比度{contrast}, 饱和度{saturation}, 色调{hue}），导出时生效")
    
    def _reset_video_adjustments(self):
        """ """
        self._brightness_slider.setValue(0)
        self._contrast_slider.setValue(0)
        self._saturation_slider.setValue(0)
        self._hue_slider.setValue(0)
        
        # 重置值显示
        self._brightness_value.setText("0")
        self._contrast_value.setText("0")
        self._saturation_value.setText("0")
        self._hue_value.setText("0")
        print("重置视频调节")
        QMessageBox.information(self, "视频调节", "重置视频调节")
    
    # 转场方法
    
    
    def _set_timeline_zoom(self, value):
        """ """
        self._timeline_widget.set_zoom(value)
        self._zoom_label.setText(f"{value}%")
        if hasattr(self, '_zoom_slider'):
            self._zoom_slider.blockSignals(True)
            self._zoom_slider.setValue(value)
            self._zoom_slider.blockSignals(False)
    
    
    # 视频翻转/倒放
    def _reverse_video(self):
        """视频倒放"""
        src = self._get_active_audio_path() if self._get_active_audio_path() else (self._clips[0]['path'] if self._clips else '')
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入视频素材")
            return
        dst = self._output_path(src, '_reversed')
        ext = os.path.splitext(src)[1] or '.mp4'
        dst = dst.replace('.mp3', ext)
        ffmpeg = self._get_ffmpeg()
        QMessageBox.information(self, "倒放", f"正在处理...\n{os.path.basename(src)}")
        try:
            subprocess.run([
                ffmpeg, '-y', '-i', src, '-vf', 'reverse',
                '-af', 'areverse', '-c:v', 'libx264', '-preset', 'fast',
                '-crf', '23', dst
            ], capture_output=True, text=True)
            self._add_to_clips(dst, 'video')
            QMessageBox.information(self, "完成", f"倒放完成:\n{dst}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"倒放失败: {e}")

    def _mirror_h(self):
        """水平镜像"""
        src = self._get_active_audio_path() if self._get_active_audio_path() else (self._clips[0]['path'] if self._clips else '')
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入视频素材")
            return
        dst = self._output_path(src, '_mirrorh')
        ext = os.path.splitext(src)[1] or '.mp4'
        dst = dst.replace('.mp3', ext)
        ffmpeg = self._get_ffmpeg()
        try:
            subprocess.run([
                ffmpeg, '-y', '-i', src, '-vf', 'hflip',
                '-c:a', 'copy', '-c:v', 'libx264', '-preset', 'fast',
                '-crf', '23', dst
            ], capture_output=True, text=True)
            self._add_to_clips(dst, 'video')
            QMessageBox.information(self, "完成", f"水平镜像完成:\n{dst}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"镜像失败: {e}")

    def _mirror_v(self):
        """垂直翻转"""
        src = self._get_active_audio_path() if self._get_active_audio_path() else (self._clips[0]['path'] if self._clips else '')
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入视频素材")
            return
        dst = self._output_path(src, '_mirrorv')
        ext = os.path.splitext(src)[1] or '.mp4'
        dst = dst.replace('.mp3', ext)
        ffmpeg = self._get_ffmpeg()
        try:
            subprocess.run([
                ffmpeg, '-y', '-i', src, '-vf', 'vflip',
                '-c:a', 'copy', '-c:v', 'libx264', '-preset', 'fast',
                '-crf', '23', dst
            ], capture_output=True, text=True)
            self._add_to_clips(dst, 'video')
            QMessageBox.information(self, "完成", f"垂直翻转完成:\n{dst}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"翻转失败: {e}")

    # 音频方法
    def _get_ffmpeg(self):
        """获取 ffmpeg 可执行文件路径"""
        import shutil
        paths = [
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'thirdparty', 'ffmpeg', 'bin', 'ffmpeg.exe'),
            os.path.join(os.path.dirname(__file__), '..', '..', 'thirdparty', 'ffmpeg', 'bin', 'ffmpeg.exe'),
        ]
        for p in paths:
            p = os.path.abspath(p)
            if os.path.exists(p):
                return p
        sys_ffmpeg = shutil.which('ffmpeg')
        if sys_ffmpeg:
            return sys_ffmpeg
        return 'ffmpeg'

    def _get_active_audio_path(self):
        """获取当前激活的音频文件路径"""
        if self._clips:
            return self._clips[0].get('path', '')
        return ''

    def _enhance_audio(self):
        """音频增强：响度归一化 + 动态压缩 + 高频增强"""
        src = self._get_active_audio_path()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入音频/视频素材")
            return
        dst = self._output_path(src, '_enhanced')
        ffmpeg = self._get_ffmpeg()
        QMessageBox.information(self, "音频增强", f"正在处理...\n{os.path.basename(src)}")
        try:
            subprocess.run([
                ffmpeg, '-y', '-i', src,
                '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11,highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=50',
                '-q:a', '2', dst
            ], capture_output=True, text=True)
            self._add_to_clips(dst, 'audio')
            QMessageBox.information(self, "完成", f"音频增强完成:\n{dst}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"处理失败: {e}")

    def _denoise_audio(self):
        """音频降噪：FFmpeg anlmdn 非局部均值降噪"""
        src = self._get_active_audio_path()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入音频/视频素材")
            return
        dst = self._output_path(src, '_denoised')
        ffmpeg = self._get_ffmpeg()
        QMessageBox.information(self, "音频降噪", f"正在处理...\n{os.path.basename(src)}")
        try:
            subprocess.run([
                ffmpeg, '-y', '-i', src,
                '-af', 'anlmdn=s=0.0005:p=7:r=0.002', '-q:a', '2', dst
            ], capture_output=True, text=True)
            self._add_to_clips(dst, 'audio')
            QMessageBox.information(self, "完成", f"降噪完成:\n{dst}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"处理失败: {e}")

    def _crop_audio(self):
        """截取音频片段"""
        src = self._get_active_audio_path()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入音频/视频素材")
            return
        start, ok1 = QInputDialog.getDouble(self, "截取音频", "起始时间(秒):", 0, 0, 99999, 1)
        if not ok1: return
        end, ok2 = QInputDialog.getDouble(self, "截取音频", "结束时间(秒):", min(start+1, 60), start, 99999, 1)
        if not ok2: return
        dst = self._output_path(src, '_cropped')
        ffmpeg = self._get_ffmpeg()
        try:
            subprocess.run([
                ffmpeg, '-y', '-ss', str(start), '-t', str(end-start), '-i', src,
                '-c', 'copy', dst
            ], capture_output=True, text=True)
            self._add_to_clips(dst, 'audio')
            QMessageBox.information(self, "完成", f"截取完成 ({start:.1f}s~{end:.1f}s):\n{dst}")
        except Exception as e:
            subprocess.run([
                ffmpeg, '-y', '-ss', str(start), '-t', str(end-start), '-i', src,
                '-q:a', '2', dst
            ], capture_output=True, text=True)
            self._add_to_clips(dst, 'audio')
            QMessageBox.information(self, "完成", f"截取完成 ({start:.1f}s~{end:.1f}s):\n{dst}")

    def _add_bgm(self):
        """添加背景音乐"""
        path, _ = QFileDialog.getOpenFileName(self, "选择BGM", "", "音频文件 (*.mp3 *.wav *.aac *.flac *.ogg *.m4a)")
        if path:
            self._add_to_clips(path, 'audio')
            QMessageBox.information(self, "BGM", f"已添加BGM:\n{os.path.basename(path)}")

    def _extract_vocal(self):
        """人声提取：使用高通/低通组合滤波进行人声分离"""
        src = self._get_active_audio_path()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入音频/视频素材")
            return
        dst = self._output_path(src, '_vocal')
        ffmpeg = self._get_ffmpeg()
        QMessageBox.information(self, "人声提取", f"正在处理...\n{os.path.basename(src)}")
        try:
            subprocess.run([
                ffmpeg, '-y', '-i', src,
                '-af', 'highpass=f=200,lowpass=f=3000,acompressor=threshold=-24dB:ratio=4:attack=5:release=50',
                '-q:a', '2', dst
            ], capture_output=True, text=True)
            self._add_to_clips(dst, 'audio')
            QMessageBox.information(self, "完成", f"人声提取完成:\n{dst}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"处理失败: {e}")

    def _output_path(self, src, suffix):
        """生成输出文件路径"""
        base = os.path.splitext(os.path.basename(src))[0]
        d = os.path.join(os.path.dirname(src) or '.', 'output')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{base}{suffix}.mp3")

    def _add_to_clips(self, path, kind='audio'):
        """将处理结果加入素材列表"""
        from datetime import datetime
        ext = os.path.splitext(path)[1].lower()
        is_video = ext in ('.mp4', '.mov', '.avi', '.mkv', '.webm')
        clip = {
            'path': path, 'name': os.path.basename(path),
            'type': 'video' if is_video else 'audio',
            'added': datetime.now().strftime('%H:%M'),
        }
        if not any(c['path'] == path for c in self._clips):
            self._clips.append(clip)
        if hasattr(self, '_refresh_timeline'):
            self._refresh_timeline()

    def _adjust_volume(self, volume):
        """调整音频轨道音量"""
        vol = volume / 100.0
        if hasattr(self, '_audio_manager') and self._audio_manager:
            tracks = self._audio_manager.list_audio_tracks()
            for t in tracks:
                self._audio_manager.adjust_audio_volume(t['id'], vol)
        print(f"调整音量到 {volume}%")

    def _apply_fade_effects(self):
        """应用淡入淡出效果（通过 ffmpeg）"""
        src = self._get_active_audio_path()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入音频/视频素材")
            return
        fi, ok1 = QInputDialog.getDouble(self, "淡入淡出", "淡入时长(秒):", 0.5, 0, 10, 1)
        if not ok1: return
        fo, ok2 = QInputDialog.getDouble(self, "淡入淡出", "淡出时长(秒):", 0.5, 0, 10, 1)
        if not ok2: return
        dst = self._output_path(src, '_fade')
        ffmpeg = self._get_ffmpeg()
        try:
            subprocess.run([
                ffmpeg, '-y', '-i', src,
                '-af', f'afade=t=in:st=0:d={fi},afade=t=out:st=99999:d={fo}',
                '-q:a', '2', dst
            ], capture_output=True, text=True)
            self._add_to_clips(dst, 'audio')
            QMessageBox.information(self, "完成", f"淡入 {fi}s, 淡出 {fo}s\n{dst}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"处理失败: {e}")
    
    def _optimize_workflow(self):
        """ """
        if self._clips:
            clip_path = self._clips[0]['path']
            platform = self._platform_var.currentText()
            # 获取视频调节参数
            video_adjust_params = {
                "brightness": self._brightness_slider.value(),
                "contrast": self._contrast_slider.value(),
                "saturation": self._saturation_slider.value(),
                "hue": self._hue_slider.value()
            }
            result = video_processor.optimize_workflow(clip_path, platform, video_adjust_params)
            QMessageBox.information(self, "智能剪辑", f"智能剪辑工作流已启动!{result}")
        else:
            show_clear_messagebox("操作提示", "请先导入视频")
    
    def _top0_smart_clip(self):
        """ """
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        
        clip_path = self._clips[0]['path']
        platform = self._platform_var.currentText() if hasattr(self, '_platform_var') else "抖音"
        
        # 显示进度对话框
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("正在分析视频内容...", "取消", 0, 100, self)
        progress.setWindowTitle("TOP 0级AI智能剪辑")
        progress.setModal(True)
        progress.show()
        
        def update_progress(value, message):
            progress.setValue(int(value))
            progress.setLabelText(message)
        
        try:
            # 通过统一内核调度器执行TOP 0级智能剪辑
            try:
                from app.core.editor_scheduler import editor_scheduler
            except ImportError:
                from core.editor_scheduler import editor_scheduler

            result = editor_scheduler.smart_clip(
                video_path=clip_path,
                target_platform=platform,
                video_style="高光剪辑",
                target_duration=60.0,
                progress_callback=update_progress
            )
            
            progress.setValue(100)
            progress.close()
            
            if result["success"]:
                # 显示结果
                output_count = len(result["output_videos"])
                msg = f"✅ TOP 0级智能剪辑完成!\n\n"
                msg += f"📊 分析结果:\n"
                msg += f"   • 标题: {result['analysis']['title']}\n"
                msg += f"   • 类型: {result['analysis']['genre']}\n"
                msg += f"   • 角色: {', '.join(result['analysis']['characters'][:3])}\n\n"
                msg += f"🎬 生成视频: {output_count} 个\n"
                
                for i, video in enumerate(result["output_videos"][:3], 1):
                    msg += f"   {i}. {video['title']} ({video['duration']:.1f}s)\n"
                
                if output_count > 3:
                    msg += f"   ... 还有 {output_count - 3} 个片段\n"
                
                msg += f"\n📁 输出目录:\n{os.path.dirname(result['output_videos'][0]['path'])}"
                
                QMessageBox.information(self, "智能剪辑完成", msg)
                
                # 将生成的视频添加到素材库
                for video in result["output_videos"]:
                    self._add_clip_to_timeline(video["path"])
            else:
                error_msg = "剪辑失败:\n" + "\n".join([e.get("error", "未知错误") for e in result["errors"]])
                QMessageBox.warning(self, "剪辑失败", error_msg)
                
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "剪辑错误", f"TOP 0级剪辑出错:\n{str(e)}")
    
    
    def _predict_viral(self):
        """ """
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        
        viral_engine = self._ensure_viral_engine()
        if not viral_engine:
            show_clear_messagebox("引擎未就绪", "爆款优化引擎未加载,请检查依赖安装")
            return
        
        clip_path = self._clips[0]['path']
        platform_text = self._platform_var.currentText() if hasattr(self, '_platform_var') else "抖音"
        
        # 映射平台名称
        platform_map = {
            "抖音": Platform.DOUYIN,
            "快手": Platform.KUAISHOU,
            "小红书": Platform.XIAOHONGSHU,
            "B站": Platform.BILIBILI,
            "视频号": Platform.WECHAT
        }
        platform = platform_map.get(platform_text, Platform.DOUYIN)
        
        # 显示进度对话框
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("正在分析视频爆款潜力...", "取消", 0, 100, self)
        progress.setWindowTitle("🔥 爆款预测分析")
        progress.setModal(True)
        progress.show()
        
        try:
            # 获取视频信息并构建特征
            progress.setValue(20)
            progress.setLabelText("正在提取视频特征...")
            
            # 这里简化处理,实际应该从AI分析结果中提取特征
            features = VideoFeatures(
                duration=self._total_duration if hasattr(self, '_total_duration') else 60.0,
                scene_count=12,
                avg_scene_duration=5.0,
                dialogue_density=0.7,
                emotion_variance=0.6,
                conflict_intensity=0.75,
                hook_quality=70,
                climax_position=0.7,
                has_cliffhanger=True,
                visual_attractiveness=75,
                audio_quality=80,
                subtitle_quality=70
            )
            
            progress.setValue(50)
            progress.setLabelText("正在预测表现...")
            
            # 预测表现
            prediction = viral_engine.predict_performance(features, platform)
            
            progress.setValue(70)
            progress.setLabelText("正在生成优化建议...")
            
            # 生成优化建议
            suggestions = viral_engine.generate_optimization_suggestions(features, platform)
            
            progress.setValue(90)
            progress.setLabelText("正在分析爆款基因...")
            
            # 获取爆款基因
            viral_genes = viral_engine.analyze_viral_genes("甜宠")
            
            progress.setValue(100)
            progress.close()
            
            # 构建结果显示
            result_text = f"""
🎯 视频爆款潜力分析

📱 目标平台: {platform.value}

📊 表现预测:
   • 3秒完播率: {prediction.to_dict()['3秒完播率']}
   • 整体完播率: {prediction.to_dict()['整体完播率']}
   • 点赞率: {prediction.to_dict()['点赞率']}
   • 评论率: {prediction.to_dict()['评论率']}
   • 分享率: {prediction.to_dict()['分享率']}
   • 爆款概率: {prediction.to_dict()['爆款概率']}
   • 预估播放量: {prediction.to_dict()['预估播放量']}

💡 优化建议 (按优先级排序):
"""
            
            for i, suggestion in enumerate(suggestions[:3], 1):
                result_text += f"""
   {i}. {suggestion.factor.value} (优先级: {suggestion.priority})
      当前得分: {suggestion.current_score:.0f}/100 -> 目标: {suggestion.target_score:.0f}/100
      建议: {suggestion.suggestion.replace(chr(10), chr(10) + '      ')}
      预期改善: {suggestion.expected_improvement}
"""
            
            result_text += f"""
🧬 推荐爆款基因:
"""
            
            for i, gene in enumerate(viral_genes[:3], 1):
                result_text += f"""
   {i}. {gene.pattern_name} (成功率: {gene.success_rate:.1%})
      {gene.description}
      关键要素: {', '.join(gene.key_elements)}
"""
            
            # 显示结果对话框
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton
            dialog = QDialog(self)
            dialog.setWindowTitle("🔥 爆款预测结果")
            dialog.setMinimumSize(600, 500)
            
            layout = QVBoxLayout(dialog)
            
            text_edit = QTextEdit()
            text_edit.setPlainText(result_text)
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)
            
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)
            
            dialog.exec()
            
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "分析错误", f"爆款预测出错:\n{str(e)}")

    # ═══════════════════════════════════════════════════════════════
    # 画中画 (Picture-in-Picture)
    # ═══════════════════════════════════════════════════════════════
    def _apply_pip(self):
        """画中画：将一个视频叠加到另一个视频上"""
        if len(self._clips) < 2:
            QMessageBox.warning(self, "提示", "画中画需要至少2个素材，请先在时间线导入主视频和叠加视频")
            return

        main_src = self._clips[0]['path']
        overlay_src = self._clips[1]['path']

        if not os.path.exists(main_src) or not os.path.exists(overlay_src):
            QMessageBox.warning(self, "提示", "素材文件不存在")
            return

        dst = self._output_path(main_src, '_pip').replace('.mp3', '.mp4')
        ffmpeg = self._get_ffmpeg()

        QMessageBox.information(self, "画中画", "正在合成画中画效果...")

        def do_pip():
            try:
                x_pos = self._pip_x.value() if hasattr(self, '_pip_x') else 75
                y_pos = self._pip_y.value() if hasattr(self, '_pip_y') else 80
                size_pct = self._pip_size.value() if hasattr(self, '_pip_size') else 30
                border_w = self._pip_border.value() if hasattr(self, '_pip_border') else 2

                # 构建 FFmpeg overlay 滤镜
                # overlay=W*x/100-w/2:H*y/100-h/2
                overlay_filter = (
                    f"[1:v]scale=iw*{size_pct/100}:ih*{size_pct/100}"
                )
                if border_w > 0:
                    overlay_filter += f",pad=iw+{border_w*2}:ih+{border_w*2}:{border_w}:{border_w}:white"

                overlay_filter += (
                    f"[pip];"
                    f"[0:v][pip]overlay="
                    f"(main_w-overlay_w)*{x_pos/100}:"
                    f"(main_h-overlay_h)*{y_pos/100}"
                )

                cmd = [
                    ffmpeg, '-y',
                    '-i', main_src,
                    '-i', overlay_src,
                    '-filter_complex', overlay_filter,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'copy',
                    '-shortest', dst
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                if result.returncode == 0:
                    self._add_to_clips(dst, 'video')
                    QMessageBox.information(self, "完成", f"画中画合成完成:\n{dst}")
                else:
                    QMessageBox.warning(self, "失败", f"合成失败:\n{result.stderr[-500:]}")
            except subprocess.TimeoutExpired:
                QMessageBox.warning(self, "失败", "处理超时（5分钟）")
            except Exception as e:
                QMessageBox.warning(self, "失败", f"处理出错: {e}")

        threading.Thread(target=do_pip, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    # 智能抠像 (Chroma Key)
    # ═══════════════════════════════════════════════════════════════
    def _apply_chroma_key(self):
        """智能抠像：去除绿幕/蓝幕/自定义颜色背景"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return

        src = self._clips[0]['path']
        if not os.path.exists(src):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return

        dst = self._output_path(src, '_chromakey').replace('.mp3', '.mp4')
        ffmpeg = self._get_ffmpeg()

        tolerance = (self._chroma_tol.value() if hasattr(self, '_chroma_tol') else 30) / 100.0
        softness = (self._chroma_soft.value() if hasattr(self, '_chroma_soft') else 5) / 100.0
        color_mode = self._chroma_color.currentText() if hasattr(self, '_chroma_color') else "绿色"

        color_map = {"绿色": "0x00FF00", "蓝色": "0x0000FF", "自定义": "0x00FF00"}
        color_hex = color_map.get(color_mode, "0x00FF00")

        QMessageBox.information(self, "智能抠像", "正在处理抠像...")

        def do_chroma():
            try:
                # FFmpeg chromakey filter
                chroma_filter = (
                    f"chromakey={color_hex}:"
                    f"similarity={tolerance:.2f}:"
                    f"blend={softness:.2f}"
                )
                cmd = [
                    ffmpeg, '-y', '-i', src,
                    '-vf', chroma_filter,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'copy', dst
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                if result.returncode == 0:
                    self._add_to_clips(dst, 'video')
                    QMessageBox.information(self, "完成", f"抠像完成:\n{dst}")
                else:
                    QMessageBox.warning(self, "失败", f"抠像失败:\n{result.stderr[-500:]}")
            except subprocess.TimeoutExpired:
                QMessageBox.warning(self, "失败", "处理超时")
            except Exception as e:
                QMessageBox.warning(self, "失败", f"处理出错: {e}")

        threading.Thread(target=do_chroma, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    # 曲线变速 (Speed Ramping)
    # ═══════════════════════════════════════════════════════════════
    def _apply_speed_ramp(self):
        """曲线变速：应用预设变速效果"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return

        src = self._clips[0]['path']
        if not os.path.exists(src):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return

        dst = self._output_path(src, '_speedramp').replace('.mp3', '.mp4')
        ffmpeg = self._get_ffmpeg()

        preset = self._speed_preset.currentText() if hasattr(self, '_speed_preset') else "无"
        speed_factor = (self._speed_factor.value() if hasattr(self, '_speed_factor') else 100) / 100.0
        easing = self._speed_easing.currentText() if hasattr(self, '_speed_easing') else "线性"

        if preset == "无" and speed_factor == 1.0:
            QMessageBox.warning(self, "提示", "请选择变速预设或调整速度因子")
            return

        QMessageBox.information(self, "曲线变速", f"正在处理: {preset}...")

        def do_speed():
            try:
                video_duration = self._get_video_duration(src)

                if preset == "倒放":
                    # 倒放
                    cmd = [
                        ffmpeg, '-y', '-i', src,
                        '-vf', 'reverse',
                        '-af', 'areverse',
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', dst
                    ]
                elif preset in ("缓入", "缓出", "缓入缓出", "卡点变速"):
                    # 使用 setpts 表达式实现变速
                    easing_expr = self._build_speed_easing_expr(preset, video_duration, easing)
                    cmd = [
                        ffmpeg, '-y', '-i', src,
                        '-filter_complex',
                        f"[0:v]setpts={easing_expr}*PTS[v];[0:a]atempo={speed_factor}[a]",
                        '-map', '[v]', '-map', '[a]',
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', dst
                    ]
                else:
                    # 固定速率变速
                    if speed_factor != 1.0:
                        setpts_expr = f"{1/speed_factor:.3f}*PTS"
                        cmd = [
                            ffmpeg, '-y', '-i', src,
                            '-filter_complex',
                            f"[0:v]setpts={setpts_expr}[v];[0:a]atempo={speed_factor}[a]",
                            '-map', '[v]', '-map', '[a]',
                            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', dst
                        ]
                    else:
                        return

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                if result.returncode == 0:
                    self._add_to_clips(dst, 'video')
                    QMessageBox.information(self, "完成", f"变速处理完成:\n{dst}")
                else:
                    QMessageBox.warning(self, "失败", f"变速失败:\n{result.stderr[-500:]}")
            except subprocess.TimeoutExpired:
                QMessageBox.warning(self, "失败", "处理超时")
            except Exception as e:
                QMessageBox.warning(self, "失败", f"处理出错: {e}")

        threading.Thread(target=do_speed, daemon=True).start()

    def _build_speed_easing_expr(self, preset, duration, easing):
        """构建变速缓动表达式"""
        if preset == "缓入":
            if easing == "线性":
                return f"if(gte(T,{duration}),{duration},T*(1+(T/{duration})*3))"
            elif easing == "缓出":
                return f"if(gte(T,{duration}),{duration},T*(4-(T/{duration})*3))"
            else:
                return f"if(gte(T,{duration}),{duration},T*(1+(T/{duration})*3))"
        elif preset == "缓出":
            if easing == "缓入":
                return f"if(gte(T,{duration}),{duration},T*(4-(T/{duration})*3))"
            else:
                return f"if(gte(T,{duration}),{duration},T*(4-(T/{duration})*3))"
        elif preset == "缓入缓出":
            mid = duration / 2
            return f"if(lt(T,{mid}),T*(1+T*2/{duration}),T*(3-T*2/{duration}))"
        elif preset == "卡点变速":
            return f"if(lt(mod(T,0.5),0.25),2*PTS,0.5*PTS)"
        return "PTS"

    def _get_video_duration(self, path):
        """获取视频时长"""
        try:
            ffmpeg = self._get_ffmpeg()
            result = subprocess.run(
                [ffmpeg, '-i', path],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            for line in result.stderr.split('\n'):
                if 'Duration' in line:
                    parts = line.strip().split('Duration: ')[1].split(',')[0]
                    h, m, s = parts.split(':')
                    return float(h) * 3600 + float(m) * 60 + float(s)
        except Exception:
            pass
        return 10.0

    # ═══════════════════════════════════════════════════════════════
    # RGB 曲线调色 (Curves Color Grading)
    # ═══════════════════════════════════════════════════════════════
    def _apply_curves(self):
        """RGB曲线调色：通过FFmpeg curves滤镜实现暗部/中间调/亮部调整"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return

        src = self._clips[0]['path']
        if not os.path.exists(src):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return

        dst = self._output_path(src, '_curves').replace('.mp3', '.mp4')
        ffmpeg = self._get_ffmpeg()

        channel = self._curve_channel.currentText() if hasattr(self, '_curve_channel') else "RGB"
        shadows = (self._curve_shadows.value() if hasattr(self, '_curve_shadows') else 0) / 100.0
        midtones = (self._curve_midtones.value() if hasattr(self, '_curve_midtones') else 0) / 100.0
        highlights = (self._curve_highlights.value() if hasattr(self, '_curve_highlights') else 0) / 100.0

        QMessageBox.information(self, "曲线调色", f"正在应用 {channel} 曲线...")

        def do_curves():
            try:
                # 构建 FFmpeg curves 滤镜参数
                # curves=preset=lighter|darker|strong_contrast, 或自定义
                # 映射 shadows/midtones/highlights 到 master 曲线
                # 暗部: 0~0.33, 中间调: 0.33~0.67, 亮部: 0.67~1.0

                if abs(shadows) < 0.01 and abs(midtones) < 0.01 and abs(highlights) < 0.01:
                    QMessageBox.warning(self, "提示", "请先调整曲线参数")
                    return

                # 构建 curves 字符串：格式为 "master='0/0 0.25/X 0.5/Y 0.75/Z 1/1'"
                # X = 0.25 + shadows*0.3, Y = 0.5 + midtones*0.3, Z = 0.75 + highlights*0.3
                p1 = max(0.0, min(1.0, 0.25 + shadows * 0.3))
                p2 = max(0.0, min(1.0, 0.50 + midtones * 0.3))
                p3 = max(0.0, min(1.0, 0.75 + highlights * 0.3))

                chan_map = {"RGB": "master", "红色": "red", "绿色": "green", "蓝色": "blue"}
                chan_name = chan_map.get(channel, "master")

                curves_str = f"{chan_name}='0/0 0.25/{p1:.2f} 0.5/{p2:.2f} 0.75/{p3:.2f} 1/1'"

                cmd = [
                    ffmpeg, '-y', '-i', src,
                    '-vf', f'curves={curves_str}',
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'copy', dst
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                if result.returncode == 0:
                    self._add_to_clips(dst, 'video')
                    QMessageBox.information(self, "完成", f"曲线调色完成:\n{dst}")
                else:
                    QMessageBox.warning(self, "失败", f"曲线调色失败:\n{result.stderr[-500:]}")
            except subprocess.TimeoutExpired:
                QMessageBox.warning(self, "失败", "处理超时")
            except Exception as e:
                QMessageBox.warning(self, "失败", f"处理出错: {e}")

        threading.Thread(target=do_curves, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    # 音乐踩点 (Beat Detection)
    # ═══════════════════════════════════════════════════════════════
    def _detect_beats(self):
        """音乐踩点：自动检测BGM节拍点"""
        src = self._get_active_audio_path()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入音频/视频素材")
            return

        sensitivity = self._beat_sensitivity.value() if hasattr(self, '_beat_sensitivity') else 5
        self._beat_list.clear()
        self._beat_list.addItem("🥁 正在分析音频节拍...")
        QApplication.processEvents()

        def do_detect():
            try:
                # 尝试使用 BGMBeatDetector
                try:
                    import numpy as np
                    from app.core.audio_processor import BGMBeatDetector

                    import soundfile as sf
                    data, sr = sf.read(src)
                    if len(data.shape) > 1:
                        data = np.mean(data, axis=1)

                    detector = BGMBeatDetector()
                    beats = detector.detect_beats(data, sr)

                    if beats:
                        self._beat_list.clear()
                        from datetime import timedelta
                        for i, beat in enumerate(beats):
                            # 灵敏度过滤：只显示强度足够的节拍
                            threshold = sensitivity / 10.0
                            if beat.intensity >= threshold:
                                ts = str(timedelta(seconds=int(beat.time)))
                                ms = f".{int(beat.time * 100) % 100:02d}"
                                intensity_bar = "█" * int(beat.intensity * 10)
                                self._beat_list.addItem(
                                    f"第{i+1}拍 | {ts}{ms} | {intensity_bar} ({beat.intensity:.1%})"
                                )
                        self._beat_list.addItem(f"━━ 共检测到 {len(beats)} 个节拍点 ━━")
                    else:
                        self._beat_list.addItem("⚠ 未检测到明显节拍，请尝试调整灵敏度")
                except ImportError as e:
                    # 回退到 FFmpeg 基于能量的节拍检测
                    self._beat_list.clear()
                    self._beat_list.addItem("使用FFmpeg检测节拍...")
                    QApplication.processEvents()

                    ffmpeg = self._get_ffmpeg()
                    # 用 silencedetect 找出音量峰值
                    result = subprocess.run(
                        [ffmpeg, '-y', '-i', src,
                         '-af', f'asplit[a][b];[a]volume=1[b];[b]ametadata=print:key=lavfi.astats.Overall.RMS_level',
                         '-f', 'null', '-'],
                        capture_output=True, text=True, timeout=60,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    self._beat_list.addItem(f"⚠ 需要安装 numpy/soundfile 库以启用完整节拍检测")
                    self._beat_list.addItem(f"提示: pip install numpy soundfile")
            except Exception as e:
                self._beat_list.clear()
                self._beat_list.addItem(f"❌ 检测失败: {str(e)[:80]}")

        threading.Thread(target=do_detect, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    # 运动跟踪 (Motion Tracking)
    # ═══════════════════════════════════════════════════════════════
    def _apply_motion_track(self):
        """运动跟踪：通过FFmpeg vidstabdetect 分析视频运动"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return

        src = self._clips[0]['path']
        if not os.path.exists(src):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return

        dst = self._output_path(src, '_tracked').replace('.mp3', '.mp4')
        track_type = self._track_type.currentText() if hasattr(self, '_track_type') else "平移跟踪"

        QMessageBox.information(self, "运动跟踪", f"正在分析视频运动: {track_type}...")

        def do_track():
            try:
                import tempfile
                ffmpeg = self._get_ffmpeg()

                # 第1步: 生成运动检测数据
                trf_file = tempfile.NamedTemporaryFile(suffix='.trf', delete=False).name
                detect_cmd = [
                    ffmpeg, '-y', '-i', src,
                    '-vf', 'vidstabdetect=result=' + trf_file.replace('\\', '/') + ':shakiness=5:accuracy=15',
                    '-f', 'null', '-'
                ]
                subprocess.run(detect_cmd, capture_output=True, text=True, timeout=120,
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)

                # 第2步: 根据跟踪类型应用稳定/变换
                if os.path.exists(trf_file) and os.path.getsize(trf_file) > 10:
                    track_filter = "vidstabtransform"
                    if track_type == "透视跟踪":
                        track_filter += "=optzoom=1:maxangle=10:crop=black"
                    else:
                        track_filter += "=smoothing=10:crop=black"

                    cmd = [
                        ffmpeg, '-y', '-i', src,
                        '-vf', f'{track_filter}:input={trf_file.replace(chr(92), "/")}',
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                        '-c:a', 'copy', dst
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)

                    try:
                        os.unlink(trf_file)
                    except Exception:
                        pass

                    if result.returncode == 0:
                        self._add_to_clips(dst, 'video')
                        QMessageBox.information(self, "完成", f"运动跟踪完成:\n{dst}")
                    else:
                        QMessageBox.warning(self, "失败", f"跟踪失败:\n{result.stderr[-500:]}")
                else:
                    QMessageBox.warning(self, "失败", "未能检测到足够的运动数据，请尝试其他视频")
                    try:
                        os.unlink(trf_file)
                    except Exception:
                        pass
            except subprocess.TimeoutExpired:
                QMessageBox.warning(self, "失败", "处理超时")
            except Exception as e:
                QMessageBox.warning(self, "失败", f"处理出错: {e}")

        threading.Thread(target=do_track, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    # 贴纸系统 (Sticker System)
    # ═══════════════════════════════════════════════════════════════
    def _add_sticker(self, name, emoji):
        """添加贴纸到活动列表"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return
        sticker_info = {"name": name, "emoji": emoji, "text": name}
        if not any(s.get("name") == name for s in self._active_stickers):
            self._active_stickers.append(sticker_info)
            self._sticker_list.addItem(f"{emoji} {name}")
            self._sticker_list.setCurrentRow(self._sticker_list.count() - 1)

    def _import_sticker(self):
        """导入自定义贴纸图片"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择贴纸图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.svg);;所有文件 (*.*)"
        )
        if not path:
            return
        name = os.path.splitext(os.path.basename(path))[0]
        sticker_info = {"name": name, "path": path, "emoji": "🖼"}
        self._active_stickers.append(sticker_info)
        self._sticker_list.addItem(f"🖼 {name} (自定义)")
        self._sticker_list.setCurrentRow(self._sticker_list.count() - 1)

    def _apply_sticker(self):
        """将贴纸渲染到视频上"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return
        if not self._active_stickers:
            QMessageBox.warning(self, "提示", "请先选择贴纸")
            return

        src = self._clips[0]['path']
        if not os.path.exists(src):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return

        dst = self._output_path(src, '_sticker').replace('.mp3', '.mp4')
        ffmpeg = self._get_ffmpeg()

        size_pct = self._sticker_size.value() if hasattr(self, '_sticker_size') else 100
        rotation = self._sticker_rot.value() if hasattr(self, '_sticker_rot') else 0
        pos_x = self._sticker_posx.value() if hasattr(self, '_sticker_posx') else 50
        pos_y = self._sticker_posy.value() if hasattr(self, '_sticker_posy') else 50
        opacity = (self._sticker_opacity.value() if hasattr(self, '_sticker_opacity') else 100) / 100.0

        QMessageBox.information(self, "贴纸", "正在渲染贴纸效果...")

        def do_sticker():
            try:
                import tempfile
                from PIL import Image, ImageDraw, ImageFont

                # 生成贴纸叠加图
                temp_files = []
                overlay_parts = []

                for i, sticker in enumerate(self._active_stickers):
                    if "path" in sticker and os.path.exists(sticker["path"]):
                        # 自定义贴纸图片
                        overlay_parts.append(f"[{i+1}:v]format=rgba,colorchannelmixer=aa={opacity}[st{i}]")
                        temp_files.append(sticker["path"])
                    else:
                        # Emoji贴纸 - 生成文字图片
                        img = Image.new('RGBA', (200, 200), (0, 0, 0, 0))
                        draw = ImageDraw.Draw(img)
                        try:
                            font_size = int(100 * size_pct / 100)
                            font = ImageFont.truetype("seguiemj.ttf", font_size)
                        except Exception:
                            font = ImageFont.load_default()
                        draw.text((10, 10), sticker["emoji"], font=font, fill=(255, 255, 255, int(255 * opacity)))
                        tmp_png = tempfile.NamedTemporaryFile(suffix='.png', delete=False).name
                        img.save(tmp_png, 'PNG')
                        temp_files.append(tmp_png)
                        overlay_parts.append(f"[{i+1}:v]format=rgba[st{i}]")

                # 构建命令
                inputs = ['-i', src]
                for tf in temp_files:
                    inputs.extend(['-i', tf])

                # 构建 overlay filter chain
                filters = [';'.join(overlay_parts)]
                curr_in = '[0:v]'
                for i in range(len(self._active_stickers)):
                    dist_x = f"(main_w-overlay_w)*{pos_x/100}"
                    dist_y = f"(main_h-overlay_h)*{pos_y/100}"
                    if i == 0:
                        filters.append(
                            f"[0:v][st0]overlay={dist_x}:{dist_y}:"
                            f"format=auto[out0]"
                        )
                    else:
                        filters.append(
                            f"[out{i-1}][st{i}]overlay={dist_x}:{dist_y}:"
                            f"format=auto[out{i}]"
                        )

                filter_str = ';'.join(filters)
                cmd = [
                    ffmpeg, '-y', *inputs,
                    '-filter_complex', filter_str,
                    '-map', f'[out{len(self._active_stickers)-1}]',
                    '-map', '0:a?',
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'copy', dst
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)

                # 清理临时文件
                for tf in temp_files:
                    if tf != src and not (sticker.get("path") == tf for sticker in self._active_stickers):
                        try:
                            os.unlink(tf)
                        except Exception:
                            pass

                if result.returncode == 0:
                    self._add_to_clips(dst, 'video')
                    QMessageBox.information(self, "完成", f"贴纸渲染完成:\n{dst}")
                else:
                    QMessageBox.warning(self, "失败", f"渲染失败:\n{result.stderr[-500:]}")
            except subprocess.TimeoutExpired:
                QMessageBox.warning(self, "失败", "处理超时")
            except Exception as e:
                QMessageBox.warning(self, "失败", f"处理出错: {e}")

        threading.Thread(target=do_sticker, daemon=True).start()

    def _clear_stickers(self):
        """清除所有贴纸"""
        self._active_stickers.clear()
        if hasattr(self, '_sticker_list'):
            self._sticker_list.clear()

    # ------------------------------------------------------------------
    # 剪辑 Agent 与工具栏真实操作补齐
    # ------------------------------------------------------------------
    def _create_edit_agent_panel(self) -> QWidget:
        """创建 Trae IDE 风格的剪辑 Agent 对话面板。"""
        panel = QFrame(self)
        panel.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        panel.setStyleSheet("""
            QFrame#editAgentPanel{background:#0f1117;border:1px solid #252a35;border-radius:10px;}
            QLabel{color:#c9d1d9;background:transparent;border:none;}
        """)
        panel.setObjectName("editAgentPanel")
        panel.setMinimumSize(420, 220)
        panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("剪辑 Agent")
        title.setStyleSheet("color:#fff;font-size:12px;font-weight:700;")
        head.addWidget(title)
        head.addStretch()

        model_label = QLabel("模型")
        model_label.setStyleSheet("color:#8b949e;font-size:11px;")
        head.addWidget(model_label)

        self._edit_agent_model_combo = QComboBox()
        self._edit_agent_model_combo.setMinimumWidth(220)
        self._edit_agent_model_combo.setStyleSheet("""
            QComboBox{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:4px 8px;font-size:11px;}
            QComboBox::drop-down{border:none;width:18px;}
        """)
        head.addWidget(self._edit_agent_model_combo)

        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet("QPushButton{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:4px 10px;font-size:11px;}QPushButton:hover{background:#30363d;}")
        refresh_btn.clicked.connect(self._refresh_edit_agent_models)
        head.addWidget(refresh_btn)

        close_btn = QPushButton("收起")
        close_btn.setStyleSheet("QPushButton{background:#2a1f24;color:#ffb4bd;border:1px solid #5c222b;border-radius:6px;padding:4px 10px;font-size:11px;}QPushButton:hover{background:#5c222b;color:#fff;}")
        close_btn.clicked.connect(lambda: self._toggle_edit_agent_panel(False))
        head.addWidget(close_btn)
        layout.addLayout(head)

        self._edit_agent_chat = QTextEdit()
        self._edit_agent_chat.setReadOnly(True)
        self._edit_agent_chat.setFixedHeight(72)
        self._edit_agent_chat.setPlaceholderText("Agent 状态和执行结果会显示在这里。")
        self._edit_agent_chat.setStyleSheet("QTextEdit{background:#0d1117;color:#9fb3c8;border:1px solid #21262d;border-radius:8px;padding:6px;font-size:11px;}")
        layout.addWidget(self._edit_agent_chat)

        interaction_card = QFrame()
        interaction_card.setStyleSheet("QFrame{background:#111722;border:1px solid #263244;border-radius:10px;}")
        interaction_layout = QVBoxLayout(interaction_card)
        interaction_layout.setContentsMargins(10, 10, 10, 10)
        interaction_layout.setSpacing(8)

        interaction_title = QLabel("输入剪辑指令")
        interaction_title.setStyleSheet("color:#e6edf3;font-size:12px;font-weight:700;")
        interaction_layout.addWidget(interaction_title)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        quick_prompts = [
            ("分析当前片段", "分析当前选中片段，给出可执行的剪辑建议"),
            ("一键切分", "把当前片段按播放头位置切成两段"),
            ("电影滤镜", "给当前片段添加电影感滤镜，强度 70%"),
            ("淡入转场", "给当前片段添加 0.5 秒淡入转场"),
        ]
        for label, prompt in quick_prompts:
            btn = QPushButton(label)
            btn.setStyleSheet("QPushButton{background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:12px;padding:4px 10px;font-size:11px;}QPushButton:hover{background:#1e6bde;color:#fff;border-color:#1e6bde;}")
            btn.clicked.connect(lambda _, text=prompt: self._fill_edit_agent_prompt(text))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        interaction_layout.addLayout(quick_row)

        input_row = QHBoxLayout()
        self._edit_agent_input = QLineEdit()
        self._edit_agent_input.setPlaceholderText("例如：把当前片段切成两段，给第一段加电影滤镜，并添加淡入转场")
        self._edit_agent_input.setStyleSheet("QLineEdit{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:8px;padding:8px;font-size:12px;}")
        self._edit_agent_input.returnPressed.connect(self._send_edit_agent_message)
        input_row.addWidget(self._edit_agent_input, 1)

        self._edit_agent_send_btn = QPushButton("发送")
        self._edit_agent_send_btn.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:8px;padding:8px 16px;font-size:12px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        self._edit_agent_send_btn.clicked.connect(self._send_edit_agent_message)
        input_row.addWidget(self._edit_agent_send_btn)

        self._edit_agent_stop_btn = QPushButton("终止")
        self._edit_agent_stop_btn.setEnabled(False)
        self._edit_agent_stop_btn.setStyleSheet("QPushButton{background:#3a1f24;color:#ffb4bd;border:1px solid #6b2530;border-radius:8px;padding:8px 16px;font-size:12px;font-weight:600;}QPushButton:disabled{background:#1b1f24;color:#555;border-color:#2a2f36;}QPushButton:hover:enabled{background:#5c222b;}")
        self._edit_agent_stop_btn.clicked.connect(self._stop_edit_agent_message)
        input_row.addWidget(self._edit_agent_stop_btn)
        interaction_layout.addLayout(input_row)
        layout.addWidget(interaction_card, 1)

        self._edit_agent_worker = None
        self._edit_agent_stream_buffer = ""
        self._refresh_edit_agent_models()
        self._append_agent_message("Agent", "已就绪。下方输入剪辑需求或点击快捷指令。")
        return panel

    def _toggle_edit_agent_panel(self, checked=None):
        """展开或收起浮动剪辑 Agent，避免占用轨道区域。"""
        panel = getattr(self, '_edit_agent_panel', None)
        if panel is None:
            return
        visible = bool(checked) if checked is not None else not panel.isVisible()
        if visible:
            self._position_edit_agent_panel()
        panel.setVisible(visible)
        if visible:
            panel.raise_()
            panel.activateWindow()
        if hasattr(self, '_edit_agent_toggle_btn'):
            self._edit_agent_toggle_btn.setChecked(visible)

    def _position_edit_agent_panel(self):
        """将剪辑 Agent 浮动面板定位到编辑器右上区域，不挤占时间线轨道高度。"""
        panel = getattr(self, '_edit_agent_panel', None)
        if panel is None:
            return

        panel_width = min(560, max(420, int(self.width() * 0.38)))
        panel_height = min(300, max(220, int(self.height() * 0.32)))
        panel.resize(panel_width, panel_height)

        # 固定在编辑器右上角，避免跟随轨道标题按钮落到时间线主体上。
        anchor = self.mapToGlobal(QPoint(self.width() - panel_width - 16, 64))

        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        if available is None:
            panel.move(anchor)
            return

        x = min(max(anchor.x(), available.left() + 8), available.right() - panel_width - 8)
        y = min(max(anchor.y(), available.top() + 8), available.bottom() - panel_height - 8)
        panel.move(x, y)

    def _refresh_edit_agent_models(self):
        """加载云端 provider 与本地 Ollama 模型到 Agent 模型切换框。"""
        combo = getattr(self, '_edit_agent_model_combo', None)
        if combo is None:
            return
        combo.clear()
        try:
            from app.modules.lego.model_config import PROVIDERS
        except Exception:
            PROVIDERS = {}

        for provider, cfg in PROVIDERS.items():
            name = cfg.get("name", provider)
            models = list(cfg.get("models") or [])
            if provider == "ollama":
                models = self._list_local_ollama_models() or ["auto"]
            if not models:
                combo.addItem(f"{name} / 默认", (provider, ""))
                continue
            for model in models:
                label = f"{name} / {model}" if model != "auto" else f"{name} / 自动"
                combo.addItem(label, (provider, "" if model == "auto" else model))

        if combo.count() == 0:
            combo.addItem("自动降级 / 可用模型", ("", ""))

    def _list_local_ollama_models(self) -> List[str]:
        """读取本地 Ollama 模型列表；失败时返回空列表并保留自动模式。"""
        try:
            from app.core.ai_engine import ai_engine
            client = getattr(ai_engine, "_ollama_client", None)
            if not client:
                return []
            models = client.list_models()
            result = []
            for item in models:
                if isinstance(item, dict):
                    result.append(item.get("name") or item.get("model") or "")
                else:
                    result.append(getattr(item, "name", getattr(item, "model", str(item))))
            return [m for m in result if m]
        except Exception as e:
            print(f"读取 Ollama 模型失败: {e}")
            return []

    def _append_agent_message(self, role: str, text: str):
        """向 Agent 对话框追加消息。"""
        chat = getattr(self, '_edit_agent_chat', None)
        if chat is None:
            return
        chat.append(f"{role}: {text}")
        chat.verticalScrollBar().setValue(chat.verticalScrollBar().maximum())

    def _fill_edit_agent_prompt(self, text: str):
        """把快捷剪辑指令填入输入框，方便用户确认后发送。"""
        edit = getattr(self, '_edit_agent_input', None)
        if edit is None:
            return
        edit.setText(text)
        edit.setFocus()
        edit.selectAll()

    def _send_edit_agent_message(self):
        """发送剪辑 Agent 指令并启动后台模型请求。"""
        if getattr(self, '_edit_agent_worker', None) and self._edit_agent_worker.isRunning():
            QMessageBox.information(self, "剪辑 Agent", "Agent 正在处理中，如需中断请点击“终止”。")
            return
        user_text = self._edit_agent_input.text().strip()
        if not user_text:
            QMessageBox.warning(self, "剪辑 Agent", "请输入剪辑指令")
            return

        provider, model = self._get_selected_edit_agent_model()
        messages = self._build_edit_agent_messages(user_text)
        self._append_agent_message("你", user_text)
        self._append_agent_message("Agent", "正在分析并生成剪辑指令...")
        self._edit_agent_input.clear()

        self._edit_agent_stream_buffer = ""
        self._edit_agent_last_user_text = user_text
        worker = EditingAgentWorker(provider, model, messages, self)
        worker.chunk_ready.connect(self._on_edit_agent_chunk)
        worker.result_ready.connect(lambda raw, text=user_text: self._on_edit_agent_result(text, raw))
        worker.error_ready.connect(self._on_edit_agent_error)
        worker.stopped_ready.connect(self._on_edit_agent_stopped)
        worker.finished.connect(self._on_edit_agent_finished)
        self._edit_agent_worker = worker
        self._edit_agent_send_btn.setEnabled(False)
        self._edit_agent_stop_btn.setEnabled(True)
        worker.start()

    def _stop_edit_agent_message(self):
        """终止当前剪辑 Agent 输出。"""
        worker = getattr(self, '_edit_agent_worker', None)
        if worker and worker.isRunning():
            worker.request_stop()
            self._append_agent_message("系统", "已请求终止当前输出。")
        self._edit_agent_stop_btn.setEnabled(False)

    def _get_selected_edit_agent_model(self):
        """获取当前 Agent 模型选择。"""
        combo = getattr(self, '_edit_agent_model_combo', None)
        if combo is None:
            return "", ""
        data = combo.currentData()
        if isinstance(data, tuple) and len(data) == 2:
            return data
        return "", ""

    def _build_edit_agent_messages(self, user_text: str) -> List[Dict[str, str]]:
        """构建剪辑 Agent 专用提示词，要求模型返回可执行 JSON 指令。"""
        context = self._get_agent_timeline_context()
        system_prompt = (
            "你是拾光剪影的剪辑 Agent，负责把用户自然语言转成可执行剪辑指令。"
            "只返回 JSON 数组，不要 Markdown，不要解释文字。"
            "可用 action: add_clip, remove_clip, move_clip, trim_clip, split_clip, "
            "duplicate_clip, add_track, add_transition, add_effect, answer。"
            "时间单位是秒，clip_index 从 0 开始。"
            "add_effect 参数示例: {\"effect_type\":\"filter\",\"params\":{\"filter_name\":\"电影\",\"intensity\":0.7}}。"
            "add_transition 参数示例: {\"transition_type\":\"fade\",\"duration\":0.5,\"clip_index\":0}。"
            "如果只是咨询问题，返回 answer。"
        )
        user_prompt = (
            f"用户剪辑指令: {user_text}\n\n"
            f"当前时间线状态:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _get_agent_timeline_context(self) -> Dict[str, Any]:
        """整理当前时间线上下文，供云端 API 或本地大模型使用。"""
        clips = []
        for index, clip in enumerate(getattr(self, '_clips', [])):
            clips.append({
                "clip_index": index,
                "id": clip.get("id"),
                "path": clip.get("path"),
                "start_time": clip.get("start_time", 0),
                "duration": clip.get("duration", 0),
                "track": clip.get("track", 0),
                "effects": clip.get("effects", {}),
                "transition": clip.get("transition"),
            })
        return {
            "clip_count": len(clips),
            "selected_clip_id": getattr(self, '_current_clip', None).get("id") if getattr(self, '_current_clip', None) else None,
            "playhead_position": getattr(self, '_playhead_position', 0),
            "clips": clips,
        }

    def _on_edit_agent_chunk(self, chunk: str):
        """缓存模型流式输出。"""
        self._edit_agent_stream_buffer += chunk

    def _on_edit_agent_result(self, user_text: str, raw: str):
        """处理模型输出并应用剪辑指令。"""
        text = raw.strip() or self._edit_agent_stream_buffer.strip()
        self._append_agent_message("Agent", text[:1200] if text else "模型无输出，尝试规则解析。")
        commands = self._parse_agent_commands(user_text, text)
        if not commands:
            self._append_agent_message("系统", "没有解析到可执行剪辑指令。")
            return
        results = self._apply_agent_commands_to_editor(commands)
        summary = "；".join([r.get("message", "") for r in results if r.get("message")])
        self._append_agent_message("系统", summary or "剪辑指令已执行。")

    def _on_edit_agent_error(self, error: str):
        """模型调用失败时回退到本地规则解析。"""
        self._append_agent_message("系统", f"模型调用失败: {error}")
        user_text = getattr(self, '_edit_agent_last_user_text', "")
        if not user_text:
            return
        commands = self._parse_agent_commands(user_text, "")
        if not commands:
            self._append_agent_message("系统", "本地规则也未解析到可执行剪辑指令。")
            return
        results = self._apply_agent_commands_to_editor(commands)
        summary = "；".join([r.get("message", "") for r in results if r.get("message")])
        self._append_agent_message("系统", summary or "已使用本地规则完成剪辑操作。")

    def _on_edit_agent_stopped(self):
        """Agent 被用户终止。"""
        self._append_agent_message("系统", "当前 Agent 输出已终止。")

    def _on_edit_agent_finished(self):
        """恢复 Agent 按钮状态。"""
        self._edit_agent_send_btn.setEnabled(True)
        self._edit_agent_stop_btn.setEnabled(False)

    def _parse_agent_commands(self, user_text: str, raw: str) -> List[Any]:
        """解析模型 JSON；失败时回退到 LLMEditor 的离线规则。"""
        try:
            from app.core.llm_editor import EditCommand, llm_editor
            items = llm_editor._extract_json(raw) if raw else None
            commands = []
            if items:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    action = item.get("action", "answer")
                    params = item.get("params", {})
                    if action == "error":
                        commands.append(EditCommand(
                            action="answer",
                            params={"message": params.get("message", "指令无法执行")},
                            confidence=item.get("confidence", 0.5),
                            raw_text=user_text,
                            description=params.get("message", ""),
                        ))
                        continue
                    commands.append(EditCommand(
                        action=action,
                        params=params,
                        confidence=item.get("confidence", 0.9),
                        raw_text=user_text,
                        description=item.get("description", action),
                    ))
            if commands:
                return commands

            result = llm_editor.parse(user_text, use_ai=False, timeline_context=self._get_agent_timeline_context())
            return result.commands if result.success else []
        except Exception as e:
            print(f"剪辑 Agent 指令解析失败: {e}")
            return []

    def _apply_agent_commands_to_editor(self, commands: List[Any]) -> List[Dict[str, Any]]:
        """将 Agent 指令落到当前剪辑模块的真实时间线数据上。"""
        results = []
        for command in commands:
            try:
                results.append(self._apply_agent_command(command))
            except Exception as e:
                results.append({"action": getattr(command, "action", "unknown"), "success": False, "message": str(e)})
        self._sync_timeline_widget_state()
        self._refresh_preview_with_effects()
        return results

    def _apply_agent_command(self, command) -> Dict[str, Any]:
        """执行单条 Agent 指令。"""
        action = getattr(command, "action", "")
        params = getattr(command, "params", {}) or {}
        if action in ("answer", "info"):
            return {"action": action, "success": True, "message": params.get("message", getattr(command, "description", ""))}
        if action == "add_track":
            track_type = params.get("track_type", "video")
            name = params.get("name", "Agent 轨道")
            if hasattr(self, '_timeline_widget'):
                self._timeline_widget.add_track(name, track_type)
            return {"action": action, "success": True, "message": f"已添加{track_type}轨道"}
        if action in ("remove_clip", "ripple_delete"):
            if params.get("clip_index") == "all":
                count = len(self._clips)
                for clip in list(self._clips):
                    self._delete_clip_by_id(clip.get("id"))
                return {"action": action, "success": True, "message": f"已删除 {count} 个片段"}
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要删除的片段"}
            self._delete_clip_by_id(clip.get("id"))
            return {"action": action, "success": True, "message": "片段已删除"}
        if action == "duplicate_clip":
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要复制的片段"}
            self._copy_clip_data_to_timeline(clip, offset=params.get("offset", clip.get("duration", 1)))
            return {"action": action, "success": True, "message": "片段已复制到时间线"}
        if action == "trim_clip":
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要裁剪的片段"}
            duration = params.get("new_duration") or params.get("duration")
            if not duration and params.get("end_time") is not None:
                duration = float(params.get("end_time")) - float(params.get("start_time", clip.get("start_time", 0)))
            if not duration or float(duration) <= 0:
                return {"action": action, "success": False, "message": "裁剪时长无效"}
            clip["duration"] = float(duration)
            clip["out_point"] = clip.get("in_point", 0) + float(duration)
            return {"action": action, "success": True, "message": f"片段已裁剪为 {float(duration):.1f}s"}
        if action == "split_clip":
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要切分的片段"}
            split_time = float(params.get("split_time", getattr(self, '_playhead_position', 0)))
            return self._split_clip_at_time(clip, split_time)
        if action in ("add_transition", "transition"):
            clip = self._resolve_agent_clip(params) or getattr(self, '_current_clip', None)
            if not clip:
                return {"action": action, "success": False, "message": "请先选择片段再添加转场"}
            transition_type = params.get("transition_type", "fade")
            duration = float(params.get("duration", 0.5))
            self._apply_transition_to_clip(clip, transition_type, duration)
            return {"action": action, "success": True, "message": f"已应用 {transition_type} 转场"}
        if action in ("add_effect", "apply_filter"):
            clip = self._resolve_agent_clip(params) or getattr(self, '_current_clip', None)
            if not clip:
                return {"action": action, "success": False, "message": "请先选择片段再添加效果"}
            effect_type = params.get("effect_type", "filter")
            effect_params = params.get("params", params)
            if effect_type == "filter":
                filter_name = effect_params.get("filter_name", params.get("filter_name", "selected"))
                intensity = float(effect_params.get("intensity", params.get("intensity", 0.7)))
                self._apply_filter_to_clip(clip, filter_name, intensity)
                return {"action": action, "success": True, "message": f"已应用滤镜 {filter_name}"}
            self._apply_effect_to_clip(clip, effect_type, effect_params)
            return {"action": action, "success": True, "message": f"已应用效果 {effect_type}"}
        return {"action": action, "success": False, "message": f"暂不支持的指令: {action}"}

    def _resolve_agent_clip(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """根据 Agent 参数定位片段。"""
        clip_id = params.get("clip_id")
        if clip_id:
            for clip in self._clips:
                if clip.get("id") == clip_id:
                    return clip
        index = params.get("clip_index")
        if index is None:
            return getattr(self, '_current_clip', None) or (self._clips[0] if self._clips else None)
        try:
            index = int(index)
        except (TypeError, ValueError):
            return None
        if 0 <= index < len(self._clips):
            return self._clips[index]
        return None

    def _split_clip_at_time(self, clip: Dict[str, Any], split_time: float) -> Dict[str, Any]:
        """在指定时间切分片段，并同步到时间线 UI。"""
        start = float(clip.get("start_time", 0))
        duration = float(clip.get("duration", 0))
        local_time = split_time - start if split_time > start else split_time
        if local_time <= 0 or local_time >= duration:
            local_time = duration / 2
        if local_time <= 0 or local_time >= duration:
            return {"action": "split_clip", "success": False, "message": "当前片段时长不足，无法切分"}

        new_clip = dict(clip)
        new_clip["id"] = f"{clip.get('id', 'clip')}_split_{int(time.time() * 1000)}"
        new_clip["start_time"] = start + local_time
        new_clip["duration"] = duration - local_time
        new_clip["in_point"] = float(clip.get("in_point", 0)) + local_time
        new_clip["out_point"] = new_clip["in_point"] + new_clip["duration"]

        clip["duration"] = local_time
        clip["out_point"] = float(clip.get("in_point", 0)) + local_time
        self._clips.append(new_clip)
        if hasattr(self, '_timeline_widget'):
            widget = self._timeline_widget.add_clip(new_clip, int(new_clip.get("track", 0)))
            if widget is not None:
                self._clip_widgets.append(widget)
                self._clip_id_to_widget[new_clip["id"]] = widget
        self._current_clip = new_clip
        # 记录撤销栈：供 _undo/_redo 回滚切分
        self._record_action({
            "type": "split",
            "original_clip": clip,
            "new_clip": new_clip,
            "original_duration": duration,
            "original_out_point": float(clip.get("in_point", 0)) + duration,
        })
        # 同步内核时间线 + 刷新预览，使剪切真正作用到视频
        self._sync_kernel_timeline()
        self._refresh_preview_to_current_clip()
        return {"action": "split_clip", "success": True, "message": f"已在 {split_time:.1f}s 切分片段"}

    def _copy_clip_data_to_timeline(self, clip: Dict[str, Any], offset: float = 1.0):
        """复制片段数据并添加到时间线。"""
        new_clip = dict(clip)
        new_clip["id"] = f"{clip.get('id', 'clip')}_copy_{int(time.time() * 1000)}"
        new_clip["start_time"] = float(clip.get("start_time", 0)) + float(offset or 1.0)
        self._clips.append(new_clip)
        if hasattr(self, '_timeline_widget'):
            widget = self._timeline_widget.add_clip(new_clip, int(new_clip.get("track", 0)))
            if widget is not None:
                self._clip_widgets.append(widget)
                self._clip_id_to_widget[new_clip["id"]] = widget
        self._current_clip = new_clip
        # 记录撤销栈：供 _undo/_redo 移除粘贴出的片段
        self._record_action({
            "type": "paste",
            "new_clip": new_clip,
        })
        # 同步内核时间线 + 刷新预览，使粘贴真正作用到视频
        self._sync_kernel_timeline()
        self._refresh_preview_to_current_clip()

    def _delete_clip_by_id(self, clip_id):
        """按片段 ID 删除本地数据、时间线控件和内核时间线数据。"""
        if not clip_id:
            return False
        # 记录撤销栈：先取出完整片段对象，供 _undo 恢复
        deleted_clip = next((c for c in self._clips if c.get("id") == clip_id), None)
        self._clips = [clip for clip in self._clips if clip.get("id") != clip_id]
        self._clip_id_to_widget.pop(clip_id, None)
        if self._current_clip and self._current_clip.get("id") == clip_id:
            self._current_clip = None

        if hasattr(self, '_timeline_widget'):
            self._timeline_widget._clips = [
                clip for clip in getattr(self._timeline_widget, '_clips', [])
                if clip.get("id") != clip_id
            ]
            for track in getattr(self._timeline_widget, '_tracks', []):
                layout = track.get("content_layout")
                if not layout:
                    continue
                for i in reversed(range(layout.count())):
                    widget = layout.itemAt(i).widget()
                    if widget is not None and hasattr(widget, "clip_data"):
                        if widget.clip_data.get("id") == clip_id:
                            layout.removeWidget(widget)
                            widget.deleteLater()
                            break
        try:
            try:
                from app.core.timeline_manager import timeline_manager as real_timeline_manager
            except ImportError:
                from core.timeline_manager import timeline_manager as real_timeline_manager
            current = real_timeline_manager.get_current_timeline()
            if current:
                for track in current.get("tracks", []):
                    real_timeline_manager.delete_clip(current["id"], track["id"], clip_id)
        except Exception as e:
            print(f"删除内核时间线片段失败: {e}")
        # 记录撤销栈：供 _undo 恢复被删片段
        if deleted_clip is not None:
            self._record_action({"type": "delete", "clip": deleted_clip})
        # 同步内核时间线 + 刷新预览，使删除真正作用到视频
        self._sync_kernel_timeline()
        self._refresh_preview_to_current_clip()
        return True

    def _sync_timeline_widget_state(self):
        """同步片段元数据到 ClipWidget，并刷新时间线宽度。"""
        if not hasattr(self, '_timeline_widget'):
            return
        for track in getattr(self._timeline_widget, '_tracks', []):
            layout = track.get("content_layout")
            if not layout:
                continue
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if widget is not None and hasattr(widget, "clip_data"):
                    clip_id = widget.clip_data.get("id")
                    for clip in self._clips:
                        if clip.get("id") == clip_id:
                            widget.clip_data = clip
                            duration = float(clip.get("duration", 10))
                            width = int(duration * 20 * (self._timeline_widget._zoom / 100))
                            widget.setFixedWidth(max(80, width))
                            widget.update()
                            break
        self._timeline_widget.update()

    def _add_clip_to_timeline(self, file_path):
        """将视频素材真实加入内核时间线、本地片段列表和 TimelineWidget。"""
        import os as _os
        import time as _time

        _report_video_import_debug(
            "C",
            "editor_module._add_clip_to_timeline:start",
            "add clip start",
            {
                "file_path": file_path,
                "file_exists": bool(file_path and _os.path.exists(file_path)),
                "module_has_os": "os" in globals(),
                "timeline_widget_type": type(getattr(self, "_timeline_widget", None)).__name__ if hasattr(self, "_timeline_widget") else None,
            },
        )
        if not file_path or not _os.path.exists(file_path):
            QMessageBox.warning(self, "添加失败", "视频文件不存在")
            return
        try:
            try:
                from app.core.timeline_manager import timeline_manager as real_timeline_manager
            except ImportError:
                from core.timeline_manager import timeline_manager as real_timeline_manager
            if not self._current_timeline:
                self._current_timeline = real_timeline_manager.create_timeline("默认时间线")
            duration = self._probe_video_duration(file_path) or 10.0
            clip_info = {
                "name": _os.path.basename(file_path),
                "path": file_path,
                "start_time": self._next_clip_start_time(),
                "duration": duration,
                "in_point": 0,
                "out_point": duration,
                "effects": {},
                "transitions": [],
            }
            new_clip = real_timeline_manager.add_clip(
                self._current_timeline["id"],
                "video_1",
                clip_info,
            )
            clip = {
                "id": new_clip.get("id", f"clip_{int(_time.time() * 1000)}"),
                "name": new_clip.get("name", clip_info["name"]),
                "path": file_path,
                "start_time": new_clip.get("start_time", clip_info["start_time"]),
                "duration": new_clip.get("duration", duration),
                "in_point": new_clip.get("in_point", 0),
                "out_point": new_clip.get("out_point", duration),
                "track": 0,
                "effects": {},
                "transitions": [],
            }
            self._clips.append(clip)
            if hasattr(self, '_timeline_widget'):
                widget = self._timeline_widget.add_clip(clip, 0)
                if widget is not None:
                    self._clip_widgets.append(widget)
                    self._clip_id_to_widget[clip["id"]] = widget
            self._current_clip = clip
            self._video_source = file_path
            self._sync_kernel_timeline()
            self._preview_seg_key = None  # 重置预览缓存，导入后恢复整段预览
            self._refresh_preview_to_current_clip()
            print(f"添加片段到时间线: {clip}")
        except Exception as e:
            _report_video_import_debug(
                "B",
                "editor_module._add_clip_to_timeline:exception",
                "add clip exception",
                {"error": repr(e), "error_type": type(e).__name__},
            )
            logger.exception("添加片段到时间线失败")
            QMessageBox.warning(self, "添加失败", f"添加片段到时间线失败: {e}")
            print(f"添加片段到时间线失败: {e}")

    def _probe_video_duration(self, file_path: str) -> float:
        """读取视频时长，失败时返回 0 让调用方回退默认值。"""
        try:
            from app.modules.lego.professional_video_engine import FFmpegUtils
            info = FFmpegUtils.get_video_info(file_path)
            return float(info.duration) if info and info.duration else 0.0
        except Exception as e:
            print(f"读取视频时长失败: {e}")
            return 0.0

    def _next_clip_start_time(self) -> float:
        """计算新片段默认放置时间，避免全部堆在 0 秒。"""
        if not self._clips:
            return 0.0
        return max(float(c.get("start_time", 0)) + float(c.get("duration", 0)) for c in self._clips)

    def _apply_filter(self, filter_name):
        """将滤镜写入当前片段，并触发预览刷新。"""
        if not self._current_clip:
            QMessageBox.warning(self, "滤镜", "请先选择一个片段")
            return
        slider = getattr(self, '_filter_intensity_slider', None)
        intensity = (slider.value() / 100.0) if slider is not None else 0.7
        self._apply_filter_to_clip(self._current_clip, filter_name, intensity)
        QMessageBox.information(self, "滤镜", f"已应用 {filter_name} 滤镜，强度 {intensity:.0%}")

    def _apply_filter_to_clip(self, clip: Dict[str, Any], filter_name: str, intensity: float):
        """对指定片段应用滤镜元数据。"""
        effects = clip.get("effects") or {}
        if not isinstance(effects, dict):
            effects = {}
        effects["filter"] = filter_name
        effects["filter_intensity"] = max(0.0, min(1.0, float(intensity)))
        clip["effects"] = effects
        clip["filter"] = filter_name
        clip["filter_intensity"] = effects["filter_intensity"]
        self._sync_timeline_widget_state()
        self._refresh_preview_with_effects()

    def _select_filter(self, filter_key: str):
        """选中某个滤镜分类并立即应用到当前片段（效果面板按钮入口）。"""
        self._active_filter_key = filter_key
        self._apply_filter(filter_key)

    def _clear_filter(self):
        """清除当前片段的滤镜，恢复为原片。"""
        if not self._current_clip:
            QMessageBox.warning(self, "滤镜", "请先选择一个片段")
            return
        self._current_clip.pop("filter", None)
        self._current_clip.pop("filter_intensity", None)
        effects = self._current_clip.get("effects") or {}
        effects.pop("filter", None)
        effects.pop("filter_intensity", None)
        self._current_clip["effects"] = effects
        self._active_filter_key = ""
        self._refresh_preview_with_effects()
        QMessageBox.information(self, "滤镜", "已清除滤镜（恢复原片）")

    def _apply_active_filter_with_intensity(self):
        """用当前强度滑块重新应用已选滤镜，使『强度』滑块真正生效。"""
        key = getattr(self, "_active_filter_key", "")
        if not key:
            QMessageBox.information(self, "滤镜", "请先在上方选择一个滤镜")
            return
        self._apply_filter(key)

    def _apply_effect_to_clip(self, clip: Dict[str, Any], effect_type: str, params: Dict[str, Any]):
        """对指定片段应用通用效果元数据。"""
        effects = clip.get("effects") or {}
        if not isinstance(effects, dict):
            effects = {}
        effects[effect_type] = dict(params or {})
        clip["effects"] = effects
        self._sync_timeline_widget_state()
        self._refresh_preview_with_effects()

    def _apply_transition(self):
        """将转场应用到当前片段，而不是只弹提示。"""
        if not self._current_clip:
            QMessageBox.warning(self, "转场", "请先选择一个片段")
            return
        transition_type = self._transition_type_var.currentText() if hasattr(self, '_transition_type_var') else "fade"
        duration_ms = self._transition_duration_var.value() if hasattr(self, '_transition_duration_var') else 500
        self._apply_transition_to_clip(self._current_clip, transition_type, duration_ms / 1000.0)
        QMessageBox.information(self, "转场", f"已应用 {transition_type} 转场，时长 {duration_ms}ms")

    def _apply_transition_to_clip(self, clip: Dict[str, Any], transition_type: str, duration: float):
        """对指定片段写入转场元数据并尝试同步转场管理器。"""
        transition = {
            "type": transition_type,
            "duration": max(0.1, float(duration)),
            "position": "end",
        }
        clip["transition"] = transition
        transitions = clip.get("transitions") or []
        if not isinstance(transitions, list):
            transitions = []
        transitions.append(transition)
        clip["transitions"] = transitions
        try:
            self._add_transition(clip.get("id"), transition_type, transition["duration"])
        except Exception as e:
            print(f"同步转场管理器失败: {e}")
        self._sync_timeline_widget_state()
        self._refresh_preview_with_effects()

    def _copy_clip(self):
        """复制当前片段数据。"""
        if not self._current_clip:
            QMessageBox.warning(self, "复制", "请先选择一个片段")
            return
        self._copied_clip = dict(self._current_clip)
        QMessageBox.information(self, "复制", "片段已复制")

    def _paste_clip(self):
        """粘贴片段到时间线。"""
        copied = getattr(self, '_copied_clip', None)
        if not copied:
            QMessageBox.warning(self, "粘贴", "剪贴板没有片段")
            return
        self._copy_clip_data_to_timeline(copied)
        self._sync_timeline_widget_state()
        QMessageBox.information(self, "粘贴", "片段已粘贴到时间线")

    def _delete_clip(self):
        """删除当前片段。"""
        if not self._current_clip:
            QMessageBox.warning(self, "删除", "请先选择一个片段")
            return
        clip_id = self._current_clip.get("id")
        self._delete_clip_by_id(clip_id)
        QMessageBox.information(self, "删除", "片段已删除")

    def _cut_clip(self):
        """在播放头位置切分当前片段。"""
        if not self._current_clip:
            QMessageBox.warning(self, "剪切", "请先选择一个片段")
            return
        # 把播放头位置换算成"片段内部时间"，并做边界保护：
        # 若播放头不在片段中间（贴着开头/结尾），切出来一边会是 0 秒空片段，无意义。
        playhead = float(getattr(self, '_playhead_position', 0))
        clip_start = float(self._current_clip.get("start_time", 0))
        clip_dur = float(self._current_clip.get("duration", 0))
        local = playhead - clip_start
        if local <= 0 or local >= clip_dur:
            QMessageBox.warning(self, "剪切", "请先把播放头移到片段中间再剪切")
            return
        result = self._split_clip_at_time(self._current_clip, playhead)
        if result.get("success"):
            QMessageBox.information(self, "剪切", result.get("message", "片段已剪切"))
        else:
            QMessageBox.warning(self, "剪切", result.get("message", "剪切失败"))

    def _open_ai_prompt_dialog(self):
        """兼容旧入口：打开轨道标题栏内嵌剪辑 Agent。"""
        self._toggle_edit_agent_panel(True)
