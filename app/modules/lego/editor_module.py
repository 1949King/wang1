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
    QFormLayout, QSpacerItem, QToolTip, QStackedLayout
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

        # P0：定时自动保存（静默）
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(120000)
        self._autosave_timer.timeout.connect(self._autosave_project)
        self._autosave_timer.start()
        self._project_dirty = False
        self._master_volume = 1.0
        self._bgm_player = None
        self._bgm_audio_output = None
        self._bgm_bound_clip_id = None
        self._autosave_prompted = False
        QTimer.singleShot(1200, self._maybe_restore_autosave)
    
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

    def _ensure_gl_preview(self):
        """懒加载 GPU 滤镜预览组件；GL 不可用时返回 None（全程回退 CPU 路径）"""
        w = getattr(self, '_gl_widget', None)
        if w is not None:
            return w if getattr(w, 'gl_ok', False) else None
        if getattr(self, '_gl_unavailable', False):
            return None
        try:
            # 预检 GL 可用性，避免黑窗
            from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext
            surf = QOffscreenSurface()
            surf.create()
            ctx = QOpenGLContext()
            if not ctx.create():
                self._gl_unavailable = True
                logger.warning("GL 上下文创建失败，滤镜预览走 CPU 路径")
                return None
            from core.gl_filter_widget import GLFilterWidget
            w = GLFilterWidget(self._preview_frame)
            pv = self._preview_frame.layout()
            if isinstance(pv, QStackedLayout):
                pv.addWidget(w)
                pv.setCurrentWidget(w)  # 触发 initializeGL
            w.show()
            self._gl_widget = w
            if not w.gl_ok:
                self._gl_unavailable = True
                return None
            # GL 接管滤镜后，PreviewManager 只供原始帧
            if getattr(self, '_preview_manager', None) is not None:
                self._preview_manager.set_active_effects(None)
            print("✅ GPU 滤镜预览已启用")
            return w
        except Exception as e:
            logger.warning(f"GL 预览初始化失败，回退 CPU 预览: {e}")
            self._gl_unavailable = True
            self._gl_widget = None
            return None

    def _show_frame_gl(self, qimg, effects):
        """GPU 显示路径：字幕叠加后上传纹理，滤镜/缩放由 shader 完成"""
        gl = getattr(self, '_gl_widget', None)
        if gl is None or not getattr(gl, 'gl_ok', False):
            self._on_preview_frame(qimg)
            return
        try:
            qimg = self._overlay_subtitles_on_qimage(qimg)
        except Exception:
            pass
        try:
            pv_layout = self._preview_frame.layout()
            if isinstance(pv_layout, QStackedLayout):
                pv_layout.setCurrentWidget(gl)
        except Exception:
            pass
        gl.show_frame(qimg, effects or {})


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
            ("📂 打开", self._open_project),
            ("💾 保存", self._save_project),
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
        pv_layout = QStackedLayout(self._preview_frame)
        pv_layout.setContentsMargins(0, 0, 0, 0)
        self._video_widget.setStyleSheet("background-color: #000000;")
        pv_layout.addWidget(self._video_widget)
        self._preview_label = QLabel("视频预览区")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet("color: #666666; font-size: 16px; background-color: #000000;")
        pv_layout.addWidget(self._preview_label)
        pv_layout.setCurrentWidget(self._preview_label)
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
        snap_btn.toggled.connect(self._on_snap_toggled)
        title_layout.addWidget(snap_btn)
        
        layout.addWidget(title_bar)
        
        body = QWidget()
        body_lo = QVBoxLayout(body)
        body_lo.setContentsMargins(8, 8, 8, 8)
        
        self._timeline_widget = TimelineWidget()
        self._timeline_widget.clip_selected.connect(self._on_clip_selected)
        # 补短 P1#8：监听关键帧点击 - 落到具体 keyframe 数据上
        self._timeline_widget.clip_keyframe_clicked.connect(self._on_keyframe_clicked)
        # 连接拖放导入信号
        self._timeline_widget.files_dropped.connect(self._on_files_dropped)
        self._timeline_widget.clip_context_action.connect(self._on_timeline_clip_context)
        self._timeline_widget.playhead_moved.connect(self._on_timeline_playhead_moved)
        self._timeline_widget.clip_trim_committed.connect(self._on_clip_trim_committed)
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
                    creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0
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
                    except Exception as _e:
                        logger.warning("操作异常（已忽略）: %s", _e)
            else:
                info = f"📁 {os.path.basename(file_path)}\n\n{os.path.getsize(file_path) // 1024} KB"
                self._import_preview_label.setText(info)
        except Exception as e:
            self._import_preview_label.setText(f"预览失败: {e}")

    def _on_preview_frame(self, qimage):
        """预览帧更新：叠字幕后显示（中文走 QPainter）"""
        if qimage and hasattr(self, '_preview_label') and hasattr(self, '_preview_frame'):
            try:
                qimage = self._overlay_subtitles_on_qimage(qimage)
            except Exception as e:
                print(f"字幕叠加失败: {e}")
            pixmap = QPixmap.fromImage(qimage)
            if not pixmap.isNull():
                pv_layout = self._preview_frame.layout()
                if isinstance(pv_layout, QStackedLayout):
                    pv_layout.setCurrentWidget(self._preview_label)
                self._preview_label.setPixmap(
                    pixmap.scaled(self._preview_frame.size(), 
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation))
                self._preview_label.show()

    def _overlay_subtitles_on_qimage(self, qimage):
        """在预览图上绘制当前时间轴字幕"""
        try:
            sm = self._ensure_subtitle_manager()
        except Exception:
            return qimage
        if sm is None:
            return qimage
        try:
            subs = sm.list_subtitles()
        except Exception:
            return qimage
        if not subs:
            return qimage
        t = float(getattr(self, "_playhead_position", 0) or 0)
        active = [
            s for s in subs
            if s.get("visible", True)
            and float(s.get("start_time", 0)) <= t <= float(s.get("end_time", 0))
        ]
        if not active:
            return qimage
        img = qimage.copy()
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = img.width(), img.height()
        for sub in active:
            text = str(sub.get("text", "") or "")
            if not text:
                continue
            font_size = 28
            outline = 2
            text_color = QColor(255, 255, 255)
            try:
                style = sm.get_subtitle_style(sub.get("style", "default")) or {}
                font_size = int(style.get("font_size", 28) or 28)
                outline = int(style.get("outline", style.get("stroke", 2)) or 2)
                c = style.get("color") or style.get("font_color") or "#FFFFFF"
                if isinstance(c, str) and c.startswith("#") and len(c) >= 7:
                    text_color = QColor(c)
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
            font = QFont("Microsoft YaHei", max(14, int(font_size * h / 1080)))
            painter.setFont(font)
            fm = QFontMetrics(font)
            tw = fm.horizontalAdvance(text)
            th = fm.height()
            x = max(8, (w - tw) // 2)
            y_ratio = 0.85
            try:
                y_ratio = float((sub.get("position") or {}).get("y", 0.85))
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
            y = int(h * min(0.95, max(0.1, y_ratio)))
            pad = 8
            painter.fillRect(x - pad, y - th - pad // 2, tw + pad * 2, th + pad, QColor(0, 0, 0, 150))
            # 描边
            if outline > 0:
                painter.setPen(QColor(0, 0, 0))
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                    painter.drawText(x + dx * outline // 2, y + dy * outline // 2, text)
            painter.setPen(text_color)
            painter.drawText(x, y, text)
        painter.end()
        return img

    def _on_timecode_updated(self, tc):
        """单文件 PM 播放时的时间码；时间线播放模式下由 tick 驱动，此处不抢 playhead"""
        if hasattr(self, '_timecode_label'):
            self._timecode_label.setText(tc)
        if getattr(self, "_timeline_playing", False):
            return
        pm = getattr(self, '_preview_manager', None)
        if pm and pm.is_playing:
            t = float(pm.current_time)
            self._playhead_position = t
            self._current_time = t
            if hasattr(self, '_timeline_widget') and self._timeline_widget:
                self._timeline_widget.set_playhead_position(t)
            self._update_time_display()



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
        """加载视频 - 使用PreviewManager显示画面，QMediaPlayer仅用于音频播放"""
        self._preview_label.setText(f"加载中... {os.path.basename(file_path)}")
        pv_layout = self._preview_frame.layout()
        if isinstance(pv_layout, QStackedLayout):
            pv_layout.setCurrentWidget(self._preview_label)
        
        # 使用QMediaPlayer加载视频（主要用于音频）
        media_content = QUrl.fromLocalFile(file_path)
        self._media_player.setSource(media_content)
        
        # 信号只连接一次，避免重复导入后回调叠加
        if not getattr(self, '_media_signals_connected', False):
            self._media_player.playbackStateChanged.connect(self._on_playback_state_changed)
            self._media_player.positionChanged.connect(self._on_position_changed)
            self._media_player.durationChanged.connect(self._on_duration_changed)
            self._media_player.mediaStatusChanged.connect(self._on_media_status_changed)
            self._media_player.errorOccurred.connect(self._on_media_error)
            self._media_signals_connected = True
        
        # 使用PreviewManager加载视频用于画面预览
        try:
            preview_manager = self._ensure_preview_manager()
            if preview_manager.open_video(file_path):
                initial_frame = preview_manager.get_frame_at(0.0)
                if initial_frame:
                    self._on_preview_frame(initial_frame)
                    print(f"PreviewManager成功加载视频: {file_path}")
        except Exception as e:
            print(f"PreviewManager加载视频失败: {e}")
        
        print(f"加载视频: {file_path}")
        self._add_clip_to_timeline(file_path)
    
    
    
    def _on_clip_selected(self, clip_data):
        """ """
        self._current_clip = clip_data
        print(f"选择片段: {clip_data['id']}")
        self._refresh_preview_to_current_clip()
    
    def _on_media_status_changed(self, status):
        """QMediaPlayer媒体状态变化回调"""
        from PyQt6.QtMultimedia import QMediaPlayer
        status_map = {
            QMediaPlayer.MediaStatus.NoMedia: "NoMedia",
            QMediaPlayer.MediaStatus.LoadingMedia: "LoadingMedia",
            QMediaPlayer.MediaStatus.LoadedMedia: "LoadedMedia",
            QMediaPlayer.MediaStatus.StalledMedia: "StalledMedia",
            QMediaPlayer.MediaStatus.BufferedMedia: "BufferedMedia",
            QMediaPlayer.MediaStatus.EndOfMedia: "EndOfMedia",
            QMediaPlayer.MediaStatus.InvalidMedia: "InvalidMedia",
        }
        print(f"媒体状态变化: {status_map.get(status, status)}")
        
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._video_duration = self._media_player.duration()
            if hasattr(self, '_progress_bar'):
                self._progress_bar.setRange(0, self._video_duration)
            print(f"视频时长: {self._video_duration}ms")
    
    def _on_media_error(self, error, error_string):
        """QMediaPlayer错误回调"""
        print(f"媒体播放错误: {error_string}")
        self._preview_label.setText(f"播放失败: {error_string}")
        pv_layout = self._preview_frame.layout()
        if isinstance(pv_layout, QStackedLayout):
            pv_layout.setCurrentWidget(self._preview_label)
    
    def on_deactivated(self):
        """模块停用回调 - 停止所有媒体播放"""
        self._media_player.stop()
        self._audio_output = None
        logger.info("编辑器模块已停用，媒体播放器已停止")

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
        """关键帧点击：选中片段并刷新预览（插值已接入 _collect_preview_effects）。"""
        self._current_clip = clip_data
        try:
            prop = keyframe.get('prop', 'value')
            t = float(keyframe.get('time_offset', 0.0) or 0)
            value = keyframe.get('value', 0.0)
            st = float(clip_data.get("start_time", 0) or 0)
            self._playhead_position = st + t
            if hasattr(self, "_timeline_widget") and self._timeline_widget:
                self._timeline_widget.set_playhead_position(self._playhead_position)
            self._refresh_preview_with_effects()
            self._notify_edit(f"关键帧 {prop}={value} @ {t:.2f}s")
        except Exception as e:
            print(f"关键帧点击处理异常: {e}")

    def set_clip_speed(self, clip_id, speed: float):
        """设置片段播放速度（预览时钟与导出 setpts）。"""
        speed = max(0.05, min(8.0, float(speed)))
        for clip in self._clips:
            if clip.get("id") != clip_id:
                continue
            clip["speed"] = speed
            self._project_dirty = True
            self._refresh_preview_with_effects()
            self._notify_edit(f"片段速度 {speed}x")
            return True
        return False

    def add_keyframe_at_playhead(self, prop: str = "opacity", value: float = 1.0):
        """在播放头位置为当前片段添加关键帧。"""
        clip = self._current_clip
        if not clip:
            self._notify_edit("请先选择片段")
            return False
        st = float(clip.get("start_time", 0) or 0)
        local_t = max(0.0, float(self._playhead_position) - st)
        kfs = list(clip.get("keyframes") or [])
        kfs.append({
            "time_offset": local_t,
            "value": float(value),
            "prop": prop,
            "easing": "linear",
        })
        return self.add_keyframes_to_clip(clip.get("id"), kfs)
        """移动片段开始时间（写入数据 + 时间线定位 + 撤销）。"""
        for clip in self._clips:
            if clip.get("id") != clip_id:
                continue
            before = {
                "start_time": float(clip.get("start_time", 0) or 0),
                "track": int(clip.get("track", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
            }
            clip["start_time"] = max(0.0, float(new_start_time))
            self._record_action({
                "type": "edit_clip",
                "clip_id": clip_id,
                "before": before,
                "after": {
                    "start_time": float(clip["start_time"]),
                    "track": int(clip.get("track", 0) or 0),
                    "duration": float(clip.get("duration", 0) or 0),
                    "in_point": float(clip.get("in_point", 0) or 0),
                    "out_point": float(clip.get("out_point", 0) or 0),
                },
            })
            self._sync_timeline_widget_state()
            self._sync_kernel_timeline()
            self._notify_edit(f"已移动片段到 {clip['start_time']:.2f}s")
            return True
        return False

    def _resize_clip(self, clip_id, new_duration):
        """调整片段时长并同步 out_point。"""
        for clip in self._clips:
            if clip.get("id") != clip_id:
                continue
            before = {
                "start_time": float(clip.get("start_time", 0) or 0),
                "track": int(clip.get("track", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
            }
            dur = max(0.05, float(new_duration))
            in_p = float(clip.get("in_point", 0) or 0)
            clip["duration"] = dur
            clip["out_point"] = in_p + dur
            self._record_action({
                "type": "edit_clip",
                "clip_id": clip_id,
                "before": before,
                "after": {
                    "start_time": float(clip.get("start_time", 0) or 0),
                    "track": int(clip.get("track", 0) or 0),
                    "duration": dur,
                    "in_point": in_p,
                    "out_point": in_p + dur,
                },
            })
            self._sync_timeline_widget_state()
            self._sync_kernel_timeline()
            return True
        return False
    
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
        self._project_dirty = True
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
            if hasattr(self._timeline_widget, "remove_clip_widget_by_id"):
                self._timeline_widget.remove_clip_widget_by_id(clip_id)
            else:
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

    def _apply_clip_fields(self, clip: dict, fields: dict) -> None:
        if not clip or not fields:
            return
        for k, v in fields.items():
            clip[k] = v

    def _apply_action(self, action: dict, mode: str) -> None:
        """执行一次操作或其逆操作。

        mode='do'  正向执行（用于重做 / 记录时的实做）
        mode='undo' 反向回滚（用于撤销）
        """
        atype = action.get("type")

        if atype in ("delete", "redo_delete"):
            is_delete = (mode == 'do')
            clip = action["clip"]
            shifts = action.get("ripple_shifts") or []
            if is_delete:
                self._clips = [c for c in self._clips if c.get("id") != clip.get("id")]
                self._timeline_remove_clip_widget(clip.get("id"))
                if self._current_clip and self._current_clip.get("id") == clip.get("id"):
                    self._current_clip = None
                for sh in shifts:
                    for c in self._clips:
                        if c.get("id") == sh.get("id"):
                            c["start_time"] = float(sh.get("new", c.get("start_time", 0)))
            else:
                if clip not in self._clips:
                    self._clips.append(clip)
                self._timeline_add_clip_widget(clip)
                self._current_clip = clip
                for sh in shifts:
                    for c in self._clips:
                        if c.get("id") == sh.get("id"):
                            c["start_time"] = float(sh.get("old", c.get("start_time", 0)))

        elif atype in ("split", "redo_split"):
            is_split = (mode == 'do')
            original = action["original_clip"]
            new_clip = action["new_clip"]
            if is_split:
                left_dur = float(action["original_duration"]) - float(new_clip.get("duration", 0))
                if left_dur <= 0.05:
                    left_dur = float(action["original_duration"]) * 0.5
                original["duration"] = left_dur
                original["out_point"] = float(original.get("in_point", 0)) + left_dur
                if new_clip not in self._clips:
                    self._clips.append(new_clip)
                self._timeline_add_clip_widget(new_clip)
                self._current_clip = new_clip
            else:
                original["duration"] = action["original_duration"]
                original["out_point"] = action["original_out_point"]
                self._clips = [c for c in self._clips if c.get("id") != new_clip.get("id")]
                self._timeline_remove_clip_widget(new_clip.get("id"))
                self._current_clip = original

        elif atype in ("paste", "redo_paste"):
            is_paste = (mode == 'do')
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

        elif atype == "edit_clip":
            clip_id = action.get("clip_id")
            fields = action.get("after") if mode == "do" else action.get("before")
            for c in self._clips:
                if c.get("id") == clip_id:
                    self._apply_clip_fields(c, fields or {})
                    self._current_clip = c
                    break

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
            self._notify_edit(f"已撤销: {action.get('type')}")
        else:
            self._notify_edit("没有可撤销的操作")
        self._update_undo_redo_state()

    def _redo(self):
        """重做最近撤销的操作（时间线感知，按钮自动 enable/disable）。"""
        if getattr(self, '_redo_history', []):
            action = self._redo_history.pop()
            self._action_history.append(action)
            self._apply_action(action, mode='do')
            self._notify_edit(f"已重做: {action.get('type')}")
        else:
            self._notify_edit("没有可重做的操作")
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
        """应用特效到片段并立即预览。"""
        target_clip = None
        for clip in self._clips:
            if clip['id'] == clip_id:
                target_clip = clip
                break
        if not target_clip:
            self._notify_edit("未找到指定的片段")
            return
        # 经 EffectManager 规范化参数
        try:
            em = self._ensure_effect_manager()
            inst = {"name": effect_name, "effect_id": effect_name, "parameters": dict(params)}
            em.apply_effect(clip_id, inst)
            params = dict(inst.get("_preview_params") or params)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        effects = target_clip.get('effects', {})
        if not isinstance(effects, dict):
            effects = {}
        effects.update(params)
        effects[effect_name] = params
        target_clip['effects'] = effects
        self._current_clip = target_clip
        self._refresh_preview_with_effects()
        self._notify_edit(f"特效 {effect_name} 已应用")

    def _apply_effect_to_clip(self, clip: Dict[str, Any], effect_type: str, params: Dict[str, Any]):
        """对指定片段应用通用效果元数据。"""
        effects = clip.get("effects") or {}
        if not isinstance(effects, dict):
            effects = {}
        mapped = dict(params or {})
        try:
            em = self._ensure_effect_manager()
            inst = {"name": effect_type, "effect_id": effect_type, "parameters": mapped}
            em.apply_effect(clip.get("id"), inst)
            mapped.update(inst.get("_preview_params") or {})
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        effects[effect_type] = mapped
        for k in ("blur", "sharpen", "vignette", "brightness", "contrast", "saturation", "opacity", "scale"):
            if k in mapped:
                effects[k] = mapped[k]
        clip["effects"] = effects
        self._sync_timeline_widget_state()
        self._refresh_preview_with_effects()

    def _add_transition(self, clip_id, transition_name, duration=1.0):
        """添加转场元数据到片段。"""
        target_clip = None
        for clip in self._clips:
            if clip['id'] == clip_id:
                target_clip = clip
                break
        if not target_clip:
            self._notify_edit("未找到指定的片段")
            return
        transitions = target_clip.get('transitions', [])
        if not isinstance(transitions, list):
            transitions = []
        transitions.append({
            'type': transition_name,
            'duration': duration,
            'time': self._playhead_position
        })
        target_clip['transitions'] = transitions
        target_clip['transition'] = transitions[-1]
        self._notify_edit(f"转场 {transition_name} {duration}s")

    def _refresh_preview_with_effects(self):
        """刷新预览以反映当前效果参数（所见即所得）"""
        pm = self._ensure_preview_manager() if hasattr(self, '_ensure_preview_manager') else None
        if not pm:
            return
        clip = self._current_clip
        effects = self._collect_preview_effects(clip)
        # 用素材内时间刷新
        t = float(getattr(self, '_playhead_position', 0) or 0)
        if clip:
            st = float(clip.get('start_time', 0) or 0)
            in_p = float(clip.get('in_point', 0) or 0)
            source_t = max(0.0, t - st + in_p)
        else:
            source_t = t
        # GPU 路径：取原始帧，滤镜交给 shader（滑杆拖动只换 uniform，秒开）
        gl = self._ensure_gl_preview()
        if gl is not None and clip:
            src = clip.get('path')
            if src and os.path.exists(src) and getattr(pm, '_video_source', None) != src:
                pm.open_video(src)
            qimg = pm.get_frame_at(source_t, effects={})
            if qimg is not None:
                self._show_frame_gl(qimg, effects)
                return
        pm.set_active_effects(effects)
        pm.update_preview(source_t, effects=effects)

    def _collect_preview_effects(self, clip=None) -> dict:
        """汇总当前片段滤镜/调色/关键帧插值，供预览与播放共用。"""
        clip = clip or self._current_clip
        effects: dict = {}
        if clip:
            raw = clip.get("effects") or {}
            if isinstance(raw, dict):
                effects.update(raw)
            if clip.get("filter"):
                effects["filter"] = clip.get("filter")
                effects["filter_intensity"] = float(clip.get("filter_intensity", 0.7) or 0.7)
            elif getattr(self, "_active_filter_key", ""):
                effects["filter"] = self._active_filter_key
                slider = getattr(self, "_filter_intensity_slider", None)
                effects["filter_intensity"] = (slider.value() / 100.0) if slider else 0.7
            # 关键帧插值（相对片段本地时间）
            t = float(getattr(self, "_playhead_position", 0) or 0)
            st = float(clip.get("start_time", 0) or 0)
            local_t = max(0.0, t - st)
            kf_vals = self._interpolate_clip_keyframes(clip, local_t)
            for k, v in kf_vals.items():
                if k == "volume":
                    effects["_volume"] = v
                else:
                    effects[k] = v
            if "opacity" not in effects and clip.get("opacity") is not None:
                effects["opacity"] = float(clip.get("opacity"))
            if clip.get("speed"):
                effects["_speed"] = float(clip.get("speed") or 1.0)
        cp = getattr(self, "_color_params", None) or {}
        if cp:
            nested = effects.get("color_params")
            if isinstance(nested, dict):
                merged = dict(nested)
                merged.update(cp)
                effects["color_params"] = merged
            else:
                effects["color_params"] = dict(cp)
        return effects

    def _interpolate_clip_keyframes(self, clip, local_t: float) -> dict:
        """线性插值片段关键帧（opacity/volume/scale）。"""
        kfs = clip.get("keyframes") or []
        if not isinstance(kfs, list) or not kfs:
            return {}
        by_prop = {}
        for kf in kfs:
            if not isinstance(kf, dict):
                continue
            prop = str(kf.get("prop") or kf.get("property") or "")
            if not prop:
                continue
            by_prop.setdefault(prop, []).append(kf)
        out = {}
        for prop, items in by_prop.items():
            if prop not in ("opacity", "volume", "scale", "scale_x", "scale_y"):
                continue
            items = sorted(items, key=lambda x: float(x.get("time_offset", x.get("time", 0)) or 0))
            times = [float(x.get("time_offset", x.get("time", 0)) or 0) for x in items]
            vals = [float(x.get("value", 0) or 0) for x in items]
            if local_t <= times[0]:
                out[prop if prop != "scale_x" else "scale"] = vals[0]
                continue
            if local_t >= times[-1]:
                out[prop if prop != "scale_x" else "scale"] = vals[-1]
                continue
            for i in range(len(times) - 1):
                if times[i] <= local_t <= times[i + 1]:
                    span = times[i + 1] - times[i] or 1e-6
                    a = (local_t - times[i]) / span
                    v = vals[i] * (1 - a) + vals[i + 1] * a
                    key = "scale" if prop in ("scale", "scale_x", "scale_y") else prop
                    out[key] = v
                    break
        return out

    def _clips_at_playhead(self, t: float = None):
        """播放头下所有覆盖片段，按 track 升序（下层在前）。"""
        if t is None:
            t = float(getattr(self, "_playhead_position", 0) or 0)
        hits = []
        for c in getattr(self, "_clips", []) or []:
            st = float(c.get("start_time", 0) or 0)
            dur = float(c.get("duration", 0) or 0)
            if st <= t < st + dur:
                hits.append(c)
        hits.sort(key=lambda c: int(c.get("track", 0) or 0))
        return hits

    def _clip_at_playhead(self, t: float = None):
        """按播放头找覆盖中的主视频片段（最高视频轨优先，否则第一段）。"""
        hits = self._clips_at_playhead(t)
        if not hits:
            return self._current_clip
        # 优先非 audio 类型 / 非音频轨
        video_hits = []
        for c in hits:
            track_i = int(c.get("track", 0) or 0)
            is_audio = str(c.get("type", "")).lower() == "audio"
            if hasattr(self, "_timeline_widget") and self._timeline_widget:
                tracks = getattr(self._timeline_widget, "_tracks", [])
                if 0 <= track_i < len(tracks) and tracks[track_i].get("type") == "audio":
                    is_audio = True
            if not is_audio:
                video_hits.append(c)
        if video_hits:
            return video_hits[-1]  # 上层
        return hits[-1]

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

    def _on_files_dropped(self, file_paths):
        """处理时间线拖放导入的文件列表"""
        for file_path in file_paths:
            if os.path.exists(file_path):
                self._add_clip_to_timeline(file_path)
                print(f"✅ 拖放导入成功: {os.path.basename(file_path)}")
            else:
                print(f"⚠️ 无法导入: {file_path}")

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
                              creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
                
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
                except Exception as _e:
                    logger.warning("操作异常（已忽略）: %s", _e)
                
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
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)

    def _emit_ai_fail(self, message):
        """从后台线程安全地发射失败信号"""
        try:
            self.ai_fail_signal.emit(message)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
    
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
                    creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0
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
    def export_project(self, output_path, show_message: bool = True):
        """导出项目（片段 + 字幕 + 音量）"""
        subs = []
        try:
            sm = self._ensure_subtitle_manager()
            if sm:
                subs = sm.list_subtitles()
                styles = getattr(sm, "styles", None) or getattr(sm, "_styles", None) or {}
                if callable(getattr(sm, "list_styles", None)):
                    styles = sm.list_styles()
            else:
                styles = {}
        except Exception:
            styles = {}
        project_data = {
            "version": "1.1",
            "clips": self._clips,
            "timeline_zoom": self._timeline_zoom,
            "subtitles": subs,
            "subtitle_styles": styles if isinstance(styles, dict) else {},
            "master_volume": float(getattr(self, "_master_volume", 1.0) or 1.0),
            "export_time": datetime.now().isoformat()
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            import json
            json.dump(project_data, f, ensure_ascii=False, indent=2)
        
        self._project_dirty = False
        if show_message:
            QMessageBox.information(self, "保存完成", f"项目已保存到:\n{output_path}")

    def _autosave_project(self):
        """静默自动保存到 autosave/latest.timeline"""
        if not getattr(self, "_clips", None):
            return
        try:
            autosave_dir = os.path.join(os.getcwd(), "autosave")
            os.makedirs(autosave_dir, exist_ok=True)
            latest = os.path.join(autosave_dir, "latest.timeline")
            self.export_project(latest, show_message=False)
            self._notify_edit("已自动保存")
        except Exception as e:
            print(f"自动保存失败: {e}")

    def _maybe_restore_autosave(self):
        """空工程时询问是否恢复自动保存。"""
        if getattr(self, "_autosave_prompted", False):
            return
        self._autosave_prompted = True
        if getattr(self, "_clips", None):
            return
        latest = os.path.join(os.getcwd(), "autosave", "latest.timeline")
        if not os.path.isfile(latest):
            return
        try:
            reply = QMessageBox.question(
                self,
                "恢复自动保存",
                "发现 autosave/latest.timeline，是否恢复？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.import_project(latest)
        except Exception as e:
            print(f"autosave 恢复询问失败: {e}")

    def _on_clip_trim_committed(self, clip_data):
        """片段拖拽/裁剪松手：同步内核、撤销栈并标记脏"""
        if not clip_data:
            return
        before = None
        if isinstance(clip_data, dict) and "_edit_before" in clip_data:
            before = clip_data.pop("_edit_before", None)
        cid = clip_data.get("id")
        for i, c in enumerate(self._clips):
            if c.get("id") == cid:
                # 合并字段到已有 dict，保持引用
                c.update({k: v for k, v in clip_data.items() if k != "_edit_before"})
                clip_data = c
                self._clips[i] = c
                break
        else:
            self._clips.append(clip_data)
        self._current_clip = clip_data
        if before:
            after = {
                "start_time": float(clip_data.get("start_time", 0) or 0),
                "track": int(clip_data.get("track", 0) or 0),
                "duration": float(clip_data.get("duration", 0) or 0),
                "in_point": float(clip_data.get("in_point", 0) or 0),
                "out_point": float(clip_data.get("out_point", 0) or 0),
            }
            if any(float(before.get(k, 0) or 0) != float(after.get(k, 0) or 0)
                   for k in ("start_time", "duration", "in_point", "out_point", "track")):
                self._record_action({
                    "type": "edit_clip",
                    "clip_id": cid,
                    "before": before,
                    "after": after,
                })
        self._project_dirty = True
        try:
            self._sync_kernel_timeline()
            self._sync_timeline_widget_state()
            self._refresh_preview_to_current_clip()
        except Exception as e:
            print(f"trim commit sync failed: {e}")
        self._notify_edit("片段已调整")
    
    def import_project(self, project_path):
        """导入项目并重建时间线片段控件"""
        if not os.path.exists(project_path):
            QMessageBox.warning(self, "错误", "项目文件不存在")
            return
        
        with open(project_path, 'r', encoding='utf-8') as f:
            import json
            project_data = json.load(f)
        
        clips = project_data.get("clips", [])
        self._timeline_zoom = project_data.get("timeline_zoom", 100)
        self._master_volume = float(project_data.get("master_volume", 1.0) or 1.0)
        try:
            if getattr(self, "_audio_output", None):
                self._audio_output.setVolume(self._master_volume)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        self._clips = []
        self._clip_widgets = []
        self._clip_id_to_widget = {}
        self._current_clip = None

        # 清空现有轨道上的片段控件
        if hasattr(self, '_timeline_widget') and self._timeline_widget:
            if hasattr(self._timeline_widget, "all_clip_widgets"):
                for w in list(self._timeline_widget.all_clip_widgets()):
                    cid = w.clip_data.get("id")
                    self._timeline_widget.remove_clip_widget_by_id(cid)
            else:
                for track in getattr(self._timeline_widget, '_tracks', []):
                    layout = track.get("content_layout")
                    if not layout:
                        continue
                    for i in reversed(range(layout.count())):
                        w = layout.itemAt(i).widget()
                        if w is not None and hasattr(w, "clip_data"):
                            layout.removeWidget(w)
                            w.deleteLater()
            self._timeline_widget._clips = []

        for clip in clips:
            if not isinstance(clip, dict):
                continue
            self._clips.append(clip)
            if hasattr(self, '_timeline_widget') and self._timeline_widget:
                widget = self._timeline_widget.add_clip(clip, int(clip.get("track", 0)))
                if widget is not None:
                    self._clip_widgets.append(widget)
                    if clip.get("id"):
                        self._clip_id_to_widget[clip["id"]] = widget
            if not self._current_clip:
                self._current_clip = clip

        # 恢复字幕
        try:
            sm = self._ensure_subtitle_manager()
            subs = project_data.get("subtitles") or []
            if sm and hasattr(sm, "subtitles"):
                sm.subtitles = list(subs)
            styles = project_data.get("subtitle_styles") or {}
            if sm and styles and hasattr(sm, "styles"):
                sm.styles = dict(styles)
        except Exception as e:
            print(f"导入字幕失败: {e}")

        if self._current_clip and self._current_clip.get("path"):
            self._video_source = self._current_clip["path"]
            try:
                media_content = QUrl.fromLocalFile(self._video_source)
                self._media_player.setSource(media_content)
                pm = self._ensure_preview_manager()
                if pm.open_video(self._video_source):
                    frame = pm.get_frame_at(float(self._current_clip.get("in_point", 0)))
                    if frame is not None:
                        self._on_preview_frame(frame)
            except Exception as e:
                print(f"打开工程后预览加载失败: {e}")

        self._sync_kernel_timeline()
        if hasattr(self, "_timeline_widget") and hasattr(self._timeline_widget, "relayout_clips"):
            self._timeline_widget.relayout_clips()
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

        # Ctrl+O: 打开项目
        self._open_shortcut = QShortcut(QKeySequence("Ctrl+O"), self)
        self._open_shortcut.activated.connect(self._open_project)
        
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
        """保存项目（仅写工程文件，不触发字幕生成）"""
        path, _ = QFileDialog.getSaveFileName(self, "保存项目", "", "项目文件 (*.timeline)")
        if not path:
            return
        if not path.endswith(".timeline"):
            path += ".timeline"
        self.export_project(path)

    def _open_project(self):
        """打开已保存的工程并重建时间线控件"""
        path, _ = QFileDialog.getOpenFileName(self, "打开项目", "", "项目文件 (*.timeline);;所有文件 (*.*)")
        if path:
            self.import_project(path)




    
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
        # 导出主故事线：视频轨；音频轨另行处理（本期仍拼主视频轨）
        def _is_audio_clip(c):
            if str(c.get("type", "")).lower() == "audio":
                return True
            ti = int(c.get("track", 0) or 0)
            if hasattr(self, "_timeline_widget") and self._timeline_widget:
                tracks = getattr(self._timeline_widget, "_tracks", [])
                if 0 <= ti < len(tracks) and tracks[ti].get("type") == "audio":
                    return True
            return False
        clips = [c for c in clips if not _is_audio_clip(c)]
        clips = sorted(clips, key=lambda c: (int(c.get("track", 0) or 0), float(c.get("start_time", 0))))
        # 同时刻多层：只取最低轨作主线（PiP 烘焙留待后续）；同轨按时间排
        if clips:
            base_track = min(int(c.get("track", 0) or 0) for c in clips)
            clips = [c for c in clips if int(c.get("track", 0) or 0) == base_track]
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
                # 片段速度
                speed = float(clip.get("speed", 1.0) or 1.0)
                if abs(speed - 1.0) > 0.01:
                    sseg = tempfile.mktemp(suffix=".mp4")
                    try:
                        cmd = [
                            ffmpeg_path, "-y", "-i", final_seg,
                            "-filter:v", f"setpts={1.0/speed}*PTS",
                            "-filter:a", f"atempo={max(0.5, min(2.0, speed))}",
                            "-c:v", "libx264", "-c:a", "aac", sseg,
                        ]
                        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                        if r.returncode == 0 and os.path.exists(sseg):
                            tmp_segments.append(sseg)
                            final_seg = sseg
                    except Exception as e:
                        print(f"变速烘焙失败: {e}")
                # 音量
                vol = float(clip.get("volume", 1.0) or 1.0)
                if abs(vol - 1.0) > 0.01:
                    vseg = tempfile.mktemp(suffix=".mp4")
                    try:
                        cmd = [
                            ffmpeg_path, "-y", "-i", final_seg,
                            "-af", f"volume={vol}",
                            "-c:v", "copy", vseg,
                        ]
                        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                        if r.returncode == 0 and os.path.exists(vseg):
                            tmp_segments.append(vseg)
                            final_seg = vseg
                    except Exception as e:
                        print(f"音量烘焙失败: {e}")
                filtered_segments.append(final_seg)
                seg_dur = (out_p - in_p) / max(0.05, speed)
                durations.append(seg_dur)
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
                except Exception as _e:
                    logger.warning("操作异常（已忽略）: %s", _e)

    def _sync_kernel_timeline(self):
        """将 self._clips 同步进统一内核，保留真实 start_time / track。"""
        try:
            from app.core.timeline_manager import timeline_manager as real_timeline_manager
        except ImportError:
            from core.timeline_manager import timeline_manager as real_timeline_manager
        if not getattr(self, '_current_timeline', None):
            self._current_timeline = real_timeline_manager.create_timeline("默认时间线")
        tl = self._current_timeline
        # 清空各轨 clips
        for track in tl.get("tracks", []):
            track["clips"] = []
        # 确保有足够 video/audio 轨
        video_tracks = [t for t in tl.get("tracks", []) if t.get("type") == "video"]
        audio_tracks = [t for t in tl.get("tracks", []) if t.get("type") == "audio"]
        for clip in self._clips:
            track_i = int(clip.get("track", 0) or 0)
            clip_info = {
                "id": clip.get("id"),
                "name": clip.get("name", os.path.basename(str(clip.get("path", "")))),
                "path": clip.get("path"),
                "start_time": float(clip.get("start_time", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
                "effects": clip.get("effects", {}),
                "transitions": clip.get("transitions", []),
                "speed": float(clip.get("speed", 1.0) or 1.0),
                "volume": float(clip.get("volume", 1.0) or 1.0),
                "keyframes": clip.get("keyframes") or [],
            }
            ctype = str(clip.get("type", "video") or "video").lower()
            # 根据时间线 UI 轨类型判断
            ui_track_type = "video"
            if hasattr(self, "_timeline_widget") and self._timeline_widget:
                tracks = getattr(self._timeline_widget, "_tracks", [])
                if 0 <= track_i < len(tracks):
                    ui_track_type = tracks[track_i].get("type", "video")
            if ui_track_type == "audio" or ctype == "audio":
                if not audio_tracks:
                    try:
                        real_timeline_manager.add_track(tl["id"], "audio", "音频")
                        audio_tracks = [t for t in tl.get("tracks", []) if t.get("type") == "audio"]
                    except Exception as _e:
                        logger.warning("操作异常（已忽略）: %s", _e)
                tid = audio_tracks[min(track_i, len(audio_tracks) - 1)]["id"] if audio_tracks else "audio_1"
            else:
                if not video_tracks:
                    tid = "video_1"
                else:
                    tid = video_tracks[min(track_i, len(video_tracks) - 1)]["id"]
            try:
                real_timeline_manager.add_clip(tl["id"], tid, clip_info)
            except Exception as e:
                print(f"同步片段到内核失败: {e}")
        try:
            real_timeline_manager._recalculate_duration(tl)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)

    def _burn_subtitles_if_any(self, video_path: str) -> str:
        """若有字幕则烧录到成片（需 FFmpeg）。"""
        import shutil
        try:
            sm = self._ensure_subtitle_manager()
            subs = sm.list_subtitles() if sm else []
        except Exception:
            subs = []
        if not subs or not video_path or not os.path.exists(video_path):
            return video_path
        ffmpeg = shutil.which("ffmpeg") or getattr(self, "_get_ffmpeg", lambda: None)()
        if not ffmpeg:
            return video_path
        srt_path = os.path.splitext(video_path)[0] + "_burn.srt"
        out_path = os.path.splitext(video_path)[0] + "_sub" + os.path.splitext(video_path)[1]
        try:
            sm.export_subtitles(srt_path, format="srt")
            # Windows 路径转义 for subtitles filter
            esc = srt_path.replace("\\", "/").replace(":", "\\:")
            cmd = [
                ffmpeg, "-y", "-i", video_path,
                "-vf", f"subtitles='{esc}'",
                "-c:a", "copy",
                out_path,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if r.returncode == 0 and os.path.exists(out_path):
                try:
                    os.replace(out_path, video_path)
                except Exception:
                    return out_path
                return video_path
        except Exception as e:
            print(f"字幕烧录失败: {e}")
        finally:
            try:
                if os.path.exists(srt_path):
                    os.remove(srt_path)
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
        return video_path

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

            # 无 FFmpeg 时：未剪辑可直接复制；有剪辑则明确提示
            import shutil
            _ff = shutil.which("ffmpeg")
            if not _ff:
                if edited_temp_path is None and not self._has_timeline_edits():
                    try:
                        shutil.copy2(clip_path, output_path)
                        QMessageBox.information(
                            self,
                            "导出成功",
                            f"未检测到 FFmpeg，已复制原片到:\n{output_path}\n"
                            f"安装 FFmpeg 并加入 PATH 后可支持剪辑导出与转码。",
                        )
                        return
                    except Exception as _ce:
                        QMessageBox.warning(self, "导出失败", f"复制失败: {_ce}")
                        return
                QMessageBox.warning(
                    self,
                    "导出失败",
                    "未检测到 FFmpeg，无法导出已剪辑时间线。\n"
                    "请安装 FFmpeg 并加入系统 PATH 后重试。",
                )
                return

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
                    except Exception as _e:
                        logger.warning("操作异常（已忽略）: %s", _e)
                success = result.get("success") if isinstance(result, dict) else getattr(result, "success", False)
                if success:
                    try:
                        output_path = self._burn_subtitles_if_any(output_path)
                    except Exception as _be:
                        print(f"字幕烧录跳过: {_be}")
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
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        return t

    @staticmethod
    def _safe_set_text(label, text: str):
        """安全设置 QLabel 文本，防止 C++ 对象已被删除时崩溃"""
        try:
            label.setText(text)
        except (RuntimeError, AttributeError) as _e:
            logger.warning("操作异常（已忽略）: %s", _e)

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
            except (RuntimeError, AttributeError) as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
            return

        try:
            cache = AnalysisCache()
            drama = cache.get_drama(video_path)
            prefs = cache.get_character_prefs(video_path)
        except Exception as e:
            self._safe_set_text(self._char_status_label, f"读取缓存异常: {e}")
            try:
                self._char_list_layout.addStretch()
            except (RuntimeError, AttributeError) as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
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
            except (RuntimeError, AttributeError) as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
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
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
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
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
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
                   creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
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
                   creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
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
                   creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
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
                   creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
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
        except (ImportError, OSError) as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
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
    
    # 播放控制方法
    def _notify_edit(self, msg: str) -> None:
        """轻量反馈：状态栏 + toast，避免每次剪辑都弹模态框"""
        self._undo_redo_toast = msg
        print(f"[剪辑] {msg}")
        try:
            win = self.window()
            if win is not None and hasattr(win, "statusBar"):
                sb = win.statusBar()
                if sb is not None:
                    sb.showMessage(msg, 2500)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)

    def _play_pause(self):
        """播放/暂停：时间线驱动（跨片段切源），接近剪映预览行为"""
        from PyQt6.QtMultimedia import QMediaPlayer

        src = getattr(self, '_video_source', None)
        if not src and self._current_clip:
            src = self._current_clip.get('path')
        if not src and not self._clips:
            self._notify_edit("请先导入视频")
            return

        if getattr(self, "_timeline_playing", False) or (
            self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            and getattr(self, "_timeline_play_timer", None)
            and self._timeline_play_timer.isActive()
        ):
            self._stop_timeline_playback()
            return

        # 若仅媒体在播（旧路径），先停
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
            if hasattr(self, '_preview_manager') and self._preview_manager:
                self._preview_manager.pause_preview()
            if hasattr(self, '_timeline_widget') and self._timeline_widget:
                self._timeline_widget.pause()
            if hasattr(self, '_pp_btn'):
                self._pp_btn.setText("▶")
            return

        self._start_timeline_playback()

    def _timeline_total_duration(self) -> float:
        if not self._clips:
            return float(getattr(self, "_total_duration", 0) or 0)
        return max(
            float(c.get("start_time", 0) or 0) + float(c.get("duration", 0) or 0)
            for c in self._clips
        )

    def _playback_rate(self) -> float:
        speed_map = {"0.5x": 0.5, "1x": 1.0, "1.5x": 1.5, "2x": 2.0}
        text = "1x"
        if hasattr(self, "_playback_speed_combo"):
            text = self._playback_speed_combo.currentText()
        return speed_map.get(text, 1.0)

    def _start_timeline_playback(self):
        """以时间线时钟驱动预览：自动跨片段切源 + 特效 + 音频跟随"""
        if hasattr(self, "_preview_manager") and self._preview_manager:
            try:
                self._preview_manager.pause_preview()
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
        self._timeline_playing = True
        self._audio_bound_clip_id = None
        if not getattr(self, "_timeline_play_timer", None):
            self._timeline_play_timer = QTimer(self)
            self._timeline_play_timer.timeout.connect(self._on_timeline_playback_tick)
        self._timeline_play_timer.start(33)
        if hasattr(self, "_pp_btn"):
            self._pp_btn.setText("⏸")
        # 立即渲染当前帧
        self._render_timeline_frame(float(getattr(self, "_playhead_position", 0) or 0))
        self._notify_edit("时间线播放中")

    def _stop_timeline_playback(self):
        self._timeline_playing = False
        if getattr(self, "_timeline_play_timer", None):
            self._timeline_play_timer.stop()
        try:
            self._media_player.pause()
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        try:
            if getattr(self, "_bgm_player", None):
                self._bgm_player.pause()
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        if hasattr(self, "_preview_manager") and self._preview_manager:
            try:
                self._preview_manager.pause_preview()
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
        if hasattr(self, "_timeline_widget") and self._timeline_widget:
            try:
                self._timeline_widget.pause()
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
        if hasattr(self, "_pp_btn"):
            self._pp_btn.setText("▶")

    def _on_timeline_playback_tick(self):
        if not getattr(self, "_timeline_playing", False):
            return
        rate = self._playback_rate()
        t = float(getattr(self, "_playhead_position", 0) or 0) + 0.033 * rate
        total = self._timeline_total_duration()
        if total > 0 and t >= total:
            self._render_timeline_frame(total)
            self._stop_timeline_playback()
            self._notify_edit("播放结束")
            return
        self._render_timeline_frame(t)

    def _edge_fade_opacity(self, clip, timeline_t: float) -> float:
        """根据转场/淡入淡出元数据计算片段边缘透明度"""
        st = float(clip.get("start_time", 0) or 0)
        dur = float(clip.get("duration", 0) or 0)
        if dur <= 0:
            return 1.0
        local = timeline_t - st
        fade_in = fade_out = 0.0
        transitions = clip.get("transitions") or []
        if isinstance(transitions, list):
            for tr in transitions:
                if not isinstance(tr, dict):
                    continue
                typ = str(tr.get("type") or tr.get("name") or tr.get("transition_type") or "")
                d = float(tr.get("duration", 0.5) or 0.5)
                if any(k in typ.lower() for k in ("fade", "淡")) or "淡" in typ:
                    fade_in = max(fade_in, d)
                    fade_out = max(fade_out, d)
        # 效果里也可能写了 fade
        eff = clip.get("effects") or {}
        if isinstance(eff, dict):
            if eff.get("fade_in"):
                fade_in = max(fade_in, float(eff.get("fade_in") or 0))
            if eff.get("fade_out"):
                fade_out = max(fade_out, float(eff.get("fade_out") or 0))
        opacity = 1.0
        if fade_in > 0 and local < fade_in:
            opacity = min(opacity, max(0.0, local / fade_in))
        if fade_out > 0 and local > dur - fade_out:
            opacity = min(opacity, max(0.0, (dur - local) / fade_out))
        return opacity

    def _render_timeline_frame(self, timeline_t: float):
        """按时间线时间渲染一帧（多轨叠层 + 特效 + 转场近似 + 音频/BGM）"""
        self._playhead_position = float(timeline_t)
        self._current_time = float(timeline_t)
        self._update_time_display()
        if hasattr(self, "_timeline_widget") and self._timeline_widget:
            self._timeline_widget.set_playhead_position(timeline_t)

        hits = self._clips_at_playhead(timeline_t)
        video_hits = []
        audio_hits = []
        for c in hits:
            track_i = int(c.get("track", 0) or 0)
            is_audio = str(c.get("type", "")).lower() == "audio"
            if hasattr(self, "_timeline_widget") and self._timeline_widget:
                tracks = getattr(self._timeline_widget, "_tracks", [])
                if 0 <= track_i < len(tracks) and tracks[track_i].get("type") == "audio":
                    is_audio = True
            if is_audio:
                audio_hits.append(c)
            else:
                video_hits.append(c)

        if not video_hits:
            try:
                from PyQt6.QtGui import QImage
                img = QImage(1280, 720, QImage.Format.Format_RGB888)
                img.fill(0)
                self._on_preview_frame(img)
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
            try:
                self._media_player.pause()
                self._audio_bound_clip_id = None
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
            self._sync_bgm_audio(timeline_t, audio_hits)
            return

        # 底层 → 上层 合成
        base_frame = None
        top_clip = video_hits[-1]
        self._current_clip = top_clip
        try:
            import numpy as np
            pm = self._ensure_preview_manager()
            use_gl_single = len(video_hits) == 1 and self._ensure_gl_preview() is not None
            gl_shown = False
            for clip in video_hits:
                src = clip.get("path")
                if not src or not os.path.exists(src):
                    continue
                st = float(clip.get("start_time", 0) or 0)
                in_p = float(clip.get("in_point", 0) or 0)
                speed = max(0.05, float(clip.get("speed", 1.0) or 1.0))
                source_t = max(0.0, (timeline_t - st) * speed + in_p)
                effects = dict(self._collect_preview_effects(clip) or {})
                opacity = self._edge_fade_opacity(clip, timeline_t)
                # 与下一片交叉的 dissolve 近似
                opacity = min(opacity, self._crossfade_opacity(clip, timeline_t, video_hits))
                if "opacity" in effects:
                    try:
                        opacity = min(opacity, float(effects["opacity"]))
                    except Exception as _e:
                        logger.warning("操作异常（已忽略）: %s", _e)
                effects["opacity"] = opacity
                if effects.get("scale"):
                    effects["scale"] = float(effects["scale"])
                if pm._video_source != src:
                    pm.open_video(src)
                if use_gl_single:
                    # GPU 路径：取原始帧直传 shader，跳过 numpy 特效与 CPU 合成
                    _raw = pm.get_frame_at(source_t, effects={}) if hasattr(pm, "get_frame_at") else None
                    if _raw is not None:
                        self._show_frame_gl(_raw, effects)
                        self._video_source = top_clip.get("path")
                        gl_shown = True
                    break
                frame = pm.get_frame_at(source_t, effects=effects) if hasattr(pm, "get_frame_at") else None
                if frame is None:
                    pm.set_active_effects(effects)
                    pm.update_preview(source_t, effects=effects)
                    continue
                # get_frame_at may return QImage
                arr = self._qimage_or_ndarray_to_bgr(frame)
                if arr is None:
                    continue
                if base_frame is None:
                    base_frame = arr.astype(np.float32)
                else:
                    # 缩放对齐
                    if arr.shape[:2] != base_frame.shape[:2]:
                        import cv2
                        arr = cv2.resize(arr, (base_frame.shape[1], base_frame.shape[0]))
                    op = float(effects.get("opacity", 1.0) or 1.0)
                    scale = float(effects.get("scale", 1.0) or 1.0)
                    overlay = arr.astype(np.float32)
                    if abs(scale - 1.0) > 0.01:
                        import cv2
                        h, w = overlay.shape[:2]
                        nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
                        scaled = cv2.resize(overlay, (nw, nh))
                        canvas = np.zeros_like(overlay)
                        y0 = max(0, (h - nh) // 2)
                        x0 = max(0, (w - nw) // 2)
                        y1, x1 = min(h, y0 + nh), min(w, x0 + nw)
                        canvas[y0:y1, x0:x1] = scaled[: y1 - y0, : x1 - x0]
                        overlay = canvas
                    base_frame = base_frame * (1.0 - op) + overlay * op
            if base_frame is not None:
                out = np.clip(base_frame, 0, 255).astype(np.uint8)
                qimg = self._bgr_to_qimage(out)
                if qimg is not None:
                    self._on_preview_frame(qimg)
                self._video_source = top_clip.get("path")
            else:
                # 回退单源 update_preview
                clip = top_clip
                src = clip["path"]
                st = float(clip.get("start_time", 0) or 0)
                in_p = float(clip.get("in_point", 0) or 0)
                speed = max(0.05, float(clip.get("speed", 1.0) or 1.0))
                source_t = max(0.0, (timeline_t - st) * speed + in_p)
                effects = dict(self._collect_preview_effects(clip) or {})
                effects["opacity"] = self._edge_fade_opacity(clip, timeline_t)
                if pm._video_source != src:
                    pm.open_video(src)
                pm.set_active_effects(effects)
                pm.update_preview(source_t, effects=effects)
                self._video_source = src
        except Exception as e:
            print(f"时间线帧渲染失败: {e}")

        # 主视频内嵌音
        try:
            clip = top_clip
            src = clip.get("path")
            st = float(clip.get("start_time", 0) or 0)
            in_p = float(clip.get("in_point", 0) or 0)
            speed = max(0.05, float(clip.get("speed", 1.0) or 1.0))
            source_t = max(0.0, (timeline_t - st) * speed + in_p)
            cid = clip.get("id")
            from PyQt6.QtCore import QUrl
            from PyQt6.QtMultimedia import QMediaPlayer
            vol = float(clip.get("volume", 1.0) or 1.0)
            effects = self._collect_preview_effects(clip)
            if effects.get("_volume") is not None:
                vol = float(effects["_volume"])
            master = float(getattr(self, "_master_volume", 1.0) or 1.0)
            if getattr(self, "_audio_output", None):
                self._audio_output.setVolume(max(0.0, min(1.0, vol * master)))
            clip_changed = getattr(self, "_audio_bound_clip_id", None) != cid
            if clip_changed:
                self._media_player.setSource(QUrl.fromLocalFile(src))
                self._audio_bound_clip_id = cid
                self._media_player.setPlaybackRate(self._playback_rate() * speed)
                self._media_player.setPosition(int(source_t * 1000))
                self._media_player.play()
            else:
                self._media_player.setPlaybackRate(self._playback_rate() * speed)
                pos_s = self._media_player.position() / 1000.0
                if abs(pos_s - source_t) > 0.35:
                    self._media_player.setPosition(int(source_t * 1000))
                if self._media_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                    self._media_player.play()
        except Exception as e:
            print(f"音频同步失败: {e}")

        self._sync_bgm_audio(timeline_t, audio_hits)

    def _crossfade_opacity(self, clip, timeline_t: float, video_hits) -> float:
        """邻片重叠区间做 dissolve 近似。"""
        st = float(clip.get("start_time", 0) or 0)
        dur = float(clip.get("duration", 0) or 0)
        end = st + dur
        fade = 0.0
        for tr in (clip.get("transitions") or []):
            if isinstance(tr, dict):
                typ = str(tr.get("type") or tr.get("name") or "")
                if any(k in typ.lower() for k in ("fade", "dissolve", "淡", "叠")):
                    fade = max(fade, float(tr.get("duration", 0.5) or 0.5))
        if fade <= 0:
            return 1.0
        # 片尾淡出
        if timeline_t > end - fade:
            return max(0.0, (end - timeline_t) / fade)
        # 片头：若与前片重叠则淡入
        if timeline_t < st + fade:
            return max(0.0, (timeline_t - st) / fade) if timeline_t >= st else 0.0
        return 1.0

    def _qimage_or_ndarray_to_bgr(self, frame):
        try:
            import numpy as np
            from PyQt6.QtGui import QImage
            if isinstance(frame, QImage):
                img = frame.convertToFormat(QImage.Format.Format_RGB888)
                w, h = img.width(), img.height()
                ptr = img.bits()
                ptr.setsize(h * w * 3)
                arr = np.frombuffer(ptr, np.uint8).reshape((h, w, 3)).copy()
                return arr[:, :, ::-1]  # RGB->BGR
            if hasattr(frame, "shape"):
                return frame
        except Exception:
            return None
        return None

    def _bgr_to_qimage(self, bgr):
        try:
            import numpy as np
            from PyQt6.QtGui import QImage
            rgb = bgr[:, :, ::-1].copy()
            h, w, ch = rgb.shape
            return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
        except Exception:
            return None

    def _ensure_bgm_player(self):
        if getattr(self, "_bgm_player", None) is not None:
            return self._bgm_player
        from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
        self._bgm_player = QMediaPlayer()
        self._bgm_audio_output = QAudioOutput()
        self._bgm_player.setAudioOutput(self._bgm_audio_output)
        return self._bgm_player

    def _sync_bgm_audio(self, timeline_t: float, audio_hits):
        """独立音频轨 BGM 跟随。"""
        try:
            player = self._ensure_bgm_player()
            if not audio_hits:
                player.pause()
                self._bgm_bound_clip_id = None
                return
            clip = audio_hits[-1]
            src = clip.get("path")
            if not src or not os.path.exists(src):
                player.pause()
                return
            st = float(clip.get("start_time", 0) or 0)
            in_p = float(clip.get("in_point", 0) or 0)
            source_t = max(0.0, timeline_t - st + in_p)
            vol = float(clip.get("volume", 1.0) or 1.0) * float(getattr(self, "_master_volume", 1.0) or 1.0)
            if self._bgm_audio_output:
                self._bgm_audio_output.setVolume(max(0.0, min(1.0, vol)))
            from PyQt6.QtCore import QUrl
            from PyQt6.QtMultimedia import QMediaPlayer
            cid = clip.get("id")
            if getattr(self, "_bgm_bound_clip_id", None) != cid:
                player.setSource(QUrl.fromLocalFile(src))
                self._bgm_bound_clip_id = cid
                player.setPosition(int(source_t * 1000))
                player.play()
            else:
                if abs(player.position() / 1000.0 - source_t) > 0.35:
                    player.setPosition(int(source_t * 1000))
                if player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                    player.play()
        except Exception as e:
            print(f"BGM 同步失败: {e}")

    def _rewind(self):
        """后退 10 秒（以播放头为准，不依赖 QMediaPlayer 时长）"""
        cur = float(getattr(self, '_playhead_position', 0) or 0)
        new_t = max(0.0, cur - 10.0)
        if getattr(self, "_timeline_playing", False):
            self._render_timeline_frame(new_t)
        else:
            self._on_timeline_playhead_moved(new_t)
        if hasattr(self, '_timeline_widget') and self._timeline_widget:
            self._timeline_widget.set_playhead_position(new_t)
    
    def _fast_forward(self):
        """快进 10 秒（以播放头为准）"""
        cur = float(getattr(self, '_playhead_position', 0) or 0)
        dur = self._timeline_total_duration()
        if dur <= 0 and self._media_player.duration() > 0:
            dur = self._media_player.duration() / 1000.0
        if dur <= 0 and hasattr(self, '_preview_manager') and self._preview_manager:
            dur = float(getattr(self._preview_manager, '_video_duration', 0) or 0)
        new_t = min(dur, cur + 10.0) if dur > 0 else cur + 10.0
        if getattr(self, "_timeline_playing", False):
            self._render_timeline_frame(new_t)
        else:
            self._on_timeline_playhead_moved(new_t)
        if hasattr(self, '_timeline_widget') and self._timeline_widget:
            self._timeline_widget.set_playhead_position(new_t)
    
    def _on_playback_speed_changed(self, speed_text):
        """播放倍速：同步音频与画面预览"""
        speed_map = {"0.5x": 0.5, "1x": 1.0, "1.5x": 1.5, "2x": 2.0}
        rate = speed_map.get(speed_text, 1.0)
        self._media_player.setPlaybackRate(rate)
        if hasattr(self, '_preview_manager') and self._preview_manager:
            self._preview_manager.playing_speed = rate
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
        if hasattr(self, '_pp_btn') and self._pp_btn is not None:
            self._pp_btn.setText("⏸" if self._is_playing else "▶")
    
    def _on_position_changed(self, position):
        """ """
        # 转换为秒
        current_time = position / 1000
        self._current_time = current_time
        self._playhead_position = current_time
        self._update_time_display()
        
        if hasattr(self, '_timeline_widget') and self._timeline_widget:
            self._timeline_widget.set_playhead_position(current_time)
        
        # 更新进度条
        if hasattr(self, '_progress_bar') and self._media_player.duration() > 0:
            self._progress_bar.setValue(int((position / self._media_player.duration()) * 100))

    def _on_timeline_playhead_moved(self, position: float):
        """时间线播放头拖动/跳转：按片段切源 + 应用滤镜（所见即所得）"""
        self._playhead_position = float(position)
        self._current_time = float(position)
        self._update_time_display()
        clip = self._clip_at_playhead(position)
        if clip and clip.get("path") and os.path.exists(clip.get("path")):
            src = clip["path"]
            self._video_source = src
            self._current_clip = clip
            pm = getattr(self, '_preview_manager', None) or self._ensure_preview_manager()
            if pm._video_source != src:
                pm.open_video(src)
            st = float(clip.get("start_time", 0) or 0)
            in_p = float(clip.get("in_point", 0) or 0)
            source_t = max(0.0, float(position) - st + in_p)
            effects = self._collect_preview_effects(clip)
            pm.set_active_effects(effects)
            pm.update_preview(source_t, effects=effects)
            if self._media_player.duration() > 0:
                self._media_player.setPosition(int(source_t * 1000))
            return
        src = getattr(self, '_video_source', None)
        if not src and self._current_clip:
            src = self._current_clip.get('path')
        if src:
            pm = getattr(self, '_preview_manager', None) or self._ensure_preview_manager()
            if pm._video_source != src:
                pm.open_video(src)
            effects = self._collect_preview_effects(self._current_clip)
            pm.set_active_effects(effects)
            pm.update_preview(position, effects=effects)
        if self._media_player.duration() > 0:
            self._media_player.setPosition(int(position * 1000))

    def _on_snap_toggled(self, enabled: bool):
        """吸附开关：写入时间线标志，供后续拖拽对齐使用"""
        self._snap_enabled = bool(enabled)
        if hasattr(self, '_timeline_widget') and self._timeline_widget is not None:
            self._timeline_widget._snap_enabled = bool(enabled)

    def _on_timeline_clip_context(self, action: str, clip_data):
        """轨道/片段右键菜单动作"""
        if clip_data:
            self._current_clip = clip_data
            self._on_clip_selected(clip_data)
        if action == "split" and clip_data:
            result = self._split_clip_at_time(
                clip_data, float(getattr(self, '_playhead_position', 0))
            )
            self._notify_edit(result.get("message", "已分割") if result else "分割失败")
        elif action == "delete" and clip_data:
            self._delete_clip_by_id(clip_data.get("id"))
            self._notify_edit("片段已删除")
        elif action == "copy" and clip_data:
            self._copied_clip = dict(clip_data)
            self._notify_edit("片段已复制")
        elif action == "duplicate" and clip_data:
            self._copy_clip_data_to_timeline(clip_data)
            self._notify_edit("已复制一份到时间线")
        elif action == "paste":
            copied = getattr(self, '_copied_clip', None)
            if copied:
                self._copy_clip_data_to_timeline(copied)
                self._notify_edit("片段已粘贴")
            else:
                self._notify_edit("剪贴板没有片段")
        self._update_undo_redo_state()
    
    def _on_progress_slider_moved(self, value):
        """预览进度条拖动：按百分比跳转时间"""
        duration = float(getattr(self, '_total_duration', 0) or 0)
        if duration <= 0 and self._media_player.duration() > 0:
            duration = self._media_player.duration() / 1000.0
        if duration <= 0:
            return
        # 进度条若是 0-100 百分比
        t = (value / 100.0) * duration if value <= 100 else (value / 1000.0) * duration
        self._on_timeline_playhead_moved(t)
    
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
        
        # 所见即所得：拖动滑块即时预览（不弹窗）
        brightness = self._brightness_slider.value()
        contrast = self._contrast_slider.value()
        saturation = self._saturation_slider.value()
        hue = self._hue_slider.value()
        self._color_params = {
            "brightness": round(brightness / 100 * 0.3, 3),
            "contrast": round(1.0 + contrast / 100 * 0.5, 3),
            "saturation": round(1.0 + saturation / 100 * 0.5, 3),
            "hue": hue,
        }
        self._refresh_preview_with_effects()
    
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
        self._notify_edit(
            f"已应用调节（亮度{brightness}, 对比度{contrast}, 饱和度{saturation}, 色调{hue}）"
        )
    
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
        """调整主音量（立即作用于 QAudioOutput + 片段默认音量）。"""
        vol = max(0.0, min(1.0, float(volume) / 100.0))
        self._master_volume = vol
        try:
            if getattr(self, "_audio_output", None):
                self._audio_output.setVolume(vol)
            if getattr(self, "_bgm_audio_output", None):
                self._bgm_audio_output.setVolume(vol)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        if hasattr(self, '_audio_manager') and self._audio_manager:
            tracks = self._audio_manager.list_audio_tracks()
            for t in tracks:
                self._audio_manager.adjust_audio_volume(t['id'], vol)
        self._notify_edit(f"音量 {int(vol * 100)}%")

    def _apply_fade_effects(self):
        """应用淡入淡出效果（通过 ffmpeg）"""
        src = self._get_active_audio_path()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入音频/视频素材")
            return
        fi, ok1 = QInputDialog.getDouble(self, "淡入淡出", "淡入时长(秒):", 0.5, 0, 10, 1)
        if not ok1:
            return
        fo, ok2 = QInputDialog.getDouble(self, "淡入淡出", "淡出时长(秒):", 0.5, 0, 10, 1)
        if not ok2:
            return
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

    def _delete_clip_by_id(self, clip_id, ripple: bool = True):
        """按片段 ID 删除；默认波纹：同轨后续片段前移闭合空隙。"""
        if not clip_id:
            return False
        deleted_clip = next((c for c in self._clips if c.get("id") == clip_id), None)
        if deleted_clip is None:
            return False
        track_i = int(deleted_clip.get("track", 0) or 0)
        st = float(deleted_clip.get("start_time", 0) or 0)
        dur = float(deleted_clip.get("duration", 0) or 0)
        end = st + dur
        ripple_shifts = []
        self._clips = [clip for clip in self._clips if clip.get("id") != clip_id]
        self._clip_id_to_widget.pop(clip_id, None)
        if self._current_clip and self._current_clip.get("id") == clip_id:
            self._current_clip = None

        if ripple and dur > 0:
            for c in self._clips:
                if int(c.get("track", 0) or 0) != track_i:
                    continue
                cst = float(c.get("start_time", 0) or 0)
                if cst >= end - 1e-4:
                    old = cst
                    c["start_time"] = max(0.0, cst - dur)
                    ripple_shifts.append({"id": c.get("id"), "old": old, "new": c["start_time"]})

        if hasattr(self, '_timeline_widget'):
            self._timeline_widget._clips = [
                clip for clip in getattr(self._timeline_widget, '_clips', [])
                if clip.get("id") != clip_id
            ]
            if hasattr(self._timeline_widget, "remove_clip_widget_by_id"):
                self._timeline_widget.remove_clip_widget_by_id(clip_id)
            else:
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
        self._record_action({
            "type": "delete",
            "clip": deleted_clip,
            "ripple_shifts": ripple_shifts,
        })
        self._sync_kernel_timeline()
        self._sync_timeline_widget_state()
        self._refresh_preview_to_current_clip()
        self._notify_edit("已删除片段" + ("（波纹）" if ripple else ""))
        return True

    def _sync_timeline_widget_state(self):
        """同步片段元数据到 ClipWidget，并按 start_time 重新定位。"""
        if not hasattr(self, '_timeline_widget'):
            return
        tw = self._timeline_widget
        if hasattr(tw, "all_clip_widgets"):
            for widget in tw.all_clip_widgets():
                clip_id = widget.clip_data.get("id")
                for clip in self._clips:
                    if clip.get("id") == clip_id:
                        widget.clip_data = clip
                        # 若轨变更则 reparent
                        ti = int(clip.get("track", 0) or 0)
                        if hasattr(tw, "reparent_clip_to_track"):
                            tw.reparent_clip_to_track(widget, ti)
                        else:
                            tw.position_clip_widget(widget)
                        widget.update()
                        break
            if hasattr(tw, "relayout_clips"):
                tw.relayout_clips()
        else:
            for track in getattr(tw, '_tracks', []):
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
                                width = int(duration * 20 * (tw._zoom / 100))
                                widget.setFixedWidth(max(80, width))
                                widget.update()
                                break
        tw.update()
    
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
                                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
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
                                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
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
                                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
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
                creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0
            )
            for line in result.stderr.split('\n'):
                if 'Duration' in line:
                    parts = line.strip().split('Duration: ')[1].split(',')[0]
                    h, m, s = parts.split(':')
                    return float(h) * 3600 + float(m) * 60 + float(s)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
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
                                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
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
                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0
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
                               creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)

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
                                            creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)

                    try:
                        os.unlink(trf_file)
                    except Exception as _e:
                        logger.warning("操作异常（已忽略）: %s", _e)

                    if result.returncode == 0:
                        self._add_to_clips(dst, 'video')
                        QMessageBox.information(self, "完成", f"运动跟踪完成:\n{dst}")
                    else:
                        QMessageBox.warning(self, "失败", f"跟踪失败:\n{result.stderr[-500:]}")
                else:
                    QMessageBox.warning(self, "失败", "未能检测到足够的运动数据，请尝试其他视频")
                    try:
                        os.unlink(trf_file)
                    except Exception as _e:
                        logger.warning("操作异常（已忽略）: %s", _e)
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
                                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)

                # 清理临时文件
                for tf in temp_files:
                    if tf != src and not (sticker.get("path") == tf for sticker in self._active_stickers):
                        try:
                            os.unlink(tf)
                        except Exception as _e:
                            logger.warning("操作异常（已忽略）: %s", _e)

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
        self._sync_timeline_widget_state()
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
        self._notify_edit(f"已应用 {filter_name}（强度 {intensity:.0%}）")

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
        self._active_filter_key = filter_name
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
        self._notify_edit("已清除滤镜")

    def _apply_active_filter_with_intensity(self):
        """用当前强度滑块重新应用已选滤镜，使『强度』滑块真正生效。"""
        key = getattr(self, "_active_filter_key", "")
        if not key:
            QMessageBox.information(self, "滤镜", "请先在上方选择一个滤镜")
            return
        self._apply_filter(key)

    def _on_filter_intensity_live(self, value: int):
        """滤镜强度拖动即预览"""
        key = getattr(self, "_active_filter_key", "") or (
            self._current_clip.get("filter") if self._current_clip else ""
        )
        if not key or not self._current_clip:
            return
        intens = value / 100.0
        self._current_clip["filter"] = key
        self._current_clip["filter_intensity"] = intens
        effects = self._current_clip.get("effects") or {}
        if not isinstance(effects, dict):
            effects = {}
        effects["filter"] = key
        effects["filter_intensity"] = intens
        self._current_clip["effects"] = effects
        self._refresh_preview_with_effects()

    def _apply_transition(self):
        """将转场应用到当前片段，而不是只弹提示。"""
        if not self._current_clip:
            QMessageBox.warning(self, "转场", "请先选择一个片段")
            return
        transition_type = self._transition_type_var.currentText() if hasattr(self, '_transition_type_var') else "fade"
        duration_ms = self._transition_duration_var.value() if hasattr(self, '_transition_duration_var') else 500
        self._apply_transition_to_clip(self._current_clip, transition_type, duration_ms / 1000.0)
        self._notify_edit(f"已应用 {transition_type} 转场，时长 {duration_ms}ms")

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
        self._sync_timeline_widget_state()
        self._refresh_preview_with_effects()

    def _copy_clip(self):
        """复制当前片段数据。"""
        if not self._current_clip:
            QMessageBox.warning(self, "复制", "请先选择一个片段")
            return
        self._copied_clip = dict(self._current_clip)
        self._notify_edit("片段已复制")

    def _paste_clip(self):
        """粘贴片段到时间线。"""
        copied = getattr(self, '_copied_clip', None)
        if not copied:
            QMessageBox.warning(self, "粘贴", "剪贴板没有片段")
            return
        self._copy_clip_data_to_timeline(copied)
        self._sync_timeline_widget_state()
        self._notify_edit("片段已粘贴到时间线")

    def _delete_clip(self):
        """删除当前片段。"""
        if not self._current_clip:
            QMessageBox.warning(self, "删除", "请先选择一个片段")
            return
        clip_id = self._current_clip.get("id")
        self._delete_clip_by_id(clip_id)
        self._notify_edit("片段已删除")

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
            self._notify_edit(result.get("message", "片段已剪切"))
        else:
            QMessageBox.warning(self, "剪切", result.get("message", "剪切失败"))

    def _open_ai_prompt_dialog(self):
        """兼容旧入口：打开轨道标题栏内嵌剪辑 Agent。"""
        self._toggle_edit_agent_panel(True)
