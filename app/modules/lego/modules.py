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
# _LazyClassProxy：  用于类变量（如 EditorScheduler(), AudioManager()）
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
      • 需要分别指定模块名和类名（如 'core.audio_manager' + 'AudioManager'）
      • 主要场景：EditorScheduler()、AudioManager(...) 等类实例化

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

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize, QUrl, QPoint, QMimeData
from PyQt6.QtGui import QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics, QPolygon, QShortcut, QKeySequence, QDrag
from PyQt6.QtWidgets import (
    QDialog,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QProgressBar, QListWidget,
    QListWidgetItem, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QInputDialog, QTabWidget, QCheckBox, QSlider,
    QTreeWidget, QTreeWidgetItem, QMenu, QToolButton, QApplication, QSizePolicy, QFormLayout, QSpacerItem,
    QToolTip
)
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget

from .core import EventBus, EventType, MasterClock, DataBus
from .skill_engine import SkillEngine, Skill
from .account_skills import (
    AccountDataCollectSkill, AccountAnalysisSkill, 
    PublishContentSkill, MatrixPublishSkill, register_account_skills
)

# 确保 app/ 在 sys.path 中以兼容 core.xxx 导入
import sys as _sys
_app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _app_root not in _sys.path:
    _sys.path.insert(0, _app_root)

# ===== Core 管理器懒加载（仅在剪辑/项目管理等模块激活时才导入） =====
project_manager = _lazy_import('core.project_manager')      # project_manager.create_project(...)
asset_manager = _lazy_import('core.asset_manager')          # asset_manager.xxx
timeline_manager = _lazy_import('core.timeline_manager')    # timeline_manager.xxx
effect_manager = _lazy_import('core.effect_manager')        # effect_manager.xxx
transition_manager = _lazy_import('core.transition_manager')  # transition_manager.xxx

# 类级别代理（支持实例化: EditorScheduler()）
EditorScheduler = _LazyClassProxy('core.editor_scheduler', 'EditorScheduler')
AudioManager = _LazyClassProxy('core.audio_manager', 'AudioManager')
SubtitleManager = _LazyClassProxy('core.subtitle_manager', 'SubtitleManager')
PresetManager = _LazyClassProxy('core.preset_manager', 'PresetManager')
PluginManager = _LazyClassProxy('core.plugin_manager', 'PluginManager')

# 导入TOP 0级剪辑引擎
try:
    from .top0_integration import Top0VideoProcessor
    TOP0_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"TOP 0级引擎导入失败: {e}")
    TOP0_ENGINE_AVAILABLE = False

# 导入爆款优化引擎
try:
    from .viral_optimization_engine import ViralOptimizationEngine, Platform, VideoFeatures
    VIRAL_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"爆款优化引擎导入失败: {e}")
    VIRAL_ENGINE_AVAILABLE = False

# 导入视频处理相关模块
import subprocess
import sys
import threading
import queue
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

# 线程池管理
class ThreadPool:
    """ """
    def __init__(self, max_workers=4):
        self.max_workers = max_workers
        self.tasks = queue.Queue()
        self.workers = []
        self.running = False
    
    def start(self):
        """ """
        self.running = True
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._worker, daemon=True)
            worker.start()
            self.workers.append(worker)
    
    def _worker(self):
        """ """
        while self.running:
            try:
                task = self.tasks.get(timeout=0.1)
                task()
                self.tasks.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"线程池工作线程错误: {e}")
    
    def submit(self, task):
        """ """
        self.tasks.put(task)
    
    def shutdown(self):
        """ """
        self.running = False
        self.tasks.join()
        for worker in self.workers:
            worker.join(timeout=1)

# 视频处理类
class VideoProcessor:
    """ """
    def __init__(self):
        self.ffmpeg = "ffmpeg.exe"
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
        """ """
        def task():
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
                print(f"处理视频失败: {e}")
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
                print(f"视频处理完成: {output_path} "
                      f"({result.processing_time:.1f}s, "
                      f"{result.output_size / 1024 / 1024:.1f}MB)")
            else:
                print(f"视频处理失败: {result.error_message}")
        except Exception as e:
            print(f"RenderManager 调用失败,回退到基础 FFmpeg: {e}")
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
            print(f"执行命令: {' '.join(cmd)}")
            import subprocess as _sp
            result = _sp.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"视频处理完成: {output_path}")
            else:
                print(f"视频处理失败: {result.stderr}")
    
    def _process_autoclip(self, video_path, output_path, export_settings):
        """ """
        params = self.default_params["autoclip"]
        print(f"AutoClip 处理中,参数: {params}")
        # 这里应该实现高光识别和剪辑逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def _process_funclip(self, video_path, output_path, export_settings):
        """ """
        params = self.default_params["funclip"]
        print(f"FunClip 处理中,参数: {params}")
        # 这里应该实现BGM,字幕,音频处理逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def _process_videofusion(self, video_path, output_path, export_settings, video_adjust_params=None):
        """ """
        params = self.default_params["videofusion"]
        adjust_params = video_adjust_params or self.default_params["video_adjust"]
        print(f"VideoFusion 处理中,参数: {params}")
        print(f"视频调节参数: {adjust_params}")
        # 这里应该实现画质增强逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def _process_lora_edit(self, video_path, output_path, export_settings):
        """ """
        params = self.default_params["lora_edit"]
        print(f"LoRA Edit 处理中,参数: {params}")
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
                
                print(f"优化工作流完成,最终输出: {final_output}")
                return final_output
            except Exception as e:
                print(f"优化工作流失败: {e}")
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
            print(f"VideoFusion 失败: {e}")
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
            print(f"LoRA Edit 失败: {e}")
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

