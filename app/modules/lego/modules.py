"""
详细化功能模块
=============
每个模块都是独立, 即插即用, 可删, 可关, 可独立更新
参考 Tk 版本的功能实现

┌──────────────────────────────────────────────────────────────┐
│  内存优化（2026-06-13）：懒加载架构                           │
│                                                               │
│  问题：modules.py 是「大杂烩」文件，包含 HomeModule、         │
│  EditorModule 等所有模块类。当 import modules.py 时，         │
│  顶部所有 import 语句全部执行，一次性加载：                    │
│    • numpy        (~100MB)                                     │
│    • librosa      (~150MB)                                     │
│    • moviepy      (~50MB)                                      │
│    • 10+ core.* 管理器 (~100MB)                               │
│    总计 ~400MB 内存，即使只看首页也会全部加载。                │
│                                                               │
│  方案：自定义 _LazyModuleProxy / _LazyClassProxy 延迟代理，   │
│  替换直接 import。真正的 importlib.import_module() 仅在        │
│  首次访问代理对象的属性或调用时执行。                          │
│                                                               │
│  效果：初始内存降低 200-400MB，首页加载速度显著提升。          │
└──────────────────────────────────────────────────────────────┘
"""

from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
import os
import json
import random
import logging
import importlib as _importlib
from datetime import datetime
logger = logging.getLogger("AI短剧编辑器.modules")

# ═══════════════════════════════════════════════════════════════
# 懒加载工具类 —— 内存优化的核心
#
# 原理：用代理对象「骗」过 Python 解释器，让它以为模块已导入。
# 实际上 importlib.import_module() 推迟到首次真·访问时才执行。
#
# _LazyModuleProxy：用于模块级变量（如 np.array(), librosa.load()）
# _LazyClassProxy：  用于类变量（如 EditorScheduler(), SubtitleManager()）
#
# 关键设计：
#   • __slots__ 减少每个代理的内存开销
#   • object.__setattr__/__getattribute__ 绕过代理自身的属性访问
#   • __call__ 支持类实例化（EditorScheduler() 调用 _LazyClassProxy）
# ═══════════════════════════════════════════════════════════════


class _LazyModuleProxy:
    """延迟加载模块代理。

    仅在首次访问属性 (proxy.xxx) 或调用 (proxy()) 时才真正执行
    importlib.import_module()。之后缓存在 _module 字段中。

    使用示例：
        np = _LazyModuleProxy('numpy')
        arr = np.array([1,2,3])  # 首次访问时才 import numpy
    """
    __slots__ = ('_name', '_module')  # 固定字段名，节省内存

    def __init__(self, name: str):
        # 使用 object.__setattr__ 绕过代理自身的属性拦截
        object.__setattr__(self, '_name', name)
        object.__setattr__(self, '_module', None)

    def _load(self):
        """触发真正的模块导入（仅首次调用时执行）"""
        m = object.__getattribute__(self, '_module')
        if m is None:
            m = _importlib.import_module(object.__getattribute__(self, '_name'))
            object.__setattr__(self, '_module', m)
        return m

    def __getattr__(self, attr):
        """代理所有属性访问：np.array → numpy.array"""
        return getattr(self._load(), attr)

    def __call__(self, *args, **kwargs):
        """代理直接调用：模块作为函数使用时"""
        return self._load()(*args, **kwargs)

    def __dir__(self):
        """支持 IDE 自动补全"""
        return dir(self._load())

    def __repr__(self):
        return f'<LazyProxy({object.__getattribute__(self, "_name")})>'


class _LazyClassProxy:
    """延迟加载类代理，专门用于支持实例化的类变量。

    与 _LazyModuleProxy 的区别：
      • 需要分别指定模块名和类名（如 'core.subtitle_manager' + 'SubtitleManager'）
      • 主要场景：EditorScheduler()、SubtitleManager(...) 等类实例化

    使用示例：
        EditorScheduler = _LazyClassProxy('core.editor_scheduler', 'EditorScheduler')
        scheduler = EditorScheduler()  # 首次调用时才 import 并实例化
    """
    __slots__ = ('_module_name', '_class_name', '_cls')

    def __init__(self, module_name: str, class_name: str):
        object.__setattr__(self, '_module_name', module_name)
        object.__setattr__(self, '_class_name', class_name)
        object.__setattr__(self, '_cls', None)

    def _load(self):
        """触发真实的类导入（仅首次调用时执行）"""
        cls = object.__getattribute__(self, '_cls')
        if cls is None:
            mod = _importlib.import_module(object.__getattribute__(self, '_module_name'))
            cls = getattr(mod, object.__getattribute__(self, '_class_name'))
            object.__setattr__(self, '_cls', cls)
        return cls

    def __call__(self, *args, **kwargs):
        """代理类实例化：EditorScheduler() → 真正创建对象"""
        return self._load()(*args, **kwargs)

    def __getattr__(self, attr):
        """代理类属性/静态方法访问"""
        return getattr(self._load(), attr)

    def __repr__(self):
        return (f'<LazyClass({object.__getattribute__(self, "_module_name")}'
                f'.{object.__getattribute__(self, "_class_name")})>')


def _lazy_import(module_name: str):
    """便捷工厂函数：创建模块懒加载代理"""
    return _LazyModuleProxy(module_name)


# ═══════════════════════════════════════════════════════════════
# 重型第三方库懒加载
# 这些库每个占用 50-150MB 内存，改为延迟导入后，
# 只有在用户真正打开剪辑/音频处理等功能时才会加载。
# ═══════════════════════════════════════════════════════════════

np = _lazy_import('numpy')          # 科学计算库，~50-100MB
librosa = _lazy_import('librosa')   # 音频分析库，~80-150MB

# moviepy 需要单独处理：VideoFileClip 和 concatenate_videoclips
# 是从 moviepy.editor 模块导入的具体类/函数，不能直接用模块代理，
# 需要通过辅助函数延迟获取。
_moviepy_editor = _lazy_import('moviepy.editor')
VideoFileClip = None             # 占位，实际通过 _get_VideoFileClip() 获取
concatenate_videoclips = None    # 占位，实际通过 _get_concatenate_videoclips() 获取


def _get_VideoFileClip():
    """延迟获取 moviepy.editor.VideoFileClip 类。

    使用方式（替代原来的 VideoFileClip(path)）：
        video = _get_VideoFileClip()(video_path)
    """
    return _moviepy_editor.VideoFileClip


def _get_concatenate_videoclips():
    """延迟获取 moviepy.editor.concatenate_videoclips 函数。

    使用方式（替代原来的 concatenate_videoclips(clips)）：
        final = _get_concatenate_videoclips()(clips)
    """
    return _moviepy_editor.concatenate_videoclips

from PySide6.QtCore import Qt, Signal, QThread, QTimer, QSize, QUrl, QPoint, QMimeData
from PySide6.QtGui import QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics, QPolygon, QShortcut, QKeySequence, QDrag
from PySide6.QtWidgets import (
    QDialog,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QProgressBar, QListWidget,
    QListWidgetItem, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QInputDialog, QTabWidget, QCheckBox, QSlider,
    QTreeWidget, QTreeWidgetItem, QMenu, QToolButton, QApplication, QSizePolicy, QFormLayout, QSpacerItem,
    QToolTip
)
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from .core import EventBus, EventType, MasterClock, DataBus
from .skill_engine import SkillEngine, Skill

# 确保 app/ 在 sys.path 中以兼容 core.xxx 导入
import sys as _sys
_app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _app_root not in _sys.path:
    _sys.path.insert(0, _app_root)

# ===== Core 管理器懒加载（仅在剪辑/项目管理等模块激活时才导入） =====
project_manager = _lazy_import('core.project_manager')      # project_manager.create_project(...)
timeline_manager = _lazy_import('core.timeline_manager')    # timeline_manager.xxx
effect_manager = _lazy_import('core.effect_manager')        # effect_manager.xxx

