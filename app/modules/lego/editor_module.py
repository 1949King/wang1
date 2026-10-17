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

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize, QUrl, QPoint, QMimeData, QEvent
from PyQt6.QtGui import (
    QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics,
    QPolygon, QShortcut, QKeySequence, QDrag, QPixmap, QImage
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
from .ai_agent_panel import AiAgentPanelMixin  # P0 拆分：AI 方法 Mixin
from .editor_export_panel import EditorExportPanelMixin  # P0 拆分：导出方法 Mixin
from .editor_agent_panel_mixin import EditorAgentPanelMixin
from .editor_agent_dock_mixin import EditorAgentDockMixin  # V4.40.50：Agent 右侧独立竖栏
from .editor_effects_mixin import EditorEffectsMixin
from .editor_ui_builder_mixin import EditorUiBuilderMixin
from .editor_ai_process_mixin import EditorAiProcessMixin
from .editor_ai_tools_mixin import EditorAiToolsMixin
from .editor_agent_runtime_mixin import EditorAgentRuntimeMixin
from .editor_compositing import (  # 拆分刀1（2026-10-11）：合成像素纯函数（非冻结符号，抽出后哈希不变）
    apply_clip_crop_bgr,
    composite_overlay_bgr_blend,
)
try:
    from app.core.sequence_format import (
        SequenceFormat,
        parse_resolution,
        normalize_size,
        fit_rect,
        aspect_from_size,
    )
except ImportError:
    from core.sequence_format import (  # type: ignore
        SequenceFormat,
        parse_resolution,
        normalize_size,
        fit_rect,
        aspect_from_size,
    )

# 确保 app/ 在 sys.path 中以兼容 core.xxx 导入
_app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _app_root not in _sys.path:
    _sys.path.insert(0, _app_root)

# Core 管理器懒加载
project_manager = _lazy_import('core.project_manager')
timeline_manager = _lazy_import('core.timeline_manager')
effect_manager = _lazy_import('core.effect_manager')

EditorScheduler = _LazyClassProxy('core.editor_scheduler', 'EditorScheduler')
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
    logger.error(f'爆款优化引擎导入失败: {e}')
    VIRAL_ENGINE_AVAILABLE = False

# 工具类
from .utils.thread_pool import ThreadPool
from .utils.hardware_monitor import (
    HardwareDetector, PerformanceMonitor,
    hardware_detector, hardware_config, performance_monitor,
)

# BaseModule —— 从 modules.py 导入（已在模块加载时定义）
from .base_module import BaseModule


def _clear_msgbox(title: str, message: str, parent=None):
    """延迟导入 modules.show_clear_messagebox 后调用。

    修复：本文件多处调用 show_clear_messagebox 提示"请先导入视频"等，
    但从未 import 过它，触发这些分支必 NameError 崩溃。不能在模块顶层
    `from .modules import show_clear_messagebox`——main_window 懒加载时是
    直接 `import .editor_module`（不经过 modules.py），modules.py 执行到
    文件末尾 `from .editor_module import EditorModule` 时 editor_module
    还在初始化中，会形成循环导入。改用函数内局部 import，只在真正调用时
    才触发，此时两个模块都已完整加载。
    """
    from .modules import show_clear_messagebox
    return show_clear_messagebox(title, message, parent)


class EditingAgentWorker(QThread):
    """剪辑 Agent 后台调用线程，负责对接云端 API 与本地 Ollama 模型。"""

    chunk_ready = pyqtSignal(str)
    result_ready = pyqtSignal(str)
    error_ready = pyqtSignal(str)
    stopped_ready = pyqtSignal()

    def __init__(self, provider: str, model: str, messages: List[Dict[str, str]],
                 parent=None, think: Optional[bool] = None):
        super().__init__(parent)
        self._provider = provider
        self._model = model
        self._messages = messages
        self._stop_requested = False
        self._think = think  # 本地推理模型思考开关：None=默认，False=关闭（更快）

    def request_stop(self):
        """请求终止当前模型输出。"""
        self._stop_requested = True

    def run(self):
        """执行模型调用；逐段转发输出，便于界面模拟 Trae IDE 对话流。"""
        try:
            from app.core.ai_engine import ai_engine

            # 仅本地 Ollama 消费 think；云端不传，避免影响其请求参数
            extra: Dict[str, Any] = {}
            if self._provider == "ollama" and self._think is not None:
                extra["think"] = self._think

            chunks = []
            if self._provider:
                stream = ai_engine.chat(
                    self._provider,
                    self._messages,
                    model=self._model or None,
                    stream=True,
                    use_cache=False,
                    **extra,
                )
            else:
                stream = ai_engine.chat_with_fallback(
                    messages=self._messages,
                    model=self._model or None,
                    use_cache=False,
                    template=lambda: "模型暂不可用，请检查云端 API Key 或本地 Ollama 服务是否正常。",
                )

            for chunk in stream:
                if self._stop_requested:
                    self.stopped_ready.emit()
                    return
                if chunk:
                    chunks.append(str(chunk))
                    self.chunk_ready.emit(str(chunk))

            raw = "".join(chunks).strip()
            # 引擎用 yield "错误: ..." 表示失败，不能当正常 JSON 结果吞掉
            if raw.startswith("错误:") or raw.startswith("API 错误"):
                self.error_ready.emit(raw)
                return
            self.result_ready.emit(raw)
        except Exception as e:
            self.error_ready.emit(str(e))


BLEND_MODE_NAME_TO_KEY = {
    "正常": "normal", "变暗": "darken", "正片叠底": "multiply", "颜色加深": "color_burn",
    "变亮": "lighten", "滤色": "screen", "叠加": "overlay", "柔光": "soft_light",
    "强光": "hard_light", "差值": "difference", "排除": "exclusion",
    "色相": "hue", "饱和度": "saturation", "颜色": "color", "明度": "luminosity",
}


class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin, EditorAgentDockMixin, EditorEffectsMixin, EditorUiBuilderMixin, EditorAiProcessMixin, EditorAiToolsMixin, EditorAgentRuntimeMixin):
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
        # >>> FROZEN:playback-av:init-media BEGIN
        self._media_player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._media_player.setAudioOutput(self._audio_output)
        self._video_widget = QVideoWidget()
        # 画面由 PreviewManager(OpenCV) 负责；QMediaPlayer 只出声。
        # 若再 setVideoOutput，会与 OpenCV 双路解码 → 卡顿，且隐藏 QVideoWidget 上易无声。
        self._audio_pending_play = False
        self._audio_pending_seek_ms = 0
        self._audio_pending_rate = 1.0
        self._ui_playhead_last_ms = 0
        # <<< FROZEN:playback-av:init-media END
        # 视频片段管理
        # _clips 的真相源。⚠️ 它是**跨线程共享**的：
        #   · 画布桥（HTTP 线程）通过 project_snapshot 的 provider/writer 读写；
        #   · autosave 定时器（主线程）每 3s 把 _clips 序列化落盘；
        #   · 渲染/导出路径在主线程遍历。
        # 所有「非原子替换」（先清空再逐个 append）与「序列化遍历」必须持有
        # _clips_lock，否则会读到空列表/半截列表，或让 json.dump 撞上
        # "list changed size during iteration" 写出损坏工程文件。
        self._clips_lock = threading.RLock()
        self._clips = []  # 存储视频片段
        # 时间线真相源（2026-10-18 解冻切换·刀1）：store adopt _clips 的**同一 list 对象**，
        # 结构写入收敛到 self._timeline_store；_clips 读点不受影响（同一性保留）。
        # 懒加载纪律：本模块重型导入均在函数内完成，timeline_store 为纯数据层、无 Qt。
        from app.core.timeline_store import TimelineStore
        self._timeline_store = TimelineStore(self._clips, lock=self._clips_lock)
        self._current_clip = None  # 当前选中的片段
        self._last_beat_times = []
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
        self._sequence_in_point = None  # 序列级入点（秒），None=未标记
        self._sequence_out_point = None  # 序列级出点（秒），None=未标记
        self._active_stickers = []  # 工程级贴纸（预览叠加 / 导出烧录）
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
        
        # 时间线管理系统 - 懒加载
        self._timeline_manager = None
        
        # 特效管理系统 - 懒加载
        self._effect_manager = None
        
        # 字幕系统 - 懒加载
        self._subtitle_manager = None
        
        # 预设系统 - 懒加载
        self._preset_manager = None
        
        # 插件系统 - 懒加载
        self._plugin_manager = None
        
        # 预览管理器 - 懒加载
        self._preview_manager = None
        self._video_source = None

        # 工程画幅 SSOT（默认漫剧竖屏）
        self._sequence_format = SequenceFormat.default()
        
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

        # 调用父类__init__方法（内部会 _setup_ui）
        _t_super = time.perf_counter()
        super().__init__()
        logger.info(
            "editor BaseModule+setup_ui wall=%.0fms",
            (time.perf_counter() - _t_super) * 1000,
        )

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
        try:
            from app.core.canvas_bridge import set_timeline_snapshot_provider
            set_timeline_snapshot_provider(lambda: self.agent_get_timeline_context())
        except Exception:
            logger.debug("画布快照提供者注册失败", exc_info=True)
        try:
            # P1-4 工程级快照：注册完整 _clips 读/写回调（直导剪辑器入口）
            from app.core.project_snapshot import set_full_clips_provider, set_clips_writer
            # ⚠️ 用快照而非 list(self._clips)：本 provider 由画布桥线程调用，
            # 若此刻主线程正在做「清空→填充」的非原子替换，会读到空/半截列表。
            set_full_clips_provider(lambda: self._clips_snapshot())
            set_clips_writer(self.agent_replace_timeline_clips)
        except Exception:
            logger.debug("工程快照读写回调注册失败", exc_info=True)
        
        # 连接工作流 / 数据分析 / JKL：延后到首屏渲染后，避免挡住模块打开
        QTimer.singleShot(0, self._deferred_editor_boot)

        # 安装额外快捷键（轻量，可同步）
        self._install_additional_shortcuts()

        # P0：定时自动保存（静默）+ 脏标记防抖（连续操作合并写盘）
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(120000)
        self._autosave_timer.timeout.connect(self._autosave_project)
        self._autosave_timer.start()
        self._autosave_debounce = QTimer(self)
        self._autosave_debounce.setSingleShot(True)
        self._autosave_debounce.setInterval(3000)  # 停手 3s 后写盘
        self._autosave_debounce.timeout.connect(self._autosave_project)
        self._project_dirty = False
        self._ripple_delete_enabled = True  # 删除默认波纹；工具栏可切普通删除
        self._master_volume = 1.0
        self._bgm_player = None
        self._bgm_audio_output = None
        self._bgm_bound_clip_id = None
        self._autosave_prompted = False
        QTimer.singleShot(1200, self._maybe_restore_autosave)

        # 预览体验：滑杆节流 + 拖 scrub 降分辨率
        self._preview_debounce = QTimer(self)
        self._preview_debounce.setSingleShot(True)
        self._preview_debounce.setInterval(60)
        self._preview_debounce.timeout.connect(self._refresh_preview_with_effects)
        self._scrub_idle_timer = QTimer(self)
        self._scrub_idle_timer.setSingleShot(True)
        self._scrub_idle_timer.setInterval(220)
        self._scrub_idle_timer.timeout.connect(self._end_preview_scrub)
        self._scrub_preview_timer = QTimer(self)
        self._scrub_preview_timer.setSingleShot(True)
        self._scrub_preview_timer.setInterval(80)  # M2：长对白略加大合并窗，降低同步 seek 密度
        self._scrub_preview_timer.timeout.connect(self._flush_scrub_preview)
        self._scrub_preview_pending = None
        self._scrub_preview_coalesce = 0
        self._scrub_render_busy = False
        self._scrub_busy_drops = 0
        self._preview_scrubbing = False
        self._preview_quality_before_scrub = None
        self._preview_gl_cache_key = None  # (src, ms) 同帧只改 GPU uniform
        # P0 体验：用户预览档位 + 代理预览（导出仍用原片 path）
        try:
            from app.modules.lego.editor_preview_ux import DEFAULT_USER_PREVIEW_QUALITY
            self._user_preview_quality = DEFAULT_USER_PREVIEW_QUALITY
        except Exception:
            self._user_preview_quality = "medium"
        self._proxy_preview_enabled = True
        self._preview_quality_before_play = None
        QTimer.singleShot(800, self._init_proxy_media_manager)

    def _deferred_editor_boot(self) -> None:
        """首屏 UI 已挂上后再接工作流 / 分析器 / JKL，缩短模块打开阻塞。"""
        t0 = time.perf_counter()
        try:
            self.connect_to_data_analyzer()
        except Exception as e:
            logger.warning("连接数据分析器失败: %s", e)
        try:
            from app.modules.lego.playback_shuttle import PlaybackShuttle
            self._playback_shuttle = PlaybackShuttle(self)
            self._playback_shuttle.install()
        except Exception as _e:
            logger.warning("JKL shuttle 安装失败（已忽略）: %s", _e)
            self._playback_shuttle = None
        logger.info(
            "editor deferred boot done in %.0fms",
            (time.perf_counter() - t0) * 1000,
        )
    
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
            logger.info('✅ TOP 0级剪辑引擎已通过统一内核调度器加载')
        except Exception as e:
            logger.error(f'⚠️ TOP 0级引擎初始化失败: {e}')
        return self._top0_processor
    
    # [Mixin] 已迁移至 editor_ai_tools_mixin.py
    
    # [Mixin] 已迁移至 editor_ai_tools_mixin.py
    
    def _ensure_subtitle_manager(self):
        """懒加载字幕管理器"""
        if self._subtitle_manager is not None:
            return self._subtitle_manager
        self._subtitle_manager = SubtitleManager()
        logger.info('✅ 字幕系统已加载')
        return self._subtitle_manager
    
    def _ensure_preset_manager(self):
        """懒加载预设管理器"""
        if self._preset_manager is not None:
            return self._preset_manager
        self._preset_manager = PresetManager()
        logger.info('✅ 预设系统已加载')
        return self._preset_manager

    def list_aesthetic_packs(self):
        """列出所有美学预设包（供 UI 面板展示）。"""
        return self._ensure_preset_manager().list_packs()

    def apply_aesthetic_pack(self, pack_id, target_clip_id=None):
        """一键套用美学预设包到片段（写真相源 ``_clips``，可撤销）。

        美学预设包 = 多个 clip 级 step（color/lut/filter/transition/blend_mode/opacity）
        的组合。本方法遍历 steps 写片段 effects/顶层字段，并作为一个 compound action
        压入撤销栈——一次撤销还原整包，不破坏既有 ``edit_clip`` before/after 语义。

        Args:
            pack_id: 预设包 id（见 preset_manager.list_packs()）
            target_clip_id: 目标片段 id；缺省作用于当前选中片段

        Returns:
            dict: success / pack_id / clip_id / name / applied / message
        """
        pm = self._ensure_preset_manager()
        pack = pm.get_pack(pack_id)
        if not pack:
            return {"success": False, "message": f"未找到美学预设包 {pack_id}"}
        steps = pm.apply_pack(pack_id)
        if not steps:
            return {"success": False, "message": f"美学预设包 {pack_id} 无有效步骤"}

        target = None
        if target_clip_id:
            target = next((c for c in self._clips if c.get("id") == target_clip_id), None)
        if target is None:
            target = getattr(self, "_current_clip", None)
        if not isinstance(target, dict) or not target.get("id"):
            return {"success": False, "message": "未选中片段"}

        # before 快照：记录所有会被改动的字段（撤销时精确还原）
        before_effects = dict(target.get("effects") or {}) if isinstance(target.get("effects"), dict) else {}
        before = {
            "effects": before_effects,
            "filter": target.get("filter"),
            "filter_intensity": target.get("filter_intensity"),
            "transition": target.get("transition"),
            "transitions": target.get("transitions"),
            "blend_mode": target.get("blend_mode"),
            "opacity": target.get("opacity"),
        }

        effects = dict(before_effects)
        after_extra: Dict[str, Any] = {}
        applied: List[str] = []

        for step in steps:
            kind = step.get("kind")
            if kind == "color":
                cp = dict(effects.get("color_params") or {})
                for k in ("brightness", "contrast", "saturation", "hue",
                          "exposure", "sharpen", "temperature"):
                    if k in step and step[k] is not None:
                        cp[k] = float(step[k])
                effects["color_params"] = cp
                for k in ("brightness", "contrast", "saturation", "hue", "exposure", "sharpen"):
                    if k in cp:
                        effects[k] = cp[k]
                applied.append("color")
            elif kind == "lut":
                cp = dict(effects.get("color_params") or {})
                lut = step.get("lut")
                if lut:
                    cp["lut"] = lut
                    cp["lut_intensity"] = float(step.get("lut_intensity", 0.7))
                    cp.pop("lut_fast", None)
                else:
                    cp.pop("lut", None)
                    cp.pop("lut_intensity", None)
                effects["color_params"] = cp
                applied.append("lut")
            elif kind == "filter":
                fname = step.get("filter_name") or step.get("name") or ""
                if fname:
                    intens = float(step.get("intensity", 0.7))
                    effects["filter"] = fname
                    effects["filter_intensity"] = intens
                    after_extra["filter"] = fname
                    after_extra["filter_intensity"] = intens
                    applied.append("filter")
            elif kind == "transition":
                ttype = step.get("transition_type") or "fade"
                dur = max(0.1, float(step.get("duration", 0.5)))
                tr = {
                    "type": ttype,
                    "plugin_id": step.get("plugin_id") or ttype,
                    "duration": dur,
                    "position": "end",
                    "curve": step.get("curve", "线性"),
                }
                after_extra["transition"] = tr
                transitions = list(target.get("transitions") or [])
                if not isinstance(transitions, list):
                    transitions = []
                transitions.append(tr)
                after_extra["transitions"] = transitions
                applied.append("transition")
            elif kind == "blend_mode":
                mode = step.get("mode")
                if mode:
                    after_extra["blend_mode"] = str(mode)
                    applied.append("blend_mode")
            elif kind == "opacity":
                op = float(step.get("value", 1.0))
                effects["opacity"] = op
                after_extra["opacity"] = op
                applied.append("opacity")

        after = {
            "effects": effects,
            "filter": after_extra.get("filter", target.get("filter")),
            "filter_intensity": after_extra.get("filter_intensity", target.get("filter_intensity")),
            "transition": after_extra.get("transition", target.get("transition")),
            "transitions": after_extra.get("transitions", target.get("transitions")),
            "blend_mode": after_extra.get("blend_mode", target.get("blend_mode")),
            "opacity": after_extra.get("opacity", target.get("opacity")),
        }

        # 写真相源：先写目标 dict，再兜底同步 _clips 里同 id 片段
        for k, v in after.items():
            target[k] = v
        # 刀4：真相源兜底同步改走 store API（set_fields 命中 live 同 id 行，原地 update）
        self._timeline_store.set_fields(target.get("id"), **after)

        self._record_action({
            "type": "compound",
            "steps": [{"type": "edit_clip", "clip_id": target.get("id"),
                       "before": before, "after": after}],
            "label": f"aesthetic_pack:{pack_id}",
        })
        self._sync_timeline_widget_state()
        self._refresh_preview_with_effects()
        self._notify_edit(f"已套用美学预设包「{pack.get('name')}」")
        return {"success": True, "pack_id": pack_id, "clip_id": target.get("id"),
                "name": pack.get("name"), "applied": applied}

    def _apply_selected_aesthetic_pack(self):
        """调色面板「美学预设包」下拉的套用入口：读选中 pack id → 套用到当前片段。"""
        combo = getattr(self, "_aesthetic_pack_combo", None)
        if combo is None:
            return
        pack_id = combo.currentData()
        if not pack_id:
            QMessageBox.information(self, "美学预设包", "请先选择一个预设包")
            return
        res = self.apply_aesthetic_pack(pack_id)
        if not (isinstance(res, dict) and res.get("success")):
            QMessageBox.warning(self, "美学预设包",
                                (res or {}).get("message", "套用失败"))

    def _ensure_plugin_manager(self):
        """懒加载插件管理器"""
        if self._plugin_manager is not None:
            return self._plugin_manager
        self._plugin_manager = PluginManager()
        self._plugin_manager.load_plugins()
        logger.info('✅ 插件系统已加载')
        return self._plugin_manager
    
    def _ensure_preview_manager(self):
        """懒加载预览管理器"""
        if self._preview_manager is not None:
            return self._preview_manager
        from core.preview_manager import PreviewManager
        self._preview_manager = PreviewManager()
        self._preview_manager.frame_ready.connect(self._on_preview_frame)
        self._preview_manager.timecode_updated.connect(self._on_timecode_updated)
        # 应用用户预览档位（默认 1/2）
        try:
            q = getattr(self, "_user_preview_quality", "medium")
            if hasattr(self._preview_manager, "set_preview_quality"):
                self._preview_manager.set_preview_quality(q)
            if hasattr(self._preview_manager, "set_proxy_preview_enabled"):
                self._preview_manager.set_proxy_preview_enabled(
                    bool(getattr(self, "_proxy_preview_enabled", True))
                )
        except Exception as e:
            logger.debug("初始化预览档位失败: %s", e)
        logger.info('✅ 预览管理器已加载')
        return self._preview_manager

    def _ensure_gl_preview(self):
        """懒加载 GPU 滤镜预览组件；GL 不可用时返回 None（全程回退 CPU 路径）"""
        # 2026-08-08：导入后 GL show_frame 触发 0xC0000005（ACCESS_VIOLATION），
        # 暂强制 CPU QLabel 预览，避免整进程崩；滤镜仍由 PreviewManager CPU 路径处理。
        if not getattr(self, "_gl_force_disabled", True):
            pass  # 预留：设 _gl_force_disabled=False 可再开 GPU 预览
        else:
            self._gl_unavailable = True
            return None

        w = getattr(self, '_gl_widget', None)
        if w is not None:
            if getattr(w, 'gl_ok', False):
                return w
            # 残留坏 GL：切回 CPU label
            try:
                pv = self._preview_frame.layout() if hasattr(self, "_preview_frame") else None
                if isinstance(pv, QStackedLayout) and hasattr(self, "_preview_label"):
                    pv.setCurrentWidget(self._preview_label)
            except Exception:
                logger.debug("预览页切换失败", exc_info=True)
            return None
        if getattr(self, '_gl_unavailable', False):
            return None

        def _fallback_to_cpu_label(orphan=None, reason: str = ""):
            """GL 失败时务必切回 QLabel，并移走孤儿控件，否则预览区会一直黑/?。"""
            self._gl_unavailable = True
            self._gl_widget = None
            try:
                pv = self._preview_frame.layout() if hasattr(self, "_preview_frame") else None
                if isinstance(pv, QStackedLayout) and hasattr(self, "_preview_label"):
                    pv.setCurrentWidget(self._preview_label)
                if orphan is not None:
                    if isinstance(pv, QStackedLayout):
                        pv.removeWidget(orphan)
                    orphan.hide()
                    orphan.setParent(None)
                    orphan.deleteLater()
            except Exception as e:
                logger.debug("GL 回退清理失败: %s", e)
            if reason:
                logger.warning("GL 滤镜预览不可用，回退 CPU: %s", reason)

        try:
            # 预检 GL 可用性，避免黑窗
            from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext
            surf = QOffscreenSurface()
            surf.create()
            ctx = QOpenGLContext()
            if not ctx.create():
                _fallback_to_cpu_label(reason="上下文创建失败")
                return None
            from core.gl_filter_widget import GLFilterWidget
            w = GLFilterWidget(self._preview_frame)
            pv = self._preview_frame.layout()
            if isinstance(pv, QStackedLayout):
                pv.addWidget(w)
                pv.setCurrentWidget(w)  # 触发 initializeGL
            w.show()
            self._gl_widget = w
            if not getattr(w, "gl_ok", False):
                _fallback_to_cpu_label(orphan=w, reason="gl_ok=False")
                return None
            # GL 接管滤镜后，PreviewManager 只供原始帧
            if getattr(self, '_preview_manager', None) is not None:
                self._preview_manager.set_active_effects(None)
            logger.info('✅ GPU 滤镜预览已启用')
            return w
        except Exception as e:
            orphan = locals().get("w")
            _fallback_to_cpu_label(orphan=orphan, reason=str(e))
            return None

    def _show_frame_gl(self, qimg, effects):
        """GPU 显示路径：先 letterbox 到工程画幅，再叠字幕；滤镜由 shader 完成。"""
        gl = getattr(self, '_gl_widget', None)
        if gl is None or not getattr(gl, 'gl_ok', False):
            # 禁止回调 _on_preview_frame，避免与统一出口互相递归
            self._present_preview_frame_cpu(qimg)
            return
        try:
            qimg = self._fit_qimage_to_sequence(qimg)
        except Exception as e:
            logger.debug("GL 画幅 letterbox 失败: %s", e)
        # M2：拖 scrub 时跳过字幕/贴纸叠层（松手 HQ 刷新再补）
        if not getattr(self, "_preview_scrubbing", False):
            try:
                qimg = self._overlay_subtitles_on_qimage(qimg)
                qimg = self._overlay_stickers_on_qimage(qimg)
            except Exception as e:
                logger.debug("叠加字幕和贴纸到预览帧失败: %s", e)
        try:
            pv_layout = self._preview_frame.layout()
            if isinstance(pv_layout, QStackedLayout):
                pv_layout.setCurrentWidget(gl)
        except Exception as e:
            logger.debug("切换预览布局至GL控件失败: %s", e)
        gl.show_frame(qimg, effects or {})

    def _gl_preview_ready(self) -> bool:
        gl = getattr(self, "_gl_widget", None)
        return gl is not None and bool(getattr(gl, "gl_ok", False))

    def _ensure_scheduler(self):
        """懒加载调度器"""
        if self._editor_scheduler is not None:
            return self._editor_scheduler
        try:
            from app.core.editor_scheduler import editor_scheduler as _scheduler
        except ImportError:
            from core.editor_scheduler import editor_scheduler as _scheduler
        self._editor_scheduler = _scheduler
        logger.info('✅ 双内核调度器已加载')
        return self._editor_scheduler
    
    def _ensure_project_manager(self):
        """懒加载项目管理器"""
        if self._project_manager is not None:
            return self._project_manager
        try:
            from app.core.project_manager import project_manager as _pm
        except ImportError:
            from core.project_manager import project_manager as _pm
        self._project_manager = _pm
        logger.info('✅ 项目管理系统已加载')
        return self._project_manager
    
    def _ensure_timeline_manager(self):
        """懒加载时间线管理器"""
        if self._timeline_manager is not None:
            return self._timeline_manager
        try:
            from app.core.timeline_manager import timeline_manager as _tm
        except ImportError:
            from core.timeline_manager import timeline_manager as _tm
        self._timeline_manager = _tm
        logger.info('✅ 时间线管理系统已加载')
        return self._timeline_manager
    
    def _ensure_effect_manager(self):
        """懒加载特效管理器"""
        if self._effect_manager is not None:
            return self._effect_manager
        try:
            from app.core.effect_manager import get_effect_manager as _gem
        except ImportError:
            from core.effect_manager import get_effect_manager as _gem
        self._effect_manager = _gem()
        logger.info('✅ 特效管理系统已加载')
        return self._effect_manager
    
    def _setup_ui(self):
        t0 = time.perf_counter()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)
        t_toolbar = time.perf_counter()
        
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setStyleSheet("QSplitter::handle { background-color: #1a1a1a; height: 4px; }")
        
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setStyleSheet("QSplitter::handle { background-color: #1a1a1a; width: 4px; }")
        # 存引用：Agent 面板的「⤢ 展开」需要临时调整右栏宽度（V4.34.1）
        self._top_splitter = top_splitter
        
        left_panel = self._create_left_panel()
        top_splitter.addWidget(left_panel)
        t_left = time.perf_counter()
        
        preview_panel = self._create_preview_panel()
        top_splitter.addWidget(preview_panel)
        t_preview = time.perf_counter()
        
        tools_panel = self._create_tools_panel()
        top_splitter.addWidget(tools_panel)
        t_tools = time.perf_counter()
        
        # 工具栏列 360（与 Agent 竖栏同宽，V4.40.50 统一 LibTV 档）
        top_splitter.setSizes([280, 790, 360])
        # 注：右栏宽度偏好的持久化已随 Agent 竖栏迁移到 _agent_dock_splitter
        main_splitter.addWidget(top_splitter)
        
        timeline_panel = self._create_timeline_panel()
        main_splitter.addWidget(timeline_panel)
        t_timeline = time.perf_counter()
        
        main_splitter.setCollapsible(0, False)
        main_splitter.setCollapsible(1, False)
        top_splitter.setMinimumHeight(200)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([450, 350])
        
        # V4.40.50：Agent 从工具栏 Tab 升级为最右侧独立竖栏（LibTV 档 360px，贯穿到底）
        layout.addWidget(self._build_agent_dock(main_splitter), 1)
        logger.info(
            "editor _setup_ui total=%.0fms (toolbar=%.0f left=%.0f preview=%.0f tools=%.0f timeline=%.0f)",
            (t_timeline - t0) * 1000,
            (t_toolbar - t0) * 1000,
            (t_left - t_toolbar) * 1000,
            (t_preview - t_left) * 1000,
            (t_tools - t_preview) * 1000,
            (t_timeline - t_tools) * 1000,
        )
    
    # [Mixin] 已迁移至 editor_ui_builder_mixin.py
    # [Mixin] 已迁移至 editor_ui_builder_mixin.py
    # [Mixin] 已迁移至 editor_ui_builder_mixin.py
    def _on_tools_tab_changed(self, index: int) -> None:
        """首次切到某工具 Tab 时再构造内容。"""
        if index < 0:
            return
        if index in getattr(self, "_tools_lazy_built", set()):
            return
        factories = getattr(self, "_tools_lazy_factories", None) or {}
        factory = factories.get(index)
        if factory is None:
            # 同步建好的「属性」等
            self._tools_lazy_built.add(index)
            return
        tabs = getattr(self, "_tools_tabs", None)
        if tabs is None:
            return
        holder = tabs.widget(index)
        if holder is None:
            return
        t0 = time.perf_counter()
        try:
            content = factory()
        except Exception as e:
            logger.exception("lazy tools tab failed idx=%s", index)
            tip = getattr(holder, "_lazy_tip", None)
            if tip is not None:
                tip.setText(f"加载失败: {e}")
            return
        lo = holder.layout()
        if lo is None:
            lo = QVBoxLayout(holder)
            lo.setContentsMargins(0, 0, 0, 0)
        # 清掉占位
        while lo.count():
            item = lo.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        lo.addWidget(content)
        self._tools_lazy_built.add(index)
        factories.pop(index, None)
        ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "editor tools tab lazy-built idx=%s title=%s in %.0fms",
            index,
            tabs.tabText(index),
            ms,
        )
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
        from app.modules.lego.editor_props_panel import build_props_panel_tab
        return build_props_panel_tab(self)

    def _make_bound_slider(self, mn, mx, dv=0, style_color="#1e6bde"):
        """创建可存引用的水平滑条（供调色/属性页接线）。"""
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(mn, mx)
        s.setValue(dv)
        s.setStyleSheet(
            f"QSlider::groove:horizontal{{background:#222;height:3px;border-radius:2px;}}"
            f"QSlider::handle:horizontal{{background:{style_color};width:10px;height:10px;"
            f"border-radius:5px;margin:-3px 0;}}"
        )
        return s

    def _make_color_tab(self):
        from app.modules.lego.editor_color_panel import build_color_panel_tab
        return build_color_panel_tab(self)

    # [Mixin] 已迁移至 editor_ui_builder_mixin.py
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

        from app.modules.lego.editor_subtitle_panel import build_subtitle_panel_section
        build_subtitle_panel_section(self, l)

        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0,0,0,0)
        o.addWidget(s)
        return t

    def _make_audio_tab(self):
        from app.modules.lego.editor_audio_panel import build_audio_panel_tab
        return build_audio_panel_tab(self)

    # [Mixin] 已迁移至 editor_ui_builder_mixin.py
    # [Mixin] 已迁移至 editor_ui_builder_mixin.py
    # [Mixin] 已迁移至 editor_ui_builder_mixin.py
    def _import_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.webm)"
        )
        if file_path:
            try:
                # ── 更新导入预览 ──
                self._update_import_preview(file_path)
                
                from app.core.local_asset_manager import local_asset_manager as _lam
                _asset = _lam.import_asset(file_path, category="videos")
                if _asset is None:
                    raise RuntimeError("素材导入失败")
                asset_info = _asset.to_dict()
                logger.info(f"导入素材成功: {asset_info['name']}")
                # _load_video → 加片 → 已 open + 刷首帧；勿再 force/open（会清空缓存+帧数探针）
                self._load_video(asset_info["path"])
                self._video_source = asset_info["path"]
                self._playhead_position = 0.0
                # 后台静默生成代理（预览用；导出仍用原片）
                try:
                    w = int(asset_info.get("width") or 0)
                    h = int(asset_info.get("height") or 0)
                    self._kick_proxy_for_path(asset_info["path"], width=w, height=h)
                except Exception as e:
                    logger.debug("导入后启动代理失败: %s", e)
                self._event_bus.emit(EventType.VIDEO_LOADED, {"path": asset_info["path"], "asset_id": asset_info["id"]})
            except Exception as e:
                QMessageBox.warning(self, "导入失败", f"导入视频失败: {str(e)}")
                logger.error(f'导入视频失败: {e}')

    def _update_import_preview(self, file_path):
        """更新导入栏素材预览（优先复用 PreviewManager 首帧，避免再起 ffmpeg 抢盘）。"""
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
            elif ext in ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v'):
                pixmap = None
                try:
                    pm = getattr(self, "_preview_manager", None) or self._ensure_preview_manager()
                    frame = None
                    if pm is not None and self._media_paths_equal(
                        getattr(pm, "_video_source", None), file_path
                    ):
                        if hasattr(pm, "get_first_frame"):
                            frame = pm.get_first_frame()
                        if frame is None:
                            frame = pm.get_frame_at(0.0)
                    if frame is not None:
                        if hasattr(frame, "copy") and hasattr(frame, "isNull"):
                            # QImage
                            if not frame.isNull():
                                pixmap = QPixmap.fromImage(frame)
                        elif hasattr(frame, "isNull"):
                            if not frame.isNull():
                                pixmap = frame if isinstance(frame, QPixmap) else QPixmap.fromImage(frame)
                except Exception as e:
                    logger.debug("导入预览复用 PM 失败: %s", e)
                if pixmap is not None and not pixmap.isNull():
                    scaled = pixmap.scaled(
                        self._import_preview_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                    self._import_preview_label.setPixmap(scaled)
                    self._import_preview_label.setText("")
                else:
                    # 轻量占位：不阻塞起 ffmpeg 子进程
                    name = os.path.basename(file_path)
                    try:
                        kb = os.path.getsize(file_path) // 1024
                    except Exception:
                        kb = 0
                    self._import_preview_label.setText(f"🎬 {name}\n{kb} KB")
            else:
                info = f"📁 {os.path.basename(file_path)}\n\n{os.path.getsize(file_path) // 1024} KB"
                self._import_preview_label.setText(info)
        except Exception as e:
            self._import_preview_label.setText(f"预览失败: {e}")

    def _on_preview_frame(self, qimage):
        """预览帧更新：统一走 GL（若可用）或 CPU label，避免两者抢 QStackedLayout。"""
        if qimage is None:
            return
        try:
            if hasattr(qimage, "isNull") and qimage.isNull():
                return
        except Exception:
            return
        if not hasattr(self, "_preview_label") or not hasattr(self, "_preview_frame"):
            return

        # GL 可用：滤镜在 shader；字幕/贴纸在 _show_frame_gl 内叠加
        if self._gl_preview_ready():
            effects = {}
            try:
                clip = getattr(self, "_current_clip", None)
                effects = dict(self._collect_preview_effects(clip) or {})
                effects = self._lighten_effects_for_playback(effects)
            except Exception:
                effects = {}
            self._show_frame_gl(qimage, effects)
            return

        # CPU：先落到工程画幅，再叠字幕/手柄
        # 播放中帧已由 _render_timeline_frame 落到 sequence 画幅 → 跳过二次 fit，减轻卡顿
        try:
            already_seq = bool(getattr(self, "_preview_frame_preletterboxed", False))
            self._preview_frame_preletterboxed = False
            if not (
                (getattr(self, "_timeline_playing", False) or getattr(self, "_preview_scrubbing", False))
                and already_seq
            ):
                qimage = self._fit_qimage_to_sequence(qimage)
            # scrub 跳过字幕/贴纸/手柄叠层（降载；松手高质量再刷）
            if not getattr(self, "_preview_scrubbing", False):
                qimage = self._overlay_subtitles_on_qimage(qimage)
            if not getattr(self, "_timeline_playing", False) and not getattr(
                self, "_preview_scrubbing", False
            ):
                qimage = self._overlay_stickers_on_qimage(qimage)
                qimage = self._overlay_transform_handles_on_qimage(qimage)
        except Exception as e:
            logger.error(f'字幕/贴纸叠加失败: {e}')
        self._present_preview_frame_cpu(qimage)

    def _present_preview_frame(self, qimage):
        """兼容旧调用：有 GL 则交给 GPU，否则 CPU letterbox。"""
        if qimage is None:
            return
        if self._gl_preview_ready():
            self._show_frame_gl(qimage, {})
            return
        self._present_preview_frame_cpu(qimage)

    def _present_preview_frame_cpu(self, qimage):
        """CPU 预览出口：按 SequenceFormat 画幅区域 + fit_mode 放置帧到 QLabel。"""
        if qimage is None or not hasattr(self, "_preview_label"):
            return
        try:
            if qimage.isNull():
                return
        except Exception:
            return
        try:
            pv_layout = self._preview_frame.layout() if hasattr(self, "_preview_frame") else None
            if isinstance(pv_layout, QStackedLayout):
                pv_layout.setCurrentWidget(self._preview_label)
        except Exception:
            logger.debug("预览布局切换失败", exc_info=True)

        sf = getattr(self, "_sequence_format", None) or SequenceFormat.default()
        frame = getattr(self, "_preview_frame", None)
        try:
            dst_w = max(1, int(frame.width()) if frame is not None else self._preview_label.width())
            dst_h = max(1, int(frame.height()) if frame is not None else self._preview_label.height())
        except Exception:
            dst_w, dst_h = 640, 360

        # 工程画幅在预览区内的目标矩形（序列 contain 进 label）
        _cx, _cy, canvas_w, canvas_h = fit_rect(
            max(1, int(sf.width)), max(1, int(sf.height)), dst_w, dst_h, "contain",
        )
        canvas_w = max(2, int(canvas_w))
        canvas_h = max(2, int(canvas_h))

        xform = (
            Qt.TransformationMode.FastTransformation
            if getattr(self, "_timeline_playing", False)
            else Qt.TransformationMode.SmoothTransformation
        )
        try:
            canvas = QImage(canvas_w, canvas_h, QImage.Format.Format_RGB32)
            canvas.fill(QColor(0, 0, 0))
            fx, fy, fw, fh = fit_rect(
                max(1, qimage.width()), max(1, qimage.height()),
                canvas_w, canvas_h, sf.fit_mode or "contain",
            )
            scaled = qimage.scaled(
                max(1, fw), max(1, fh),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                xform,
            )
            painter = QPainter(canvas)
            painter.setRenderHint(
                QPainter.RenderHint.SmoothPixmapTransform,
                not getattr(self, "_timeline_playing", False),
            )
            painter.drawImage(int(fx), int(fy), scaled)
            painter.end()
            pixmap = QPixmap.fromImage(canvas)
        except Exception as e:
            logger.debug("sequence letterbox 失败，回退 KeepAspectRatio: %s", e)
            pixmap = QPixmap.fromImage(qimage)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    dst_w, dst_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    xform,
                )

        if pixmap is None or pixmap.isNull():
            return
        # 再 fit 进 label（与 canvas 同比例时几乎 no-op；保持居中黑边）
        if pixmap.width() != dst_w or pixmap.height() != dst_h:
            pixmap = pixmap.scaled(
                dst_w, dst_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                xform,
            )
        self._preview_label.setPixmap(pixmap)
        self._preview_label.setText("")
        self._preview_label.show()

    def _overlay_subtitles_on_qimage(self, qimage):
        """在预览图上绘制当前时间轴字幕（样式/位置与 ASS 烧录对齐）。"""
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
            font_family = "Microsoft YaHei"
            bg = QColor(0, 0, 0, 150)
            try:
                style = sm.get_subtitle_style(sub.get("style", "default")) or {}
                font_size = int(style.get("font_size", 28) or 28)
                outline = int(
                    style.get("border_width", style.get("outline", style.get("stroke", 2))) or 2
                )
                font_family = str(style.get("font") or "Microsoft YaHei")
                font_family = font_family.replace("Arial Bold", "Arial")
                c = style.get("color") or style.get("font_color") or "#FFFFFF"
                if isinstance(c, str) and c.startswith("#") and len(c) >= 7:
                    text_color = QColor(c)
                bg_raw = str(style.get("background") or "#000000")
                op = float(style.get("opacity", 0.8) or 0.8)
                if bg_raw.lower() in ("transparent", "none", ""):
                    bg = QColor(0, 0, 0, 0)
                elif bg_raw.startswith("#") and len(bg_raw) >= 7:
                    bg = QColor(bg_raw)
                    bg.setAlpha(int(round(max(0.0, min(1.0, op)) * 255)))
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
            scaled = max(14, int(font_size * h / 1080))
            font = QFont(font_family, scaled)
            painter.setFont(font)
            fm = QFontMetrics(font)
            # 多行
            lines = text.split("\n")
            tw = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
            th = fm.height() * len(lines)
            x_ratio, y_ratio = 0.5, 0.85
            try:
                pos = sub.get("position") or {}
                x_ratio = float(pos.get("x", 0.5))
                y_ratio = float(pos.get("y", 0.85))
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
            x_ratio = min(0.98, max(0.02, x_ratio))
            y_ratio = min(0.95, max(0.05, y_ratio))
            cx = int(w * x_ratio) + int(sub.get("offset_x", 0) or 0)
            cy = int(h * y_ratio) + int(sub.get("offset_y", 0) or 0)

            # 动画：入场/出场（淡入淡出改 alpha；滑入滑出改位置偏移；缩放/旋转改绘制比例）
            anim_in = str(sub.get("anim_in") or "无")
            anim_out = str(sub.get("anim_out") or "无")
            anim_dur = max(0.05, float(sub.get("anim_duration_ms", 500) or 500) / 1000.0)
            st = float(sub.get("start_time", 0) or 0)
            et = float(sub.get("end_time", 0) or 0)
            t_in = t - st
            t_out = et - t
            alpha_mul = 1.0
            slide_off = (0, 0)
            scale_mul = 1.0
            rot_deg = 0.0
            slide_dirs = {
                "滑入上": (0, -1), "滑入下": (0, 1), "滑入左": (-1, 0), "滑入右": (1, 0),
                "滑出上": (0, -1), "滑出下": (0, 1), "滑出左": (-1, 0), "滑出右": (1, 0),
            }
            if t_in < anim_dur:
                ratio = max(0.0, min(1.0, t_in / anim_dur))
                if anim_in == "淡入":
                    alpha_mul = min(alpha_mul, ratio)
                elif anim_in in slide_dirs:
                    dx, dy = slide_dirs[anim_in]
                    slide_off = (int(dx * 80 * (1.0 - ratio)), int(dy * 80 * (1.0 - ratio)))
                elif anim_in == "缩放进入":
                    scale_mul = min(scale_mul, 0.2 + 0.8 * ratio)
                elif anim_in == "旋转进入":
                    rot_deg = -30.0 * (1.0 - ratio)
            if t_out < anim_dur and et > st:
                ratio = max(0.0, min(1.0, t_out / anim_dur))
                if anim_out == "淡出":
                    alpha_mul = min(alpha_mul, ratio)
                elif anim_out in slide_dirs:
                    dx, dy = slide_dirs[anim_out]
                    slide_off = (int(dx * 80 * (1.0 - ratio)), int(dy * 80 * (1.0 - ratio)))
                elif anim_out == "缩放退出":
                    scale_mul = min(scale_mul, 0.2 + 0.8 * ratio)
            cx += slide_off[0]
            cy += slide_off[1]

            x = cx - tw // 2
            y_top = cy - th // 2
            pad = 8

            painter.save()
            if alpha_mul < 0.999:
                painter.setOpacity(max(0.0, min(1.0, alpha_mul)))
            if abs(rot_deg) > 0.05 or scale_mul < 0.999:
                painter.translate(cx, cy)
                if abs(rot_deg) > 0.05:
                    painter.rotate(rot_deg)
                if scale_mul < 0.999:
                    painter.scale(scale_mul, scale_mul)
                painter.translate(-cx, -cy)

            if bg.alpha() > 0:
                painter.fillRect(x - pad, y_top - pad // 2, tw + pad * 2, th + pad, bg)

            shadow_kind = str(style.get("shadow", "无")) if isinstance(style, dict) else "无"
            if shadow_kind != "无":
                shadow_color = QColor(0, 0, 0, 200 if shadow_kind == "投影" else 130)
                shadow_dx, shadow_dy = (4, 4) if shadow_kind in ("投影", "硬边") else (2, 2)
                spread = 1 if shadow_kind != "发光" else 3
                painter.setPen(shadow_color)
                for i, ln in enumerate(lines):
                    lx = cx - fm.horizontalAdvance(ln) // 2
                    ly = y_top + fm.ascent() + i * fm.height()
                    if shadow_kind == "发光":
                        for gx, gy in ((-spread, 0), (spread, 0), (0, -spread), (0, spread)):
                            painter.drawText(lx + gx, ly + gy, ln)
                    else:
                        painter.drawText(lx + shadow_dx, ly + shadow_dy, ln)

            # 描边
            if outline > 0:
                painter.setPen(QColor(0, 0, 0))
                for i, ln in enumerate(lines):
                    lx = cx - fm.horizontalAdvance(ln) // 2
                    ly = y_top + fm.ascent() + i * fm.height()
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                        painter.drawText(lx + dx * max(1, outline // 2), ly + dy * max(1, outline // 2), ln)
            painter.setPen(text_color)
            for i, ln in enumerate(lines):
                lx = cx - fm.horizontalAdvance(ln) // 2
                ly = y_top + fm.ascent() + i * fm.height()
                painter.drawText(lx, ly, ln)
            painter.restore()
        painter.end()
        return img

    def _overlay_stickers_on_qimage(self, qimage):
        """在预览图上绘制工程贴纸（emoji / 自定义图片）。"""
        stickers = getattr(self, "_active_stickers", None) or []
        if not stickers or qimage is None or qimage.isNull():
            return qimage
        img = qimage.copy()
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = img.width(), img.height()
        t = float(getattr(self, "_playhead_position", 0) or 0)
        for stk in stickers:
            try:
                st = float(stk.get("start_time", 0) or 0)
                et = float(stk.get("end_time", 1e9) or 1e9)
                if t < st - 0.001 or t > et + 0.001:
                    continue
                x_ratio = float(stk.get("x", 50)) / 100.0
                y_ratio = float(stk.get("y", 50)) / 100.0
                size_pct = float(stk.get("size", 100) or 100)
                rot = float(stk.get("rotation", 0) or 0)
                opacity = float(stk.get("opacity", 1.0) or 1.0)
                if opacity > 1.0:
                    opacity = opacity / 100.0
                opacity = max(0.05, min(1.0, opacity))
                cx, cy = int(w * x_ratio), int(h * y_ratio)
                painter.save()
                painter.translate(cx, cy)
                painter.rotate(rot)
                painter.setOpacity(opacity)
                path = stk.get("path")
                if path and os.path.exists(path):
                    pm = QPixmap(path)
                    if not pm.isNull():
                        tw = max(16, int(w * 0.18 * size_pct / 100.0))
                        pm = pm.scaled(
                            tw, tw,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        painter.drawPixmap(-pm.width() // 2, -pm.height() // 2, pm)
                else:
                    emoji = str(stk.get("emoji") or "★")
                    base = max(20, int(h * 0.14 * size_pct / 100.0))
                    font = QFont("Segoe UI Emoji")
                    font.setPixelSize(base)
                    painter.setFont(font)
                    fm = QFontMetrics(font)
                    tw = fm.horizontalAdvance(emoji)
                    painter.setPen(QColor(255, 255, 255))
                    painter.drawText(-tw // 2, fm.ascent() // 2, emoji)
                painter.restore()
            except Exception as e:
                logger.warning("贴纸预览绘制失败: %s", e)
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
        """兼容旧入口 → 应用调色。"""
        self._apply_color_grading()

    def _sv(self, key: str, default: int = 0) -> int:
        from app.modules.lego.editor_color_panel import sv
        return sv(self, key, default)

    def _gather_color_params_from_ui(self) -> dict:
        from app.modules.lego.editor_color_panel import gather_color_params_from_ui
        return gather_color_params_from_ui(self)

    def _on_color_slider_live(self, *_args):
        from app.modules.lego.editor_color_panel import on_color_slider_live
        on_color_slider_live(self, *_args)

    def _apply_color_grading(self):
        from app.modules.lego.editor_color_panel import apply_color_grading
        return apply_color_grading(self)

    def _reset_color_grading(self):
        from app.modules.lego.editor_color_panel import reset_color_grading
        return reset_color_grading(self)

    def _apply_video_adjustments(self):
        """兼容旧调用 → 应用调色。"""
        self._apply_color_grading()

    def _reset_video_adjustments(self):
        """兼容旧调用 → 重置调色。"""
        self._reset_color_grading()

    def _property_target_clips(self):
        """属性/调色作用目标：多选优先，否则当前片。"""
        tw = getattr(self, "_timeline_widget", None)
        if tw is not None and hasattr(tw, "get_selected_clips"):
            try:
                sel = [c for c in (tw.get_selected_clips() or []) if isinstance(c, dict)]
                if sel:
                    return sel
            except Exception:
                logger.debug("选中项读取失败", exc_info=True)
        cur = getattr(self, "_current_clip", None)
        return [cur] if isinstance(cur, dict) else []

    def _on_clip_opacity_live(self, value: int):
        targets = self._property_target_clips()
        if not targets:
            return
        op = max(0.0, min(1.0, float(value) / 100.0))
        for clip in targets:
            effects = dict(clip.get("effects") or {}) if isinstance(clip.get("effects"), dict) else {}
            effects["opacity"] = op
            clip["opacity"] = op
            clip["effects"] = effects
            # 刀4：真相源字段写收敛 TimelineStore.set_fields（选区副本同步语义保留）
            self._timeline_store.set_fields(clip.get("id"), opacity=op, effects=effects)
        self._schedule_preview_refresh()

    def _on_clip_blend_mode_changed(self, mode_text: str):
        """属性页「混合」下拉：写入 clip["blend_mode"]（预览像素混合 + 导出 FFmpeg blend 滤镜）。"""
        targets = self._property_target_clips()
        if not targets:
            return
        mode = str(mode_text or "正常")
        for clip in targets:
            clip["blend_mode"] = mode
            # 刀4：字段写走 store API（live dict 原地 update，保读点同一性）
            self._timeline_store.set_fields(clip.get("id"), blend_mode=mode)
        self._schedule_preview_refresh()

    def _on_clip_crop_live(self, *_args):
        """属性页「裁剪上/下/左/右」：写入 clip["crop"]（源帧像素，预览+叠轨导出生效）。"""
        targets = self._property_target_clips()
        if not targets:
            return
        crop = {
            "top": int(self._crop_top.value()),
            "bottom": int(self._crop_bottom.value()),
            "left": int(self._crop_left.value()),
            "right": int(self._crop_right.value()),
        }
        for clip in targets:
            clip["crop"] = dict(crop)
            # 刀4：字段写走 store API
            self._timeline_store.set_fields(clip.get("id"), crop=dict(crop))
        self._schedule_preview_refresh()

    def _apply_sequence_format_to_preview(self):
        """画幅比例由帧内 letterbox / GL viewport 处理。

        不对 QStackedLayout 子控件 setGeometry：会与栈布局抢尺寸，导致 GL/Label
        错位、黑屏或露出占位文字（????）。
        """
        return

    def _preview_frame_size(self):
        """预览/属性页用的画幅尺寸（工程 SequenceFormat SSOT）。"""
        sf = getattr(self, "_sequence_format", None) or SequenceFormat.default()
        return max(1, int(sf.width)), max(1, int(sf.height))

    def _fit_qimage_to_sequence(self, qimage):
        """将任意源帧放到工程画幅画布上（contain 黑边 / cover 裁切），供预览与 GL 共用。"""
        if qimage is None:
            return qimage
        try:
            if qimage.isNull():
                return qimage
        except Exception:
            return qimage
        sf = getattr(self, "_sequence_format", None) or SequenceFormat.default()
        cw = max(2, int(sf.width))
        ch = max(2, int(sf.height))
        try:
            if int(qimage.width()) == cw and int(qimage.height()) == ch:
                return qimage
        except Exception:
            logger.debug("图像尺寸判断失败", exc_info=True)
        xform = (
            Qt.TransformationMode.FastTransformation
            if getattr(self, "_timeline_playing", False)
            else Qt.TransformationMode.SmoothTransformation
        )
        canvas = QImage(cw, ch, QImage.Format.Format_RGB32)
        canvas.fill(QColor(0, 0, 0))
        fx, fy, fw, fh = fit_rect(
            max(1, int(qimage.width())), max(1, int(qimage.height())),
            cw, ch, sf.fit_mode or "contain",
        )
        scaled = qimage.scaled(
            max(1, int(fw)), max(1, int(fh)),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            xform,
        )
        painter = QPainter(canvas)
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            not getattr(self, "_timeline_playing", False),
        )
        painter.drawImage(int(fx), int(fy), scaled)
        painter.end()
        return canvas

    def _place_bgr_on_sequence_canvas(self, arr, canvas=None):
        """把 BGR ndarray 按 fit_mode 放到工程画幅画布（float32）；供多轨合成底图。"""
        import numpy as np
        import cv2
        sf = getattr(self, "_sequence_format", None) or SequenceFormat.default()
        cw = max(2, int(sf.width))
        ch = max(2, int(sf.height))
        if canvas is None:
            canvas = np.zeros((ch, cw, 3), dtype=np.float32)
        else:
            canvas = canvas.astype(np.float32, copy=False)
            ch, cw = int(canvas.shape[0]), int(canvas.shape[1])
        if arr is None:
            return canvas
        sh, sw = int(arr.shape[0]), int(arr.shape[1])
        if sh < 1 or sw < 1:
            return canvas
        fx, fy, fw, fh = fit_rect(sw, sh, cw, ch, sf.fit_mode or "contain")
        fw, fh = max(1, int(fw)), max(1, int(fh))
        resized = cv2.resize(arr, (fw, fh), interpolation=cv2.INTER_LINEAR)
        dx0 = max(0, int(fx))
        dy0 = max(0, int(fy))
        dx1 = min(cw, int(fx) + fw)
        dy1 = min(ch, int(fy) + fh)
        if dx1 <= dx0 or dy1 <= dy0:
            return canvas
        sx0 = dx0 - int(fx)
        sy0 = dy0 - int(fy)
        sx1 = sx0 + (dx1 - dx0)
        sy1 = sy0 + (dy1 - dy0)
        canvas[dy0:dy1, dx0:dx1] = resized[sy0:sy1, sx0:sx1].astype(np.float32)
        return canvas

    def _infer_sequence_from_clips(self) -> bool:
        """旧工程无 sequence：用首个视频片像素推断画幅。成功返回 True。"""
        for c in getattr(self, "_clips", []) or []:
            if not isinstance(c, dict):
                continue
            if str(c.get("type", "")).lower() == "audio":
                continue
            path = c.get("path")
            w = int(c.get("width") or c.get("video_width") or 0)
            h = int(c.get("height") or c.get("video_height") or 0)
            if (w <= 0 or h <= 0) and path and os.path.exists(str(path)):
                try:
                    from app.modules.lego.video_processor import get_video_info
                    info = get_video_info(str(path))
                    if info is not None:
                        w = int(getattr(info, "width", 0) or 0)
                        h = int(getattr(info, "height", 0) or 0)
                except Exception:
                    w = h = 0
                if w <= 0 or h <= 0:
                    try:
                        from app.modules.lego.professional_video_engine import FFmpegUtils
                        info = FFmpegUtils.get_video_info(str(path))
                        if info is not None:
                            w = int(getattr(info, "width", 0) or 0)
                            h = int(getattr(info, "height", 0) or 0)
                    except Exception:
                        w = h = 0
                if w <= 0 or h <= 0:
                    try:
                        pm = self._ensure_preview_manager()
                        if pm.open_video(str(path)):
                            w = int(getattr(pm, "_video_width", 0) or 0)
                            h = int(getattr(pm, "_video_height", 0) or 0)
                    except Exception:
                        continue
            if w <= 0 or h <= 0:
                continue
            aspect = aspect_from_size(w, h)
            nw, nh = normalize_size(aspect, w, h)
            self._sequence_format = SequenceFormat(
                aspect=aspect, width=nw, height=nh, fit_mode="contain",
            )
            return True
        return False

    def _preview_content_rect(self):
        """预览 label 内实际画面矩形（扣除信箱黑边）。"""
        lbl = getattr(self, "_preview_label", None)
        if lbl is None:
            return 0, 0, 1, 1
        pm = lbl.pixmap()
        lw = max(1, lbl.width())
        lh = max(1, lbl.height())
        if pm is None or pm.isNull():
            return 0, 0, lw, lh
        pw, ph = pm.width(), pm.height()
        x0 = (lw - pw) // 2
        y0 = (lh - ph) // 2
        return int(x0), int(y0), max(1, int(pw)), max(1, int(ph))

    def _preview_norm_from_pos(self, pos):
        """鼠标位置 → 画面归一化坐标 (nx, ny) 与是否落在画面内。"""
        x0, y0, pw, ph = self._preview_content_rect()
        try:
            px = float(pos.x())
            py = float(pos.y())
        except Exception:
            px = float(pos.x())
            py = float(pos.y())
        nx = (px - x0) / float(pw)
        ny = (py - y0) / float(ph)
        inside = 0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0
        return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny)), inside

    @staticmethod
    def _clip_box_norm(tf):
        """根据归一化 transform 估算叠层窗 [left, top, right, bottom, cx, cy]。"""
        sc = max(0.05, min(2.0, float(tf.get("scale", 1.0) or 1.0)))
        x = float(tf.get("x", 0.5) or 0.5)
        y = float(tf.get("y", 0.5) or 0.5)
        left = (1.0 - sc) * x
        top = (1.0 - sc) * y
        right = left + sc
        bottom = top + sc
        return left, top, right, bottom, (left + right) * 0.5, (top + bottom) * 0.5

    def _hit_preview_transform_mode(self, nx, ny, tf, alt=False):
        """命中：scale / rotate / move。"""
        if alt:
            return "rotate"
        left, top, right, bottom, _cx, _cy = self._clip_box_norm(tf)
        corner_r2 = 0.012
        edge_t = 0.025
        for cx0, cy0 in ((left, top), (right, top), (left, bottom), (right, bottom)):
            if (nx - cx0) ** 2 + (ny - cy0) ** 2 <= corner_r2:
                return "scale"
        on_edge = (
            (abs(nx - left) <= edge_t and top - edge_t <= ny <= bottom + edge_t)
            or (abs(nx - right) <= edge_t and top - edge_t <= ny <= bottom + edge_t)
            or (abs(ny - top) <= edge_t and left - edge_t <= nx <= right + edge_t)
            or (abs(ny - bottom) <= edge_t and left - edge_t <= nx <= right + edge_t)
        )
        if on_edge:
            return "scale"
        return "move"

    def _overlay_transform_handles_on_qimage(self, qimage):
        """在预览上画选中片段的变换框 + 四角把手（暂停时）。"""
        if getattr(self, "_timeline_playing", False):
            return qimage
        clip = getattr(self, "_current_clip", None)
        if not clip or self._is_export_audio_clip(clip):
            return qimage
        try:
            from app.modules.lego.clip_transform import normalize_clip_transform
            from PyQt6.QtCore import QRectF
        except Exception:
            return qimage
        w, h = qimage.width(), qimage.height()
        if w < 8 or h < 8:
            return qimage
        tf = normalize_clip_transform(clip, w, h, {"x": 0.5, "y": 0.5, "scale": 1.0})
        left, top, right, bottom, _cx, _cy = self._clip_box_norm(tf)
        img = qimage.copy()
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(30, 107, 222, 220))
        pen.setWidth(max(2, int(min(w, h) * 0.003)))
        painter.setPen(pen)
        rect = QRectF(left * w, top * h, (right - left) * w, (bottom - top) * h)
        painter.drawRect(rect)
        rot = float(tf.get("rotation", 0) or 0)
        hs = max(4.0, min(w, h) * 0.012)
        painter.setBrush(QBrush(QColor(30, 107, 222, 240)))
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
        for hx, hy in ((left, top), (right, top), (left, bottom), (right, bottom)):
            painter.drawRect(QRectF(hx * w - hs, hy * h - hs, hs * 2, hs * 2))
        if abs(rot) > 0.5:
            painter.setPen(QPen(QColor(245, 158, 11, 200), 1))
            painter.drawText(int(rect.left()) + 4, max(12, int(rect.top()) - 6), f"{rot:.0f}°")
        painter.end()
        return img

    def _apply_preview_transform_to_clip(self, clip, *, x=None, y=None, scale=None, rotation=None):
        fw, fh = self._preview_frame_size()
        try:
            from app.modules.lego.clip_transform import apply_normalized_transform
        except Exception:
            from app.modules.lego.video_processor import apply_normalized_transform
        kwargs = {"frame_w": fw, "frame_h": fh}
        if x is not None:
            kwargs["x"] = x
        if y is not None:
            kwargs["y"] = y
        if scale is not None:
            kwargs["scale"] = scale
        if rotation is not None:
            kwargs["rotation"] = rotation
        apply_normalized_transform(clip, **kwargs)
        for c in getattr(self, "_clips", []) or []:
            if c.get("id") == clip.get("id"):
                apply_normalized_transform(c, **kwargs)
                break
        try:
            from app.modules.lego.clip_transform import normalize_clip_transform
            tf = normalize_clip_transform(clip, fw, fh)
        except Exception:
            tf = {"x": x or 0.5, "y": y or 0.5, "scale": scale or 1.0, "rotation": rotation or 0.0}
        if x is not None or y is not None:
            if hasattr(self, "_clip_pos_x") and self._clip_pos_x:
                self._clip_pos_x.blockSignals(True)
                self._clip_pos_y.blockSignals(True)
                self._clip_pos_x.setValue(int(round((float(tf["x"]) - 0.5) * fw)))
                self._clip_pos_y.setValue(int(round((float(tf["y"]) - 0.5) * fh)))
                self._clip_pos_x.blockSignals(False)
                self._clip_pos_y.blockSignals(False)
            self._sync_pip_sliders_values(float(tf["x"]), float(tf["y"]), float(tf.get("scale", 1.0)))
        if scale is not None and hasattr(self, "_clip_scale_slider") and self._clip_scale_slider:
            self._clip_scale_slider.blockSignals(True)
            self._clip_scale_slider.setValue(int(round(float(tf["scale"]) * 100)))
            self._clip_scale_slider.blockSignals(False)
            self._sync_pip_sliders_values(float(tf["x"]), float(tf["y"]), float(tf["scale"]))
        if rotation is not None and hasattr(self, "_clip_rot_slider") and self._clip_rot_slider:
            self._clip_rot_slider.blockSignals(True)
            self._clip_rot_slider.setValue(int(round(float(tf.get("rotation", 0) or 0))))
            self._clip_rot_slider.blockSignals(False)

    def eventFilter(self, obj, event):
        """预览区：边角缩放 / Alt 旋转 / 中心平移；Ctrl+滚轮缩放；画幅自适应。"""
        try:
            # ── 画幅自适应：preview_frame resize → 让 preview_label 按 SequenceFormat 居中 ──
            if obj is getattr(self, "_preview_frame", None):
                if event.type() == QEvent.Type.Resize:
                    self._apply_sequence_format_to_preview()
                    return False
            if obj is getattr(self, "_preview_label", None):
                et = event.type()
                if et == QEvent.Type.Wheel:
                    mods = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
                    if mods & Qt.KeyboardModifier.ControlModifier:
                        clip = getattr(self, "_current_clip", None)
                        if clip and not self._is_export_audio_clip(clip):
                            try:
                                from app.modules.lego.clip_transform import normalize_clip_transform
                                fw, fh = self._preview_frame_size()
                                tf0 = normalize_clip_transform(
                                    clip, fw, fh, {"x": 0.5, "y": 0.5, "scale": 1.0}
                                )
                                delta = event.angleDelta().y() if hasattr(event, "angleDelta") else 0
                                step = 0.05 if delta > 0 else -0.05
                                nsc = max(0.05, min(2.0, float(tf0.get("scale", 1.0)) + step))
                                self._apply_preview_transform_to_clip(clip, scale=nsc)
                                self._schedule_preview_refresh()
                                self._notify_edit(f"缩放 {int(nsc * 100)}%")
                            except Exception as e:
                                print(f"预览滚轮缩放失败: {e}")
                            return True
                if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    clip = getattr(self, "_current_clip", None)
                    if clip and not self._is_export_audio_clip(clip):
                        fw, fh = self._preview_frame_size()
                        try:
                            from app.modules.lego.clip_transform import normalize_clip_transform
                        except Exception:
                            from app.modules.lego.video_processor import normalize_clip_transform
                        pos = event.position() if hasattr(event, "position") else event.pos()
                        nx, ny, _inside = self._preview_norm_from_pos(pos)
                        tf0 = normalize_clip_transform(
                            clip, fw, fh, {"x": 0.5, "y": 0.5, "scale": 1.0}
                        )
                        mods = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
                        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
                        mode = self._hit_preview_transform_mode(nx, ny, tf0, alt=alt)
                        self._preview_drag_active = True
                        self._preview_drag_mode = mode
                        self._preview_drag_origin = pos
                        self._preview_drag_tf0 = tf0
                        import math
                        _l, _t, _r, _b, cx, cy = self._clip_box_norm(tf0)
                        self._preview_drag_angle0 = math.degrees(math.atan2(ny - cy, nx - cx))
                        self._preview_drag_dist0 = max(1e-4, math.hypot(nx - cx, ny - cy))
                        return True
                elif et == QEvent.Type.MouseMove and getattr(self, "_preview_drag_active", False):
                    clip = getattr(self, "_current_clip", None)
                    origin = getattr(self, "_preview_drag_origin", None)
                    tf0 = getattr(self, "_preview_drag_tf0", None)
                    mode = getattr(self, "_preview_drag_mode", "move")
                    if clip and origin is not None and tf0 is not None:
                        pos = event.position() if hasattr(event, "position") else event.pos()
                        nx, ny, _ = self._preview_norm_from_pos(pos)
                        ox, oy, _ = self._preview_norm_from_pos(origin)
                        if mode == "rotate":
                            import math
                            _l, _t, _r, _b, cx, cy = self._clip_box_norm(tf0)
                            ang = math.degrees(math.atan2(ny - cy, nx - cx))
                            drot = ang - float(getattr(self, "_preview_drag_angle0", ang))
                            nrot = float(tf0.get("rotation", 0) or 0) + drot
                            while nrot > 180:
                                nrot -= 360
                            while nrot < -180:
                                nrot += 360
                            self._apply_preview_transform_to_clip(clip, rotation=nrot)
                        elif mode == "scale":
                            import math
                            _l, _t, _r, _b, cx, cy = self._clip_box_norm(tf0)
                            dist = max(1e-4, math.hypot(nx - cx, ny - cy))
                            ratio = dist / float(getattr(self, "_preview_drag_dist0", dist) or dist)
                            nsc = max(0.05, min(2.0, float(tf0.get("scale", 1.0) or 1.0) * ratio))
                            self._apply_preview_transform_to_clip(clip, scale=nsc)
                        else:
                            dx = nx - ox
                            dy = ny - oy
                            nnx = max(0.0, min(1.0, float(tf0["x"]) + dx))
                            nny = max(0.0, min(1.0, float(tf0["y"]) + dy))
                            self._apply_preview_transform_to_clip(clip, x=nnx, y=nny)
                        self._schedule_preview_refresh()
                    return True
                elif et == QEvent.Type.MouseButtonRelease and getattr(self, "_preview_drag_active", False):
                    mode = getattr(self, "_preview_drag_mode", "move")
                    self._preview_drag_active = False
                    self._preview_drag_origin = None
                    self._preview_drag_tf0 = None
                    self._preview_drag_mode = "move"
                    msg = {
                        "rotate": "已调整画面旋转",
                        "scale": "已调整画面缩放",
                    }.get(mode, "已调整画面位置")
                    self._notify_edit(msg)
                    return True
        except Exception as e:
            print(f"预览拖拽失败: {e}")
        return super().eventFilter(obj, event)

    def _on_clip_transform_live(self, *_args):
        clip = getattr(self, "_current_clip", None)
        if not clip:
            return
        scale = 1.0
        try:
            scale = max(0.05, min(2.0, float(self._clip_scale_slider.value()) / 100.0))
        except Exception as e:
            logger.debug("读取片段缩放值失败: %s", e)
        rot = 0
        try:
            rot = int(self._clip_rot_slider.value())
        except Exception as e:
            logger.debug("读取片段旋转值失败: %s", e)
        px = py = 0
        try:
            px = int(self._clip_pos_x.value())
            py = int(self._clip_pos_y.value())
        except Exception as e:
            logger.debug("读取片段位置值失败: %s", e)
        anchor = "中心"
        try:
            if hasattr(self, "_clip_anchor") and self._clip_anchor:
                anchor = self._clip_anchor.currentText() or "中心"
        except Exception as e:
            logger.debug("读取片段锚点失败: %s", e)
        fw, fh = self._preview_frame_size()
        nx = max(0.0, min(1.0, px / float(fw) + 0.5))
        ny = max(0.0, min(1.0, py / float(fh) + 0.5))
        try:
            from app.modules.lego.clip_transform import apply_normalized_transform
        except Exception:
            from app.modules.lego.video_processor import apply_normalized_transform
        apply_normalized_transform(
            clip, x=nx, y=ny, scale=scale, rotation=rot, anchor=anchor,
            frame_w=fw, frame_h=fh,
        )
        for c in getattr(self, "_clips", []) or []:
            if c.get("id") == clip.get("id"):
                apply_normalized_transform(
                    c, x=nx, y=ny, scale=scale, rotation=rot, anchor=anchor,
                    frame_w=fw, frame_h=fh,
                )
                break
        self._sync_pip_sliders_values(nx, ny, scale)
        self._schedule_preview_refresh()

    def _on_pip_transform_live(self, *_args):
        """画中画滑条：写入当前选中片段的归一化变换并刷新预览。"""
        clip = getattr(self, "_current_clip", None)
        if not clip:
            return
        try:
            nx = float(self._pip_x.value()) / 100.0
            ny = float(self._pip_y.value()) / 100.0
            ns = max(0.05, min(2.0, float(self._pip_size.value()) / 100.0))
        except Exception:
            return
        fw, fh = self._preview_frame_size()
        try:
            from app.modules.lego.video_processor import apply_normalized_transform
        except Exception:
            from modules.lego.video_processor import apply_normalized_transform
        apply_normalized_transform(
            clip, x=nx, y=ny, scale=ns, frame_w=fw, frame_h=fh
        )
        for c in getattr(self, "_clips", []) or []:
            if c.get("id") == clip.get("id"):
                apply_normalized_transform(
                    c, x=nx, y=ny, scale=ns, frame_w=fw, frame_h=fh
                )
                break
        if hasattr(self, "_clip_pos_x") and self._clip_pos_x:
            self._clip_pos_x.blockSignals(True)
            self._clip_pos_y.blockSignals(True)
            self._clip_scale_slider.blockSignals(True)
            self._clip_pos_x.setValue(int(round((nx - 0.5) * fw)))
            self._clip_pos_y.setValue(int(round((ny - 0.5) * fh)))
            self._clip_scale_slider.setValue(int(round(ns * 100)))
            self._clip_pos_x.blockSignals(False)
            self._clip_pos_y.blockSignals(False)
            self._clip_scale_slider.blockSignals(False)
        self._schedule_preview_refresh()

    def _sync_pip_sliders_values(self, nx, ny, scale):
        for attr, val in (("_pip_x", nx), ("_pip_y", ny), ("_pip_size", scale)):
            w = getattr(self, attr, None)
            if w is None:
                continue
            w.blockSignals(True)
            try:
                w.setValue(int(round(float(val) * 100)))
            except Exception as e:
                logger.debug("同步滑块值失败: %s", e)
            w.blockSignals(False)

    def _sync_pro_sliders_from_clip(self, clip_data):
        """选中片段时同步属性页不透明度/缩放/位置/画中画。"""
        if not clip_data:
            return
        fw, fh = self._preview_frame_size()
        try:
            from app.modules.lego.video_processor import normalize_clip_transform
        except Exception:
            from modules.lego.video_processor import normalize_clip_transform
        track_i = int(clip_data.get("track", 0) or 0)
        video_tracks = [
            int(c.get("track", 0) or 0)
            for c in (getattr(self, "_clips", []) or [])
            if not self._is_export_audio_clip(c)
        ]
        base_track = min(video_tracks) if video_tracks else 0
        defaults = {"x": 0.5, "y": 0.5, "scale": 1.0, "opacity": 1.0}
        if track_i > base_track:
            defaults = {"x": 0.75, "y": 0.80, "scale": 0.35, "opacity": 1.0}
        tf = normalize_clip_transform(clip_data, fw, fh, defaults)
        op = tf["opacity"]
        scale = tf["scale"]
        if hasattr(self, "_clip_opacity_slider") and self._clip_opacity_slider:
            self._clip_opacity_slider.blockSignals(True)
            self._clip_opacity_slider.setValue(int(round(op * 100)))
            self._clip_opacity_slider.blockSignals(False)
        if hasattr(self, "_clip_scale_slider") and self._clip_scale_slider:
            self._clip_scale_slider.blockSignals(True)
            self._clip_scale_slider.setValue(int(round(scale * 100)))
            self._clip_scale_slider.blockSignals(False)
        if hasattr(self, "_clip_pos_x") and self._clip_pos_x:
            self._clip_pos_x.blockSignals(True)
            self._clip_pos_y.blockSignals(True)
            self._clip_pos_x.setValue(int(round((tf["x"] - 0.5) * fw)))
            self._clip_pos_y.setValue(int(round((tf["y"] - 0.5) * fh)))
            self._clip_pos_x.blockSignals(False)
            self._clip_pos_y.blockSignals(False)
        self._sync_pip_sliders_values(tf["x"], tf["y"], scale)
        rot = int(tf.get("rotation", clip_data.get("rotation", 0)) or 0)
        if hasattr(self, "_clip_rot_slider") and self._clip_rot_slider:
            self._clip_rot_slider.blockSignals(True)
            self._clip_rot_slider.setValue(rot)
            self._clip_rot_slider.blockSignals(False)
        if hasattr(self, "_clip_anchor") and self._clip_anchor:
            anchor = str(tf.get("anchor") or clip_data.get("anchor") or "中心")
            idx = self._clip_anchor.findText(anchor)
            self._clip_anchor.blockSignals(True)
            if idx >= 0:
                self._clip_anchor.setCurrentIndex(idx)
            self._clip_anchor.blockSignals(False)
        if hasattr(self, "_blend_mode") and self._blend_mode:
            mode = str(clip_data.get("blend_mode") or "正常")
            idx = self._blend_mode.findText(mode)
            self._blend_mode.blockSignals(True)
            self._blend_mode.setCurrentIndex(idx if idx >= 0 else 0)
            self._blend_mode.blockSignals(False)
        crop = clip_data.get("crop") if isinstance(clip_data.get("crop"), dict) else {}
        for attr, key in (
            ("_crop_top", "top"), ("_crop_bottom", "bottom"),
            ("_crop_left", "left"), ("_crop_right", "right"),
        ):
            w = getattr(self, attr, None)
            if w is None:
                continue
            w.blockSignals(True)
            try:
                w.setValue(int(crop.get(key, 0) or 0))
            except Exception:
                w.setValue(0)
            w.blockSignals(False)

    def _refresh_export_project_info(self):
        """刷新导出页项目信息。"""
        try:
            clips = getattr(self, "_clips", []) or []
            dur = 0.0
            for c in clips:
                if self._is_export_audio_clip(c):
                    continue
                st = float(c.get("start_time", 0) or 0)
                d = float(c.get("duration", 0) or 0)
                dur = max(dur, st + d)
            res = "--"
            sf = getattr(self, "_sequence_format", None)
            if sf is not None:
                res = sf.resolution_str()
            elif hasattr(self, "_resolution_var") and self._resolution_var:
                res = self._resolution_var.currentText()
            if hasattr(self, "_proj_res_label") and self._proj_res_label:
                self._proj_res_label.setText(f"分辨率: {res}")
            if hasattr(self, "_proj_dur_label") and self._proj_dur_label:
                m, s = divmod(int(dur), 60)
                self._proj_dur_label.setText(f"时长: {m:02d}:{s:02d}")
            if hasattr(self, "_proj_size_label") and self._proj_size_label:
                # 粗估：bitrate * duration
                br = "3000k"
                if hasattr(self, "_bitrate_var") and self._bitrate_var:
                    br = self._bitrate_var.currentText()
                try:
                    kbps = float(br.replace("k", "").replace("K", "").replace("M", "000"))
                    mb = kbps / 8.0 * max(dur, 1.0) / 1024.0
                    self._proj_size_label.setText(f"预估: ~{mb:.1f} MB")
                except Exception:
                    self._proj_size_label.setText("预估: --")
        except Exception as e:
            logger.error(f'刷新导出信息失败: {e}')


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
        # 勿写中文占位到 label（缺字体会显示 ????）；有帧后再刷新
        try:
            self._preview_label.setText("")
        except Exception:
            logger.debug("预览标签清空失败", exc_info=True)
        
        # 使用QMediaPlayer加载视频（主要用于音频）
        media_content = QUrl.fromLocalFile(file_path)
        self._media_player.setSource(media_content)
        
        # 信号只连接一次，避免重复导入后回调叠加
        self._ensure_media_signals()
        self._ensure_media_audio_output()
        
        # 先加片（时长探测可轻量 open）；再统一 open+首帧，避免 import 路径多次关开 capture
        logger.info(f'加载视频: {file_path}')
        self._suppress_add_clip_preview = True
        try:
            self._add_clip_to_timeline(file_path)
        finally:
            self._suppress_add_clip_preview = False
        try:
            preview_manager = self._ensure_preview_manager()
            # 同文件已由时长探测打开则复用；否则完整 open 一次（含帧数校正）
            if self._ensure_preview_source_open(
                preview_manager, file_path, for_scrub=False, preload=False
            ):
                self._preview_source_path = file_path
                initial_frame = None
                if hasattr(preview_manager, "get_first_frame"):
                    initial_frame = preview_manager.get_first_frame()
                if initial_frame is None:
                    initial_frame = preview_manager.get_frame_at(0.0)
                if initial_frame is not None and not (
                    hasattr(initial_frame, "isNull") and initial_frame.isNull()
                ):
                    self._on_preview_frame(initial_frame)
                    logger.info(f'PreviewManager成功加载视频: {file_path}')
                else:
                    self._force_show_first_video_frame()
            else:
                self._force_show_first_video_frame()
        except Exception as e:
            logger.error(f'PreviewManager加载视频失败: {e}')
            try:
                self._force_show_first_video_frame()
            except Exception:
                logger.debug("首帧显示失败", exc_info=True)
    
    
    
    def _on_clip_selected(self, clip_data):
        """选区变化；None = 清空（时间线空白/取消多选）。"""
        self._current_clip = clip_data
        if not clip_data:
            return
        logger.info(f"选择片段: {clip_data.get('id')}")
        self._sync_volume_slider_from_clip(clip_data)
        self._sync_pro_sliders_from_clip(clip_data)
        self._refresh_export_project_info()
        # 点选只刷预览，不拽播放头到片头
        self._refresh_preview_to_current_clip(jump_playhead=False)

    def _sync_volume_slider_from_clip(self, clip_data):
        """选中片段时把音量滑条同步到 clip.volume。"""
        slider = getattr(self, "_clip_volume_slider", None)
        if slider is None or not clip_data:
            return
        vol_pct = int(round(float(clip_data.get("volume", 1.0) or 1.0) * 100))
        vol_pct = max(0, min(200, vol_pct))
        slider.blockSignals(True)
        slider.setValue(vol_pct)
        slider.blockSignals(False)

    def _on_timeline_track_volume(self, track, volume):
        """时间线轨音量变化 → 立刻按当前/顶层片刷新输出音量。"""
        self._touch_project_dirty()
        clip = getattr(self, "_current_clip", None)
        if clip is None and getattr(self, "_clips", None):
            # 尝试用该轨上最近播放头下的片
            ti = None
            tw = getattr(self, "_timeline_widget", None)
            if tw and track in getattr(tw, "_tracks", []):
                ti = tw._tracks.index(track)
            t = float(getattr(self, "_playhead_position", 0) or 0)
            for c in self._clips:
                if ti is not None and int(c.get("track", 0) or 0) != ti:
                    continue
                st = float(c.get("start_time", 0) or 0)
                dur = float(c.get("duration", 0) or 0)
                if st <= t < st + dur:
                    clip = c
                    break
        if not clip:
            return
        clip_vol = float(clip.get("volume", 1.0) or 1.0)
        master = float(getattr(self, "_master_volume", 1.0) or 1.0)
        out = max(0.0, min(1.0, clip_vol * master * float(volume)))
        try:
            if getattr(self, "_audio_output", None):
                self._audio_output.setVolume(out)
            if getattr(self, "_bgm_audio_output", None) and self._looks_like_audio_clip(clip):
                self._bgm_audio_output.setVolume(out)
        except Exception as _e:
            logger.warning("轨音量即时应用失败: %s", _e)
        self._notify_edit(f"轨音量 {int(float(volume) * 100)}%")

    def _on_clip_volume_live(self, value: int):
        """拖动时即时听感，不入撤销栈（多选同步写 volume）。"""
        targets = self._property_target_clips()
        if not targets:
            return
        vol = max(0.0, float(value) / 100.0)
        for clip in targets:
            clip["volume"] = vol
            cid = clip.get("id")
            # 刀4：真相源字段写走 store API
            self._timeline_store.set_fields(cid, volume=vol)
        clip = targets[0]
        master = float(getattr(self, "_master_volume", 1.0) or 1.0)
        track_vol = self._track_volume_for_clip(clip)
        out = max(0.0, min(1.0, vol * master * track_vol))
        try:
            if getattr(self, "_audio_output", None):
                self._audio_output.setVolume(out)
            if getattr(self, "_bgm_audio_output", None) and self._looks_like_audio_clip(clip):
                self._bgm_audio_output.setVolume(out)
        except Exception as _e:
            logger.warning("片段音量即时应用失败: %s", _e)

    def _on_clip_volume_committed(self):
        """松手写入撤销栈（多选 → compound）。"""
        targets = self._property_target_clips()
        slider = getattr(self, "_clip_volume_slider", None)
        if not targets or slider is None:
            return
        vol = max(0.0, float(slider.value()) / 100.0)
        before_map = getattr(self, "_clip_volume_before_drag_map", None) or {}
        steps = []
        for clip in targets:
            cid = clip.get("id")
            before_vol = float(before_map.get(cid, clip.get("volume", 1.0)) or 1.0)
            clip["volume"] = vol
            # 刀4：真相源字段写走 store API
            self._timeline_store.set_fields(cid, volume=vol)
            if abs(before_vol - vol) >= 0.005:
                steps.append({
                    "type": "edit_clip",
                    "clip_id": cid,
                    "before": {"volume": before_vol},
                    "after": {"volume": vol},
                })
        if len(steps) == 1:
            self._record_action(steps[0])
        elif steps:
            self._record_action({"type": "compound", "steps": steps, "label": "batch_volume"})
        self._touch_project_dirty()
        n = len(targets)
        self._notify_edit(
            f"片段音量 {int(vol * 100)}%" if n <= 1 else f"{n} 个片段音量 {int(vol * 100)}%"
        )

    def _on_clip_volume_pressed(self):
        targets = self._property_target_clips()
        self._clip_volume_before_drag_map = {
            c.get("id"): float(c.get("volume", 1.0) or 1.0) for c in targets if c.get("id")
        }
        clip = getattr(self, "_current_clip", None)
        self._clip_volume_before_drag = float((clip or {}).get("volume", 1.0) or 1.0)

    def _looks_like_audio_clip(self, clip) -> bool:
        if not clip:
            return False
        if clip.get("type") == "audio":
            return True
        path = str(clip.get("path") or "").lower()
        return path.endswith((".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg"))

    def _track_volume_for_clip(self, clip) -> float:
        """读取时间线轨道音量（默认 1.0）。"""
        if not clip:
            return 1.0
        tw = getattr(self, "_timeline_widget", None)
        if tw is None:
            return 1.0
        ti = int(clip.get("track", 0) or 0)
        tracks = getattr(tw, "_tracks", None) or []
        if 0 <= ti < len(tracks):
            return float(tracks[ti].get("volume", 1.0) or 1.0)
        return 1.0
    
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

        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            if status == QMediaPlayer.MediaStatus.LoadedMedia:
                self._video_duration = self._media_player.duration()
                print(f"视频时长: {self._video_duration}ms")
                self._sync_progress_bar_from_playhead()
            if getattr(self, "_audio_pending_play", False):
                try:
                    self._media_player.setPlaybackRate(
                        float(getattr(self, "_audio_pending_rate", 1.0) or 1.0)
                    )
                    # 2026-09-13 解冻修复：同步速率缓存，避免 tick 节流判断基于过期值
                    self._audio_applied_rate = float(getattr(self, "_audio_pending_rate", 1.0) or 1.0)
                    self._media_player.setPosition(
                        int(getattr(self, "_audio_pending_seek_ms", 0) or 0)
                    )
                    self._media_player.play()
                except Exception as e:
                    logger.warning("pending 音频播放失败: %s", e)
                self._audio_pending_play = False

    def _on_media_error(self, error, error_string):
        """QMediaPlayer错误回调"""
        logger.error(f'媒体播放错误: {error_string}')
        self._audio_pending_play = False
        if not getattr(self, "_timeline_playing", False):
            self._preview_label.setText(f"播放失败: {error_string}")
            pv_layout = self._preview_frame.layout()
            if isinstance(pv_layout, QStackedLayout):
                pv_layout.setCurrentWidget(self._preview_label)

    def _ensure_media_signals(self):
        if getattr(self, "_media_signals_connected", False):
            return
        self._media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._media_player.positionChanged.connect(self._on_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        self._media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._media_player.errorOccurred.connect(self._on_media_error)
        self._media_signals_connected = True

    def _ensure_media_audio_output(self):
        """保证主播放器有可用、未静音的 AudioOutput（切模块后可能被清掉）。"""
        from PyQt6.QtMultimedia import QAudioOutput
        if getattr(self, "_audio_output", None) is None:
            self._audio_output = QAudioOutput()
            self._media_player.setAudioOutput(self._audio_output)
        try:
            self._audio_output.setMuted(False)
        except Exception as e:
            logger.debug("取消音频静音失败: %s", e)
        # 画面走 OpenCV；卸掉视频输出避免双解码/无声
        try:
            self._media_player.setVideoOutput(None)
        except Exception as e:
            logger.debug("卸载MediaPlayer视频输出失败: %s", e)
        return self._audio_output

    def _arm_media_audio(self, source_t: float, rate: float = 1.0, *, expect_loading: bool = False):
        """在媒体就绪后播/seek；未就绪则记 pending，等 LoadedMedia。"""
        from PyQt6.QtMultimedia import QMediaPlayer
        self._ensure_media_signals()
        self._ensure_media_audio_output()
        seek_ms = max(0, int(float(source_t) * 1000))
        rate = max(0.05, float(rate or 1.0))
        self._audio_pending_seek_ms = seek_ms
        self._audio_pending_rate = rate
        # 2026-09-13 解冻修复：播放速率节流。曲线变速（speed_ramp）下每 33ms tick
        # 都会带上连续变化的瞬时倍率，若每次都 setPlaybackRate，Windows WMF 后端
        # 频繁切速率会造成音频抖动/重缓冲。仅当相对变化超过 8%（含绝对下限 0.02）才重设。
        applied = getattr(self, "_audio_applied_rate", None)
        if applied is None or abs(rate - applied) > max(0.02, 0.08 * max(0.05, applied)):
            try:
                self._media_player.setPlaybackRate(rate)
                self._audio_applied_rate = rate
            except Exception as e:
                logger.debug("设置音频播放速率失败: %s", e)
        st = self._media_player.mediaStatus()
        ready = st in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        )
        if expect_loading or not ready:
            self._audio_pending_play = True
            return
        self._audio_pending_play = False
        # 纠偏阈值放宽：每帧 80ms 硬 seek 会导致可闻卡顿；墙钟画面为主，音频允许短漂移
        if abs(self._media_player.position() - seek_ms) > 280:
            self._media_player.setPosition(seek_ms)
        if self._media_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.play()

    def on_deactivated(self):
        """模块停用回调 - 停止所有媒体播放（保留 AudioOutput，避免回来后无声）"""
        self._shutdown_media(release_source=False)
        logger.info("编辑器模块已停用，媒体播放器已停止")

    # >>> FROZEN:exit-media:shutdown BEGIN
    def cleanup(self):
        """主窗口关闭时调用：强制停声并释放媒体源，避免 Windows 下关窗后幽灵音频。"""
        self._shutdown_media(release_source=True)
        logger.info("编辑器模块 cleanup：媒体已释放")

    def _shutdown_media(self, *, release_source: bool = False):
        """停止时间线 + 主音 + BGM；关进程前应 release_source=True。"""
        from PyQt6.QtCore import QUrl

        try:
            self._stop_timeline_playback()
        except Exception as e:
            logger.debug("停止时间线回放失败: %s", e)
        self._audio_pending_play = False

        for player_attr, ao_attr in (
            ("_media_player", "_audio_output"),
            ("_bgm_player", "_bgm_audio_output"),
        ):
            player = getattr(self, player_attr, None)
            if player is None:
                continue
            try:
                ao = getattr(self, ao_attr, None)
                if ao is not None:
                    ao.setMuted(True)
                    ao.setVolume(0.0)
            except Exception as e:
                logger.debug("静音音频输出失败: %s", e)
            try:
                player.stop()
            except Exception as e:
                logger.debug("停止MediaPlayer失败: %s", e)
            if release_source:
                try:
                    player.setSource(QUrl())
                except Exception as e:
                    logger.debug("释放MediaPlayer播放源失败: %s", e)

        if release_source:
            self._audio_bound_clip_id = None
            self._bgm_bound_clip_id = None
    # <<< FROZEN:exit-media:shutdown END

    # ------------------------------------------------------------------
    # 补短 P1#8：关键帧可视化 - 公开便利 API
    # ------------------------------------------------------------------
    def add_keyframes_to_clip(self, clip_id, keyframes):
        """
        公开 API：给指定 clip 注入关键帧（合并同 prop+time，其余通道保留）。

        参数：
            clip_id: 添加到时间线时返回的 clip id（来自 _clips / new_clip['id']）
            keyframes: list[dict]，每项至少包含
                time_offset: 相对 clip 起点的时间偏移（秒）
                prop:       属性名（"opacity" / "scale_x" / "position_x" ...）
                value:      关键帧值
                easing:     缓动类型（可选，默认 "linear"）

        返回：
            bool - 是否成功（找不到 clip 时返回 False）
        """
        clip = next((c for c in self._clips if c.get("id") == clip_id), None)
        if clip is None and clip_id not in getattr(self, "_clip_id_to_widget", {}):
            logger.error(f'[P1#8] add_keyframes_to_clip 失败: 找不到 clip_id={clip_id}')
            return False
        before = list((clip or {}).get("keyframes") or [])
        merged = [dict(k) for k in (keyframes or []) if isinstance(k, dict)]
        widget = self._clip_id_to_widget.get(clip_id)
        if widget is not None:
            widget.set_keyframes(merged)
            merged = widget.get_keyframes()
        if clip is not None:
            # 刀4：真相源字段写走 store API（clip 即 live dict，原地 update 等价）
            self._timeline_store.set_fields(clip_id, keyframes=merged)
        elif widget is not None and hasattr(widget, "clip_data"):
            widget.clip_data["keyframes"] = merged
            # 刀4：写回真相源改走 store API（原 for c in self._clips 手工同步已收敛）
            self._timeline_store.set_fields(clip_id, keyframes=merged)
        self._touch_project_dirty()
        self._record_action({
            "type": "edit_clip",
            "clip_id": clip_id,
            "before": {"keyframes": before},
            "after": {"keyframes": list(merged)},
        })
        self._refresh_preview_with_effects()
        return True

    def add_keyframe_channel_to_clip(self, clip_id, prop_name, time_value_pairs,
                                       easing="linear"):
        """
        公开 API：通过"通道 + (time, value) 列表"批量添加关键帧（合并，不擦其它通道）。
        """
        clip = next((c for c in self._clips if c.get("id") == clip_id), None)
        existing = list((clip or {}).get("keyframes") or [])
        # 去掉同 prop 旧点，再追加新点
        kept = [k for k in existing if str(k.get("prop") or "") != str(prop_name)]
        for t, v in time_value_pairs:
            kept.append({
                "time_offset": float(t),
                "value": float(v),
                "prop": prop_name,
                "easing": easing,
            })
        return self.add_keyframes_to_clip(clip_id, kept)

    def get_keyframes_for_clip(self, clip_id):
        """获取指定 clip 当前的关键帧数据列表（找不到时返回空列表）"""
        widget = self._clip_id_to_widget.get(clip_id)
        if widget is not None:
            return widget.get_keyframes()
        clip = next((c for c in self._clips if c.get("id") == clip_id), None)
        return list((clip or {}).get("keyframes") or [])

    def _open_keyframe_curve_editor(self):
        """深工具：可视化关键帧曲线编辑器（拖拽点 / 双击改缓动 / 右键删除）。"""
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

        clip = self._current_clip
        if not clip:
            self._notify_edit("请先选择片段")
            return
        prop_labels = {
            "opacity": "不透明度", "volume": "音量", "scale": "缩放",
            "x": "水平位置", "y": "垂直位置", "rotation": "旋转",
        }
        prop, ok = QInputDialog.getItem(
            self, "曲线编辑器", "选择属性通道：", list(prop_labels.values()), 0, False,
        )
        if not ok:
            return
        prop_key = next((p for p, lab in prop_labels.items() if lab == prop), "opacity")
        ranges = {
            "opacity": (0.0, 1.0), "volume": (0.0, 2.0), "scale": (0.1, 3.0),
            "x": (0.0, 1.0), "y": (0.0, 1.0), "rotation": (-180.0, 180.0),
        }
        lo, hi = ranges.get(prop_key, (0.0, 1.0))
        all_kfs = self.get_keyframes_for_clip(clip.get("id"))
        channel_kfs = [k for k in all_kfs if str(k.get("prop", prop_key)) == prop_key]
        other_kfs = [k for k in all_kfs if str(k.get("prop", prop_key)) != prop_key]
        dur = float(clip.get("duration", 10) or 10)

        try:
            from app.modules.lego.keyframe_curve_editor import KeyframeCurveEditor
        except Exception:
            from app.modules.lego.keyframe_curve_editor import KeyframeCurveEditor  # noqa: F811

        dlg = QDialog(self)
        dlg.setWindowTitle(f"关键帧曲线 — {prop_labels.get(prop_key, prop_key)}")
        dlg.setMinimumSize(580, 380)
        lay = QVBoxLayout(dlg)
        editor = KeyframeCurveEditor(value_range=(lo, hi))
        editor.set_keyframes(channel_kfs, time_span=(0.0, max(dur, 1.0)))
        lay.addWidget(editor)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("应用")
        cancel_btn = btns.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        edited = editor.keyframes()
        for k in edited:
            k["prop"] = prop_key
        merged = other_kfs + edited
        self.add_keyframes_to_clip(clip.get("id"), merged)
        self._notify_edit(f"已更新 {prop_labels.get(prop_key, prop_key)} 曲线（{len(edited)} 个关键帧）")

    def _on_add_keyframe_clicked(self):
        """关键帧按钮：选属性 → 填数值 → 写入播放头。"""
        clip = self._current_clip
        if not clip:
            self._notify_edit("请先选择片段")
            return
        props = ["opacity", "volume", "scale", "x", "y", "rotation"]
        labels = {
            "opacity": "不透明度 (0~1)",
            "volume": "音量 (0~2)",
            "scale": "缩放 (0.1~3)",
            "x": "水平位置 (0~1)",
            "y": "垂直位置 (0~1)",
            "rotation": "旋转 (°)",
        }
        prop, ok = QInputDialog.getItem(
            self, "添加关键帧", "属性：",
            [labels[p] for p in props], 0, False,
        )
        if not ok:
            return
        # 反查 prop
        prop_key = next((p for p, lab in labels.items() if lab == prop), "opacity")
        # 默认值：当前插值或静态字段
        st = float(clip.get("start_time", 0) or 0)
        local_t = max(0.0, float(getattr(self, "_playhead_position", 0) or 0) - st)
        cur = self._interpolate_clip_keyframes(clip, local_t)
        fw, fh = self._preview_frame_size()
        try:
            from app.modules.lego.clip_transform import normalize_clip_transform
        except Exception:
            from app.modules.lego.video_processor import normalize_clip_transform
        tf = normalize_clip_transform(clip, fw, fh, {"x": 0.5, "y": 0.5, "scale": 1.0})
        defaults = {
            "opacity": float(cur.get("opacity", clip.get("opacity", 1.0)) or 1.0),
            "volume": float(cur.get("volume", clip.get("volume", 1.0)) or 1.0),
            "scale": float(cur.get("scale", clip.get("scale", 1.0)) or 1.0),
            "x": float(cur.get("x", tf["x"])),
            "y": float(cur.get("y", tf["y"])),
            "rotation": float(cur.get("rotation", tf.get("rotation", 0))),
        }
        ranges = {
            "opacity": (0.0, 1.0),
            "volume": (0.0, 2.0),
            "scale": (0.1, 3.0),
            "x": (0.0, 1.0),
            "y": (0.0, 1.0),
            "rotation": (-180.0, 180.0),
        }
        lo, hi = ranges[prop_key]
        val, ok2 = QInputDialog.getDouble(
            self, "关键帧数值", f"{labels[prop_key]}：",
            defaults[prop_key], lo, hi, 2,
        )
        if not ok2:
            return
        self.add_keyframe_at_playhead(prop_key, float(val))

    def _on_delete_keyframe_near_playhead(self):
        """删除当前片段在播放头 ±0.08s 内的关键帧。"""
        clip = self._current_clip
        if not clip:
            self._notify_edit("请先选择片段")
            return
        st = float(clip.get("start_time", 0) or 0)
        local_t = max(0.0, float(getattr(self, "_playhead_position", 0) or 0) - st)
        before = list(clip.get("keyframes") or [])
        kept = []
        removed = 0
        for kf in before:
            if not isinstance(kf, dict):
                continue
            t = float(kf.get("time_offset", kf.get("time", 0)) or 0)
            if abs(t - local_t) <= 0.08:
                removed += 1
                continue
            kept.append(kf)
        if removed <= 0:
            self._notify_edit("播放头附近没有关键帧")
            return
        self.add_keyframes_to_clip(clip.get("id"), kept)
        self._notify_edit(f"已删除 {removed} 个关键帧")

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
            logger.error(f'关键帧点击处理异常: {e}')

    def set_clip_speed(self, clip_id, speed: float):
        """设置片段播放速度（预览时钟与导出 setpts）。"""
        speed = max(0.05, min(8.0, float(speed)))
        for clip in self._clips:
            if clip.get("id") != clip_id:
                continue
            before = {"speed": float(clip.get("speed", 1.0) or 1.0)}
            # 刀4：字段写走 store API（live dict 原地 update，后续读 clip 仍同一对象）
            self._timeline_store.set_fields(clip_id, speed=speed)
            self._record_action({
                "type": "edit_clip",
                "clip_id": clip_id,
                "before": before,
                "after": {"speed": speed},
            })
            self._touch_project_dirty()
            self._refresh_preview_with_effects()
            self._notify_edit(f"片段速度 {speed}x")
            return True
        return False

    def _apply_clip_speed_from_ui(self):
        """属性页「应用变速」：写入当前片段 speed，预览立刻生效（不重新导出文件）。"""
        clip = self._current_clip
        if not clip:
            QMessageBox.warning(self, "变速", "请先选择一个片段")
            return
        preset = self._speed_preset.currentText() if hasattr(self, "_speed_preset") else "无"
        factor = (self._speed_factor.value() if hasattr(self, "_speed_factor") else 100) / 100.0
        speed_map = {
            "0.25x慢放": 0.25,
            "0.5x慢放": 0.5,
            "2x快放": 2.0,
            "4x快放": 4.0,
        }
        if preset in speed_map:
            speed = speed_map[preset]
        elif preset == "倒放":
            QMessageBox.information(self, "变速", "倒放请用「导出变速成片」生成新素材")
            return
        elif preset in ("缓入", "缓出", "缓入缓出", "卡点变速"):
            QMessageBox.information(self, "变速", "曲线变速请用「导出变速成片」；固定倍率可用速度因子")
            speed = factor
        else:
            speed = factor
        self.set_clip_speed(clip.get("id"), speed)

    # LUT_NAME_MAP → editor_color_panel.LUT_NAME_MAP

    def _rebuild_lut_combo(self):
        from app.modules.lego.editor_color_panel import rebuild_lut_combo
        return rebuild_lut_combo(self)

    def _resolve_lut_key_from_ui(self):
        from app.modules.lego.editor_color_panel import resolve_lut_key_from_ui
        return resolve_lut_key_from_ui(self)

    def _import_lut_file(self):
        from app.modules.lego.editor_color_panel import import_lut_file
        return import_lut_file(self)

    def _preview_lut_live(self):
        from app.modules.lego.editor_color_panel import preview_lut_live
        return preview_lut_live(self)

    def _apply_lut_preset(self):
        from app.modules.lego.editor_color_panel import apply_lut_preset
        return apply_lut_preset(self)

    def add_keyframe_at_playhead(self, prop: str = "opacity", value: float = 1.0):
        """在播放头位置为当前片段添加关键帧（同 prop 近时间点覆盖）。"""
        clip = self._current_clip
        if not clip:
            self._notify_edit("请先选择片段")
            return False
        st = float(clip.get("start_time", 0) or 0)
        local_t = max(0.0, float(self._playhead_position) - st)
        kfs = [
            k for k in list(clip.get("keyframes") or [])
            if not (
                isinstance(k, dict)
                and str(k.get("prop") or "") == prop
                and abs(float(k.get("time_offset", k.get("time", 0)) or 0) - local_t) < 0.05
            )
        ]
        kfs.append({
            "time_offset": local_t,
            "value": float(value),
            "prop": prop,
            "easing": "linear",
        })
        ok = self.add_keyframes_to_clip(clip.get("id"), kfs)
        if ok:
            self._notify_edit(f"关键帧 {prop}={value:.2f} @ {local_t:.2f}s")
        return ok

    def move_clip(self, clip_id, new_start_time):
        """移动片段开始时间（写入数据 + 联动音画 + 时间线定位 + 撤销）。"""
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
            # 刀4：字段写走 store API
            self._timeline_store.set_fields(clip_id, start_time=max(0.0, float(new_start_time)))
            link_steps = self._linked_av_edit_steps(clip, before=before)
            self._sync_linked_av_timing(clip, before=before)
            after = {
                "start_time": float(clip["start_time"]),
                "track": int(clip.get("track", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
            }
            main = {
                "type": "edit_clip",
                "clip_id": clip_id,
                "before": before,
                "after": after,
            }
            if link_steps:
                self._record_action({
                    "type": "compound",
                    "steps": [main] + link_steps,
                    "label": "move_clip_linked_av",
                })
            else:
                self._record_action(main)
            self._sync_timeline_widget_state()
            self._sync_kernel_timeline()
            self._notify_edit(f"已移动片段到 {clip['start_time']:.2f}s")
            return True
        return False

    def _resize_clip(self, clip_id, new_duration):
        """调整片段时长并同步 out_point（联动音画对齐）。"""
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
            # 刀4：字段写走 store API
            self._timeline_store.set_fields(clip_id, duration=dur, out_point=in_p + dur)
            link_steps = self._linked_av_edit_steps(clip, before=before)
            self._sync_linked_av_timing(clip, before=before)
            after = {
                "start_time": float(clip.get("start_time", 0) or 0),
                "track": int(clip.get("track", 0) or 0),
                "duration": dur,
                "in_point": in_p,
                "out_point": in_p + dur,
            }
            main = {
                "type": "edit_clip",
                "clip_id": clip_id,
                "before": before,
                "after": after,
            }
            if link_steps:
                self._record_action({
                    "type": "compound",
                    "steps": [main] + link_steps,
                    "label": "resize_clip_linked_av",
                })
            else:
                self._record_action(main)
            self._sync_timeline_widget_state()
            self._sync_kernel_timeline()
            return True
        return False
    
    def agent_trim_clip(self, clip_id: str, duration: Optional[float] = None,
                        in_point: Optional[float] = None,
                        out_point: Optional[float] = None) -> Dict[str, Any]:
        """Agent 公开接口：裁剪片段（时长 / 入点 / 出点），统一进撤销栈并同步 UI。

        收敛了一条真实缺陷：此前 AI 面板的 `trim_clip` 直接写
        `clip["duration"]` / `clip["out_point"]`，数据变了却**不进撤销栈**
        （Ctrl+Z 回不去），也不同步内核时间线与联动音画。
        现在本地面板与 capability 都走这里，只有一个实现。
        """
        try:
            if duration is None and in_point is None and out_point is None:
                return {"action": "trim_clip", "success": False,
                        "message": "trim_clip 需要 duration / in_point / out_point 之一"}
            clip = next((c for c in self._clips if c.get("id") == clip_id), None)
            if clip is None:
                return {"action": "trim_clip", "success": False,
                        "message": f"未找到片段 {clip_id}"}

            # ── 只改时长：复用 _resize_clip（已含撤销 + 联动音画 + 同步）──
            if in_point is None and out_point is None:
                try:
                    dur = float(duration)
                except (TypeError, ValueError):
                    return {"action": "trim_clip", "success": False, "message": "裁剪时长参数无效"}
                if dur <= 0:
                    return {"action": "trim_clip", "success": False, "message": "裁剪时长必须为正数"}
                if not self._resize_clip(clip_id, dur):
                    return {"action": "trim_clip", "success": False,
                            "message": f"未找到片段 {clip_id}"}
                self._touch_project_dirty()
                self._refresh_preview_with_effects()
                self._notify_edit(f"片段已裁剪为 {dur:.2f}s")
                return {"action": "trim_clip", "success": True,
                        "message": f"片段已裁剪为 {dur:.2f}s",
                        "clip_id": clip_id, "duration": dur}

            # ── 改入/出点：自己走一遍 before/after + 撤销栈 ──
            before = {
                "start_time": float(clip.get("start_time", 0) or 0),
                "track": int(clip.get("track", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
            }
            speed = float(clip.get("speed", 1.0) or 1.0) or 1.0
            new_in = before["in_point"] if in_point is None else max(0.0, float(in_point))
            if out_point is not None:
                new_out = max(new_in + 0.05, float(out_point))
            elif in_point is not None:
                # 只移入点：保持时长不变，出点跟着平移（源内窗口整体挪动）
                new_out = new_in + before["duration"] * speed
            else:
                new_out = before["out_point"] or (new_in + before["duration"] * speed)
            if new_out <= new_in:
                return {"action": "trim_clip", "success": False, "message": "出点必须大于入点"}

            # 刀4：字段写走 store API
            self._timeline_store.set_fields(
                clip_id,
                in_point=new_in,
                out_point=new_out,
                duration=max(0.05, (new_out - new_in) / speed),
            )
            after = {
                "start_time": float(clip.get("start_time", 0) or 0),
                "track": int(clip.get("track", 0) or 0),
                "duration": float(clip["duration"]),
                "in_point": new_in,
                "out_point": new_out,
            }
            link_steps = self._linked_av_edit_steps(clip, before=before)
            self._sync_linked_av_timing(clip, before=before)
            main = {"type": "edit_clip", "clip_id": clip_id, "before": before, "after": after}
            if link_steps:
                self._record_action({
                    "type": "compound",
                    "steps": [main] + link_steps,
                    "label": "trim_clip_linked_av",
                })
            else:
                self._record_action(main)
            self._sync_timeline_widget_state()
            self._sync_kernel_timeline()
            self._touch_project_dirty()
            self._refresh_preview_with_effects()
            self._notify_edit(f"片段已裁剪：{new_in:.2f}s → {new_out:.2f}s")
            return {
                "action": "trim_clip", "success": True,
                "message": f"片段已裁剪：{new_in:.2f}s → {new_out:.2f}s",
                "clip_id": clip_id, "in_point": new_in,
                "out_point": new_out, "duration": float(clip["duration"]),
            }
        except Exception as e:
            logger.exception(f"[Agent] agent_trim_clip 失败: {e}")
            return {"action": "trim_clip", "success": False, "message": str(e)}

    def agent_move_clip(self, clip_id: str, new_start_time: float) -> Dict[str, Any]:
        """Agent 公开接口：移动片段到新时间点（move_clip 已含撤销 + 联动音画 + 同步）。"""
        try:
            st = float(new_start_time)
        except (TypeError, ValueError):
            return {"action": "move_clip", "success": False, "message": "new_start_time 参数无效"}
        if st < 0:
            return {"action": "move_clip", "success": False, "message": "new_start_time 不能为负"}
        if not self.move_clip(clip_id, st):
            return {"action": "move_clip", "success": False,
                    "message": "移动片段失败（片段可能不在时间线）"}
        self._touch_project_dirty()
        return {
            "action": "move_clip", "success": True,
            "message": f"已移动片段到 {st:.2f}s",
            "clip_id": clip_id, "start_time": st,
        }

    # ═══════════════════════════════════════════════════════════════
    # 词锚定 · 重锚（阶段 5：接入 Agent）
    # ═══════════════════════════════════════════════════════════════
    def agent_reanchor_clips(
        self,
        dialogues: Optional[List[Dict[str, Any]]] = None,
        *,
        dry_run: bool = True,
        threshold: float = 0.75,
        spread: bool = True,
    ) -> Dict[str, Any]:
        """Agent 公开接口：文案改动后把片段重新对齐到新台词。

        「重锚」解决的是：锚点记在**台词的第 a~b 个词**上，一旦改了文案、
        重跑 ASR，词级时间会整体变化，锚点必须重新求解。计算全在
        ``app.core.dialogue_anchor.plan_reanchor``（纯函数、只读快照、不写 `_clips`），
        本方法只负责「取快照 → 出计划 → （可选）落地」。

        Args:
            dialogues: 新的台词序列（`DialogueSegment` 或同形 dict 均可）。
                       为 None 时用构造参数 ``self._dialogues``（若存在）。
            dry_run:   **默认 True —— 只出计划、不动时间线**。Agent 应先出计划
                       给用户看，确认后带 ``dry_run=False`` 再来一次。
            threshold: 指纹相似度阈值，低于此值判孤儿（不硬挂错句子）。
            spread:    落地时是否「铺开」——把每个片段时长改成它新分到的词区间
                       长度。默认开：词区间本就更精确，用段落时长会与区间打架。
                       关掉则只平移 ``start_time``、时长保持原样。

        Returns:
            计划摘要 + 逐片段差异。``dry_run=True`` 时带 ``applied=False``。
            落地成功时带 ``undo=1``（整包**一条** compound 撤销，Ctrl+Z 一次回滚）。

        ⚠️ 纪律：本方法绝不「部分落地」。若没有任何片段可重排（全孤儿/全无锚点），
        直接返回 ``applied=False`` 而不写 ``_action_history`` —— 避免用户按一次
        Ctrl+Z 却看不到任何变化，误以为撤销坏了。
        """
        from app.core.dialogue_anchor import plan_reanchor, summarize

        try:
            thr = float(threshold)
        except (TypeError, ValueError):
            return {"action": "reanchor_clips", "success": False,
                    "message": "threshold 参数无效"}

        # ── 1) 取新台词：优先入参，回落 self._dialogues ──
        dlg = dialogues if dialogues is not None else getattr(self, "_dialogues", None)
        if not dlg:
            return {
                "action": "reanchor_clips", "success": False,
                "message": ("没有可用的台词序列。请先跑剧情理解/ASR 得到带词级时间的台词，"
                            "或直接把 dialogues 传进来。"),
            }

        # ── 2) 取快照（持锁一次拿到稳定列表，绝不把 self._clips 引用交出去）──
        clips = self._clips_snapshot()

        # ── 3) 纯函数求解计划（不写任何状态）──
        try:
            plan = plan_reanchor(clips, dlg, threshold=thr)
        except Exception as e:
            logger.warning(f"[Agent] 重锚计划求解失败: {e}")
            return {"action": "reanchor_clips", "success": False,
                    "message": f"重锚计划求解失败: {e}"}

        summary = summarize(plan)
        shifts = [
            {
                "clip_id": s.clip_id,
                "reason": s.reason,
                "old_range": list(s.old_range) if s.old_range else None,
                "new_range": list(s.new_range) if s.new_range else None,
                "dialogue_id": s.dialogue_id,
                "note": s.note,
            }
            for s in plan.shifts
        ]
        base: Dict[str, Any] = {
            "action": "reanchor_clips",
            "success": True,
            "message": summary,
            "matched": plan.matched,
            "orphaned": plan.orphaned,
            "unchanged": plan.unchanged,
            "unmatched_new": plan.unmatched_new,
            "overlaps": list(plan.overlaps),
            "total": plan.total,
            "shifts": shifts,
        }

        # ── dry_run：只交计划 ──
        if dry_run:
            base.update({"dry_run": True, "applied": False,
                         "message": f"[预览] {summary}。确认后请以 dry_run=false 再执行。"})
            return base

        # ── 4) 落地 ──
        movable = plan.moved()
        if not movable:
            base.update({
                "dry_run": False, "applied": False,
                "message": f"无可重排片段（{summary}），时间线未改动。",
            })
            return base

        clip_by_id = {str(c.get("id", "")): c for c in clips}
        steps: List[Dict[str, Any]] = []

        for s in movable:
            clip = clip_by_id.get(s.clip_id)
            if clip is None or not s.new_range:
                continue
            new_start = max(0.0, float(s.new_range[0]))
            before = {
                "start_time": float(clip.get("start_time", 0) or 0),
                "track": int(clip.get("track", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
            }
            after = dict(before)
            after["start_time"] = new_start
            if spread:
                # 新词区间长度 → 新时长；同步 out_point 保持「入点 + 时长」契约
                new_dur = max(0.05, float(s.new_range[1]) - new_start)
                after["duration"] = new_dur
                after["out_point"] = float(clip.get("in_point", 0) or 0) + new_dur
            steps.append({
                "type": "edit_clip",
                "clip_id": s.clip_id,
                "before": before,
                "after": after,
            })

        if not steps:
            base.update({
                "dry_run": False, "applied": False,
                "message": "计划中的片段在时间线上已找不到（可能被并发删除），未改动时间线。",
            })
            return base

        # ⚠️ 整段持 _clips_lock：本方法是跨线程写入口（画布桥/Agent 线程），
        # 「逐个改 start_time/duration」若不原子，渲染与 autosave 会读到半新半旧的
        # 时间线。RLock 可重入，内部 _sync_* 再取锁不会死锁。
        lock = getattr(self, "_clips_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._clips_lock = lock
        with lock:
            for step in steps:
                for c in self._clips:
                    if str(c.get("id", "")) == step["clip_id"]:
                        self._apply_clip_fields(c, step["after"])
                        break
            # 一条 compound 撤销：用户按一次 Ctrl+Z 还原整包重排
            self._record_action({
                "type": "compound",
                "steps": steps,
                "label": "reanchor_clips",
            })
            self._sync_timeline_widget_state()
            self._sync_kernel_timeline()
        self._refresh_preview_with_effects()

        base.update({
            "dry_run": False,
            "applied": True,
            "undo": 1,
            "moved": len(steps),
            "message": f"已按新台词重排 {len(steps)} 个片段（{summary}）。Ctrl+Z 一次可整包撤销。",
        })
        return base

    # ===== 补短 P0#4:撤销/重做完整贯通 UI =====
    # _on_ai_clip / _on_ai_clip_fallback 已迁移到 ai_agent_panel.py（AiAgentPanelMixin）

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
            logger.error(f'[P0#4] 快捷键注册失败: {e}')

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
            logger.error(f'[P0#4] 状态更新失败: {e}')

    def get_undo_redo_toast(self) -> str:
        """获取最近一次撤销/重做的轻量提示(供 status bar / 主窗口显示)"""
        return self._undo_redo_toast

    # ---- 撤销/重做核心：历史栈 + 时间线感知的回滚（替代原被覆盖的死代码） ----

    def _get_history_lock(self):
        """撤销/重做栈的互斥锁（懒建）。

        ★ A3（2026-10-05）：压栈（Agent 能力链，见 agent_reanchor_clips 在锁内
        `_record_action`）与弹栈（UI 线程 `_undo`/`_redo`）此前**无互斥**——
        list 的 append/pop 虽各自原子，但「pop 后立刻 append 到另一个栈」不是，
        并发下会出现同一个 action 同时留在两条栈（或直接丢失）。
        """
        lock = getattr(self, "_history_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._history_lock = lock
        return lock

    def _record_action(self, action: dict) -> None:
        """将一次编辑操作压入撤销栈，并清空重做栈、刷新按钮状态。"""
        if not hasattr(self, '_action_history'):
            self._action_history = []
        if not hasattr(self, '_redo_history'):
            self._redo_history = []
        # B1 撤销反馈回路：盖来源章（agent=能力链做的 / user=用户手动）。
        # 线程局部判定，Agent 能力与用户 UI 操作并发时互不污染；判定失败按 user 兜底。
        try:
            from app.core.agent_origin import is_agent_origin
            action.setdefault("origin", "agent" if is_agent_origin() else "user")
        except Exception:
            action.setdefault("origin", "user")
        with self._get_history_lock():
            self._action_history.append(action)
            self._redo_history.clear()
            if len(self._action_history) > getattr(self, 'MAX_UNDO_DEPTH', 100):
                self._action_history.pop(0)
        self._touch_project_dirty()
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
        old_track = int(clip.get("track", 0) or 0)
        for k, v in fields.items():
            clip[k] = v
        # track 变化时同步 UI 换轨
        if "track" in fields:
            new_track = int(fields.get("track", old_track) or 0)
            if new_track != old_track:
                tw = getattr(self, "_timeline_widget", None)
                if tw is not None and hasattr(tw, "reparent_clip_to_track"):
                    w = None
                    for cw in tw.all_clip_widgets():
                        if cw.clip_data.get("id") == clip.get("id"):
                            w = cw
                            break
                    if w is not None:
                        try:
                            tw.reparent_clip_to_track(w, new_track)
                        except Exception as e:
                            logger.debug("换轨同步 UI 失败: %s", e)

    def _apply_action(self, action: dict, mode: str) -> None:
        """执行一次操作或其逆操作（**整段持 `_clips_lock`**）。

        ★ A3（2026-10-05）加锁原因：本方法多步改 `self._clips`（delete/batch/split/
        drop/add/edit_clip/stickers/compound），此前**不持锁**——画布桥线程的
        `_clips_snapshot()` 与 autosave 会读到「半新半旧」的真相源（本文件 L473-479
        自写的纪律要求所有非原子整段替换都持锁，此处此前是自违反）。
        RLock 可重入 ⇒ 内部 `_sync_*` 与 compound 递归再取锁不会死锁。
        """
        lock = getattr(self, "_clips_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._clips_lock = lock
        with lock:
            self._apply_action_locked(action, mode)

    def _apply_action_locked(self, action: dict, mode: str) -> None:
        """（原实现保持不变；锁由 `_apply_action` 统一加，勿单独直调。）

        mode='do'  正向执行（用于重做 / 记录时的实做）
        mode='undo' 反向回滚（用于撤销）
        """
        atype = action.get("type")

        if atype in ("delete", "redo_delete"):
            is_delete = (mode == 'do')
            clip = action["clip"]
            shifts = action.get("ripple_shifts") or []
            if is_delete:
                # 刀2：结构写入收敛 TimelineStore（原地突变保同一性，RLock 可重入）
                self._timeline_store.remove_by_id(clip.get("id"))
                self._timeline_remove_clip_widget(clip.get("id"))
                if self._current_clip and self._current_clip.get("id") == clip.get("id"):
                    self._current_clip = None
                for sh in shifts:
                    # 刀4：波纹位移字段写走 store API（保留「缺键则维持现值」语义）
                    _c = self._timeline_store.find_by_id(sh.get("id"))
                    if _c is not None:
                        self._timeline_store.set_fields(
                            sh.get("id"), start_time=float(sh.get("new", _c.get("start_time", 0))))
            else:
                if clip not in self._clips:
                    self._timeline_store.add(clip)
                self._timeline_add_clip_widget(clip)
                self._current_clip = clip
                for sh in shifts:
                    _c = self._timeline_store.find_by_id(sh.get("id"))
                    if _c is not None:
                        self._timeline_store.set_fields(
                            sh.get("id"), start_time=float(sh.get("old", _c.get("start_time", 0))))

        elif atype == "batch_delete":
            items = action.get("items") or []
            if mode == "do":
                for item in items:
                    clip = item["clip"]
                    shifts = item.get("ripple_shifts") or []
                    self._timeline_store.remove_by_id(clip.get("id"))
                    self._timeline_remove_clip_widget(clip.get("id"))
                    if self._current_clip and self._current_clip.get("id") == clip.get("id"):
                        self._current_clip = None
                    for sh in shifts:
                        # 刀4：波纹位移字段写走 store API
                        _c = self._timeline_store.find_by_id(sh.get("id"))
                        if _c is not None:
                            self._timeline_store.set_fields(
                                sh.get("id"), start_time=float(sh.get("new", _c.get("start_time", 0))))
            else:
                for item in reversed(items):
                    clip = item["clip"]
                    shifts = item.get("ripple_shifts") or []
                    if clip not in self._clips:
                        self._timeline_store.add(clip)
                    self._timeline_add_clip_widget(clip)
                    self._current_clip = clip
                    for sh in shifts:
                        _c = self._timeline_store.find_by_id(sh.get("id"))
                        if _c is not None:
                            self._timeline_store.set_fields(
                                sh.get("id"), start_time=float(sh.get("old", _c.get("start_time", 0))))

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
                    self._timeline_store.add(new_clip)
                self._timeline_add_clip_widget(new_clip)
                self._current_clip = new_clip
            else:
                original["duration"] = action["original_duration"]
                original["out_point"] = action["original_out_point"]
                self._timeline_store.remove_by_id(new_clip.get("id"))
                self._timeline_remove_clip_widget(new_clip.get("id"))
                self._current_clip = original

        elif atype in ("paste", "redo_paste"):
            is_paste = (mode == 'do')
            new_clip = action["new_clip"]
            if is_paste:
                if new_clip not in self._clips:
                    self._timeline_store.add(new_clip)
                self._timeline_add_clip_widget(new_clip)
                self._current_clip = new_clip
            else:
                self._timeline_store.remove_by_id(new_clip.get("id"))
                self._timeline_remove_clip_widget(new_clip.get("id"))
                if self._current_clip and self._current_clip.get("id") == new_clip.get("id"):
                    self._current_clip = None

        elif atype == "add_clip":
            # 添加片段（AI剪辑/画布入轨/素材拖入）的撤销支持
            clip = action.get("clip")
            audio_clip = action.get("audio_clip")
            if mode == 'undo':
                # 撤销添加：移除视频片段 + 联动音频片段
                if audio_clip:
                    self._timeline_store.remove_by_id(audio_clip.get("id"))
                    self._timeline_remove_clip_widget(audio_clip.get("id"))
                if clip:
                    self._timeline_store.remove_by_id(clip.get("id"))
                    self._timeline_remove_clip_widget(clip.get("id"))
                    if self._current_clip and self._current_clip.get("id") == clip.get("id"):
                        self._current_clip = None
            else:
                # 重做添加：重新加入视频片段 + 联动音频片段
                if clip and clip not in self._clips:
                    self._timeline_store.add(clip)
                if clip:
                    self._timeline_add_clip_widget(clip)
                    self._current_clip = clip
                if audio_clip and audio_clip not in self._clips:
                    self._timeline_store.add(audio_clip)
                    self._timeline_add_clip_widget(audio_clip)

        elif atype == "edit_clip":
            clip_id = action.get("clip_id")
            fields = action.get("after") if mode == "do" else action.get("before")
            for c in self._clips:
                if c.get("id") == clip_id:
                    self._apply_clip_fields(c, fields or {})
                    self._current_clip = c
                    break

        elif atype == "stickers":
            # ★ A3（2026-10-05）：贴纸整表快照回滚（贴纸挂在引擎上、不是 clip 字段，
            #   故不能走 edit_clip；整表替换是最简单且不会漏项的还原方式）。
            snap = action.get("after") if mode == "do" else action.get("before")
            self._active_stickers = [dict(s) for s in (snap or [])]
            self._refresh_sticker_list_ui()

        elif atype == "compound":
            steps = action.get("steps") or []
            ordered = steps if mode == "do" else reversed(steps)
            for step in ordered:
                self._apply_action(step, mode=mode)

        # 刷新时间线与预览
        self._sync_timeline_widget_state()
        self._sync_kernel_timeline()
        self._refresh_preview_with_effects()
        self._refresh_preview_to_current_clip()

    def _undo(self):
        """撤销最近一步操作（时间线感知，按钮自动 enable/disable）。"""
        # ★ A3：栈操作持 _history_lock（与 Agent 线程的压栈互斥）；
        #   _apply_action 在锁外执行，避免与 _clips_lock 形成长嵌套。
        with self._get_history_lock():
            action = self._action_history.pop() if getattr(self, '_action_history', []) else None
            if action is not None:
                self._redo_history.append(action)
        if action is not None:
            self._apply_action(action, mode='undo')
            if action.get("origin") == "agent":
                self._notify_edit(f"已撤销: {action.get('type')}（Agent 操作 · 已反馈学习）")
                self._on_agent_action_undone(action)
            else:
                self._notify_edit(f"已撤销: {action.get('type')}")
        else:
            self._notify_edit("没有可撤销的操作")
        self._update_undo_redo_state()

    def _redo(self):
        """重做最近撤销的操作（时间线感知，按钮自动 enable/disable）。"""
        with self._get_history_lock():
            action = self._redo_history.pop() if getattr(self, '_redo_history', []) else None
            if action is not None:
                self._action_history.append(action)
        if action is not None:
            self._apply_action(action, mode='do')
            if action.get("origin") == "agent":
                self._on_agent_action_redone(action)
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
            logger.info('✅ 切换到自动选择内核（按任务自主选择轻量/专业）')
        elif index == 1:
            self._kernel_mode = "light"
            editor_scheduler.set_selection_mode("lightweight")
            logger.info('✅ 切换到轻量内核（快速预览模式）')
        else:
            success = editor_scheduler.set_selection_mode("professional")
            if success:
                self._kernel_mode = "pro"
                logger.info('✅ 切换到专业内核（完整功能模式）')
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
        # 刀4：字段写走 store API（live dict 原地 update，语义等价）
        self._timeline_store.set_fields(clip_id, effects=effects)
        self._current_clip = target_clip
        self._touch_project_dirty()
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
        self._touch_project_dirty()
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
        # 刀4：转场元数据字段写走 store API
        self._timeline_store.set_fields(
            target_clip.get("id"), transitions=transitions, transition=transitions[-1])
        self._notify_edit(f"转场 {transition_name} {duration}s")

    def _schedule_preview_refresh(self):
        """滑杆/LUT 拖动：合并到下一帧刷新，避免每 tick 全量解码。"""
        # scrub 中改 LUT：走 scrub 队列 + busy-drop，勿另开全量解码
        if getattr(self, "_preview_scrubbing", False):
            self._scrub_preview_pending = float(getattr(self, "_playhead_position", 0) or 0)
            st = getattr(self, "_scrub_preview_timer", None)
            if st is not None:
                st.start()
                return
        t = getattr(self, "_preview_debounce", None)
        if t is None:
            self._refresh_preview_with_effects()
            return
        # 带 LUT 时加长合并窗，减轻拖强度时的解码风暴
        try:
            cp = getattr(self, "_color_params", None) or {}
            if cp.get("lut"):
                t.setInterval(120)
            else:
                t.setInterval(60)
        except Exception:
            logger.debug("定时器间隔设置失败", exc_info=True)
        t.start()

    def _begin_preview_scrub(self):
        """拖播放头时降预览分辨率，松手后恢复用户档。"""
        if getattr(self, "_timeline_playing", False):
            return
        pm = getattr(self, "_preview_manager", None)
        if pm is None:
            return
        if not getattr(self, "_preview_scrubbing", False):
            self._preview_scrubbing = True
            # 恢复目标固定为用户档，避免连环 scrub 把 low 存成「原质量」
            self._preview_quality_before_scrub = getattr(
                self, "_user_preview_quality", "medium"
            )
            try:
                pm.set_preview_quality("low")
            except Exception as e:
                logger.debug("拖动预览切换低画质失败: %s", e)
        idle = getattr(self, "_scrub_idle_timer", None)
        if idle is not None:
            idle.start()

    def _end_preview_scrub(self):
        if not getattr(self, "_preview_scrubbing", False):
            return
        self._preview_scrubbing = False
        pending = getattr(self, "_scrub_preview_pending", None)
        coalesce = int(getattr(self, "_scrub_preview_coalesce", 0) or 0)
        drops = int(getattr(self, "_scrub_busy_drops", 0) or 0)
        if coalesce > 0 or drops > 0:
            logger.info(
                "scrub 预览降载：合并 %d 次，busy-drop %d 次",
                coalesce, drops,
            )
        self._scrub_preview_coalesce = 0
        self._scrub_busy_drops = 0
        st = getattr(self, "_scrub_preview_timer", None)
        if st is not None:
            st.stop()
        pm = getattr(self, "_preview_manager", None)
        q = getattr(self, "_preview_quality_before_scrub", None) or getattr(
            self, "_user_preview_quality", "medium"
        )
        if pm is not None and q:
            try:
                if not getattr(self, "_timeline_playing", False):
                    pm.set_preview_quality(q)
            except Exception as e:
                logger.debug("恢复预览画质失败: %s", e)
        self._preview_quality_before_scrub = None
        # 松手后高质量再刷一帧 + 一次性音频 seek（含字幕叠层）
        if pending is not None:
            self._render_scrub_preview_at(float(pending), sync_audio=True)
        else:
            self._refresh_preview_with_effects()
            self._sync_scrub_audio_position()

    def _sync_scrub_audio_position(self):
        """scrub 结束后一次性对齐 QMediaPlayer，避免拖动中每 tick seek。"""
        try:
            pos = float(getattr(self, "_playhead_position", 0) or 0)
            clip = self._clip_at_playhead(pos)
            if clip and clip.get("path") and self._media_player.duration() > 0:
                try:
                    from app.core.speed_ramping import (
                        source_time_for_clip_at_timeline,
                        instant_speed_for_clip_at_timeline,
                    )
                    source_t = source_time_for_clip_at_timeline(clip, pos)
                    rate = self._playback_rate() * instant_speed_for_clip_at_timeline(clip, pos)
                    try:
                        self._media_player.setPlaybackRate(max(0.05, rate))
                    except Exception:
                        logger.debug("播放速率设置失败", exc_info=True)
                except Exception:
                    st = float(clip.get("start_time", 0) or 0)
                    in_p = float(clip.get("in_point", 0) or 0)
                    speed = max(0.05, float(clip.get("speed", 1.0) or 1.0))
                    source_t = max(0.0, (pos - st) * speed + in_p)
                self._media_player.setPosition(int(source_t * 1000))
            elif self._media_player.duration() > 0:
                self._media_player.setPosition(int(pos * 1000))
        except Exception as _e:
            logger.debug("scrub 音频对齐跳过: %s", _e)

    def _flush_scrub_preview(self):
        """合并 scrub 预览；解码未完成则 busy-drop，只保留最新 pending（M2）。"""
        if getattr(self, "_timeline_playing", False):
            return
        if getattr(self, "_scrub_render_busy", False):
            self._scrub_busy_drops = int(getattr(self, "_scrub_busy_drops", 0) or 0) + 1
            st = getattr(self, "_scrub_preview_timer", None)
            if st is not None:
                st.start()
            return
        pos = getattr(self, "_scrub_preview_pending", None)
        if pos is None:
            return
        self._scrub_preview_pending = None
        self._scrub_render_busy = True
        try:
            self._render_scrub_preview_at(float(pos), sync_audio=False)
        finally:
            self._scrub_render_busy = False
        if getattr(self, "_scrub_preview_pending", None) is not None:
            st = getattr(self, "_scrub_preview_timer", None)
            if st is not None:
                st.start()

    def _render_scrub_preview_at(self, position: float, sync_audio: bool = False):
        """scrub/跳转：走时间线合成（转场/叠轨/画幅），与播放所见一致。

        拖动中 stub 掉主音/BGM 同步（不改冻结符号体），避免每 tick play/seek。
        松手 sync_audio=True 时再一次性对齐音位置。
        """
        position = float(position)
        self._preview_scrubbing = True
        # 实例级 stub：冻结区 main-audio 仍会调用，但不真正出声/seek
        real_arm = self._arm_media_audio
        real_bgm = self._sync_bgm_audio

        def _noop_audio(*_a, **_k):
            return None

        self._arm_media_audio = _noop_audio  # type: ignore[method-assign]
        self._sync_bgm_audio = _noop_audio  # type: ignore[method-assign]
        try:
            try:
                self._media_player.pause()
            except Exception:
                logger.debug("播放器暂停失败", exc_info=True)
            try:
                bgm = getattr(self, "_bgm_player", None)
                if bgm is not None:
                    bgm.pause()
            except Exception:
                logger.debug("BGM 暂停失败", exc_info=True)
            self._render_timeline_frame(position)
        finally:
            self._arm_media_audio = real_arm  # type: ignore[method-assign]
            self._sync_bgm_audio = real_bgm  # type: ignore[method-assign]
        if sync_audio:
            self._sync_scrub_audio_position()
    def _lighten_effects_for_playback(self, effects: dict) -> dict:
        """播放/scrub 跳过重 CPU 项（LUT/锐化/模糊/暗角）；命名滤镜留给 GPU shader。"""
        if not effects:
            return effects
        playing = getattr(self, "_timeline_playing", False)
        scrubbing = getattr(self, "_preview_scrubbing", False)
        if not playing and not scrubbing:
            return effects
        e = dict(effects)
        e["_preview_fast"] = True
        e.pop("sharpen", None)
        e.pop("blur", None)
        e.pop("vignette", None)
        cp = e.get("color_params")
        if isinstance(cp, dict):
            cp = dict(cp)
            # 播放中 LUT 用快速路径标记；保留名称供松手/导出
            if cp.get("lut"):
                cp["lut_fast"] = True
            e["color_params"] = cp
        if e.get("lut"):
            e["lut_fast"] = True
        return e

    def _refresh_preview_with_effects(self):
        """刷新预览以反映当前效果参数（所见即所得）"""
        pm = self._ensure_preview_manager() if hasattr(self, '_ensure_preview_manager') else None
        if not pm:
            return
        clip = self._current_clip
        effects = self._lighten_effects_for_playback(self._collect_preview_effects(clip))
        # 用素材内时间刷新（含片段 speed）
        t = float(getattr(self, '_playhead_position', 0) or 0)
        if clip:
            try:
                from app.core.speed_ramping import source_time_for_clip_at_timeline
                source_t = source_time_for_clip_at_timeline(clip, t)
            except Exception:
                st = float(clip.get('start_time', 0) or 0)
                in_p = float(clip.get('in_point', 0) or 0)
                speed = max(0.05, float(clip.get('speed', 1.0) or 1.0))
                source_t = max(0.0, (t - st) * speed + in_p)
        else:
            source_t = t
        # GPU 路径：同帧只改 uniform；换帧才上传纹理
        gl = self._ensure_gl_preview()
        if gl is not None and clip:
            src = clip.get('path')
            if src and os.path.exists(src):
                need_open = (
                    not self._media_paths_equal(getattr(pm, "_video_source", None), src)
                    or getattr(pm, "_video_capture", None) is None
                )
                if need_open:
                    self._ensure_preview_source_open(
                        pm,
                        src,
                        for_scrub=bool(
                            getattr(self, "_timeline_playing", False)
                            or getattr(self, "_preview_scrubbing", False)
                        ),
                        preload=False,
                    )
                    self._preview_gl_cache_key = None
            # LUT 在 GPU 路径不可见 → 有 LUT 时走 CPU（或 fast LUT）
            has_lut = bool(
                (effects.get("color_params") or {}).get("lut")
                if isinstance(effects.get("color_params"), dict)
                else effects.get("lut")
            )
            if has_lut and not getattr(gl, "supports_lut", False):
                pm.set_active_effects(effects)
                pm.update_preview(source_t, effects=effects)
                return
            cache_key = (src, int(round(source_t * 1000)))
            if (
                cache_key == getattr(self, "_preview_gl_cache_key", None)
                and hasattr(gl, "set_effects")
                and getattr(gl, "_img", None) is not None
            ):
                try:
                    pv_layout = self._preview_frame.layout()
                    if isinstance(pv_layout, QStackedLayout):
                        pv_layout.setCurrentWidget(gl)
                    gl.set_effects(effects or {})
                    return
                except Exception as e:
                    logger.debug("应用GL预览effects失败: %s", e)
            qimg = pm.get_frame_at(source_t, effects={})
            if qimg is not None:
                self._preview_gl_cache_key = cache_key
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
            # EffectManager 预览参数（若片段上已挂）
            preview_params = effects.pop("_preview_params", None)
            if isinstance(preview_params, dict):
                for k, v in preview_params.items():
                    if k not in effects:
                        effects[k] = v
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
                elif k == "x":
                    effects["_tf_x"] = v
                elif k == "y":
                    effects["_tf_y"] = v
                elif k == "rotation":
                    effects["_tf_rot"] = v
                    effects["rotation"] = v
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
        """插值片段关键帧（opacity/volume/scale），优先走 keyframe_animation 缓动。"""
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
        try:
            from app.core.keyframe_animation import KeyframeAnimation, EasingType
        except ImportError:
            try:
                from core.keyframe_animation import KeyframeAnimation, EasingType
            except ImportError:
                KeyframeAnimation = None
                EasingType = None

        for prop, items in by_prop.items():
            if prop not in (
                "opacity", "volume", "scale", "scale_x", "scale_y",
                "x", "y", "position_x", "position_y", "pip_x", "pip_y",
                "rotation", "rot",
            ):
                continue
            if prop in ("scale", "scale_x", "scale_y"):
                key = "scale"
            elif prop in ("x", "position_x", "pip_x"):
                key = "x"
            elif prop in ("y", "position_y", "pip_y"):
                key = "y"
            elif prop in ("rotation", "rot"):
                key = "rotation"
            else:
                key = prop
            if KeyframeAnimation is not None:
                anim = KeyframeAnimation(name=prop)
                for x in items:
                    t = float(x.get("time_offset", x.get("time", 0)) or 0)
                    v = float(x.get("value", 0) or 0)
                    easing_name = str(x.get("easing") or "linear").lower()
                    try:
                        easing = EasingType(easing_name) if EasingType else None
                    except (ValueError, TypeError):
                        easing = EasingType.LINEAR if EasingType else None
                    if easing is not None:
                        anim.add_keyframe(t, v, easing=easing)
                    else:
                        anim.add_keyframe(t, v)
                out[key] = float(anim.get_value(local_t))
                continue
            # 回退线性
            items = sorted(items, key=lambda x: float(x.get("time_offset", x.get("time", 0)) or 0))
            times = [float(x.get("time_offset", x.get("time", 0)) or 0) for x in items]
            vals = [float(x.get("value", 0) or 0) for x in items]
            if local_t <= times[0]:
                out[key] = vals[0]
                continue
            if local_t >= times[-1]:
                out[key] = vals[-1]
                continue
            for i in range(len(times) - 1):
                if times[i] <= local_t <= times[i + 1]:
                    span = times[i + 1] - times[i] or 1e-6
                    a = (local_t - times[i]) / span
                    out[key] = vals[i] * (1 - a) + vals[i + 1] * a
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

    # ─── 字幕面板（实现见 editor_subtitle_panel） ───
    @staticmethod
    def _sub_btn_style(bg):
        from app.modules.lego.editor_subtitle_panel import sub_btn_style
        return sub_btn_style(bg)

    @staticmethod
    def _sub_input_style():
        from app.modules.lego.editor_subtitle_panel import sub_input_style
        return sub_input_style()

    def _apply_subtitle_style(self):
        from app.modules.lego.editor_subtitle_panel import apply_subtitle_style
        apply_subtitle_style(self)

    def _on_color_click(self, color):
        from app.modules.lego.editor_subtitle_panel import on_color_click
        on_color_click(self, color)

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

    def _on_workflow_hint_received(self, hint: dict) -> None:
        """接收闭环跳转的工作流提示（如爆款建议 → 下一轮粗剪）。"""
        if not isinstance(hint, dict):
            return
        body = (hint.get("body") or "").strip()
        title = hint.get("title") or "工作流提示"
        platform = hint.get("platform") or ""
        short = f"{title}" + (f"（{platform}）" if platform else "")
        self._notify_edit(short)
        if body:
            QMessageBox.information(self, title, body)
    
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
        """接收素材库 / 选题 / Agent 预览闭环推送的素材，添加到时间线。

        兼容两种载荷：
        - 单文件: {"file_path": "...", "source": "...", "title": "..."}
        - 批量: {"clips": [{"path"/"file_path": "...", ...}], "source": "..."}（PreviewValidationLoop）

        另：单文件中若 kind=="audio"（或路径为音频扩展名），走
        `_add_audio_clip_to_timeline()` **纯音轨**入轨，不产生视频片段
        （配音轨自动落位，2026-10-15 解冻 playback-av）。
        """
        data = event.data if hasattr(event, 'data') else event
        src = data.get("source", "") if isinstance(data, dict) else ""

        clips = data.get("clips") if isinstance(data, dict) else None
        if isinstance(clips, list) and clips:
            added, failed = [], []
            for c in clips:
                p = (c.get("path") or c.get("file_path") or "") if isinstance(c, dict) else str(c)
                # 透传生成线 clip_id：精剪 clip_order 按生成线 id 引用（见 _add_clip_to_timeline）
                src_cid = (c.get("clip_id") or c.get("id") or "") if isinstance(c, dict) else ""
                if p and os.path.exists(p):
                    self._add_clip_to_timeline(p, src_cid)
                    added.append(os.path.basename(p))
                else:
                    failed.append(p or "(空路径)")
            if added:
                tip = "、".join(added[:3]) + (f" 等{len(added)}个" if len(added) > 3 else "")
                self._notify_edit(f"已加入时间线: {tip}" + (f" ({src})" if src else ""))
                logger.info(f'✅ Agent 素材已添加到时间线: {tip}')
            if failed:
                msg = f"{len(failed)} 个素材未能加入时间线（文件不存在）: {', '.join(failed[:3])}"
                logger.info(f'⚠️ {msg}')
                try:
                    self._notify_edit(msg)
                except Exception:
                    logger.warning("编辑通知发送失败", exc_info=True)
            return

        file_path = data.get("file_path", "") if isinstance(data, dict) else str(data)
        if file_path and os.path.exists(file_path):
            # 配音轨自动落位（2026-10-15 解冻 playback-av）：kind=="audio" 或音频扩展名
            # ⇒ 纯音轨入轨；旧 _add_clip_to_timeline 只认视频、会把 wav 当视频片段塞进视频轨。
            _m_kind = str(data.get("kind") or "").lower() if isinstance(data, dict) else ""
            _m_ext = os.path.splitext(file_path)[1].lower()
            _m_is_audio = _m_kind == "audio" or (
                not _m_kind and _m_ext in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")
            )
            if _m_is_audio:
                self._add_audio_clip_to_timeline(
                    file_path,
                    title=(data.get("title", "") if isinstance(data, dict) else "") or "",
                    duration_hint=(data.get("duration_hint", 0) if isinstance(data, dict) else 0) or 0,
                )
            else:
                self._add_clip_to_timeline(file_path)
            if isinstance(data, dict):
                try:
                    from app.core.editor_canvas_link import extra_from_material_payload, stamp_clip
                except ImportError:
                    from core.editor_canvas_link import extra_from_material_payload, stamp_clip  # type: ignore
                extra = extra_from_material_payload(data)
                if extra:
                    for c in reversed(getattr(self, "_clips", []) or []):
                        if (c.get("path") or "") == file_path:
                            stamp_clip(c, extra)
                            if extra.get("canvas_title"):
                                # 刀4：字段写走 store API
                                self._timeline_store.set_fields(c.get("id"), name=extra["canvas_title"])
                            break
            title = data.get("title", "") if isinstance(data, dict) else ""
            tip = title or os.path.basename(file_path)
            self._notify_edit(f"已加入时间线: {tip}" + (f" ({src})" if src else ""))
            logger.info(f'✅ 素材已添加到时间线: {os.path.basename(file_path)}')
            # 画布回流：可选开启线性补帧（非神经网络）
            if isinstance(data, dict) and data.get("enable_interpolation"):
                try:
                    pm = self._ensure_preview_manager()
                    if pm is not None and hasattr(pm, "set_interpolation_enabled"):
                        pm.set_interpolation_enabled(True)
                        self._notify_edit("已开启线性补帧（画布素材联动）")
                    elif pm is not None and hasattr(pm, "enable_ai_interpolation"):
                        pm.enable_ai_interpolation(True)
                        self._notify_edit("已开启线性补帧（画布素材联动）")
                except Exception as e:
                    logger.debug("开启线性补帧失败: %s", e)
        else:
            msg = f"无法添加素材（文件不存在）: {file_path or '(空路径)'}"
            logger.info(f'⚠️ {msg}')
            try:
                QMessageBox.warning(self, "添加失败", msg)
            except Exception:
                logger.warning("添加失败提示框弹出异常", exc_info=True)
            try:
                self._notify_edit(msg)
            except Exception:
                logger.warning("编辑通知发送失败", exc_info=True)

    def _on_send_clip_to_canvas(self):
        """剪辑选中片段 → AI 画布 outbox。"""
        targets = self._property_target_clips()
        if not targets:
            try:
                from app.modules.lego.modules import show_clear_messagebox as _clear_msgbox
            except Exception:
                def _clear_msgbox(title, text):  # type: ignore
                    QMessageBox.information(self, title, text)
            _clear_msgbox("操作提示", "请先在时间线选中一个片段")
            return
        clip = targets[0]
        path = (clip.get("path") or clip.get("file_path") or "") if isinstance(clip, dict) else ""
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "发送失败", f"片段文件不存在: {path or '(空)'}")
            return
        try:
            from app.core.canvas_bridge import push_editor_to_canvas, get_canvas_bridge
        except ImportError:
            from core.canvas_bridge import push_editor_to_canvas, get_canvas_bridge  # type: ignore
        get_canvas_bridge().start()
        title = clip.get("name") or clip.get("title") or os.path.basename(path)
        try:
            from app.core.editor_canvas_link import outbox_fields_from_clip
        except ImportError:
            from core.editor_canvas_link import outbox_fields_from_clip  # type: ignore
        extra = outbox_fields_from_clip(clip if isinstance(clip, dict) else {})
        res = push_editor_to_canvas(path, title=str(title), source="editor", extra=extra)
        if res.get("success"):
            self._notify_edit(res.get("message") or "已推送到画布")
            self._record_ai_tool_history(res.get("message") or "发送到画布")
            QMessageBox.information(
                self,
                "已发送到画布",
                (res.get("message") or "成功")
                + "\n打开「AI 画布」后会自动落成源文件节点；也可在右下角「来自剪辑」下载。",
            )
        else:
            QMessageBox.warning(self, "发送失败", res.get("message") or "未知错误")

    def _on_canvas_roundtrip_suggest(self):
        """AI 剪辑 ↔ 画布：勾选建议后才推送，不改时间线。"""
        res = self.agent_suggest_canvas_roundtrip(open_ui=True)
        if res.get("cancelled"):
            return
        pushed = int(res.get("pushed") or 0)
        if pushed:
            QMessageBox.information(self, "已推送到画布", res.get("message") or f"已推送 {pushed} 条")
            return
        suggestions = res.get("suggestions") or []
        writes = [x for x in suggestions if x.get("action") in ("send_to_canvas", "refresh_canvas")]
        if not writes:
            QMessageBox.information(self, "AI 联动", "时间线没有可推送到画布的视频片段")

    def _on_files_dropped(self, file_paths):
        """处理时间线拖放导入的文件列表"""
        for file_path in file_paths:
            if os.path.exists(file_path):
                self._add_clip_to_timeline(file_path)
                logger.info(f'✅ 拖放导入成功: {os.path.basename(file_path)}')
            else:
                logger.info(f'⚠️ 无法导入: {file_path}')

    # ─── 字幕 CRUD（实现见 editor_subtitle_panel） ───
    def _refresh_subtitle_list(self):
        from app.modules.lego.editor_subtitle_panel import refresh_subtitle_list
        refresh_subtitle_list(self)

    def _on_subtitle_selected(self, current, previous):
        from app.modules.lego.editor_subtitle_panel import on_subtitle_selected
        on_subtitle_selected(self, current, previous)

    def _save_subtitle_edit(self):
        from app.modules.lego.editor_subtitle_panel import save_subtitle_edit
        save_subtitle_edit(self)

    def _add_subtitle(self):
        from app.modules.lego.editor_subtitle_panel import add_subtitle
        add_subtitle(self)

    def _delete_subtitle(self):
        from app.modules.lego.editor_subtitle_panel import delete_subtitle
        delete_subtitle(self)

    def _find_clip_for_subtitle_range(self, t_in: float, t_out: float):
        from app.modules.lego.editor_subtitle_panel import find_clip_for_subtitle_range
        return find_clip_for_subtitle_range(self, t_in, t_out)

    def _resolve_subtitle_frame_binding(self, sub: dict):
        from app.modules.lego.editor_subtitle_panel import resolve_subtitle_frame_binding
        return resolve_subtitle_frame_binding(self, sub)

    def _apply_ripple_delete_range(
        self,
        t_in: float,
        t_out: float,
        *,
        track=None,
        record: bool = True,
    ):
        from app.modules.lego.editor_subtitle_panel import apply_ripple_delete_range
        return apply_ripple_delete_range(self, t_in, t_out, track=track, record=record)

    def _toggle_subtitle_visibility(self):
        from app.modules.lego.editor_subtitle_panel import toggle_subtitle_visibility
        toggle_subtitle_visibility(self)

    def _split_subtitle(self):
        from app.modules.lego.editor_subtitle_panel import split_subtitle
        split_subtitle(self)

    def _merge_subtitle(self):
        from app.modules.lego.editor_subtitle_panel import merge_subtitle
        merge_subtitle(self)

    def _import_subtitles(self):
        from app.modules.lego.editor_subtitle_panel import import_subtitles
        import_subtitles(self)

    def _export_subtitles(self):
        from app.modules.lego.editor_subtitle_panel import export_subtitles
        export_subtitles(self)

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    def _on_subtitle_generated(self, count: int):
        """主线程回调：字幕生成完成后刷新UI"""
        if hasattr(self, '_ai_task_label'):
            self._ai_task_label.setText("任务: 待机中")
            self._ai_task_label.setStyleSheet("color:#888;font-size:10px;")
        if hasattr(self, '_ai_progress'):
            self._ai_progress.hide()
        self._refresh_subtitle_list()
        self._touch_project_dirty()
        try:
            self._schedule_preview_refresh()
        except Exception as e:
            logger.debug("AI字幕完成后调度预览刷新失败: %s", e)
        QMessageBox.information(self, "AI字幕", f"AI字幕生成完成，共 {count} 条（已按对白识别）")

    # _on_ai_fail / _on_ai_progress 已迁移到 ai_agent_panel.py（AiAgentPanelMixin）

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py
    
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
        styles = {}
        try:
            sm = self._ensure_subtitle_manager()
            if sm:
                subs = sm.list_subtitles() if hasattr(sm, "list_subtitles") else list(getattr(sm, "subtitles", []) or [])
                raw = getattr(sm, "subtitle_styles", None)
                if isinstance(raw, dict):
                    styles = dict(raw)
        except Exception:
            styles = {}
        project_data = {
            "version": "1.2",
            # 必须拷贝：json.dump 遍历期间若画布桥线程 append/清空 _clips，
            # 会抛 RuntimeError 或被写出「半截列表」的损坏工程文件。
            "clips": self._clips_snapshot(),
            "timeline_zoom": self._timeline_zoom,
            "subtitles": subs,
            "subtitle_styles": styles,
            "stickers": list(getattr(self, "_active_stickers", None) or []),
            "master_volume": float(getattr(self, "_master_volume", 1.0) or 1.0),
            "sequence": (
                self._sequence_format.to_dict()
                if getattr(self, "_sequence_format", None) is not None
                else SequenceFormat.default().to_dict()
            ),
            "export_time": datetime.now().isoformat()
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            import json
            json.dump(project_data, f, ensure_ascii=False, indent=2)
        
        self._project_dirty = False
        if show_message:
            QMessageBox.information(self, "保存完成", f"项目已保存到:\n{output_path}")

    def _touch_project_dirty(self):
        """标记工程已改，并启动 3s 防抖自动保存。"""
        self._project_dirty = True
        t = getattr(self, "_autosave_debounce", None)
        if t is not None:
            t.start()

    def _autosave_project(self):
        """静默自动保存到 autosave/latest.timeline（仅 dirty 时写盘）。"""
        if not getattr(self, "_project_dirty", False):
            return
        has_clips = bool(getattr(self, "_clips", None))
        has_subs = False
        try:
            sm = getattr(self, "_subtitle_manager", None)
            if sm and hasattr(sm, "list_subtitles"):
                has_subs = bool(sm.list_subtitles())
        except Exception:
            has_subs = False
        if not has_clips and not has_subs and not getattr(self, "_active_stickers", None):
            self._project_dirty = False
            return
        try:
            autosave_dir = os.path.join(os.getcwd(), "autosave")
            os.makedirs(autosave_dir, exist_ok=True)
            latest = os.path.join(autosave_dir, "latest.timeline")
            self.export_project(latest, show_message=False)
            self._project_dirty = False
            deb = getattr(self, "_autosave_debounce", None)
            if deb is not None:
                deb.stop()
            self._notify_edit("已自动保存")
        except Exception as e:
            logger.error(f'自动保存失败: {e}')

    def create_blank_project(self, name: str) -> str:
        """新建空白工程并立刻落盘（V4.43.14，供首页 CTA；缘由见 session_state 模块头）"""
        from . import session_state as ss
        path = ss.new_project_path(name)
        with self._clips_lock:
            self._timeline_store.clear()
        self._project_path, self._project_dirty = path, False
        self.export_project(path, show_message=False)
        return path

    def _maybe_restore_autosave(self):
        """**仅在上次「异常退出」时**询问是否恢复自动保存（V4.43.13）。

        策略全在 `autosave_recovery` 模块头注释 —— 对标 Premiere（仅崩溃弹、只弹一次）/
        Office（正常关闭即删恢复文件）/ NightOS（`awake` 标记残留即判崩溃）。
        """
        if getattr(self, "_autosave_prompted", False):
            return
        self._autosave_prompted = True
        if getattr(self, "_clips", None):
            return

        from . import autosave_recovery as ar

        if not ar.begin_session():          # 上次正常关闭 ⇒ 不打扰
            return
        mtime = ar.take_pending()           # 存档缺失 / 过期 / 已问过 ⇒ None
        if mtime is None:
            return

        reply = QMessageBox.question(
            self,
            "恢复自动保存",
            f"上次未正常退出，发现自动保存的工程：\n"
            f"autosave/latest.timeline\n修改时间：{ar.describe_mtime(mtime)}\n\n是否恢复？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        ar.remember_prompted(mtime)         # 无论选是/否，这一版都不再问
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.import_project(ar.latest_path())
            except Exception as ie:
                QMessageBox.warning(self, "恢复失败", f"无法恢复自动保存工程：\n{ie}")

    def _on_clip_trim_committed(self, clip_data):
        """片段拖拽/裁剪松手：同步内核、撤销栈并标记脏"""
        if not clip_data:
            return
        # 多选批量平移：一条 compound undo
        if isinstance(clip_data, dict) and clip_data.get("_batch_move"):
            items = clip_data.get("items") or []
            steps = []
            for it in items:
                cid = it.get("clip_id")
                clip = it.get("clip")
                before = it.get("before")
                after = it.get("after")
                if clip is None:
                    clip = next((c for c in self._clips if c.get("id") == cid), None)
                if clip is None or not before or not after:
                    continue
                # 刀4：合并到真相源改走 store API（原 for i,c in enumerate 手工 merge 已收敛）
                patch = {
                    k: after[k] for k in ("start_time", "track", "duration", "in_point", "out_point")
                    if k in after
                }
                if patch:
                    self._timeline_store.set_fields(cid, **patch)
                live = self._timeline_store.find_by_id(cid)
                if live is not None:
                    clip = live
                steps.append({
                    "type": "edit_clip",
                    "clip_id": cid,
                    "before": before,
                    "after": after,
                })
                # 联动片也进 compound，避免 Ctrl+Z 只回视频不回音频
                try:
                    link_steps = self._linked_av_edit_steps(clip, before=before)
                    steps.extend(link_steps)
                    self._sync_linked_av_timing(clip, before=before)
                except Exception as e:
                    logger.info(f'linked AV sync failed: {e}')
            if steps:
                self._record_action({"type": "compound", "steps": steps})
            if items:
                primary = items[0].get("clip")
                if primary is not None:
                    self._current_clip = primary
            self._touch_project_dirty()
            try:
                self._sync_kernel_timeline()
                self._sync_timeline_widget_state()
                self._refresh_preview_to_current_clip()
            except Exception as e:
                logger.info(f'batch move sync failed: {e}')
            self._notify_edit(f"已批量移动 {len(steps)} 个片段")
            return

        before = None
        if isinstance(clip_data, dict) and "_edit_before" in clip_data:
            before = clip_data.pop("_edit_before", None)
        cid = clip_data.get("id")
        # 刀4：字段合并走 store API（保持 live dict 同一对象，widget/撤销读点不漂）
        live = self._timeline_store.find_by_id(cid)
        if live is not None:
            self._timeline_store.set_fields(
                cid, **{k: v for k, v in clip_data.items() if k != "_edit_before"})
            clip_data = live
        else:
            self._timeline_store.add(clip_data)
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
                steps = [{
                    "type": "edit_clip",
                    "clip_id": cid,
                    "before": before,
                    "after": after,
                }]
                try:
                    steps.extend(self._linked_av_edit_steps(clip_data, before=before))
                except Exception:
                    logger.debug("联动音频编辑步骤扩展失败", exc_info=True)
                if len(steps) == 1:
                    self._record_action(steps[0])
                else:
                    self._record_action({"type": "compound", "steps": steps})
        # 联动音视频 timing 同步（撤销步骤已在同步前快照）
        try:
            self._sync_linked_av_timing(clip_data, before=before)
        except Exception as e:
            logger.info(f'linked AV sync failed: {e}')
        self._touch_project_dirty()
        try:
            self._sync_kernel_timeline()
            self._sync_timeline_widget_state()
            self._refresh_preview_to_current_clip()
        except Exception as e:
            logger.info(f'trim commit sync failed: {e}')
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
        # 工程画幅 SSOT（缺省仍漫剧竖屏；无任何线索时等 clips 加载后推断）
        _sequence_needs_infer = False
        try:
            seq_raw = project_data.get("sequence")
            if isinstance(seq_raw, dict):
                self._sequence_format = SequenceFormat.from_dict(seq_raw)
            else:
                # 旧工程：尝试从顶层 resolution/aspect 恢复
                res = project_data.get("resolution") or project_data.get("export_resolution")
                asp = project_data.get("aspect") or project_data.get("aspect_ratio")
                if res or asp:
                    try:
                        w, h = parse_resolution(str(res)) if res else (1080, 1920)
                    except Exception:
                        w, h = 1080, 1920
                    aspect = str(asp or aspect_from_size(w, h))
                    w, h = normalize_size(aspect, w, h)
                    self._sequence_format = SequenceFormat(
                        aspect=aspect, width=w, height=h, fit_mode="contain",
                    )
                else:
                    self._sequence_format = SequenceFormat.default()
                    _sequence_needs_infer = True
            self._apply_sequence_format_to_export_combos()
            self._refresh_preview_aspect_badge()
        except Exception as e:
            logger.error(f'导入工程画幅失败: {e}')
            self._sequence_format = SequenceFormat.default()
            _sequence_needs_infer = True
        try:
            if getattr(self, "_audio_output", None):
                self._audio_output.setVolume(min(1.0, self._master_volume))
            msl = getattr(self, "_master_volume_slider", None)
            if msl is not None:
                msl.blockSignals(True)
                msl.setValue(int(round(self._master_volume * 100)))
                msl.blockSignals(False)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        # ⚠️ 整段持有 _clips_lock：「先清空再逐个 append」若不原子，
        # 画布桥线程（agent_replace_timeline_clips）或 autosave 会读到中间态。
        lock = getattr(self, "_clips_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._clips_lock = lock
        with lock:
            self._timeline_store.clear()
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
                self._timeline_store.add(clip)
                if hasattr(self, '_timeline_widget') and self._timeline_widget:
                    widget = self._timeline_widget.add_clip(clip, int(clip.get("track", 0)))
                    if widget is not None:
                        self._clip_widgets.append(widget)
                        if clip.get("id"):
                            self._clip_id_to_widget[clip["id"]] = widget
                if not self._current_clip:
                    self._current_clip = clip

            # 旧工程可能只存了视频片：补联动音频，否则音频轨无波形
            self._ensure_linked_audio_clips()
            # 修复「视频轨被裁成 ~8s、同文件音频仍是全长」导致播放后半只剩声音
            try:
                self._heal_linked_av_duration_mismatch()
            except Exception as e:
                logger.error(f'联动音画时长修复失败: {e}')

        # 无 sequence / resolution 的旧工程：按首个视频片推断画幅
        if _sequence_needs_infer:
            try:
                if self._infer_sequence_from_clips():
                    self._apply_sequence_format_to_export_combos()
                    self._apply_sequence_format_to_preview()
                    self._refresh_preview_aspect_badge()
            except Exception as e:
                logger.error(f'推断工程画幅失败: {e}')

        # 恢复字幕
        try:
            sm = self._ensure_subtitle_manager()
            subs = project_data.get("subtitles") or []
            if sm and hasattr(sm, "subtitles"):
                sm.subtitles = list(subs)
            styles = project_data.get("subtitle_styles") or {}
            if sm and isinstance(styles, dict) and hasattr(sm, "subtitle_styles"):
                # 保留默认键，覆盖工程内样式
                merged = dict(getattr(sm, "subtitle_styles", {}) or {})
                merged.update(styles)
                sm.subtitle_styles = merged
            self._refresh_subtitle_list()
        except Exception as e:
            logger.error(f'导入字幕失败: {e}')

        # 恢复贴纸
        try:
            raw_stk = project_data.get("stickers") or []
            self._active_stickers = [dict(s) for s in raw_stk if isinstance(s, dict)]
            self._refresh_sticker_list_ui()
        except Exception as e:
            logger.error(f'导入贴纸失败: {e}')
            self._active_stickers = []

        # 主选优先视频片（避免首条是联动音频时预览走偏）
        try:
            for c in self._clips:
                if str(c.get("type", "")).lower() != "audio" and c.get("path"):
                    self._current_clip = c
                    break
        except Exception:
            logger.debug("剪辑定位失败", exc_info=True)

        self._sync_kernel_timeline()
        if hasattr(self, "_timeline_widget") and hasattr(self._timeline_widget, "relayout_clips"):
            self._timeline_widget.relayout_clips()
        # 立刻刷真首帧；对话框关闭后再刷一次（避免被占位/空帧盖住）
        self._force_show_first_video_frame()
        try:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._force_show_first_video_frame)
            QTimer.singleShot(200, self._force_show_first_video_frame)
        except Exception:
            logger.debug("首帧定时显示失败", exc_info=True)
        n_sub = 0
        try:
            sm = getattr(self, "_subtitle_manager", None)
            n_sub = len(sm.list_subtitles()) if sm and hasattr(sm, "list_subtitles") else 0
        except Exception:
            n_sub = 0
        QMessageBox.information(
            self, "导入完成",
            f"已导入 {len(self._clips)} 个片段" + (f"、{n_sub} 条字幕" if n_sub else ""),
        )
        self._force_show_first_video_frame()
    
    # ===== 快捷键增强 =====
    def _install_additional_shortcuts(self):
        """安装额外的快捷键（与工具栏共用 editor_ux_commands）"""
        from app.modules.lego.editor_ux_commands import bind_action

        # Ctrl+I: 导入视频
        self._import_shortcut = QShortcut(QKeySequence("Ctrl+I"), self)
        self._import_shortcut.activated.connect(bind_action(self, "import"))
        
        # Ctrl+E: 导出视频
        self._export_shortcut = QShortcut(QKeySequence("Ctrl+E"), self)
        self._export_shortcut.activated.connect(bind_action(self, "export"))
        
        # Ctrl+S: 保存项目
        self._save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self._save_shortcut.activated.connect(bind_action(self, "save_project"))

        # Ctrl+O: 打开项目
        self._open_shortcut = QShortcut(QKeySequence("Ctrl+O"), self)
        self._open_shortcut.activated.connect(bind_action(self, "open_project"))
        
        # Space: 播放/暂停
        self._play_pause_shortcut = QShortcut(QKeySequence("Space"), self)
        self._play_pause_shortcut.activated.connect(bind_action(self, "play_pause"))
        
        # Delete: 删除选中片段
        self._delete_shortcut = QShortcut(QKeySequence("Delete"), self)
        self._delete_shortcut.activated.connect(bind_action(self, "delete"))
        
        # Ctrl+D: 复制片段
        self._duplicate_shortcut = QShortcut(QKeySequence("Ctrl+D"), self)
        self._duplicate_shortcut.activated.connect(self._copy_clip)

        # 精细编辑：←/→ 逐帧；Shift+←/→ 移动选中片段一帧
        self._frame_prev_shortcut = QShortcut(QKeySequence("Left"), self)
        self._frame_prev_shortcut.activated.connect(lambda: self._step_playhead_frames(-1))
        self._frame_next_shortcut = QShortcut(QKeySequence("Right"), self)
        self._frame_next_shortcut.activated.connect(lambda: self._step_playhead_frames(1))
        self._nudge_left_shortcut = QShortcut(QKeySequence("Shift+Left"), self)
        self._nudge_left_shortcut.activated.connect(lambda: self._nudge_selected_clip_frames(-1))
        self._nudge_right_shortcut = QShortcut(QKeySequence("Shift+Right"), self)
        self._nudge_right_shortcut.activated.connect(lambda: self._nudge_selected_clip_frames(1))
        self._zoom_in_shortcut = QShortcut(QKeySequence("Ctrl+="), self)
        self._zoom_in_shortcut.activated.connect(
            lambda: self._set_timeline_zoom(min(3000, int(getattr(self._timeline_widget, "_zoom", 100)) + 50))
        )
        self._zoom_in_shortcut2 = QShortcut(QKeySequence("Ctrl++"), self)
        self._zoom_in_shortcut2.activated.connect(
            lambda: self._set_timeline_zoom(min(3000, int(getattr(self._timeline_widget, "_zoom", 100)) + 50))
        )
        self._zoom_out_shortcut = QShortcut(QKeySequence("Ctrl+-"), self)
        self._zoom_out_shortcut.activated.connect(
            lambda: self._set_timeline_zoom(max(10, int(getattr(self._timeline_widget, "_zoom", 100)) - 50))
        )

        # ── 专业剪辑快捷键 ──
        # Ctrl+K / C：在播放头位置切分片段（C 在输入框内不抢键）
        self._split_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._split_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._split_shortcut.activated.connect(bind_action(self, "cut"))
        self._razor_shortcut = QShortcut(QKeySequence("C"), self)
        self._razor_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._razor_shortcut.activated.connect(self._razor_cut_shortcut)

        # Ctrl+0：时间线自适应缩放（zoom to fit）
        self._zoom_fit_shortcut = QShortcut(QKeySequence("Ctrl+0"), self)
        self._zoom_fit_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._zoom_fit_shortcut.activated.connect(self._zoom_timeline_to_fit)

        # I / O：序列级入出点标记
        self._mark_in_shortcut = QShortcut(QKeySequence("I"), self)
        self._mark_in_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._mark_in_shortcut.activated.connect(self._mark_sequence_in)

        self._mark_out_shortcut = QShortcut(QKeySequence("O"), self)
        self._mark_out_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._mark_out_shortcut.activated.connect(self._mark_sequence_out)

        self._clear_in_out_shortcut = QShortcut(QKeySequence("Ctrl+Shift+X"), self)
        self._clear_in_out_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._clear_in_out_shortcut.activated.connect(self._clear_sequence_in_out)

        # Shift+Delete：消除所有轨道间 >50ms 的间隙（ripple）
        self._ripple_delete_gaps_shortcut = QShortcut(
            QKeySequence("Shift+Delete"), self
        )
        self._ripple_delete_gaps_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._ripple_delete_gaps_shortcut.activated.connect(bind_action(self, "close_gap"))

        # 预览档位快捷：1/2/3 → 1/4 · 1/2 · 100%（无修饰键时生效）
        self._pq_quarter_shortcut = QShortcut(QKeySequence("Ctrl+1"), self)
        self._pq_quarter_shortcut.activated.connect(
            bind_action(self, "set_preview_quality", quality="low")
        )
        self._pq_half_shortcut = QShortcut(QKeySequence("Ctrl+2"), self)
        self._pq_half_shortcut.activated.connect(
            bind_action(self, "set_preview_quality", quality="medium")
        )
        self._pq_full_shortcut = QShortcut(QKeySequence("Ctrl+3"), self)
        self._pq_full_shortcut.activated.connect(
            bind_action(self, "set_preview_quality", quality="high")
        )
    
    def _default_projects_dir(self) -> str:
        """默认工程目录（首页"最近项目"/统计只扫这个目录，保持一致才能互通）"""
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "projects")
        os.makedirs(d, exist_ok=True)
        return d

    def _save_project(self):
        """保存项目（仅写工程文件，不触发字幕生成）"""
        path, _ = QFileDialog.getSaveFileName(self, "保存项目", self._default_projects_dir(), "项目文件 (*.timeline)")
        if not path:
            return
        if not path.endswith(".timeline"):
            path += ".timeline"
        self.export_project(path)

    def _open_project(self):
        """打开已保存的工程并重建时间线控件"""
        path, _ = QFileDialog.getOpenFileName(self, "打开项目", self._default_projects_dir(), "项目文件 (*.timeline);;所有文件 (*.*)")
        if path:
            self.import_project(path)




    
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
                logger.error(f'同步片段到内核失败: {e}')
        try:
            real_timeline_manager._recalculate_duration(tl)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)

    def _burn_subtitles_if_any(self, video_path: str) -> str:
        """若有字幕则烧录到成片（实现见 editor_burn）。"""
        from app.modules.lego.editor_burn import burn_subtitles_if_any
        return burn_subtitles_if_any(self, video_path)


    def _resolve_clip_media_path(self, path: str) -> str:
        """相对路径 → 可打开的绝对路径（工程根 / cwd）。"""
        if not path:
            return ""
        if os.path.isfile(path):
            return os.path.normpath(os.path.abspath(path))
        candidates = [
            os.path.normpath(os.path.join(os.getcwd(), path)),
            os.path.normpath(os.path.join(_app_root, path)),
            os.path.normpath(os.path.join(_app_root, path.replace("/", os.sep))),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return os.path.abspath(c)
        return path

    # ── P0：预览档位 / 代理媒体 ──────────────────────────────

    def _on_preview_quality_combo(self, _index: int = 0):
        combo = getattr(self, "_preview_quality_combo", None)
        if combo is None:
            return
        q = combo.currentData()
        self.set_user_preview_quality(q)

    def set_user_preview_quality(self, quality) -> None:
        """设置用户预览档位（1/4·1/2·100%）；拖 scrub/播放中只更新恢复目标。"""
        try:
            from app.modules.lego.editor_preview_ux import normalize_preview_quality
            q = normalize_preview_quality(quality)
        except Exception:
            q = str(quality or "medium")
            if q not in ("low", "medium", "high"):
                q = "medium"
        self._user_preview_quality = q
        # 同步下拉框
        combo = getattr(self, "_preview_quality_combo", None)
        if combo is not None:
            for i in range(combo.count()):
                if combo.itemData(i) == q:
                    if combo.currentIndex() != i:
                        combo.blockSignals(True)
                        combo.setCurrentIndex(i)
                        combo.blockSignals(False)
                    break
        playing = bool(getattr(self, "_timeline_playing", False))
        scrubbing = bool(getattr(self, "_preview_scrubbing", False))
        self._preview_quality_before_scrub = q
        self._preview_quality_before_play = q
        if playing or scrubbing:
            return
        pm = getattr(self, "_preview_manager", None)
        if pm is not None and hasattr(pm, "set_preview_quality"):
            try:
                pm.set_preview_quality(q)
                self._refresh_preview_with_effects()
            except Exception as e:
                logger.debug("应用预览档位失败: %s", e)

    def set_proxy_preview_enabled(self, enabled: bool) -> None:
        """开关预览代理；导出始终用原片。"""
        self._proxy_preview_enabled = bool(enabled)
        btn = getattr(self, "_proxy_toggle_btn", None)
        if btn is not None and btn.isChecked() != bool(enabled):
            btn.blockSignals(True)
            btn.setChecked(bool(enabled))
            btn.blockSignals(False)
        pm = getattr(self, "_preview_manager", None)
        if pm is not None and hasattr(pm, "set_proxy_preview_enabled"):
            try:
                pm.set_proxy_preview_enabled(bool(enabled))
            except Exception:
                logger.debug("代理预览开关失败", exc_info=True)
        # 切换后重开当前预览源
        try:
            self._preview_source_path = None
            if not getattr(self, "_timeline_playing", False):
                self._refresh_preview_with_effects()
        except Exception as e:
            logger.debug("代理开关后刷新预览失败: %s", e)

    def _init_proxy_media_manager(self):
        """懒初始化代理管理器；读取设置中的缓存目录。"""
        try:
            from app.core.proxy_media import get_proxy_manager, ProxyStrategy
            mgr = get_proxy_manager(strategy=ProxyStrategy.AUTO)
            # 可选：从环境/配置读缓存盘
            cache_dir = os.environ.get("SHIGUANG_PROXY_CACHE") or os.environ.get(
                "PROXY_MEDIA_DIR"
            )
            if not cache_dir:
                try:
                    cfg_path = os.path.join(_app_root, "config.json")
                    if os.path.isfile(cfg_path):
                        with open(cfg_path, "r", encoding="utf-8") as f:
                            cfg = json.load(f) or {}
                        cache_dir = (
                            (cfg.get("editor") or {}).get("proxy_cache_dir")
                            or cfg.get("proxy_cache_dir")
                        )
                except Exception:
                    cache_dir = None
            if cache_dir:
                mgr.set_cache_dir(str(cache_dir))
            try:
                mgr.clear_idle_cache(14.0)
            except Exception:
                logger.debug("空闲缓存清理失败", exc_info=True)
            self._proxy_manager = mgr
            logger.info("[proxy] 管理器就绪 cache=%s", mgr.cache_dir)
        except Exception as e:
            logger.debug("初始化代理管理器失败: %s", e)
            self._proxy_manager = None

    def _get_proxy_manager(self):
        mgr = getattr(self, "_proxy_manager", None)
        if mgr is not None:
            return mgr
        try:
            self._init_proxy_media_manager()
        except Exception:
            logger.debug("代理媒体管理器初始化失败", exc_info=True)
        return getattr(self, "_proxy_manager", None)

    def _maybe_proxy_preview_path(self, src: str) -> str:
        """预览路径：开启代理且文件就绪则返回代理，否则原片。"""
        if not src or not getattr(self, "_proxy_preview_enabled", True):
            return src
        abs_src = self._resolve_clip_media_path(src) or src
        # 片段上已挂 proxy_path
        for c in getattr(self, "_clips", None) or []:
            if not isinstance(c, dict):
                continue
            cpath = self._resolve_clip_media_path(str(c.get("path") or ""))
            if self._media_paths_equal(cpath, abs_src):
                proxy = str(c.get("proxy_path") or "")
                if proxy and os.path.isfile(proxy):
                    return proxy
                break
        mgr = self._get_proxy_manager()
        if mgr is None:
            return abs_src
        try:
            return mgr.resolve_for_preview(abs_src) or abs_src
        except Exception:
            return abs_src

    def _kick_proxy_for_path(self, source_path: str, width: int = 0, height: int = 0):
        """后台生成代理；完成后写回同 path 的所有 clip.proxy_path。"""
        if not source_path or not getattr(self, "_proxy_preview_enabled", True):
            return
        mgr = self._get_proxy_manager()
        if mgr is None:
            return
        abs_src = self._resolve_clip_media_path(source_path) or source_path
        if not os.path.isfile(abs_src):
            return
        try:
            if not mgr.should_generate_proxy(abs_src, width=width, height=height):
                return
            if mgr.has_proxy(abs_src):
                self._on_proxy_ready(True, mgr.get_proxy_path(abs_src), abs_src)
                return
        except Exception as e:
            logger.debug("代理判定失败: %s", e)
            return

        def _done(ok: bool, proxy_path: str, src=abs_src):
            # 回到主线程写 clip（默认参数固定闭包，避免晚到回调读到旧值）
            try:
                QTimer.singleShot(
                    0,
                    lambda o=ok, p=proxy_path, s=src: self._on_proxy_ready(o, p, s),
                )
            except Exception:
                self._on_proxy_ready(ok, proxy_path, src)

        try:
            mgr.generate_async(abs_src, on_done=_done)
            self._notify_edit("正在后台生成代理媒体…")
        except Exception as e:
            logger.debug("启动代理生成失败: %s", e)

    def _on_proxy_ready(self, ok: bool, proxy_path: str, source_path: str):
        if not ok or not proxy_path or not os.path.isfile(proxy_path):
            if not ok:
                logger.warning("[proxy] 生成失败: %s", source_path)
            return
        try:
            from app.modules.lego.editor_preview_ux import attach_proxy_path
            n = 0
            for c in getattr(self, "_clips", None) or []:
                if not isinstance(c, dict):
                    continue
                cpath = self._resolve_clip_media_path(str(c.get("path") or ""))
                if self._media_paths_equal(cpath, source_path):
                    if attach_proxy_path(c, proxy_path):
                        n += 1
            if n:
                self._notify_edit(f"代理已就绪（{n} 片段），预览将自动切换")
                # 强制下次 open 走代理
                self._preview_source_path = None
                # 胶片条改走代理路径：清 key 并唤醒可见片重采
                tw = getattr(self, "_timeline_widget", None)
                if tw is not None and hasattr(tw, "all_clip_widgets"):
                    for w in tw.all_clip_widgets():
                        try:
                            w._thumb_key = None
                            w._thumbnail_cache = []
                            w._scaled_thumb_cache = {}
                            # 代理已就绪：取消等待、立刻重采
                            w._filmstrip_proxy_wait_done = True
                            tmr = getattr(w, "_filmstrip_proxy_timer", None)
                            if tmr is not None and tmr.isActive():
                                tmr.stop()
                            if hasattr(w, "_request_thumbnail_refresh"):
                                w._request_thumbnail_refresh()
                        except Exception:
                            continue
                if not getattr(self, "_timeline_playing", False):
                    self._refresh_preview_with_effects()
        except Exception as e:
            logger.debug("代理就绪回写失败: %s", e)

    def _pick_preview_video_clip(self):
        """预览用片：优先当前视频片，否则时间线上第一个有 path 的非纯音频片。"""
        cur = getattr(self, "_current_clip", None)
        if isinstance(cur, dict) and cur.get("path"):
            if str(cur.get("type", "")).lower() != "audio":
                return cur
            # 联动音频：找同 path 视频
            path = cur.get("path")
            for c in getattr(self, "_clips", None) or []:
                if c.get("path") == path and str(c.get("type", "")).lower() != "audio":
                    return c
            return cur  # 同文件仍可解画
        for c in getattr(self, "_clips", None) or []:
            if not c.get("path"):
                continue
            if str(c.get("type", "")).lower() == "audio":
                # 视频封装的音频轨也可解画
                ext = os.path.splitext(str(c.get("path")))[1].lower()
                if ext in (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"):
                    return c
                continue
            return c
        return None

    def _media_paths_equal(self, a: Optional[str], b: Optional[str]) -> bool:
        """比较媒体路径是否同一文件（忽略大小写/相对绝对差异）。"""
        if not a or not b:
            return False
        if a == b:
            return True
        try:
            return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
        except Exception:
            return False

    def _ensure_preview_source_open(
        self,
        pm,
        src: str,
        *,
        for_scrub: bool = False,
        preload: bool = False,
    ) -> bool:
        """打开预览源；已打开同一文件则复用，避免反复关开 capture / 帧数探针。"""
        if pm is None or not src:
            return False
        # 预览可走代理；导出仍用 clip.path 原片
        open_src = self._maybe_proxy_preview_path(src)
        try:
            if self._media_paths_equal(getattr(pm, "_video_source", None), open_src) and getattr(
                pm, "_video_capture", None
            ) is not None:
                self._preview_source_path = open_src
                return True
        except Exception:
            logger.debug("预览源路径设置失败", exc_info=True)
        try:
            ok = bool(pm.open_video(open_src, preload=preload, for_scrub=for_scrub))
            if ok:
                self._preview_source_path = open_src
            return ok
        except Exception:
            return False

    def _force_show_first_video_frame(self) -> bool:
        """强制显示当前工程视频真首帧（in_point），禁止留下 No Signal 占位。"""
        clip = self._pick_preview_video_clip()
        if not clip:
            return False
        src = self._resolve_clip_media_path(str(clip.get("path") or ""))
        if not src or not os.path.isfile(src):
            return False
        try:
            self._current_clip = clip
            self._video_source = src
            clip["path"] = src  # 写回绝对路径，后续 open 更稳
            in_p = float(clip.get("in_point", 0) or 0)
            st = float(clip.get("start_time", 0) or 0)
            pm = self._ensure_preview_manager()
            if pm is None:
                return False
            if not self._ensure_preview_source_open(pm, src, for_scrub=True):
                return False
            self._preview_source_path = src
            # in_point≈0 用 get_first_frame；否则 seek
            if in_p <= 1e-4 and hasattr(pm, "get_first_frame"):
                frame = pm.get_first_frame()
            else:
                frame = pm.get_frame_at(in_p)
            if frame is None and hasattr(pm, "get_first_frame"):
                frame = pm.get_first_frame()
            self._playhead_position = st
            if frame is not None:
                # 只刷一次：避免 _on_preview_frame + _render_timeline_frame 双开销
                self._on_preview_frame(frame)
            else:
                try:
                    self._render_timeline_frame(st)
                except Exception:
                    logger.debug("时间线帧渲染失败", exc_info=True)
            player = getattr(self, "_media_player", None)
            if player is not None:
                from PyQt6.QtCore import QUrl
                player.setSource(QUrl.fromLocalFile(src))
                player.setPosition(int(max(0.0, in_p) * 1000))
            try:
                self._update_time_display()
                tw = getattr(self, "_timeline_widget", None)
                if tw is not None:
                    tw.set_playhead_position(st)
                    total = self._timeline_total_duration()
                    if hasattr(tw, "set_total_duration") and total > 0:
                        tw.set_total_duration(max(total + 2.0, total * 1.02))
            except Exception:
                logger.debug("总时长显示失败", exc_info=True)
            return frame is not None
        except Exception as e:
            logger.debug("强制首帧预览失败: %s", e)
            return False

    def _refresh_preview_to_current_clip(self, *, jump_playhead: bool = False):
        """让预览反映当前选中片段的 in/out 区间，使工具栏编辑在预览中可见。

        jump_playhead=False（默认点选）：不把播放头拽到片头，避免改属性时画面/头乱跳。
        jump_playhead=True：定位到片头（导入/强制刷新等路径）。
        """
        clip = self._pick_preview_video_clip() or getattr(self, "_current_clip", None)
        pm = self._ensure_preview_manager()
        if not clip or pm is None:
            return
        try:
            src = self._resolve_clip_media_path(str(clip.get("path") or ""))
            if not src or not os.path.isfile(src):
                return
            in_p = float(clip.get("in_point", 0) or 0)
            out_p = float(clip.get("out_point", 0) or 0)
            st = float(clip.get("start_time", 0) or 0)
            clip_dur = float(clip.get("duration", 0) or 0)
            if out_p <= in_p and clip_dur > 0:
                out_p = in_p + clip_dur
            # 缓存键：片段 id + 裁剪区间，未变则不重复刷新（先判再 probe）
            seg_key = (clip.get("id"), round(in_p, 3), round(out_p, 3), bool(jump_playhead))
            if getattr(self, "_preview_seg_key", None) == seg_key:
                if getattr(self, "_preview_label", None) is not None:
                    pm0 = getattr(self, "_preview_label", None).pixmap()
                    if pm0 is not None and not pm0.isNull():
                        return
            self._preview_seg_key = seg_key
            self._ensure_preview_source_open(pm, src, for_scrub=True)
            self._preview_source_path = src
            self._video_source = src

            speed = max(0.05, float(clip.get("speed", 1.0) or 1.0))
            t = float(getattr(self, "_playhead_position", 0) or 0)
            if jump_playhead:
                self._playhead_position = st
                source_t = in_p
                try:
                    tw = getattr(self, "_timeline_widget", None)
                    if tw is not None:
                        tw.set_playhead_position(st)
                except Exception:
                    logger.debug("播放头位置设置失败", exc_info=True)
            elif st <= t < st + max(clip_dur, 0.05):
                try:
                    from app.core.speed_ramping import source_time_for_clip_at_timeline
                    source_t = source_time_for_clip_at_timeline(clip, t)
                except Exception:
                    source_t = max(0.0, (t - st) * speed + in_p)
            else:
                source_t = in_p

            if source_t <= 1e-4 and hasattr(pm, "get_first_frame"):
                frame = pm.get_first_frame()
            else:
                frame = pm.get_frame_at(source_t)
            if frame is None and hasattr(pm, "get_first_frame"):
                frame = pm.get_first_frame()
            if frame is not None:
                self._on_preview_frame(frame)
            else:
                self._force_show_first_video_frame()
            player = getattr(self, "_media_player", None)
            if player is not None:
                from PyQt6.QtCore import QUrl
                if player.source().isEmpty() or not self._media_paths_equal(
                    getattr(self, "_video_source", ""), src
                ):
                    player.setSource(QUrl.fromLocalFile(src))
                player.setPosition(int(max(0.0, source_t) * 1000))
        except Exception as e:
            logger.error(f'预览片段刷新失败: {e}')
            self._preview_seg_key = None
            try:
                self._force_show_first_video_frame()
            except Exception:
                logger.debug("首帧显示失败", exc_info=True)

    # [Mixin] 已迁移至 editor_ui_builder_mixin.py
    @staticmethod
    def _safe_set_text(label, text: str):
        """安全设置 QLabel 文本，防止 C++ 对象已被删除时崩溃"""
        try:
            label.setText(text)
        except (RuntimeError, AttributeError) as _e:
            logger.warning("操作异常（已忽略）: %s", _e)

    # [Mixin] 已迁移至 editor_ui_builder_mixin.py
    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] 已迁移至 editor_ai_process_mixin.py
    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] 已迁移至 editor_ai_process_mixin.py
    # [Mixin] 已迁移至 editor_ui_builder_mixin.py
    # ────────────── M2 漫剧导出预设 ──────────────

    _DRAMA_PLATFORM_PRESETS = {
        "抖音": ("1080x1920", "9:16", "3000k", "30fps"),
        "快手": ("1080x1920", "9:16", "3000k", "30fps"),
        "小红书": ("1080x1920", "9:16", "3000k", "30fps"),
        "视频号": ("1080x1920", "9:16", "3000k", "30fps"),
        "B站": ("1920x1080", "16:9", "5000k", "30fps"),
        "默认": ("1080x1920", "9:16", "3000k", "30fps"),
    }

    def _set_export_combo_text(self, attr: str, text: str) -> None:
        cmb = getattr(self, attr, None)
        if cmb is None:
            return
        idx = cmb.findText(text)
        if idx >= 0:
            cmb.setCurrentIndex(idx)
        elif text:
            cmb.addItem(text)
            cmb.setCurrentIndex(cmb.findText(text))

    def _apply_sequence_format_to_export_combos(self) -> None:
        """SSOT → 导出下拉（不触发递归）。"""
        sf = getattr(self, "_sequence_format", None) or SequenceFormat.default()
        widgets = [
            getattr(self, "_resolution_var", None),
            getattr(self, "_aspect_var", None),
            getattr(self, "_fit_mode_var", None),
        ]
        for w in widgets:
            if w is not None:
                w.blockSignals(True)
        try:
            self._set_export_combo_text("_resolution_var", sf.resolution_str())
            self._set_export_combo_text("_aspect_var", sf.aspect)
            fit_cmb = getattr(self, "_fit_mode_var", None)
            if fit_cmb is not None:
                want = (sf.fit_mode or "contain").strip().lower()
                idx = fit_cmb.findData(want)
                if idx < 0:
                    idx = 0 if want != "cover" else 1
                fit_cmb.setCurrentIndex(max(0, idx))
        finally:
            for w in widgets:
                if w is not None:
                    w.blockSignals(False)

    def _sync_sequence_format_from_export_combos(self, *, prefer_aspect: bool = False) -> None:
        """导出下拉 → SSOT。prefer_aspect=True 时按比例重算像素。"""
        aspect = "9:16"
        res = "1080x1920"
        try:
            if getattr(self, "_aspect_var", None) is not None:
                aspect = self._aspect_var.currentText() or aspect
            if getattr(self, "_resolution_var", None) is not None:
                res = self._resolution_var.currentText() or res
        except Exception:
            logger.debug("分辨率变量读取失败", exc_info=True)
        try:
            w, h = parse_resolution(res)
        except Exception:
            w, h = 1080, 1920
        fit = "contain"
        fit_cmb = getattr(self, "_fit_mode_var", None)
        if fit_cmb is not None:
            data = fit_cmb.currentData()
            if data in ("contain", "cover"):
                fit = str(data)
            elif "裁切" in (fit_cmb.currentText() or ""):
                fit = "cover"
        else:
            old = getattr(self, "_sequence_format", None)
            if old is not None:
                fit = old.fit_mode or "contain"
        if prefer_aspect:
            w, h = normalize_size(aspect, w, h)
        else:
            # 分辨率优先：吸附比例文案
            try:
                aspect = aspect_from_size(w, h)
            except Exception:
                logger.debug("宽高比计算失败", exc_info=True)
            w, h = normalize_size(aspect, w, h)
        self._sequence_format = SequenceFormat(
            aspect=aspect, width=int(w), height=int(h), fit_mode=fit,
        )
        # 若 normalize 改了像素，回写分辨率下拉
        want = self._sequence_format.resolution_str()
        try:
            if getattr(self, "_resolution_var", None) is not None:
                if self._resolution_var.currentText() != want:
                    self._resolution_var.blockSignals(True)
                    self._set_export_combo_text("_resolution_var", want)
                    self._resolution_var.blockSignals(False)
            if getattr(self, "_aspect_var", None) is not None:
                if self._aspect_var.currentText() != self._sequence_format.aspect:
                    self._aspect_var.blockSignals(True)
                    self._set_export_combo_text("_aspect_var", self._sequence_format.aspect)
                    self._aspect_var.blockSignals(False)
        except Exception:
            logger.debug("宽高比下拉设置失败", exc_info=True)

    def _on_export_aspect_or_resolution_changed(self, *_args) -> None:
        sender = self.sender() if hasattr(self, "sender") else None
        prefer_aspect = sender is getattr(self, "_aspect_var", None)
        self._sync_sequence_format_from_export_combos(prefer_aspect=prefer_aspect)
        self._refresh_preview_aspect_badge()
        try:
            self._schedule_preview_refresh()
        except Exception:
            logger.debug("预览刷新调度失败", exc_info=True)

    def _on_export_fit_mode_changed(self, *_args) -> None:
        self._sync_sequence_format_from_export_combos(prefer_aspect=False)
        self._refresh_preview_aspect_badge()
        try:
            self._schedule_preview_refresh()
        except Exception:
            logger.debug("预览刷新调度失败", exc_info=True)

    # 容器（格式）↔ 编码兼容表：避免用户选出「格式与编码不匹配」导出失败或播放器打不开
    _CONTAINER_VIDEO_CODECS = {
        "mp4": {"H.264", "H.265"},
        "mov": {"H.264", "H.265"},
        "mkv": {"H.264", "H.265", "VP9", "AV1"},
        "avi": {"H.264"},
    }
    _CONTAINER_AUDIO_CODECS = {
        "mp4": {"AAC", "MP3"},
        "mov": {"AAC", "MP3", "WAV"},
        "mkv": {"AAC", "MP3", "WAV"},
        "avi": {"MP3", "WAV"},
    }

    def _on_export_format_changed(self, fmt: str) -> None:
        """格式（容器）切换时，若当前编码/音频编码与容器不兼容，自动改为该容器下的默认兼容项，
        并提示用户，避免出现「选了却导出失败/播放器打不开」的假成功。"""
        fmt_key = str(fmt or "MP4").strip().lower()
        allowed_v = self._CONTAINER_VIDEO_CODECS.get(fmt_key)
        allowed_a = self._CONTAINER_AUDIO_CODECS.get(fmt_key)
        fixed = []
        try:
            if allowed_v and getattr(self, "_codec_var", None) is not None:
                cur = self._codec_var.currentText()
                if cur not in allowed_v:
                    fallback_v = "H.264"
                    self._codec_var.blockSignals(True)
                    self._codec_var.setCurrentText(fallback_v)
                    self._codec_var.blockSignals(False)
                    fixed.append(f"编码 {cur}→{fallback_v}")
            if allowed_a and getattr(self, "_audio_codec_var", None) is not None:
                cur = self._audio_codec_var.currentText()
                if cur not in allowed_a:
                    fallback_a = "MP3" if "MP3" in allowed_a else next(iter(allowed_a))
                    self._audio_codec_var.blockSignals(True)
                    self._audio_codec_var.setCurrentText(fallback_a)
                    self._audio_codec_var.blockSignals(False)
                    fixed.append(f"音频编码 {cur}→{fallback_a}")
        except Exception as e:
            logger.debug("格式兼容自动修正失败: %s", e)
        if fixed:
            self._notify_edit(f"「{fmt}」容器不支持原编码，已自动改为兼容项：" + "；".join(fixed))

    def _toggle_sequence_fit_mode(self) -> None:
        """预览徽标点击：contain ↔ cover。"""
        old = getattr(self, "_sequence_format", None) or SequenceFormat.default()
        nxt = "cover" if (old.fit_mode or "contain") != "cover" else "contain"
        self._sequence_format = SequenceFormat(
            aspect=old.aspect, width=int(old.width), height=int(old.height), fit_mode=nxt,
        )
        self._apply_sequence_format_to_export_combos()
        self._refresh_preview_aspect_badge()
        label = "裁切铺满" if nxt == "cover" else "等比黑边"
        self._notify_edit(f"画幅适配：{label}")
        try:
            self._schedule_preview_refresh()
        except Exception:
            logger.debug("预览刷新调度失败", exc_info=True)

    def _apply_export_video_preset(
        self,
        *,
        platform: str = "",
        resolution: str = "",
        aspect: str = "",
        bitrate: str = "",
        fps: str = "",
        output_mode: str = "",
    ) -> None:
        """写入导出下拉（短暂 blockSignals，避免平台↔模式互相递归）。"""
        widgets = [
            getattr(self, "_platform_var", None),
            getattr(self, "_resolution_var", None),
            getattr(self, "_aspect_var", None),
            getattr(self, "_bitrate_var", None),
            getattr(self, "_fps_var", None),
            getattr(self, "_output_mode_var", None),
        ]
        for w in widgets:
            if w is not None:
                w.blockSignals(True)
        try:
            if platform:
                self._set_export_combo_text("_platform_var", platform)
            if resolution:
                self._set_export_combo_text("_resolution_var", resolution)
            if aspect:
                self._set_export_combo_text("_aspect_var", aspect)
            if bitrate:
                self._set_export_combo_text("_bitrate_var", bitrate)
            if fps:
                self._set_export_combo_text("_fps_var", fps)
            if output_mode:
                self._set_export_combo_text("_output_mode_var", output_mode)
        finally:
            for w in widgets:
                if w is not None:
                    w.blockSignals(False)
        # 预设后写 SSOT（比例优先对齐像素）
        try:
            if resolution:
                rw, rh = parse_resolution(resolution)
            else:
                rw, rh = 1080, 1920
        except Exception:
            rw, rh = 1080, 1920
        asp = aspect or "9:16"
        rw, rh = normalize_size(asp, rw, rh)
        fit = "contain"
        old = getattr(self, "_sequence_format", None)
        if old is not None:
            fit = old.fit_mode or "contain"
        self._sequence_format = SequenceFormat(
            aspect=asp, width=int(rw), height=int(rh), fit_mode=fit,
        )
        self._apply_sequence_format_to_export_combos()
        self._refresh_preview_aspect_badge()
        self._refresh_export_project_info()
        try:
            self._schedule_preview_refresh()
        except Exception:
            logger.debug("预览刷新调度失败", exc_info=True)

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    def _export_chapters_csv(self) -> None:
        from app.core.chapter_markers import chapter_marker_manager

        chapters = chapter_marker_manager.list_all()
        if not chapters:
            QMessageBox.information(self, "章节 CSV", "还没有章节标记，未写出文件。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出章节 CSV", "chapters.csv", "CSV (*.csv)"
        )
        if not path:
            return
        text = chapter_marker_manager.export_csv()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        QMessageBox.information(self, "章节 CSV", f"已导出 {len(chapters)} 条:\n{path}")

    def _export_chapters_ffmetadata(self) -> None:
        from app.core.chapter_markers import chapter_marker_manager

        chapters = chapter_marker_manager.list_all()
        if not chapters:
            QMessageBox.information(self, "章节元数据", "还没有章节标记，未写出文件。")
            return
        dur = 0.0
        for c in self._clips or []:
            end = float(c.get("start_time") or 0) + float(c.get("duration") or 0)
            if end > dur:
                dur = end
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 FFmpeg 章节", "chapters.ffmeta", "FFmpeg metadata (*.ffmeta *.txt)"
        )
        if not path:
            return
        text = chapter_marker_manager.export_ffmetadata(duration=dur or None)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        QMessageBox.information(self, "章节元数据", f"已导出 {len(chapters)} 条:\n{path}")

    def _on_export_platform_changed(self, platform: str) -> None:
        preset = self._DRAMA_PLATFORM_PRESETS.get(platform)
        if not preset:
            return
        res, aspect, br, fps = preset
        self._apply_export_video_preset(
            resolution=res, aspect=aspect, bitrate=br, fps=fps,
        )

    def _on_export_output_mode_changed(self, mode: str) -> None:
        if mode in ("自定义参数", ""):
            return
        if mode in ("漫剧竖屏快切", "30秒爆款引流", "90秒剧情解说"):
            self._apply_export_video_preset(
                platform="抖音",
                resolution="1080x1920",
                aspect="9:16",
                bitrate="5000k" if mode == "漫剧竖屏快切" else "3000k",
                fps="30fps",
            )
        elif mode == "8分钟挂车长视频":
            self._apply_export_video_preset(
                platform="抖音",
                resolution="1080x1920",
                aspect="9:16",
                bitrate="3000k",
                fps="30fps",
            )
        elif mode == "B站横屏长视频":
            self._apply_export_video_preset(
                platform="B站",
                resolution="1920x1080",
                aspect="16:9",
                bitrate="5000k",
                fps="30fps",
            )

    def _refresh_preview_aspect_badge(self, *_args) -> None:
        badge = getattr(self, "_preview_aspect_badge", None)
        if badge is None:
            return
        sf = getattr(self, "_sequence_format", None)
        if sf is None:
            # 兜底：从控件读
            aspect = "9:16"
            res = "1080x1920"
            try:
                if hasattr(self, "_aspect_var") and self._aspect_var is not None:
                    aspect = self._aspect_var.currentText() or aspect
                if hasattr(self, "_resolution_var") and self._resolution_var is not None:
                    res = self._resolution_var.currentText() or res
                w, h = parse_resolution(res)
                sf = SequenceFormat(aspect=aspect, width=w, height=h, fit_mode="contain")
            except Exception:
                sf = SequenceFormat.default()
        badge.setText(sf.badge_text())
        orient = sf.orientation()
        if orient == "竖屏":
            badge.setStyleSheet(
                "QLabel{background:#1a3a2a;color:#7ee787;border:1px solid #2f5139;"
                "border-radius:4px;padding:2px 8px;font-size:10px;font-weight:600;}"
            )
        elif orient == "方形":
            badge.setStyleSheet(
                "QLabel{background:#2a2438;color:#d2a8ff;border:1px solid #8957e5;"
                "border-radius:4px;padding:2px 8px;font-size:10px;font-weight:600;}"
            )
        else:
            badge.setText(sf.badge_text())
            badge.setStyleSheet(
                "QLabel{background:#1a2744;color:#79c0ff;border:1px solid #1f6feb;"
                "border-radius:4px;padding:2px 8px;font-size:10px;font-weight:600;}"
            )
    
    # 播放控制方法
    def _notify_edit(self, msg: str) -> None:
        """轻量反馈：状态栏 + toast，避免每次剪辑都弹模态框"""
        self._undo_redo_toast = msg
        logger.info(f'[剪辑] {msg}')
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
        """以墙钟驱动预览：自动跨片段切源 + 特效 + 音频跟随。"""
        try:
            self._heal_linked_av_duration_mismatch()
        except Exception as e:
            logger.debug("播放前音画时长修复跳过: %s", e)
        if hasattr(self, "_preview_manager") and self._preview_manager:
            try:
                self._preview_manager.pause_preview()
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
        self._timeline_playing = True
        self._timeline_render_busy = False
        self._audio_bound_clip_id = None
        # 墙钟锚点：真实流逝时间驱动 playhead，避免渲染慢导致越播越拖
        from PyQt6.QtCore import QElapsedTimer
        self._playback_clock = QElapsedTimer()
        self._playback_anchor_t = float(getattr(self, "_playhead_position", 0) or 0)
        self._playback_clock.start()
        # 播放中降预览分辨率，减轻每帧解码/缩放成本
        try:
            pm = self._ensure_preview_manager()
            self._preview_quality_before_play = getattr(pm, "preview_quality", "high")
            if hasattr(pm, "set_preview_quality"):
                pm.set_preview_quality("low")
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        self._ensure_media_signals()
        self._ensure_media_audio_output()
        if not getattr(self, "_timeline_play_timer", None):
            self._timeline_play_timer = QTimer(self)
            self._timeline_play_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._timeline_play_timer.timeout.connect(self._on_timeline_playback_tick)
        # ~30fps 轮询；忙则丢帧，由墙钟保证时间轴不堆积
        self._timeline_play_timer.start(33)
        if hasattr(self, "_pp_btn"):
            self._pp_btn.setText("⏸")
        # 立即渲染当前帧
        self._render_timeline_frame(float(getattr(self, "_playhead_position", 0) or 0))
        self._notify_edit("时间线播放中")

    def _stop_timeline_playback(self):
        self._timeline_playing = False
        self._timeline_render_busy = False
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
            # 恢复播放前预览质量
            try:
                q = getattr(self, "_preview_quality_before_play", None)
                if q and hasattr(self._preview_manager, "set_preview_quality"):
                    self._preview_manager.set_preview_quality(q)
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
        # 上一帧还在渲染：丢帧追赶墙钟，避免队列堆积加剧卡顿
        if getattr(self, "_timeline_render_busy", False):
            return
        rate = self._playback_rate()
        clock = getattr(self, "_playback_clock", None)
        if clock is not None:
            t = float(getattr(self, "_playback_anchor_t", 0) or 0) + (clock.elapsed() / 1000.0) * rate
        else:
            t = float(getattr(self, "_playhead_position", 0) or 0) + 0.016 * rate
        total = self._timeline_total_duration()
        if total > 0 and t >= total:
            self._render_timeline_frame(total)
            self._stop_timeline_playback()
            self._notify_edit("播放结束")
            return
        self._timeline_render_busy = True
        try:
            self._render_timeline_frame(t)
        finally:
            self._timeline_render_busy = False

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
        # 播放中节流时间线 UI，避免每帧重绘轨道
        now_ms = 0
        try:
            from PyQt6.QtCore import QDateTime
            now_ms = int(QDateTime.currentMSecsSinceEpoch())
        except Exception:
            now_ms = int(time.time() * 1000)
        if (not getattr(self, "_timeline_playing", False)) or (
            now_ms - int(getattr(self, "_ui_playhead_last_ms", 0) or 0) >= 100
        ):
            self._ui_playhead_last_ms = now_ms
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
            # 音画脱节兜底：视频轨被误裁短时，同文件音频轨仍覆盖 → 继续解画
            # （否则会出现「前几秒有画面，之后只有声音」；scrub 因回退 _current_clip 仍能出画）
            _vid_ext = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv")
            for ac in audio_hits:
                ap = str(ac.get("path") or "")
                if ap and os.path.splitext(ap)[1].lower() in _vid_ext and os.path.exists(ap):
                    video_hits = [dict(ac, type="video")]
                    break
        if not video_hits:
            try:
                from PyQt6.QtGui import QImage
                bw, bh = self._preview_frame_size()
                img = QImage(bw, bh, QImage.Format.Format_RGB888)
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
            # 自研转场插件：片尾窗双帧混合（优先于叠层 dissolve 近似）
            try:
                plugin_bgr = self._try_render_plugin_transition(timeline_t, video_hits, pm)
            except Exception:
                plugin_bgr = None
            if plugin_bgr is not None:
                out = np.clip(plugin_bgr, 0, 255).astype(np.uint8)
                qimg = self._bgr_to_qimage(out)
                if qimg is not None:
                    self._on_preview_frame(qimg)
                self._video_source = top_clip.get("path")
            else:
                # 多轨必须走 CPU 叠层，才能应用归一化位置/缩放
                use_gl_single = len(video_hits) == 1 and self._ensure_gl_preview() is not None
                gl_shown = False
                base_track = min(int(c.get("track", 0) or 0) for c in video_hits)
                for clip_i, clip in enumerate(video_hits):
                    src = self._resolve_clip_media_path(str(clip.get("path") or ""))
                    if not src or not os.path.exists(src):
                        continue
                    st = float(clip.get("start_time", 0) or 0)
                    in_p = float(clip.get("in_point", 0) or 0)
                    speed = max(0.05, float(clip.get("speed", 1.0) or 1.0))
                    try:
                        from app.core.speed_ramping import source_time_for_clip_at_timeline
                        source_t = source_time_for_clip_at_timeline(clip, timeline_t)
                    except Exception:
                        source_t = max(0.0, (timeline_t - st) * speed + in_p)
                    effects = dict(self._collect_preview_effects(clip) or {})
                    effects = self._lighten_effects_for_playback(effects)
                    opacity = self._edge_fade_opacity(clip, timeline_t)
                    opacity = min(opacity, self._crossfade_opacity(clip, timeline_t, video_hits))
                    if "opacity" in effects:
                        try:
                            opacity = min(opacity, float(effects["opacity"]))
                        except Exception as _e:
                            logger.warning("操作异常（已忽略）: %s", _e)
                    effects["opacity"] = opacity
                    is_overlay = clip_i > 0 or int(clip.get("track", 0) or 0) > base_track
                    if is_overlay:
                        # 叠层：位置/缩放由合成阶段处理，避免 get_frame_at 居中缩放
                        effects.pop("scale", None)
                    elif effects.get("scale"):
                        effects["scale"] = float(effects["scale"])
                    # 播放或 scrub：轻量 open，跳过帧数探针/预读线程
                    playing = bool(getattr(self, "_timeline_playing", False))
                    scrubbing = bool(getattr(self, "_preview_scrubbing", False))
                    self._ensure_preview_source_open(
                        pm, src, for_scrub=(playing or scrubbing), preload=False
                    )
                    if use_gl_single:
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
                        # 播放中丢帧时保留上一帧，避免灰屏/黑场闪一下
                        continue
                    arr = self._qimage_or_ndarray_to_bgr(frame)
                    if arr is None:
                        continue
                    arr = apply_clip_crop_bgr(arr, clip)
                    if base_frame is None:
                        # 底轨：落到工程画幅，预览与导出同坐标系
                        base_frame = self._place_bgr_on_sequence_canvas(arr)
                    else:
                        bh, bw = base_frame.shape[:2]
                        defaults = {"x": 0.75, "y": 0.80, "scale": 0.35, "opacity": 1.0}
                        # 关键帧位置/旋转注入临时 clip 视图
                        clip_view = dict(clip)
                        tfx = dict(clip.get("transform") or {})
                        if effects.get("_tf_x") is not None:
                            tfx["x"] = float(effects["_tf_x"])
                        if effects.get("_tf_y") is not None:
                            tfx["y"] = float(effects["_tf_y"])
                        if effects.get("_tf_rot") is not None:
                            tfx["rotation"] = float(effects["_tf_rot"])
                            clip_view["rotation"] = float(effects["_tf_rot"])
                        if tfx:
                            clip_view["transform"] = tfx
                        # 也写入 effects 供 normalize 读 _tf_*
                        ce = dict(clip.get("effects") or {})
                        for k in ("_tf_x", "_tf_y", "_tf_rot"):
                            if effects.get(k) is not None:
                                ce[k] = effects[k]
                        clip_view["effects"] = ce
                        try:
                            from app.modules.lego.clip_transform import (
                                normalize_clip_transform, composite_overlay_bgr,
                            )
                        except Exception:
                            from app.modules.lego.video_processor import (
                                normalize_clip_transform, composite_overlay_bgr,
                            )
                        tf = normalize_clip_transform(clip_view, bw, bh, defaults)
                        op = min(float(effects.get("opacity", 1.0) or 1.0), tf["opacity"])
                        blend_mode = BLEND_MODE_NAME_TO_KEY.get(
                            str(clip.get("blend_mode") or "正常"), "normal"
                        )
                        if blend_mode == "normal":
                            base_frame = composite_overlay_bgr(base_frame, arr, tf, op)
                        else:
                            base_frame = composite_overlay_bgr_blend(base_frame, arr, tf, op, blend_mode)
                if gl_shown:
                    pass
                elif base_frame is not None:
                    out = np.clip(base_frame, 0, 255).astype(np.uint8)
                    qimg = self._bgr_to_qimage(out)
                    if qimg is not None:
                        # 已落到 sequence 画幅 → 播放中跳过二次 letterbox
                        self._preview_frame_preletterboxed = True
                        self._on_preview_frame(qimg)
                    self._video_source = top_clip.get("path")
                else:
                    # 回退单源 update_preview
                    clip = top_clip
                    src = self._resolve_clip_media_path(str(clip.get("path") or "")) or clip.get("path")
                    st = float(clip.get("start_time", 0) or 0)
                    in_p = float(clip.get("in_point", 0) or 0)
                    speed = max(0.05, float(clip.get("speed", 1.0) or 1.0))
                    try:
                        from app.core.speed_ramping import source_time_for_clip_at_timeline
                        source_t = source_time_for_clip_at_timeline(clip, timeline_t)
                    except Exception:
                        source_t = max(0.0, (timeline_t - st) * speed + in_p)
                    effects = dict(self._collect_preview_effects(clip) or {})
                    effects = self._lighten_effects_for_playback(effects)
                    effects["opacity"] = self._edge_fade_opacity(clip, timeline_t)
                    playing = bool(getattr(self, "_timeline_playing", False))
                    scrubbing = bool(getattr(self, "_preview_scrubbing", False))
                    self._ensure_preview_source_open(
                        pm, src, for_scrub=(playing or scrubbing), preload=False
                    )
                    pm.set_active_effects(effects)
                    pm.update_preview(source_t, effects=effects)
                    self._video_source = src
        except Exception as e:
            logger.error(f'时间线帧渲染失败: {e}')

        # >>> FROZEN:playback-av:main-audio BEGIN
        # 主视频内嵌音：墙钟为画面主时钟；QMediaPlayer 只出声（勿再挂 VideoOutput）
        # 2026-08-07 解冻：source_t / rate 可读 speed_ramp（瞬时倍率），纠偏仍约 280ms
        try:
            clip = top_clip
            src = clip.get("path")
            st = float(clip.get("start_time", 0) or 0)
            in_p = float(clip.get("in_point", 0) or 0)
            speed = max(0.05, float(clip.get("speed", 1.0) or 1.0))
            try:
                from app.core.speed_ramping import (
                    source_time_for_clip_at_timeline,
                    instant_speed_for_clip_at_timeline,
                )
                source_t = source_time_for_clip_at_timeline(clip, timeline_t)
                speed = instant_speed_for_clip_at_timeline(clip, timeline_t)
            except Exception:
                source_t = max(0.0, (timeline_t - st) * speed + in_p)
            cid = clip.get("id")
            from PyQt6.QtCore import QUrl
            vol = float(clip.get("volume", 1.0) or 1.0)
            effects = self._collect_preview_effects(clip)
            if effects.get("_volume") is not None:
                vol = float(effects["_volume"])
            master = float(getattr(self, "_master_volume", 1.0) or 1.0)
            track_vol = self._track_volume_for_clip(clip)
            ao = self._ensure_media_audio_output()
            if ao is not None:
                ao.setVolume(max(0.0, min(1.0, vol * master * track_vol)))
            rate = self._playback_rate() * speed
            clip_changed = getattr(self, "_audio_bound_clip_id", None) != cid
            if clip_changed:
                self._media_player.setSource(QUrl.fromLocalFile(src))
                self._audio_bound_clip_id = cid
                # 2026-09-13 解冻修复：切源后媒体引擎速率可能被复位，清缓存强制下次重设
                self._audio_applied_rate = None
            self._arm_media_audio(source_t, rate)
        except Exception as e:
            print(f"音频同步失败: {e}")

        self._sync_bgm_audio(timeline_t, audio_hits)
        # <<< FROZEN:playback-av:main-audio END

    def _rebuild_transition_combo(self):
        """从 ITransitionPlugin / transition_*.py 填充类型下拉。"""
        combo = getattr(self, "_transition_type_var", None)
        if combo is None:
            return
        prev = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        try:
            from app.core.transition_plugin_registry import display_entries
            entries = display_entries()
        except Exception:
            try:
                from core.transition_plugin_registry import display_entries
                entries = display_entries()
            except Exception:
                entries = [
                    ("淡入淡出", "transition_fade"),
                    ("滑动", "transition_slide"),
                    ("缩放", "transition_zoom"),
                    ("溶解", "transition_dissolve"),
                    ("擦除", "transition_wipe"),
                    ("翻转", "transition_flip"),
                    ("旋转", "transition_spin"),
                    ("故障", "transition_glitch"),
                ]
        for label, pid in entries:
            combo.addItem(label, pid)
        if prev is not None:
            idx = combo.findData(prev)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _clip_outgoing_transition(self, clip) -> Optional[Dict[str, Any]]:
        """片段片尾转场元数据（优先 transition，否则 transitions 最后一项）。"""
        if not isinstance(clip, dict):
            return None
        tr = clip.get("transition")
        if isinstance(tr, dict) and float(tr.get("duration", 0) or 0) > 0:
            return tr
        lst = clip.get("transitions") or []
        if isinstance(lst, list):
            for item in reversed(lst):
                if isinstance(item, dict) and float(item.get("duration", 0) or 0) > 0:
                    return item
        return None

    def _find_next_clip_same_track(self, clip):
        """同轨、start 紧随当前片尾之后的下一片（视频）。"""
        if not clip:
            return None
        track = int(clip.get("track", 0) or 0)
        end = float(clip.get("start_time", 0) or 0) + float(clip.get("duration", 0) or 0)
        best = None
        best_st = None
        for other in getattr(self, "_clips", None) or []:
            if other is clip or other.get("id") == clip.get("id"):
                continue
            if int(other.get("track", 0) or 0) != track:
                continue
            if str(other.get("type", "")).lower() == "audio":
                continue
            ost = float(other.get("start_time", 0) or 0)
            if ost + 0.05 < end:
                continue
            if best_st is None or ost < best_st:
                best, best_st = other, ost
        return best

    def _decode_clip_bgr_at(self, clip, timeline_t: float, pm):
        """解码某片在 timeline_t 的 BGR（落到工程画幅）。"""
        if not clip or pm is None:
            return None
        src = self._resolve_clip_media_path(str(clip.get("path") or ""))
        if not src or not os.path.exists(src):
            return None
        st = float(clip.get("start_time", 0) or 0)
        in_p = float(clip.get("in_point", 0) or 0)
        speed = max(0.05, float(clip.get("speed", 1.0) or 1.0))
        try:
            from app.core.speed_ramping import source_time_for_clip_at_timeline
            source_t = source_time_for_clip_at_timeline(clip, timeline_t)
        except Exception:
            source_t = max(0.0, (timeline_t - st) * speed + in_p)
        # 邻片可能尚未进入自身时间窗：钳到片内
        dur = float(clip.get("duration", 0) or 0)
        local = max(0.0, min(dur, timeline_t - st))
        source_t = max(0.0, local * speed + in_p)
        effects = dict(self._collect_preview_effects(clip) or {})
        effects = self._lighten_effects_for_playback(effects)
        effects.pop("opacity", None)
        playing = bool(getattr(self, "_timeline_playing", False))
        scrubbing = bool(getattr(self, "_preview_scrubbing", False))
        self._ensure_preview_source_open(
            pm, src, for_scrub=(playing or scrubbing), preload=False
        )
        frame = pm.get_frame_at(source_t, effects=effects) if hasattr(pm, "get_frame_at") else None
        arr = self._qimage_or_ndarray_to_bgr(frame)
        if arr is None:
            return None
        return self._place_bgr_on_sequence_canvas(arr)

    # [Mixin] 已迁移至 editor_ai_process_mixin.py
    def _crossfade_opacity(self, clip, timeline_t: float, video_hits) -> float:
        """邻片重叠 / 片缘转场窗：无插件双帧时的 dissolve 近似。"""
        st = float(clip.get("start_time", 0) or 0)
        dur = float(clip.get("duration", 0) or 0)
        end = st + dur
        fade = 0.0
        trs = list(clip.get("transitions") or [])
        if isinstance(clip.get("transition"), dict):
            trs.append(clip["transition"])
        for tr in trs:
            if isinstance(tr, dict):
                fade = max(fade, float(tr.get("duration", 0) or 0))
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

    def _is_linked_video_audio_clip(self, audio_clip) -> bool:
        """导入视频时自动挂到音频轨的联动片（同 path + 同 start），主音已由视频播放器承担。"""
        path = audio_clip.get("path")
        if not path:
            return False
        st = float(audio_clip.get("start_time", 0) or 0)
        for other in self._clips or []:
            if other is audio_clip or other.get("id") == audio_clip.get("id"):
                continue
            if str(other.get("type", "")).lower() == "audio":
                continue
            if other.get("path") != path:
                continue
            if abs(float(other.get("start_time", 0) or 0) - st) < 0.05:
                return True
        return False

    def _find_linked_av_partners(self, clip, ref_start=None):
        """同 path、与 ref_start 对齐的联动片（视频↔音频）。"""
        if not clip:
            return []
        path = clip.get("path")
        cid = clip.get("id")
        if not path:
            return []
        st0 = float(ref_start if ref_start is not None else clip.get("start_time", 0) or 0)
        out = []
        for c in self._clips or []:
            if c.get("id") == cid:
                continue
            if c.get("path") != path:
                continue
            if abs(float(c.get("start_time", 0) or 0) - st0) < 0.08:
                out.append(c)
        return out

    def _linked_av_edit_steps(self, clip, before=None):
        """在同步联动片之前，生成可用于 compound undo 的 edit_clip 步骤。"""
        steps = []
        if not clip:
            return steps
        ref = before.get("start_time") if isinstance(before, dict) else None
        partners = self._find_linked_av_partners(clip, ref_start=ref)
        if not partners:
            partners = self._find_linked_av_partners(clip, ref_start=clip.get("start_time"))
        fields = ("start_time", "duration", "in_point", "out_point", "track")
        for pclip in partners:
            pb = {
                f: (
                    int(pclip.get(f, 0) or 0)
                    if f == "track"
                    else float(pclip.get(f, 0) or 0)
                )
                for f in fields
            }
            pa = {}
            for f in fields:
                if f == "track":
                    # 联动只对齐时间窗，轨号各自保留（视频轨/音频轨）
                    pa[f] = int(pclip.get("track", 0) or 0)
                elif f in clip:
                    pa[f] = float(clip.get(f, 0) or 0)
                else:
                    pa[f] = pb[f]
            if any(
                float(pb.get(k, 0) or 0) != float(pa.get(k, 0) or 0)
                for k in ("start_time", "duration", "in_point", "out_point")
            ):
                steps.append({
                    "type": "edit_clip",
                    "clip_id": pclip.get("id"),
                    "before": pb,
                    "after": pa,
                })
        return steps

    def _sync_linked_av_timing(self, clip, before=None):
        """trim/移动后，把联动音/视频的 start/in/out/duration 对齐（剪映式音画锁）。"""
        if not clip:
            return
        ref = None
        if isinstance(before, dict):
            ref = before.get("start_time")
        partners = self._find_linked_av_partners(clip, ref_start=ref)
        if not partners:
            # 已对齐过则用当前 start 再找一次
            partners = self._find_linked_av_partners(clip, ref_start=clip.get("start_time"))
        fields = ("start_time", "duration", "in_point", "out_point")
        tw = getattr(self, "_timeline_widget", None)
        for pclip in partners:
            for f in fields:
                if f in clip:
                    pclip[f] = clip[f]
            if tw is not None and hasattr(tw, "all_clip_widgets"):
                for w in tw.all_clip_widgets():
                    if w.clip_data.get("id") == pclip.get("id"):
                        # 保持 widget 与 dict 同一引用
                        w.clip_data.update({f: pclip[f] for f in fields if f in pclip})
                        tw.position_clip_widget(w)
                        break

    def _sync_bgm_audio(self, timeline_t: float, audio_hits):
        """独立音频轨 BGM 跟随（跳过与视频联动的内嵌音，避免双开抢时钟）。"""
        try:
            player = self._ensure_bgm_player()
            real_hits = [c for c in (audio_hits or []) if not self._is_linked_video_audio_clip(c)]
            if not real_hits:
                player.pause()
                self._bgm_bound_clip_id = None
                return
            clip = real_hits[-1]
            src = clip.get("path")
            if not src or not os.path.exists(src):
                player.pause()
                return
            st = float(clip.get("start_time", 0) or 0)
            in_p = float(clip.get("in_point", 0) or 0)
            source_t = max(0.0, timeline_t - st + in_p)
            vol = float(clip.get("volume", 1.0) or 1.0) * float(getattr(self, "_master_volume", 1.0) or 1.0)
            vol *= self._track_volume_for_clip(clip)
            # 音量关键帧
            try:
                st = float(clip.get("start_time", 0) or 0)
                local_t = max(0.0, float(timeline_t) - st)
                kf = self._interpolate_clip_keyframes(clip, local_t)
                if "volume" in kf:
                    vol = float(kf["volume"]) * float(getattr(self, "_master_volume", 1.0) or 1.0)
                    vol *= self._track_volume_for_clip(clip)
            except Exception as e:
                logger.debug("计算片段音量失败: %s", e)
            if self._bgm_audio_output:
                self._bgm_audio_output.setVolume(max(0.0, min(1.0, vol)))
            from PyQt6.QtCore import QUrl
            from PyQt6.QtMultimedia import QMediaPlayer
            cid = clip.get("id")
            if getattr(self, "_bgm_bound_clip_id", None) != cid:
                player.setSource(QUrl.fromLocalFile(src))
                self._bgm_bound_clip_id = cid
                player.setPlaybackRate(self._playback_rate())
                player.setPosition(int(source_t * 1000))
                player.play()
            else:
                player.setPlaybackRate(self._playback_rate())
                if abs(player.position() / 1000.0 - source_t) > 0.28:
                    player.setPosition(int(source_t * 1000))
                if player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                    player.play()
        except Exception as e:
            print(f"BGM 同步失败: {e}")

    def _rebasing_playback_clock(self, timeline_t: float):
        """在播放中跳转/改速后，把墙钟锚点重设到新位置。"""
        if not getattr(self, "_timeline_playing", False):
            return
        from PyQt6.QtCore import QElapsedTimer
        self._playback_anchor_t = float(timeline_t)
        clock = QElapsedTimer()
        clock.start()
        self._playback_clock = clock

    def _rewind(self):
        """后退 10 秒（以播放头为准，不依赖 QMediaPlayer 时长）"""
        cur = float(getattr(self, '_playhead_position', 0) or 0)
        new_t = max(0.0, cur - 10.0)
        self._rebasing_playback_clock(new_t)
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
        self._rebasing_playback_clock(new_t)
        if getattr(self, "_timeline_playing", False):
            self._render_timeline_frame(new_t)
        else:
            self._on_timeline_playhead_moved(new_t)
        if hasattr(self, '_timeline_widget') and self._timeline_widget:
            self._timeline_widget.set_playhead_position(new_t)
    
    def _on_playback_speed_changed(self, speed_text):
        """播放倍速：同步音频与画面预览；播放中重设墙钟锚点。"""
        speed_map = {"0.5x": 0.5, "1x": 1.0, "1.5x": 1.5, "2x": 2.0}
        rate = speed_map.get(speed_text, 1.0)
        self._media_player.setPlaybackRate(rate)
        if hasattr(self, '_preview_manager') and self._preview_manager:
            self._preview_manager.playing_speed = rate
        if getattr(self, "_timeline_playing", False):
            self._rebasing_playback_clock(float(getattr(self, "_playhead_position", 0) or 0))
        logger.info(f'播放倍速切换为: {speed_text}')
    
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
        """刷新时间码与预览进度条。"""
        def format_time(seconds):
            seconds = max(0.0, float(seconds or 0))
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"

        cur = float(getattr(self, "_playhead_position", 0) or getattr(self, "_current_time", 0) or 0)
        total = 0.0
        try:
            total = float(self._timeline_total_duration() or 0)
        except Exception:
            total = 0.0
        if total <= 0:
            total = float(getattr(self, "_total_duration", 0) or 0)

        text = f"{format_time(cur)} / {format_time(total)}"
        if getattr(self, "_timecode_label", None) is not None:
            self._timecode_label.setText(text)
        if getattr(self, "_time_label", None) is not None:
            self._time_label.setText(text)
        self._sync_progress_bar_from_playhead()

    def _sync_progress_bar_from_playhead(self):
        """进度条 0~1000 映射时间线总长；拖动中不回写。"""
        bar = getattr(self, "_progress_bar", None)
        if bar is None:
            return
        try:
            if bar.isSliderDown():
                return
        except Exception:
            logger.debug("滑杆状态读取失败", exc_info=True)
        total = 0.0
        try:
            total = float(self._timeline_total_duration() or 0)
        except Exception:
            total = 0.0
        if total <= 0:
            total = float(getattr(self, "_total_duration", 0) or 0)
        if total <= 0:
            return
        t = float(getattr(self, "_playhead_position", 0) or 0)
        val = int(max(0, min(1000, round((t / total) * 1000.0))))
        if bar.maximum() != 1000:
            bar.setRange(0, 1000)
        if bar.value() == val:
            return
        bar.blockSignals(True)
        bar.setValue(val)
        bar.blockSignals(False)

    def _on_progress_slider_moved(self, value):
        """预览进度条拖动：按时间线总长跳转。"""
        total = 0.0
        try:
            total = float(self._timeline_total_duration() or 0)
        except Exception:
            total = 0.0
        if total <= 0:
            total = float(getattr(self, "_total_duration", 0) or 0)
        if total <= 0 and self._media_player.duration() > 0:
            total = self._media_player.duration() / 1000.0
        if total <= 0:
            return
        t = (float(value) / 1000.0) * total
        self._on_timeline_playhead_moved(t)

    def _on_progress_slider_released(self):
        """松手再确认一次定位（含音频 seek 路径）。"""
        bar = getattr(self, "_progress_bar", None)
        if bar is None:
            return
        self._on_progress_slider_moved(bar.value())

    def _on_duration_changed(self, duration):
        """QMediaPlayer 时长变化（毫秒）→ 秒。"""
        self._total_duration = float(duration or 0) / 1000.0
        self._update_time_display()

    def _move_playhead(self, position):
        """ """
        self._playhead_position = position
        self._current_time = position
        self._update_time_display()
        logger.info(f'播放头移动到 {position}s')
    
    # 媒体播放器事件处理
    def _on_playback_state_changed(self, state):
        """媒体播放态。时间线播放时勿抢写播放按钮。"""
        from PyQt6.QtMultimedia import QMediaPlayer
        self._is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        if getattr(self, "_timeline_playing", False):
            return
        status = "播放" if self._is_playing else "暂停"
        print(f"播放状态: {status}")
        if hasattr(self, '_pp_btn') and self._pp_btn is not None:
            self._pp_btn.setText("⏸" if self._is_playing else "▶")
    
    def _on_position_changed(self, position):
        """单文件媒体时钟。时间线播放时禁止用片内时间覆盖播放头。"""
        if getattr(self, "_timeline_playing", False):
            return
        current_time = position / 1000
        self._current_time = current_time
        self._playhead_position = current_time
        self._update_time_display()
        
        if hasattr(self, '_timeline_widget') and self._timeline_widget:
            self._timeline_widget.set_playhead_position(current_time)
    def _on_timeline_playhead_moved(self, position: float):
        """时间线播放头拖动/跳转：UI 即时更新，重预览合并到 scrub 定时器。"""
        self._playhead_position = float(position)
        self._current_time = float(position)
        self._update_time_display()
        if getattr(self, "_timeline_playing", False):
            # 播放中画面由 _render_timeline_frame 驱动自身墙钟；这里只是它同步 UI
            # 播放头后回抛的信号，不应重新 rebase 墙钟锚点（否则每 ~100ms 抖一次），
            # 也不需要二次解码，直接 return。
            return
        # 未播放（scrub/跳转）：_rebasing_playback_clock 内部按 _timeline_playing
        # 早退，这里调用恒为 no-op，故不再调用。
        self._begin_preview_scrub()
        self._scrub_preview_pending = float(position)
        self._scrub_preview_coalesce = int(getattr(self, "_scrub_preview_coalesce", 0) or 0) + 1
        st = getattr(self, "_scrub_preview_timer", None)
        if st is not None:
            st.start()
        else:
            self._flush_scrub_preview()

    def _on_snap_toggled(self, enabled: bool):
        """吸附开关：写入时间线标志，供后续拖拽对齐使用"""
        self._snap_enabled = bool(enabled)
        if hasattr(self, '_timeline_widget') and self._timeline_widget is not None:
            self._timeline_widget._snap_enabled = bool(enabled)

    def _on_ripple_delete_toggled(self, enabled: bool):
        """波纹删除 ↔ 普通删除（留白）。"""
        self._ripple_delete_enabled = bool(enabled)
        self._notify_edit("删除模式：波纹" if enabled else "删除模式：普通（留白）")

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
        elif action == "close_gap":
            self._ripple_delete_gaps()
        elif action == "delete" and clip_data:
            # 走多选删除，与 Delete 键一致
            tw = getattr(self, "_timeline_widget", None)
            if tw is not None and hasattr(tw, "get_selected_ids"):
                ids = tw.get_selected_ids() or set()
                if clip_data.get("id") not in ids:
                    if hasattr(tw, "set_selection"):
                        tw.set_selection([clip_data.get("id")], primary=clip_data, emit=True)
            self._delete_clip()
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

    def _set_timeline_zoom(self, value):
        """时间线缩放 10~3000%。"""
        value = max(10, min(3000, int(round(float(value)))))
        self._timeline_widget.set_zoom(value)
        if hasattr(self, "_zoom_label") and self._zoom_label is not None:
            self._zoom_label.setText(f"{value}%")
        if hasattr(self, "_zoom_slider") and self._zoom_slider is not None:
            self._zoom_slider.blockSignals(True)
            self._zoom_slider.setValue(value)
            self._zoom_slider.blockSignals(False)

    def _timeline_content_duration(self) -> float:
        """时间线内容总时长（秒）：取片段 end 最大值。"""
        dur = 0.0
        for c in getattr(self, "_clips", []) or []:
            if not isinstance(c, dict):
                continue
            st = float(c.get("start_time", 0) or 0)
            d = float(c.get("duration", 0) or 0)
            dur = max(dur, st + d)
        tw = getattr(self, "_timeline_widget", None)
        if tw is not None:
            try:
                dur = max(dur, float(getattr(tw, "_total_duration", 0) or 0))
            except Exception:
                logger.debug("总时长读取失败", exc_info=True)
        try:
            dur = max(dur, float(getattr(self, "_total_duration", 0) or 0))
        except Exception:
            logger.debug("总时长读取失败", exc_info=True)
        return max(0.0, dur)

    def _zoom_timeline_to_fit(self):
        """Ctrl+0：自适应缩放，让整段内容恰好落入可视区（修正 BASE_PPS=20）。"""
        tw = getattr(self, "_timeline_widget", None)
        if tw is None:
            return
        total_dur = self._timeline_content_duration()
        if total_dur <= 0.05:
            self._set_timeline_zoom(100)
            return
        scroll = getattr(tw, "_track_scroll", None)
        if scroll is not None and hasattr(scroll, "viewport"):
            view_w = max(1, int(scroll.viewport().width()))
        elif hasattr(tw, "viewport"):
            view_w = max(1, int(tw.viewport().width()))
        else:
            view_w = max(1, int(tw.width()))
        left = int(getattr(tw, "_left_margin", 100) or 100)
        usable = max(40, view_w - left - 24)
        try:
            from app.modules.lego.timeline_widget import _TIMELINE_BASE_PPS
            base_pps = float(_TIMELINE_BASE_PPS)
        except Exception:
            base_pps = 20.0
        want_pps = usable / total_dur
        zoom = int(round((want_pps / max(1e-6, base_pps)) * 100.0))
        zoom = max(10, min(3000, zoom))
        self._set_timeline_zoom(zoom)
        try:
            if scroll is not None and hasattr(scroll, "horizontalScrollBar"):
                scroll.horizontalScrollBar().setValue(0)
        except Exception:
            logger.debug("滚动条复位失败", exc_info=True)
        self._notify_edit(f"时间线适应窗口 {zoom}%")

    def _mark_sequence_in(self):
        """I 键：在当前播放头位置标记序列级入点。"""
        t = float(getattr(self, "_playhead_position", 0) or 0)
        self._sequence_in_point = t
        self._notify_edit(f"入点 {self._format_time(t)}")
        self._flash_timeline_marker()

    def _mark_sequence_out(self):
        """O 键：在当前播放头位置标记序列级出点。"""
        t = float(getattr(self, "_playhead_position", 0) or 0)
        # 出点不能早于入点
        if self._sequence_in_point is not None and t <= self._sequence_in_point:
            self._notify_edit("出点必须晚于入点")
            return
        self._sequence_out_point = t
        self._notify_edit(f"出点 {self._format_time(t)}")
        self._flash_timeline_marker()

    def _clear_sequence_in_out(self):
        """清除序列级入出点。"""
        self._sequence_in_point = None
        self._sequence_out_point = None
        self._notify_edit("已清除入出点")
        self._flash_timeline_marker()

    def _format_time(self, t: float) -> str:
        """秒 → MM:SS.ff 字符串（60fps 精度）。"""
        t = max(0.0, float(t))
        m = int(t // 60)
        s = int(t % 60)
        ff = int(round((t - int(t)) * 30)) % 30
        return f"{m:02d}:{s:02d}.{ff:02d}"

    def _flash_timeline_marker(self):
        """触发时间线重绘以显示/更新入出点标记（若 timeline 支持）。"""
        tw = getattr(self, "_timeline_widget", None)
        if tw is None:
            return
        try:
            if hasattr(tw, "update_in_out_markers"):
                tw.update_in_out_markers(
                    getattr(self, "_sequence_in_point", None),
                    getattr(self, "_sequence_out_point", None),
                )
            elif hasattr(tw, "update"):
                tw.update()
        except Exception:
            logger.debug("时间线刷新失败", exc_info=True)

    def _ripple_delete_gaps(self):
        """Shift+Del / 合缝：各轨磁吸贴齐（前移片，不删内容），可撤销。"""
        try:
            from app.core.edit_commands import close_track_gaps
        except Exception:
            self._notify_edit("合缝：核心模块不可用")
            return
        clips = list(getattr(self, "_clips", []) or [])
        if not clips:
            self._notify_edit("没有片段可合缝")
            return
        # 若有选中：只合所选片所在轨；否则全轨
        track_filter = None
        tw = getattr(self, "_timeline_widget", None)
        if tw is not None and hasattr(tw, "get_selected_clips"):
            sel = [c for c in (tw.get_selected_clips() or []) if isinstance(c, dict)]
            if sel:
                tracks = {int(c.get("track", 0) or 0) for c in sel}
                if len(tracks) == 1:
                    track_filter = next(iter(tracks))
        result = close_track_gaps(clips, track=track_filter, gap_threshold=0.05)
        if not result.ok:
            self._notify_edit(result.message)
            return
        self._timeline_store.replace_all(result.clips)
        self._record_action(result.undo_action)
        self._touch_project_dirty()
        self._sync_timeline_widget_state()
        self._sync_kernel_timeline()
        self._notify_edit(result.message)

    def _edit_frame_duration(self) -> float:
        tw = getattr(self, "_timeline_widget", None)
        if tw is not None and hasattr(tw, "frame_duration"):
            return float(tw.frame_duration())
        return 1.0 / 30.0

    def _step_playhead_frames(self, frames: int):
        """←/→：播放头按帧步进（精细定位）。"""
        step = self._edit_frame_duration() * int(frames)
        cur = float(getattr(self, "_playhead_position", 0) or 0)
        new_t = max(0.0, cur + step)
        dur = 0.0
        try:
            dur = float(self._timeline_total_duration() or 0)
        except Exception:
            dur = 0.0
        if dur > 0:
            new_t = min(dur, new_t)
        self._rebasing_playback_clock(new_t)
        if getattr(self, "_timeline_playing", False):
            self._render_timeline_frame(new_t)
        else:
            self._on_timeline_playhead_moved(new_t)
        tw = getattr(self, "_timeline_widget", None)
        if tw is not None:
            tw.set_playhead_position(new_t)

    # [Mixin] 已迁移至 editor_effects_mixin.py
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
            result = subprocess.run([
                ffmpeg, '-y', '-i', src,
                '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11,highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=50',
                '-q:a', '2', dst
            ], capture_output=True, text=True)
            if result.returncode != 0 or not os.path.exists(dst):
                QMessageBox.warning(self, "失败", f"音频增强失败:\n{(result.stderr or '')[-500:]}")
                return
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
            result = subprocess.run([
                ffmpeg, '-y', '-i', src,
                '-af', 'anlmdn=s=0.0005:p=7:r=0.002', '-q:a', '2', dst
            ], capture_output=True, text=True)
            if result.returncode != 0 or not os.path.exists(dst):
                QMessageBox.warning(self, "失败", f"降噪失败:\n{(result.stderr or '')[-500:]}")
                return
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
            result = subprocess.run([
                ffmpeg, '-y', '-ss', str(start), '-t', str(end-start), '-i', src,
                '-c', 'copy', dst
            ], capture_output=True, text=True)
            if result.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
                # -c copy 对部分容器/切点会失败，回退重编码
                result = subprocess.run([
                    ffmpeg, '-y', '-ss', str(start), '-t', str(end-start), '-i', src,
                    '-q:a', '2', dst
                ], capture_output=True, text=True)
            if result.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
                QMessageBox.warning(self, "失败", f"截取失败:\n{(result.stderr or '')[-500:]}")
                return
            self._add_to_clips(dst, 'audio')
            QMessageBox.information(self, "完成", f"截取完成 ({start:.1f}s~{end:.1f}s):\n{dst}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"处理失败: {e}")

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
        QMessageBox.information(
            self, "人声提取（滤波近似）",
            f"注：本功能用高低通滤波近似突出人声频段，非神经网络人声分离，效果有限。\n正在处理...\n{os.path.basename(src)}"
        )
        try:
            result = subprocess.run([
                ffmpeg, '-y', '-i', src,
                '-af', 'highpass=f=200,lowpass=f=3000,acompressor=threshold=-24dB:ratio=4:attack=5:release=50',
                '-q:a', '2', dst
            ], capture_output=True, text=True)
            if result.returncode != 0 or not os.path.exists(dst):
                QMessageBox.warning(self, "失败", f"人声提取失败:\n{(result.stderr or '')[-500:]}")
                return
            self._add_to_clips(dst, 'audio')
            QMessageBox.information(self, "完成", f"人声提取（滤波近似）完成:\n{dst}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"处理失败: {e}")

    def _output_path(self, src, suffix):
        """生成输出文件路径"""
        base = os.path.splitext(os.path.basename(src))[0]
        d = os.path.join(os.path.dirname(src) or '.', 'output')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{base}{suffix}.mp3")

    def _add_to_clips(self, path, kind='audio'):
        """将处理结果加入素材列表，音频真正落到时间线 audio 轨。"""
        from datetime import datetime
        import time as _time
        ext = os.path.splitext(path)[1].lower()
        is_video = ext in ('.mp4', '.mov', '.avi', '.mkv', '.webm')
        clip_kind = 'video' if is_video and kind != 'audio' else ('audio' if kind == 'audio' or not is_video else 'video')
        duration = self._probe_video_duration(path) or 10.0
        start_time = self._next_clip_start_time() if hasattr(self, '_next_clip_start_time') else 0.0
        clip = {
            'id': f"{clip_kind}_{int(_time.time() * 1000)}",
            'path': path,
            'name': os.path.basename(path),
            'type': clip_kind,
            'start_time': start_time,
            'duration': duration,
            'in_point': 0.0,
            'out_point': duration,
            'effects': {},
            'transitions': [],
            'added': datetime.now().strftime('%H:%M'),
        }
        if not any(c.get('path') == path and c.get('type') == clip_kind for c in self._clips):
            self._timeline_store.add(clip)

        tw = getattr(self, '_timeline_widget', None)
        if tw is not None and hasattr(tw, 'add_clip'):
            if clip_kind == 'audio':
                track_i = tw.find_track_index_by_type('audio', default=1) if hasattr(tw, 'find_track_index_by_type') else 1
            else:
                track_i = tw.find_track_index_by_type('video', default=0) if hasattr(tw, 'find_track_index_by_type') else 0
            clip['track'] = track_i
            widget = tw.add_clip(clip, track_i)
            if widget is not None:
                if not hasattr(self, '_clip_widgets'):
                    self._clip_widgets = []
                self._clip_widgets.append(widget)
                if hasattr(self, '_clip_id_to_widget'):
                    self._clip_id_to_widget[clip['id']] = widget
        elif hasattr(self, '_refresh_timeline'):
            self._refresh_timeline()

    def _adjust_volume(self, volume):
        """调整总控音量（立即作用于 QAudioOutput；与片段/轨道音量相乘）。"""
        vol = max(0.0, min(2.0, float(volume) / 100.0))
        self._master_volume = vol
        self._touch_project_dirty()
        clip = getattr(self, "_current_clip", None)
        clip_vol = float((clip or {}).get("volume", 1.0) or 1.0)
        track_vol = self._track_volume_for_clip(clip) if clip else 1.0
        out = max(0.0, min(1.0, clip_vol * vol * track_vol))
        try:
            if getattr(self, "_audio_output", None):
                self._audio_output.setVolume(out)
            if getattr(self, "_bgm_audio_output", None):
                self._bgm_audio_output.setVolume(out)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        self._notify_edit(f"总控音量 {int(vol * 100)}%")

    # [Mixin] 已迁移至 editor_effects_mixin.py
    def _delete_clip_by_id(self, clip_id, ripple: bool = True):
        """按片段 ID 删除；默认波纹；视频片连带删除同起点联动音频（一次撤销）。"""
        if not clip_id:
            return False
        deleted_clip = next((c for c in self._clips if c.get("id") == clip_id), None)
        if deleted_clip is None:
            return False

        # 先收集联动音频（同 path + 同 start），再删主片，避免迭代中途改列表
        linked_ids = []
        if not self._is_linked_video_audio_clip(deleted_clip):
            path = deleted_clip.get("path")
            st0 = float(deleted_clip.get("start_time", 0) or 0)
            for c in self._clips:
                if c.get("id") == clip_id:
                    continue
                if not self._is_linked_video_audio_clip(c):
                    continue
                if c.get("path") == path and abs(float(c.get("start_time", 0) or 0) - st0) < 0.05:
                    linked_ids.append(c.get("id"))

        items = []
        for i, cid in enumerate([clip_id] + linked_ids):
            use_ripple = ripple if i == 0 else True
            payload = self._delete_one_clip_internal(
                cid, ripple=use_ripple, record=False, sync=False
            )
            if payload:
                items.append(payload)
        if not items:
            return False
        if len(items) == 1:
            self._record_action({"type": "delete", **items[0]})
        else:
            self._record_action({"type": "batch_delete", "items": items})
        self._sync_kernel_timeline()
        self._sync_timeline_widget_state()
        self._refresh_preview_to_current_clip()
        self._notify_edit("已删除片段" + ("（波纹）" if ripple else ""))
        return True

    def _delete_one_clip_internal(
        self, clip_id, ripple: bool = True, record: bool = True, sync: bool = True
    ):
        """单片删除核心；record=False 时不入撤销栈；sync=False 供批量包装。

        返回 {"clip", "ripple_shifts"} 供撤销；失败返回 None。
        """
        deleted_clip = next((c for c in self._clips if c.get("id") == clip_id), None)
        if deleted_clip is None:
            return None
        track_i = int(deleted_clip.get("track", 0) or 0)
        st = float(deleted_clip.get("start_time", 0) or 0)
        dur = float(deleted_clip.get("duration", 0) or 0)
        end = st + dur
        ripple_shifts = []
        self._timeline_store.remove_by_id(clip_id)
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
                    new_st = max(0.0, cst - dur)
                    # 刀4：波纹位移字段写走 store API
                    self._timeline_store.set_fields(c.get("id"), start_time=new_st)
                    ripple_shifts.append({"id": c.get("id"), "old": old, "new": new_st})

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
            logger.error(f'删除内核时间线片段失败: {e}')
        payload = {"clip": deleted_clip, "ripple_shifts": ripple_shifts}
        if record:
            self._record_action({"type": "delete", **payload})
        if sync:
            self._sync_kernel_timeline()
            self._sync_timeline_widget_state()
            self._refresh_preview_to_current_clip()
            self._notify_edit("已删除片段" + ("（波纹）" if ripple else ""))
        return payload

    # [Mixin] 已迁移至 editor_effects_mixin.py
    def _build_speed_easing_expr(self, preset, duration, easing):
        """兼容旧调用；新路径优先 SpeedRamp 预设。"""
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
    # [Mixin] 已迁移至 editor_effects_mixin.py
    # ═══════════════════════════════════════════════════════════════
    # 音乐踩点 (Beat Detection)
    # ═══════════════════════════════════════════════════════════════
    # [Mixin] 已迁移至 editor_effects_mixin.py
    # [Mixin] 已迁移至 editor_effects_mixin.py
    # ═══════════════════════════════════════════════════════════════
    # 运动跟踪 (Motion Tracking)
    # ═══════════════════════════════════════════════════════════════
    # [Mixin] 已迁移至 editor_effects_mixin.py
    # ═══════════════════════════════════════════════════════════════
    # 贴纸系统 (Sticker System) — 预览叠加 + 导出烧录
    # ═══════════════════════════════════════════════════════════════
    def _gather_sticker_params_from_ui(self) -> dict:
        size = 100
        rot = 0
        x = y = 50
        opacity = 1.0
        start_time = 0.0
        end_time = 99999.0
        try:
            size = int(self._sticker_size.value()) if hasattr(self, "_sticker_size") else 100
            rot = int(self._sticker_rot.value()) if hasattr(self, "_sticker_rot") else 0
            x = int(self._sticker_posx.value()) if hasattr(self, "_sticker_posx") else 50
            y = int(self._sticker_posy.value()) if hasattr(self, "_sticker_posy") else 50
            opacity = (int(self._sticker_opacity.value()) if hasattr(self, "_sticker_opacity") else 100) / 100.0
            start_time = float(self._sticker_start.value()) if hasattr(self, "_sticker_start") else 0.0
            end_time = float(self._sticker_end.value()) if hasattr(self, "_sticker_end") else 99999.0
            if end_time <= start_time:
                end_time = 99999.0
        except Exception as e:
            logger.debug("读取贴纸参数失败: %s", e)
        return {
            "size": size, "rotation": rot, "x": x, "y": y, "opacity": opacity,
            "start_time": start_time, "end_time": end_time,
        }

    def _selected_sticker_index(self) -> int:
        stickers = getattr(self, "_active_stickers", None) or []
        if not stickers:
            return -1
        idx = -1
        try:
            if hasattr(self, "_sticker_list") and self._sticker_list is not None:
                idx = self._sticker_list.currentRow()
        except Exception:
            idx = -1
        if idx < 0 or idx >= len(stickers):
            return len(stickers) - 1
        return idx

    def _refresh_sticker_list_ui(self):
        if not hasattr(self, "_sticker_list") or self._sticker_list is None:
            return
        stickers = getattr(self, "_active_stickers", None) or []
        cur = self._sticker_list.currentRow()
        self._sticker_list.blockSignals(True)
        self._sticker_list.clear()
        for s in stickers:
            emoji = s.get("emoji") or ("🖼" if s.get("path") else "★")
            name = s.get("name") or "贴纸"
            tag = " (自定义)" if s.get("path") else ""
            self._sticker_list.addItem(f"{emoji} {name}{tag}")
        if stickers:
            self._sticker_list.setCurrentRow(min(max(cur, 0), len(stickers) - 1))
        self._sticker_list.blockSignals(False)

    def _on_sticker_list_selected(self, row: int):
        stickers = getattr(self, "_active_stickers", None) or []
        if row < 0 or row >= len(stickers):
            return
        self._sync_sticker_sliders_from_item(stickers[row])

    def _sync_sticker_sliders_from_item(self, stk: dict):
        if not stk:
            return
        pairs = (
            ("_sticker_size", int(stk.get("size", 100) or 100)),
            ("_sticker_rot", int(stk.get("rotation", 0) or 0)),
            ("_sticker_posx", int(stk.get("x", 50) or 50)),
            ("_sticker_posy", int(stk.get("y", 50) or 50)),
            ("_sticker_opacity", int(round(float(stk.get("opacity", 1.0) or 1.0) * 100))
             if float(stk.get("opacity", 1.0) or 1.0) <= 1.0
             else int(stk.get("opacity", 100) or 100)),
            ("_sticker_start", float(stk.get("start_time", 0.0) or 0.0)),
            ("_sticker_end", float(stk.get("end_time", 99999.0) or 99999.0)),
        )
        for attr, val in pairs:
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                w.blockSignals(True)
                w.setValue(val)
                w.blockSignals(False)
            except Exception as e:
                logger.debug("同步贴纸参数滑块失败: %s", e)

    def _on_sticker_param_live(self, *_args):
        """拖动贴纸参数：写回选中项并即时预览。"""
        stickers = getattr(self, "_active_stickers", None) or []
        idx = self._selected_sticker_index()
        if idx < 0 or idx >= len(stickers):
            return
        stickers[idx].update(self._gather_sticker_params_from_ui())
        self._touch_project_dirty()
        self._schedule_preview_refresh()

    def _add_sticker(self, name, emoji):
        """添加贴纸到画布（即时预览，无需离线渲染）。"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return
        if not hasattr(self, "_active_stickers") or self._active_stickers is None:
            self._active_stickers = []
        params = self._gather_sticker_params_from_ui()
        # 同位置多层时略微错开，避免完全叠死
        n = len(self._active_stickers)
        if n:
            params["x"] = min(95, max(5, int(params.get("x", 50)) + (n % 5) * 3))
            params["y"] = min(95, max(5, int(params.get("y", 50)) + (n % 4) * 2))
        sticker_info = {
            "id": f"stk_{int(time.time() * 1000)}_{n}",
            "name": name,
            "emoji": emoji,
            "text": name,
            **params,
        }
        self._active_stickers.append(sticker_info)
        self._refresh_sticker_list_ui()
        if hasattr(self, "_sticker_list"):
            self._sticker_list.setCurrentRow(len(self._active_stickers) - 1)
        self._touch_project_dirty()
        self._schedule_preview_refresh()
        self._notify_edit(f"已添加贴纸 {emoji} {name}")

    def _import_sticker(self):
        """导入自定义贴纸图片到画布。"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择贴纸图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)"
        )
        if not path:
            return
        name = os.path.splitext(os.path.basename(path))[0]
        if not hasattr(self, "_active_stickers") or self._active_stickers is None:
            self._active_stickers = []
        params = self._gather_sticker_params_from_ui()
        sticker_info = {
            "id": f"stk_{int(time.time() * 1000)}",
            "name": name,
            "path": path,
            "emoji": "🖼",
            **params,
        }
        self._active_stickers.append(sticker_info)
        self._refresh_sticker_list_ui()
        if hasattr(self, "_sticker_list"):
            self._sticker_list.setCurrentRow(len(self._active_stickers) - 1)
        self._touch_project_dirty()
        self._schedule_preview_refresh()
        self._notify_edit(f"已导入贴纸 {name}")

    def _apply_sticker(self):
        """将当前滑杆参数写到选中贴纸（预览即时可见）。"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return
        stickers = getattr(self, "_active_stickers", None) or []
        if not stickers:
            QMessageBox.warning(self, "提示", "请先点选贴纸库中的贴纸")
            return
        idx = self._selected_sticker_index()
        # ★ A3（2026-10-05）：入撤销栈（此前贴纸参数改了撤不回）。
        before = self._snapshot_stickers()
        stickers[idx].update(self._gather_sticker_params_from_ui())
        self._record_action({"type": "stickers", "before": before,
                             "after": self._snapshot_stickers(), "label": "贴纸参数"})
        self._touch_project_dirty()
        self._schedule_preview_refresh()
        self._notify_edit("贴纸参数已更新到预览")

    def _clear_stickers(self):
        """清除所有贴纸。"""
        # ★ A3（2026-10-05）：入撤销栈 —— 「清空」是最需要后悔药的操作之一。
        before = self._snapshot_stickers()
        if hasattr(self, "_active_stickers"):
            self._active_stickers.clear()
        else:
            self._active_stickers = []
        if hasattr(self, "_sticker_list") and self._sticker_list is not None:
            self._sticker_list.clear()
        self._record_action({"type": "stickers", "before": before,
                             "after": self._snapshot_stickers(), "label": "清除贴纸"})
        self._touch_project_dirty()
        self._schedule_preview_refresh()
        self._notify_edit("已清除贴纸")

    def _snapshot_stickers(self) -> list:
        """贴纸列表的深拷贝快照（撤销/重做用；贴纸是 dict，浅拷贝会串改）。"""
        return [dict(s) for s in (getattr(self, "_active_stickers", None) or [])]

    def _burn_stickers_if_any(self, video_path: str) -> str:
        """导出后把贴纸烧进成片（实现见 editor_burn）。"""
        from app.modules.lego.editor_burn import burn_stickers_if_any
        return burn_stickers_if_any(self, video_path)


    # ------------------------------------------------------------------
    # 剪辑 Agent 与工具栏真实操作补齐
    # ------------------------------------------------------------------
    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _subscribe_provider_activated 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _on_provider_activated_event 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] _list_local_ollama_models 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # ═══════════════════════════════════════════════════════════════════════
    # Agent 新增：配置卡 / 进度卡 / 预览问题卡 / 打分卡 / 脚本卡 构建方法
    # ═══════════════════════════════════════════════════════════════════════

    # [Mixin] _PIPELINE_STAGES 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _stage_progress 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _stage_label 已迁移至 editor_agent_runtime_mixin.py

    # ───────────────── 配置卡（P0 痛点1+8） ─────────────────

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] _get_pipeline_params 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _refresh_provider_status 已迁移至 editor_agent_runtime_mixin.py

    # ───────────────── 进度卡（P0 痛点2） ─────────────────

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _update_pipeline_stage 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _finalize_pipeline_stage 已迁移至 editor_agent_runtime_mixin.py

    # ───────────────── 预览问题卡（P1 痛点5 保守版） ─────────────────

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _render_preview_issues 已迁移至 editor_agent_runtime_mixin.py

    # ───────────────── 打分结果卡（P1 痛点3） ─────────────────

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # ───────────────── 脚本结果卡（P1 痛点4+6） ─────────────────

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] 已迁移至 editor_ai_tools_mixin.py

    # [Mixin] _on_manual_edit_clicked 已迁移至 editor_agent_runtime_mixin.py

    # ═══════════════════════════════════════════════════════════════════════

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # ═══════════════════════════════════════════════════════════════
    # Agent 公开接口（P0-A：EditorCapabilityHandlers 调用的公开方法）
    # 这些方法包装同名私有方法，增加 try/except 保护，避免 handler 直接依赖私有实现
    # ═══════════════════════════════════════════════════════════════

    def _clips_snapshot(self) -> List[Dict[str, Any]]:
        """原子取得 ``_clips`` 的浅拷贝列表。

        为什么需要它：``_clips`` 会被画布桥线程和 autosave 定时器同时接触。
        直接遍历 ``self._clips`` 或把引用交给 ``json.dump`` 都会在
        「非原子替换」进行到一半时读到中间态。本方法在锁内 list() 一次，
        调用方拿到的是**当时那一刻**的稳定列表（元素仍是同一批 dict 引用，
        因为剪辑数据靠 id 定位、不做深拷贝才符合现有契约）。

        用法：跨线程 / 序列化 / 需要遍历过程中修改集合的场景一律用它。
        （刀2·2026-10-18：canonical 出口收敛到 TimelineStore.snapshot，锁语义不变。）
        """
        return self._timeline_store.snapshot()

    def agent_get_timeline_context(self) -> Dict[str, Any]:
        """Agent 公开接口：获取当前时间线上下文（时间线数据、选中片段、播放头位置）。"""
        try:
            return self._get_agent_timeline_context()
        except Exception as e:
            logger.warning(f"[Agent] agent_get_timeline_context 失败: {e}")
            return {"error": str(e), "clip_count": 0, "clips": []}

    def agent_replace_timeline_clips(self, clips: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Agent 公开接口：整条替换时间线片段（工程级快照直导/回滚的落点）。

        复用 ``import_project`` 的重建序列（清空 _clips → 逐个 add_clip → 同步内核 →
        重排 → 刷首帧），但不弹文件框、不碰字幕/贴纸（那些属于独立工程资产）。
        返回诚实结果：失败时 ``ok:False`` + 可执行中文指引，绝不假成功。
        """
        try:
            if not isinstance(clips, list):
                return {"ok": False, "message": "clips 必须是数组"}
            # ⚠️ 整段持有 _clips_lock：本方法是**跨线程写入口**（画布桥调用），
            # 「先清空再逐个 append」若不原子，渲染/autosave/导出线程会读到
            # 空列表或半截列表。RLock 可重入，内部方法再取锁不会死锁。
            lock = getattr(self, "_clips_lock", None)
            if lock is None:
                lock = threading.RLock()
                self._clips_lock = lock
            with lock:
                self._timeline_store.clear()
                self._clip_widgets = []
                self._clip_id_to_widget = {}
                self._current_clip = None

                # 清空现有轨道片段控件
                if hasattr(self, "_timeline_widget") and self._timeline_widget:
                    if hasattr(self._timeline_widget, "all_clip_widgets"):
                        for w in list(self._timeline_widget.all_clip_widgets()):
                            cid = w.clip_data.get("id")
                            self._timeline_widget.remove_clip_widget_by_id(cid)
                    else:
                        for track in getattr(self._timeline_widget, "_tracks", []):
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
                    self._timeline_store.add(clip)
                    if hasattr(self, "_timeline_widget") and self._timeline_widget:
                        widget = self._timeline_widget.add_clip(clip, int(clip.get("track", 0)))
                        if widget is not None:
                            self._clip_widgets.append(widget)
                            if clip.get("id"):
                                self._clip_id_to_widget[clip["id"]] = widget
                    if not self._current_clip:
                        self._current_clip = clip

                self._ensure_linked_audio_clips()
                try:
                    self._heal_linked_av_duration_mismatch()
                except Exception as e:
                    logger.error(f"联动音画时长修复失败: {e}")
                # 主选优先视频片
                for c in self._clips:
                    if str(c.get("type", "")).lower() != "audio" and c.get("path"):
                        self._current_clip = c
                        break
            self._sync_kernel_timeline()
            if hasattr(self, "_timeline_widget") and hasattr(self._timeline_widget, "relayout_clips"):
                self._timeline_widget.relayout_clips()
            self._force_show_first_video_frame()
            self._notify_edit(f"已导入 {len(self._clips)} 个片段（工程快照）")
            return {"ok": True, "message": f"已替换时间线：{len(self._clips)} 个片段"}
        except Exception as e:
            logger.exception(f"[Agent] agent_replace_timeline_clips 失败: {e}")
            return {"ok": False, "message": f"替换时间线失败（非假成功）: {e}"}

    def agent_apply_storyboard_durations(
        self, durations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Agent 公开接口：把分镜记忆规划算出的「建议时长」真正落回 ``_clips``。

        输入 ``durations`` 形如 ``[{"clip_id": "c1", "duration": 6.5}, ...]``。
        按 clip_id 匹配 ``_clips``，只改 ``duration`` 字段（不动其它属性），
        改完触发时间线 widget 重排 + 内核同步 + 首帧刷新（如果可达）。
        匹配不到的 clip_id 计入 ``unmatched``，绝不假成功。

        诚实失败：参数非法 / 剪辑模块没就绪 → ``ok:false`` + message。
        """
        try:
            if not isinstance(durations, list):
                return {"ok": False, "message": "durations 必须是数组"}
            clips = getattr(self, "_clips", [])
            if not isinstance(clips, list):
                return {"ok": False, "message": "_clips 不是数组"}
            applied = 0
            unmatched: List[str] = []
            for d in durations:
                if not isinstance(d, dict):
                    continue
                cid = d.get("clip_id")
                dur = d.get("duration")
                if not isinstance(cid, str) or not cid:
                    continue
                if not isinstance(dur, (int, float)) or not float(dur) > 0:
                    continue
                target = next((c for c in clips if c.get("id") == cid), None)
                if target is None:
                    unmatched.append(cid)
                    continue
                target["duration"] = float(dur)
                # out_point 跟着改（保持 in_point 起点不动）
                try:
                    in_pt = float(target.get("in_point", 0) or 0)
                    target["out_point"] = in_pt + float(dur)
                except Exception:
                    logger.debug("storyboard duration apply: out_point 联动失败 (clip=%s)", cid, exc_info=True)
                applied += 1
            # 同步内核 + 刷新
            try:
                self._sync_kernel_timeline()
            except Exception:
                logger.debug("storyboard duration apply: _sync_kernel_timeline 失败", exc_info=True)
            try:
                if hasattr(self, "_timeline_widget") and self._timeline_widget:
                    if hasattr(self._timeline_widget, "relayout_clips"):
                        self._timeline_widget.relayout_clips()
                    self._force_show_first_video_frame()
            except Exception:
                logger.debug("storyboard duration apply: 刷新时间线失败", exc_info=True)
            self._notify_edit(f"分镜记忆已落回 {applied} 个片段的时长")
            return {
                "ok": True,
                "applied": applied,
                "unmatched": unmatched,
                "message": f"已应用 {applied} 个片段（未匹配 {len(unmatched)} 个）",
            }
        except Exception as e:
            logger.exception(f"[Agent] agent_apply_storyboard_durations 失败: {e}")
            return {"ok": False, "message": f"应用失败（非假成功）: {e}"}

    def agent_send_selected_to_canvas(self, clip_id: str = "") -> Dict[str, Any]:
        """把选中（或指定）视频片段推到画布 outbox；不改时间线。"""
        clip = None
        if clip_id:
            clip = next((c for c in getattr(self, "_clips", []) if c.get("id") == clip_id), None)
        if clip is None:
            targets = self._property_target_clips() if hasattr(self, "_property_target_clips") else []
            clip = targets[0] if targets else None
        if not isinstance(clip, dict):
            return {"success": False, "message": "请先在时间线选中一个片段"}
        path = clip.get("path") or clip.get("file_path") or ""
        if not path or not os.path.exists(path):
            return {"success": False, "message": f"片段文件不存在: {path or '(空)'}"}
        try:
            from app.core.canvas_bridge import push_editor_to_canvas, get_canvas_bridge
            from app.core.editor_canvas_link import outbox_fields_from_clip
        except ImportError:
            from core.canvas_bridge import push_editor_to_canvas, get_canvas_bridge  # type: ignore
            from core.editor_canvas_link import outbox_fields_from_clip  # type: ignore
        get_canvas_bridge().start()
        title = clip.get("name") or clip.get("title") or os.path.basename(path)
        res = push_editor_to_canvas(
            path,
            title=str(title),
            source="editor",
            extra=outbox_fields_from_clip(clip),
        )
        if res.get("success"):
            self._notify_edit(res.get("message") or "已推送到画布")
            self._record_ai_tool_history(res.get("message") or "发送到画布")
        return res if isinstance(res, dict) else {"success": False, "message": str(res)}

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    def agent_ripple_delete_range(
        self,
        t_in: float,
        t_out: float,
        *,
        track=None,
        record: bool = True,
    ) -> Dict[str, Any]:
        """
        Agent 公开接口：时间线波纹删除 [t_in, t_out)，同步 widget/内核/预览，可撤销（M4）。

        track 未指定时默认主视频轨（find_track_index_by_type），避免误伤全轨。
        """
        try:
            if track is None:
                tw = getattr(self, "_timeline_widget", None)
                if tw is not None and hasattr(tw, "find_track_index_by_type"):
                    track = tw.find_track_index_by_type("video", default=0)
                else:
                    track = 0
            result = self._apply_ripple_delete_range(
                float(t_in), float(t_out), track=track, record=record,
            )
            ok = bool(getattr(result, "ok", False) or getattr(result, "steps", None))
            return {
                "action": "ripple_delete",
                "success": ok,
                "message": getattr(result, "message", "") or ("波纹删除完成" if ok else "波纹删除失败"),
                "deleted_duration": float(getattr(result, "deleted_duration", 0) or 0),
                "track": track,
            }
        except Exception as e:
            logger.exception(f"[Agent] agent_ripple_delete_range 失败: {e}")
            return {
                "action": "ripple_delete",
                "success": False,
                "message": f"波纹删除失败（非假成功）: {e}",
            }

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] _on_edit_agent_chunk 已迁移至 editor_agent_runtime_mixin.py

    def _on_edit_agent_result(self, user_text: str, raw: str):
        """处理模型输出并应用剪辑指令（Plan 模式下先展示规划等待确认）。"""
        # 顶层 try/except 兜底（P0 闪退修复）：
        # 本槽由 QThread 信号触发，任何异常会让槽函数崩溃、主线程闪退。
        # 兜底时记录完整堆栈 + 在 Agent 面板显示错误消息，避免静默崩溃。
        try:
            self._do_on_edit_agent_result(user_text, raw)
            # ✅ 激活 AgentBrain Hebbian 学习（P0）：成功路径强化相关突触
            self._agent_brain_learn(success=True, user_text=user_text)
            # 知心秘书完整档：记录本轮对话到多轮历史
            self._record_agent_turn(user_text, raw)
        except Exception as e:
            logger.exception(f"[Agent] _on_edit_agent_result 处理失败: {e}")
            # ❌ 失败路径弱化相关突触，让 Agent 下次倾向其他路径
            self._agent_brain_learn(success=False, user_text=user_text, error=str(e))
            try:
                self._append_agent_message("系统", f"❌ Agent 结果处理异常: {e}")
            except Exception:
                # 二次异常时静默，避免连环崩溃（已记录到 logger）
                pass

    def _do_on_edit_agent_result(self, user_text: str, raw: str):
        """实际处理模型输出并应用剪辑指令（被 _on_edit_agent_result 包裹）。"""
        text = raw.strip() or self._edit_agent_stream_buffer.strip()
        if text.startswith("错误:") or text.startswith("API 错误"):
            self._append_agent_message("系统", f"❌ {text}")
            self._append_agent_message(
                "系统",
                "请到「模型管理」确认 DeepSeek 等已保存并激活（卡片圆形按钮为绿），再在 Agent 下拉选 ★ DeepSeek。",
            )
            return

        # 方案三（Function Calling 体验）：先判定是否为可执行 JSON 指令，
        # 是则执行；不是则视为自由对话回复，直接展示原文（不再误报"无指令"）。
        if self._is_agent_plan_mode():
            plan_steps, commands = self._parse_agent_plan(text)
            if plan_steps:
                self._append_agent_message("Agent", text[:1200] if text else "模型无输出。")
                self._show_agent_plan(plan_steps, commands, user_text)
                self._append_agent_message("系统", "规划已生成，请确认后执行。")
                return
            # Plan 解析失败，回退到普通指令解析

        commands = self._parse_agent_commands(user_text, text)
        if commands:
            self._append_agent_message("Agent", text[:1200] if text else "模型无输出。")
            results = self._apply_agent_commands_to_editor(commands)
            summary = self._format_agent_command_summary(results)
            self._append_agent_message("系统", summary or "剪辑指令已处理。")
            return

        # 未解析出可执行指令 → 当作自由对话回复直接展示
        self._append_agent_message("Agent", text[:2000] if text else "模型无输出。")

    def _parse_agent_plan(self, text: str):
        """解析 Plan 模式的 {plan, commands} 结构。"""
        if not text:
            return [], []
        try:
            # 尝试提取 JSON 对象
            import re
            match = re.search(r'\{[\s\S]*\}', text)
            if not match:
                return [], []
            data = json.loads(match.group(0))
            plan_steps = data.get("plan", [])
            raw_commands = data.get("commands", [])
            # 转换为 EditCommand
            from app.core.llm_editor import EditCommand
            commands = []
            for item in raw_commands:
                if not isinstance(item, dict):
                    continue
                commands.append(EditCommand(
                    action=item.get("action", "answer"),
                    params=item.get("params", {}),
                    confidence=item.get("confidence", 0.9),
                    raw_text="",
                    description=item.get("description", item.get("action", "")),
                ))
            return plan_steps, commands
        except Exception as e:
            logger.debug(f"Plan 解析失败: {e}")
            return [], []

    # [Mixin] _show_agent_plan 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _confirm_agent_plan 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _cancel_agent_plan 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _on_agent_feedback 已迁移至 editor_agent_runtime_mixin.py

    def _on_edit_agent_error(self, error: str):
        """模型调用失败时回退到本地规则解析。"""
        # 顶层 try/except 兜底（P0 闪退修复）：
        # 本槽是高频错误路径（模型 API 失败时触发），内部 _parse_agent_commands
        # 会调用 llm_editor.parse，若返回 None 会再次 AttributeError，
        # 错误处理函数里再抛异常会导致主线程崩溃。
        try:
            self._append_agent_message(
                "系统",
                f"模型调用失败: {error}\n"
                "将仅用本地规则尝试解析（能力有限，不是模型已成功）。",
            )
            user_text = getattr(self, '_edit_agent_last_user_text', "")
            # ❌ 模型调用失败：弱化相关突触（P0 激活 AgentBrain 学习）
            self._agent_brain_learn(success=False, user_text=user_text, error=error)
            if not user_text:
                return
            commands = self._parse_agent_commands(user_text, "")
            if not commands:
                self._append_agent_message(
                    "系统",
                    "本地规则也未解析到可执行剪辑指令（未改时间线）。",
                )
                return
            results = self._apply_agent_commands_to_editor(commands)
            summary = self._format_agent_command_summary(results)
            self._append_agent_message(
                "系统",
                f"本地规则回退结果：{summary}",
            )
        except Exception as e:
            logger.exception(f"[Agent] _on_edit_agent_error 处理失败: {e}")
            try:
                self._append_agent_message("系统", f"❌ Agent 错误处理异常: {e}")
            except Exception:
                logger.warning("Agent 错误消息输出失败", exc_info=True)

    # [Mixin] _on_edit_agent_stopped 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _on_edit_agent_finished 已迁移至 editor_agent_runtime_mixin.py

    # ────────────── AgentBrain 学习机制（P0 激活）──────────────
    def _agent_brain_learn(self, success: bool, user_text: str = "", error: str = "",
                           related: Optional[List[str]] = None):
        """激活 AgentBrain Hebbian 学习机制（P0）。

        根据本次 Agent 调用的成败，调整相关神经元的突触权重：
        - 成功：强化 user_text 关键词匹配到的 capability 突触
        - 失败：弱化相关突触，让 Agent 下次倾向其他路径

        学习失败不影响主流程（异常隔离），符合 .trae/rules/2.md §六.4 异常处理规范。

        Args:
            success: 本次 Agent 调用是否成功
            user_text: 用户原始输入文本（用于推断相关 capability）
            error: 失败时的错误信息（仅用于日志）
            related: 显式指定相关 capability（优先于文本推断；撤销反馈回路用）
        """
        try:
            from app.core.agent_brain import agent_brain
            related_caps = related if related else self._extract_related_capabilities(user_text)
            feedback = {
                "type": "success" if success else "quality",
                "related_capabilities": related_caps,
                "severity": "low" if success else "medium",
            }
            agent_brain.learn_from_feedback(feedback)
            logger.debug(f"[Agent] AgentBrain 学习触发: success={success}, related={related_caps}")
        except Exception as e:
            # 学习失败不能影响主流程（异常隔离）
            logger.warning(f"[Agent] AgentBrain 学习失败: {e}")

    # ---- B1 撤销反馈回路：用户 Ctrl+Z 是最诚实的负反馈 ----

    def _on_agent_action_undone(self, action: dict) -> None:
        """用户撤销了一条 Agent 来源的编辑 → Hebbian 负反馈（弱化相关突触）。

        用户没说一句话，但用 Ctrl+Z 投了票——这比任何文字反馈都诚实。
        尝试把撤销栈动作映射回具体 capability，让弱化打得更准；
        映射不出也不影响学习（_extract_related_capabilities 有兜底）。
        """
        label = action.get("label") or action.get("type") or "unknown"
        try:
            related = self._infer_agent_action_capabilities(action)
            self._agent_brain_learn(
                success=False,
                user_text=f"撤销 Agent 的 {label} 操作",
                error=f"user_undo:{label}",
                related=related or None,
            )
            logger.debug(f"[Agent] 撤销负反馈已触发: {label} → {related}")
        except Exception:
            logger.debug("[Agent] 撤销负反馈失败（不影响撤销主流程）", exc_info=True)

    def _on_agent_action_redone(self, action: dict) -> None:
        """撤销后又被重做 → 收回负反馈（净学习量归零，符合直觉）。"""
        label = action.get("label") or action.get("type") or "unknown"
        try:
            related = self._infer_agent_action_capabilities(action)
            self._agent_brain_learn(
                success=True,
                user_text=f"重做 Agent 的 {label} 操作",
                related=related or None,
            )
        except Exception:
            logger.debug("[Agent] 重做正反馈失败（不影响重做主流程）", exc_info=True)

    def _infer_agent_action_capabilities(self, action: dict) -> List[str]:
        """把撤销栈动作（type/label/before-after diff）映射回 capability_id 列表。

        映射顺序：label 关键词 > type 关键词 > edit_clip 的 before/after diff >
        compound 步骤递归。全部落空返回 []（由调用方走文本推断兜底）。
        """
        caps: List[str] = []
        t = (action.get("type") or "").lower()
        label = (action.get("label") or "").lower()
        text = f"{t} {label}"
        if "delete" in text:
            caps.append("editor.ripple_delete_range")
        if "split" in text:
            caps.append("editor.split_clip")
        if "trim" in text or "resize" in text:
            caps.append("editor.trim_clip")
        if "move" in text:
            caps.append("editor.move_clip")
        if "volume" in text or "audio" in text:
            caps.append("editor.set_clip_properties")
        if "lut" in text or "color" in text or "filter" in text:
            caps.append("editor.apply_filter")
        if "transition" in text:
            caps.append("editor.add_transition")
        if not caps and t == "edit_clip":
            before = action.get("before") or {}
            after = action.get("after") or {}
            if (before.get("start_time") != after.get("start_time")
                    or before.get("track") != after.get("track")):
                caps.append("editor.move_clip")
            elif any(before.get(k) != after.get(k)
                     for k in ("duration", "in_point", "out_point")):
                caps.append("editor.trim_clip")
            else:
                caps.append("editor.set_clip_properties")
        if not caps and action.get("type") == "compound":
            for step in action.get("steps") or []:
                caps.extend(self._infer_agent_action_capabilities(step))
        seen: set = set()
        return [c for c in caps if not (c in seen or seen.add(c))]

    def _extract_related_capabilities(self, user_text: str) -> List[str]:
        """从用户输入文本推断相关 capability_id（用于 AgentBrain 学习）。

        通过关键词匹配，把 user_text 映射到 AgentBrain 注册的 capability_id
        （见 app/core/agent_brain.py 神经元注册表）。
        无匹配时返回默认的剪辑相关 capability，确保学习始终有效。

        Args:
            user_text: 用户原始输入文本

        Returns:
            List[str]: 匹配到的 capability_id 列表
        """
        if not user_text:
            return ["pipeline.execute_editing"]

        text = user_text.lower()
        # 关键词 → capability_id 映射（与 agent_brain.py 神经元注册表保持一致）
        keyword_to_cap = {
            "pipeline.execute_editing": ["精剪", "成片", "导出", "剪辑"],
            "editor.split_clip": ["切分", "切割", "split"],
            "editor.apply_filter": ["滤镜", "调色", "filter"],
            "editor.add_transition": ["转场", "过渡", "transition"],
            "editor.ripple_delete_range": ["波纹删", "波纹删除", "ripple"],
            "editor.suggest_cleanup": ["去水词", "清静音", "填充词", "suggest_cleanup"],
            "ext.run_extension": ["插件", "拓展", "效果"],
            "ext.run_skill": ["技能", "skill", "导演"],
            "model.chat": ["对话", "聊天", "问答", "生成文案"],
            "pipeline.generate": ["生成", "视频", "抽卡", "画面"],
            "pipeline.generate_script": ["脚本", "创意", "镜头顺序", "配乐"],
            "editor.get_timeline_context": ["时间线", "上下文", "轨道"],
        }

        matched = []
        for cap_id, keywords in keyword_to_cap.items():
            if any(kw.lower() in text for kw in keywords):
                matched.append(cap_id)

        # 无匹配时返回默认剪辑 capability，确保 reinforce_path 始终被调用
        return matched if matched else ["pipeline.execute_editing"]

    # ────────────── Agent 全链路事件处理 ──────────────
    # [Mixin] _on_pipeline_event 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _handle_video_generation_done 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _handle_waiting_preview 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _handle_pipeline_progress 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] _reset_pipeline_button 已迁移至 editor_agent_runtime_mixin.py

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

            # 提取到 JSON 但无有效 action 指令 → 视为自由对话文本
            if items is not None:
                return []

            # 模型未输出 JSON（自由对话）时，用离线规则对用户原始输入做兜底，
            # 仅在用户输入命中剪辑指令模式时补救执行，闲聊文本不会命中。
            result = llm_editor.parse(user_text, use_ai=False, timeline_context=self._get_agent_timeline_context())
            return result.commands if result.success else []
        except Exception as e:
            logger.error(f'剪辑 Agent 指令解析失败: {e}')
            return []

    # _apply_agent_commands_to_editor / _apply_agent_command 已迁移到 ai_agent_panel.py（AiAgentPanelMixin）

    def _agent_dispatch(self, cap_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """统一调用层便捷封装 —— Agent 通过 dispatcher 访问三大模块"""
        try:
            from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest
            result = capability_dispatcher.invoke(CapabilityRequest(
                capability_id=cap_id, params=params, caller="agent",
                agent_mode=self._get_agent_session_mode() if hasattr(self, "_get_agent_session_mode") else "",
                approved=True,
            ))
            if result.success:
                msg = str(result.output)[:120] if result.output is not None else "ok"
                return {"action": cap_id, "success": True, "message": msg}
            err = result.error or "未知错误"
            return {
                "action": cap_id,
                "success": False,
                "message": f"能力 {cap_id} 失败（非假成功）: {err}",
            }
        except Exception as e:
            logger.warning(f"[Agent] dispatch {cap_id} 失败: {e}")
            return {"action": cap_id, "success": False, "message": str(e)}

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # ────────────── Agent 全链路闭环入口 ──────────────
    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] _on_full_pipeline_done 已迁移至 editor_agent_runtime_mixin.py

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    def agent_execute_pipeline_editing(self, editing_script: Dict[str, Any],
                                        session_id: str = "") -> str:
        """Agent 公开接口：执行精修剪辑脚本并输出成片。"""
        try:
            return self._execute_pipeline_editing(editing_script, session_id)
        except Exception as e:
            logger.exception(f"[Agent] agent_execute_pipeline_editing 失败: {e}")
            return ""

    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    # [Mixin] _create_edit_agent_panel 已迁移至 editor_agent_panel_mixin.py
    @staticmethod
    def _find_system_font() -> str:
        """查找系统可用字体文件路径（用于 drawtext 字幕渲染）。"""
        import os as _os
        import sys as _sys
        font_candidates = []
        if _sys.platform == "win32":
            windir = _os.environ.get("WINDIR", r"C:\Windows")
            font_dir = _os.path.join(windir, "Fonts")
            if _os.path.isdir(font_dir):
                # 优先查找常见中文字体
                for name in ["msyh.ttc", "msyhbd.ttc", "simhei.ttf",
                             "simsun.ttc", "arial.ttf"]:
                    p = _os.path.join(font_dir, name)
                    if _os.path.isfile(p):
                        font_candidates.append(p)
                # 兜底：查找第一个 .ttf/.ttc 文件
                if not font_candidates:
                    try:
                        for f in _os.listdir(font_dir):
                            if f.lower().endswith((".ttf", ".ttc", ".otf")):
                                font_candidates.append(_os.path.join(font_dir, f))
                                break
                    except Exception as e:
                        logger.debug("遍历字体目录失败: %s", e)
        elif _sys.platform == "darwin":
            for d in ["/System/Library/Fonts", "/Library/Fonts"]:
                if _os.path.isdir(d):
                    for name in ["PingFang.ttc", "STHeiti Medium.ttc", "Arial.ttf"]:
                        p = _os.path.join(d, name)
                        if _os.path.isfile(p):
                            font_candidates.append(p)
                            break
        else:
            for d in ["/usr/share/fonts", "/usr/local/share/fonts"]:
                if _os.path.isdir(d):
                    for root, dirs, files in _os.walk(d):
                        for f in files:
                            if f.lower().endswith((".ttf", ".ttc", ".otf")):
                                font_candidates.append(_os.path.join(root, f))
                                break
                        if font_candidates:
                            break

        if font_candidates:
            logger.info(f"[pipeline] 找到系统字体: {font_candidates[0]}")
            return font_candidates[0]
        logger.warning("[pipeline] 未找到系统字体，字幕将被跳过")
        return ""

    @staticmethod
    def _find_pipeline_ffmpeg() -> str:
        """查找 ffmpeg：优先复用项目 ffmpeg_utils，回退 core 层 + 系统 PATH。"""
        try:
            from app.core.ffmpeg_utils import find_ffmpeg
            path = find_ffmpeg()
            if path and os.path.isfile(path):
                return path
        except Exception as e:
            logger.debug("查找FFmpeg路径失败: %s", e)
        try:
            from app.core.ai.video_generation_client import VideoGenerationClient
            return VideoGenerationClient._find_ffmpeg() or ""
        except Exception:
            import shutil as _sh
            return _sh.which("ffmpeg") or _sh.which("ffmpeg.exe") or ""

    def _format_extension_result(self, result: Any) -> str:
        """格式化扩展调用结果为简短文本。"""
        if result is None:
            return "无返回值"
        if isinstance(result, bool):
            return "成功" if result else "失败"
        if isinstance(result, dict):
            return result.get("message") or result.get("status") or str(result)[:100]
        if isinstance(result, str):
            return result[:100]
        return str(result)[:100]

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

    def _perform_split_clip(self, clip: Dict[str, Any], split_time: float):
        """执行单次切分（不记撤销、不刷新）。成功返回 undo action dict，否则 None。"""
        if not isinstance(clip, dict):
            return None
        # 必须用 _clips 里的活引用
        cid = clip.get("id")
        live = next((c for c in (self._clips or []) if c.get("id") == cid), clip)
        start = float(live.get("start_time", 0) or 0)
        duration = float(live.get("duration", 0) or 0)
        local_time = float(split_time) - start
        if local_time <= 1e-4 or local_time >= duration - 1e-4:
            return None

        new_clip = dict(live)
        new_clip["id"] = f"{live.get('id', 'clip')}_split_{int(time.time() * 1000)}"
        new_clip["start_time"] = start + local_time
        new_clip["duration"] = duration - local_time
        new_clip["in_point"] = float(live.get("in_point", 0) or 0) + local_time
        new_clip["out_point"] = new_clip["in_point"] + new_clip["duration"]

        original_out = float(live.get("in_point", 0) or 0) + duration
        new_out_point = float(live.get("in_point", 0) or 0) + local_time
        # 刀4：真相源字段写走 store API；live 不在真相源时兜底写传入引用（理论不可达）
        if not self._timeline_store.set_fields(cid, duration=local_time, out_point=new_out_point):
            live["duration"] = local_time          # ratchet-exempt: 片段已脱离真相源的兜底
            live["out_point"] = new_out_point      # ratchet-exempt: 保持旧路径行为不变
        self._timeline_store.add(new_clip)
        if hasattr(self, "_timeline_widget") and self._timeline_widget:
            widget = self._timeline_widget.add_clip(new_clip, int(new_clip.get("track", 0)))
            if widget is not None:
                self._clip_widgets.append(widget)
                self._clip_id_to_widget[new_clip["id"]] = widget
        self._current_clip = new_clip
        return {
            "type": "split",
            "original_clip": live,
            "new_clip": new_clip,
            "original_duration": duration,
            "original_out_point": original_out,
        }

    def _clips_covering_time(self, t: float):
        hits = []
        for c in getattr(self, "_clips", []) or []:
            if not isinstance(c, dict):
                continue
            st = float(c.get("start_time", 0) or 0)
            dur = float(c.get("duration", 0) or 0)
            if st + 1e-4 < t < st + dur - 1e-4:
                hits.append(c)
        return hits

    def _expand_cut_targets_with_linked_av(self, seeds, cut_t: float):
        """种子片段 + 同 path/同 start 联动片（仍覆盖 cut_t）去重。"""
        by_id = {}
        for c in seeds or []:
            if not isinstance(c, dict) or not c.get("id"):
                continue
            st = float(c.get("start_time", 0) or 0)
            dur = float(c.get("duration", 0) or 0)
            if not (st + 1e-4 < cut_t < st + dur - 1e-4):
                continue
            by_id[c["id"]] = c
            try:
                for p in self._find_linked_av_partners(c) or []:
                    pst = float(p.get("start_time", 0) or 0)
                    pdur = float(p.get("duration", 0) or 0)
                    if pst + 1e-4 < cut_t < pst + pdur - 1e-4 and p.get("id"):
                        by_id[p["id"]] = p
            except Exception as e:
                logger.debug("联动音画扩展失败: %s", e)
        return list(by_id.values())

    def _cut_at_timeline_time(self, cut_t: float, seed_clips=None) -> Dict[str, Any]:
        """在绝对时间切开：强制联动音画，多片一条 compound undo。"""
        cut_t = float(cut_t)
        if seed_clips:
            targets = self._expand_cut_targets_with_linked_av(seed_clips, cut_t)
        else:
            targets = self._expand_cut_targets_with_linked_av(
                self._clips_covering_time(cut_t), cut_t
            )
        if not targets:
            return {"action": "split_clip", "success": False, "message": "该时间没有可切开的片段"}

        # 视频优先，避免只扩到音频
        def _rank(c):
            is_audio = str(c.get("type", "")).lower() == "audio"
            return (1 if is_audio else 0, int(c.get("track", 0) or 0))

        targets = sorted(targets, key=_rank)
        steps = []
        done = set()
        for clip in targets:
            cid = clip.get("id")
            if cid in done:
                continue
            live = next((c for c in self._clips if c.get("id") == cid), None)
            if live is None:
                continue
            act = self._perform_split_clip(live, cut_t)
            if act:
                steps.append(act)
                done.add(cid)

        if not steps:
            return {"action": "split_clip", "success": False, "message": "无法在该位置切开（可能已在片缘）"}

        if len(steps) == 1:
            self._record_action(steps[0])
        else:
            self._record_action({"type": "compound", "steps": steps, "label": "razor_cut"})
        self._sync_kernel_timeline()
        self._sync_timeline_widget_state()
        self._refresh_preview_to_current_clip()
        n = len(steps)
        return {
            "action": "split_clip",
            "success": True,
            "message": f"已在 {cut_t:.2f}s 切开 {n} 个片段" if n > 1 else f"已在 {cut_t:.2f}s 切分片段",
            "count": n,
        }

    def _split_clip_at_time(self, clip: Dict[str, Any], split_time: float) -> Dict[str, Any]:
        """在指定时间切分片段（含联动音画），并同步到时间线 UI。"""
        return self._cut_at_timeline_time(float(split_time), seed_clips=[clip])

    # ── P1-C: Agent 反馈标记 emit ──

    def _emit_agent_marker(self, marker: dict) -> None:
        """向 EventBus 追加一条 Agent 操作标记（供 TimelineMarkerLayer 渲染）。

        Args:
            marker: {clip_id, time, action, status, message, color?}
        """
        try:
            import time as _t
            from .core import EventBus, EventType
            marker["id"] = marker.get("id") or f"agent_{marker.get('action', 'unk')}_{int(_t.time() * 1000)}"
            existing = list(getattr(self, "_agent_markers", []) or [])
            existing.append(marker)
            self._agent_markers = existing
            bus = EventBus.get_instance()
            bus.emit(EventType.AGENT_MARKERS_UPDATED, {"markers": existing})
        except Exception as e:
            logger.debug("[Agent] _emit_agent_marker 失败: %s", e)

    def agent_split_clip(self, clip: Dict[str, Any], split_time: float) -> Dict[str, Any]:
        """Agent 公开接口：在指定时间切分片段并同步 UI。"""
        try:
            res = self._split_clip_at_time(clip, split_time)
            # P1-C: emit Agent 反馈标记到时间线
            try:
                self._emit_agent_marker({
                    "clip_id": clip.get("id"),
                    "time": split_time,
                    "action": "split_clip",
                    "status": "success",
                    "message": res.get("message", "") if isinstance(res, dict) else "切分成功",
                })
            except Exception:
                logger.warning("切分成功通知发送失败", exc_info=True)
            return res
        except Exception as e:
            logger.exception(f"[Agent] agent_split_clip 失败: {e}")
            # P1-C: 失败也 emit 标记
            try:
                self._emit_agent_marker({
                    "clip_id": clip.get("id"),
                    "time": split_time,
                    "action": "split_clip",
                    "status": "failed",
                    "message": str(e),
                })
            except Exception:
                logger.warning("切分失败通知发送失败", exc_info=True)
            return {"action": "split_clip", "success": False, "message": str(e)}

    def _copy_clip_data_to_timeline(self, clip: Dict[str, Any], offset: float = 1.0):
        """复制片段数据并添加到时间线。"""
        new_clip = dict(clip)
        new_clip["id"] = f"{clip.get('id', 'clip')}_copy_{int(time.time() * 1000)}"
        new_clip["start_time"] = float(clip.get("start_time", 0)) + float(offset or 1.0)
        self._timeline_store.add(new_clip)
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

    def _ensure_linked_audio_clips(self):
        """为缺少联动音频的视频片补 audio 轨片段（旧 autosave / 仅视频工程）。"""
        import time as _time

        if not hasattr(self, "_timeline_widget") or self._timeline_widget is None:
            return
        tw = self._timeline_widget
        audio_track_i = (
            tw.find_track_index_by_type("audio", default=1)
            if hasattr(tw, "find_track_index_by_type")
            else 1
        )
        existing = list(getattr(self, "_clips", []) or [])

        def _has_linked_audio(vclip: dict) -> bool:
            vpath = str(vclip.get("path") or "")
            vst = float(vclip.get("start_time", 0) or 0)
            tracks = getattr(tw, "_tracks", []) or []
            for c in existing:
                is_audio = str(c.get("type", "")).lower() == "audio"
                if not is_audio:
                    ti = int(c.get("track", -1) or -1)
                    if not (0 <= ti < len(tracks) and tracks[ti].get("type") == "audio"):
                        continue
                if str(c.get("path") or "") != vpath:
                    continue
                if abs(float(c.get("start_time", 0) or 0) - vst) < 1e-3:
                    return True
            return False

        added = []
        for clip in list(existing):
            ctype = str(clip.get("type", "video") or "video").lower()
            ti = int(clip.get("track", 0) or 0)
            tracks = getattr(tw, "_tracks", []) or []
            on_video = ctype == "video" or (
                0 <= ti < len(tracks) and tracks[ti].get("type") == "video"
            )
            if not on_video or ctype == "audio":
                continue
            path = clip.get("path")
            if not path or not os.path.exists(path):
                # 相对路径再试 cwd
                alt = os.path.normpath(os.path.join(os.getcwd(), str(path or "")))
                if not os.path.exists(alt):
                    continue
                clip["path"] = alt
                path = alt
            if _has_linked_audio(clip):
                continue
            audio_clip = {
                "id": f"audio_{int(_time.time() * 1000)}_{len(added)}",
                "name": os.path.basename(path) + " (音频)",
                "path": path,
                "start_time": float(clip.get("start_time", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
                "track": audio_track_i,
                "type": "audio",
                "effects": {},
                "transitions": [],
            }
            widget = tw.add_clip(audio_clip, audio_track_i)
            if widget is not None:
                self._clip_widgets.append(widget)
                self._clip_id_to_widget[audio_clip["id"]] = widget
                self._timeline_store.add(audio_clip)
                existing.append(audio_clip)
                added.append(audio_clip)
        if added:
            self._touch_project_dirty()
            logger.info(f'已补全 {len(added)} 条联动音频（波形）')

    def _resolve_media_duration(self, file_path: str) -> float:
        """媒体时长 SSOT：ffprobe / PreviewManager / OpenCV 取最大可信值。"""
        duration = 0.0
        try:
            duration = max(duration, float(self._probe_video_duration(file_path) or 0.0))
        except Exception:
            logger.debug("视频时长探测失败", exc_info=True)
        try:
            pm = getattr(self, "_preview_manager", None)
            if pm is not None and self._media_paths_equal(
                getattr(pm, "_video_source", None), file_path
            ):
                # 仅复用已打开源，勿为取时长额外 open（会冲掉完整帧数校正）
                duration = max(duration, float(getattr(pm, "_video_duration", 0) or 0))
        except Exception as e:
            logger.debug("PreviewManager 取时长失败: %s", e)
        # ffprobe 已给出可信时长时跳过再开一轮 OpenCV（导入路径减负）
        if duration > 0.05:
            return float(duration)
        try:
            import cv2
            cap = cv2.VideoCapture(file_path, cv2.CAP_FFMPEG)
            if cap.isOpened():
                fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 30.0
                fc = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if fc > 0 and fps > 0:
                    duration = max(duration, fc / fps)
            cap.release()
        except Exception:
            logger.debug("视频资源释放失败", exc_info=True)
        return float(duration or 0.0)

    def _heal_av_clips_signature(self):
        """用于 heal 幂等：片段 id/时长/起止未变则跳过重探。"""
        clips = getattr(self, "_clips", []) or []
        return tuple(
            (
                c.get("id"),
                str(c.get("type") or ""),
                str(c.get("path") or ""),
                round(float(c.get("start_time", 0) or 0), 3),
                round(float(c.get("duration", 0) or 0), 3),
                round(float(c.get("in_point", 0) or 0), 3),
                round(float(c.get("out_point", 0) or 0), 3),
            )
            for c in clips
        )

    def _heal_linked_av_duration_mismatch(self) -> int:
        """修复同 path、同 start 的音画时长脱节（视频远短于文件/音频）。

        典型：CAP_PROP 低估或只裁了视频轨，播放 ~8s 后黑场只剩声。
        仅当视频时长明显短于文件真实时长，且联动音频接近真实时长时扩展视频。
        幂等：签名未变则直接返回，避免每次按 ▶ 都 ffprobe/open。
        """
        sig = self._heal_av_clips_signature()
        if sig and sig == getattr(self, "_heal_av_sig", None):
            return 0
        healed = 0
        tw = getattr(self, "_timeline_widget", None)
        for clip in list(getattr(self, "_clips", []) or []):
            if str(clip.get("type", "")).lower() == "audio":
                continue
            path = self._resolve_clip_media_path(str(clip.get("path") or ""))
            if not path or not os.path.exists(path):
                continue
            v_dur = float(clip.get("duration", 0) or 0)
            if v_dur <= 0.05:
                continue
            partners = self._find_linked_av_partners(clip)
            audio_partners = [
                p for p in partners if str(p.get("type", "")).lower() == "audio"
            ]
            if not audio_partners:
                continue
            a = max(audio_partners, key=lambda p: float(p.get("duration", 0) or 0))
            a_dur = float(a.get("duration", 0) or 0)
            if a_dur <= v_dur * 1.25:
                continue
            file_dur = self._resolve_media_duration(path)
            if file_dur <= 0.05:
                file_dur = a_dur
            # 视频明显短于文件，且音频接近文件全长 → 视为误裁，扩展视频
            if v_dur >= file_dur * 0.85:
                continue
            if a_dur < file_dur * 0.85:
                continue
            in_p = float(clip.get("in_point", 0) or 0)
            new_dur = max(0.05, min(a_dur, max(0.05, file_dur - in_p)))
            if new_dur <= v_dur + 0.05:
                continue
            # 刀4：字段写走 store API
            self._timeline_store.set_fields(clip.get("id"), duration=new_dur, out_point=in_p + new_dur)
            if tw is not None and hasattr(tw, "all_clip_widgets"):
                for w in tw.all_clip_widgets():
                    if w.clip_data.get("id") == clip.get("id"):
                        w.clip_data["duration"] = new_dur
                        w.clip_data["out_point"] = in_p + new_dur
                        tw.position_clip_widget(w)
                        break
            healed += 1
            logger.info(
                "联动音画时长修复: clip=%s %.2fs → %.2fs (audio=%.2fs file=%.2fs)",
                clip.get("id"), v_dur, new_dur, a_dur, file_dur,
            )
        if healed:
            self._touch_project_dirty()
            try:
                total = self._timeline_total_duration()
                if tw is not None and hasattr(tw, "set_total_duration") and total > 0:
                    tw.set_total_duration(max(total + 2.0, total * 1.02))
            except Exception:
                logger.debug("总时长显示失败", exc_info=True)
        # 无论是否修好，缓存当前签名，避免每次播放重复探测
        self._heal_av_sig = self._heal_av_clips_signature()
        return healed

    def _add_clip_to_timeline(self, file_path, source_clip_id: str = ""):
        """将视频素材真实加入内核时间线、本地片段列表和 TimelineWidget。

        参数：
            file_path: 视频文件路径
            source_clip_id: 可选，素材来源系统的片段 id（如 AI 生成线 clip_id）。
                pipeline 全链路的 editing_script.clip_order 引用的是生成线 id，
                而内核时间线会另生成 clip_{ts} 新 id；此处保留别名写入片段
                "source_clip_id" 字段，供精剪查表回填（不动内核 id 生成规则）。
        """
        import os as _os
        import time as _time

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
            # 时长 SSOT：ffprobe / PreviewManager / OpenCV 取最大，避免 CAP_PROP 低估成 ~8s
            duration = self._resolve_media_duration(file_path)
            if duration <= 0.05:
                duration = 10.0
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
            # 强制用探测时长，避免内核/旧值把片长压短
            clip = {
                "id": new_clip.get("id", f"clip_{int(_time.time() * 1000)}"),
                "name": new_clip.get("name", clip_info["name"]),
                "path": file_path,
                "start_time": new_clip.get("start_time", clip_info["start_time"]),
                "duration": duration,
                "in_point": 0.0,
                "out_point": duration,
                "track": 0,
                "type": "video",
                "effects": {},
                "transitions": [],
            }
            # 保留生成线 clip_id 别名（demo/pipeline 链路精剪查表用，见方法 docstring）
            if source_clip_id:
                clip["source_clip_id"] = str(source_clip_id)
            self._timeline_store.add(clip)
            audio_clip = None  # 联动音频片段（有 timeline_widget 时才创建）
            if hasattr(self, '_timeline_widget'):
                video_track_i = 0
                audio_track_i = 1
                if hasattr(self._timeline_widget, 'find_track_index_by_type'):
                    video_track_i = self._timeline_widget.find_track_index_by_type('video', default=0)
                    audio_track_i = self._timeline_widget.find_track_index_by_type('audio', default=1)
                clip["track"] = video_track_i
                widget = self._timeline_widget.add_clip(clip, video_track_i)
                if widget is not None:
                    self._clip_widgets.append(widget)
                    self._clip_id_to_widget[clip["id"]] = widget
                
                # ── 为视频内嵌音频创建音频片段（音频轨道，不写死 track==1）──
                audio_clip = {
                    "id": f"audio_{int(_time.time() * 1000)}",
                    "name": _os.path.basename(file_path) + " (音频)",
                    "path": file_path,
                    "start_time": clip["start_time"],
                    "duration": clip["duration"],
                    "in_point": clip["in_point"],
                    "out_point": clip["out_point"],
                    "track": audio_track_i,
                    "type": "audio",
                    "effects": {},
                    "transitions": [],
                }
                audio_widget = self._timeline_widget.add_clip(audio_clip, audio_track_i)
                if audio_widget is not None:
                    self._clip_widgets.append(audio_widget)
                    self._clip_id_to_widget[audio_clip["id"]] = audio_widget
                    self._timeline_store.add(audio_clip)
            
            self._current_clip = clip
            self._video_source = file_path
            self._sync_kernel_timeline()
            # 时间线总时长跟片段对齐（默认 600 会让波形/标尺看起来比视频片长很多）
            try:
                tw = getattr(self, "_timeline_widget", None)
                total = self._timeline_total_duration()
                if tw is not None and hasattr(tw, "set_total_duration") and total > 0:
                    tw.set_total_duration(max(total + 2.0, total * 1.02))
            except Exception as e:
                logger.debug("同步时间线总时长失败: %s", e)
            self._preview_seg_key = None  # 重置预览缓存，导入后恢复整段预览
            # 首帧由 _load_video 统一刷；此处仅在非 load 路径（如拖入）兜底一次
            if not getattr(self, "_suppress_add_clip_preview", False):
                try:
                    if not self._force_show_first_video_frame():
                        self._render_timeline_frame(float(clip.get("start_time", 0) or 0))
                except Exception as e:
                    logger.debug("导入后首帧刷新失败: %s", e)
            logger.info(f'添加片段到时间线: {clip}')
            # 记录撤销操作（AI剪辑/画布入轨/素材拖入的片段也支持 Ctrl+Z）
            try:
                self._record_action({
                    "type": "add_clip",
                    "clip": clip,
                    "audio_clip": audio_clip,
                })
            except Exception:
                logger.debug("add_clip 撤销记录失败", exc_info=True)
        except Exception as e:
            logger.exception("添加片段到时间线失败")
            QMessageBox.warning(self, "添加失败", f"添加片段到时间线失败: {e}")
            logger.error(f'添加片段到时间线失败: {e}')

    def _add_audio_clip_to_timeline(self, file_path: str, title: str = "", duration_hint: float = 0.0):
        """把**纯音频**素材加入时间线音轨（配音轨自动落位，2026-10-15 解冻 playback-av）。

        与 `_add_clip_to_timeline` 的区别：只在 audio 轨创建 clip，**不产生
        「wav 当视频片段」的脏数据**（旧方法对任何素材都先建 video 片段再配联动音轨，
        纯音频会被错误地当成视频）。时长优先用 `duration_hint`（配音音频的真实时长），
        否则 ffprobe 探测；最终统一由 `_sync_kernel_timeline()` 写进内核音轨。

        参数：
            file_path: 音频文件路径（.wav/.mp3/...）
            title: 片段显示名（缺省用文件名）
            duration_hint: 已知时长（配音链传递，避免 ffprobe 低估）
        """
        import os as _os
        import time as _time

        if not file_path or not _os.path.exists(file_path):
            QMessageBox.warning(self, "添加失败", "音频文件不存在")
            return
        try:
            try:
                from app.core.timeline_manager import timeline_manager as real_timeline_manager
            except ImportError:
                from core.timeline_manager import timeline_manager as real_timeline_manager  # type: ignore
            if not self._current_timeline:
                self._current_timeline = real_timeline_manager.create_timeline("默认时间线")
            # 时长真相源：配音链给的 duration_hint 优先（= 音频真实时长），否则探测
            duration = float(duration_hint) if duration_hint and float(duration_hint) > 0 else 0.0
            if duration <= 0.05:
                duration = float(self._resolve_media_duration(file_path) or 0.0)
            if duration <= 0.05:
                duration = 3.0
            audio_clip = {
                "id": f"audio_{int(_time.time() * 1000)}",
                "name": (title or _os.path.basename(file_path)),
                "path": file_path,
                "start_time": self._next_clip_start_time(),
                "duration": duration,
                "in_point": 0.0,
                "out_point": duration,
                "track": 1,
                "type": "audio",
                "effects": {},
                "transitions": [],
            }
            if hasattr(self, "_timeline_widget") and self._timeline_widget is not None:
                tw = self._timeline_widget
                audio_track_i = (
                    tw.find_track_index_by_type("audio", default=1)
                    if hasattr(tw, "find_track_index_by_type")
                    else 1
                )
                audio_clip["track"] = audio_track_i
                widget = tw.add_clip(audio_clip, audio_track_i)
                if widget is not None:
                    self._clip_widgets.append(widget)
                    self._clip_id_to_widget[audio_clip["id"]] = widget
            self._timeline_store.add(audio_clip)
            self._sync_kernel_timeline()
            self._touch_project_dirty()
            try:
                self._notify_edit(f"已加入音轨: {audio_clip['name']}")
            except Exception:
                logger.warning("编辑通知发送失败", exc_info=True)
            logger.info(f"✅ 配音音频已加入音轨: {audio_clip['name']} ({duration:.2f}s)")
            try:
                self._record_action({"type": "add_clip", "clip": None, "audio_clip": audio_clip})
            except Exception:
                logger.debug("音频入轨撤销记录失败", exc_info=True)
        except Exception as e:
            logger.exception("音频入轨失败")
            try:
                QMessageBox.warning(self, "添加失败", f"音频入轨失败: {e}")
            except Exception:
                logger.warning("音频入轨失败提示框弹出异常", exc_info=True)

    def _probe_video_duration(self, file_path: str) -> float:
        """读取视频时长，失败时返回 0 让调用方回退默认值。"""
        try:
            from app.modules.lego.professional_video_engine import FFmpegUtils
            info = FFmpegUtils.get_video_info(file_path)
            return float(info.duration) if info and info.duration else 0.0
        except Exception as e:
            logger.error(f'读取视频时长失败: {e}')
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
        """对指定片段应用滤镜；若当前多选则批写选中片。"""
        targets = self._property_target_clips()
        if clip and clip not in targets and clip.get("id") not in {c.get("id") for c in targets}:
            targets = [clip] + [c for c in targets if c.get("id") != clip.get("id")]
        if not targets and clip:
            targets = [clip]
        intens = max(0.0, min(1.0, float(intensity)))
        steps = []
        for c in targets:
            before = {"effects": dict(c.get("effects") or {}) if isinstance(c.get("effects"), dict) else {}}
            effects = dict(before["effects"])
            effects["filter"] = filter_name
            effects["filter_intensity"] = intens
            c["effects"] = effects
            c["filter"] = filter_name
            c["filter_intensity"] = intens
            steps.append({
                "type": "edit_clip",
                "clip_id": c.get("id"),
                "before": before,
                "after": {"effects": effects, "filter": filter_name, "filter_intensity": intens},
            })
        self._active_filter_key = filter_name
        if len(steps) == 1:
            self._record_action(steps[0])
        elif steps:
            self._record_action({"type": "compound", "steps": steps, "label": "batch_filter"})
        self._sync_timeline_widget_state()
        self._refresh_preview_with_effects()

    def agent_apply_filter(self, clip: Dict[str, Any], filter_name: str, intensity: float):
        """Agent 公开接口：对指定片段应用滤镜元数据。"""
        try:
            self._apply_filter_to_clip(clip, filter_name, intensity)
            # P1-C: emit Agent 反馈标记
            try:
                clip_time = float(clip.get("start_time", 0)) if clip else 0
                self._emit_agent_marker({
                    "clip_id": clip.get("id") if clip else None,
                    "time": clip_time,
                    "action": "apply_filter",
                    "status": "success",
                    "message": f"滤镜 {filter_name} (强度 {intensity:.0%})",
                })
            except Exception:
                logger.warning("滤镜结果通知发送失败", exc_info=True)
            return {"success": True, "filter_name": filter_name, "intensity": intensity}
        except Exception as e:
            logger.exception(f"[Agent] agent_apply_filter 失败: {e}")
            # P1-C: 失败也 emit
            try:
                clip_time = float(clip.get("start_time", 0)) if clip else 0
                self._emit_agent_marker({
                    "clip_id": clip.get("id") if clip else None,
                    "time": clip_time,
                    "action": "apply_filter",
                    "status": "failed",
                    "message": str(e),
                })
            except Exception:
                logger.warning("滤镜失败通知发送失败", exc_info=True)
            return {"success": False, "message": str(e)}

    def _on_filter_category_changed(self, category: str):
        """滤镜「分类」下拉：按分类筛选按钮网格的可见性（原片按钮始终可见）。"""
        buttons = getattr(self, "_filter_buttons", None)
        if not buttons:
            return
        show_all = not category or category == "全部"
        for btn, key in buttons:
            btn.setVisible(show_all or key == "" or key == category)

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
        self._schedule_preview_refresh()

    def _apply_transition(self):
        """将转场应用到当前片段（自研/插件 id，非剪映商店包）。"""
        if not self._current_clip:
            QMessageBox.warning(self, "转场", "请先选择一个片段")
            return
        combo = getattr(self, "_transition_type_var", None)
        transition_type = combo.currentText() if combo else "淡入淡出"
        plugin_id = combo.currentData() if combo else None
        if not plugin_id:
            try:
                from app.core.transition_plugin_registry import resolve_plugin_id
                plugin_id = resolve_plugin_id(transition_type)
            except Exception:
                plugin_id = None
        duration_ms = (
            self._transition_duration_var.value()
            if hasattr(self, "_transition_duration_var") and self._transition_duration_var
            else 500
        )
        curve = (
            self._transition_curve_var.currentText()
            if hasattr(self, "_transition_curve_var") and self._transition_curve_var
            else "线性"
        )
        self._apply_transition_to_clip(
            self._current_clip,
            transition_type,
            duration_ms / 1000.0,
            curve=curve,
            plugin_id=plugin_id,
        )
        self._touch_project_dirty()
        note = ""
        try:
            from app.core.transition_plugin_registry import export_degradation_note
            tr = (self._current_clip or {}).get("transition") or {}
            note = export_degradation_note(tr if isinstance(tr, dict) else None)
        except Exception:
            note = ""
        msg = f"已应用 {transition_type} 转场，时长 {duration_ms}ms"
        if note:
            msg = f"{msg}（{note}）"
        self._notify_edit(msg)

    def _apply_transition_to_clip(
        self,
        clip: Dict[str, Any],
        transition_type: str,
        duration: float,
        curve: str = "线性",
        plugin_id: Optional[str] = None,
    ):
        """对指定片段写入转场元数据（含 plugin_id 供预览双帧混合）。"""
        # ★ A3（2026-10-05）：**入撤销栈** —— 此前转场不可撤销（最大体验洞之一）。
        #   复用既有 `edit_clip` 型 action：撤销走 _apply_action 的通用字段回写路径，
        #   **零新分支**。before 里显式记「原本有没有这两个键」，撤到无转场时写回 None/[]，
        #   `clip.get("transition")` 仍为假值 ⇒ 下游「有无转场」判定不受影响。
        _before = {
            "transition": clip.get("transition"),
            "transitions": list(clip.get("transitions") or []),
        }
        if not plugin_id:
            try:
                from app.core.transition_plugin_registry import resolve_plugin_id
                plugin_id = resolve_plugin_id(transition_type)
            except Exception:
                plugin_id = None
        transition = {
            "type": transition_type,
            "plugin_id": plugin_id or transition_type,
            "duration": max(0.1, float(duration)),
            "position": "end",
            "curve": curve or "线性",
        }
        clip["transition"] = transition
        transitions = clip.get("transitions") or []
        if not isinstance(transitions, list):
            transitions = []
        transitions.append(transition)
        clip["transitions"] = transitions
        self._record_action({
            "type": "edit_clip",
            "clip_id": clip.get("id"),
            "before": _before,
            "after": {"transition": transition, "transitions": list(transitions)},
            "label": f"转场 {transition_type}",
        })
        self._sync_timeline_widget_state()
        self._refresh_preview_with_effects()

    def agent_apply_transition(self, clip: Dict[str, Any], transition_type: str,
                                duration: float, curve: str = "线性"):
        """Agent 公开接口：对指定片段应用转场元数据。"""
        try:
            self._apply_transition_to_clip(clip, transition_type, duration, curve)
            # P1-C: emit Agent 反馈标记
            try:
                clip_time = float(clip.get("start_time", 0)) if clip else 0
                self._emit_agent_marker({
                    "clip_id": clip.get("id") if clip else None,
                    "time": clip_time,
                    "action": "apply_transition",
                    "status": "success",
                    "message": f"转场 {transition_type} ({duration:.1f}s)",
                })
            except Exception:
                logger.warning("转场结果通知发送失败", exc_info=True)
            return {"success": True, "transition_type": transition_type, "duration": duration}
        except Exception as e:
            logger.exception(f"[Agent] agent_apply_transition 失败: {e}")
            # P1-C: 失败也 emit
            try:
                clip_time = float(clip.get("start_time", 0)) if clip else 0
                self._emit_agent_marker({
                    "clip_id": clip.get("id") if clip else None,
                    "time": clip_time,
                    "action": "apply_transition",
                    "status": "failed",
                    "message": str(e),
                })
            except Exception:
                logger.warning("转场失败通知发送失败", exc_info=True)
            return {"success": False, "message": str(e)}

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
        """删除选中片段（支持多选；走 ripple 删除，含联动音频）。"""
        tw = getattr(self, "_timeline_widget", None)
        ids = []
        if tw is not None and hasattr(tw, "get_selected_ids"):
            # 有时间线时只信选区，禁止回退陈旧 _current_clip（幽灵删除）
            ids = [i for i in (tw.get_selected_ids() or []) if i]
            if not ids:
                self._current_clip = None
                QMessageBox.warning(self, "删除", "请先选择一个片段")
                return
        else:
            if self._current_clip and self._current_clip.get("id"):
                ids = [self._current_clip.get("id")]
        ids = [i for i in ids if i]
        if not ids:
            QMessageBox.warning(self, "删除", "请先选择一个片段")
            return
        # 多选：收集删除 payload 后一条 batch_delete（避免多次 undo）
        use_ripple = bool(getattr(self, "_ripple_delete_enabled", True))
        if len(ids) == 1:
            self._delete_clip_by_id(ids[0], ripple=use_ripple)
            if tw is not None and hasattr(tw, "clear_selection"):
                tw.clear_selection(emit=False)
            self._notify_edit("片段已删除" + ("（波纹）" if use_ripple else ""))
            return
        items = []
        # 从右往左删，减轻波纹互相干扰
        ordered = []
        for cid in ids:
            clip = next((c for c in self._clips if c.get("id") == cid), None)
            if clip is None:
                continue
            ordered.append((float(clip.get("start_time", 0) or 0), cid))
        ordered.sort(key=lambda x: -x[0])
        seen = set()
        for _, cid in ordered:
            if cid in seen:
                continue
            deleted_clip = next((c for c in self._clips if c.get("id") == cid), None)
            if deleted_clip is None:
                continue
            linked_ids = []
            if not self._is_linked_video_audio_clip(deleted_clip):
                path = deleted_clip.get("path")
                st0 = float(deleted_clip.get("start_time", 0) or 0)
                for c in self._clips:
                    if c.get("id") == cid:
                        continue
                    if not self._is_linked_video_audio_clip(c):
                        continue
                    if c.get("path") == path and abs(float(c.get("start_time", 0) or 0) - st0) < 0.05:
                        linked_ids.append(c.get("id"))
            for i, del_id in enumerate([cid] + linked_ids):
                if del_id in seen:
                    continue
                # 主片跟开关；联动音跟随主片同模式，避免只剩空隙音频
                payload = self._delete_one_clip_internal(
                    del_id, ripple=use_ripple, record=False, sync=False
                )
                if payload:
                    items.append(payload)
                    seen.add(del_id)
        if not items:
            return
        self._record_action({"type": "batch_delete", "items": items})
        self._sync_kernel_timeline()
        self._sync_timeline_widget_state()
        self._refresh_preview_to_current_clip()
        if tw is not None and hasattr(tw, "clear_selection"):
            tw.clear_selection(emit=False)
        self._notify_edit(f"已删除 {len(items)} 个片段")

    def _toggle_razor_tool(self):
        """工具栏 ✂：切换刀片工具态。"""
        tw = getattr(self, "_timeline_widget", None)
        if tw is None or not hasattr(tw, "toggle_razor_mode"):
            self._cut_clip()
            return
        on = tw.toggle_razor_mode()
        self._notify_edit("刀片工具已开启：悬停见切开线，点击切开" if on else "已退出刀片工具")

    def _on_timeline_escape(self):
        """Esc：取消拖片 → 退出刀片。"""
        try:
            from PyQt6.QtWidgets import QApplication
            if QApplication.activeModalWidget() is not None:
                return
        except Exception:
            logger.debug("模态窗口判断失败", exc_info=True)
        tw = getattr(self, "_timeline_widget", None)
        if tw is not None and hasattr(tw, "cancel_active_clip_interaction"):
            if tw.cancel_active_clip_interaction():
                self._notify_edit("已取消本次拖拽")
                return
        self._exit_razor_tool()

    def _exit_razor_tool(self):
        try:
            from PyQt6.QtWidgets import QApplication
            if QApplication.activeModalWidget() is not None:
                return
        except Exception:
            logger.debug("模态窗口判断失败", exc_info=True)
        tw = getattr(self, "_timeline_widget", None)
        if tw is not None and hasattr(tw, "is_razor_mode") and tw.is_razor_mode():
            tw.set_razor_mode(False)

    def _on_razor_mode_changed(self, enabled: bool):
        btn = getattr(self, "_razor_btn", None)
        if btn is not None:
            try:
                btn.blockSignals(True)
                btn.setChecked(bool(enabled))
                btn.blockSignals(False)
            except Exception:
                logger.debug("按钮状态设置失败", exc_info=True)

    def _on_razor_cut_at(self, cut_t: float):
        """时间线刀片点击：切开指针下所有覆盖片（含联动音画）。"""
        result = self._cut_at_timeline_time(float(cut_t), seed_clips=None)
        if result.get("success"):
            self._notify_edit(result.get("message", "已切开"))
        else:
            self._notify_edit(result.get("message", "无法切开"))

    def _razor_cut_shortcut(self):
        """C 键：切换刀片工具（输入框内不触发）。"""
        try:
            from PyQt6.QtWidgets import (
                QApplication, QLineEdit, QTextEdit, QPlainTextEdit,
                QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox,
            )
            w = QApplication.focusWidget()
            if isinstance(
                w,
                (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox),
            ):
                return
            if w is not None and getattr(w, "isReadOnly", lambda: True)() is False:
                if w.inherits("QLineEdit"):
                    return
        except Exception:
            logger.debug("控件类型判断失败", exc_info=True)
        self._toggle_razor_tool()

    def _cut_clip(self):
        """Ctrl+K / 菜单：在播放头切开选中（否则切开命中片），强制联动音画。"""
        playhead = float(getattr(self, "_playhead_position", 0) or 0)
        tw = getattr(self, "_timeline_widget", None)
        targets = []
        if tw is not None and hasattr(tw, "get_selected_clips"):
            try:
                targets = [c for c in (tw.get_selected_clips() or []) if isinstance(c, dict)]
            except Exception:
                targets = []
        if not targets and isinstance(getattr(self, "_current_clip", None), dict):
            targets = [self._current_clip]
        result = self._cut_at_timeline_time(
            playhead, seed_clips=targets if targets else None
        )
        if result.get("success"):
            self._notify_edit(result.get("message", "已切分"))
        else:
            QMessageBox.warning(
                self, "剪切",
                result.get("message")
                or "请把播放头移到片段中间，或先选中要切开的片段",
            )
    def _open_ai_prompt_dialog(self):
        """兼容旧入口：打开轨道标题栏内嵌剪辑 Agent。"""
        self._toggle_edit_agent_panel(True)