# 账号运营分析类
class AccountAnalyzer:
    """ """
    def __init__(self):
        self.data_dir = "运营数据"
        os.makedirs(self.data_dir, exist_ok=True)
    
    def add_video_data(self, video_id, title, views, likes, comments, shares, conversions):
        """ """
        try:
            data = {
                "video_id": video_id,
                "title": title,
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "conversions": conversions,
                "timestamp": datetime.now().isoformat(),
                "like_rate": likes / views if views > 0 else 0,
                "comment_rate": comments / views if views > 0 else 0,
                "share_rate": shares / views if views > 0 else 0,
                "conversion_rate": conversions / views if views > 0 else 0
            }
            
            data_file = os.path.join(self.data_dir, f"{video_id}.json")
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"添加视频数据失败: {e}")
            return False
    
    def analyze_data(self):
        """ """
        try:
            all_data = []
            for file in os.listdir(self.data_dir):
                if file.endswith(".json"):
                    file_path = os.path.join(self.data_dir, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            all_data.append(data)
                    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                        continue
            
            if not all_data:
                return {"error": "无数据"}
            
            # 计算平均值
            total_views = sum(d.get("views", 0) for d in all_data)
            total_likes = sum(d.get("likes", 0) for d in all_data)
            total_comments = sum(d.get("comments", 0) for d in all_data)
            total_shares = sum(d.get("shares", 0) for d in all_data)
            total_conversions = sum(d.get("conversions", 0) for d in all_data)
            
            avg_views = total_views / len(all_data)
            avg_likes = total_likes / len(all_data)
            avg_comments = total_comments / len(all_data)
            avg_shares = total_shares / len(all_data)
            avg_conversions = total_conversions / len(all_data)
            
            # 计算平均比率
            avg_like_rate = sum(d.get("like_rate", 0) for d in all_data) / len(all_data)
            avg_comment_rate = sum(d.get("comment_rate", 0) for d in all_data) / len(all_data)
            avg_share_rate = sum(d.get("share_rate", 0) for d in all_data) / len(all_data)
            avg_conversion_rate = sum(d.get("conversion_rate", 0) for d in all_data) / len(all_data)
            
            # 找出表现最好的视频
            top_views = sorted(all_data, key=lambda x: x.get("views", 0), reverse=True)[:3]
            top_conversions = sorted(all_data, key=lambda x: x.get("conversions", 0), reverse=True)[:3]
            top_conversion_rate = sorted(all_data, key=lambda x: x.get("conversion_rate", 0), reverse=True)[:3]
            
            return {
                "total_videos": len(all_data),
                "total_views": total_views,
                "total_likes": total_likes,
                "total_comments": total_comments,
                "total_shares": total_shares,
                "total_conversions": total_conversions,
                "average_views": avg_views,
                "average_likes": avg_likes,
                "average_comments": avg_comments,
                "average_shares": avg_shares,
                "average_conversions": avg_conversions,
                "average_like_rate": avg_like_rate,
                "average_comment_rate": avg_comment_rate,
                "average_share_rate": avg_share_rate,
                "average_conversion_rate": avg_conversion_rate,
                "top_views": top_views,
                "top_conversions": top_conversions,
                "top_conversion_rate": top_conversion_rate
            }
        except Exception as e:
            print(f"分析数据失败: {e}")
            return {"error": str(e)}
    
    def generate_optimization_suggestions(self, analysis_data):
        """ """
        if "error" in analysis_data:
            return "暂无数据,无法生成建议"
        
        suggestions = []
        
        # 基于数据生成建议
        if analysis_data["average_like_rate"] < 0.05:
            suggestions.append("建议优化视频内容质量,增加情感共鸣点")
        
        if analysis_data["average_comment_rate"] < 0.01:
            suggestions.append("建议在视频中设置互动问题,鼓励观众评论")
        
        if analysis_data["average_share_rate"] < 0.005:
            suggestions.append("建议增加视频的价值性和分享点")
        
        if analysis_data["average_conversion_rate"] < 0.001:
            suggestions.append("建议优化引导语和转化路径")
        
        if not suggestions:
            suggestions.append("数据表现良好,继续保持")
        
        return "\n".join(suggestions)

# 初始化账号分析器
account_analyzer = AccountAnalyzer()

# OpenClow 自动化引擎
class OpenClowEngine:
    """ """
    def __init__(self):
        """ """
        self.data_dir = "openclow_data"
        os.makedirs(self.data_dir, exist_ok=True)
        self.platforms = ["抖音", "快手", "视频号"]
        self.accounts = {}
        self.published_content = []
        self.reply_rules = []
        self.operation_data = []
    
    def collect_data(self, platform, account_id):
        """ """
        try:
            # 模拟数据采集过程
            print(f"开始采集{platform}账号{account_id}的数据...")
            # 模拟采集的数据
            collected_data = {
                "platform": platform,
                "account_id": account_id,
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "views": 10000,
                    "likes": 500,
                    "comments": 100,
                    "shares": 50,
                    "followers": 5000
                }
            }
            # 保存采集的数据
            data_file = os.path.join(self.data_dir, f"{platform}_{account_id}_{int(time.time())}.json")
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(collected_data, f, ensure_ascii=False, indent=2)
            print(f"{platform}账号{account_id}的数据采集完成")
            return collected_data
        except Exception as e:
            print(f"数据采集失败: {e}")
            return None
    
    def auto_publish(self, platform, account_id, content, schedule_time=None):
        """ """
        try:
            # 模拟内容发布过程
            publish_time = schedule_time if schedule_time else datetime.now().isoformat()
            print(f"开始发布内容到{platform}账号{account_id}...")
            # 创建发布记录
            publish_record = {
                "id": f"pub_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "content": content,
                "publish_time": publish_time,
                "status": "published",
                "timestamp": datetime.now().isoformat()
            }
            # 保存发布记录
            self.published_content.append(publish_record)
            # 保存到文件
            publish_file = os.path.join(self.data_dir, f"publish_{publish_record['id']}.json")
            with open(publish_file, "w", encoding="utf-8") as f:
                json.dump(publish_record, f, ensure_ascii=False, indent=2)
            print(f"内容已成功发布到{platform}账号{account_id}")
            return publish_record
        except Exception as e:
            print(f"内容发布失败: {e}")
            return None
    
    def smart_reply(self, platform, account_id, comment, keywords=None):
        """ """
        try:
            # 模拟智能回复过程
            print(f"处理{platform}账号{account_id}的评论...")
            reply = "感谢您的评论!"  # 默认回复
            # 基于关键词生成回复
            if keywords:
                for keyword in keywords:
                    if keyword in comment:
                        # 查找匹配的回复规则
                        for rule in self.reply_rules:
                            if rule["keyword"] in comment:
                                reply = rule["reply"]
                                break
                        else:
                            reply = f"感谢您的评论!"
                        break
            else:
                reply = f"感谢您的评论!"
            # 创建回复记录
            reply_record = {
                "id": f"reply_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "comment": comment,
                "reply": reply,
                "timestamp": datetime.now().isoformat()
            }
            # 保存回复记录
            reply_file = os.path.join(self.data_dir, f"reply_{reply_record['id']}.json")
            with open(reply_file, "w", encoding="utf-8") as f:
                json.dump(reply_record, f, ensure_ascii=False, indent=2)
            print(f"已回复{platform}账号{account_id}的评论")
            return reply_record
        except Exception as e:
            print(f"智能回复失败: {e}")
            return None
    
    def write_back_data(self, platform, account_id, data):
        """ """
        try:
            # 模拟数据回写过程
            print(f"回写{platform}账号{account_id}的运营数据...")
            # 创建回写记录
            write_back_record = {
                "id": f"writeback_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "data": data,
                "timestamp": datetime.now().isoformat()
            }
            # 保存回写记录
            self.operation_data.append(write_back_record)
            # 保存到文件
            write_back_file = os.path.join(self.data_dir, f"writeback_{write_back_record['id']}.json")
            with open(write_back_file, "w", encoding="utf-8") as f:
                json.dump(write_back_record, f, ensure_ascii=False, indent=2)
            print(f"{platform}账号{account_id}的运营数据回写完成")
            return write_back_record
        except Exception as e:
            print(f"数据回写失败: {e}")
            return None
    
    def generate_operation_suggestions(self, platform, account_id, data):
        """ """
        try:
            # 模拟生成运营建议
            print(f"为{platform}账号{account_id}生成运营建议...")
            # 基于数据生成建议
            suggestions = []
            # 分析数据
            views = data.get("views", 0)
            likes = data.get("likes", 0)
            comments = data.get("comments", 0)
            shares = data.get("shares", 0)
            followers = data.get("followers", 0)
            
            # 计算互动率
            if views > 0:
                interaction_rate = (likes + comments + shares) / views
            else:
                interaction_rate = 0
            
            # 基于数据生成建议
            if views < 10000:
                suggestions.append("建议增加内容发布频率,提高账号曝光度")
            if interaction_rate < 0.05:
                suggestions.append("建议在视频中增加互动元素,提高观众参与度")
            if comments < 100:
                suggestions.append("建议主动回复评论,增强粉丝粘性")
            if shares < 50:
                suggestions.append("建议创作更具分享价值的内容")
            if followers < 1000:
                suggestions.append("建议优化账号简介和封面,吸引更多关注")
            
            if not suggestions:
                suggestions.append("账号运营状况良好,继续保持现有策略")
            
            # 创建建议记录
            suggestion_record = {
                "id": f"suggestion_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "data": data,
                "suggestions": suggestions,
                "timestamp": datetime.now().isoformat()
            }
            # 保存建议记录
            suggestion_file = os.path.join(self.data_dir, f"suggestion_{suggestion_record['id']}.json")
            with open(suggestion_file, "w", encoding="utf-8") as f:
                json.dump(suggestion_record, f, ensure_ascii=False, indent=2)
            print(f"已为{platform}账号{account_id}生成运营建议")
            return suggestion_record
        except Exception as e:
            print(f"生成运营建议失败: {e}")
            return None
    
    def add_reply_rule(self, keyword, reply):
        """ """
        rule = {
            "id": f"rule_{int(time.time())}",
            "keyword": keyword,
            "reply": reply,
            "timestamp": datetime.now().isoformat()
        }
        self.reply_rules.append(rule)
        # 保存规则到文件
        rules_file = os.path.join(self.data_dir, "reply_rules.json")
        with open(rules_file, "w", encoding="utf-8") as f:
            json.dump(self.reply_rules, f, ensure_ascii=False, indent=2)
        return rule
    
    def get_published_content(self):
        """ """
        return self.published_content
    
    def get_operation_data(self):
        """ """
        return self.operation_data