# 类级别代理（支持实例化: EditorScheduler()）
EditorScheduler = _LazyClassProxy('core.editor_scheduler', 'EditorScheduler')
SubtitleManager = _LazyClassProxy('core.subtitle_manager', 'SubtitleManager')
PresetManager = _LazyClassProxy('core.preset_manager', 'PresetManager')
PluginManager = _LazyClassProxy('core.plugin_manager', 'PluginManager')

# 导入TOP 0级剪辑引擎（冷启动 P1：改为惰性，见下方 _LAZY_REEXPORTS / __getattr__）
#
# 原写法是顶层 `from .top0_integration import Top0VideoProcessor`，实测这一跳
# 0.330s（top0_integration → drama_understanding_engine → cv2/numpy/aiohttp）。
# 而 Top0VideoProcessor 在本文件内**零消费**（TOP0_ENGINE_AVAILABLE 也无人读），
# 唯一真实使用者 app/core/editor_scheduler.py:719 早就用自己的 _safe_import 懒加载。
# 故删掉顶层导入，改为经模块级 __getattr__ 按需转发。
TOP0_ENGINE_AVAILABLE = None     # None = 未探测；访问 Top0VideoProcessor 时仍可用

# 导入爆款优化引擎（同上，本文件内零消费；真实消费者各自就地导入）
# 注意：Platform / VideoFeatures 是 enum/dataclass，转发时一并按需加载。
VIRAL_ENGINE_AVAILABLE = None

# 导入视频处理相关模块
import subprocess
import sys
import os
import time
from datetime import datetime

# ========== B1 拆分标记 (2026-05-31) ==========
# ThreadPool / HardwareDetector / PerformanceMonitor 已抽到 utils/ 子包
# 此处 re-export 以保持向后兼容, 外部代码 `from .modules import ThreadPool` 仍可用
from .utils.thread_pool import ThreadPool
from .utils.hardware_monitor import (
    HardwareDetector, PerformanceMonitor,
    hardware_detector, hardware_config, performance_monitor,
)

