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
from .account_skills import (
    AccountDataCollectSkill, AccountAnalysisSkill,
    PublishContentSkill, MatrixPublishSkill, register_account_skills
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


def _blend_pixels_bgr(base01, over01, mode: str):
    """按混合模式计算 base/overlay 混合结果（BGR，float，0~1）。非独立分离模式（色相/饱和度/颜色/明度）用 W3C 公式。"""
    import numpy as np

    if mode in (None, "", "normal", "正常"):
        return over01

    if mode in ("darken", "变暗"):
        return np.minimum(base01, over01)
    if mode in ("multiply", "正片叠底"):
        return base01 * over01
    if mode in ("color_burn", "颜色加深"):
        return np.where(over01 <= 1e-6, 0.0, 1.0 - np.minimum(1.0, (1.0 - base01) / np.maximum(over01, 1e-6)))
    if mode in ("lighten", "变亮"):
        return np.maximum(base01, over01)
    if mode in ("screen", "滤色"):
        return base01 + over01 - base01 * over01
    if mode in ("hard_light", "强光"):
        lo = 2.0 * base01 * over01
        hi = 1.0 - 2.0 * (1.0 - base01) * (1.0 - over01)
        return np.where(over01 <= 0.5, lo, hi)
    if mode in ("overlay", "叠加"):
        lo = 2.0 * base01 * over01
        hi = 1.0 - 2.0 * (1.0 - base01) * (1.0 - over01)
        return np.where(base01 <= 0.5, lo, hi)
    if mode in ("soft_light", "柔光"):
        d = np.where(base01 <= 0.25, ((16 * base01 - 12) * base01 + 4) * base01, np.sqrt(np.maximum(base01, 0.0)))
        lo = base01 - (1.0 - 2.0 * over01) * base01 * (1.0 - base01)
        hi = base01 + (2.0 * over01 - 1.0) * (d - base01)
        return np.where(over01 <= 0.5, lo, hi)
    if mode in ("difference", "差值"):
        return np.abs(base01 - over01)
    if mode in ("exclusion", "排除"):
        return base01 + over01 - 2.0 * base01 * over01
    if mode in ("hue", "saturation", "color", "luminosity", "色相", "饱和度", "颜色", "明度"):
        def lum(c):
            return c[..., 2] * 0.3 + c[..., 1] * 0.59 + c[..., 0] * 0.11

        def clip_lum(c):
            return np.clip(c, 0.0, 1.0)

        def set_lum(c, l):
            d = l - lum(c)
            return clip_lum(c + d[..., None])

        def sat(c):
            return c.max(axis=-1) - c.min(axis=-1)

        def set_sat(c, s):
            order = np.argsort(c, axis=-1)  # 从小到大：min, mid, max 的下标
            cmin = np.take_along_axis(c, order[..., 0:1], axis=-1)
            cmid = np.take_along_axis(c, order[..., 1:2], axis=-1)
            cmax = np.take_along_axis(c, order[..., 2:3], axis=-1)
            rng = np.maximum(cmax - cmin, 1e-6)
            new_mid = np.where(cmax > cmin, (cmid - cmin) * s[..., None] / rng, 0.0)
            new_max = np.where(cmax > cmin, s[..., None], 0.0)
            new_min = np.zeros_like(cmin)
            out = np.zeros_like(c)
            np.put_along_axis(out, order[..., 0:1], new_min, axis=-1)
            np.put_along_axis(out, order[..., 1:2], new_mid, axis=-1)
            np.put_along_axis(out, order[..., 2:3], new_max, axis=-1)
            return out

        if mode in ("hue", "色相"):
            return set_lum(set_sat(over01, sat(base01)), lum(base01))
        if mode in ("saturation", "饱和度"):
            return set_lum(set_sat(base01, sat(over01)), lum(base01))
        if mode in ("color", "颜色"):
            return set_lum(over01, lum(base01))
        return set_lum(base01, lum(over01))  # luminosity/明度

    return over01


def apply_clip_crop_bgr(arr, clip: dict):
    """按 clip["crop"]（上/下/左/右，源帧像素）裁掉四边，返回裁剪后的数组（无裁剪时原样返回）。"""
    if arr is None or not isinstance(clip, dict):
        return arr
    crop = clip.get("crop")
    if not isinstance(crop, dict):
        return arr
    try:
        top = max(0, int(crop.get("top", 0) or 0))
        bottom = max(0, int(crop.get("bottom", 0) or 0))
        left = max(0, int(crop.get("left", 0) or 0))
        right = max(0, int(crop.get("right", 0) or 0))
    except (TypeError, ValueError):
        return arr
    if top == 0 and bottom == 0 and left == 0 and right == 0:
        return arr
    h, w = arr.shape[:2]
    y0, y1 = min(top, h - 1), max(top + 1, h - bottom)
    x0, x1 = min(left, w - 1), max(left + 1, w - right)
    if y1 <= y0 or x1 <= x0:
        return arr
    return arr[y0:y1, x0:x1]


def composite_overlay_bgr_blend(base_bgr, overlay_bgr, tf: dict, opacity: float = 1.0, blend_mode: str = "normal"):
    """在 composite_overlay_bgr 的定位/缩放/旋转几何基础上，额外支持像素混合模式。

    与冻结区 clip_transform.composite_overlay_bgr 的放置几何保持一致（新写函数，
    不改动冻结文件），仅当 blend_mode 非「正常」时按混合公式计算叠层结果。
    """
    import numpy as np
    import cv2

    base = base_bgr.astype(np.float32)
    overlay = overlay_bgr.astype(np.float32)
    bh, bw = base.shape[:2]
    if overlay.shape[:2] != (bh, bw):
        overlay = cv2.resize(overlay, (bw, bh)).astype(np.float32)

    scale = float(tf.get("scale", 1.0) or 1.0)
    ow = max(1, int(bw * scale))
    oh = max(1, int(bh * scale))
    scaled = cv2.resize(overlay, (ow, oh))
    rot = float(tf.get("rotation", 0) or 0)
    ax = float(tf.get("anchor_x", 0.5))
    ay = float(tf.get("anchor_y", 0.5))

    if abs(rot) > 0.05:
        cx, cy = ow * ax, oh * ay
        M = cv2.getRotationMatrix2D((cx, cy), rot, 1.0)
        cos = abs(M[0, 0])
        sin = abs(M[0, 1])
        nw = int(oh * sin + ow * cos)
        nh = int(oh * cos + ow * sin)
        M[0, 2] += (nw / 2) - cx
        M[1, 2] += (nh / 2) - cy
        scaled = cv2.warpAffine(
            scaled, M, (nw, nh),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
        ow, oh = nw, nh

    x0 = int((bw - ow) * float(tf.get("x", 0.5)))
    y0 = int((bh - oh) * float(tf.get("y", 0.5)))
    x0 = max(-ow + 1, min(bw - 1, x0))
    y0 = max(-oh + 1, min(bh - 1, y0))

    sx0 = max(0, -x0)
    sy0 = max(0, -y0)
    dx0 = max(0, x0)
    dy0 = max(0, y0)
    dx1 = min(bw, x0 + ow)
    dy1 = min(bh, y0 + oh)

    result = base.copy()
    if dx1 > dx0 and dy1 > dy0:
        sw = dx1 - dx0
        sh = dy1 - dy0
        over_region01 = np.clip(scaled[sy0:sy0 + sh, sx0:sx0 + sw] / 255.0, 0.0, 1.0)
        base_region01 = np.clip(result[dy0:dy1, dx0:dx1] / 255.0, 0.0, 1.0)
        blended01 = _blend_pixels_bgr(base_region01, over_region01, blend_mode)
        blended = np.clip(blended01, 0.0, 1.0) * 255.0
        op = max(0.0, min(1.0, float(opacity)))
        result[dy0:dy1, dx0:dx1] = base_region01 * 255.0 * (1.0 - op) + blended * op
    return result


class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin):
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
            self.connect_to_workflow()
        except Exception as e:
            logger.warning("连接工作流管理器失败: %s", e)
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
        print("✅ 预览管理器已加载")
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
                pass
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
            print("✅ GPU 滤镜预览已启用")
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
        try:
            from app.core.effect_manager import get_effect_manager as _gem
        except ImportError:
            from core.effect_manager import get_effect_manager as _gem
        self._effect_manager = _gem()
        print("✅ 特效管理系统已加载")
        return self._effect_manager
    
    def _ensure_transition_manager(self):
        """懒加载转场管理器"""
        if self._transition_manager is not None:
            return self._transition_manager
        try:
            from app.core.transition_manager import get_transition_manager as _gtm
        except ImportError:
            from core.transition_manager import get_transition_manager as _gtm
        self._transition_manager = _gtm()
        print("✅ 转场管理系统已加载")
        return self._transition_manager
    
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
        
        left_panel = self._create_left_panel()
        top_splitter.addWidget(left_panel)
        t_left = time.perf_counter()
        
        preview_panel = self._create_preview_panel()
        top_splitter.addWidget(preview_panel)
        t_preview = time.perf_counter()
        
        tools_panel = self._create_tools_panel()
        top_splitter.addWidget(tools_panel)
        t_tools = time.perf_counter()
        
        top_splitter.setSizes([280, 750, 380])
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
        
        layout.addWidget(main_splitter, 1)
        logger.info(
            "editor _setup_ui total=%.0fms (toolbar=%.0f left=%.0f preview=%.0f tools=%.0f timeline=%.0f)",
            (t_timeline - t0) * 1000,
            (t_toolbar - t0) * 1000,
            (t_left - t_toolbar) * 1000,
            (t_preview - t_left) * 1000,
            (t_tools - t_preview) * 1000,
            (t_timeline - t_tools) * 1000,
        )
    
    def _create_toolbar(self) -> QWidget:
        toolbar = QFrame()
        toolbar.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
        toolbar.setFixedHeight(50)
        
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(15, 5, 15, 5)
        layout.setSpacing(10)
        
        # 工具栏与快捷键共用 editor_ux_commands 调度
        from app.modules.lego.editor_ux_commands import bind_action
        actions = [
            ("📁 导入", bind_action(self, "import")),
            ("📂 打开", bind_action(self, "open_project")),
            ("💾 保存", bind_action(self, "save_project")),
            ("✂️ 剪切", bind_action(self, "cut")),
            ("📋 复制", bind_action(self, "copy")),
            ("📄 粘贴", bind_action(self, "paste")),
            ("🗑️ 删除", bind_action(self, "delete")),
            ("🔄 撤销", bind_action(self, "undo"), "undo"),
            ("🔄 重做", bind_action(self, "redo"), "redo"),
            ("🧲 收拢", bind_action(self, "close_gap"), "close_gap"),
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
            elif tag == "close_gap":
                btn.setToolTip("空隙收拢 / 波纹消隙 (Shift+Delete)")
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

        # 分级预览：1/4 · 1/2 · 100%（拖 scrub / 播放强制 1/4，静止回用户档）
        from app.modules.lego.editor_preview_ux import quality_combo_items
        q_lbl = QLabel("预览")
        q_lbl.setStyleSheet("color:#666;font-size:10px;padding-left:8px;")
        title_layout.addWidget(q_lbl)
        self._preview_quality_combo = QComboBox()
        self._preview_quality_combo.setFixedWidth(96)
        self._preview_quality_combo.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#ddd;border:1px solid #333;border-radius:4px;"
            "padding:1px 4px;font-size:10px;}QComboBox:hover{border-color:#1e6bde;}"
        )
        for text, pm_q in quality_combo_items():
            self._preview_quality_combo.addItem(text, pm_q)
        # 默认选中用户档
        want = getattr(self, "_user_preview_quality", "medium")
        for i in range(self._preview_quality_combo.count()):
            if self._preview_quality_combo.itemData(i) == want:
                self._preview_quality_combo.setCurrentIndex(i)
                break
        self._preview_quality_combo.setToolTip(
            "预览分辨率：粗剪 1/4 · 常规 1/2 · 精剪 100%；拖动/播放自动降至 1/4"
        )
        self._preview_quality_combo.currentIndexChanged.connect(self._on_preview_quality_combo)
        title_layout.addWidget(self._preview_quality_combo)

        self._proxy_toggle_btn = QPushButton("代理")
        self._proxy_toggle_btn.setCheckable(True)
        self._proxy_toggle_btn.setChecked(bool(getattr(self, "_proxy_preview_enabled", True)))
        self._proxy_toggle_btn.setFixedHeight(22)
        self._proxy_toggle_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#888;border:1px solid #333;border-radius:4px;"
            "padding:2px 8px;font-size:10px;}"
            "QPushButton:checked{background:#1e6bde;color:#fff;border-color:#1e6bde;}"
        )
        self._proxy_toggle_btn.setToolTip("预览走代理媒体（导出仍用原片）；高码率/4K 建议开启")
        self._proxy_toggle_btn.toggled.connect(self.set_proxy_preview_enabled)
        title_layout.addWidget(self._proxy_toggle_btn)

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
        self._preview_label = QLabel("")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setScaledContents(False)
        self._preview_label.setStyleSheet("color: #666666; font-size: 16px; background-color: #000000;")
        self._preview_label.setMouseTracking(True)
        self._preview_label.installEventFilter(self)
        self._preview_frame.installEventFilter(self)
        self._preview_drag_active = False
        self._preview_drag_origin = None
        self._preview_drag_tf0 = None
        self._preview_drag_mode = "move"
        self._preview_drag_angle0 = 0.0
        pv_layout.addWidget(self._preview_label)
        pv_layout.setCurrentWidget(self._preview_label)
        body_lo.addWidget(self._preview_frame, 1)
        
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 4, 0, 0)
        controls_layout.setSpacing(6)
        
        self._progress_bar = QSlider(Qt.Orientation.Horizontal)
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setToolTip("拖动跳转时间线播放头")
        self._progress_bar.setStyleSheet("""
            QSlider::groove:horizontal {
                background-color: #1e1e1e; height: 4px; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background-color: #1e6bde; width: 12px; height: 12px;
                margin: -4px 0; border-radius: 6px;
            }
        """)
        self._progress_bar.sliderMoved.connect(self._on_progress_slider_moved)
        self._progress_bar.sliderReleased.connect(self._on_progress_slider_released)
        controls_layout.addWidget(self._progress_bar, 1)
        
        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setStyleSheet("color: #666666; font-size: 11px;")
        controls_layout.addWidget(self._time_label)

        # M2：预览区画幅提示（竖屏漫剧默认 9:16）
        self._preview_aspect_badge = QLabel(self._sequence_format.badge_text())
        self._preview_aspect_badge.setStyleSheet(
            "QLabel{background:#1a3a2a;color:#7ee787;border:1px solid #2f5139;"
            "border-radius:4px;padding:2px 8px;font-size:10px;font-weight:600;}"
        )
        self._preview_aspect_badge.setToolTip(
            "工程画幅 SSOT；点击切换 黑边/裁切；预览 letterbox；导出同步"
        )
        self._preview_aspect_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_aspect_badge.mousePressEvent = (  # type: ignore[method-assign]
            lambda _e: self._toggle_sequence_fit_mode()
        )
        controls_layout.addWidget(self._preview_aspect_badge)
        
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

        # 首屏只建「属性」；其余 Tab 点开再构造（显著缩短首次打开）
        self._tools_lazy_built: set = set()
        self._tools_lazy_factories: Dict[int, Any] = {}

        def _placeholder() -> QWidget:
            w = QWidget()
            lo = QVBoxLayout(w)
            lo.setContentsMargins(0, 0, 0, 0)
            lo.setSpacing(0)
            tip = QLabel("加载中…")
            tip.setStyleSheet("color:#666;font-size:11px;padding:16px;")
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lo.addWidget(tip)
            w._lazy_tip = tip  # type: ignore[attr-defined]
            return w

        def _add_lazy(title: str, factory) -> int:
            holder = _placeholder()
            idx = tabs.addTab(holder, title)
            self._tools_lazy_factories[idx] = factory
            return idx

        # 属性：选中片段立刻要用，同步构建
        tabs.addTab(self._make_pro_tab(), "属性")
        _add_lazy("调色", self._make_color_tab)
        _add_lazy("特效", self._make_effect_tab)
        _add_lazy("文字", self._make_text_tab)
        _add_lazy("贴纸", self._make_sticker_tab)
        _add_lazy("音频", self._make_audio_tab)
        _add_lazy("角色", self._create_character_tab)
        _add_lazy("AI", self._create_ai_tools_tab)
        self._agent_tab_index = _add_lazy("🤖 Agent", self._create_edit_agent_panel)
        _add_lazy("导出", self._create_params_tab)

        tabs.currentChanged.connect(self._on_tools_tab_changed)
        self._tools_tabs = tabs
        layout.addWidget(tabs, 1)
        return card

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
        self._filter_category_combo = QComboBox()
        self._filter_category_combo.addItems(
            ["全部", "电影感", "复古", "清新", "黑白", "暖色调", "冷色调", "梦幻", "锐利", "柔和", "都市", "黄昏"]
        )
        self._filter_category_combo.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;"
            "padding:3px 6px;font-size:10px;}QComboBox:hover{border-color:#333;}"
            "QComboBox::drop-down{border:none;width:14px;}"
            "QComboBox QAbstractItemView{background:#121212;color:#fff;border:1px solid #333;selection-background-color:#1e6bde;}"
        )
        self._add_cmb_row(fl.layout(), "分类", self._filter_category_combo)
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
        self._filter_buttons = []
        for i,(nm,hc) in enumerate(fts):
            b = QPushButton(nm)
            b.setStyleSheet(f"QPushButton{{background:#0a0a0a;color:#ccc;border:1px solid #222;border-left:3px solid {hc};border-radius:3px;padding:5px 6px;font-size:10px;text-align:left;}}QPushButton:hover{{background:#1a1a1a;color:#fff;}}")
            key = FILTER_KEYS.get(nm, "")
            if key == "":
                b.clicked.connect(lambda _, b=b: self._clear_filter())
            else:
                b.clicked.connect(lambda _, k=key: self._select_filter(k))
            g.addWidget(b,i//3,i%3)
            self._filter_buttons.append((b, key))
        self._filter_category_combo.currentTextChanged.connect(self._on_filter_category_changed)
        fl.layout().addLayout(g)
        self._filter_intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self._filter_intensity_slider.setRange(0, 100)
        self._filter_intensity_slider.setValue(50)
        self._filter_intensity_slider.setStyleSheet(
            "QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}"
            "QSlider::handle:horizontal{background:#1e6bde;width:10px;height:10px;"
            "border-radius:5px;margin:-3px 0;}"
        )
        self._filter_intensity_slider.valueChanged.connect(self._on_filter_intensity_live)
        self._add_setting_row(fl.layout(), "强度", self._filter_intensity_slider, "%")
        l.addWidget(fl)

        tr = self._sect("转场")
        self._transition_type_var = QComboBox()
        self._transition_type_var.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;"
            "padding:3px 6px;font-size:10px;}"
        )
        self._rebuild_transition_combo()
        self._add_cmb_row(tr.layout(), "类型", self._transition_type_var)
        self._transition_duration_var = QSpinBox()
        self._transition_duration_var.setRange(100, 3000)
        self._transition_duration_var.setValue(500)
        self._transition_duration_var.setStyleSheet(
            "QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;"
            "padding:3px 5px;font-size:10px;}"
        )
        self._add_setting_row(tr.layout(), "时长", self._transition_duration_var, "ms")
        self._transition_curve_var = QComboBox()
        self._transition_curve_var.addItems(
            ["线性", "缓入", "缓出", "缓入缓出", "弹性", "回弹"]
        )
        self._transition_curve_var.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;"
            "padding:3px 6px;font-size:10px;}"
        )
        self._add_cmb_row(tr.layout(), "曲线", self._transition_curve_var)
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
            sl.valueChanged.connect(self._on_sticker_param_live)
        self._add_setting_row(cst.layout(), "大小", self._sticker_size, "%")
        self._add_setting_row(cst.layout(), "旋转", self._sticker_rot, "°")
        self._add_setting_row(cst.layout(), "位置X", self._sticker_posx, "%")
        self._add_setting_row(cst.layout(), "位置Y", self._sticker_posy, "%")
        self._add_setting_row(cst.layout(), "透明度", self._sticker_opacity, "%")
        self._sticker_start = QDoubleSpinBox()
        self._sticker_start.setRange(0, 99999)
        self._sticker_start.setDecimals(1)
        self._sticker_start.setSingleStep(0.5)
        self._sticker_start.setValue(0.0)
        self._sticker_end = QDoubleSpinBox()
        self._sticker_end.setRange(0, 99999)
        self._sticker_end.setDecimals(1)
        self._sticker_end.setSingleStep(0.5)
        self._sticker_end.setValue(99999.0)
        for spn in (self._sticker_start, self._sticker_end):
            spn.setSuffix("s")
            spn.setStyleSheet("QDoubleSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}")
            spn.setToolTip("贴纸仅在此时间区间内显示/导出；出点留最大值表示到片尾")
            spn.valueChanged.connect(self._on_sticker_param_live)
        self._add_setting_row(cst.layout(), "入点", self._sticker_start)
        self._add_setting_row(cst.layout(), "出点", self._sticker_end)
        add_custom = QPushButton("📁 导入贴纸")
        add_custom.setStyleSheet("QPushButton{background:#22c55e;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#16a34a;}")
        add_custom.clicked.connect(self._import_sticker)
        cst.layout().addWidget(add_custom)
        l.addWidget(cst)

        bns = QHBoxLayout()
        apply_s = QPushButton("✅ 更新到画布")
        apply_s.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        apply_s.setToolTip("把当前大小/位置/旋转写到选中贴纸，并刷新预览")
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
        self._sticker_list.currentRowChanged.connect(self._on_sticker_list_selected)
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
        zoom_out_btn.clicked.connect(lambda _: self._set_timeline_zoom(max(10, self._timeline_widget._zoom - 25)))
        zoom_out_btn.setToolTip("缩小")
        title_layout.addWidget(zoom_out_btn)
        
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(10, 3000)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(120)
        self._zoom_slider.setToolTip("时间线缩放 10%~3000%；Ctrl+滚轮也可缩放")
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
        zoom_in_btn.clicked.connect(lambda _: self._set_timeline_zoom(min(3000, self._timeline_widget._zoom + 25)))
        zoom_in_btn.setToolTip("放大")
        title_layout.addWidget(zoom_in_btn)
        
        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("color:#1e6bde;font-size:10px;font-weight:600;min-width:36px;")
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(self._zoom_label)

        zoom_fit_btn = QPushButton("⧉")
        zoom_fit_btn.setFixedWidth(24)
        zoom_fit_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:3px;"
            "padding:2px 4px;font-size:11px;}QPushButton:hover{background:#3a3a3a;color:#fff;}"
        )
        zoom_fit_btn.setToolTip("适应窗口（Ctrl+0）")
        zoom_fit_btn.clicked.connect(self._zoom_timeline_to_fit)
        title_layout.addWidget(zoom_fit_btn)

        self._razor_btn = QPushButton("✂")
        self._razor_btn.setFixedWidth(24)
        self._razor_btn.setCheckable(True)
        self._razor_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:3px;"
            "padding:2px 4px;font-size:11px;}QPushButton:hover{background:#3a3a3a;color:#fff;}"
            "QPushButton:checked{background:#c0392b;color:#fff;border:1px solid #e74c3c;}"
        )
        self._razor_btn.setToolTip("刀片工具（C 切换）：悬停切开线，点击切开；Ctrl+K 在播放头切开")
        self._razor_btn.clicked.connect(self._toggle_razor_tool)
        title_layout.addWidget(self._razor_btn)
        
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
        snap_btn.setChecked(True)  # 默认开启，与 TimelineWidget._snap_enabled 一致
        snap_btn.setToolTip("吸附到播放头与相邻片缘（按像素阈值，放大后更精细；按住 Alt 临时关闭）")
        snap_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#888;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:10px;}QPushButton:checked{background:#1e6bde;color:#fff;border-color:#1e6bde;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        snap_btn.toggled.connect(self._on_snap_toggled)
        title_layout.addWidget(snap_btn)
        self._snap_btn = snap_btn

        ripple_btn = QPushButton("🌊 波纹删")
        ripple_btn.setCheckable(True)
        ripple_btn.setChecked(bool(getattr(self, "_ripple_delete_enabled", True)))
        ripple_btn.setToolTip("开启：删除后后方片段前移闭合空隙；关闭：普通删除留白")
        ripple_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#888;border:1px solid #333;border-radius:4px;"
            "padding:3px 8px;font-size:10px;}"
            "QPushButton:checked{background:#0d9488;color:#fff;border-color:#0d9488;}"
            "QPushButton:hover{background:#3a3a3a;color:#fff;}"
        )
        ripple_btn.toggled.connect(self._on_ripple_delete_toggled)
        title_layout.addWidget(ripple_btn)
        self._ripple_btn = ripple_btn

        kf_btn = QPushButton("◆ 关键帧")
        kf_btn.setToolTip("在播放头为当前片段添加关键帧（不透明度/音量/缩放）")
        kf_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ddd;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:10px;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        kf_btn.clicked.connect(self._on_add_keyframe_clicked)
        title_layout.addWidget(kf_btn)
        del_kf_btn = QPushButton("⌫ 删关键帧")
        del_kf_btn.setToolTip("删除当前播放头附近的关键帧")
        del_kf_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ddd;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:10px;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        del_kf_btn.clicked.connect(self._on_delete_keyframe_near_playhead)
        title_layout.addWidget(del_kf_btn)
        
        layout.addWidget(title_bar)
        
        body = QWidget()
        body_lo = QVBoxLayout(body)
        body_lo.setContentsMargins(8, 8, 8, 8)
        
        self._timeline_widget = TimelineWidget()
        self._timeline_widget._snap_enabled = True
        self._snap_enabled = True
        self._timeline_widget.clip_selected.connect(self._on_clip_selected)
        # 补短 P1#8：监听关键帧点击 - 落到具体 keyframe 数据上
        self._timeline_widget.clip_keyframe_clicked.connect(self._on_keyframe_clicked)
        # 连接拖放导入信号
        self._timeline_widget.files_dropped.connect(self._on_files_dropped)
        self._timeline_widget.clip_context_action.connect(self._on_timeline_clip_context)
        self._timeline_widget.playhead_moved.connect(self._on_timeline_playhead_moved)
        self._timeline_widget.clip_trim_committed.connect(self._on_clip_trim_committed)
        self._timeline_widget.razor_cut_at.connect(self._on_razor_cut_at)
        self._timeline_widget.razor_mode_changed.connect(self._on_razor_mode_changed)
        self._timeline_widget._track_volume_changed_cb = self._on_timeline_track_volume
        # Esc：优先取消拖拽/trim，其次退出刀片（时间线焦点；不抢模态对话框）
        try:
            self._razor_esc_shortcut = QShortcut(
                QKeySequence(Qt.Key.Key_Escape), self._timeline_widget
            )
            self._razor_esc_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self._razor_esc_shortcut.setEnabled(True)
            self._razor_esc_shortcut.activated.connect(self._on_timeline_escape)
        except Exception as e:
            logger.debug("注册 Esc 时间线快捷键失败: %s", e)
        body_lo.addWidget(self._timeline_widget, 3)

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
                _report_video_import_debug(
                    "A",
                    "editor_module._import_video:exception",
                    "import video exception",
                    {"error": repr(e), "error_type": type(e).__name__},
                )
                QMessageBox.warning(self, "导入失败", f"导入视频失败: {str(e)}")
                print(f"导入视频失败: {e}")

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
            print(f"字幕/贴纸叠加失败: {e}")
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
            pass

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
                pass
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
            for c in getattr(self, "_clips", []) or []:
                if c.get("id") == clip.get("id"):
                    c["opacity"] = op
                    c["effects"] = effects
                    break
        self._schedule_preview_refresh()

    def _on_clip_blend_mode_changed(self, mode_text: str):
        """属性页「混合」下拉：写入 clip["blend_mode"]（预览像素混合 + 导出 FFmpeg blend 滤镜）。"""
        targets = self._property_target_clips()
        if not targets:
            return
        mode = str(mode_text or "正常")
        for clip in targets:
            clip["blend_mode"] = mode
            for c in getattr(self, "_clips", []) or []:
                if c.get("id") == clip.get("id"):
                    c["blend_mode"] = mode
                    break
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
            for c in getattr(self, "_clips", []) or []:
                if c.get("id") == clip.get("id"):
                    c["crop"] = dict(crop)
                    break
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
            pass
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
            print(f"刷新导出信息失败: {e}")


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
            pass
        
        # 使用QMediaPlayer加载视频（主要用于音频）
        media_content = QUrl.fromLocalFile(file_path)
        self._media_player.setSource(media_content)
        
        # 信号只连接一次，避免重复导入后回调叠加
        self._ensure_media_signals()
        self._ensure_media_audio_output()
        
        # 先加片（时长探测可轻量 open）；再统一 open+首帧，避免 import 路径多次关开 capture
        print(f"加载视频: {file_path}")
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
                    print(f"PreviewManager成功加载视频: {file_path}")
                else:
                    self._force_show_first_video_frame()
            else:
                self._force_show_first_video_frame()
        except Exception as e:
            print(f"PreviewManager加载视频失败: {e}")
            try:
                self._force_show_first_video_frame()
            except Exception:
                pass
    
    
    
    def _on_clip_selected(self, clip_data):
        """选区变化；None = 清空（时间线空白/取消多选）。"""
        self._current_clip = clip_data
        if not clip_data:
            return
        print(f"选择片段: {clip_data.get('id')}")
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
            for c in getattr(self, "_clips", []) or []:
                if c.get("id") == cid:
                    c["volume"] = vol
                    break
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
            for c in getattr(self, "_clips", []) or []:
                if c.get("id") == cid:
                    c["volume"] = vol
                    break
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
                    self._media_player.setPosition(
                        int(getattr(self, "_audio_pending_seek_ms", 0) or 0)
                    )
                    self._media_player.play()
                except Exception as e:
                    logger.warning("pending 音频播放失败: %s", e)
                self._audio_pending_play = False

    def _on_media_error(self, error, error_string):
        """QMediaPlayer错误回调"""
        print(f"媒体播放错误: {error_string}")
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
        try:
            self._media_player.setPlaybackRate(rate)
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
            print(f"[P1#8] add_keyframes_to_clip 失败: 找不到 clip_id={clip_id}")
            return False
        before = list((clip or {}).get("keyframes") or [])
        merged = [dict(k) for k in (keyframes or []) if isinstance(k, dict)]
        widget = self._clip_id_to_widget.get(clip_id)
        if widget is not None:
            widget.set_keyframes(merged)
            merged = widget.get_keyframes()
        if clip is not None:
            clip["keyframes"] = merged
        elif widget is not None and hasattr(widget, "clip_data"):
            widget.clip_data["keyframes"] = merged
            # 尝试写回 _clips
            for c in self._clips:
                if c.get("id") == clip_id:
                    c["keyframes"] = merged
                    break
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
            print(f"关键帧点击处理异常: {e}")

    def set_clip_speed(self, clip_id, speed: float):
        """设置片段播放速度（预览时钟与导出 setpts）。"""
        speed = max(0.05, min(8.0, float(speed)))
        for clip in self._clips:
            if clip.get("id") != clip_id:
                continue
            before = {"speed": float(clip.get("speed", 1.0) or 1.0)}
            clip["speed"] = speed
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
            clip["start_time"] = max(0.0, float(new_start_time))
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
            clip["duration"] = dur
            clip["out_point"] = in_p + dur
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

        elif atype == "batch_delete":
            items = action.get("items") or []
            if mode == "do":
                for item in items:
                    clip = item["clip"]
                    shifts = item.get("ripple_shifts") or []
                    self._clips = [c for c in self._clips if c.get("id") != clip.get("id")]
                    self._timeline_remove_clip_widget(clip.get("id"))
                    if self._current_clip and self._current_clip.get("id") == clip.get("id"):
                        self._current_clip = None
                    for sh in shifts:
                        for c in self._clips:
                            if c.get("id") == sh.get("id"):
                                c["start_time"] = float(sh.get("new", c.get("start_time", 0)))
            else:
                for item in reversed(items):
                    clip = item["clip"]
                    shifts = item.get("ripple_shifts") or []
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
        target_clip['transitions'] = transitions
        target_clip['transition'] = transitions[-1]
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
            pass
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
                        pass
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
                pass
            try:
                bgm = getattr(self, "_bgm_player", None)
                if bgm is not None:
                    bgm.pause()
            except Exception:
                pass
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
        """接收闭环跳转的工作流提示（如账号运营爆款建议 → 下一轮粗剪）。"""
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
        - 批量: {"clips": [{"path"/"file_path": "...", ...}, ...], "source": "..."}（PreviewValidationLoop）
        """
        data = event.data if hasattr(event, 'data') else event
        src = data.get("source", "") if isinstance(data, dict) else ""

        clips = data.get("clips") if isinstance(data, dict) else None
        if isinstance(clips, list) and clips:
            added, failed = [], []
            for c in clips:
                p = (c.get("path") or c.get("file_path") or "") if isinstance(c, dict) else str(c)
                if p and os.path.exists(p):
                    self._add_clip_to_timeline(p)
                    added.append(os.path.basename(p))
                else:
                    failed.append(p or "(空路径)")
            if added:
                tip = "、".join(added[:3]) + (f" 等{len(added)}个" if len(added) > 3 else "")
                self._notify_edit(f"已加入时间线: {tip}" + (f" ({src})" if src else ""))
                print(f"✅ Agent 素材已添加到时间线: {tip}")
            if failed:
                msg = f"{len(failed)} 个素材未能加入时间线（文件不存在）: {', '.join(failed[:3])}"
                print(f"⚠️ {msg}")
                try:
                    self._notify_edit(msg)
                except Exception:
                    pass
            return

        file_path = data.get("file_path", "") if isinstance(data, dict) else str(data)
        if file_path and os.path.exists(file_path):
            self._add_clip_to_timeline(file_path)
            title = data.get("title", "") if isinstance(data, dict) else ""
            tip = title or os.path.basename(file_path)
            self._notify_edit(f"已加入时间线: {tip}" + (f" ({src})" if src else ""))
            print(f"✅ 素材已添加到时间线: {os.path.basename(file_path)}")
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
            print(f"⚠️ {msg}")
            try:
                QMessageBox.warning(self, "添加失败", msg)
            except Exception:
                pass
            try:
                self._notify_edit(msg)
            except Exception:
                pass

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
        res = push_editor_to_canvas(path, title=str(title), source="editor")
        if res.get("success"):
            self._notify_edit(res.get("message") or "已推送到画布")
            self._record_ai_tool_history(res.get("message") or "发送到画布")
            QMessageBox.information(
                self,
                "已发送到画布",
                (res.get("message") or "成功")
                + "\n请打开「AI 画布」，在右下角「来自剪辑」下载或导入。",
            )
        else:
            QMessageBox.warning(self, "发送失败", res.get("message") or "未知错误")

    def _on_files_dropped(self, file_paths):
        """处理时间线拖放导入的文件列表"""
        for file_path in file_paths:
            if os.path.exists(file_path):
                self._add_clip_to_timeline(file_path)
                print(f"✅ 拖放导入成功: {os.path.basename(file_path)}")
            else:
                print(f"⚠️ 无法导入: {file_path}")

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

    def _remove_fillers_and_silence(self):
        from app.modules.lego.editor_subtitle_panel import remove_fillers_and_silence
        remove_fillers_and_silence(self)

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

    def _generate_ai_subtitles(self):
        from app.modules.lego.editor_subtitle_panel import generate_ai_subtitles
        generate_ai_subtitles(self)

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
        """已废弃：禁止生成与对白无关的占位字幕。"""
        return []
    
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
            _clear_msgbox("操作提示", "请先导入视频")
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
            _clear_msgbox("操作提示", "请先导入视频")
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
            "clips": self._clips,
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
            mtime = os.path.getmtime(latest)
            from datetime import datetime
            mtime_s = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            reply = QMessageBox.question(
                self,
                "恢复自动保存",
                f"发现 autosave/latest.timeline\n修改时间：{mtime_s}\n\n是否恢复？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    self.import_project(latest)
                except Exception as ie:
                    QMessageBox.warning(
                        self, "恢复失败",
                        f"无法恢复自动保存工程：\n{ie}",
                    )
        except Exception as e:
            try:
                QMessageBox.warning(self, "恢复自动保存", f"询问失败：{e}")
            except Exception:
                print(f"autosave 恢复询问失败: {e}")

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
                # 合并到真相源
                for i, c in enumerate(self._clips):
                    if c.get("id") == cid:
                        c.update({
                            k: after[k] for k in ("start_time", "track", "duration", "in_point", "out_point")
                            if k in after
                        })
                        clip = c
                        self._clips[i] = c
                        break
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
                    print(f"linked AV sync failed: {e}")
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
                print(f"batch move sync failed: {e}")
            self._notify_edit(f"已批量移动 {len(steps)} 个片段")
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
                steps = [{
                    "type": "edit_clip",
                    "clip_id": cid,
                    "before": before,
                    "after": after,
                }]
                try:
                    steps.extend(self._linked_av_edit_steps(clip_data, before=before))
                except Exception:
                    pass
                if len(steps) == 1:
                    self._record_action(steps[0])
                else:
                    self._record_action({"type": "compound", "steps": steps})
        # 联动音视频 timing 同步（撤销步骤已在同步前快照）
        try:
            self._sync_linked_av_timing(clip_data, before=before)
        except Exception as e:
            print(f"linked AV sync failed: {e}")
        self._touch_project_dirty()
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
            print(f"导入工程画幅失败: {e}")
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

        # 旧工程可能只存了视频片：补联动音频，否则音频轨无波形
        self._ensure_linked_audio_clips()
        # 修复「视频轨被裁成 ~8s、同文件音频仍是全长」导致播放后半只剩声音
        try:
            self._heal_linked_av_duration_mismatch()
        except Exception as e:
            print(f"联动音画时长修复失败: {e}")

        # 无 sequence / resolution 的旧工程：按首个视频片推断画幅
        if _sequence_needs_infer:
            try:
                if self._infer_sequence_from_clips():
                    self._apply_sequence_format_to_export_combos()
                    self._apply_sequence_format_to_preview()
                    self._refresh_preview_aspect_badge()
            except Exception as e:
                print(f"推断工程画幅失败: {e}")

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
            print(f"导入字幕失败: {e}")

        # 恢复贴纸
        try:
            raw_stk = project_data.get("stickers") or []
            self._active_stickers = [dict(s) for s in raw_stk if isinstance(s, dict)]
            self._refresh_sticker_list_ui()
        except Exception as e:
            print(f"导入贴纸失败: {e}")
            self._active_stickers = []

        # 主选优先视频片（避免首条是联动音频时预览走偏）
        try:
            for c in self._clips:
                if str(c.get("type", "")).lower() != "audio" and c.get("path"):
                    self._current_clip = c
                    break
        except Exception:
            pass

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
            pass
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
                print(f"同步片段到内核失败: {e}")
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
                pass
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
                pass
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
            pass
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
            pass
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
                    pass
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
                pass
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
                    pass
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
            print(f"预览片段刷新失败: {e}")
            self._preview_seg_key = None
            try:
                self._force_show_first_video_frame()
            except Exception:
                pass

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
        from app.modules.lego.editor_ai_panel import build_ai_panel_tab
        return build_ai_panel_tab(self)

    def _record_ai_tool_history(self, text: str):
        """把 AI 工具处理结果写入「处理历史」列表（此前控件创建后从未写入，永远是空的）"""
        history_list = getattr(self, "_ai_history_list", None)
        if history_list is None:
            return
        try:
            from datetime import datetime
            history_list.insertItem(0, f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
            while history_list.count() > 50:
                history_list.takeItem(history_list.count() - 1)
        except Exception:
            pass

    def _funclip_process(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
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
                if not segments:
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(self, "FunClip", "未检测到有效场景（空结果）。请换有镜头切换的素材。")
                    ))
                    return
                seg_list_path = os.path.join(output_dir, f"{base_name}_segments.txt")
                with open(seg_list_path, 'w', encoding='utf-8') as f:
                    for s, e in segments:
                        f.write(f"file '{clip_path}'\ninpoint {s}\noutpoint {e}\n")
                ffres = subprocess.run([
                    self._get_ffmpeg(), "-y", "-f", "concat", "-safe", "0",
                    "-segment_time_metadata", "1",
                    "-i", seg_list_path,
                    "-vf", "select=concatdec_select,setpts=PTS-STARTPTS",
                    "-c:v", "libx264", "-preset", "fast",
                    "-an", output_path
                ], capture_output=True, text=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
                if ffres.returncode != 0 or not os.path.isfile(output_path):
                    err = (ffres.stderr or "")[-500:]
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(self, "FunClip", f"导出失败:\n{err or '输出文件不存在，请检查 FFmpeg'}")
                    ))
                else:
                    # 修复：此前只弹「完成」提示，成片从不加入时间线，用户还要
                    # 手动去输出目录导入——体验割裂。这里直接加进时间线；
                    # 同时如实提示输出无音轨（拼接用的是 concatdec select 视频
                    # 滤镜，未做音频对应拼接，故用 -an 去掉了音轨，不是缺陷
                    # 遗漏，但必须让用户知道不是"完整成片"）。
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        self._add_clip_to_timeline(output_path),
                        self._record_ai_tool_history(f"FunClip 场景检测完成 → {os.path.basename(output_path)}"),
                        QMessageBox.information(self, "FunClip",
                            f"场景检测完成，已添加到时间线！\n输出: {output_path}\n\n"
                            f"⚠️ 该成片仅保留视频画面，不含原始音轨")
                    ))
            except ImportError:
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "提示", "请安装cv2: pip install opencv-python")
                ))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "失败", f"处理失败: {err}")
                ))
        t = threading.Thread(target=process, daemon=True)
        t.start()

    def _refresh_ollama_diagnose_ui(self):
        """把 Ollama diagnose() 摘要显示在 AI 页。"""
        label = getattr(self, "_ollama_status_label", None)
        if label is None:
            return
        try:
            from app.modules.lego.ollama_client import ollama_client
            report = ollama_client.diagnose()
            self._last_ollama_report = report
            if report.get("service_running"):
                models = ollama_client.list_models()
                n = len(models or [])
                label.setText(f"● 运行中 · {report.get('base_url','')} · 模型 {n} 个")
                label.setStyleSheet("color:#22c55e;font-size:10px;font-weight:600;")
                if n == 0:
                    label.setText(
                        f"● 运行中但无模型 · {report.get('base_url','')} · 请 ollama pull <模型>"
                    )
                    label.setStyleSheet("color:#f59e0b;font-size:10px;font-weight:600;")
            elif not report.get("installed"):
                label.setText("● 未安装 · " + (report.get("suggestion") or "请安装 Ollama")[:80])
                label.setStyleSheet("color:#ef4444;font-size:10px;")
            else:
                err = report.get("error") or "服务未运行"
                label.setText(f"● 未运行 · {err}")
                label.setStyleSheet("color:#ef4444;font-size:10px;")
            tip = ollama_client.format_diagnose_report(report)
            label.setToolTip(tip)
        except Exception as e:
            label.setText(f"● 诊断失败: {e}")
            label.setStyleSheet("color:#f59e0b;font-size:10px;")

    def _show_ollama_diagnose_detail(self):
        """弹窗展示完整 diagnose() 文案。"""
        try:
            from app.modules.lego.ollama_client import ollama_client
            msg = ollama_client.diagnose_user_message()
        except Exception as e:
            msg = f"诊断失败: {e}"
        QMessageBox.information(self, "Ollama 诊断", msg)

    def _autoclip_process(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
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
                if not best:
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(self, "失败", "未检测到有效高光片段（视频过短或无法解码）")
                    ))
                    return
                ffres = subprocess.run([
                    self._get_ffmpeg(), "-y", "-f", "concat", "-safe", "0",
                    "-segment_time_metadata", "1",
                    "-i", clip_list,
                    "-vf", "select=concatdec_select,setpts=PTS-STARTPTS",
                    "-c:v", "libx264", "-preset", "fast",
                    output_path
                ], capture_output=True, text=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
                if ffres.returncode == 0 and os.path.exists(output_path):
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        self._add_clip_to_timeline(output_path),
                        self._record_ai_tool_history(f"AutoClip 高光检测完成 → {os.path.basename(output_path)}"),
                        QMessageBox.information(self, "AutoClip", f"高光检测完成，已添加到时间线！输出: {output_path}")
                    ))
                else:
                    err = (ffres.stderr or "")[-500:]
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(self, "失败", f"高光片段合成失败:\n{err}")
                    ))
            except ImportError:
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "提示", "请安装cv2: pip install opencv-python")
                ))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "失败", f"处理失败: {err}")
                ))
        t = threading.Thread(target=process, daemon=True)
        t.start()

    def _videofusion_process(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
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
                    self._get_ffmpeg(), "-y", "-i", clip_path,
                    "-vf", filter_str,
                    "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-c:a", "aac", "-b:a", "192k",
                    output_path
                ], capture_output=True, text=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
                if result.returncode == 0:
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        self._add_clip_to_timeline(output_path),
                        self._record_ai_tool_history(f"Fusion 画质增强完成 → {os.path.basename(output_path)}"),
                        QMessageBox.information(self, "VideoFusion", f"画质增强完成，已添加到时间线！输出: {output_path}")
                    ))
                else:
                    err = result.stderr
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(self, "失败", f"增强失败: {err}")
                    ))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "失败", f"处理失败: {err}")
                ))
        t = threading.Thread(target=process, daemon=True)
        t.start()

    def _lora_edit_process(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
            return
        clip_path = self._clips[0]['path']
        output_dir = "短剧AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(clip_path).rsplit('.', 1)[0]
        output_path = os.path.join(output_dir, f"{base_name}_stylized.mp4")
        msg = QMessageBox(self)
        msg.setWindowTitle("风格化（滤镜近似）")
        msg.setText("正在应用风格化效果（FFmpeg 调色滤镜近似，非 LoRA/神经网络风格迁移）...")
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
                    self._get_ffmpeg(), "-y", "-i", clip_path,
                    "-vf", filter_str,
                    "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-c:a", "copy",
                    output_path
                ], capture_output=True, text=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
                if result.returncode == 0 and os.path.exists(output_path):
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        self._add_clip_to_timeline(output_path),
                        self._record_ai_tool_history(f"风格化完成 → {os.path.basename(output_path)}"),
                        QMessageBox.information(self, "完成", f"风格化完成，已添加到时间线！输出: {output_path}")
                    ))
                else:
                    err = (result.stderr or "")[-500:]
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(self, "失败", f"处理失败: {err}")
                    ))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "失败", f"处理失败: {err}")
                ))
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
        # M2：漫剧竖屏预设置顶，并真正改分辨率/比例（此前仅展示文案）
        self._output_mode_var.addItems([
            "漫剧竖屏快切",
            "自定义参数",
            "30秒爆款引流",
            "90秒剧情解说",
            "8分钟挂车长视频",
            "B站横屏长视频",
        ])
        self._output_mode_var.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:4px 8px;font-size:10px;}QComboBox:hover{border-color:#333;}")
        mo.layout().addWidget(self._output_mode_var)
        drama_btn = QPushButton("📱 一键漫剧竖屏 1080×1920")
        drama_btn.setStyleSheet(
            "QPushButton{background:#1a3a2a;color:#7ee787;border:1px solid #2f5139;"
            "border-radius:4px;padding:6px;font-size:10px;font-weight:600;}"
            "QPushButton:hover{background:#238636;color:#fff;}"
        )
        drama_btn.setToolTip("抖音/快手/小红书竖屏：9:16 · 1080x1920 · 30fps · 导出等比填充黑边")
        drama_btn.clicked.connect(self._apply_manju_portrait_preset)
        mo.layout().addWidget(drama_btn)
        landscape_btn = QPushButton("🖥️ 一键横屏 1920×1080")
        landscape_btn.setStyleSheet(
            "QPushButton{background:#1a2744;color:#79c0ff;border:1px solid #1f6feb;"
            "border-radius:4px;padding:6px;font-size:10px;font-weight:600;}"
            "QPushButton:hover{background:#1f6feb;color:#fff;}"
        )
        landscape_btn.setToolTip("B站/横屏：16:9 · 1920x1080 · 30fps · 导出等比填充黑边")
        landscape_btn.clicked.connect(self._apply_landscape_preset)
        mo.layout().addWidget(landscape_btn)
        l.addWidget(mo)
        
        vo = self._sect("🎬 视频参数")
        vo_lo = vo.layout()
        self._platform_var = QComboBox()
        self._platform_var.addItems(["抖音", "快手", "视频号", "B站", "小红书", "默认"])
        self._resolution_var = QComboBox()
        self._resolution_var.addItems([
            "1080x1920", "720x1280", "1920x1080", "1280x720", "1080x1080", "3840x2160",
        ])
        self._aspect_var = QComboBox()
        self._aspect_var.addItems(["9:16", "16:9", "1:1", "4:3"])
        self._fit_mode_var = QComboBox()
        self._fit_mode_var.addItem("等比黑边", "contain")
        self._fit_mode_var.addItem("裁切铺满", "cover")
        self._fit_mode_var.setToolTip(
            "素材相对工程画幅：黑边=完整可见；裁切=铺满画幅（可能切边）。预览与导出同步。"
        )
        self._fps_var = QComboBox()
        self._fps_var.addItems(["30fps", "60fps", "24fps", "25fps", "50fps"])
        self._codec_var = QComboBox()
        self._codec_var.addItems(["H.264", "H.265", "VP9", "AV1"])
        self._format_var = QComboBox()
        self._format_var.addItems(["MP4", "MKV", "AVI", "MOV"])
        self._bitrate_var = QComboBox()
        self._bitrate_var.addItems(["3000k", "2000k", "5000k", "1M", "10M"])
        self._bitrate_control_var = QComboBox()
        self._bitrate_control_var.addItems(["CBR", "VBR", "CRF"])
        self._bitrate_control_var.setToolTip(
            "CBR=恒定码率（按上方比特率）；VBR=可变码率（上方比特率为目标均值）；"
            "CRF=恒定质量（忽略比特率，按下方质量档位控制体积/画质）"
        )
        self._quality_var = QComboBox()
        self._quality_var.addItems(["高", "中", "低"])
        self._quality_var.setToolTip("画质档位：CRF 模式下直接决定质量；其他模式下影响编码预设")
        self._gop_var = QSpinBox()
        self._gop_var.setRange(1, 300)
        self._gop_var.setValue(30)
        self._gop_var.setToolTip("关键帧间隔（GOP），越小 seek 越快但体积越大，直播/短视频常用等于帧率")
        _cmb_ss = (
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;"
            "padding:3px 6px;font-size:10px;}"
        )
        for cmb in (
            self._platform_var, self._resolution_var, self._aspect_var, self._fit_mode_var,
            self._fps_var, self._codec_var, self._format_var, self._bitrate_var,
            self._bitrate_control_var, self._quality_var,
        ):
            cmb.setStyleSheet(_cmb_ss)
        self._gop_var.setStyleSheet("QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}")
        self._add_cmb_row(vo_lo, "平台", self._platform_var)
        self._add_cmb_row(vo_lo, "分辨率", self._resolution_var)
        self._add_cmb_row(vo_lo, "比例", self._aspect_var)
        self._add_cmb_row(vo_lo, "适配", self._fit_mode_var)
        self._add_cmb_row(vo_lo, "帧率", self._fps_var)
        self._add_cmb_row(vo_lo, "编码", self._codec_var)
        self._add_cmb_row(vo_lo, "格式", self._format_var)
        self._add_cmb_row(vo_lo, "比特率", self._bitrate_var)
        self._add_cmb_row(vo_lo, "码控", self._bitrate_control_var)
        self._add_cmb_row(vo_lo, "质量", self._quality_var)
        self._add_setting_row(vo_lo, "GOP", self._gop_var)
        # M2：平台 / 输出模式联动预设；避免改平台时互相打架用 blockSignals
        self._platform_var.currentTextChanged.connect(self._on_export_platform_changed)
        self._output_mode_var.currentTextChanged.connect(self._on_export_output_mode_changed)
        self._aspect_var.currentTextChanged.connect(self._on_export_aspect_or_resolution_changed)
        self._resolution_var.currentTextChanged.connect(self._on_export_aspect_or_resolution_changed)
        self._fit_mode_var.currentIndexChanged.connect(self._on_export_fit_mode_changed)
        self._format_var.currentTextChanged.connect(self._on_export_format_changed)
        QTimer.singleShot(0, self._apply_manju_portrait_preset)
        l.addWidget(vo)
        
        au = self._sect("🔊 音频参数")
        au_lo = au.layout()
        self._audio_codec_var = QComboBox(); self._audio_codec_var.addItems(["AAC", "MP3", "WAV"])
        self._audio_channel_var = QComboBox(); self._audio_channel_var.addItems(["立体声", "单声道"])
        self._audio_sample_var = QComboBox(); self._audio_sample_var.addItems(["44100", "48000", "22050"])
        self._audio_bitrate_var = QComboBox(); self._audio_bitrate_var.addItems(["128k", "192k", "256k", "320k"])
        for cmb in (
            self._audio_codec_var, self._audio_channel_var,
            self._audio_sample_var, self._audio_bitrate_var,
        ):
            cmb.setStyleSheet(_cmb_ss)
        self._add_cmb_row(au_lo, "编码", self._audio_codec_var)
        self._add_cmb_row(au_lo, "通道", self._audio_channel_var)
        self._add_cmb_row(au_lo, "采样率", self._audio_sample_var)
        self._add_cmb_row(au_lo, "比特率", self._audio_bitrate_var)
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
        self._hw_section.setVisible(True)
        
        exp_btn = QPushButton("💾 开始导出")
        exp_btn.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;padding:8px;font-size:12px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        exp_btn.clicked.connect(self._export_video)
        l.addWidget(exp_btn)
        QTimer.singleShot(0, self._refresh_export_project_info)
        
        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0, 0, 0, 0)
        o.addWidget(s)
        return t

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
            pass
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
                pass
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
            pass

    def _on_export_aspect_or_resolution_changed(self, *_args) -> None:
        sender = self.sender() if hasattr(self, "sender") else None
        prefer_aspect = sender is getattr(self, "_aspect_var", None)
        self._sync_sequence_format_from_export_combos(prefer_aspect=prefer_aspect)
        self._refresh_preview_aspect_badge()
        try:
            self._schedule_preview_refresh()
        except Exception:
            pass

    def _on_export_fit_mode_changed(self, *_args) -> None:
        self._sync_sequence_format_from_export_combos(prefer_aspect=False)
        self._refresh_preview_aspect_badge()
        try:
            self._schedule_preview_refresh()
        except Exception:
            pass

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
            pass

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
            pass

    def _apply_manju_portrait_preset(self) -> None:
        """一键漫剧竖屏：抖音系 9:16 / 1080x1920。"""
        self._apply_export_video_preset(
            platform="抖音",
            resolution="1080x1920",
            aspect="9:16",
            bitrate="5000k",
            fps="30fps",
            output_mode="漫剧竖屏快切",
        )
        self._notify_edit("已套用漫剧竖屏：1080×1920 · 9:16（导出等比+黑边）")

    def _apply_landscape_preset(self) -> None:
        """一键横屏：B站系 16:9 / 1920x1080。"""
        self._apply_export_video_preset(
            platform="B站",
            resolution="1920x1080",
            aspect="16:9",
            bitrate="5000k",
            fps="30fps",
            output_mode="B站横屏长视频",
        )
        self._notify_edit("已套用横屏：1920×1080 · 16:9（导出等比+黑边）")

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
            print(f"时间线帧渲染失败: {e}")

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

    def _try_render_plugin_transition(self, timeline_t: float, video_hits, pm):
        """
        片尾转场窗内：解出/入两帧，走 ITransitionPlugin / apply()。
        成功返回 BGR；否则 None（回退叠层 + dissolve 近似）。
        """
        candidates = list(video_hits or [])
        # 也检查即将结束、尚在转场窗内的片（下片可能尚未命中）
        for c in getattr(self, "_clips", None) or []:
            if str(c.get("type", "")).lower() == "audio":
                continue
            tr = self._clip_outgoing_transition(c)
            if not tr:
                continue
            st = float(c.get("start_time", 0) or 0)
            end = st + float(c.get("duration", 0) or 0)
            fade = float(tr.get("duration", 0.5) or 0.5)
            if end - fade <= timeline_t <= end + 0.02:
                if c not in candidates:
                    candidates.append(c)
        for clip in candidates:
            tr = self._clip_outgoing_transition(clip)
            if not tr:
                continue
            fade = float(tr.get("duration", 0.5) or 0.5)
            if fade <= 0.05:
                continue
            st = float(clip.get("start_time", 0) or 0)
            end = st + float(clip.get("duration", 0) or 0)
            if not (end - fade <= timeline_t <= end + 0.02):
                continue
            nxt = self._find_next_clip_same_track(clip)
            if not nxt:
                continue
            # 允许邻接或轻微重叠
            nst = float(nxt.get("start_time", 0) or 0)
            if nst > end + 0.15:
                continue
            progress = (timeline_t - (end - fade)) / fade
            progress = max(0.0, min(1.0, progress))
            plugin_id = tr.get("plugin_id") or tr.get("type") or tr.get("name")
            try:
                from app.core.transition_plugin_registry import (
                    apply_frames, resolve_plugin_id, easing_from_curve,
                )
            except Exception:
                from core.transition_plugin_registry import (
                    apply_frames, resolve_plugin_id, easing_from_curve,
                )
            pid = resolve_plugin_id(str(plugin_id or "")) or str(plugin_id or "")
            if not pid:
                continue
            a = self._decode_clip_bgr_at(clip, min(timeline_t, end - 1e-3), pm)
            b = self._decode_clip_bgr_at(nxt, max(timeline_t, nst), pm)
            if a is None or b is None:
                continue
            params = {
                "duration": fade,
                "easing": easing_from_curve(str(tr.get("curve") or "线性")),
                "direction": tr.get("direction") or "right",
            }
            mixed = apply_frames(pid, a, b, progress, params)
            if mixed is None:
                continue
            return mixed
        return None

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
            pass
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
        print(f"播放头移动到 {position}s")
    
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
                pass
        try:
            dur = max(dur, float(getattr(self, "_total_duration", 0) or 0))
        except Exception:
            pass
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
            pass
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
            pass

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
        self._clips = result.clips
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

    def _nudge_selected_clip_frames(self, frames: int):
        """Shift+←/→：选中片段（支持多选）按帧平移。"""
        tw = getattr(self, "_timeline_widget", None)
        clips = []
        if tw is not None and hasattr(tw, "get_selected_clips"):
            clips = list(tw.get_selected_clips() or [])
        if not clips:
            clip = getattr(self, "_current_clip", None)
            if clip:
                clips = [clip]
        if not clips:
            return
        step = self._edit_frame_duration() * int(frames)
        if len(clips) == 1:
            clip = clips[0]
            before = {
                "id": clip.get("id"),
                "start_time": float(clip.get("start_time", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
                "track": int(clip.get("track", 0) or 0),
            }
            clip["start_time"] = max(0.0, float(clip.get("start_time", 0) or 0) + step)
            if tw is not None:
                for w in tw.all_clip_widgets():
                    if w.clip_data.get("id") == clip.get("id"):
                        tw.position_clip_widget(w)
                        break
            payload = dict(clip)
            payload["_edit_before"] = before
            try:
                self._on_clip_trim_committed(payload)
            except Exception:
                self._sync_timeline_widget_state()
            return
        # 多选：一条 compound
        items = []
        for clip in clips:
            st0 = float(clip.get("start_time", 0) or 0)
            before = {
                "id": clip.get("id"),
                "start_time": st0,
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
                "track": int(clip.get("track", 0) or 0),
            }
            clip["start_time"] = max(0.0, st0 + step)
            after = {
                "start_time": float(clip["start_time"]),
                "track": int(clip.get("track", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
            }
            items.append({"clip_id": clip.get("id"), "before": before, "after": after, "clip": clip})
            if tw is not None:
                for w in tw.all_clip_widgets():
                    if w.clip_data.get("id") == clip.get("id"):
                        tw.position_clip_widget(w)
                        break
        self._on_clip_trim_committed({"_batch_move": True, "items": items})
    
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
            self._clips.append(clip)

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
        if hasattr(self, '_audio_manager') and self._audio_manager:
            tracks = self._audio_manager.list_audio_tracks()
            for t in tracks:
                self._audio_manager.adjust_audio_volume(t['id'], out)
        self._notify_edit(f"总控音量 {int(vol * 100)}%")

    def _apply_fade_effects(self):
        """应用音频页整套设置：淡入淡出 + 均衡器 + 降噪 + 压缩器 + 混响（一次 ffmpeg 调用）。"""
        src = self._get_active_audio_path()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入音频/视频素材")
            return

        def _spn_val(attr, default=0):
            row = getattr(self, attr, None)
            w = row.findChild(QSpinBox) if row is not None else None
            return w.value() if w is not None else default

        def _slr_val(attr, default=0):
            row = getattr(self, attr, None)
            w = row.findChild(QSlider) if row is not None else None
            return w.value() if w is not None else default

        def _cmb_val(attr, default="无"):
            row = getattr(self, attr, None)
            w = row.findChild(QComboBox) if row is not None else None
            return w.currentText() if w is not None else default

        fade_in_ms = _spn_val("_fade_in_row", 0)
        fade_out_ms = _spn_val("_fade_out_row", 0)
        eq_low = _slr_val("_eq_low_row", 0)
        eq_mid = _slr_val("_eq_mid_row", 0)
        eq_high = _slr_val("_eq_high_row", 0)
        denoise_on = bool(getattr(self, "_denoise_chk", None) and self._denoise_chk.isChecked())
        denoise_strength = _slr_val("_denoise_strength_row", 50)
        comp_on = bool(getattr(self, "_compressor_chk", None) and self._compressor_chk.isChecked())
        comp_ratio = _slr_val("_compressor_ratio_row", 50)
        reverb = _cmb_val("_reverb_row", "无")

        dur = float(self._get_video_duration(src) or 0)
        af_parts = []
        if fade_in_ms > 0:
            af_parts.append(f"afade=t=in:st=0:d={fade_in_ms / 1000.0:.3f}")
        if fade_out_ms > 0:
            fo_s = fade_out_ms / 1000.0
            st = max(0.0, (dur - fo_s)) if dur > 0 else 0.0
            af_parts.append(f"afade=t=out:st={st:.3f}:d={fo_s:.3f}")
        if eq_low:
            af_parts.append(f"equalizer=f=100:width_type=o:width=2:g={eq_low}")
        if eq_mid:
            af_parts.append(f"equalizer=f=1000:width_type=o:width=1:g={eq_mid}")
        if eq_high:
            af_parts.append(f"equalizer=f=8000:width_type=o:width=2:g={eq_high}")
        if denoise_on:
            nr = max(0.01, min(97.0, 3.0 + denoise_strength / 100.0 * 94.0))
            af_parts.append(f"afftdn=nr={nr:.2f}")
        if comp_on:
            ratio = max(1.0, min(20.0, 1.0 + comp_ratio / 100.0 * 19.0))
            af_parts.append(f"acompressor=threshold=-20dB:ratio={ratio:.2f}:attack=5:release=50")
        reverb_map = {
            "小房间": "aecho=0.8:0.5:40:0.25",
            "中厅": "aecho=0.8:0.6:60|100:0.3|0.2",
            "大教堂": "aecho=0.8:0.7:100|200|300:0.4|0.3|0.2",
            "板式": "aecho=0.8:0.5:20:0.3",
            "弹簧": "aecho=0.8:0.6:30|60:0.35|0.25",
        }
        if reverb in reverb_map:
            af_parts.append(reverb_map[reverb])

        if not af_parts:
            QMessageBox.information(self, "提示", "未设置任何音频效果（淡入淡出/均衡器/降噪/压缩器/混响均为默认值）")
            return

        dst = self._output_path(src, '_audiofx')
        ffmpeg = self._get_ffmpeg()
        try:
            result = subprocess.run([
                ffmpeg, '-y', '-i', src,
                '-af', ",".join(af_parts),
                '-q:a', '2', dst
            ], capture_output=True, text=True)
            if result.returncode != 0 or not os.path.exists(dst):
                QMessageBox.warning(self, "失败", f"音频效果处理失败:\n{(result.stderr or '')[-500:]}")
                return
            self._add_to_clips(dst, 'audio')
            QMessageBox.information(
                self, "完成",
                f"已应用音频效果（淡入{fade_in_ms}ms/淡出{fade_out_ms}ms"
                f"{'/降噪' if denoise_on else ''}{'/压缩' if comp_on else ''}"
                f"{'/混响:' + reverb if reverb in reverb_map else ''}）:\n{dst}",
            )
        except Exception as e:
            QMessageBox.warning(self, "失败", f"处理失败: {e}")

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
        payload = {"clip": deleted_clip, "ripple_shifts": ripple_shifts}
        if record:
            self._record_action({"type": "delete", **payload})
        if sync:
            self._sync_kernel_timeline()
            self._sync_timeline_widget_state()
            self._refresh_preview_to_current_clip()
            self._notify_edit("已删除片段" + ("（波纹）" if ripple else ""))
        return payload

    def _sync_timeline_widget_state(self):
        """同步片段元数据到 ClipWidget，并按 start_time 重新定位。"""
        if not hasattr(self, '_timeline_widget'):
            return
        tw = self._timeline_widget
        # 合缝等路径会 deepcopy 替换 _clips；镜像到时间线并刷新活引用
        tw._clips = list(self._clips)
        try:
            if hasattr(tw, "refresh_load_spans"):
                tw.refresh_load_spans(self._clips)
            if hasattr(tw, "update_in_out_markers"):
                tw.update_in_out_markers(
                    getattr(self, "_sequence_in_point", None),
                    getattr(self, "_sequence_out_point", None),
                )
        except Exception as e:
            logger.debug("同步标尺 I/O / 负载线失败: %s", e)
        cur_id = None
        if isinstance(getattr(self, "_current_clip", None), dict):
            cur_id = self._current_clip.get("id")
        if cur_id:
            self._current_clip = next(
                (c for c in self._clips if c.get("id") == cur_id),
                self._current_clip,
            )
        if isinstance(getattr(tw, "_current_clip", None), dict):
            tid = tw._current_clip.get("id")
            if tid:
                tw._current_clip = next(
                    (c for c in self._clips if c.get("id") == tid),
                    tw._current_clip,
                )
        if hasattr(tw, "all_clip_widgets"):
            for widget in tw.all_clip_widgets():
                clip_id = widget.clip_data.get("id")
                for clip in self._clips:
                    if clip.get("id") == clip_id:
                        widget.clip_data = clip
                        if hasattr(widget, "set_keyframes"):
                            widget.set_keyframes(clip.get("keyframes") or [])
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
            if hasattr(tw, "_apply_selection_visual"):
                tw._apply_selection_visual()
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
            _clear_msgbox("操作提示", "请先导入视频")
    
    def _top0_smart_clip(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
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
            _clear_msgbox("操作提示", "请先导入视频")
            return
        
        viral_engine = self._ensure_viral_engine()
        if not viral_engine:
            _clear_msgbox("引擎未就绪", "爆款优化引擎未加载,请检查依赖安装")
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
   {i}. {gene.pattern_name} (经验成功率: {gene.success_rate:.1%})
      {gene.description}
      关键要素: {', '.join(gene.key_elements)}
"""
            # 如实说明：以上"成功率"/预测数据来自行业经验规则库和启发式模型，
            # 不是本软件对真实播放数据的统计结果，仅供参考
            result_text += "\n⚠️ 以上预测和成功率均为启发式估算，非真实平台数据统计，仅供参考\n"
            
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
                    QTimer.singleShot(0, lambda: (
                        self._add_to_clips(dst, 'video'),
                        QMessageBox.information(self, "完成", f"画中画合成完成:\n{dst}")
                    ))
                else:
                    err = result.stderr[-500:]
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"合成失败:\n{err}"))
            except subprocess.TimeoutExpired:
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", "处理超时（5分钟）"))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"处理出错: {err}"))

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
                    QTimer.singleShot(0, lambda: (
                        self._add_to_clips(dst, 'video'),
                        QMessageBox.information(self, "完成", f"抠像完成:\n{dst}")
                    ))
                else:
                    err = result.stderr[-500:]
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"抠像失败:\n{err}"))
            except subprocess.TimeoutExpired:
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", "处理超时"))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"处理出错: {err}"))

        threading.Thread(target=do_chroma, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    # 曲线变速 (Speed Ramping)
    # ═══════════════════════════════════════════════════════════════
    def _apply_speed_ramp(self):
        """曲线变速：优先走 core.speed_ramping；UI 回调回主线程（A3）。"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return

        clip = self._current_clip
        if not clip or self._is_export_audio_clip(clip):
            video_clips = [
                c for c in self._clips
                if c.get("path") and not self._is_export_audio_clip(c)
            ]
            clip = video_clips[0] if video_clips else None
        if not clip:
            QMessageBox.warning(self, "提示", "没有可用的视频片段")
            return

        src = clip.get("path", "")
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return

        dst = self._output_path(src, '_speedramp').replace('.mp3', '.mp4')
        preset = self._speed_preset.currentText() if hasattr(self, '_speed_preset') else "无"
        speed_factor = (self._speed_factor.value() if hasattr(self, '_speed_factor') else 100) / 100.0

        if preset == "无" and abs(speed_factor - 1.0) < 1e-6:
            QMessageBox.warning(self, "提示", "请选择变速预设或调整速度因子")
            return

        self._notify_edit(f"曲线变速处理中: {preset}…")

        preset_map = {
            "缓入": "ramp_in",
            "缓出": "ramp_out",
            "缓入缓出": "fast_slow_fast",
            "卡点变速": "bullet_time",
        }

        def _done(ok: bool, path: str, err: str = "", *, speed=None, ramp_dict=None):
            if ok and path and os.path.exists(path):
                if ramp_dict is not None:
                    clip["speed_ramp"] = ramp_dict
                if speed is not None:
                    try:
                        self.set_clip_speed(clip.get("id"), float(speed))
                    except Exception:
                        clip["speed"] = float(speed)
                self._add_to_clips(path, 'video')
                QMessageBox.information(self, "完成", f"变速成片已加入时间线:\n{path}")
            else:
                QMessageBox.warning(self, "失败", err or "变速失败")

        def do_speed():
            err = ""
            ramp_dict = None
            speed_val = None
            try:
                from app.core.speed_ramping import (
                    SpeedRamp, SpeedEasing,
                    apply_speed_ramp_ffmpeg, reverse_clip_ffmpeg,
                )
                video_duration = float(self._get_video_duration(src) or 0) or 10.0
                ok = False
                if preset == "倒放":
                    ok = reverse_clip_ffmpeg(src, dst)
                    err = "" if ok else "倒放失败"
                elif preset in preset_map:
                    ramp = SpeedRamp.preset_preset(preset_map[preset])
                    easing_map = {
                        "线性": SpeedEasing.LINEAR,
                        "缓入": SpeedEasing.EASE_IN,
                        "缓出": SpeedEasing.EASE_OUT,
                        "缓入缓出": SpeedEasing.EASE_IN_OUT,
                        "阶梯": SpeedEasing.STEP,
                    }
                    ui_easing = easing_map.get(
                        self._speed_easing.currentText() if hasattr(self, "_speed_easing") else "线性"
                    )
                    if ui_easing is not None:
                        # UI「缓动」下拉覆盖预设默认曲线（卡点变速用阶跃形，保留原样更稳）
                        if preset != "卡点变速":
                            for kf in ramp.keyframes[1:]:
                                kf.easing = ui_easing
                    # 关键帧时间按片段时长归一化到绝对秒
                    for kf in ramp.keyframes:
                        kf.time = float(kf.time) * video_duration
                    ok = apply_speed_ramp_ffmpeg(src, dst, ramp, total_duration=video_duration)
                    if ok:
                        ramp_dict = ramp.to_dict()
                    err = "" if ok else "曲线变速渲染失败（可改用固定倍率「应用变速」）"
                else:
                    # 固定倍率：写入片段 speed（预览）并导出成片
                    factor = {
                        "0.25x慢放": 0.25,
                        "0.5x慢放": 0.5,
                        "2x快放": 2.0,
                        "4x快放": 4.0,
                    }.get(preset, speed_factor)
                    ramp = SpeedRamp(enabled=True)
                    ramp.add_keyframe(0.0, float(factor), SpeedEasing.LINEAR)
                    ramp.add_keyframe(video_duration, float(factor), SpeedEasing.LINEAR)
                    ok = apply_speed_ramp_ffmpeg(src, dst, ramp, total_duration=video_duration)
                    if ok:
                        speed_val = float(factor)
                        ramp_dict = ramp.to_dict()
                    err = "" if ok else "固定倍率导出失败"
                QTimer.singleShot(
                    0,
                    lambda ok=ok, err=err, rd=ramp_dict, sv=speed_val: _done(
                        ok, dst if ok else "", err, speed=sv, ramp_dict=rd
                    ),
                )
            except Exception as e:
                QTimer.singleShot(0, lambda msg=str(e): _done(False, "", msg))

        threading.Thread(target=do_speed, daemon=True).start()

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
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "提示", "请先调整曲线参数"))
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
                    QTimer.singleShot(0, lambda: (
                        self._add_to_clips(dst, 'video'),
                        QMessageBox.information(self, "完成", f"曲线调色完成:\n{dst}")
                    ))
                else:
                    err = result.stderr[-500:]
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"曲线调色失败:\n{err}"))
            except subprocess.TimeoutExpired:
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", "处理超时"))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"处理出错: {err}"))

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

        def _set_beat_lines(lines):
            self._beat_list.clear()
            for line in lines:
                self._beat_list.addItem(line)

        def do_detect():
            lines = []
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
                        from datetime import timedelta
                        for i, beat in enumerate(beats):
                            # 灵敏度过滤：只显示强度足够的节拍
                            threshold = sensitivity / 10.0
                            if beat.intensity >= threshold:
                                ts = str(timedelta(seconds=int(beat.time)))
                                ms = f".{int(beat.time * 100) % 100:02d}"
                                intensity_bar = "█" * int(beat.intensity * 10)
                                lines.append(
                                    f"第{i+1}拍 | {ts}{ms} | {intensity_bar} ({beat.intensity:.1%})"
                                )
                        lines.append(f"━━ 共检测到 {len(beats)} 个节拍点 ━━")
                    else:
                        lines.append("⚠ 未检测到明显节拍，请尝试调整灵敏度")
                    QTimer.singleShot(0, lambda ls=list(lines): _set_beat_lines(ls))
                    return
                except ImportError as e:
                    # 回退到 FFmpeg 基于能量的节拍检测
                    lines = ["使用FFmpeg检测节拍..."]
                    QTimer.singleShot(0, lambda ls=list(lines): _set_beat_lines(ls))

                    ffmpeg = self._get_ffmpeg()
                    # 用 silencedetect 找出音量峰值
                    result = subprocess.run(
                        [ffmpeg, '-y', '-i', src,
                         '-af', f'asplit[a][b];[a]volume=1[b];[b]ametadata=print:key=lavfi.astats.Overall.RMS_level',
                         '-f', 'null', '-'],
                        capture_output=True, text=True, timeout=60,
                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0
                    )
                    lines.append("⚠ 需要安装 numpy/soundfile 库以启用完整节拍检测")
                    lines.append("提示: pip install numpy soundfile")
                    QTimer.singleShot(0, lambda ls=list(lines): _set_beat_lines(ls))
            except Exception as e:
                err = f"❌ 检测失败: {str(e)[:80]}"
                QTimer.singleShot(0, lambda ls=[err]: _set_beat_lines(ls))

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
                        QTimer.singleShot(0, lambda: (
                            self._add_to_clips(dst, 'video'),
                            QMessageBox.information(self, "完成", f"运动跟踪完成:\n{dst}")
                        ))
                    else:
                        err = result.stderr[-500:]
                        QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"跟踪失败:\n{err}"))
                else:
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", "未能检测到足够的运动数据，请尝试其他视频"))
                    try:
                        os.unlink(trf_file)
                    except Exception as _e:
                        logger.warning("操作异常（已忽略）: %s", _e)
            except subprocess.TimeoutExpired:
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", "处理超时"))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"处理出错: {err}"))

        threading.Thread(target=do_track, daemon=True).start()

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
        stickers[idx].update(self._gather_sticker_params_from_ui())
        self._touch_project_dirty()
        self._schedule_preview_refresh()
        self._notify_edit("贴纸参数已更新到预览")

    def _clear_stickers(self):
        """清除所有贴纸。"""
        if hasattr(self, "_active_stickers"):
            self._active_stickers.clear()
        else:
            self._active_stickers = []
        if hasattr(self, "_sticker_list") and self._sticker_list is not None:
            self._sticker_list.clear()
        self._touch_project_dirty()
        self._schedule_preview_refresh()
        self._notify_edit("已清除贴纸")

    def _burn_stickers_if_any(self, video_path: str) -> str:
        """导出后把贴纸烧进成片（实现见 editor_burn）。"""
        from app.modules.lego.editor_burn import burn_stickers_if_any
        return burn_stickers_if_any(self, video_path)


    # ------------------------------------------------------------------
    # 剪辑 Agent 与工具栏真实操作补齐
    # ------------------------------------------------------------------
    def _create_edit_agent_panel(self) -> QWidget:
        """创建剪辑 Agent 对话面板（嵌入右侧工具栏标签页）。"""
        panel = QWidget()
        panel.setObjectName("editAgentPanel")
        panel.setStyleSheet("""
            QWidget#editAgentPanel{background:#0f1117;}
            QLabel{color:#c9d1d9;background:transparent;border:none;}
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("剪辑 Agent")
        title.setStyleSheet("color:#fff;font-size:12px;font-weight:700;")
        head.addWidget(title)
        head.addStretch()

        # 模式切换：Plan 模式 / 执行模式
        mode_label = QLabel("模式")
        mode_label.setStyleSheet("color:#8b949e;font-size:11px;")
        head.addWidget(mode_label)
        self._agent_mode_combo = QComboBox()
        self._agent_mode_combo.addItem("协作 B", "collaborative")
        self._agent_mode_combo.addItem("Plan", "plan")
        self._agent_mode_combo.addItem("自主 C", "autonomous")
        self._agent_mode_combo.setMinimumWidth(100)
        self._agent_mode_combo.setToolTip(
            "Plan：只规划不改时间线；协作 B：只读自动、删除需确认；自主 C：白名单自动执行（付费生成不重试）"
        )
        self._agent_mode_combo.setStyleSheet("""
            QComboBox{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:3px 8px;font-size:11px;}
            QComboBox::drop-down{border:none;width:16px;}
        """)
        head.addWidget(self._agent_mode_combo)

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

        self._agent_active_hint = QLabel("")
        self._agent_active_hint.setStyleSheet("color:#3fb950;font-size:11px;padding-left:4px;")
        head.addWidget(self._agent_active_hint)

        close_btn = QPushButton("收起")
        close_btn.setStyleSheet("QPushButton{background:#2a1f24;color:#ffb4bd;border:1px solid #5c222b;border-radius:6px;padding:4px 10px;font-size:11px;}QPushButton:hover{background:#5c222b;color:#fff;}")
        close_btn.clicked.connect(self._close_agent_tab)
        head.addWidget(close_btn)
        layout.addLayout(head)

        # 多集上下文（Dify 式应用变量，写入 MemoryStore）
        proj_row = QHBoxLayout()
        proj_row.setSpacing(6)
        _pl = "color:#8b949e;font-size:11px;"
        _pe = "QLineEdit{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:4px 8px;font-size:11px;}"
        for text in ("剧名",):
            lb = QLabel(text)
            lb.setStyleSheet(_pl)
            proj_row.addWidget(lb)
        self._agent_drama_edit = QLineEdit()
        self._agent_drama_edit.setPlaceholderText("漫剧名（写入多集记忆）")
        self._agent_drama_edit.setStyleSheet(_pe)
        proj_row.addWidget(self._agent_drama_edit, 2)
        lb_ep = QLabel("集数")
        lb_ep.setStyleSheet(_pl)
        proj_row.addWidget(lb_ep)
        self._agent_episode_edit = QLineEdit()
        self._agent_episode_edit.setPlaceholderText("如 03")
        self._agent_episode_edit.setMaximumWidth(72)
        self._agent_episode_edit.setStyleSheet(_pe)
        proj_row.addWidget(self._agent_episode_edit)
        lb_pf = QLabel("平台")
        lb_pf.setStyleSheet(_pl)
        proj_row.addWidget(lb_pf)
        self._agent_platform_edit = QLineEdit()
        self._agent_platform_edit.setPlaceholderText("douyin")
        self._agent_platform_edit.setMaximumWidth(90)
        self._agent_platform_edit.setStyleSheet(_pe)
        proj_row.addWidget(self._agent_platform_edit)
        save_ctx_btn = QPushButton("保存上下文")
        save_ctx_btn.setStyleSheet(
            "QPushButton{background:#21262d;color:#c9d1d9;border:1px solid #30363d;"
            "border-radius:6px;padding:4px 10px;font-size:11px;}"
            "QPushButton:hover{background:#30363d;}"
        )
        save_ctx_btn.clicked.connect(self._save_agent_project_context)
        proj_row.addWidget(save_ctx_btn)
        layout.addLayout(proj_row)
        self._load_agent_project_context_fields()
        self._subscribe_provider_activated()

        # ── 内容区 QScrollArea（确保内容超出时可滚动）──
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea{background:transparent;border:none;}
            QScrollBar:vertical{background:#0f1117;width:8px;border:none;}
            QScrollBar::handle:vertical{background:#30363d;border-radius:4px;min-height:30px;}
            QScrollBar::handle:vertical:hover{background:#484f58;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
            QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}
        """)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 4, 0, 4)
        scroll_layout.setSpacing(8)

        # ── 左右脑神经链接：🧠 大脑状态条（实时显示神经元/突触/激活统计）──
        self._agent_brain_status_label = QLabel("🧠 大脑初始化中...")
        self._agent_brain_status_label.setStyleSheet(
            "QLabel{background:#1a1030;color:#d2a8ff;border:1px solid #3b1f6f;"
            "border-radius:6px;padding:6px 10px;font-size:11px;}"
        )
        self._agent_brain_status_label.setWordWrap(True)
        scroll_layout.addWidget(self._agent_brain_status_label)
        # 启动时首次刷新 + 定时器周期刷新（每 5 秒）
        QTimer.singleShot(0, self._refresh_agent_brain_status)
        self._agent_brain_refresh_timer = QTimer(self)
        self._agent_brain_refresh_timer.setInterval(5000)
        self._agent_brain_refresh_timer.timeout.connect(self._refresh_agent_brain_status)
        self._agent_brain_refresh_timer.start()

        self._edit_agent_chat = QTextEdit()
        self._edit_agent_chat.setReadOnly(True)
        self._edit_agent_chat.setFixedHeight(72)
        self._edit_agent_chat.setPlaceholderText("Agent 状态和执行结果会显示在这里。")
        self._edit_agent_chat.setStyleSheet("QTextEdit{background:#0d1117;color:#9fb3c8;border:1px solid #21262d;border-radius:8px;padding:6px;font-size:11px;}")
        scroll_layout.addWidget(self._edit_agent_chat)

        # ── 新增 1：执行参数配置卡（P0 痛点1+8）──
        self._build_agent_config_card(scroll_layout)

        # ── 新增 2：进度卡（P0 痛点2）──
        self._build_agent_progress_card(scroll_layout)

        # ── 新增 3：预览问题卡（P1 痛点5）──
        self._build_agent_preview_card(scroll_layout)

        # ── 新增 4：打分结果卡（P1 痛点3）──
        self._build_agent_score_card(scroll_layout)

        # ── 新增 5：剪辑脚本卡（P1 痛点4+6）──
        self._build_agent_script_card(scroll_layout)

        # Plan 模式规划显示区域（默认隐藏）
        self._agent_plan_card = QFrame()
        self._agent_plan_card.setStyleSheet("QFrame{background:#0d1f12;border:1px solid #1f4d2a;border-radius:8px;}")
        self._agent_plan_card.setVisible(False)
        plan_layout = QVBoxLayout(self._agent_plan_card)
        plan_layout.setContentsMargins(10, 8, 10, 10)
        plan_layout.setSpacing(6)

        plan_header = QHBoxLayout()
        plan_title = QLabel("📋 执行规划")
        plan_title.setStyleSheet("color:#7ee787;font-size:12px;font-weight:700;")
        plan_header.addWidget(plan_title)
        plan_header.addStretch()
        plan_layout.addLayout(plan_header)

        self._agent_plan_view = QTextEdit()
        self._agent_plan_view.setReadOnly(True)
        self._agent_plan_view.setMinimumHeight(80)
        self._agent_plan_view.setMaximumHeight(160)
        self._agent_plan_view.setStyleSheet("QTextEdit{background:#0a1a0e;color:#9fb3c8;border:1px solid #1f4d2a;border-radius:6px;padding:6px;font-size:11px;}")
        plan_layout.addWidget(self._agent_plan_view)

        plan_btn_row = QHBoxLayout()
        plan_btn_row.setSpacing(6)
        self._agent_plan_confirm_btn = QPushButton("✅ 确认执行")
        self._agent_plan_confirm_btn.setStyleSheet("QPushButton{background:#238636;color:#fff;border:none;border-radius:6px;padding:6px 14px;font-size:11px;font-weight:600;}QPushButton:hover{background:#2ea043;}")
        self._agent_plan_confirm_btn.clicked.connect(self._confirm_agent_plan)
        plan_btn_row.addWidget(self._agent_plan_confirm_btn)

        self._agent_plan_cancel_btn = QPushButton("取消")
        self._agent_plan_cancel_btn.setStyleSheet("QPushButton{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:6px 14px;font-size:11px;}QPushButton:hover{background:#30363d;}")
        self._agent_plan_cancel_btn.clicked.connect(self._cancel_agent_plan)
        plan_btn_row.addWidget(self._agent_plan_cancel_btn)
        plan_btn_row.addStretch()
        plan_layout.addLayout(plan_btn_row)

        scroll_layout.addWidget(self._agent_plan_card)

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

        # 全链路一键执行按钮（Agent 全量双向闭环：生成→预览→打分→精剪→成片）
        pipeline_row = QHBoxLayout()
        pipeline_row.setSpacing(6)
        pipeline_btn = QPushButton("🚀 全链路执行（生成→预览→打分→精剪→成片）")
        pipeline_btn.setObjectName("edit_agent_pipeline_btn")
        pipeline_btn.setProperty("waiting_preview", False)
        pipeline_btn.setStyleSheet("QPushButton{background:#1f2a3d;color:#7ee787;border:1px solid #2f5139;border-radius:8px;padding:6px 12px;font-size:11px;font-weight:600;}QPushButton:hover{background:#238636;color:#fff;border-color:#238636;}")
        pipeline_btn.clicked.connect(self._on_run_full_pipeline)
        self._edit_agent_pipeline_btn = pipeline_btn  # 保存引用
        pipeline_row.addWidget(pipeline_btn)
        pipeline_row.addStretch()
        interaction_layout.addLayout(pipeline_row)

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

        self._edit_agent_pause_btn = QPushButton("暂停")
        self._edit_agent_pause_btn.setToolTip("暂停任务；点「继续」后才会再跑")
        self._edit_agent_pause_btn.setStyleSheet("QPushButton{background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:8px 12px;font-size:12px;}")
        self._edit_agent_pause_btn.clicked.connect(self._pause_edit_agent_task)
        input_row.addWidget(self._edit_agent_pause_btn)

        self._edit_agent_resume_btn = QPushButton("继续")
        self._edit_agent_resume_btn.setStyleSheet("QPushButton{background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:8px 12px;font-size:12px;}")
        self._edit_agent_resume_btn.clicked.connect(self._resume_edit_agent_task)
        input_row.addWidget(self._edit_agent_resume_btn)

        self._edit_agent_replan_btn = QPushButton("重规划")
        self._edit_agent_replan_btn.setToolTip("切到 Plan 并用上一条指令重新规划")
        self._edit_agent_replan_btn.setStyleSheet("QPushButton{background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:8px 12px;font-size:12px;}")
        self._edit_agent_replan_btn.clicked.connect(self._replan_edit_agent_task)
        input_row.addWidget(self._edit_agent_replan_btn)
        interaction_layout.addLayout(input_row)
        scroll_layout.addWidget(interaction_card)

        # 设置 scrollArea 的 content 并加入主布局
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)

        self._edit_agent_worker = None
        self._edit_agent_stream_buffer = ""
        self._edit_agent_inbox = []
        self._refresh_edit_agent_models()
        self._append_agent_message("Agent", "已就绪。下方输入剪辑需求或点击快捷指令。")

        # 注册统一调用层 handler，传入 EditorModule lazy 引用
        try:
            from app.core.capability_dispatcher import capability_dispatcher
            from app.core.capability_handlers import register_builtin_handlers
            register_builtin_handlers(capability_dispatcher, editor_module_ref=lambda: self)
        except Exception as e:
            logger.warning(f"[Agent] 注册 CapabilityDispatcher 失败: {e}")

        # 画布 HTTP 共享同一 Agent / 拓展面
        try:
            from app.core.project_agent_host import bind_editor_module
            bind_editor_module(self)
        except Exception as e:
            logger.debug("bind project_agent_host: %s", e)

        # 监听反馈可用事件，刷新面板指示
        try:
            from app.modules.lego.core import EventType
            from app.core.agent_feedback_bridge import agent_feedback_bridge
            agent_feedback_bridge.event_bus  # 触发订阅
            self._event_bus.on(EventType.AGENT_FEEDBACK_AVAILABLE, self._on_agent_feedback)
        except Exception as e:
            logger.warning(f"[Agent] 反馈桥初始化失败: {e}")

        # 监听全链路暂停等待预览确认事件
        try:
            self._event_bus.on(EventType.CUSTOM, self._on_pipeline_event)
        except Exception as e:
            logger.warning(f"[Agent] 全链路事件监听初始化失败: {e}")

        return panel

    def _toggle_edit_agent_panel(self, checked=None):
        """切换到剪辑 Agent 标签页（嵌入右侧工具栏，不再使用浮动面板）。"""
        tabs = getattr(self, '_tools_tabs', None)
        if tabs is None:
            QTimer.singleShot(100, lambda: self._toggle_edit_agent_panel(checked))
            return
        agent_idx = getattr(self, '_agent_tab_index', -1)
        if agent_idx < 0:
            return
        tabs.setCurrentIndex(agent_idx)
        # 懒挂载：切页会触发 _on_tools_tab_changed；若信号被挡住则手动确保
        self._on_tools_tab_changed(agent_idx)
        if hasattr(self, '_edit_agent_toggle_btn'):
            self._edit_agent_toggle_btn.setChecked(True)
            self._edit_agent_toggle_btn.setText("🤖 Agent")

    def _close_agent_tab(self):
        """收起 Agent 标签页，切回上一个标签。"""
        tabs = getattr(self, '_tools_tabs', None)
        if tabs is None:
            return
        agent_idx = getattr(self, '_agent_tab_index', -1)
        # 切回"属性"标签页
        if agent_idx > 0:
            tabs.setCurrentIndex(0)
        if hasattr(self, '_edit_agent_toggle_btn'):
            self._edit_agent_toggle_btn.setChecked(False)
            self._edit_agent_toggle_btn.setText("🤖 剪辑 Agent")

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

    def _subscribe_provider_activated(self):
        """模型管理激活变化时刷新 Agent 下拉。"""
        if getattr(self, "_provider_activated_hooked", False):
            return
        try:
            from .core import EventBus, EventType
            bus = EventBus.get_instance()
            bus.on(EventType.PROVIDER_ACTIVATED, self._on_provider_activated_event)
            self._provider_activated_hooked = True
        except Exception as e:
            logger.debug("[Agent] 订阅 PROVIDER_ACTIVATED 失败: %s", e)

    def _on_provider_activated_event(self, event):
        try:
            self._refresh_edit_agent_models()
        except Exception as e:
            logger.debug("[Agent] 激活事件刷新模型失败: %s", e)

    def _load_agent_project_context_fields(self):
        try:
            from app.core.memory_store import memory_store
            ctx = memory_store.get_project_context() or {}
            if getattr(self, "_agent_drama_edit", None) is not None:
                self._agent_drama_edit.setText(str(ctx.get("drama_title") or ""))
            if getattr(self, "_agent_episode_edit", None) is not None:
                self._agent_episode_edit.setText(str(ctx.get("episode") or ""))
            if getattr(self, "_agent_platform_edit", None) is not None:
                self._agent_platform_edit.setText(str(ctx.get("platform") or ""))
        except Exception:
            pass

    def _save_agent_project_context(self):
        try:
            from app.core.memory_store import memory_store
            title = self._agent_drama_edit.text().strip() if getattr(self, "_agent_drama_edit", None) else ""
            episode = self._agent_episode_edit.text().strip() if getattr(self, "_agent_episode_edit", None) else ""
            platform = self._agent_platform_edit.text().strip() if getattr(self, "_agent_platform_edit", None) else ""
            memory_store.set_project_context(
                drama_title=title,
                episode=episode,
                platform=platform,
                notes="",
            )
            self._append_agent_message(
                "系统",
                f"已保存多集上下文：{title or '（无剧名）'} / 第{episode or '?'}集 / {platform or '未指定平台'}",
            )
        except Exception as e:
            QMessageBox.warning(self, "多集上下文", f"保存失败: {e}")

    def _persist_agent_project_context_silent(self):
        """发送指令前静默把输入框写入记忆，避免用户忘点保存。"""
        try:
            from app.core.memory_store import memory_store
            title = ""
            episode = ""
            platform = ""
            if getattr(self, "_agent_drama_edit", None) is not None:
                title = self._agent_drama_edit.text().strip()
            if getattr(self, "_agent_episode_edit", None) is not None:
                episode = self._agent_episode_edit.text().strip()
            if getattr(self, "_agent_platform_edit", None) is not None:
                platform = self._agent_platform_edit.text().strip()
            if title or episode or platform:
                memory_store.set_project_context(
                    drama_title=title,
                    episode=episode,
                    platform=platform,
                )
        except Exception:
            pass

    def _refresh_edit_agent_models(self):
        """加载可用 Provider 到 Agent 模型框；优先选中「模型管理」当前激活项。"""
        combo = getattr(self, '_edit_agent_model_combo', None)
        if combo is None:
            return
        combo.clear()
        try:
            from app.modules.lego.model_config import (
                PROVIDERS,
                ensure_active_provider_sensible,
                load_active_provider,
            )
            ensure_active_provider_sensible()
        except Exception:
            PROVIDERS = {}
            load_active_provider = lambda: ""  # noqa: E731

        try:
            from app.core.ai_engine import ai_engine
            available = set(ai_engine.get_available_providers() or [])
        except Exception:
            available = set()

        try:
            from app.modules.lego.cloud_api import cloud_api_service
        except Exception:
            cloud_api_service = None

        active = ""
        try:
            active = load_active_provider() or ""
        except Exception:
            active = ""

        # 排序：激活 > 已配置可用云端 > 其余
        entries = []
        for provider, cfg in PROVIDERS.items():
            name = cfg.get("name", provider)
            is_local = bool(cfg.get("is_local"))
            configured = False
            if is_local:
                configured = provider in available
            elif cloud_api_service is not None:
                try:
                    configured = bool(cloud_api_service.is_configured(provider))
                except Exception:
                    configured = provider in available
            models = list(cfg.get("models") or [])
            if provider == "ollama":
                models = self._list_local_ollama_models() or (["auto"] if configured else [])
            if not configured and not models:
                continue
            if not models:
                models = [""]
            for model in models:
                # 跳过未配置的云端（避免默认点到空 Key）
                if not is_local and not configured:
                    continue
                label = f"{name} / {model}" if model and model != "auto" else f"{name} / 自动"
                if provider == active:
                    label = "★ " + label
                if configured or provider in available:
                    label = label + " ✓"
                entries.append((provider == active, configured or provider in available, provider, model, label))

        entries.sort(key=lambda x: (0 if x[0] else 1, 0 if x[1] else 1, x[2], x[3] or ""))

        select_idx = 0
        for i, (_is_active, _ok, provider, model, label) in enumerate(entries):
            combo.addItem(label, (provider, "" if model == "auto" else model))
            if _is_active and select_idx == 0:
                select_idx = i
            elif active and provider == active and model and select_idx == 0:
                select_idx = i

        if combo.count() == 0:
            combo.addItem("自动降级 / 可用模型", ("", ""))
        else:
            # 若激活项在列表中，选中它；否则选第一个已配置项
            if active:
                for i in range(combo.count()):
                    data = combo.itemData(i)
                    if isinstance(data, tuple) and data[0] == active:
                        select_idx = i
                        break
            combo.setCurrentIndex(min(select_idx, combo.count() - 1))

        hint = getattr(self, "_agent_active_hint", None)
        if hint is not None:
            try:
                name = (PROVIDERS.get(active) or {}).get("name") or active or "未激活"
                hint.setText(f"激活:{name}")
            except Exception:
                hint.setText("")

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

    def _refresh_agent_brain_status(self):
        """刷新 🧠 大脑状态条：显示神经元总数、左右脑分布、突触数与最强链路。

        - 失败时静默降级为占位文本，不影响 Agent 面板其它功能
        - 数据来自 AgentBrain.get_brain_status()，无副作用
        """
        label = getattr(self, '_agent_brain_status_label', None)
        if label is None:
            return
        try:
            from app.core.agent_brain import agent_brain
            status = agent_brain.get_brain_status()
            total_n = status.get("total_neurons", 0)
            right_n = status.get("right_brain_count", 0)
            left_n = status.get("left_brain_count", 0)
            cc_n = status.get("cc_count", 0)
            total_s = status.get("total_synapses", 0)
            active = status.get("active_neurons", []) or []
            top_syns = status.get("top_synapses", []) or []

            # 拼装主状态行
            main = (f"🧠 神经元 {total_n} | 🌐 左脑 {left_n} / 右脑 {right_n} / 胼胝体 {cc_n}"
                    f" | 🔗 突触 {total_s} | ⚡ 激活 {len(active)}")
            # 拼装最强链路（最多 2 条，避免占屏）
            links = []
            for s in top_syns[:2]:
                pre = s.get("pre", "")
                post = s.get("post", "")
                w = s.get("weight", 0.0)
                try:
                    w_pct = int(float(w) * 100)
                except (TypeError, ValueError):
                    w_pct = 0
                links.append(f"{pre}→{post}({w_pct}%)")
            link_text = " | 强链路: " + " / ".join(links) if links else ""
            label.setText(main + link_text)
        except Exception as e:
            # 静默降级，避免阻塞 UI 刷新定时器
            label.setText(f"🧠 大脑状态不可用: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # Agent 新增：配置卡 / 进度卡 / 预览问题卡 / 打分卡 / 脚本卡 构建方法
    # ═══════════════════════════════════════════════════════════════════════

    # Agent 全链路 6+ 主阶段映射（用于进度条）
    _PIPELINE_STAGES = [
        ("routing",           "🔀", "智能业务分流",   5),
        ("generation",        "🎬", "AI 视频生成",    25),
        ("import_parsing",    "📥", "素材解析",        25),
        ("preview",           "🔍", "预览校验",        40),
        ("scoring",           "📊", "五维打分",        55),
        ("scripting",         "📝", "剪辑脚本",        70),
        ("editing",           "✂️", "精剪成片",        85),
        ("done",              "✅", "完成",           100),
    ]

    def _stage_progress(self, stage: str) -> int:
        """把 stage 字符串映射到 0-100 进度槽位。"""
        for s, _, _, pct in self._PIPELINE_STAGES:
            if s == stage:
                return pct
        if stage == "waiting_for_preview_confirmation":
            return 40
        if stage == "error":
            return 0
        return 0

    def _stage_label(self, stage: str) -> str:
        """把 stage 字符串映射为带 emoji 的标签文本。"""
        for s, emoji, label, _ in self._PIPELINE_STAGES:
            if s == stage:
                return f"{emoji} {label}"
        if stage == "waiting_for_preview_confirmation":
            return "⏸️ 等待预览确认"
        if stage == "error":
            return "❌ 执行失败"
        return "⚙️ 执行中"

    # ───────────────── 配置卡（P0 痛点1+8） ─────────────────

    def _build_agent_config_card(self, parent_layout: QVBoxLayout):
        """构造参数配置卡（平台 / 目标时长 / 单段时长 / Provider 选择）。"""
        card = QFrame()
        card.setObjectName("agentConfigCard")
        card.setStyleSheet("""
            QFrame#agentConfigCard{background:#111722;border:1px solid #263244;border-radius:10px;}
            QLabel{color:#8b949e;font-size:11px;}
            QComboBox{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:4px 8px;font-size:11px;}
            QComboBox::drop-down{border:none;width:18px;}
            QDoubleSpinBox{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:4px 8px;font-size:11px;}
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        t = QLabel("⚙️ 全链路执行参数")
        t.setStyleSheet("color:#e6edf3;font-size:12px;font-weight:700;")
        head.addWidget(t)
        head.addStretch()
        toggle = QPushButton("收起")
        toggle.setFixedHeight(24)
        toggle.setStyleSheet(
            "QPushButton{background:#21262d;color:#c9d1d9;border:1px solid #30363d;"
            "border-radius:6px;padding:2px 10px;font-size:11px;}"
            "QPushButton:hover{background:#30363d;}"
        )
        head.addWidget(toggle)
        lay.addLayout(head)

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        # Row 1：平台 + 目标时长
        lbl1 = QLabel("平台")
        self._agent_platform_combo = QComboBox()
        self._agent_platform_combo.addItem("抖音", "douyin")
        self._agent_platform_combo.addItem("快手", "kuaishou")
        self._agent_platform_combo.addItem("B站", "bilibili")
        self._agent_platform_combo.addItem("小红书", "xiaohongshu")
        self._agent_platform_combo.setCurrentIndex(0)
        grid.addWidget(lbl1, 0, 0)
        grid.addWidget(self._agent_platform_combo, 0, 1)

        lbl2 = QLabel("目标时长")
        self._agent_duration_combo = QComboBox()
        self._agent_duration_combo.addItem("15秒", 15.0)
        self._agent_duration_combo.addItem("30秒", 30.0)
        self._agent_duration_combo.addItem("60秒", 60.0)
        self._agent_duration_combo.addItem("90秒", 90.0)
        self._agent_duration_combo.setCurrentIndex(1)  # 默认30秒
        grid.addWidget(lbl2, 0, 2)
        grid.addWidget(self._agent_duration_combo, 0, 3)

        # Row 2：单段时长 + Provider
        lbl3 = QLabel("单段时长")
        self._agent_clip_duration_spin = QDoubleSpinBox()
        self._agent_clip_duration_spin.setRange(0.5, 10.0)
        self._agent_clip_duration_spin.setSingleStep(0.5)
        self._agent_clip_duration_spin.setValue(5.0)
        self._agent_clip_duration_spin.setSuffix(" 秒")
        grid.addWidget(lbl3, 1, 0)
        grid.addWidget(self._agent_clip_duration_spin, 1, 1)

        lbl4 = QLabel("Provider")
        self._agent_provider_combo = QComboBox()
        self._agent_provider_combo.addItem("Auto（自动）", "auto")
        self._agent_provider_combo.addItem("Seedance", "seedance")
        self._agent_provider_combo.addItem("CogVideo", "cogvideo")
        self._agent_provider_combo.addItem("本地占位", "local")
        self._agent_provider_combo.setCurrentIndex(0)
        grid.addWidget(lbl4, 1, 2)
        grid.addWidget(self._agent_provider_combo, 1, 3)
        body_lay.addLayout(grid)

        # Provider 状态警告
        self._agent_provider_status_lbl = QLabel("")
        self._agent_provider_status_lbl.setStyleSheet("color:#7ee787;font-size:10px;")
        self._agent_provider_status_lbl.setWordWrap(True)
        body_lay.addWidget(self._agent_provider_status_lbl)
        self._agent_provider_combo.currentIndexChanged.connect(self._refresh_provider_status)
        lay.addWidget(body)

        def _toggle_config():
            visible = body.isVisible()
            body.setVisible(not visible)
            toggle.setText("展开" if visible else "收起")

        toggle.clicked.connect(_toggle_config)

        parent_layout.addWidget(card)

        # 首次加载时刷新 provider 状态
        QTimer.singleShot(300, self._refresh_provider_status)

    def _get_pipeline_params(self) -> Dict[str, Any]:
        """从配置卡收集 pipeline.run_full 参数（UI 层只读）。"""
        p = getattr(self, "_agent_platform_combo", None)
        d = getattr(self, "_agent_duration_combo", None)
        c = getattr(self, "_agent_clip_duration_spin", None)
        pv = getattr(self, "_agent_provider_combo", None)
        return {
            "platform": p.currentData() if p else "douyin",
            "target_duration": float(d.currentData() if d else 30.0),
            "clip_duration": float(c.value() if c else 5.0),
            "provider": pv.currentData() if pv else "auto",
        }

    def _refresh_provider_status(self):
        """刷新 provider 可用性状态标签（只读查询，不修改 client）。"""
        lbl = getattr(self, "_agent_provider_status_lbl", None)
        if lbl is None:
            return
        try:
            from app.core.ai.video_generation_client import video_generation_client
            chosen = self._agent_provider_combo.currentData() if hasattr(self, "_agent_provider_combo") else "auto"
            providers = video_generation_client.list_providers()
            # 注意：list_providers 返回 dict 列表，不是对象
            cloud_ok = False
            cloud_names = []
            for p in providers:
                pid = p.get("id", "")
                if pid in ("seedance", "cogvideo") and p.get("available", False):
                    cloud_ok = True
                    cloud_names.append(pid.upper())
            if chosen == "auto":
                if cloud_ok:
                    lbl.setText(f"✔ 云端可用: {', '.join(cloud_names)}")
                    lbl.setStyleSheet("color:#7ee787;font-size:10px;")
                else:
                    lbl.setText("⚠ 云端 Provider 全部不可用，将回退本地色块占位生成")
                    lbl.setStyleSheet("color:#ff7b72;font-size:10px;font-weight:700;")
            elif chosen == "local":
                lbl.setText("使用本地占位色块生成（无需网络）")
                lbl.setStyleSheet("color:#7ee787;font-size:10px;")
            else:
                chosen_obj = next((x for x in providers if x.get("id") == chosen), None)
                if chosen_obj and chosen_obj.get("available", False):
                    lbl.setText(f"✔ {chosen.upper()} 可用")
                    lbl.setStyleSheet("color:#7ee787;font-size:10px;")
                else:
                    lbl.setText(f"⚠ {chosen.upper()} 不可用，将回退本地色块")
                    lbl.setStyleSheet("color:#ff7b72;font-size:10px;font-weight:700;")
        except Exception as e:
            logger.debug(f"[Agent] provider 状态刷新失败: {e}")
            lbl.setText("")

    # ───────────────── 进度卡（P0 痛点2） ─────────────────

    def _build_agent_progress_card(self, parent_layout: QVBoxLayout):
        """构造执行进度卡（阶段进度条 + stage 标签 + 细节）。"""
        card = QFrame()
        card.setObjectName("agentProgressCard")
        card.setStyleSheet("""
            QFrame#agentProgressCard{background:#0d1117;border:1px solid #21262d;border-radius:10px;}
            QProgressBar{background:#161b22;border:1px solid #30363d;border-radius:4px;text-align:center;height:8px;}
            QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #1f6feb,stop:1 #7ee787);border-radius:4px;}
            QLabel#stageMain{color:#e6edf3;font-size:12px;font-weight:700;}
            QLabel#stageDetail{color:#8b949e;font-size:11px;}
        """)
        card.setVisible(False)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._agent_stage_label = QLabel("")
        self._agent_stage_label.setObjectName("stageMain")
        head.addWidget(self._agent_stage_label)
        head.addStretch()
        lay.addLayout(head)

        self._agent_stage_bar = QProgressBar()
        self._agent_stage_bar.setRange(0, 100)
        self._agent_stage_bar.setValue(0)
        self._agent_stage_bar.setTextVisible(False)
        self._agent_stage_bar.setFixedHeight(8)
        lay.addWidget(self._agent_stage_bar)

        self._agent_stage_detail = QLabel("")
        self._agent_stage_detail.setObjectName("stageDetail")
        self._agent_stage_detail.setWordWrap(True)
        self._agent_stage_detail.setMaximumHeight(40)
        lay.addWidget(self._agent_stage_detail)

        self._agent_progress_card = card
        parent_layout.addWidget(card)

    def _update_pipeline_stage(self, stage: str, message: str = ""):
        """根据 stage 更新进度卡（UI 层只渲染，不参与调度）。"""
        card = getattr(self, "_agent_progress_card", None)
        bar = getattr(self, "_agent_stage_bar", None)
        lbl = getattr(self, "_agent_stage_label", None)
        det = getattr(self, "_agent_stage_detail", None)
        if card is None or bar is None or lbl is None:
            return
        card.setVisible(True)
        pct = self._stage_progress(stage)
        if pct > 0:
            # 允许进度条只前进不回退
            if pct >= bar.value():
                bar.setValue(pct)
        lbl.setText(self._stage_label(stage))
        if det is not None and message:
            det.setText(message[:120])

    def _finalize_pipeline_stage(self, success: bool, error: str = "", degraded: bool = False):
        """完成时把进度条置 100%（或失败为红色；降级为琥珀色文案）。"""
        bar = getattr(self, "_agent_stage_bar", None)
        lbl = getattr(self, "_agent_stage_label", None)
        det = getattr(self, "_agent_stage_detail", None)
        if bar is None:
            return
        if success and not degraded:
            bar.setValue(100)
            if lbl:
                lbl.setText("✅ 执行完成")
            if det:
                det.setText(error or "")
        elif success and degraded:
            bar.setValue(100)
            if lbl:
                lbl.setText("⚠️ 降级完成（无成片）")
            if det:
                det.setText((error or "仅有脚本/中间结果")[:120])
        else:
            bar.setStyleSheet("QProgressBar{background:#161b22;border:1px solid #30363d;border-radius:4px;height:8px;}"
                              "QProgressBar::chunk{background:#ff7b72;border-radius:4px;}")
            bar.setValue(100)
            if lbl:
                lbl.setText("❌ 执行失败")
            if det:
                det.setText(error[:120] if error else "")

    # ───────────────── 预览问题卡（P1 痛点5 保守版） ─────────────────

    def _build_agent_preview_card(self, parent_layout: QVBoxLayout):
        """构造预览问题卡（保守版：只显示失败片段 clip_id）。"""
        card = QFrame()
        card.setObjectName("agentPreviewCard")
        card.setStyleSheet("QFrame#agentPreviewCard{background:#1b1405;border:1px solid #8b6914;border-radius:10px;}")
        card.setVisible(False)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(4)

        head = QHBoxLayout()
        t = QLabel("⏸ 预览问题片段")
        t.setStyleSheet("color:#f0b429;font-size:12px;font-weight:700;")
        head.addWidget(t)
        head.addStretch()
        self._agent_preview_count_lbl = QLabel("")
        self._agent_preview_count_lbl.setStyleSheet("color:#8b949e;font-size:10px;")
        head.addWidget(self._agent_preview_count_lbl)
        lay.addLayout(head)

        self._agent_preview_list = QListWidget()
        self._agent_preview_list.setFixedHeight(80)
        self._agent_preview_list.setStyleSheet(
            "QListWidget{background:#0f1117;color:#c9d1d9;border:1px solid #21262d;border-radius:6px;font-size:11px;}"
            "QListWidget::item{padding:3px 6px;}")
        lay.addWidget(self._agent_preview_list)

        self._agent_preview_card = card
        parent_layout.addWidget(card)

    def _render_preview_issues(self, failed_clips: List[Dict[str, Any]]):
        """渲染预览失败片段列表（保守版：clip_id）。"""
        lst = getattr(self, "_agent_preview_list", None)
        card = getattr(self, "_agent_preview_card", None)
        clbl = getattr(self, "_agent_preview_count_lbl", None)
        if lst is None or card is None:
            return
        lst.clear()
        if not failed_clips:
            card.setVisible(False)
            return
        for c in failed_clips:
            cid = c.get("clip_id") or c.get("id", "?")
            path = c.get("path", "")
            short_path = os.path.basename(path) if path else ""
            text = f"🔴 {cid}   {short_path}"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, c)
            lst.addItem(it)
        if clbl:
            clbl.setText(f"共 {len(failed_clips)} 个片段")
        card.setVisible(True)

    # ───────────────── 打分结果卡（P1 痛点3） ─────────────────

    def _build_agent_score_card(self, parent_layout: QVBoxLayout):
        """构造五维打分结果卡。"""
        card = QFrame()
        card.setObjectName("agentScoreCard")
        card.setStyleSheet("QFrame#agentScoreCard{background:#0d1217;border:1px solid #1f4d7a;border-radius:10px;}")
        card.setVisible(False)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(4)

        head = QHBoxLayout()
        t = QLabel("📊 五维打分结果")
        t.setStyleSheet("color:#58a6ff;font-size:12px;font-weight:700;")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)

        self._agent_score_list = QListWidget()
        self._agent_score_list.setFixedHeight(110)
        self._agent_score_list.setStyleSheet(
            "QListWidget{background:#0f1117;color:#c9d1d9;border:1px solid #21262d;border-radius:6px;font-size:11px;}"
            "QListWidget::item{padding:4px 8px;}")
        lay.addWidget(self._agent_score_list)

        self._agent_score_card = card
        parent_layout.addWidget(card)

    def _render_score_results(self, scored_results: List[Dict[str, Any]]):
        """把五维打分结果渲染到打分卡。"""
        lst = getattr(self, "_agent_score_list", None)
        card = getattr(self, "_agent_score_card", None)
        if lst is None or card is None:
            return
        lst.clear()
        if not scored_results:
            card.setVisible(False)
            return
        grade_color = {"S": "#ffd700", "A": "#7ee787", "B": "#d29922", "C": "#fb8500", "D": "#ff7b72"}
        for idx, sc in enumerate(scored_results, 1):
            grade = sc.get("grade", "C")
            color = grade_color.get(grade, "#c9d1d9")
            score = sc.get("weighted_score", 0.0)
            cid = sc.get("clip_id", f"#{idx}")
            drop = sc.get("should_drop", False)
            dims = sc.get("dimensions", {}) or {}
            q = dims.get("画面质量", dims.get("visual_quality", 0))
            n = dims.get("高光叙事价值", dims.get("narrative_highlight",
                  dims.get("narrative_value", 0)))
            s_ = dims.get("文案匹配度", dims.get("copy_match", 0))
            b = dims.get("BGM适配度", dims.get("bgm_match",
                  dims.get("bgm_fit", 0)))
            d_ = dims.get("镜头时长合理性", dims.get("shot_duration",
                   dims.get("duration_reasonable", 0)))
            drop_tag = "  ⚠️ 已剔除" if drop else ""
            # 修复：缺 quality_scores 时各维度用固定 70 分基线填充（避免误判 D
            # 级），但此前 UI 完全不标注，用户会把基线分当成真实 AI 质检结果。
            estimated = sc.get("estimated_dims") or []
            est_tag = f'  <span style="color:#d29922;">（{len(estimated)}/5维为估算基线）</span>' if estimated else ""
            html = (f'<span style="color:{color};font-weight:800;">[{grade}]</span> '
                    f'<span style="color:#e6edf3;">镜头{idx} {cid}</span>  '
                    f'<span style="color:{color};font-weight:700;">{score:.1f}分</span>  '
                    f'<span style="color:#8b949e;">(画面{q:.0f}/叙事{n:.0f}/文案{s_:.0f}/BGM{b:.0f}/时长{d_:.0f})</span>'
                    f'<span style="color:#ff7b72;">{drop_tag}</span>{est_tag}')
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, sc)
            lbl = QLabel(html)
            lbl.setStyleSheet("background:transparent;")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lst.addItem(it)
            lst.setItemWidget(it, lbl)
            it.setSizeHint(lbl.sizeHint())
        card.setVisible(True)

    # ───────────────── 脚本结果卡（P1 痛点4+6） ─────────────────

    def _build_agent_script_card(self, parent_layout: QVBoxLayout):
        """构造剪辑脚本结果卡（HTML 渲染 + 复制/导出/一键手动精剪）。"""
        card = QFrame()
        card.setObjectName("agentScriptCard")
        card.setStyleSheet("QFrame#agentScriptCard{background:#101810;border:1px solid #1f4d2a;border-radius:10px;}")
        card.setVisible(False)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        t = QLabel("📝 剪辑创意脚本")
        t.setStyleSheet("color:#7ee787;font-size:12px;font-weight:700;")
        head.addWidget(t)
        head.addStretch()

        self._agent_copy_script_btn = QPushButton("📋 复制")
        self._agent_copy_script_btn.setStyleSheet(
            "QPushButton{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:3px 10px;font-size:10px;}"
            "QPushButton:hover{background:#1e6bde;color:#fff;}")
        self._agent_copy_script_btn.clicked.connect(self._on_copy_script_clicked)
        head.addWidget(self._agent_copy_script_btn)

        self._agent_export_script_btn = QPushButton("📁 导出")
        self._agent_export_script_btn.setStyleSheet(
            "QPushButton{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:3px 10px;font-size:10px;}"
            "QPushButton:hover{background:#1e6bde;color:#fff;}")
        self._agent_export_script_btn.clicked.connect(self._on_export_script_clicked)
        head.addWidget(self._agent_export_script_btn)
        lay.addLayout(head)

        self._agent_script_view = QTextEdit()
        self._agent_script_view.setReadOnly(True)
        self._agent_script_view.setFixedHeight(130)
        self._agent_script_view.setStyleSheet(
            "QTextEdit{background:#0a1a0e;color:#9fb3c8;border:1px solid #1f4d2a;border-radius:6px;padding:6px;font-size:11px;}")
        lay.addWidget(self._agent_script_view)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._agent_manual_edit_btn = QPushButton("▶ 一键手动精剪")
        self._agent_manual_edit_btn.setStyleSheet(
            "QPushButton{background:#1f6feb;color:#fff;border:1px solid #388bfd;border-radius:8px;padding:5px 14px;font-size:11px;font-weight:700;}"
            "QPushButton:hover{background:#388bfd;}"
            "QPushButton:disabled{background:#1b1f24;color:#555;border-color:#2a2f36;}")
        self._agent_manual_edit_btn.clicked.connect(self._on_manual_edit_clicked)
        btn_row.addWidget(self._agent_manual_edit_btn)
        lay.addLayout(btn_row)

        self._agent_script_card = card
        parent_layout.addWidget(card)
        self._last_editing_script: Optional[Dict[str, Any]] = None

    def _render_editing_script(self, script: Optional[Dict[str, Any]]):
        """渲染剪辑脚本到脚本卡。"""
        view = getattr(self, "_agent_script_view", None)
        card = getattr(self, "_agent_script_card", None)
        if view is None or card is None:
            return
        if not script:
            card.setVisible(False)
            return
        self._last_editing_script = script
        platform = script.get("platform", "-")
        target_dur = script.get("target_duration", "-")
        pacing = script.get("pacing", "-")
        clip_order = script.get("clip_order", []) or []
        transitions = script.get("transitions", {}) or {}
        beat_pts = script.get("beat_points", []) or []
        bgm = script.get("bgm_style", script.get("bgm", ""))
        dropped = script.get("dropped_clips", []) or []
        rationale = script.get("rationale", "")

        # 镜头序列
        seq_html = []
        for i, item in enumerate(clip_order, 1):
            cid = item.get("clip_id") or item.get("id", f"#{i}")
            dur = item.get("duration", "")
            grade = item.get("grade", "")
            tr = transitions.get(cid, transitions.get(str(i-1), ""))
            color = {"S": "#ffd700", "A": "#7ee787", "B": "#d29922", "C": "#fb8500", "D": "#ff7b72"}.get(grade, "#58a6ff")
            grade_tag = f' <span style="color:{color};font-weight:700;">[{grade}]</span>' if grade else ""
            dur_tag = f' <span style="color:#8b949e;">{dur}s</span>' if dur else ""
            tr_tag = f' <span style="color:#d29922;">→ {tr}</span>' if tr and i < len(clip_order) else ""
            seq_html.append(f'<span style="color:#e6edf3;">{i}. {cid}</span>{grade_tag}{dur_tag}{tr_tag}')
        seq_text = "<br>".join(seq_html) or '<span style="color:#8b949e;">(空)</span>'

        # 卡点
        beat_text = ", ".join([f"{b:.1f}s" for b in beat_pts]) if beat_pts else '<span style="color:#8b949e;">(无)</span>'
        # 剔除
        dropped_text = ", ".join(dropped) if dropped else '<span style="color:#8b949e;">(无)</span>'

        html = f"""
        <div style="font-family:微软雅黑;font-size:11px;line-height:1.5;">
          <div><b style="color:#7ee787;">平台：</b>{platform} &nbsp;
               <b style="color:#7ee787;">时长：</b>{target_dur}s &nbsp;
               <b style="color:#7ee787;">节奏：</b>{pacing}</div>
          {'<div><b style="color:#7ee787;">创意说明：</b><span style="color:#9fb3c8;">'+rationale+'</span></div>' if rationale else ''}
          <div><b style="color:#7ee787;">镜头顺序（{len(clip_order)}）：</b></div>
          <div style="padding:4px 0;">{seq_text}</div>
          <div><b style="color:#7ee787;">卡点：</b><span style="color:#9fb3c8;">{beat_text}</span></div>
          <div><b style="color:#7ee787;">配乐风格：</b><span style="color:#9fb3c8;">{bgm or '未选择'}</span></div>
          <div><b style="color:#ff7b72;">已剔除镜头：</b><span style="color:#ff7b72;">{dropped_text}</span></div>
        </div>
        """
        view.setHtml(html)
        card.setVisible(True)

    def _on_copy_script_clicked(self):
        """复制当前剪辑脚本为 JSON 到剪贴板。"""
        script = getattr(self, "_last_editing_script", None)
        if not script:
            QMessageBox.information(self, "复制脚本", "暂无可用的剪辑脚本。")
            return
        try:
            import json
            text = json.dumps(script, ensure_ascii=False, indent=2)
            QApplication.clipboard().setText(text)
            self._append_agent_message("系统", "剪辑脚本 JSON 已复制到剪贴板。")
        except Exception as e:
            QMessageBox.warning(self, "复制失败", str(e))

    def _on_export_script_clicked(self):
        """导出当前剪辑脚本到 JSON 文件（父窗口传 self，符合 PyQt6 弹窗铁律）。"""
        script = getattr(self, "_last_editing_script", None)
        if not script:
            QMessageBox.information(self, "导出脚本", "暂无可用的剪辑脚本。")
            return
        try:
            import json
            path, _ = QFileDialog.getSaveFileName(
                self, "导出剪辑脚本", "editing_script.json", "JSON Files (*.json)"
            )
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                json.dump(script, f, ensure_ascii=False, indent=2)
            self._append_agent_message("系统", f"剪辑脚本已导出：{path}")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _on_manual_edit_clicked(self):
        """一键手动精剪：调用既有 pipeline.execute_editing 能力。"""
        script = getattr(self, "_last_editing_script", None)
        if not script:
            QMessageBox.information(self, "手动精剪", "暂无可用的剪辑脚本。")
            return
        btn = getattr(self, "_agent_manual_edit_btn", None)
        if btn is not None:
            btn.setEnabled(False)
        try:
            self._append_agent_message("Agent", "▶ 开始手动精剪（应用转场/字幕/配乐）...")
            from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest
            res = capability_dispatcher.invoke(CapabilityRequest(
                capability_id="pipeline.execute_editing",
                params={"editing_script": script, "session_id": ""},
                caller="agent_manual_edit",
            ))
            if res.success:
                out = res.output or {}
                final = out.get("final_video_path", "")
                if final and os.path.exists(final):
                    self._append_agent_message("Agent", f"✅ 手动精剪完成！成片：\n{final}")
                else:
                    msg = out.get("message", "已执行精剪")
                    self._append_agent_message("Agent", f"✅ 精剪执行完成：{msg}")
            else:
                self._append_agent_message("Agent", f"❌ 精剪执行失败：{res.error}")
        except Exception as e:
            logger.exception("[Agent] 手动精剪按钮异常")
            self._append_agent_message("Agent", f"❌ 精剪执行异常: {e}")
        finally:
            if btn is not None:
                btn.setEnabled(True)

    # ═══════════════════════════════════════════════════════════════════════

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
            user_text = self._edit_agent_input.text().strip()
            if user_text:
                inbox = getattr(self, "_edit_agent_inbox", None)
                if inbox is None:
                    self._edit_agent_inbox = []
                    inbox = self._edit_agent_inbox
                inbox.append(user_text)
                self._edit_agent_input.clear()
                self._append_agent_message("系统", f"已排队（串行）：{user_text[:80]}")
            else:
                QMessageBox.information(self, "剪辑 Agent", "Agent 正在处理中，可点「暂停/终止」或等待完成后自动发送队列。")
            return
        user_text = self._edit_agent_input.text().strip()
        if not user_text:
            QMessageBox.warning(self, "剪辑 Agent", "请输入剪辑指令")
            return

        from app.core.agent_context import compress_messages
        from app.core.agent_session import agent_sessions
        from app.core.agent_task_store import agent_tasks

        ok_round, err_round = agent_sessions.begin_model_round("editor")
        if not ok_round:
            QMessageBox.warning(self, "剪辑 Agent", err_round)
            return

        provider, model = self._get_selected_edit_agent_model()
        self._persist_agent_project_context_silent()
        messages = compress_messages(self._build_edit_agent_messages(user_text))
        task = agent_tasks.create(
            session_id="editor",
            goal=user_text,
            mode=self._get_agent_session_mode(),
            source="editor",
        )
        self._edit_agent_task_id = task.get("id")
        try:
            agent_tasks.transition(task["id"], "running")
        except Exception:
            pass
        self._append_agent_message("你", user_text)
        using = provider or "自动降级"
        if model:
            using = f"{using}/{model}"
        self._append_agent_message("Agent", f"正在用 {using} 分析并生成剪辑指令...")
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

    def _pause_edit_agent_task(self):
        from app.core.agent_session import agent_sessions
        from app.core.agent_task_store import agent_tasks

        agent_sessions.pause("editor")
        tid = getattr(self, "_edit_agent_task_id", "") or ""
        if tid:
            try:
                agent_tasks.transition(tid, "paused", pausedReason="user")
            except Exception:
                pass
        worker = getattr(self, "_edit_agent_worker", None)
        if worker and worker.isRunning():
            worker.request_stop()
        stop_btn = getattr(self, "_edit_agent_stop_btn", None)
        if stop_btn is not None:
            stop_btn.setEnabled(False)
        self._append_agent_message("系统", "任务已暂停。点「继续」解除暂停后再发送。")

    def _resume_edit_agent_task(self):
        from app.core.agent_session import agent_sessions
        from app.core.agent_task_store import agent_tasks

        agent_sessions.resume("editor")
        tid = getattr(self, "_edit_agent_task_id", "") or ""
        if tid:
            try:
                agent_tasks.transition(tid, "running")
            except Exception:
                pass
        self._append_agent_message("系统", "已继续。可以发送下一条或等待队列。")

    def _replan_edit_agent_task(self):
        combo = getattr(self, "_agent_mode_combo", None)
        if combo is not None:
            idx = combo.findData("plan")
            if idx >= 0:
                combo.setCurrentIndex(idx)
        last = getattr(self, "_edit_agent_last_user_text", "") or ""
        if last:
            self._fill_edit_agent_prompt(last)
        self._append_agent_message("系统", "已切 Plan。确认输入后发送以重新规划。")

    def _stop_edit_agent_message(self):
        """终止当前剪辑 Agent 输出。"""
        from app.core.agent_session import agent_sessions
        from app.core.agent_task_store import agent_tasks

        agent_sessions.stop("editor")
        tid = getattr(self, "_edit_agent_task_id", "") or ""
        if tid:
            try:
                agent_tasks.transition(tid, "stopped")
            except Exception:
                pass
        worker = getattr(self, '_edit_agent_worker', None)
        if worker and worker.isRunning():
            worker.request_stop()
            self._append_agent_message("系统", "已请求终止当前输出。")
        stop_btn = getattr(self, "_edit_agent_stop_btn", None)
        if stop_btn is not None:
            stop_btn.setEnabled(False)

    def _get_selected_edit_agent_model(self):
        """获取当前 Agent 模型选择；空时回退到模型管理激活项。"""
        combo = getattr(self, '_edit_agent_model_combo', None)
        if combo is not None:
            data = combo.currentData()
            if isinstance(data, tuple) and len(data) == 2 and data[0]:
                return data
        try:
            from app.modules.lego.model_config import load_active_provider
            active = load_active_provider() or ""
            if active:
                return active, ""
        except Exception:
            pass
        return "", ""

    def _build_edit_agent_messages(self, user_text: str) -> List[Dict[str, str]]:
        """构建剪辑 Agent 专用提示词，要求模型返回可执行 JSON 指令。"""
        from app.core.agent_action_registry import (
            build_agent_actions_help_block,
            list_editor_capabilities_for_prompt,
        )

        context = self._get_agent_timeline_context()
        extensions_info = self._get_agent_extensions_context()
        from app.core.agent_policy import mode_prompt_block

        is_plan_mode = self._is_agent_plan_mode()
        agent_mode = self._get_agent_session_mode()
        caps_info = list_editor_capabilities_for_prompt()

        system_prompt = (
            "你是拾光剪影的 AI 剪辑助手，也是一位友善的对话伙伴。"
            "你可以像普通 AI 助手一样自由对话，自然回答剪辑技巧、项目功能、视频创作等任何问题，"
            "文字内容不限格式，直接回复即可，不要套 JSON。\n\n"
            "只有当用户提出明确的剪辑操作需求（切分、删除、滤镜、转场、特效、字幕、轨等）时，"
            "才输出可执行的 JSON 指令数组，且不要附带多余解释文字。\n"
            f"{build_agent_actions_help_block()}"
            + mode_prompt_block(agent_mode)
            + "时间单位是秒，clip_index 从 0 开始。"
            "add_effect 参数示例: {\"effect_type\":\"filter\",\"params\":{\"filter_name\":\"电影\",\"intensity\":0.7}}。"
            "add_transition 参数示例: {\"transition_type\":\"fade\",\"duration\":0.5,\"clip_index\":0}。"
            "call_extension 用于调用拓展中心的插件/Skill/MCP 工具，参数示例: "
            "{\"extension_id\":\"技能ID\",\"tool_id\":\"工具ID\",\"params\":{\"key\":\"value\"}}。"
            "call_model 参数示例: {\"provider\":\"deepseek\",\"messages\":[{\"role\":\"user\",\"content\":\"...\"}],\"model\":\"...\"}。"
            "start_workflow 参数示例: {\"drama_info\":{\"title\":\"...\",\"platform\":\"douyin\"}}。"
            "account_optimize 参数示例: {\"platform\":\"douyin\",\"features\":{...}}。"
        )

        # Plan 模式要求先规划
        if is_plan_mode:
            system_prompt += (
                "\n\n当前为 Plan 模式：你必须先返回执行规划，格式为 JSON 对象："
                "{\"plan\":[\"步骤1\",\"步骤2\",...],\"commands\":[{...指令...}]}。"
                "plan 是给用户看的人类可读步骤列表，commands 是实际要执行的指令数组。"
                "用户确认后才会执行 commands。"
            )
        else:
            system_prompt += "\n\n直接返回 JSON 指令数组。"

        # 注入长期记忆 + 待处理反馈
        try:
            from app.core.memory_store import memory_store
            from app.core.agent_feedback_bridge import agent_feedback_bridge
            mem_ctx = memory_store.get_agent_context(top_k=5)
            pending = agent_feedback_bridge.get_pending_feedback(limit=3)
            if mem_ctx:
                system_prompt += mem_ctx
            if pending:
                summaries = [f.get("summary", agent_feedback_bridge._brief(f)) for f in pending]
                system_prompt += "\n\n[近期发布反馈]\n" + "\n".join(f"- {s}" for s in summaries)
                system_prompt += "\n请在生成剪辑指令时考虑以上反馈。"
                agent_feedback_bridge.mark_feedback_consumed(
                    [f.get("feedback_id") for f in pending if f.get("feedback_id")]
                )
        except Exception as e:
            logger.debug(f"[Agent] 注入记忆失败: {e}")

        # 注入拓展中心可用工具 + Dispatcher 能力（OpenTake 式「可枚举工具面」）
        ext_prompt = ""
        if extensions_info:
            # 截断过长列表，避免撑爆上下文
            slim = extensions_info[:40]
            ext_prompt = f"\n\n拓展中心可用工具:\n{json.dumps(slim, ensure_ascii=False, indent=2)}"
        caps_prompt = ""
        if caps_info:
            caps_prompt = (
                f"\n\n已注册剪辑相关 capability（供理解，对话仍用上面 action）:\n"
                f"{json.dumps(caps_info, ensure_ascii=False, indent=2)}"
            )

        user_prompt = (
            f"用户剪辑指令: {user_text}\n\n"
            f"当前时间线状态:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
            f"{caps_prompt}"
            f"{ext_prompt}"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _is_agent_plan_mode(self) -> bool:
        """判断当前是否为 Plan 模式。"""
        return self._get_agent_session_mode() == "plan"

    def _get_agent_session_mode(self) -> str:
        from app.core.agent_policy import normalize_mode

        combo = getattr(self, "_agent_mode_combo", None)
        if combo is None:
            return "collaborative"
        return normalize_mode(combo.currentData())

    def _get_agent_extensions_context(self) -> List[Dict[str, Any]]:
        """收集拓展中心可用工具，供 Agent 调用。"""
        tools = []
        try:
            from app.core.extension_base import get_extensions_registry
            registry = get_extensions_registry()
            for ext in registry.list_all():
                if not ext.is_enabled and not ext.is_available:
                    continue
                ext_tools = ext.get_tools() or []
                for t in ext_tools:
                    tools.append({
                        "extension_id": ext.info.id,
                        "extension_name": ext.info.name,
                        "extension_type": ext.extension_type.value,
                        "tool_id": t.id,
                        "tool_name": t.name,
                        "description": t.description,
                    })
        except Exception as e:
            logger.debug(f"收集拓展中心工具失败: {e}")

        # 补充 SkillEngine 中的技能（兼容直接注册的 Skill）
        try:
            # 触发外部 skill 注册（幂等：仅首次实际扫描 app/skills/external/，
            # 后续调用直接返回 0）。修复 Agent 面板看不到外部 skill 的问题：
            # 外部 skill 注册原本只在 extensions_module._refresh_skill_list 触发，
            # 若用户未打开拓展中心标签页，Agent 调用 list_all() 会拿不到外部 skill。
            try:
                from app.skills.external_loader import ensure_external_skills_registered
                ensure_external_skills_registered()
            except Exception as ext_e:
                logger.debug(f"外部 skill 注册失败（不影响内置 skill）: {ext_e}")
            from .skill_engine import skill_engine
            for skill in skill_engine.list_all():
                tools.append({
                    "extension_id": skill.skill_id,
                    "extension_name": skill.skill_name,
                    "extension_type": "skill",
                    "tool_id": skill.skill_id,
                    "tool_name": skill.skill_name,
                    "description": getattr(skill, "skill_description", ""),
                })
        except Exception as e:
            logger.debug(f"收集 SkillEngine 技能失败: {e}")

        # 补充 PluginManager 管理的传统插件（修复 Agent 看不到传统插件的问题：
        # 原逻辑只收集 ExtensionsRegistry 和 SkillEngine，短剧筛选/AI特效等
        # PluginManager 管理的插件对 Agent 不可见，模型无法生成 call_extension 指令）
        try:
            # _ensure_plugin_manager 内置 lazy load（首次调用初始化，后续直接返回）
            plugin_mgr = self._ensure_plugin_manager()
            if plugin_mgr is not None:
                for plugin in plugin_mgr.list_plugins(enabled_only=True):
                    plugin_id = getattr(plugin, "id", None)
                    if not plugin_id:
                        continue
                    tools.append({
                        "extension_id": plugin_id,
                        "extension_name": getattr(plugin, "name", plugin_id),
                        "extension_type": "plugin",
                        "tool_id": plugin_id,
                        "tool_name": getattr(plugin, "name", plugin_id),
                        "description": getattr(plugin, "description", ""),
                    })
        except Exception as e:
            logger.debug(f"收集 PluginManager 插件失败: {e}")

        return tools

    def _get_agent_timeline_context(self) -> Dict[str, Any]:
        """整理当前时间线上下文（OpenTake get_timeline 风格：可自省、可决策）。"""
        clips = []
        track_ids = set()
        total_end = 0.0
        for index, clip in enumerate(getattr(self, '_clips', [])):
            start = float(clip.get("start_time", 0) or 0)
            duration = float(clip.get("duration", 0) or 0)
            end = start + duration
            if end > total_end:
                total_end = end
            track = clip.get("track", 0)
            try:
                track_ids.add(int(track))
            except (TypeError, ValueError):
                track_ids.add(track)
            path = clip.get("path") or ""
            clips.append({
                "clip_index": index,
                "id": clip.get("id"),
                "name": clip.get("name") or (path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""),
                "path": path,
                "start_time": start,
                "duration": duration,
                "end_time": end,
                "in_point": clip.get("in_point", 0),
                "out_point": clip.get("out_point"),
                "track": track,
                "volume": clip.get("volume"),
                "speed": clip.get("speed", 1.0),
                "effects": clip.get("effects", {}),
                "transition": clip.get("transition"),
                "has_keyframes": bool(clip.get("keyframes")),
            })

        # 同轨空隙摘要（供去静音/吸附决策，不改数据）
        gaps = []
        by_track: Dict[Any, list] = {}
        for c in clips:
            by_track.setdefault(c["track"], []).append(c)
        for track, items in by_track.items():
            items = sorted(items, key=lambda x: x["start_time"])
            for i in range(len(items) - 1):
                gap_start = items[i]["end_time"]
                gap_end = items[i + 1]["start_time"]
                if gap_end - gap_start > 0.05:
                    gaps.append({
                        "track": track,
                        "t_in": round(gap_start, 3),
                        "t_out": round(gap_end, 3),
                        "duration": round(gap_end - gap_start, 3),
                    })

        return {
            "clip_count": len(clips),
            "track_count": len(track_ids),
            "tracks": sorted(track_ids, key=lambda x: (isinstance(x, str), x)),
            "timeline_duration": round(total_end, 3),
            "gap_count": len(gaps),
            "gaps": gaps[:20],
            "selected_clip_id": getattr(self, '_current_clip', None).get("id") if getattr(self, '_current_clip', None) else None,
            "playhead_position": getattr(self, '_playhead_position', 0),
            "clips": clips,
        }

    # ═══════════════════════════════════════════════════════════════
    # Agent 公开接口（P0-A：EditorCapabilityHandlers 调用的公开方法）
    # 这些方法包装同名私有方法，增加 try/except 保护，避免 handler 直接依赖私有实现
    # ═══════════════════════════════════════════════════════════════

    def agent_get_timeline_context(self) -> Dict[str, Any]:
        """Agent 公开接口：获取当前时间线上下文（时间线数据、选中片段、播放头位置）。"""
        try:
            return self._get_agent_timeline_context()
        except Exception as e:
            logger.warning(f"[Agent] agent_get_timeline_context 失败: {e}")
            return {"error": str(e), "clip_count": 0, "clips": []}

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

    def agent_suggest_cleanup(self, *, open_ui: bool = True) -> Dict[str, Any]:
        """
        M5：去水词/静音「建议 + 确认」——默认弹勾选对话框，不静默写 _clips，不走 run_full。

        open_ui=False 时仅返回建议 JSON（供 Agent 展示），不改时间线。
        """
        try:
            from app.modules.lego.editor_subtitle_panel import (
                build_editor_cleanup_plan,
                run_cleanup_checklist_flow,
                suggest_cleanup_intervals_payload,
            )
            plan, err = build_editor_cleanup_plan(self)
            if err:
                return {
                    "action": "suggest_cleanup",
                    "success": False,
                    "message": err,
                    "intervals": [],
                    "awaiting_confirm": False,
                }
            payload = suggest_cleanup_intervals_payload(plan)
            if not open_ui:
                return {
                    "action": "suggest_cleanup",
                    "success": True,
                    "message": f"建议 {len(payload)} 段，待确认后执行（未改时间线）",
                    "intervals": payload,
                    "awaiting_confirm": True,
                    "suggested_count": len(payload),
                    "total_duration": float(plan.total_duration),
                    "is_dense_dialogue": bool(plan.is_dense_dialogue),
                }
            flow = run_cleanup_checklist_flow(self, plan)
            return {
                "action": "suggest_cleanup",
                "success": bool(flow.get("success")),
                "cancelled": bool(flow.get("cancelled")),
                "message": flow.get("message", ""),
                "intervals": flow.get("intervals") or payload,
                "suggested_count": flow.get("suggested_count", len(payload)),
                "selected_count": flow.get("selected_count", 0),
                "awaiting_confirm": False,
            }
        except Exception as e:
            logger.exception(f"[Agent] agent_suggest_cleanup 失败: {e}")
            return {
                "action": "suggest_cleanup",
                "success": False,
                "message": f"建议去水词失败（非假成功）: {e}",
                "intervals": [],
            }

    def _on_edit_agent_chunk(self, chunk: str):
        """缓存模型流式输出。"""
        # 顶层 try/except 兜底（P0 闪退修复）：
        # 本槽由 QThread.chunk_ready 信号高频触发（每个 token 一次），
        # 若 _edit_agent_stream_buffer 未初始化或主窗口切换中属性已销毁，
        # 会 AttributeError 穿透到信号分发器导致主线程崩溃。
        try:
            self._edit_agent_stream_buffer = getattr(self, '_edit_agent_stream_buffer', "") + chunk
        except Exception as e:
            logger.warning(f"[Agent] _on_edit_agent_chunk 处理失败: {e}")

    def _on_edit_agent_result(self, user_text: str, raw: str):
        """处理模型输出并应用剪辑指令（Plan 模式下先展示规划等待确认）。"""
        # 顶层 try/except 兜底（P0 闪退修复）：
        # 本槽由 QThread 信号触发，任何异常会让槽函数崩溃、主线程闪退。
        # 兜底时记录完整堆栈 + 在 Agent 面板显示错误消息，避免静默崩溃。
        try:
            self._do_on_edit_agent_result(user_text, raw)
            # ✅ 激活 AgentBrain Hebbian 学习（P0）：成功路径强化相关突触
            self._agent_brain_learn(success=True, user_text=user_text)
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

    def _show_agent_plan(self, plan_steps: List[str], commands: List[Any], user_text: str):
        """展示 Plan 模式规划，等待用户确认。"""
        self._pending_plan_commands = commands
        self._pending_plan_user_text = user_text
        # 格式化规划步骤
        plan_text = "\n".join([f"{i+1}. {step}" for i, step in enumerate(plan_steps)])
        self._agent_plan_view.setPlainText(plan_text)
        self._agent_plan_card.setVisible(True)

    def _confirm_agent_plan(self):
        """用户确认执行 Plan 规划。"""
        commands = getattr(self, '_pending_plan_commands', [])
        if not commands:
            self._append_agent_message("系统", "没有可执行的指令。")
            self._agent_plan_card.setVisible(False)
            return
        self._append_agent_message("系统", "开始执行规划...")
        results = self._apply_agent_commands_to_editor(commands)
        summary = self._format_agent_command_summary(results)
        self._append_agent_message("系统", summary or "规划已处理。")
        self._agent_plan_card.setVisible(False)
        self._pending_plan_commands = []
        self._pending_plan_user_text = ""

    def _cancel_agent_plan(self):
        """用户取消 Plan 规划。"""
        self._agent_plan_card.setVisible(False)
        self._pending_plan_commands = []
        self._pending_plan_user_text = ""
        self._append_agent_message("系统", "规划已取消。")

    def _on_agent_feedback(self, event):
        """收到反馈时在 Agent 面板显示提示（非侵入）"""
        summary = (event.data or {}).get("summary", "")
        if summary:
            self._append_agent_message("系统", f"📦 收到新反馈: {summary}（下次指令将自动参考）")

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
                pass

    def _on_edit_agent_stopped(self):
        """Agent 被用户终止。"""
        # 顶层 try/except 兜底（P0 闪退修复）：
        # 用户点终止按钮触发，若 Agent 面板已销毁访问 QTextEdit 会 RuntimeError。
        try:
            self._append_agent_message("系统", "当前 Agent 输出已终止。")
        except Exception as e:
            logger.warning(f"[Agent] _on_edit_agent_stopped 处理失败: {e}")

    def _on_edit_agent_finished(self):
        """恢复 Agent 按钮状态。"""
        # 顶层 try/except 兜底（P0 闪退修复）：
        # finished 是 QThread 内置信号，无论成功/失败/异常 100% 必触发。
        # 若用户已切换模块按钮可能已 deleteLater，访问会 RuntimeError 崩溃。
        try:
            send_btn = getattr(self, '_edit_agent_send_btn', None)
            stop_btn = getattr(self, '_edit_agent_stop_btn', None)
            if send_btn is not None:
                send_btn.setEnabled(True)
            if stop_btn is not None:
                stop_btn.setEnabled(False)
            inbox = getattr(self, "_edit_agent_inbox", None) or []
            if inbox:
                nxt = inbox.pop(0)
                self._edit_agent_inbox = inbox
                self._edit_agent_input.setText(nxt)
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, self._send_edit_agent_message)
        except Exception as e:
            logger.warning(f"[Agent] _on_edit_agent_finished 处理失败: {e}")

    # ────────────── AgentBrain 学习机制（P0 激活）──────────────
    def _agent_brain_learn(self, success: bool, user_text: str = "", error: str = ""):
        """激活 AgentBrain Hebbian 学习机制（P0）。

        根据本次 Agent 调用的成败，调整相关神经元的突触权重：
        - 成功：强化 user_text 关键词匹配到的 capability 突触
        - 失败：弱化相关突触，让 Agent 下次倾向其他路径

        学习失败不影响主流程（异常隔离），符合 .trae/rules/2.md §六.4 异常处理规范。

        Args:
            success: 本次 Agent 调用是否成功
            user_text: 用户原始输入文本（用于推断相关 capability）
            error: 失败时的错误信息（仅用于日志）
        """
        try:
            from app.core.agent_brain import agent_brain
            related = self._extract_related_capabilities(user_text)
            feedback = {
                "type": "success" if success else "quality",
                "related_capabilities": related,
                "severity": "low" if success else "medium",
            }
            agent_brain.learn_from_feedback(feedback)
            logger.debug(f"[Agent] AgentBrain 学习触发: success={success}, related={related}")
        except Exception as e:
            # 学习失败不能影响主流程（异常隔离）
            logger.warning(f"[Agent] AgentBrain 学习失败: {e}")

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
    def _on_pipeline_event(self, event):
        """监听全链路相关事件，更新 Agent 面板状态。"""
        try:
            data = event.data if hasattr(event, "data") else event
            if not isinstance(data, dict):
                return
            subtype = data.get("subtype", "")
            if subtype == "pipeline_waiting_preview":
                self._handle_waiting_preview(data)
            elif subtype == "pipeline_progress":
                self._handle_pipeline_progress(data)
            elif subtype == "pipeline_done":
                self._handle_pipeline_done(data)
            elif subtype == "video_generation_done":
                self._handle_video_generation_done(data)
        except Exception as e:
            logger.debug(f"[Agent] 处理全链路事件失败: {e}")

    def _handle_video_generation_done(self, data: Dict):
        """检测是否使用了本地占位色块回退，如有则提醒用户。"""
        lbl = getattr(self, "_agent_provider_status_lbl", None)
        if lbl is None:
            return
        try:
            paths = data.get("paths", []) or []
            if not paths:
                return
            # 判断文件名前缀是否为 gen_*（本地占位生成）
            import os as _os
            all_local = all(_os.path.basename(str(p)).startswith("gen_") for p in paths)
            if all_local:
                existing = lbl.text()
                note = "⚠ 本次生成使用了本地占位色块（云端 provider 不可用）"
                if note not in existing:
                    new_text = (existing + "\n" + note) if existing.strip() else note
                    lbl.setText(new_text)
                    lbl.setStyleSheet("color:#ff7b72;font-size:10px;font-weight:700;")
                self._append_agent_message("系统", note)
        except Exception as e:
            logger.debug(f"[Agent] 处理生成回退提示失败: {e}")

    def _handle_waiting_preview(self, data: Dict):
        """处理等待预览确认事件：更新按钮状态、提示 + 渲染预览问题卡。"""
        status = data.get("status", {})
        failed_count = status.get("by_status", {}).get("failed", 0)
        total = status.get("total", 0)

        # ── 新增：渲染预览问题片段列表（保守版） ──
        try:
            from app.core.preview_validation_loop import (
                preview_validation_loop, PreviewStatus
            )
            failed_clips = preview_validation_loop.get_clips_by_status(
                PreviewStatus.FAILED
            )
            self._render_preview_issues(failed_clips)
        except Exception as e:
            logger.debug(f"[Agent] 渲染预览问题列表失败: {e}")

        # ── 新增：进度卡停在 waiting_for_preview_confirmation ──
        self._update_pipeline_stage(
            "waiting_for_preview_confirmation",
            f"{failed_count}/{total} 个片段需要人工确认"
        )

        self._append_agent_message(
            "Agent",
            f"⏸️ 全链路已暂停：预览发现 {failed_count}/{total} 个片段有问题。\n"
            f"请在时间线上调整后，点击下方【✅ 确认预览并继续】按钮继续执行。",
        )
        # 切换按钮状态
        pipeline_btn = getattr(self, "_edit_agent_pipeline_btn", None)
        if pipeline_btn:
            pipeline_btn.setText("✅ 确认预览并继续")
            pipeline_btn.setStyleSheet(
                "QPushButton{background:#1f6feb;color:#fff;border:1px solid #388bfd;"
                "border-radius:8px;padding:6px 12px;font-size:11px;font-weight:700;}"
                "QPushButton:hover{background:#388bfd;}"
            )
            pipeline_btn.setProperty("waiting_preview", True)

    def _handle_pipeline_progress(self, data: Dict):
        """处理全链路进度更新事件。"""
        stage = data.get("stage", "")
        message = data.get("message", "")
        # ── 新增：刷新进度卡 ──
        self._update_pipeline_stage(stage, message)
        # 保留原有 emoji 消息追加逻辑
        if not message:
            return
        if stage == "routing":
            self._append_agent_message("Agent", f"🔀 {message}")
        elif stage == "generation":
            self._append_agent_message("Agent", f"🎬 {message}")
        elif stage == "import_parsing":
            self._append_agent_message("Agent", f"📥 {message}")
        elif stage == "preview":
            self._append_agent_message("Agent", f"🔍 {message}")
        elif stage == "scoring":
            self._append_agent_message("Agent", f"📊 {message}")
        elif stage == "scripting":
            self._append_agent_message("Agent", f"📝 {message}")
        elif stage == "editing":
            self._append_agent_message("Agent", f"✂️ {message}")
        elif stage == "done":
            self._append_agent_message("Agent", f"✅ {message}")

    def _handle_pipeline_done(self, data: Dict):
        """处理全链路完成事件：重置按钮状态 + 渲染打分/脚本卡 + 进度完成。"""
        result = data.get("result", {})
        success = result.get("success", False)
        error = result.get("error", "")

        # ── 新增：进度卡最终状态 ──
        degraded = bool(result.get("degraded")) or (
            result.get("success")
            and not result.get("final_video_path")
            and bool(result.get("editing_script"))
        )
        self._finalize_pipeline_stage(
            bool(result.get("success")),
            result.get("error") or "",
            degraded=degraded,
        )

        # ── 新增：渲染五维打分结果卡（从 session 对象取 scored_results） ──
        try:
            session_id = result.get("session_id", "")
            scored = []
            if session_id:
                from app.core.agent_pipeline_orchestrator import (
                    agent_pipeline_orchestrator
                )
                session = agent_pipeline_orchestrator.get_session(session_id)
                if session is not None and getattr(session, "scored_results", None):
                    scored = session.scored_results
            self._render_score_results(scored)
        except Exception as e:
            logger.debug(f"[Agent] 渲染打分卡失败: {e}")

        # ── 新增：渲染剪辑脚本卡（事件载荷已有 editing_script） ──
        try:
            editing_script = result.get("editing_script") or {}
            self._render_editing_script(editing_script if editing_script else None)
        except Exception as e:
            logger.debug(f"[Agent] 渲染脚本卡失败: {e}")

        if result.get("success"):
            final_path = result.get("final_video_path", "")
            degraded = bool(result.get("degraded")) or (
                not final_path and bool(result.get("editing_script"))
            )
            if final_path and not degraded:
                self._append_agent_message(
                    "Agent", f"🎉 全链路执行成功！成片已输出：\n{final_path}")
            elif degraded:
                reason = result.get("error") or "未产出成片文件"
                self._append_agent_message(
                    "Agent",
                    f"⚠️ 全链路降级完成（非完整成片成功）：{reason}\n"
                    "若有脚本，可点【▶ 一键手动精剪】导出；请勿当作已自动成片。",
                )
            else:
                self._append_agent_message(
                    "Agent",
                    "⚠️ 标记成功但无成片路径（状态异常）。请检查日志，勿当作导出完成。",
                )
        else:
            self._append_agent_message(
                "Agent",
                f"❌ 全链路执行失败（非假成功）：{result.get('error', '未知错误')}",
            )
        # 恢复按钮为初始状态
        self._reset_pipeline_button()

    def _reset_pipeline_button(self):
        """重置全链路按钮状态。"""
        pipeline_btn = getattr(self, "_edit_agent_pipeline_btn", None)
        if pipeline_btn:
            pipeline_btn.setText("🚀 全链路执行（生成→预览→打分→精剪→成片）")
            pipeline_btn.setStyleSheet(
                "QPushButton{background:#1f2a3d;color:#7ee787;border:1px solid #2f5139;"
                "border-radius:8px;padding:6px 12px;font-size:11px;font-weight:600;}"
                "QPushButton:hover{background:#238636;color:#fff;border-color:#238636;}"
            )
            pipeline_btn.setProperty("waiting_preview", False)

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
            print(f"剪辑 Agent 指令解析失败: {e}")
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

    def _agent_call_extension(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Agent 调用拓展中心 —— 优先走统一调用层，失败时回退原逻辑"""
        # 优先走统一调用层
        try:
            from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest
            result = capability_dispatcher.invoke(CapabilityRequest(
                capability_id="ext.run_extension",
                params=params,
                caller="agent",
                agent_mode=self._get_agent_session_mode() if hasattr(self, "_get_agent_session_mode") else "",
                approved=True,
            ))
            if result.success:
                output = result.output.get("result") if result.output else None
                msg = self._format_extension_result(output)
                return {"action": "call_extension", "success": True,
                        "message": msg if msg else "调用成功"}
            # dispatcher 失败则继续走原逻辑
        except Exception as e:
            logger.debug(f"[Agent] dispatcher 调用失败，回退原逻辑: {e}")

        # 原逻辑 fallback（保留向后兼容）
        ext_id = params.get("extension_id") or params.get("extensionId")
        tool_id = params.get("tool_id") or params.get("toolId") or ext_id
        call_params = params.get("params") or {}
        if not ext_id:
            return {"action": "call_extension", "success": False, "message": "缺少 extension_id 参数"}

        # 优先从 ExtensionsRegistry 查找
        try:
            from app.core.extension_base import get_extensions_registry
            registry = get_extensions_registry()
            ext = registry.get(ext_id)
            if ext is not None:
                if not ext.is_available:
                    if not ext.initialize():
                        return {"action": "call_extension", "success": False,
                                "message": f"扩展 {ext.info.name} 初始化失败: {ext.error}"}
                result = ext.run(tool_id, **call_params)
                msg = self._format_extension_result(result)
                return {"action": "call_extension", "success": True,
                        "message": f"已调用 {ext.info.name}.{tool_id}: {msg}"}
        except Exception as e:
            logger.warning(f"Agent 调用 ExtensionsRegistry 失败: {e}")

        # 回退到 SkillEngine
        try:
            from .skill_engine import skill_engine
            for skill in skill_engine.list_all():
                if skill.skill_id == ext_id:
                    from .extensions_context import ExtensionsContext
                    ctx = ExtensionsContext(inputs=call_params)
                    result = skill.execute(ctx)
                    msg = self._format_extension_result(result)
                    return {"action": "call_extension", "success": True,
                            "message": f"已执行技能 {skill.skill_name}: {msg}"}
        except Exception as e:
            logger.warning(f"Agent 调用 SkillEngine 失败: {e}")

        # 回退到 PluginManager（传统插件：短剧筛选、AI特效工坊等）
        # 修复 Agent 看不到 PluginManager 管理的传统插件问题：
        # 原逻辑只走 ExtensionsRegistry + SkillEngine，传统插件无法被调用
        try:
            plugin_mgr = self._ensure_plugin_manager()
            if plugin_mgr is not None:
                plugin = plugin_mgr.get_plugin(ext_id)
                if plugin is not None and getattr(plugin, "enabled", False):
                    # PluginManager.run_plugin 内部已 try/except，失败返回 None
                    result = plugin_mgr.run_plugin(ext_id, **call_params)
                    msg = self._format_extension_result(result)
                    return {"action": "call_extension", "success": True,
                            "message": f"已调用插件 {getattr(plugin, 'name', ext_id)}: {msg}"}
        except Exception as e:
            logger.warning(f"Agent 调用 PluginManager 失败: {e}")

        return {"action": "call_extension", "success": False,
                "message": f"未找到扩展: {ext_id}"}

    # ────────────── Agent 全链路闭环入口 ──────────────
    def _on_run_full_pipeline(self):
        """
        全链路一键执行入口（按钮点击）。
        根据当前按钮状态决定是「启动新流程」还是「继续等待中的流程」。
        """
        pipeline_btn = getattr(self, "_edit_agent_pipeline_btn", None)
        waiting_preview = False
        if pipeline_btn is not None:
            waiting_preview = pipeline_btn.property("waiting_preview") or False

        if waiting_preview:
            # 场景：预览暂停中，用户点击确认 → 以 auto_preview_pass=True 重新执行，跳过预览阻塞
            self._append_agent_message("Agent", "✅ 用户已确认预览，继续执行后续流程...")
            brief = ""
            inp = getattr(self, "_edit_agent_input", None)
            if inp is not None:
                brief = inp.text().strip()
            try:
                from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest

                send_btn = getattr(self, "_edit_agent_send_btn", None)
                if send_btn is not None:
                    send_btn.setEnabled(False)

                def _cb(result):
                    try:
                        QTimer.singleShot(0, lambda: self._on_full_pipeline_done(result))
                    except Exception:
                        logger.exception("[Agent] 全链路继续回调切主线程失败")

                capability_dispatcher.invoke_async(CapabilityRequest(
                    capability_id="pipeline.run_full",
                    params={
                        "materials": [],  # 已在之前的会话中处理，此处沿用
                        "creative_brief": brief,
                        **self._get_pipeline_params(),
                        "auto_preview_pass": True,  # 关键：跳过预览阻塞
                    },
                    caller="agent",
                ), callback=_cb)
            except Exception as e:
                logger.exception("[Agent] 全链路继续执行失败")
                self._append_agent_message("Agent", f"❌ 继续执行失败: {e}")
                send_btn = getattr(self, "_edit_agent_send_btn", None)
                if send_btn is not None:
                    send_btn.setEnabled(True)
            return

        # ── 正常启动新流程 ──
        # 收集导入栏素材（self._clips）
        materials = []
        for c in getattr(self, "_clips", []):
            path = c.get("path", "")
            if path:
                materials.append({
                    "path": path,
                    "type": c.get("type", "video"),
                    "duration": float(c.get("duration", 5.0) or 5.0),
                    "name": c.get("name", ""),
                })
        # 创意简报：优先取 Agent 输入框文本
        brief = ""
        inp = getattr(self, "_edit_agent_input", None)
        if inp is not None:
            brief = inp.text().strip()

        # ── 前置校验：无素材 + 无简报 → 友好提示 ──
        if not materials and not brief:
            self._append_agent_message(
                "Agent",
                "⚠️ 无法启动全链路执行：\n"
                "• 导入栏没有素材\n"
                "• Agent 输入框为空\n\n"
                "请选择以下任一方式后重试：\n"
                "1. 导入视频/图片素材（走 AI 素材剪辑业务线）\n"
                "2. 在输入框描述创意构思（走 AI 视频生成业务线）"
            )
            return

        # 左右脑协同联想：此前 correlate()/right_brain_think()/left_brain_think() 只有定义没有
        # 调用方，是完全不影响任何实际决策的死代码。这里在启动前跑一次，把联想到的能力
        # 展示给用户，让「左右脑协同」名副其实（仅展示，不改变实际路由/参数逻辑）。
        if brief:
            try:
                from app.core.agent_brain import agent_brain
                plan = agent_brain.correlate(brief)
                right = plan.get("right_brain_plan") or []
                left = plan.get("left_brain_plan") or []
                if right or left:
                    self._append_agent_message(
                        "Agent",
                        f"🧠 联想：右脑(创意) {right or '无'} · 左脑(逻辑) {left or '无'}",
                    )
            except Exception as e:
                logger.debug(f"[Agent] 左右脑联想失败: {e}")

        try:
            from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest
            self._append_agent_message(
                "Agent", f"🚀 启动全链路执行（素材 {len(materials)} 个，简报: {brief[:30] or '无'}）...")
            # 防重复点击
            send_btn = getattr(self, "_edit_agent_send_btn", None)
            if send_btn is not None:
                send_btn.setEnabled(False)

            def _cb(result):
                # worker 线程回调 → 通过 QTimer 切回主线程刷新 UI
                try:
                    QTimer.singleShot(0, lambda: self._on_full_pipeline_done(result))
                except Exception:
                    logger.exception("[Agent] 全链路回调切主线程失败")

            capability_dispatcher.invoke_async(CapabilityRequest(
                capability_id="pipeline.run_full",
                params={
                    "materials": materials,
                    "creative_brief": brief,
                    **self._get_pipeline_params(),
                    "auto_preview_pass": False,  # 默认：等待人工确认
                },
                caller="agent",
            ), callback=_cb)
        except Exception as e:
            logger.exception("[Agent] 全链路启动失败")
            self._append_agent_message("Agent", f"❌ 全链路启动失败: {e}")
            send_btn = getattr(self, "_edit_agent_send_btn", None)
            if send_btn is not None:
                send_btn.setEnabled(True)

    def _on_full_pipeline_done(self, result):
        """全链路执行完成回调（主线程刷新 UI）。"""
        send_btn = getattr(self, "_edit_agent_send_btn", None)
        if send_btn is not None:
            send_btn.setEnabled(True)
        if result.success:
            out = result.output or {}
            final_path = out.get("final_video_path", "")
            route = (out.get("route") or {}).get("route", "")
            scored = out.get("scored_count", 0)
            degraded = bool(out.get("degraded")) or (
                not final_path and bool(out.get("editing_script"))
            )
            if final_path and not degraded:
                msg = (f"✅ 全链路完成｜分流:{route} 打分镜头:{scored}｜成片:\n{final_path}")
            elif degraded:
                reason = out.get("error") or "未产出成片文件，仅有脚本/中间结果"
                msg = (
                    f"⚠️ 全链路降级完成（非成片成功）｜分流:{route} 打分:{scored}\n"
                    f"{reason}\n请用脚本卡【▶ 一键手动精剪】导出，勿当作已自动成片。"
                )
            else:
                msg = (
                    f"⚠️ 标记成功但无成片路径｜分流:{route} 打分:{scored}（请查日志）"
                )
            self._append_agent_message("Agent", msg)
        else:
            self._append_agent_message(
                "Agent", f"❌ 全链路失败（非假成功）: {result.error}"
            )

    def _execute_pipeline_editing(self, editing_script: Dict[str, Any],
                                  session_id: str = "") -> str:
        """
        精剪执行入口：解析剪辑脚本，应用转场、字幕、配乐，输出高质量成片。
        被 pipeline.execute_editing 能力调用（通过 editor_module_ref）。
        返回成片路径，失败返回空串。
        """
        import sys as _sys
        import subprocess as _sp
        import tempfile as _tf
        import json as _json

        clip_order = (editing_script or {}).get("clip_order", []) or []
        transitions = (editing_script or {}).get("transitions", {}) or {}
        bgm_path = (editing_script or {}).get("bgm", "")
        # 从脚本或 _clips 中提取字幕文本（如果脚本生成了的话）
        subtitles = (editing_script or {}).get("subtitles", []) or []
        if not subtitles:
            # 尝试从片段元数据中取
            subtitles = [c.get("dialogue", "") for c in self._clips if c.get("dialogue")]

        if not clip_order:
            logger.warning("[pipeline] 精剪：clip_order 为空")
            return ""

        # 按 clip_order 顺序收集存在的片段路径和时长
        clip_map = {c.get("id"): c for c in getattr(self, "_clips", []) if c.get("id")}
        paths_and_durations = []
        for cid in clip_order:
            clip = clip_map.get(cid)
            if clip and clip.get("path") and os.path.exists(clip["path"]):
                duration = float(clip.get("duration", 5.0) or 5.0)
                paths_and_durations.append({"path": clip["path"], "duration": duration, "id": cid})

        if not paths_and_durations:
            logger.warning("[pipeline] 精剪：clip_order 无可用片段路径")
            return ""

        output_dir = "短剧AI剪辑输出"
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            logger.debug("创建短剧AI剪辑输出目录失败: %s", e)
        out_path = os.path.join(
            output_dir, f"pipeline_{session_id or int(time.time())}_final.mp4")

        # 如果只有一个片段，直接应用字幕并添加静音（以适配后续可能的混音）
        if len(paths_and_durations) == 1:
            p = paths_and_durations[0]
            ffmpeg = self._find_pipeline_ffmpeg()
            if not ffmpeg:
                return ""
            return self._apply_single_clip_ffmpeg(ffmpeg, p["path"], p["duration"],
                                                   subtitles[0] if subtitles else "",
                                                   bgm_path, out_path)

        # 多片段：构建复杂的 filter_complex
        ffmpeg = self._find_pipeline_ffmpeg()
        if not ffmpeg:
            logger.warning("[pipeline] 未找到 ffmpeg，无法拼接成片")
            return ""

        return self._apply_multi_clip_ffmpeg(ffmpeg, paths_and_durations, transitions,
                                              subtitles, bgm_path, out_path)

    def agent_execute_pipeline_editing(self, editing_script: Dict[str, Any],
                                        session_id: str = "") -> str:
        """Agent 公开接口：执行精修剪辑脚本并输出成片。"""
        try:
            return self._execute_pipeline_editing(editing_script, session_id)
        except Exception as e:
            logger.exception(f"[Agent] agent_execute_pipeline_editing 失败: {e}")
            return ""

    def _apply_single_clip_ffmpeg(self, ffmpeg: str, input_path: str, duration: float,
                                   subtitle_text: str, bgm_path: str, out_path: str) -> str:
        """处理单个片段：叠加字幕，如有 BGM 则混音。"""
        import sys as _sys
        import subprocess as _sp

        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", input_path]

        has_bgm = bgm_path and os.path.exists(bgm_path)
        if has_bgm:
            cmd.extend(["-i", bgm_path])

        filter_complex = []
        cmd.extend(["-filter_complex"])

        # 字幕处理
        if subtitle_text:
            safe_text = subtitle_text.replace("'", "'\\''").replace(":", "\\:")
            filter_complex.append(f"drawtext=text='{safe_text}':fontcolor=white:fontsize=40:x=(w-text_w)/2:y=(h-text_h)*0.85:box=1:boxcolor=black@0.5:boxborderw=10[v]")
            video_stream = "[v]"
        else:
            video_stream = "[0:v]"

        # 音频处理（BGM 混音或原声）
        if has_bgm:
            filter_complex.append("[0:a][1:a]amix=inputs=2:duration=shortest[a]")
            audio_stream = "[a]"
        else:
            audio_stream = "[0:a]"

        cmd.append(";".join(filter_complex))
        cmd.extend(["-map", video_stream, "-map", audio_stream])

        cmd.extend([
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", out_path
        ])

        flags = 0x08000000 if _sys.platform == "win32" else 0
        try:
            proc = _sp.run(cmd, capture_output=True, timeout=300, creationflags=flags)
            if proc.returncode == 0 and os.path.exists(out_path) \
               and os.path.getsize(out_path) > 0:
                logger.info(f"[pipeline] 单片段成片已输出: {out_path}")
                return out_path
            else:
                err = proc.stderr.decode("utf-8", "ignore")[:200]
                logger.warning(f"[pipeline] 单片段处理失败: {err}")
                return ""
        except Exception as e:
            logger.warning(f"[pipeline] 单片段处理异常: {e}")
            return ""

    def _apply_multi_clip_ffmpeg(self, ffmpeg: str, clips: List[Dict], transitions: Dict,
                                  subtitles: List[str], bgm_path: str, out_path: str) -> str:
        """处理多个片段：应用 xfade 转场、字幕，并混音。"""
        import sys as _sys
        import subprocess as _sp

        # xfade 有效转场类型映射
        _XFADE_VALID = {
            "fade", "fadeblack", "fadewhite", "smoothleft", "smoothright",
            "circlecrop", "radial", "smthopen", "smthcover",
            "wipeleft", "wiperight", "slideleft", "slideright",
            "dissolve", "overlay",
        }
        _TRANSITION_MAP = {
            "fade": "fade",
            "cut": "fade",
            "zoom": "fadeblack",
            "slide": "smoothleft",
            "dissolve": "dissolve",
        }

        # 查找系统字体 + 转义路径（FFmpeg filter 要求正斜杠 + 冒号转义）
        _font_file = EditorModule._find_system_font()
        if _font_file:
            _font_file = _font_file.replace("\\", "/")
            # FFmpeg filter 语法中冒号是保留字符，需用反斜杠转义
            # C:/Windows/... → C\:/Windows/...
            _font_file = _font_file.replace(":", "\\:")

        def _has_audio_stream(filepath: str) -> bool:
            """用 ffprobe 检测文件是否有音频流"""
            try:
                probe_cmd = [
                    ffmpeg.replace("ffmpeg", "ffprobe"), "-v", "error",
                    "-select_streams", "a", "-show_entries", "stream=codec_type",
                    "-of", "csv=p=0", filepath
                ]
                p = _sp.run(probe_cmd, capture_output=True, timeout=10,
                            creationflags=0x08000000 if _sys.platform == "win32" else 0)
                return b"audio" in p.stdout
            except Exception:
                return False  # 检测失败默认无音频

        def _build_filter_parts(enable_subtitles: bool = True,
                                 has_audio: bool = True) -> List[str]:
            """构建 filter_complex 滤镜链"""
            parts = []
            prev_v = None
            prev_a = None
            cum_dur = 0.0
            prev_has_audio = has_audio  # 第一个片段是否有音频

            for i, clip in enumerate(clips):
                subtitle_text = subtitles[i] if i < len(subtitles) else ""
                current_v = f"[{i}:v]"

                # 检测当前片段是否有音频
                clip_has_audio = clip.get("_has_audio", has_audio)
                current_a = f"[{i}:a]" if clip_has_audio else None

                # 字幕滤镜
                if enable_subtitles and subtitle_text and _font_file:
                    safe_text = subtitle_text.replace("'", "'\\''").replace(":", "\\:")
                    parts.append(
                        f"{current_v}drawtext=fontfile='{_font_file}':"
                        f"text='{safe_text}':fontcolor=white:fontsize=36:"
                        f"x=(w-text_w)/2:y=(h-text_h)*0.9:"
                        f"box=1:boxcolor=black@0.4:boxborderw=8[v{i}]"
                    )
                    current_v = f"[v{i}]"

                # 转场参数
                clip_dur = clip["duration"]
                raw_transition = transitions.get(clip["id"], "fade")
                transition_type = _TRANSITION_MAP.get(raw_transition, raw_transition)
                if transition_type not in _XFADE_VALID:
                    transition_type = "fade"
                transition_duration = min(0.5, clip_dur * 0.2)
                offset = cum_dur - transition_duration if i > 0 else 0

                if i == 0:
                    prev_v = current_v
                    prev_a = current_a if clip_has_audio else None
                    cum_dur += clip_dur
                    prev_has_audio = clip_has_audio
                else:
                    out_v = f"[xf{i}v]"
                    parts.append(
                        f"{prev_v}{current_v}xfade=transition={transition_type}:"
                        f"duration={transition_duration}:offset={max(0, offset)}{out_v}"
                    )
                    # 仅当前后片段都有音频时才做音频转场
                    if prev_has_audio and clip_has_audio:
                        out_a = f"[xf{i}a]"
                        parts.append(
                            f"{prev_a}{current_a}acrossfade=d={transition_duration}:"
                            f"c1=tri:c2=tri{out_a}"
                        )
                        prev_a = out_a
                    elif clip_has_audio:
                        prev_a = current_a
                    # 如果当前片段无音频，prev_a 保持不变

                    prev_v = out_v
                    cum_dur += clip_dur - transition_duration
                    prev_has_audio = clip_has_audio

            # BGM 混音（仅当有音频流时）
            if has_bgm and prev_a:
                parts.append(f"{prev_a}[{len(clips)}:a]amix=inputs=2:duration=shortest[aout]")
                final_a = "[aout]"
            elif prev_a:
                final_a = prev_a
            else:
                final_a = None  # 无音频

            _build_filter_parts._final_v = prev_v
            _build_filter_parts._final_a = final_a
            return parts

        # 输入文件
        cmd_base = [ffmpeg, "-y", "-loglevel", "error"]
        for c in clips:
            cmd_base.extend(["-i", c["path"]])

        has_bgm = bgm_path and os.path.exists(bgm_path)
        if has_bgm:
            cmd_base.extend(["-i", bgm_path])

        flags = 0x08000000 if _sys.platform == "win32" else 0

        # 预检测每个片段是否有音频流
        for c in clips:
            if "_has_audio" not in c:
                c["_has_audio"] = _has_audio_stream(c["path"])

        any_has_audio = any(c.get("_has_audio", False) for c in clips)

        def _try_build(enable_subtitles: bool) -> str:
            """尝试构建并执行 FFmpeg 命令"""
            if not any_has_audio and not has_bgm:
                # 全部无音频 + 无 BGM → 跳过音频处理
                fp = _build_filter_parts(enable_subtitles=enable_subtitles, has_audio=False)
            else:
                fp = _build_filter_parts(enable_subtitles=enable_subtitles, has_audio=True)

            cmd = list(cmd_base)
            cmd.extend(["-filter_complex", ";".join(fp)])
            cmd.extend(["-map", _build_filter_parts._final_v])
            if _build_filter_parts._final_a:
                cmd.extend(["-map", _build_filter_parts._final_a])
            cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", out_path])
            if _build_filter_parts._final_a or has_bgm:
                cmd.extend(["-c:a", "aac"])

            try:
                proc = _sp.run(cmd, capture_output=True, timeout=600, creationflags=flags)
                if proc.returncode == 0 and os.path.exists(out_path) \
                   and os.path.getsize(out_path) > 0:
                    return out_path
                else:
                    err = proc.stderr.decode("utf-8", "ignore")[:300]
                    logger.warning(f"[pipeline] FFmpeg 失败: {err}")
                    return ""
            except Exception as e:
                logger.warning(f"[pipeline] FFmpeg 异常: {e}")
                return ""

        # 第一次尝试：带字幕
        if _font_file and any(s for s in subtitles if s):
            result = _try_build(enable_subtitles=True)
            if result:
                logger.info(f"[pipeline] 精剪成片已输出（带字幕）: {result}")
                return result
            logger.warning("[pipeline] 带字幕精剪失败，降级无字幕")

        # 第二次尝试：无字幕
        result = _try_build(enable_subtitles=False)
        if result:
            logger.info(f"[pipeline] 精剪成片已输出（无字幕降级）: {result}")
        else:
            logger.warning("[pipeline] 精剪合成失败（无字幕也失败）")
        return result

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
        live["duration"] = local_time
        live["out_point"] = float(live.get("in_point", 0) or 0) + local_time
        self._clips.append(new_clip)
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
                pass
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
                pass
            return {"action": "split_clip", "success": False, "message": str(e)}

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
                self._clips.append(audio_clip)
                existing.append(audio_clip)
                added.append(audio_clip)
        if added:
            self._touch_project_dirty()
            print(f"已补全 {len(added)} 条联动音频（波形）")

    def _resolve_media_duration(self, file_path: str) -> float:
        """媒体时长 SSOT：ffprobe / PreviewManager / OpenCV 取最大可信值。"""
        duration = 0.0
        try:
            duration = max(duration, float(self._probe_video_duration(file_path) or 0.0))
        except Exception:
            pass
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
            pass
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
            clip["duration"] = new_dur
            clip["out_point"] = in_p + new_dur
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
                pass
        # 无论是否修好，缓存当前签名，避免每次播放重复探测
        self._heal_av_sig = self._heal_av_clips_signature()
        return healed

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
            self._clips.append(clip)
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
                    self._clips.append(audio_clip)
            
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
                pass
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
                pass
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
                pass
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
                pass
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
            pass
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
            pass
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
                pass

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
            pass
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