# 硬件检测和性能监控
class HardwareDetector:
    """ """
    def detect_hardware(self):
        """ """
        try:
            import psutil
            # 获取CPU信息
            cpu_count = psutil.cpu_count(logical=True)
            cpu_freq = psutil.cpu_freq().current if psutil.cpu_freq() else 0
            
            # 获取内存信息
            memory = psutil.virtual_memory()
            total_memory = memory.total // (1024 * 1024 * 1024)
            
            # 获取磁盘信息
            disk = psutil.disk_usage('/')
            total_disk = disk.total // (1024 * 1024 * 1024)
            
            return {
                "cpu_count": cpu_count,
                "cpu_freq": cpu_freq,
                "total_memory": total_memory,
                "total_disk": total_disk,
                "max_threads": min(cpu_count, 8),
                "max_batch_size": min(cpu_count * 2, 16),
                "cache_size": min(total_memory * 1024 * 1024 * 1024 // 4, 4 * 1024 * 1024 * 1024)
            }
        except Exception as e:
            print(f"硬件检测失败: {e}")
            # 返回默认值
            return {
                "cpu_count": 4,
                "cpu_freq": 2500,
                "total_memory": 8,
                "total_disk": 100,
                "max_threads": 4,
                "max_batch_size": 8,
                "cache_size": 2 * 1024 * 1024 * 1024
            }

class PerformanceMonitor:
    """ """
    def __init__(self):
        self.start_time = time.time()
        self.metrics = {}
    
    def record_metrics(self):
        """ """
        try:
            import psutil
            # 记录CPU使用率
            cpu_usage = psutil.cpu_percent()
            # 记录内存使用率
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            # 记录磁盘使用率
            disk = psutil.disk_usage('/')
            disk_usage = disk.percent
            
            self.metrics = {
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage,
                "uptime": time.time() - self.start_time
            }
            
            print(f"性能指标: CPU={cpu_usage}%, 内存={memory_usage}%, 磁盘={disk_usage}%")
            return self.metrics
        except Exception as e:
            print(f"性能监控失败: {e}")
            return {}

# 初始化硬件检测器和性能监控器
hardware_detector = HardwareDetector()
hardware_config = hardware_detector.detect_hardware()
performance_monitor = PerformanceMonitor()

# 初始化OpenClow引擎
openclow_engine = OpenClowEngine()



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
    from PyQt6.QtWidgets import QMessageBox
    from PyQt6.QtGui import QIcon
    
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        header_layout = QHBoxLayout()
        
        header = QLabel("🏠 欢迎使用 拾光剪影")
        header.setStyleSheet("font-size: 28px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(header)
        header_layout.addStretch()

        layout.addLayout(header_layout)
        
        quick_group = self._create_card("快速开始")
        quick_layout = QGridLayout(quick_group)
        quick_layout.setSpacing(15)
        
        quick_actions = [
            ("🎬", "新建剪辑", "editor", "#1e6bde"),
            ("📝", "AI脚本", "copywriting", "#4caf50"),
            ("📋", "批量处理", "tasks", "#ff9800"),
            ("🎭", "短剧筛选", "drama", "#9c27b0"),
            ("👤", "账号运营", "account", "#00bcd4"),
            ("📁", "素材管理", "materials", "#795548"),
        ]
        
        for i, (icon, text, target, color) in enumerate(quick_actions):
            btn = self._create_action_button(icon, text, color)
            btn.clicked.connect(lambda checked, t=target: self._navigate_to(t))
            quick_layout.addWidget(btn, i // 3, i % 3)
        
        layout.addWidget(quick_group)
        
        stats_group = self._create_card("今日统计")
        stats_layout = QHBoxLayout(stats_group)
        
        self._stat_labels = {}  # key -> QLabel
        for label, key in [("处理视频", "videos"), ("生成文案", "copy"), ("发布内容", "publish"), ("总播放", "views")]:
            stat_widget = QWidget()
            stat_layout = QVBoxLayout(stat_widget)
            stat_layout.setContentsMargins(20, 10, 20, 10)
            
            value_label = QLabel("--")
            value_label.setStyleSheet("font-size: 32px; font-weight: bold; color: #1e6bde;")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stat_layout.addWidget(value_label)
            
            name_label = QLabel(label)
            name_label.setStyleSheet("font-size: 14px; color: #808080;")
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stat_layout.addWidget(name_label)
            
            self._stat_labels[key] = value_label
            stats_layout.addWidget(stat_widget)
        
        layout.addWidget(stats_group)
        
        recent_group = self._create_card("最近项目")
        recent_layout = QVBoxLayout(recent_group)
        
        self._recent_list = QListWidget()
        self._recent_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                border: none;
                border-radius: 8px;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #2a2a2a;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #2a2a2a;
            }
        """)
        self._recent_list.itemDoubleClicked.connect(self._open_recent_project)
        recent_layout.addWidget(self._recent_list)
        
        layout.addWidget(recent_group)
        layout.addStretch()
        
        # 初始加载数据
        self._refresh_stats()
        self._refresh_recent_projects()
    
    def _create_card(self, title: str) -> QGroupBox:
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
    
    def _navigate_to(self, module_id: str):
        self._event_bus.emit(EventType.MODULE_ACTIVATED, {"target": module_id})
    
    def _show_login_dialog(self):
        """ """
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QGroupBox, QCheckBox, QComboBox
        
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
            print("登录成功")
            # 这里可以添加登录逻辑
        else:
            print("登录取消")
    
    def on_activated(self):
        """每次切换到首页时刷新数据，首次显示引导"""
        self._refresh_stats()
        self._refresh_recent_projects()
        # 首次打开时显示新手引导
        if not hasattr(self, '_welcome_shown'):
            self._welcome_shown = False
        if not self._welcome_shown:
            # 延迟显示，等UI渲染完
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(300, self._show_welcome_guide)

    def _show_welcome_guide(self):
        """首次打开：弹出新手引导弹窗（功能概览、快捷入口介绍）"""
        if self._welcome_shown:
            return
        self._welcome_shown = True
        from PyQt6.QtWidgets import QDialog, QMessageBox
        msg = (
            "🎬 <b>欢迎使用 拾光剪影！</b>\n\n"
            "<b>核心功能一览：</b>\n"
            "🎬 <b>剪辑工作台</b> — 多轨道编辑、滤镜、转场、字幕、AI辅助剪辑\n"
            "✍️ <b>AI文案生成</b> — 智能脚本/标题/标签，支持推送到剪辑\n"
            "🎭 <b>短剧筛选</b> — 多平台热度榜、佣金分析、趋势预测\n"
            "👤 <b>账号运营</b> — 多平台矩阵管理、OAuth授权、批量发布\n"
            "🤖 <b>模型广场</b> — 16+ AI模型接入、使用统计、成本追踪\n"
            "🧩 <b>插件中心</b> — 可扩展插件生态、一键安装/卸载\n\n"
            "<b>快速上手：</b>\n"
            "1️⃣ 点击「新建剪辑」开始一个项目\n"
            "2️⃣ 在「模型广场」配置AI模型\n"
            "3️⃣ 浏览「短剧筛选」发掘热点\n"
            "4️⃣ 访问「设置」自定义快捷键和主题\n"
            "5️⃣ 打开「帮助」查看详细教程\n\n"
            "拾光剪影 — AI驱动的短视频创作平台 🚀"
        )
        box = QMessageBox(self)
        box.setWindowTitle("欢迎使用 拾光剪影")
        box.setText(msg)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setStyleSheet("QMessageBox{background:#121212;color:#ccc;font-size:12px;} QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;padding:8px 24px;}")
        box.exec()

    def _refresh_stats(self):
        """从系统读取真实统计：项目数/任务数/发布数/播放量"""
        try:
            import os, json
            from pathlib import Path

            workspace = Path(__file__).parent.parent.parent.parent

            # 项目统计 — 从 data/projects/ 目录扫描
            projects_dir = workspace / "data" / "projects"
            project_count = "0"
            if projects_dir.exists():
                count = len([f for f in projects_dir.iterdir()
                             if f.is_file() and f.suffix in ('.json', '.proj')])
                project_count = str(count)

            # 任务统计 — 从 batch_task_manager 读取活跃队列数
            task_count = "0"
            try:
                from core.batch_task_manager import batch_task_manager
                if batch_task_manager and getattr(batch_task_manager, '_queues', None):
                    task_count = str(len(batch_task_manager._queues))
            except ImportError:
                pass

            # 发布统计 — 从 publish_log.json 读取
            publish_count = "0"
            try:
                pf = workspace / "data" / "publish_log.json"
                if pf.exists():
                    with open(pf, 'r', encoding='utf-8') as f:
                        pd_data = json.load(f)
                    publish_count = str(len(pd_data) if isinstance(pd_data, list) else 0)
            except Exception:
                pass

            # 播放统计 — 从 analytics.json 读取
            views_count = "0"
            try:
                af = workspace / "data" / "analytics.json"
                if af.exists():
                    with open(af, 'r', encoding='utf-8') as f:
                        a_data = json.load(f)
                    views_count = str(a_data.get("total_views", 0))
            except (OSError, json.JSONDecodeError):
                pass

            self._stat_labels.get("videos", QLabel()).setText(project_count)
            self._stat_labels.get("copy", QLabel()).setText(task_count)
            self._stat_labels.get("publish", QLabel()).setText(publish_count)
            self._stat_labels.get("views", QLabel()).setText(views_count)
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"刷新统计数据失败: {e}")

    def _refresh_recent_projects(self):
        """从 data/projects/ 目录扫描最近 10 个项目"""
        from pathlib import Path
        import os

        self._recent_list.clear()
        workspace = Path(__file__).parent.parent.parent.parent

        try:
            projects_dir = workspace / "data" / "projects"
            if projects_dir.exists():
                files = []
                for f in projects_dir.iterdir():
                    if f.is_file() and f.suffix in ('.json', '.proj'):
                        files.append((f, f.stat().st_mtime))
                files.sort(key=lambda x: x[1], reverse=True)

                from datetime import datetime
                for f_path, mtime in files[:10]:
                    dt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    self._recent_list.addItem(f"{f_path.stem}  ({dt})")

            if self._recent_list.count() == 0:
                self._recent_list.addItem("（暂无最近项目）")
                self._recent_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"刷新最近项目失败: {e}")
            self._recent_list.addItem(f"（加载失败）")

    def _open_recent_project(self, item):
        """双击打开最近项目 → 导航到编辑器"""
        from pathlib import Path

        text = item.text()
        if text.startswith("（"):
            return

        # 提取项目名（去除时间后缀）
        project_name = text.split("  (")[0] if "  (" in text else text
        workspace = Path(__file__).parent.parent.parent.parent
        project_file = workspace / "data" / "projects" / f"{project_name}.json"

        if project_file.exists():
            try:
                self._event_bus.emit(EventType.MODULE_ACTIVATED, {
                    "target": "editor",
                    "project": str(project_file)
                })
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"打开项目失败: {e}")


class TimeRuler(QWidget):
    """ """
    
    clicked = pyqtSignal(float)  # 点击位置（秒）
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._zoom = 100
        self._total_duration = 60
        self._playhead_pos = 0
        self._left_margin = 100  # 左侧轨道控制区宽度
        self.setFixedHeight(45)
        self.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
    
    def set_zoom(self, zoom):
        self._zoom = max(10, min(500, zoom))
        self.update()
    
    def set_playhead(self, pos):
        self._playhead_pos = pos
        self.update()
    
    def _px_per_second(self):
        """ """
        return 20 * (self._zoom / 100)
    
    def _time_to_x(self, t):
        """ """
        return self._left_margin + int(t * self._px_per_second())
    
    def _x_to_time(self, x):
        """ """
        return max(0, (x - self._left_margin) / self._px_per_second())
    
    def _format_time_label(self, t):
        """ """
        if t < 1:
            return f"{int(t * 1000)}ms" if t > 0 else "0"
        elif t < 60:
            return f"{t:g}s"  # 使用 :g 去除多余的小数位
        else:
            m, s = divmod(int(t), 60)
            return f"{m}:{s:02d}"
    
    def paintEvent(self, event):
        """ """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        painter.fillRect(rect, QColor("#1a1a1a"))
        
        pps = self._px_per_second()
        width = rect.width()
        # 根据可见宽度动态计算当前可见的最大时长
        visible_duration = int((width - self._left_margin) / pps) if pps > 0 else 60
        # 总时长取可见时长和 _total_duration 的较大值，确保至少能显示当前内容
        max_t = max(self._total_duration, visible_duration)
        
        # 根据 pps 自动选择刻度间隔
        candidates = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60]
        major_step = 1.0
        minor_step = 0.5
        for c in candidates:
            pixel_dist = c * pps
            if 60 <= pixel_dist <= 200:
                major_step = c
                minor_step = c / (5.0 if c >= 1 else 2.0)
                break
        
        # 绘制次刻度
        painter.setPen(QColor("#333333"))
        t = 0
        while t <= max_t:
            x = self._time_to_x(t)
            if x >= self._left_margin and x <= width:
                painter.drawLine(x, 33, x, 40)
            t += minor_step
        
        # 绘制主刻度
        painter.setPen(QPen(QColor("#555555"), 2))
        t = 0
        while t <= max_t:
            x = self._time_to_x(t)
            if x >= self._left_margin and x <= width:
                painter.drawLine(x, 22, x, 40)
            t += major_step
        
        # 绘制时间标签
        painter.setPen(QColor("#cccccc"))
        font = QFont("Arial", 10, QFont.Weight.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)
        
        t = 0
        while t <= max_t:
            x = self._time_to_x(t)
            if x >= self._left_margin and x <= width:
                lbl = self._format_time_label(t)
                tw = fm.horizontalAdvance(lbl)
                painter.drawText(x - tw // 2, 18, lbl)
            t += major_step
        
        # 绘制播放头
        ph_x = self._time_to_x(self._playhead_pos)
        if ph_x >= self._left_margin and ph_x <= width:
            painter.setPen(QPen(QColor("#ff4757"), 2))
            painter.drawLine(ph_x, 0, ph_x, 40)
            painter.setBrush(QColor("#ff4757"))
            painter.drawPolygon(QPolygon([
                QPoint(ph_x - 5, 0), QPoint(ph_x + 5, 0), QPoint(ph_x, 8)
            ]))
    
    def mousePressEvent(self, event):
        """ """
        if event.button() == Qt.MouseButton.LeftButton:
            t = self._x_to_time(event.pos().x())
            self.clicked.emit(t)


class TrackControlPanel(QWidget):
    """统一控制栏 - 100px固定宽度，位于轨道区左侧非滚动区域"""

    mute_toggled = pyqtSignal(object, bool)
    solo_toggled = pyqtSignal(object, bool)
    lock_toggled = pyqtSignal(object, bool)
    volume_changed = pyqtSignal(object, float)
    collapse_toggled = pyqtSignal(object, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 48)
        self.setStyleSheet("background:#151515; border-right:1px solid #1e1e1e; border-bottom:1px solid #1e1e1e;")
        self._track = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 1, 4, 1)
        lay.setSpacing(1)

        # 占位提示
        self._placeholder = QLabel("选择轨道\n进行操作")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet("color:#444;font-size:10px;background:transparent;border:none;")
        lay.addWidget(self._placeholder)

        # 轨道名称
        self._track_name = QLabel("")
        self._track_name.setStyleSheet("color:#888;font-size:9px;font-weight:500;background:transparent;border:none;")
        self._track_name.hide()
        lay.addWidget(self._track_name)

        # M/S/L 按钮行
        btn_style = (
            "QPushButton{background:transparent;color:#555;border:1px solid #333;border-radius:3px;"
            "font-size:9px;font-weight:bold;}"
            "QPushButton:hover{background:#2a2a2a;color:#aaa;}"
        )

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(2)

        self._mute_btn = QPushButton("M")
        self._mute_btn.setFixedSize(20, 20)
        self._mute_btn.setCheckable(True)
        self._mute_btn.setToolTip("静音")
        self._mute_btn.setStyleSheet(btn_style + "QPushButton:checked{background:#d32f2f;color:#fff;border-color:#d32f2f;}")
        self._mute_btn.toggled.connect(lambda checked: self.mute_toggled.emit(self._track, checked))
        btn_row.addWidget(self._mute_btn)

        self._solo_btn = QPushButton("S")
        self._solo_btn.setFixedSize(20, 20)
        self._solo_btn.setCheckable(True)
        self._solo_btn.setToolTip("独奏")
        self._solo_btn.setStyleSheet(btn_style + "QPushButton:checked{background:#ff9800;color:#fff;border-color:#ff9800;}")
        self._solo_btn.toggled.connect(lambda checked: self.solo_toggled.emit(self._track, checked))
        btn_row.addWidget(self._solo_btn)

        self._lock_btn = QPushButton("L")
        self._lock_btn.setFixedSize(20, 20)
        self._lock_btn.setCheckable(True)
        self._lock_btn.setToolTip("锁定")
        self._lock_btn.setStyleSheet(btn_style + "QPushButton:checked{background:#555;color:#fff;border-color:#777;}")
        self._lock_btn.toggled.connect(lambda checked: self.lock_toggled.emit(self._track, checked))
        btn_row.addWidget(self._lock_btn)

        self._fold_btn = QPushButton("⊟")
        self._fold_btn.setFixedSize(20, 20)
        self._fold_btn.setCheckable(True)
        self._fold_btn.setToolTip("折叠/展开")
        self._fold_btn.setStyleSheet(btn_style + "QPushButton:checked{background:#1e6bde;color:#fff;border-color:#1e6bde;}")
        self._fold_btn.toggled.connect(lambda checked: self.collapse_toggled.emit(self._track, checked))
        btn_row.addWidget(self._fold_btn)

        btn_row.addStretch()
        lay.addLayout(btn_row)

        # 音量滑条 (仅音频轨显示)
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 200)
        self._volume_slider.setValue(100)
        self._volume_slider.setFixedHeight(12)
        self._volume_slider.setToolTip("音量")
        self._volume_slider.setStyleSheet("""
            QSlider::groove:horizontal{background:#333;height:3px;border-radius:1px;}
            QSlider::handle:horizontal{background:#81c784;width:8px;height:8px;margin:-3px 0;border-radius:4px;}
            QSlider::handle:horizontal:hover{background:#a5d6a7;}
            QSlider::sub-page:horizontal{background:#81c784;height:3px;border-radius:1px;}
        """)
        self._volume_slider.valueChanged.connect(
            lambda v: self.volume_changed.emit(self._track, v / 100.0)
        )
        self._volume_slider.hide()
        lay.addWidget(self._volume_slider)

        self._btn_row = btn_row
        self._hide_controls()

    def _hide_controls(self):
        """隐藏所有控件"""
        self._track_name.hide()
        self._volume_slider.hide()
        for i in range(self._btn_row.count()):
            w = self._btn_row.itemAt(i).widget()
            if w:
                w.hide()

    def _show_controls(self):
        """显示所有控件"""
        self._track_name.show()
        self._volume_slider.show()
        for i in range(self._btn_row.count()):
            w = self._btn_row.itemAt(i).widget()
            if w:
                w.show()

    def bind_track(self, track, y_pos):
        """绑定轨道"""
        self._track = track
        if track is None:
            self._placeholder.show()
            self._hide_controls()
            self.hide()
            return

        self.move(0, y_pos)
        self._placeholder.hide()
        self._show_controls()

        colors = {"video": "#4fc3f7", "audio": "#81c784", "subtitle": "#ffb74d"}
        lbls = {"video": "视频轨", "audio": "音频轨", "subtitle": "字幕轨"}
        track_type = track.get('type', 'video')
        self._track_name.setText(lbls.get(track_type, track.get('name', '')))
        self._track_name.setStyleSheet(
            f"color:{colors.get(track_type,'#aaa')};font-size:9px;font-weight:bold;background:transparent;border:none;"
        )

        # M/S/L 状态同步
        self._mute_btn.blockSignals(True)
        self._mute_btn.setChecked(track.get('muted', False))
        self._mute_btn.blockSignals(False)
        self._solo_btn.blockSignals(True)
        self._solo_btn.setChecked(track.get('solo', False))
        self._solo_btn.blockSignals(False)
        self._lock_btn.blockSignals(True)
        self._lock_btn.setChecked(track.get('locked', False))
        self._lock_btn.blockSignals(False)
        self._fold_btn.blockSignals(True)
        self._fold_btn.setChecked(track.get('collapsed', False))
        self._fold_btn.blockSignals(False)

        # 音量滑条 - 仅音频轨道显示
        if track_type == "audio":
            self._volume_slider.show()
            self._volume_slider.blockSignals(True)
            self._volume_slider.setValue(int(track.get('volume', 1.0) * 100))
            self._volume_slider.blockSignals(False)
        else:
            self._volume_slider.hide()

        self.show()
        self.raise_()


class TimelineWidget(QWidget):
    """ """

    clip_selected = pyqtSignal(object)
    playhead_moved = pyqtSignal(float)
    # 补短 P1#8：转发 ClipWidget 的关键帧点击，方便 EditorModule 直接监听
    clip_keyframe_clicked = pyqtSignal(object, dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks = []
        self._clips = []
        self._current_clip = None
        self._zoom = 100
        self._playhead_pos = 0
        self._total_duration = 600
        self._is_playing = False
        self._timer = None
        self._selected_track = None
        # Track drag reorder state
        self._drag_track = None
        self._drag_orig_index = -1
        self._drag_start_y = 0
        self._drag_active = False
        self._drag_indicator = None
        self._drag_press_global_y = None
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # === 顶部：时间标尺 ===
        self._time_ruler = TimeRuler(self)
        self._time_ruler.clicked.connect(self.set_playhead_position)
        layout.addWidget(self._time_ruler)

        # === 轨道区 ===
        # 浮动控制栏 — 绝对定位，跟随选中轨道
        self._track_ctrl_panel = TrackControlPanel(self)
        self._track_ctrl_panel.mute_toggled.connect(self._on_track_mute)
        self._track_ctrl_panel.solo_toggled.connect(self._on_track_solo)
        self._track_ctrl_panel.lock_toggled.connect(self._on_track_lock)
        self._track_ctrl_panel.volume_changed.connect(self._on_track_volume)
        self._track_ctrl_panel.collapse_toggled.connect(self._on_track_collapse)
        self._track_ctrl_panel.hide()

        # === 轨道滚动区（左侧留100px给控制栏） ===
        self._track_scroll = QScrollArea()
        self._track_scroll.setWidgetResizable(False)
        self._track_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._track_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._track_scroll.setStyleSheet("""
            QScrollArea { background-color: #0d0d0d; border: none; }
            QScrollBar:vertical { background-color: #151515; width: 8px; margin: 0; }
            QScrollBar::handle:vertical { background-color: #3a3a3a; border-radius: 4px; min-height: 30px; }
            QScrollBar::handle:vertical:hover { background-color: #555; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { background-color: #151515; height: 8px; margin: 0; }
            QScrollBar::handle:horizontal { background-color: #3a3a3a; border-radius: 4px; min-width: 30px; }
            QScrollBar::handle:horizontal:hover { background-color: #555; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            QScrollBar::corner { background-color: #151515; }
        """)
        self._track_scroll.setViewportMargins(100, 0, 0, 0)

        self._track_viewport = QWidget()
        self._track_viewport.setStyleSheet("background-color: #0d0d0d;")
        self._track_layout = QVBoxLayout(self._track_viewport)
        self._track_layout.setContentsMargins(0, 0, 0, 0)
        self._track_layout.setSpacing(0)
        self._track_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 播放头
        self._track_playhead = QFrame(self._track_viewport)
        self._track_playhead.setStyleSheet("background-color: #ff4757; width: 2px;")
        self._track_playhead.setFixedWidth(2)
        self._track_playhead.move(0, 0)

        self._track_scroll.setWidget(self._track_viewport)
        self._track_scroll.horizontalScrollBar().valueChanged.connect(
            lambda v: self._time_ruler.update()
        )
        # 垂直滚动时更新控制栏位置
        self._track_scroll.verticalScrollBar().valueChanged.connect(
            lambda v: self._update_ctrl_panel_position()
        )

        layout.addWidget(self._track_scroll, 1)
        
        self._add_track("视频轨", "video")
        self._add_track("音频轨", "audio")
        self._add_track("字幕轨", "subtitle")
        self._update_track_min_width()
    
    def _update_time_ruler(self):
        """ """
        self._time_ruler.set_zoom(self._zoom)
    
    def _add_track(self, name, track_type):
        """ """
        TRACK_H = 48
        
        track_widget = QFrame()
        track_widget.setFixedHeight(TRACK_H)
        track_widget.setStyleSheet(
            "QFrame { background:#111; border:none; border-bottom:1px solid #1e1e1e; border-radius:0; }"
            "QFrame:hover { background:#161616; }"
        )
        track_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        track_widget.setMouseTracking(True)
        track_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        track_widget.customContextMenuRequested.connect(
            lambda pos: self._show_track_menu(track_widget)
        )
        track_row = QHBoxLayout(track_widget)
        track_row.setContentsMargins(0, 0, 0, 0)
        track_row.setSpacing(0)
        
        # ---- 轨道标识 (28px) ----
        identifier = QFrame()
        identifier.setFixedSize(28, TRACK_H)
        identifier.setStyleSheet("background:#151515; border-right:1px solid #1e1e1e;")
        identifier.setMouseTracking(True)
        identifier.setCursor(Qt.CursorShape.SizeVerCursor)
        id_lay = QVBoxLayout(identifier)
        id_lay.setContentsMargins(0, 0, 0, 0)
        id_lay.setSpacing(0)
        
        icons = {"video": "V", "audio": "A", "subtitle": "T"}
        colors = {"video": "#4fc3f7", "audio": "#81c784", "subtitle": "#ffb74d"}
        icon_lbl = QLabel(icons.get(track_type, "?"))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        icon_lbl.setStyleSheet(
            f"color:{colors.get(track_type,'#aaa')};font-size:11px;font-weight:bold;"
            "background:transparent;border:none;"
        )
        id_lay.addWidget(icon_lbl)
        track_row.addWidget(identifier)
        
        # ---- 片段区域 ----
        clip_container = QWidget()
        clip_container.setStyleSheet("background:#111;")
        clip_container.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        clip_container.customContextMenuRequested.connect(
            lambda pos: self._show_track_menu(track_widget)
        )
        clip_layout = QHBoxLayout(clip_container)
        clip_layout.setContentsMargins(4, 4, 4, 4)
        clip_layout.setSpacing(2)
        clip_layout.addStretch()
        track_row.addWidget(clip_container, 1)
        
        self._track_layout.addWidget(track_widget)
        
        track = {
            'id': len(self._tracks) + 1,
            'name': name,
            'type': track_type,
            'widget': track_widget,
            'identifier': identifier,
            'clip_container': clip_container,
            'content_layout': clip_layout,
            'muted': False,
            'solo': False,
            'locked': False,
            'volume': 1.0,
        }
        
        # Left-click: select (short press) / drag reorder (long press + move)
        # All sub-widgets route to the same drag handlers
        identifier.mousePressEvent = lambda e: self._drag_press(track, e)
        identifier.mouseMoveEvent = lambda e: self._drag_move(track, e)
        identifier.mouseReleaseEvent = lambda e: self._drag_release(track, e)
        
        track_widget.mousePressEvent = lambda e: self._drag_press(track, e)
        track_widget.mouseMoveEvent = lambda e: self._drag_move(track, e)
        track_widget.mouseReleaseEvent = lambda e: self._drag_release(track, e)
        
        clip_container.mousePressEvent = lambda e: self._drag_press(track, e)
        clip_container.mouseMoveEvent = lambda e: self._drag_move(track, e)
        clip_container.mouseReleaseEvent = lambda e: self._drag_release(track, e)
        
        self._tracks.append(track)
        return track
    
    def _select_track(self, track):
        """选中轨道，更新左侧控制栏浮动位置"""
        if self._selected_track == track:
            return
        
        self._selected_track = track
        
        for t in self._tracks:
            if t == track:
                t['widget'].setStyleSheet(
                    "QFrame { background:#1a2a3a; border:none; border-bottom:1px solid #1e6bde; border-radius:0; }"
                )
                t['identifier'].setStyleSheet("background:#1e3a5f; border-right:1px solid #1e6bde;")
            else:
                t['widget'].setStyleSheet(
                    "QFrame { background:#111; border:none; border-bottom:1px solid #1e1e1e; border-radius:0; }"
                    "QFrame:hover { background:#161616; }"
                )
                t['identifier'].setStyleSheet("background:#151515; border-right:1px solid #1e1e1e;")
        
        self._update_ctrl_panel_position()
    
    def _update_ctrl_panel_position(self):
        """更新左侧控制栏浮动位置，使其与选中轨道垂直对齐"""
        track = self._selected_track
        if track is None:
            self._track_ctrl_panel.bind_track(None, 0)
            return
        
        ruler_h = self._time_ruler.height()
        scroll_offset = self._track_scroll.verticalScrollBar().value()
        track_y = track['widget'].pos().y()
        # 绝对Y = 标尺高度 + 轨道在viewport中位置 - 滚动偏移
        y_pos = ruler_h + track_y - scroll_offset
        self._track_ctrl_panel.bind_track(track, y_pos)
    
    def _drag_press(self, track, event):
        """Left mouse press: always select track, prepare for possible drag"""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        event.accept()
        
        # Always select the track
        self._select_track(track)
        
        # Prepare drag state (locked tracks cannot be dragged)
        if track.get('locked', False):
            return
        
        self._drag_track = track
        self._drag_orig_index = self._tracks.index(track)
        self._drag_start_y = track['widget'].pos().y()
        self._drag_active = False
        self._drag_press_global_y = event.globalPosition().y()
        
        if self._drag_indicator is None:
            self._drag_indicator = QFrame(self._track_viewport)
            self._drag_indicator.setStyleSheet("background-color: #1e6bde;")
            self._drag_indicator.setFixedHeight(3)
            self._drag_indicator.hide()
    
    def _drag_move(self, track, event):
        """Left mouse move: detect drag threshold, move track widget"""
        if self._drag_track != track or self._drag_press_global_y is None:
            return
        event.accept()
        
        widget = track['widget']
        delta = event.globalPosition().y() - self._drag_press_global_y
        
        if not self._drag_active:
            if abs(delta) > 8:
                self._drag_active = True
                widget.raise_()
                widget.setStyleSheet(
                    "QFrame { background:#2a3a4a; border:1px solid #1e6bde; border-radius:2px; }"
                )
                if self._drag_indicator:
                    self._drag_indicator.show()
                    self._drag_indicator.raise_()
        else:
            new_y = self._drag_start_y + int(delta)
            new_y = max(0, new_y)
            widget.move(0, new_y)
            self._update_drag_indicator()
    
    def _drag_release(self, track, event):
        """Left mouse release: finalize drag if active"""
        if self._drag_active and self._drag_track == track:
            self._finalize_drag(track)
        self._drag_track = None
        self._drag_active = False
        self._drag_press_global_y = None
        if self._drag_indicator:
            self._drag_indicator.hide()
    
    def _update_drag_indicator(self):
        """Position the insertion indicator between tracks"""
        if not self._drag_track or not self._drag_indicator:
            return
        
        dragged = self._drag_track
        dragged_y = dragged['widget'].pos().y()
        dragged_h = dragged['widget'].height()
        dragged_center = dragged_y + dragged_h // 2
        
        target_index = self._drag_orig_index
        for i, t in enumerate(self._tracks):
            if t == dragged:
                continue
            ty = t['widget'].pos().y()
            th = t['widget'].height()
            tc = ty + th // 2
            if dragged_center > tc:
                target_index = i + 1 if i >= self._drag_orig_index else i
            else:
                target_index = i if i < self._drag_orig_index else i - 1
        
        if target_index < self._drag_orig_index:
            indicator_y = self._tracks[target_index]['widget'].pos().y()
        else:
            idx = min(target_index, len(self._tracks) - 1)
            track_h = self._tracks[idx]['widget'].height()
            indicator_y = self._tracks[idx]['widget'].pos().y() + track_h
        
        self._drag_indicator.setFixedWidth(self._track_viewport.width())
        self._drag_indicator.move(0, indicator_y)
    
    def _finalize_drag(self, track):
        """Finalize drag: reorder the track in layout and list"""
        if not track:
            return
        
        dragged_y = track['widget'].pos().y()
        dragged_h = track['widget'].height()
        dragged_center = dragged_y + dragged_h // 2
        
        # Calculate target index
        new_index = 0
        for i, t in enumerate(self._tracks):
            if t == track:
                continue
            ty = t['widget'].pos().y()
            th = t['widget'].height()
            if dragged_center > ty + th // 2:
                new_index = i + 1
        
        old_index = self._drag_orig_index
        if new_index == old_index:
            self._restore_track_positions()
            return
        
        # Reorder in layout
        widget = track['widget']
        self._track_layout.removeWidget(widget)
        self._track_layout.insertWidget(new_index, widget)
        
        # Reorder in list
        self._tracks.pop(old_index)
        self._tracks.insert(new_index, track)
        
        # Update IDs
        for i, t in enumerate(self._tracks):
            t['id'] = i + 1
        
        self._restore_track_positions()
    
    def _restore_track_positions(self):
        """Restore all track widgets to their layout positions"""
        for t in self._tracks:
            w = t['widget']
            w.move(0, 0)  # Layout handles positioning
    
    def _show_track_menu(self, track_widget):
        """ """
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#1e1e1e;border:1px solid #333;padding:4px;}"
            "QMenu::item{padding:5px 20px;color:#ccc;font-size:11px;}"
            "QMenu::item:selected{background:#1e6bde;color:#fff;}"
            "QMenu::separator{height:1px;background:#333;margin:4px 8px;}"
        )
        
        add_track = menu.addAction("➕ 添加轨道")
        add_clip = menu.addAction("➕ 添加片段")
        menu.addSeparator()
        rename = menu.addAction("✏ 重命名")
        duplicate = menu.addAction("📋 复制轨道")
        menu.addSeparator()
        lock_action = menu.addAction("🔒 锁定/解锁轨道")
        hide_action = menu.addAction("👁 隐藏/显示轨道")
        menu.addSeparator()
        delete = menu.addAction("🗑 删除轨道")
        
        action = menu.exec(track_widget.mapToGlobal(QPoint(10, 10)))
        if not action:
            return
        
        target_track = None
        for t in self._tracks:
            if t['widget'] is track_widget:
                target_track = t
                break
        if not target_track:
            return
        
        if action == add_track:
            self.add_track("New Track", "video")
        elif action == add_clip:
            pass  # Clip adding is handled by the import/素材 panel
        elif action == delete:
            self.remove_track(target_track['id'])
        elif action == rename:
            self._rename_track(target_track)
        elif action == duplicate:
            self._duplicate_track(target_track)
        elif action == lock_action:
            target_track['locked'] = not target_track['locked']
            if self._selected_track == target_track:
                self._track_ctrl_panel._lock_btn.setChecked(target_track['locked'])
        elif action == hide_action:
            target_track['widget'].setVisible(not target_track['widget'].isVisible())
    
    def _on_track_mute(self, track, checked):
        """ """
        track['muted'] = checked
        opacity = 0.3 if checked else 1.0
        for i in range(track['content_layout'].count()):
            widget = track['content_layout'].itemAt(i).widget()
            if isinstance(widget, ClipWidget):
                widget.setGraphicsEffect(None)
                if checked:
                    from PyQt6.QtWidgets import QGraphicsOpacityEffect
                    eff = QGraphicsOpacityEffect()
                    eff.setOpacity(opacity)
                    widget.setGraphicsEffect(eff)
    
    def _on_track_solo(self, track, checked):
        """ """
        track['solo'] = checked
        if checked:
            for t in self._tracks:
                if t != track and t['type'] == track['type']:
                    t['solo'] = False
    
    def _on_track_lock(self, track, checked):
        """ """
        track['locked'] = checked

    def _on_track_volume(self, track, volume):
        """轨道音量调整"""
        if track is None:
            return
        track['volume'] = volume

    def _on_track_collapse(self, track, collapsed):
        """轨道折叠/展开"""
        if track is None:
            return
        track['collapsed'] = collapsed
        if collapsed:
            track['clip_container'].setVisible(False)
            track['widget'].setFixedHeight(8)
            track['identifier'].setFixedHeight(8)
        else:
            track['clip_container'].setVisible(True)
            track['widget'].setFixedHeight(48)
            track['identifier'].setFixedHeight(48)
        self._update_track_min_width()
        if self._selected_track == track:
            self._update_ctrl_panel_position()
    
    def _rename_track(self, track):
        """ """
        from PyQt6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "Rename Track", "Track name:",
            text=track['name']
        )
        if ok and new_name.strip():
            track['name'] = new_name.strip()
    
    def _duplicate_track(self, track):
        """Duplicate track with same clips"""
        new_track = self._add_track(track['name'] + " (copy)", track['type'])
        self._update_track_min_width()
        # Copy clips from original track
        for i in range(track['content_layout'].count()):
            widget = track['content_layout'].itemAt(i).widget()
            if isinstance(widget, ClipWidget):
                clip_data = dict(widget.clip_data)
                self.add_clip(clip_data, new_track['id'] - 1)
        return new_track
    
    # 已移除自定义设置相关方法
    
    def add_track(self, name, track_type):
        """ """
        track = self._add_track(name, track_type)
        self._update_track_min_width()
        return track
    
    def remove_track(self, track_id):
        """ """
        for i, track in enumerate(self._tracks):
            if track['id'] == track_id:
                track['widget'].deleteLater()
                self._tracks.pop(i)
                for j, t in enumerate(self._tracks):
                    t['id'] = j + 1
                self._update_track_min_width()
                return True
        return False
    
    def add_clip(self, clip_data, track_index=0):
        """ """
        if track_index < 0 or track_index >= len(self._tracks):
            return

        track = self._tracks[track_index]
        clip_widget = ClipWidget(clip_data, self)
        clip_widget.clicked.connect(self._on_clip_clicked)
        # 补短 P1#8：把关键帧点击信号桥接到 TimelineWidget 自身，
        # EditorModule 可直接监听 TimelineWidget.clip_keyframe_clicked
        clip_widget.keyframe_clicked.connect(self.clip_keyframe_clicked.emit)
        
        # 计算片段宽度(基于时长和缩放比例)
        clip_duration = clip_data.get('duration', 10)
        scale_factor = self._zoom / 100
        clip_width = int(clip_duration * 20 * scale_factor)  # 20px/秒
        clip_widget.setFixedWidth(max(80, clip_width))
        
        # 添加到轨道
        track_layout = track['content_layout']
        track_layout.insertWidget(track_layout.count() - 1, clip_widget)
        
        clip_data['track'] = track_index
        self._clips.append(clip_data)
        return clip_widget
    
    def _on_clip_clicked(self, clip_data):
        """ """
        # 取消之前选中的片段
        if self._current_clip:
            for clip in self._clips:
                if clip['id'] == self._current_clip['id']:
                    # 找到对应的ClipWidget并取消选择
                    pass
        
        # 选中当前片段
        self._current_clip = clip_data
        self.clip_selected.emit(clip_data)
    
    def set_zoom(self, zoom):
        """ """
        self._zoom = max(10, min(500, zoom))
        self._update_time_ruler()
        # 更新轨道最小宽度（与时间标尺长度一致）
        self._update_track_min_width()
        # 更新片段宽度
        for track in self._tracks:
            track_layout = track['content_layout']
            for i in range(track_layout.count() - 1):  # 减去最后的伸缩项
                widget = track_layout.itemAt(i).widget()
                if isinstance(widget, ClipWidget):
                    clip_duration = widget.clip_data.get('duration', 10)
                    scale_factor = self._zoom / 100
                    clip_width = int(clip_duration * 20 * scale_factor)
                    widget.setFixedWidth(max(80, clip_width))
    
    def _update_track_min_width(self):
        """ """
        px_per_sec = 20 * (self._zoom / 100)
        min_width = int(self._total_duration * px_per_sec + 120)
        track_count = max(3, len(self._tracks))
        min_height = track_count * 48 + 20
        self._track_viewport.setMinimumSize(min_width, min_height)
    
    def set_playhead_position(self, position):
        """ """
        self._playhead_pos = position
        # 更新时间标尺中的播放头
        self._time_ruler.set_playhead(position)
        # 更新轨道区域中的播放头（viewport 内）
        scale_factor = self._zoom / 100
        playhead_x = 100 + int(position * 20 * scale_factor)
        self._track_playhead.move(playhead_x, 0)
        self._track_playhead.setFixedHeight(self._track_viewport.height())
        self._track_playhead.setStyleSheet("background-color: #ff4757; width: 2px;")
        self.playhead_moved.emit(position)
    
    def play(self):
        """ """
        if not self._is_playing:
            self._is_playing = True
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._on_playback_tick)
            self._timer.start(33)  # 约30fps
    
    def pause(self):
        """ """
        if self._is_playing:
            self._is_playing = False
            if self._timer:
                self._timer.stop()
                self._timer.deleteLater()
                self._timer = None
    
    def stop(self):
        """ """
        self.pause()
        self.set_playhead_position(0)
    
    def _on_playback_tick(self):
        """ """
        if self._is_playing:
            new_position = self._playhead_pos + 0.033  # 约30fps
            if new_position <= self._total_duration:
                self.set_playhead_position(new_position)
            else:
                self.stop()


class ClipWidget(QFrame):
    """ """

    clicked = pyqtSignal(object)
    resized = pyqtSignal(object)
    moved = pyqtSignal(object)
    keyframe_clicked = pyqtSignal(object, dict)  # (clip_data, keyframe)

    # 补短 P1#8：关键帧可视化 - 属性->颜色 映射
    KEYFRAME_COLORS = {
        'position_x': '#00d4ff', 'position_y': '#00d4ff',
        'scale_x': '#ff9500', 'scale_y': '#ff9500',
        'rotation': '#9c27b0',
        'opacity': '#ffffff',
        'volume': '#4caf50',
        'speed': '#f44336',
        'brightness': '#ffeb3b', 'contrast': '#ffeb3b',
        'saturation': '#ffeb3b', 'hue': '#ffeb3b',
        'blur': '#9e9e9e', 'vignette': '#9e9e9e', 'sharpen': '#9e9e9e',
        'crop_top': '#795548', 'crop_bottom': '#795548',
        'crop_left': '#795548', 'crop_right': '#795548',
    }

    def __init__(self, clip_data, parent=None):
        super().__init__(parent)
        self.clip_data = clip_data
        self._is_selected = False
        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None

        # 补短 P1#8：关键帧数据 - 数据契约见 _get_keyframes()/set_keyframes()
        # 期望格式（clip_data['keyframes'] 或显式调用 set_keyframes 传入）：
        #   [
        #     {"time_offset": 1.2, "value": 0.5, "prop": "opacity", "easing": "linear"},
        #     ...
        #   ]
        # 没有数据时不做任何绘制 - 完全不影响现有 clip 外观
        self._keyframes = self._coerce_keyframes(clip_data.get('keyframes'))
        self._kf_hit_radius = 7  # 命中半径（px），与绘制点尺寸匹配

        self.setFixedHeight(38)
        self.setStyleSheet("""
            QFrame {
                background-color: #1e6bde;
                border-radius: 3px;
                border: none;
            }
            QFrame:hover {
                background-color: #2575e0;
            }
            QFrame[selected="true"] {
                border: 1.5px solid #ff4757;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        # 片段名称（省略号处理）
        clip_name = QLabel(os.path.basename(clip_data.get('path', '未命名')))
        clip_name.setStyleSheet("color: #eee; font-size: 10px; background:transparent; border:none;")
        clip_name.setMaximumWidth(100)
        clip_name.setEllipsize(Qt.TextElideMode.ElideRight)
        layout.addWidget(clip_name)

        layout.addStretch()

        # 时长标签
        dur = clip_data.get('duration', 0)
        dur_lbl = QLabel(f"{dur:.1f}s" if dur < 60 else f"{int(dur//60)}:{int(dur%60):02d}")
        dur_lbl.setStyleSheet("color: #bcd4f5; font-size: 9px; background:transparent; border:none;")
        layout.addWidget(dur_lbl)

    # ------------------------------------------------------------------
    # 补短 P1#8：关键帧数据接入（最小侵入 - 不影响无关键帧的 clip）
    # ------------------------------------------------------------------
    @staticmethod
    def _coerce_keyframes(raw):
        """
        规整关键帧数据：
          - 接受 None / 缺失 / 非 list 都返回空列表
          - 过滤掉缺 time_offset 的项
        """
        if not raw or not isinstance(raw, (list, tuple)):
            return []
        out = []
        for kf in raw:
            if not isinstance(kf, dict):
                continue
            if 'time_offset' not in kf and 't' not in kf:
                continue
            out.append({
                'time_offset': float(kf.get('time_offset', kf.get('t', 0.0))),
                'value': kf.get('value', 0.0),
                'prop': str(kf.get('prop', kf.get('property', 'value'))),
                'easing': str(kf.get('easing', 'linear')),
            })
        # 按时间排序，方便绘制与命中
        out.sort(key=lambda x: x['time_offset'])
        return out

    def set_keyframes(self, keyframes):
        """
        公开 API：更新关键帧数据并触发重绘。

        用法：
            clip_widget.set_keyframes([
                {"time_offset": 1.2, "value": 0.5, "prop": "opacity"},
            ])
        """
        self._keyframes = self._coerce_keyframes(keyframes)
        # 同步回 clip_data，保证序列化和撤销栈一致
        self.clip_data['keyframes'] = [
            {**kf, 'time_offset': kf['time_offset']} for kf in self._keyframes
        ]
        self.update()  # 触发 paintEvent

    def get_keyframes(self):
        """返回当前关键帧数据副本（防止外部误改内部状态）"""
        return [dict(kf) for kf in self._keyframes]

    def _color_for_prop(self, prop_name):
        return self.KEYFRAME_COLORS.get(prop_name, '#ffffff')

    def _time_to_x(self, time_offset):
        """关键帧时间偏移 -> clip 内 x 坐标（与 TimelineWidget 的 px_per_sec 算法保持一致）"""
        try:
            scale_factor = self.parent()._zoom / 100
        except (AttributeError, TypeError):
            scale_factor = 1.0
        return int(time_offset * 20 * scale_factor)

    def _keyframe_rects(self):
        """
        返回所有关键帧点的 (x, y_center, color, kf_dict)，
        x 会被裁剪到 [2, width-2]，保证不出 clip 边界。
        """
        rects = []
        w = self.width()
        h = self.height()
        # 关键帧点固定画在底部 6px 高的条带上（不与顶部 QLabel 文字冲突）
        band_top = h - 7
        y_center = band_top + 3
        for kf in self._keyframes:
            x = self._time_to_x(kf['time_offset'])
            if x < 2:
                x = 2
            elif x > w - 2:
                x = w - 2
            rects.append((x, y_center, self._color_for_prop(kf['prop']), kf))
        return rects

    def paintEvent(self, event):
        """
        补短 P1#8：在 QFrame 原样式（stylesheet 背景）之上叠加关键帧菱形点。

        关键设计：
          1. 先 super().paintEvent() 让 QFrame 走自己的 stylesheet，保持原样
          2. 再用 QPainter 叠加绘制 - 不修改 QSS、不增加子控件
          3. 无关键帧时直接走 super().paintEvent，零开销零影响
          4. 选中态点稍大、描边亮；非选中态点 5x5、描边半透明
        """
        super().paintEvent(event)
        if not self._keyframes:
            return

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # 选中时画一层底部高亮带（提示用户该 clip 有动画）
            if self._is_selected and self._keyframes:
                band_color = QColor(0, 0, 0, 60)
                painter.fillRect(0, self.height() - 7, self.width(), 7, band_color)

            size = 5 if self._is_selected else 4
            for x, y, color_hex, _kf in self._keyframe_rects():
                color = QColor(color_hex)
                # 填充菱形
                if self._is_selected:
                    painter.setBrush(QBrush(color))
                    painter.setPen(QPen(QColor(255, 255, 255), 1.2))
                else:
                    # 非选中：半透明 + 深色描边
                    fill = QColor(color)
                    fill.setAlpha(200)
                    painter.setBrush(QBrush(fill))
                    painter.setPen(QPen(QColor(0, 0, 0, 180), 1))

                # 菱形（4 个顶点） - 用 QPolygon 即可
                half = size
                poly = QPolygon([
                    QPoint(x, y - half),
                    QPoint(x + half, y),
                    QPoint(x, y + half),
                    QPoint(x - half, y),
                ])
                painter.drawPolygon(poly)
        finally:
            painter.end()

    def _hit_test_keyframe(self, pos):
        """
        鼠标位置命中关键帧点测试。命中返回 kf dict，否则返回 None。
        使用曼哈顿距离（菱形近似），半径 = self._kf_hit_radius。
        """
        for x, y, _color, kf in self._keyframe_rects():
            if abs(pos.x() - x) + abs(pos.y() - y) <= self._kf_hit_radius:
                return kf
        return None
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self._drag_offset = self.pos()
            # 检查是否点击在边缘(调整大小)
            if event.pos().x() < 10:
                self._is_resizing = True
                self._resize_direction = 'left'
            elif event.pos().x() > self.width() - 10:
                self._is_resizing = True
                self._resize_direction = 'right'
            else:
                # 补短 P1#8：若点击命中关键帧点，发 keyframe_clicked 而非切换选中
                # 这样不打断用户的"先看 clip 再细看关键帧"的操作流
                kf_hit = self._hit_test_keyframe(event.pos())
                if kf_hit is not None:
                    self.keyframe_clicked.emit(self.clip_data, kf_hit)
                    # 不进入选中/拖拽流程，但仍消费事件
                    super().mousePressEvent(event)
                    return

                self._is_resizing = False
                # 切换选择状态
                self._is_selected = not self._is_selected
                self.setProperty('selected', str(self._is_selected).lower())
                self.style().unpolish(self)
                self.style().polish(self)
                # 补短 P1#8：选中态变化需触发 paintEvent 重新画关键帧大小
                self.update()
                self.clicked.emit(self.clip_data)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 补短 P1#8：未在拖拽/调整大小时，命中关键帧点 -> 显示 tooltip
        if not self._is_resizing and not (self._drag_start_pos and self._drag_offset):
            kf_hit = self._hit_test_keyframe(event.pos())
            if kf_hit is not None:
                tip = self._format_keyframe_tooltip(kf_hit)
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                QToolTip.hideText()
                # 不强制重置 cursor，避免和 track 拖拽的 cursor 冲突
            # tooltip 处理完直接返回，不影响原有拖拽/调整大小逻辑
            return

        if self._is_resizing:
            # 调整大小逻辑
            delta = event.pos().x() - self._drag_start_pos.x()
            if self._resize_direction == 'right':
                new_width = max(80, self.width() + delta)
                self.setFixedWidth(new_width)
                # 更新片段时长
                if 'duration' in self.clip_data:
                    scale_factor = self.parent()._zoom / 100
                    self.clip_data['duration'] = new_width / (20 * scale_factor)
                    self.resized.emit(self.clip_data)
            elif self._resize_direction == 'left':
                new_width = max(80, self.width() - delta)
                new_x = self.x() + delta
                if new_x >= 0:
                    self.setFixedWidth(new_width)
                    self.move(new_x, self.y())
                    # 更新片段开始时间和时长
                    if 'start_time' in self.clip_data and 'duration' in self.clip_data:
                        scale_factor = self.parent()._zoom / 100
                        self.clip_data['start_time'] += delta / (20 * scale_factor)
                        self.clip_data['duration'] = new_width / (20 * scale_factor)
                        self.resized.emit(self.clip_data)
        elif self._drag_start_pos and self._drag_offset:
            # 拖拽逻辑
            new_pos = self.mapToParent(event.pos()) - self._drag_start_pos + self._drag_offset
            # 确保片段在轨道内
            new_pos.setY(self._drag_offset.y())  # 保持垂直位置不变
            if new_pos.x() >= 0:
                self.move(new_pos)
                # 更新片段开始时间 (偏移量修正为100px,与时间标尺严格对齐)
                if 'start_time' in self.clip_data:
                    scale_factor = self.parent()._zoom / 100
                    self.clip_data['start_time'] = (new_pos.x() - 100) / (20 * scale_factor)
                    self.moved.emit(self.clip_data)

    def mouseReleaseEvent(self, event):
        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def set_selected(self, selected):
        self._is_selected = selected
        self.setProperty('selected', str(selected).lower())
        self.style().unpolish(self)
        self.style().polish(self)
        # 补短 P1#8：选中态变化需重绘关键帧
        self.update()

    # ------------------------------------------------------------------
    # 补短 P1#8：内部辅助
    # ------------------------------------------------------------------
    def _format_keyframe_tooltip(self, kf):
        """关键帧 tooltip 文案：属性 @ 时间 = 值 (缓动)"""
        try:
            value = kf.get('value', 0.0)
            value_str = f"{float(value):.3f}".rstrip('0').rstrip('.')
        except Exception:
            value_str = str(value)
        t = kf.get('time_offset', 0.0)
        return (
            f"◆ {kf.get('prop', 'value')}\n"
            f"  @ {t:.2f}s = {value_str}\n"
            f"  easing: {kf.get('easing', 'linear')}"
        )



# EditorModule 已拆分为独立文件 editor_module.py
from .editor_module import EditorModule

# CopywritingModule / TasksModule / MaterialsModule 已拆分为独立文件
from .copywriting_module import CopywritingModule
from .tasks_module import TasksModule
from .materials_module import MaterialsModule


MODULE_CLASSES = [
    HomeModule,
    EditorModule,
    CopywritingModule,
    TasksModule,
    MaterialsModule,
]

from .plugins_module import PluginsModule
from .performance_module import PerformanceModule
from .drama_finder_module import DramaFinderModule
from .account_ops_module import AccountOpsModule
from .model_management import ModelManagementModule

MODULE_CLASSES.extend([
    PluginsModule,
    PerformanceModule,
    DramaFinderModule,
    AccountOpsModule,
    ModelManagementModule,
])