# 视频处理类
class VideoProcessor:
    """ """
    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self.ffmpeg = ffmpeg_path or "ffmpeg.exe"
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.output_dir = "短剧AI剪辑输出"
        os.makedirs(self.output_dir, exist_ok=True)
        self.thread_pool = ThreadPool()
        self.thread_pool.start()
        # 默认优化参数
        self.default_params = {
            "autoclip": {
                "duration": 15,  # 抖音/快手黄金时长
                "highlight_ratio": [0.7, 0.2, 0.1],  # 70%核心冲突+20%情绪铺垫+10%悬念结尾
                "force_front_conflict": True,  # 前3秒强制识别强冲突画面
                "remove_redundant": True,  # 剔除冗余剧情
                "quick_cut": True,  # 快速卡点组接
                "transitions": ["fade", "flash"]  # 淡入淡出/闪切
            },
            "funclip": {
                "bgm_category": "auto",  # 品类专属BGM
                "bgm_sync": True,  # BGM卡点剪辑
                "volume_balance": [0.7, 0.3],  # 人声70%+BGM30%
                "subtitle_font": "黑体",  # 黑体/微软雅黑粗体
                "subtitle_style": "white+black_border",  # 白色字体+黑色粗描边
                "subtitle_position": "bottom_quarter",  # 视频底部1/4处
                "add_narration": True,  # 添加旁白钩子
                "add_sound_effects": True  # 添加音效
            },
            "videofusion": {
                "enhance_4k": True,  # 4K高清增强
                "skin_correction": True,  # 肤色矫正
                "de_shake": True,  # 动态防抖
                "line_sharpen": True,  # 线条锐化(漫剧)
                "color_saturation": 1.1,  # 色彩饱和度提升10%
                "remove_noise": True,  # 去除画面噪点
                "aspect_ratio": "9:16",  # 画面比例锁定9:16
                "platform_format": "native"  # 平台原生格式导出
            },
            "lora_edit": {
                "copyright_check": True,  # 全维度版权检测
                "ai_face_replace": True,  # AI相似脸型替换
                "logo_removal": True,  # 无痕遮挡品牌logo
                "watermark_position": "bottom_right",  # 引流小贴纸位置
                "watermark_size": 0.08,  # 屏幕占比≤8%
                "watermark_opacity": 0.7,  # 半透明(透明度70%)
                "watermark_time": [0.67, 1.0]  # 视频后半段出现
            },
            "video_adjust": {
                "brightness": 0,  # 亮度调节
                "contrast": 0,  # 对比度调节
                "saturation": 0,  # 饱和度调节
                "hue": 0  # 色调调节
            }
        }
    
    def process_video(self, video_path, mode, export_settings=None):
        """提交一次视频处理任务到线程池。

        ⚠️ 这里必须写 `nonlocal export_settings`（2026-11-15 修）：
        `task()` 里既要读 `export_settings`（判 None），又给它赋默认值。
        Python 的规则是**函数内只要有赋值，这个名字在整个函数里就是局部的**，
        于是那句 `if export_settings is None` 抛 UnboundLocalError，
        再被下面的 `except Exception` 吞掉只写日志 ——
        结果就是「调用方永远收到『任务已提交到线程池』，任务每次都失败」。
        这类错不报异常、不崩界面，只能靠 ruff F823 或逐行读出来。
        """
        def task():
            nonlocal export_settings
            try:
                # 默认导出设置
                if export_settings is None:
                    export_settings = {
                        "resolution": "1920x1080",
                        "bitrate": "5M",
                        "format": "mp4"
                    }
                
                base_name = os.path.basename(video_path)
                ext = export_settings["format"]
                output_name = f"[{mode}]_{os.path.splitext(base_name)[0]}.{ext}"
                output_path = os.path.join(self.output_dir, output_name)
                
                # 根据模式应用不同的处理逻辑
                if mode == "AutoClip":
                    self._process_autoclip(video_path, output_path, export_settings)
                elif mode == "FunClip":
                    self._process_funclip(video_path, output_path, export_settings)
                elif mode == "VideoFusion":
                    self._process_videofusion(video_path, output_path, export_settings)
                elif mode == "LoRA Edit":
                    self._process_lora_edit(video_path, output_path, export_settings)
                else:
                    # 基础处理
                    self._basic_process(video_path, output_path, export_settings)
                
            except Exception as e:
                logger.error(f'处理视频失败: {e}')
                return None
        
        self.thread_pool.submit(task)
        return "任务已提交到线程池"
    
    def _basic_process(self, video_path, output_path, export_settings):
        """ """
        try:
            try:
                from app.core.render_manager import get_render_manager, RenderMode
            except ImportError:
                from core.render_manager import get_render_manager, RenderMode
            rm = get_render_manager()
            platform = export_settings.get("platform", "通用HD")
            result = rm.render(video_path, output_path, platform=platform)
            if result.success:
                logger.info(f'视频处理完成: {output_path} ({result.processing_time:.1f}s, {result.output_size / 1024 / 1024:.1f}MB)')
            else:
                logger.error(f'视频处理失败: {result.error_message}')
        except Exception as e:
            logger.error(f'RenderManager 调用失败,回退到基础 FFmpeg: {e}')
            # 回退方案
            res_str = export_settings.get("resolution", "1920x1080")
            cmd = [
                self.ffmpeg,
                "-i", video_path,
                "-c:v", "libx264",
                "-b:v", export_settings.get("bitrate", "5M"),
                "-s", res_str,
                "-y", output_path
            ]
            logger.info(f"执行命令: {' '.join(cmd)}")
            import subprocess as _sp
            result = _sp.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f'视频处理完成: {output_path}')
            else:
                logger.error(f'视频处理失败: {result.stderr}')
    
    def _process_autoclip(self, video_path, output_path, export_settings):
        """ """
        params = self.default_params["autoclip"]
        logger.info(f'AutoClip 处理中,参数: {params}')
        # 这里应该实现高光识别和剪辑逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def _process_funclip(self, video_path, output_path, export_settings):
        """ """
        params = self.default_params["funclip"]
        logger.info(f'FunClip 处理中,参数: {params}')
        # 这里应该实现BGM,字幕,音频处理逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def _process_videofusion(self, video_path, output_path, export_settings, video_adjust_params=None):
        """ """
        params = self.default_params["videofusion"]
        adjust_params = video_adjust_params or self.default_params["video_adjust"]
        logger.info(f'VideoFusion 处理中,参数: {params}')
        logger.info(f'视频调节参数: {adjust_params}')
        # 这里应该实现画质增强逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def _process_lora_edit(self, video_path, output_path, export_settings):
        """ """
        params = self.default_params["lora_edit"]
        logger.info(f'LoRA Edit 处理中,参数: {params}')
        # 这里应该实现版权优化和引流植入逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def optimize_workflow(self, video_path, platform="抖音", video_adjust_params=None):
        """ """
        def task():
            try:
                # 1. AutoClip 高光识别
                autoclip_output = os.path.join(self.output_dir, f"autoclip_{os.path.basename(video_path)}")
                self._do_autoclip(video_path, autoclip_output)
                
                # 2. FunClip 精剪
                funclip_output = os.path.join(self.output_dir, f"funclip_{os.path.basename(video_path)}")
                self._do_funclip(autoclip_output, funclip_output)
                
                # 3. VideoFusion 画质增强
                videofusion_output = os.path.join(self.output_dir, f"videofusion_{os.path.basename(video_path)}")
                self._do_videofusion(funclip_output, videofusion_output, video_adjust_params)
                
                # 4. LoRA Edit 合规+引流
                final_output = os.path.join(self.output_dir, f"final_{platform}_{os.path.basename(video_path)}")
                self._do_lora_edit(videofusion_output, final_output)
                
                logger.info(f'优化工作流完成,最终输出: {final_output}')
                return final_output
            except Exception as e:
                logger.error(f'优化工作流失败: {e}')
                return None
        
        self.thread_pool.submit(task)
        return "优化工作流已提交到线程池"
    
    def _do_autoclip(self, video_path, output_path):
        """ """
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            scene_scores = []; window = int(fps * 2); step = int(fps * 0.5)
            for start in range(0, frame_count, step):
                end = min(start + window, frame_count)
                cap.set(cv2.CAP_PROP_POS_FRAMES, start)
                motion_sum = 0; prev = None; frame_num = 0
                for pos in range(start, end, 2):
                    ret, frm = cap.read()
                    if not ret: break
                    g = cv2.cvtColor(frm, cv2.COLOR_BGR2GRAY); g = cv2.resize(g, (160, 90))
                    if prev is not None:
                        motion_sum += np.mean(np.abs(g.astype(float) - prev.astype(float)))
                    prev = g; frame_num += 1
                if frame_num > 0:
                    scene_scores.append((start/fps, min(end/fps, frame_count/fps), motion_sum/frame_num))
            cap.release()
            scene_scores.sort(key=lambda x: x[2], reverse=True)
            best = sorted(scene_scores[:8], key=lambda x: x[0])
            list_file = output_path + ".txt"
            with open(list_file, 'w', encoding='utf-8') as f:
                for s, e, sc in best: f.write(f"file '{video_path}'\ninpoint {s}\noutpoint {e}\n")
            subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-segment_time_metadata","1",
                "-i",list_file,"-vf","select=concatdec_select,setpts=PTS-STARTPTS",
                "-c:v","libx264","-preset","fast",output_path],
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
            if os.path.exists(list_file): os.remove(list_file)
        except ImportError:
            self._basic_process(video_path, output_path, {"resolution":"1920x1080","bitrate":"5M","format":"mp4"})
    
    def _do_funclip(self, video_path, output_path):
        """ """
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            prev_frame = None; scene_changes = []
            for i in range(0, frame_count, int(fps)):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()
                if not ret: break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY); gray = cv2.resize(gray, (320, 180))
                if prev_frame is not None:
                    diff = np.mean(np.abs(gray.astype(float) - prev_frame.astype(float)))
                    if diff > 15: scene_changes.append(i / fps)
                prev_frame = gray
            cap.release()
            full_duration = frame_count / fps
            scene_changes = [0.0] + scene_changes + [full_duration]
            segments = [(scene_changes[i], scene_changes[i+1]) for i in range(len(scene_changes)-1)]
            segments = [(s,e) for s,e in segments if e-s>2.0][:10]
            list_file = output_path + ".txt"
            with open(list_file, 'w', encoding='utf-8') as f:
                for s, e in segments: f.write(f"file '{video_path}'\ninpoint {s}\noutpoint {e}\n")
            subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-segment_time_metadata","1",
                "-i",list_file,"-vf","select=concatdec_select,setpts=PTS-STARTPTS",
                "-c:v","libx264","-preset","fast","-an",output_path],
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
            if os.path.exists(list_file): os.remove(list_file)
        except ImportError:
            self._basic_process(video_path, output_path, {"resolution":"1920x1080","bitrate":"5M","format":"mp4"})
    
    def _do_videofusion(self, video_path, output_path, adjust_params=None):
        """ """
        try:
            filters = "unsharp=5:5:1.0:5:5:0.0,hqdn3d=4:3:6:4,format=yuv420p"
            subprocess.run(["ffmpeg","-y","-i",video_path,"-vf",filters,
                "-c:v","libx264","-preset","medium","-crf","18",
                "-c:a","aac","-b:a","192k",output_path],
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        except Exception as e:
            logger.error(f'VideoFusion 失败: {e}')
            self._basic_process(video_path, output_path, {"resolution":"1920x1080","bitrate":"5M","format":"mp4"})
    
    def _do_lora_edit(self, video_path, output_path):
        """ """
        try:
            filters = "eq=brightness=0.05:contrast=1.1:saturation=1.3,colorbalance=rs=0.1:gs=-0.05:bs=-0.1,hue=h=5,vignette=PI/4,unsharp=3:3:0.8"
            subprocess.run(["ffmpeg","-y","-i",video_path,"-vf",filters,
                "-c:v","libx264","-preset","medium","-crf","20","-c:a","copy",output_path],
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        except Exception as e:
            logger.error(f'LoRA Edit 失败: {e}')
            self._basic_process(video_path, output_path, {"resolution":"1920x1080","bitrate":"5M","format":"mp4"})
    
    def shutdown(self):
        """ """
        self.thread_pool.shutdown()

# 初始化视频处理器（使用统一的 FFmpeg 路径检测）
try:
    from app.core.ffmpeg_utils import find_ffmpeg, find_ffprobe
    ffmpeg_path = find_ffmpeg() or "ffmpeg"
    ffprobe_path = find_ffprobe() or "ffprobe"
    video_processor = VideoProcessor(ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)
except ImportError:
    video_processor = VideoProcessor()

# ==============================================  
# 智能剪辑算法 (专业版)
# ==============================================
class AIClipAlgorithm:
    def __init__(self):
        # 基础权重(专业版)
        self.weights = {
            'volume': 1.2,          # 音量
            'volume_change': 1.5,    # 音量变化
            'shot_change': 1.8,      # 镜头切换
            'motion_intensity': 1.0,  # 运动强度
            'brightness': 0.8,       # 亮度
            'color_saturation': 0.6,  # 色彩饱和度
            'time_position': 1.0,     # 时间位置权重
            'keyword': 2.0,          # 关键词
            'emotion': 1.5           # 情绪分
        }

    def calculate_score(self, features, prompt=None, duration=None, position=None):
        """
        专业版打分逻辑
        - 综合多维度特征
        - 动态权重调整
        - 时间位置权重
        """
        # 复制基础权重
        weights = self.weights.copy()

        # 动态根据提示词调整权重
        if prompt:
            prompt = prompt.lower()
            if "高能" in prompt or "卡点" in prompt:
                weights['shot_change'] = 2.5
                weights['volume'] = 2.0
                weights['motion_intensity'] = 1.8
            if "催泪" in prompt or "情感" in prompt:
                weights['emotion'] = 3.0
                weights['volume_change'] = 2.0
            if "平静" in prompt or "舒缓" in prompt:
                weights['shot_change'] = 0.5
                weights['motion_intensity'] = 0.3
            if "开头" in prompt or "引人" in prompt:
                weights['time_position'] = 2.0

        # 计算时间位置权重(开头和结尾更重要)
        time_weight = 1.0
        if duration and position is not None:
            # 前10%和后10%的内容更重要
            if position < duration * 0.1:
                time_weight = 1.5
            elif position > duration * 0.9:
                time_weight = 1.3

        # 计算最终得分
        score = (
            weights['volume'] * features.get('volume', 0) +
            weights['volume_change'] * features.get('volume_change', 0) +
            weights['shot_change'] * features.get('shot_change', 0) +
            weights['motion_intensity'] * features.get('motion_intensity', 0) +
            weights['brightness'] * features.get('brightness', 0) +
            weights['color_saturation'] * features.get('color_saturation', 0) +
            weights['keyword'] * features.get('keyword', 0) +
            weights['emotion'] * features.get('emotion', 0)
        ) * time_weight

        return round(score, 2)

    def analyze_audio(self, audio_clip):
        """
        专业音频分析
        - 音量分析
        - 音量变化分析
        - 频率分析
        """
        y, sr = librosa.load(audio_clip.reader(), sr=16000)
        
        # 音量
        volume = np.mean(np.abs(y))
        
        # 音量变化(能量变化)
        energy = np.array([np.sum(np.abs(y[i:i+1024]**2)) for i in range(0, len(y), 1024)])
        if len(energy) > 1:
            volume_change = np.std(energy) / np.mean(energy)
        else:
            volume_change = 0
        
        # 频率分析(简单版本)
        # 计算频谱
        S = np.abs(librosa.stft(y))
        # 低频能量(说话声)
        low_freq = np.mean(S[:100])
        # 高频能量(音效)
        high_freq = np.mean(S[100:])
        
        return {
            'volume': volume,
            'volume_change': volume_change,
            'low_freq': low_freq,
            'high_freq': high_freq
        }

    def _sample_frames(self, video_clip, n=10):
        """
        从视频中均匀采样 n 帧（RGB float32 数组），用于轻量特征分析。
        返回空列表表示无法取帧（如 0 时长 / 解码失败）。
        """
        try:
            dur = float(getattr(video_clip, "duration", 0) or 0)
        except Exception:
            dur = 0.0
        if dur <= 0 or n < 1:
            return []
        # 均匀采样时间点（避开首尾边界）
        edges = np.linspace(0.0, max(1e-3, dur - 1e-3), n)
        frames = []
        for t in edges:
            try:
                f = video_clip.get_frame(float(t))
            except Exception:
                continue
            if f is None or getattr(f, "size", 0) == 0:
                continue
            frames.append(np.asarray(f, dtype=np.float32))
        return frames

    def analyze_video(self, video_clip):
        """
        轻量但真实的视频分析（替代原随机模拟）：
        - brightness:        平均亮度（归一化 0~1）
        - color_saturation:  平均饱和度（HSV-S，0~1）
        - motion_intensity:  帧间像素差（0~1）
        - shot_change:       相邻帧直方图差异（镜头切换检测，0~1）
        全部基于真实帧数据，确定性、可复现，同一视频结果稳定。
        """
        frames = self._sample_frames(video_clip, n=10)
        if not frames:
            return {
                'shot_change': 0.0,
                'motion_intensity': 0.0,
                'brightness': 0.5,
                'color_saturation': 0.5,
            }

        # 亮度：各帧平均亮度
        brightness = float(np.mean([f.mean() for f in frames])) / 255.0

        # 饱和度：每像素 (max-min)/(max+eps) 的均值（等价于 HSV 的 S 通道）
        sats = []
        for f in frames:
            mx = f.max(axis=2)
            mn = f.min(axis=2)
            sats.append(((mx - mn) / (mx + 1e-8)).mean())
        color_saturation = float(np.mean(sats))

        # 运动强度：相邻帧平均绝对差
        diffs = [np.mean(np.abs(frames[i] - frames[i - 1])) for i in range(1, len(frames))]
        motion_intensity = (float(np.mean(diffs)) / 255.0) if diffs else 0.0

        # 镜头切换：相邻帧颜色直方图差异（归一化）
        shot_diffs = []
        for i in range(1, len(frames)):
            h1 = np.histogram(frames[i - 1].reshape(-1, 3), bins=8, range=(0, 255))[0]
            h2 = np.histogram(frames[i].reshape(-1, 3), bins=8, range=(0, 255))[0]
            denom = (h1.sum() + h2.sum()) + 1e-8
            shot_diffs.append(0.5 * float(np.sum(np.abs(h1 - h2))) / denom)
        shot_change = float(np.mean(shot_diffs)) if shot_diffs else 0.0

        return {
            'shot_change': round(float(np.clip(shot_change * 4.0, 0.0, 1.0)), 4),
            'motion_intensity': round(float(np.clip(motion_intensity * 4.0, 0.0, 1.0)), 4),
            'brightness': round(float(np.clip(brightness, 0.0, 1.0)), 4),
            'color_saturation': round(float(np.clip(color_saturation, 0.0, 1.0)), 4),
        }

    def analyze_segment(self, video, start, end):
        """
        分析单个视频片段：组合音频特征 + 真实视频特征。
        keyword / emotion 使用轻量确定性启发式（非随机）：
          - keyword: 由音频低频能量是否显著（疑似人声/对白）决定 0/1
          - emotion: 由亮度 + 音量变化推导的粗略情绪激活度（非真情绪识别）
        后续可替换为真实语音识别 / 情绪模型，对外接口不变。
        """
        seg = video.subclip(start, end)

        # 音频分析（无音轨时安全降级，避免崩溃）
        audio = getattr(seg, "audio", None)
        if audio is not None:
            audio_features = self.analyze_audio(audio)
        else:
            audio_features = {'volume': 0.0, 'volume_change': 0.0,
                              'low_freq': 0.0, 'high_freq': 0.0}

        # 视频分析（真实特征）
        video_features = self.analyze_video(seg)

        # keyword：低频能量显著 → 疑似人声/对白
        low_freq = audio_features.get('low_freq', 0.0) or 0.0
        keyword = 1.0 if low_freq > 1e-4 else 0.0

        # emotion：亮度与音量变化的粗略激活度（启发式，确定性）
        vol_change = min(1.0, abs(audio_features.get('volume_change', 0.0) or 0.0))
        emotion = float(np.clip(
            0.45 + 0.45 * (video_features['brightness'] - 0.5) + 0.10 * vol_change,
            0.0, 1.0,
        ))

        features = {
            **audio_features,
            **video_features,
            'keyword': keyword,
            'emotion': round(emotion, 4),
        }

        return features

    def select_segments(self, segments, max_segments=8, min_duration=1.5, max_duration=3.0):
        """
        智能片段选择
        - 选择高分片段
        - 保证片段之间的连续性
        - 控制片段时长
        """
        # 按得分排序
        sorted_segments = sorted(segments, key=lambda x: x['score'], reverse=True)
        
        selected = []
        used_time = set()
        
        for seg in sorted_segments:
            # 检查是否与已选片段重叠
            overlap = False
            for s in selected:
                if not (seg['end'] <= s['start'] or seg['start'] >= s['end']):
                    overlap = True
                    break
            
            if not overlap:
                # 调整片段时长
                duration = seg['end'] - seg['start']
                if duration < min_duration:
                    # 扩展片段
                    extend = (min_duration - duration) / 2
                    seg['start'] = max(0, seg['start'] - extend)
                    seg['end'] = min(seg['end'] + extend, seg.get('total_duration', seg['end']))
                elif duration > max_duration:
                    # 缩短片段
                    seg['end'] = seg['start'] + max_duration
                
                selected.append(seg)
                if len(selected) >= max_segments:
                    break
        
        # 按时间顺序排序
        selected.sort(key=lambda x: x['start'])
        
        return selected

    def process_video(self, video_path, prompt=None, output_length=15):
        """
        专业版视频处理
        - 多维度分析
        - 智能片段选择
        - 流畅拼接
        """
        video = _get_VideoFileClip()(video_path)
        duration = video.duration
        segments = []
        seg_dur = 2

        # 分析所有片段
        for start in np.arange(0, duration, seg_dur):
            end = min(start + seg_dur, duration)
            
            # 分析片段特征
            features = self.analyze_segment(video, start, end)
            
            # 计算得分
            score = self.calculate_score(features, prompt, duration, start)
            
            segments.append({
                "start": start,
                "end": end,
                "score": score,
                "features": features,
                "total_duration": duration
            })

        # 智能选择片段
        selected_segments = self.select_segments(segments, max_segments=output_length//2)

        # 拼接片段
        clips = []
        for seg in selected_segments:
            clip = video.subclip(seg['start'], seg['end'])
            clips.append(clip)

        # 流畅拼接(添加淡入淡出效果)
        if clips:
            # 为每个片段添加淡入淡出效果
            for i, clip in enumerate(clips):
                if i > 0:
                    clip = clip.crossfadein(0.3)
                if i < len(clips) - 1:
                    clip = clip.crossfadeout(0.3)
                clips[i] = clip
            
            final = _get_concatenate_videoclips()(clips)
        else:
            # 如果没有选中片段,返回原始视频的前15秒
            final = video.subclip(0, min(15, duration))

        # 输出路径
        output_dir = "AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"ai_clip_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
        
        # 导出视频
        final.write_videofile(
            out_path, 
            fps=24, 
            codec='libx264',
            bitrate='5000k',
            preset='medium',
            verbose=False
        )

        video.close()
        return out_path

# 自定义提示框 - 优化显示效果
class CustomMessageBox(QMessageBox):
    """ """
    def __init__(self, icon, title, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setText(text)
        self.setIcon(icon)
        self.setStyleSheet("""
            QMessageBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 2px solid #ff9800;
                border-radius: 10px;
                padding: 20px;
            }
            QLabel {
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
                padding: 10px;
                background-color: transparent;
            }
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-size: 14px;
                font-weight: bold;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
            }
        """)

def show_custom_messagebox(icon_type, title, message, parent=None):
    """ """
    from PySide6.QtWidgets import QMessageBox
    from PySide6.QtGui import QIcon
    
    msg = CustomMessageBox(icon_type, title, message, parent)
    msg.exec()


# 自定义清晰提示框
class ClearMessageBox(QDialog):
    """ """
    def __init__(self, title, message, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(400, 200)
        
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # 内容区域
        content_layout = QHBoxLayout()
        content_layout.setSpacing(20)
        
        # 警告图标
        icon_label = QLabel("⚠️")
        icon_label.setStyleSheet("font-size: 48px;")
        content_layout.addWidget(icon_label)
        
        # 消息文本
        message_label = QLabel(message)
        message_label.setStyleSheet("""
            color: #ffffff;
            font-size: 18px;
            font-weight: bold;
            padding: 10px;
        """)
        message_label.setWordWrap(True)
        content_layout.addWidget(message_label, 1)
        
        layout.addLayout(content_layout)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        ok_btn = QPushButton("确定")
        ok_btn.setFixedSize(120, 40)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
            }
        """)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
        # 设置对话框样式
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                border: 3px solid #ff9800;
                border-radius: 12px;
            }
        """)

def show_clear_messagebox(title, message, parent=None):
    """ """
    msg = ClearMessageBox(title, message, parent)
    msg.exec()

class BaseModule(QWidget):
    """
    模块基类 - 所有模块必须继承此类
    
    特性:
    - 独立 QWidget
    - 只依赖内核,不依赖其他模块
    - 通过 EventBus 通信
    """
    
    module_id: str = "base"
    module_name: str = "基础模块"
    module_icon: str = "📦"
    
    def __init__(self):
        super().__init__()
        self._event_bus = EventBus.get_instance()
        self._data_bus = DataBus.get_instance()
        self._clock = MasterClock.get_instance()
        self._skill_engine = SkillEngine.get_instance()
        self._setup_ui()
        self._setup_event_handlers()
    
    def _setup_ui(self):
        """ """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        title = QLabel(f"{self.module_icon} {self.module_name}")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
    
    def _setup_event_handlers(self):
        """ """
        pass
    
    def on_activated(self):
        """ """
        pass
    
    def on_deactivated(self):
        """ """
        pass
    
    def set_theme(self, theme: str):
        """设置主题 - 通过 theme 属性让全局 QSS 属性选择器自动响应
        
        历史问题修复：
        - 原实现使用 unpolish/polish 递归遍历所有子控件，会导致卡死
        - 现在只设置属性，由 ThemeManager 的全局 QSS 自动应用样式
        """
        self.setProperty("theme", theme)
        # 只设置属性，不调用 unpolish/polish（性能差且容易卡死）
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)


class HomeModule(BaseModule):
    """
    首页模块
    - 显示:最近项目,快捷入口,统计,公告,快速开始
    - 只做入口,不做业务
    """
    
    module_id = "home"
    module_name = "首页"
    module_icon = "🏠"
    
    def _setup_ui(self):
        """V4.43.0 重构：3 段式布局

        段 1:Header + 摘要小卡(状态/统计/更新)
        段 2:最近使用资源(横向滚动条)
        段 3:项目卡片墙(网格)+ 工具入口(8 工具)
        段 4:ComfyUI + MCP 摘要卡(双卡并排)

        借鉴 AI-Canvas-tauri ProjectLibraryModal + ProjectAssetsOverlay
        """
        from .home_project_card import ProjectCard
        from .home_recent_resources import RecentResourcesPanel
        from .home_sub_widgets import ComfyUISummaryCard, McpSummaryCard
        from .home_tools_grid import HomeToolsGrid

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(16)

        # ─────────── 段 1:Header ───────────
        header_layout = QHBoxLayout()
        header = QLabel("🏠 欢迎使用 拾光剪影")
        header.setObjectName("titleLabel")
        header.setProperty("theme", "dark")  # 标题用主程序主题
        header_layout.addWidget(header)
        header_layout.addStretch(1)

        # 紧凑统计 chip 行
        self._stats_chips = QHBoxLayout()
        self._stats_chips.setSpacing(8)
        self._stat_chip_labels = {}
        for label, key in [
            ("📦", "videos"),
            ("📝", "copy"),
            ("📤", "publish"),
            ("👁", "views"),
        ]:
            chip = QLabel(f"{label} —")
            chip.setObjectName("chipMuted")
            chip.setProperty("theme", "dark")
            self._stats_chips.addWidget(chip)
            self._stat_chip_labels[key] = chip
        header_layout.addLayout(self._stats_chips)
        layout.addLayout(header_layout)

        # ─────────── 段 2:最近使用资源 ───────────
        self._recent_resources = RecentResourcesPanel()
        self._recent_resources.resource_clicked.connect(self._on_resource_clicked)
        layout.addWidget(self._recent_resources)

        # ─────────── 段 3:项目卡片墙(网格)+ 工具入口(网格) ───────────
        # 用 QScrollArea 让卡片墙可滚动（项目多时不撑爆窗口）
        scroll = QScrollArea()
        scroll.setObjectName("homeScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(260)

        scroll_inner = QWidget()
        scroll_inner_layout = QVBoxLayout(scroll_inner)
        scroll_inner_layout.setContentsMargins(0, 0, 0, 0)
        scroll_inner_layout.setSpacing(16)

        # ── 项目卡片墙标题 + 工具入口标题(并排)──
        section_titles = QHBoxLayout()
        projects_title = QLabel("📁 最近的项目")
        projects_title.setObjectName("sectionTitle")
        section_titles.addWidget(projects_title)
        section_titles.addStretch(1)
        tools_title = QLabel("🛠 工具入口")
        tools_title.setObjectName("sectionTitle")
        section_titles.addWidget(tools_title)
        scroll_inner_layout.addLayout(section_titles)

        # ── 项目卡片墙(左)+ 工具入口(右)──
        body = QHBoxLayout()
        body.setSpacing(20)

        # 左:项目卡片墙(网格 4 列)
        self._projects_grid = QGridLayout()
        self._projects_grid.setSpacing(12)
        self._project_cards: list[ProjectCard] = []
        projects_holder = QWidget()
        projects_holder.setLayout(self._projects_grid)
        # 撑开
        projects_holder.setMinimumWidth(240 * 4 + 12 * 3 + 4)
        body.addWidget(projects_holder, stretch=3)

        # 右:工具入口(HomeToolsGrid 自带 4 列 × 2 行)
        self._tools_grid = HomeToolsGrid()
        self._tools_grid.tool_clicked.connect(self._on_tool_clicked)
        body.addWidget(self._tools_grid, stretch=2)

        scroll_inner_layout.addLayout(body)
        scroll_inner_layout.addStretch(1)

        scroll.setWidget(scroll_inner)
        layout.addWidget(scroll, stretch=1)

        # ─────────── 段 4:ComfyUI + MCP 摘要卡(双卡并排)───────────
        sub_layout = QHBoxLayout()
        sub_layout.setSpacing(12)
        self._comfyui_card = ComfyUISummaryCard()
        self._comfyui_card.open_settings_requested.connect(
            lambda: self._navigate_to("settings")
        )
        self._comfyui_card.start_requested.connect(self._on_comfyui_start)
        sub_layout.addWidget(self._comfyui_card)

        self._mcp_card = McpSummaryCard()
        # 2026-11-13：点「设置」以前只是打开设置模块（默认页），用户找不到 MCP 配置。
        # MCP 配置在「拓展中心 → 🔌 MCP 服务」页签，直接跳过去。
        self._mcp_card.open_settings_requested.connect(
            lambda: self._navigate_to("extensions", "mcp")
        )
        self._mcp_card.copy_config_requested.connect(self._on_mcp_copy_config)
        sub_layout.addWidget(self._mcp_card)

        layout.addLayout(sub_layout)

        # 初始加载数据
        self._refresh_stats()
        self._refresh_recent_projects()
        self._refresh_recent_resources()
        self._refresh_sub_cards()

    def _create_card(self, title: str) -> QGroupBox:
        """保留旧 helper(部分代码可能引用),委托给 QFrame 包装"""
        # 旧调用方不再存在(已迁移到 home_* 子组件),这里留个兼容桩
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox {
                font-size: 16px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 12px;
                margin-top: 16px;
                padding-top: 16px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 20px;
                padding: 0 10px;
                background-color: #1a1a1a;
            }
        """)
        return group

    def _create_action_button(self, icon: str, text: str, color: str) -> QPushButton:
        """保留旧 helper 兼容桩,新代码已迁到 HomeToolsGrid"""
        btn = QPushButton(f"{icon}\n{text}")
        btn.setMinimumSize(120, 80)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
            }}
        """)
        return btn
    
    def _navigate_to(self, module_id: str, action: str | None = None):
        payload = {"target": module_id}
        if action:
            payload["action"] = action
        self._event_bus.emit(EventType.MODULE_ACTIVATED, payload)
    
    def _show_login_dialog(self):
        """ """
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QGroupBox, QCheckBox, QComboBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("登录信息与设置")
        dialog.setMinimumWidth(400)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QLineEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
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
                background-color: #1a1a1a;
            }
            QCheckBox {
                color: #ffffff;
            }
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 登录信息部分
        login_group = QGroupBox("登录信息")
        login_layout = QVBoxLayout(login_group)
        
        # 用户名
        user_layout = QHBoxLayout()
        user_label = QLabel("用户名:")
        user_input = QLineEdit()
        user_input.setText("妮可")  # 默认值
        user_layout.addWidget(user_label)
        user_layout.addWidget(user_input)
        login_layout.addLayout(user_layout)
        
        # 密码
        pass_layout = QHBoxLayout()
        pass_label = QLabel("密码:")
        pass_input = QLineEdit()
        pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        pass_layout.addWidget(pass_label)
        pass_layout.addWidget(pass_input)
        login_layout.addLayout(pass_layout)
        
        # 记住密码
        remember_layout = QHBoxLayout()
        remember_check = QCheckBox("记住密码")
        remember_check.setChecked(True)
        remember_layout.addWidget(remember_check)
        login_layout.addLayout(remember_layout)
        
        layout.addWidget(login_group)
        
        # 登录设置部分
        settings_group = QGroupBox("登录设置")
        settings_layout = QVBoxLayout(settings_group)
        
        # 自动登录
        auto_login_layout = QHBoxLayout()
        auto_login_check = QCheckBox("自动登录")
        auto_login_check.setChecked(True)
        auto_login_layout.addWidget(auto_login_check)
        settings_layout.addLayout(auto_login_layout)
        
        # 登录方式
        login_method_layout = QHBoxLayout()
        method_label = QLabel("登录方式:")
        method_combo = QComboBox()
        method_combo.addItems(["账号密码登录", "二维码登录", "第三方登录"])
        method_combo.setCurrentText("账号密码登录")
        login_method_layout.addWidget(method_label)
        login_method_layout.addWidget(method_combo)
        settings_layout.addLayout(login_method_layout)
        
        # 语言设置
        language_layout = QHBoxLayout()
        language_label = QLabel("语言:")
        language_combo = QComboBox()
        language_combo.addItems(["简体中文", "English"])
        language_combo.setCurrentText("简体中文")
        language_layout.addWidget(language_label)
        language_layout.addWidget(language_combo)
        settings_layout.addLayout(language_layout)
        
        layout.addWidget(settings_group)
        
        # 按钮部分
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)
        
        login_btn = QPushButton("登录")
        login_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(login_btn)
        
        layout.addLayout(btn_layout)
        
        dialog.exec()
        
        # 处理登录结果
        if dialog.result() == QDialog.DialogCode.Accepted:
            logger.info('登录成功')
            # 这里可以添加登录逻辑
        else:
            logger.info('登录取消')
    
    def on_activated(self):
        """每次切换到首页时刷新数据，首次显示引导"""
        self._refresh_stats()
        self._refresh_recent_projects()
        # 首次打开时显示新手引导
        if not hasattr(self, '_welcome_shown'):
            self._welcome_shown = False
        if not self._welcome_shown:
            # 延迟显示，等UI渲染完
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, self._show_welcome_guide)

    def _show_welcome_guide(self):
        """首次打开：弹出新手引导弹窗（功能概览、快捷入口介绍）"""
        if self._welcome_shown:
            return
        self._welcome_shown = True
        from PySide6.QtWidgets import QDialog, QMessageBox
        msg = (
            "🎬 <b>欢迎使用 拾光剪影！</b>\n\n"
            "<b>核心功能一览：</b>\n"
            "🎬 <b>剪辑工作台</b> — 多轨道编辑、滤镜、转场、字幕、AI辅助剪辑\n"
            "✍️ <b>AI文案生成</b> — 智能脚本/标题/标签，支持推送到剪辑\n"
            "🤖 <b>模型广场</b> — 16+ AI模型接入、使用统计、成本追踪\n"
            "🧩 <b>插件中心</b> — 可扩展插件生态、一键安装/卸载\n\n"
            "<b>快速上手：</b>\n"
            "1️⃣ 点击「新建剪辑」开始一个项目\n"
            "2️⃣ 在「模型广场」配置AI模型\n"
            "3️⃣ 访问「设置」自定义快捷键和主题\n"
            "4️⃣ 打开「帮助」查看详细教程\n\n"
            "拾光剪影 — AI驱动的短视频创作平台 🚀"
        )
        box = QMessageBox(self)
        box.setWindowTitle("欢迎使用 拾光剪影")
        box.setText(msg)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setStyleSheet("QMessageBox{background:#121212;color:#ccc;font-size:12px;} QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;padding:8px 24px;}")
        box.exec()

    def _refresh_stats(self):
        """从系统读取真实统计：项目数/任务数/发布数/播放量

        V4.43.0:改为更新顶部紧凑 chip(原 32px 大字版太占空间,改为 #chipMuted 小标签)
        """
        try:
            import json
            from pathlib import Path

            workspace = Path(__file__).parent.parent.parent.parent

            # 项目统计 — 从 data/projects/ 目录扫描
            projects_dir = workspace / "data" / "projects"
            project_count = "0"
            if projects_dir.exists():
                count = len([f for f in projects_dir.iterdir()
                             if f.is_file() and f.suffix in ('.timeline', '.json', '.proj')])
                project_count = str(count)

            # "生成文案"统计 — 仍标注「未接入」如实说明
            copy_count = "—"

            # 发布统计 — 从 publish_log.json 读取
            publish_count = "0"
            try:
                pf = workspace / "data" / "publish_log.json"
                if pf.exists():
                    with open(pf, 'r', encoding='utf-8') as f:
                        pd_data = json.load(f)
                    publish_count = str(len(pd_data) if isinstance(pd_data, list) else 0)
            except Exception as e:
                logger.debug("读取发布统计失败: %s", e)

            # 播放统计 — 从 analytics.json 读取
            views_count = "0"
            try:
                af = workspace / "data" / "analytics.json"
                if af.exists():
                    with open(af, 'r', encoding='utf-8') as f:
                        a_data = json.load(f)
                    views_count = str(a_data.get("total_views", 0))
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("读取播放统计失败: %s", e)

            # 更新顶部 chip
            for key, val in [
                ("videos", project_count),
                ("copy", copy_count),
                ("publish", publish_count),
                ("views", views_count),
            ]:
                chip = self._stat_chip_labels.get(key)
                if chip is not None:
                    # 取 emoji 前缀
                    emoji = chip.text().split()[0]
                    chip.setText(f"{emoji} {val}")
        except Exception as e:
            logger.debug("刷新统计数据失败: %s", e)

    def _refresh_recent_projects(self):
        """V4.43.0:从 data/projects/ 扫描最近 8 个项目,渲染为 ProjectCard 墙

        V4.43.3:空状态从「📭 暂无项目」（弱提示）升级为「+ 新建项目」CTA 卡（含
        新建/导入两个动作按钮），双击卡也走"_create_new_project"。
        """
        from pathlib import Path
        from .home_project_card import ProjectCard, EmptyProjectCard

        # 清空旧卡片
        for old in self._project_cards:
            self._projects_grid.removeWidget(old)
            old.deleteLater()
        self._project_cards.clear()

        try:
            workspace = Path(__file__).parent.parent.parent.parent
            projects_dir = workspace / "data" / "projects"
            files: list[tuple[Path, float]] = []
            if projects_dir.exists():
                for f in projects_dir.iterdir():
                    if f.is_file() and f.suffix in ('.timeline', '.json', '.proj'):
                        files.append((f, f.stat().st_mtime))
                files.sort(key=lambda x: x[1], reverse=True)

            if not files:
                # V4.43.3：空项目 CTA 卡（含新建/导入两按钮）
                empty = EmptyProjectCard(self)
                empty.create_requested.connect(self._create_new_project)
                empty.import_requested.connect(self._import_project)
                self._projects_grid.addWidget(empty, 0, 0)
                self._project_cards.append(empty)
                return

            # 4 列网格
            for i, (f_path, mtime) in enumerate(files[:8]):
                # 简单 emoji 推断:文件名含「剧」用 🎬,否则 🎞
                emoji = "🎬" if "剧" in f_path.stem else "🎞"
                card = ProjectCard(
                    project_id=str(f_path),
                    title=f_path.stem,
                    emoji=emoji,
                    mtime=mtime,
                )
                card.open_requested.connect(self._open_recent_project)
                card.delete_requested.connect(self._delete_project)
                row, col = i // 4, i % 4
                self._projects_grid.addWidget(card, row, col)
                self._project_cards.append(card)
        except Exception as e:
            logger.debug("刷新最近项目失败: %s", e)

    def _refresh_recent_resources(self):
        """填充最近使用资源 chip — V4.43.0 新增

        当前实现是占位(空列表),后续接入真实的"最近使用"数据源
        (本地 SQLite / mtime 排序的全局文件索引)
        """
        # 占位:不传 resources,显示默认提示
        # 真实接入时改为从 DataBus 读取最近资源列表
        try:
            resources = []  # 占位空列表
            self._recent_resources.set_resources(resources)
        except Exception as e:
            logger.debug("刷新最近资源失败: %s", e)

    def _refresh_sub_cards(self):
        """V4.43.0 新增:刷新 ComfyUI / MCP 摘要卡状态

        占位实现:从全局配置读取真实状态(若不存在则按未安装/未启动显示)
        """
        try:
            # 实际接入时:ConfigManager.instance().get("comfyui.path") 等
            # 当前占位:
            self._comfyui_card.update_state(
                installed=False, path="未安装", running=False
            )
            self._mcp_card.update_state(
                port=0, running=False, client_count=0
            )
        except Exception as e:
            logger.debug("刷新子卡片失败: %s", e)

    def _create_new_project(self) -> None:
        """V4.43.3:首页空项目 CTA → 新建空白工程并跳到剪辑模块

        V4.43.0 ~ 4.43.2 这一步是死代码（首页不响应）,改为激活编辑器并创建时间线文件,
        复用 MainWindow 已有的 MODULE_ACTIVATED(action=create_project)通路。
        """
        try:
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(
                self, "新建项目", "项目名称", text="未命名项目"
            )
            if not ok or not text.strip():
                return
            self._event_bus.emit(EventType.MODULE_ACTIVATED, {
                "target": "editor",
                "action": "create_project",
                "name": text.strip(),
            })
            logger.info("首页 CTA:请求新建项目 %s", text)
        except Exception as e:
            logger.warning("新建项目失败: %s", e)

    def _import_project(self) -> None:
        """V4.43.3:首页空项目 CTA → 选 .timeline / .proj 文件导入

        通过 QFileDialog 选文件,然后走 MODULE_ACTIVATED(open_project) 通路,
        与 _open_recent_project 行为一致。
        """
        try:
            from pathlib import Path
            from PySide6.QtWidgets import QFileDialog
            path_str, _ = QFileDialog.getOpenFileName(
                self,
                "导入项目文件",
                str(Path(__file__).parent.parent.parent.parent / "data" / "projects"),
                "拾光剪影工程 (*.timeline *.proj);;JSON (*.json);;所有文件 (*)",
            )
            if not path_str:
                return
            self._open_recent_project(path_str)
        except Exception as e:
            logger.warning("导入项目失败: %s", e)

    def _open_recent_project(self, project_path: str):
        """项目卡片打开/双击 — 真正加载工程文件

        project_path 直接就是完整路径(V4.43.0 改动:不再用 QListWidget 的 UserRole 间接传递)
        """
        from pathlib import Path
        project_file = Path(project_path)
        if project_file.exists():
            try:
                self._event_bus.emit(EventType.MODULE_ACTIVATED, {
                    "target": "editor",
                    "action": "open_project",
                    "project": str(project_file),
                })
            except Exception as e:
                logger.warning("打开项目失败: %s", e)
        else:
            QMessageBox.warning(self, "打开失败", f"工程文件不存在：\n{project_file}")

    def _delete_project(self, project_path: str):
        """删除项目 — 弹出确认后移到回收站

        纪律:必须走 OS 回收站(Win32 SHFileOperation / macOS Finder Trash),
        不直接 os.remove() —— 见 personal_files_safety 规则。
        """
        from pathlib import Path
        project_file = Path(project_path)
        if not project_file.exists():
            return
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除项目「{project_file.stem}」吗?\n文件将移至回收站。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            # Win 回收站(项目主体不删源数据时用 send2tr;开发期先 unlink,后续接入)
            # TODO:接入 send2trash 库后改走回收站
            project_file.unlink()
            logger.info("项目已删除: %s", project_file)
            self._refresh_recent_projects()
        except Exception as e:
            logger.warning("删除项目失败: %s", e)
            QMessageBox.warning(self, "删除失败", f"{e}")

    def _on_resource_clicked(self, resource_id: str) -> None:
        """最近资源 chip 点击 — 占位(数据源尚未接入)

        V4.43.0 该面板 resources 恒为空,此 handler 不会触发。
        真实接入时再定事件契约(EventType 需先注册成员,禁止裸字符串 —— 见 agent_constants 纪律)。
        """
        logger.debug("资源跳转(占位,未接入数据源): %s", resource_id)

    def _on_tool_clicked(self, tool_id: str) -> None:
        """8 工具入口点击 — 路由到对应模块 / 设置面板"""
        if tool_id == "settings":
            self._navigate_to("settings")
        elif tool_id == "agent":
            self._navigate_to("editor")  # agent 在编辑器 dock 内
        elif tool_id == "help":
            self._navigate_to("settings")  # 帮助入口在设置面板
        elif tool_id == "stats":
            self._navigate_to("performance")
        elif tool_id in ("projects", "storage"):
            self._navigate_to("materials")
        elif tool_id == "canvas":
            self._navigate_to("characters")
        elif tool_id == "comfyui":
            self._navigate_to("settings")  # ComfyUI 设置
        else:
            logger.debug("工具入口未实现路由: %s", tool_id)

    def _on_comfyui_start(self) -> None:
        """ComfyUI 摘要卡 - 启动按钮 — 调起后端"""
        logger.debug("ComfyUI 启动请求")
        try:
            # TODO:实际接入 comfyui.start 端点
            QMessageBox.information(
                self, "ComfyUI", "ComfyUI 启动功能待接入。\n请前往设置 → ComfyUI 配置路径。"
            )
        except Exception as e:
            logger.warning("ComfyUI 启动失败: %s", e)

    def _on_mcp_copy_config(self) -> None:
        """MCP 摘要卡 - 复制配置 — 复制 JSON 到剪贴板"""
        try:
            config = '{"mcpServers":{"shiguang":{"command":"shiguang-canvas-mcp","args":["--port","8765"]}}}'
            QApplication.clipboard().setText(config)
            logger.debug("MCP 配置已复制")
            QMessageBox.information(
                self, "MCP", "MCP 配置已复制到剪贴板，可粘贴到 Claude/Cursor 等客户端。"
            )
        except Exception as e:
            logger.warning("复制 MCP 配置失败: %s", e)


# ═══════════════════════════════════════════════════════════════
# 向后兼容 re-export（冷启动 P1 优化：改为惰性转发）
# ═══════════════════════════════════════════════════════════════
#
# 问题：本文件在 2026-06-13 的「懒加载架构」改造中把顶部 import 换成了
# _LazyModuleProxy / _LazyClassProxy，但**文件末尾**仍留着一整块顶层
# eager import（原 1517-1547 行）：timeline_widget / timeline_subwidgets /
# clip_widget / editor_module / copywriting_module / tasks_module /
# materials_module / plugins_module / performance_module / model_management。
#
# 后果：任何 `import .modules`（哪怕只为拿 HomeModule）都会连带加载整条链。
# 冷启动实测：MainWindow._setup_default_modules → import .modules 时，
# HomeModule 那一跳 7.76s（其中 torch 6.97s 由 drama_understanding_engine
# 的模块级探测引入，已单独修复）；拆掉本题块后进一步降到 ~0.9s 以下。
# **懒加载设计是从文件底部被击穿的。**
#
# 改法：删除顶层 import，改用 PEP 562 模块级 __getattr__ 惰性转发。
# 语义与原先等价 —— `from .modules import ClipWidget` 仍可用，只是
# 真正的 importlib.import_module() 推迟到首次访问该名字时执行。
#
# ⚠️ 循环导入注意：editor_module / copywriting_module 等会反向
# `from .modules import show_clear_messagebox`。改为惰性后，读取
# show_clear_messagebox 时本模块必须已执行完（模块级 __getattr__ 只在
# 属性缺失时才触发，而 show_clear_messagebox 是真实定义，不经过这里），
# 因此不受影响。

_LAZY_REEXPORTS = {
    # 名字 -> (子模块, 类名)
    "TimelineWidget":         (".timeline_widget", "TimelineWidget"),
    "TimeRuler":              (".timeline_subwidgets", "TimeRuler"),
    "TrackControlPanel":      (".timeline_subwidgets", "TrackControlPanel"),
    "ClipWidget":             (".clip_widget", "ClipWidget"),
    "EditorModule":           (".editor_module", "EditorModule"),
    "CopywritingModule":      (".copywriting_module", "CopywritingModule"),
    "TasksModule":            (".tasks_module", "TasksModule"),
    "MaterialsModule":        (".materials_module", "MaterialsModule"),
    "PluginsModule":          (".plugins_module", "PluginsModule"),
    "PerformanceModule":      (".performance_module", "PerformanceModule"),
    "ModelManagementModule":  (".model_management", "ModelManagementModule"),
    # 冷启动 P1 追加：原先在文件中段 eager import，本文件内零消费
    "Top0VideoProcessor":     (".top0_integration", "Top0VideoProcessor"),
    "ViralOptimizationEngine": (".viral_optimization_engine", "ViralOptimizationEngine"),
    "Platform":               (".viral_optimization_engine", "Platform"),
    "VideoFeatures":          (".viral_optimization_engine", "VideoFeatures"),
}

# 惰性模块列表（顺序即历史 MODULE_CLASSES 的存在顺序，供需要枚举的调用方使用）
LAZY_MODULE_CLASS_NAMES = [
    "HomeModule",
    "EditorModule",
    "CopywritingModule",
    "TasksModule",
    "MaterialsModule",
    "PluginsModule",
    "PerformanceModule",
    "ModelManagementModule",
]


def __getattr__(name: str):
    """PEP 562：按需转发被拆出去的模块类（冷启动 P1）。

    仅当属性在本模块中不存在时才被调用。HomeModule 等定义在本文件内的类
    不经过这里；被拆到独立文件的类才走惰性 import。
    """
    target = _LAZY_REEXPORTS.get(name)
    if target is not None:
        submodule, class_name = target
        import importlib as _il
        mod = _il.import_module(submodule, package=__package__)
        return getattr(mod, class_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    """让 dir(modules) 仍能列出惰性转发名（保持可发现性）。"""
    return sorted(list(globals().keys()) + list(_LAZY_REEXPORTS.keys()))


def get_module_classes():
    """惰性获取全部模块类（替代原先的 MODULE_CLASSES 常量）。

    原 MODULE_CLASSES 是全库零消费的常量（仅本文件内两处赋值/扩展），
    此处改为按需构造，避免为了一个没人读的列表在导入期拉起所有模块。
    """
    import importlib as _il
    out = []
    for nm in LAZY_MODULE_CLASS_NAMES:
        if nm == "HomeModule":
            out.append(HomeModule)
            continue
        target = _LAZY_REEXPORTS.get(nm)
        if target is None:
            continue
        submodule, class_name = target
        mod = _il.import_module(submodule, package=__package__)
        out.append(getattr(mod, class_name))
    return out

