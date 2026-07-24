"""
统一渲染管理器 (RenderManager)
===============================
中央渲染调度中心，整合：
- C++ 引擎 (高性能) / FFmpeg CLI (兼容) / GPU 加速
- 进度追踪 + ETA 估算
- 多平台导出预设
- 优先级任务队列
"""
import os
import sys
import time
import json
import logging
import threading
import subprocess
from typing import Dict, List, Optional, Tuple, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

logger = logging.getLogger("AI短剧编辑器.render_manager")


# ============================================================
# 枚举与数据结构
# ============================================================

class RenderBackend(Enum):
    """渲染后端"""
    CPP_ENGINE = "cpp_engine"       # C++ 引擎 (性能最高)
    FFMPEG_CLI = "ffmpeg_cli"       # FFmpeg 命令行 (兼容性最广)
    CPU_FALLBACK = "cpu_fallback"   # CPU 软渲染


class RenderMode(Enum):
    """渲染模式"""
    PREVIEW = "preview"     # 预览 (低质量, 快速)
    STANDARD = "standard"   # 标准 (平衡质量与速度)
    EXPORT = "export"       # 导出 (高质量, 慢速)


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class TaskStatus(Enum):
    """任务状态"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HardwareEncoder(Enum):
    """硬件编码器"""
    NONE = "libx264"
    NVIDIA = "h264_nvenc"
    NVIDIA_HEVC = "hevc_nvenc"
    INTEL = "h264_qsv"
    INTEL_HEVC = "hevc_qsv"
    AMD = "h264_amf"
    AMD_HEVC = "hevc_amf"


@dataclass
class RenderConfig:
    """渲染配置"""
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    video_codec: str = "libx264"
    video_bitrate: str = "5M"
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"
    preset: str = "medium"
    crf: int = 23
    pix_fmt: str = "yuv420p"
    format: str = "mp4"
    mode: RenderMode = RenderMode.STANDARD
    gpu_encoder: Optional[HardwareEncoder] = None
    extra_args: List[str] = field(default_factory=list)

    def copy(self) -> "RenderConfig":
        return RenderConfig(**self.__dict__.copy())


@dataclass
class RenderTask:
    """渲染任务"""
    task_id: str
    input_path: str
    output_path: str
    config: RenderConfig
    operation: str = "export"  # cut, merge, export, transcode
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.QUEUED
    progress: float = 0.0
    speed: float = 0.0          # 渲染速度 (x 倍速)
    eta: float = 0.0            # 预计剩余秒数
    start_time: float = 0.0
    end_time: float = 0.0
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    on_progress: Optional[Callable] = None
    on_complete: Optional[Callable] = None


@dataclass
class RenderResult:
    """渲染结果"""
    task_id: str
    success: bool
    output_path: str
    processing_time: float
    output_size: int = 0
    error_message: str = ""


@dataclass
class VideoMeta:
    """视频元数据"""
    path: str = ""
    duration: float = 0.0
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    bitrate: int = 0
    codec: str = ""
    has_audio: bool = True
    audio_codec: str = ""
    file_size: int = 0


# ============================================================
# 平台导出预设
# ============================================================

PLATFORM_PRESETS = {
    "抖音": {
        "width": 1080, "height": 1920, "fps": 30.0,
        "video_bitrate": "4M", "crf": 23, "preset": "fast",
    },
    "快手": {
        "width": 1080, "height": 1920, "fps": 30.0,
        "video_bitrate": "5M", "crf": 21, "preset": "medium",
    },
    "小红书": {
        "width": 1080, "height": 1440, "fps": 30.0,
        "video_bitrate": "6M", "crf": 18, "preset": "slow",
    },
    "B站": {
        "width": 1920, "height": 1080, "fps": 60.0,
        "video_bitrate": "8M", "crf": 18, "preset": "slow",
    },
    "视频号": {
        "width": 1080, "height": 1920, "fps": 30.0,
        "video_bitrate": "4M", "crf": 23, "preset": "fast",
    },
    "通用HD": {
        "width": 1920, "height": 1080, "fps": 30.0,
        "video_bitrate": "5M", "crf": 23, "preset": "medium",
    },
}

QUALITY_PRESETS = {
    RenderMode.PREVIEW: {
        "preset": "ultrafast", "crf": 30,
        "video_bitrate": "2M", "width_scale": 0.5,
    },
    RenderMode.STANDARD: {
        "preset": "medium", "crf": 23,
        "video_bitrate": "5M", "width_scale": 1.0,
    },
    RenderMode.EXPORT: {
        "preset": "slow", "crf": 18,
        "video_bitrate": "8M", "width_scale": 1.0,
    },
}


# ---- 工具函数 ----

def _parse_bitrate(bitrate_str: str, default: int = 5000000) -> int:
    """解析码率字符串: '5M' → 5000000, '128k' → 128000, '3000' → 3000"""
    if not bitrate_str:
        return default
    try:
        s = bitrate_str.upper().strip()
        if s.endswith("M"):
            return int(float(s[:-1]) * 1000000)
        elif s.endswith("K"):
            return int(float(s[:-1]) * 1000)
        else:
            return int(s)
    except (ValueError, TypeError):
        return default

# ============================================================
# FFmpeg 工具
# ============================================================

class FFmpegTool:
    """FFmpeg 工具封装"""
    
    _ffmpeg_path: Optional[str] = None
    _ffprobe_path: Optional[str] = None
    
    @classmethod
    def find_ffmpeg(cls) -> str:
        """查找 FFmpeg"""
        if cls._ffmpeg_path:
            return cls._ffmpeg_path
        
        search_paths = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        "thirdparty", "ffmpeg", "bin", "ffmpeg.exe"),
            "ffmpeg", "ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
        ]
        for p in search_paths:
            if os.path.exists(p) or __import__('shutil').which(p):
                cls._ffmpeg_path = p if os.path.exists(p) else p
                return cls._ffmpeg_path
        
        raise RuntimeError("FFmpeg 未找到")
    
    @classmethod
    def find_ffprobe(cls) -> str:
        """查找 ffprobe"""
        if cls._ffprobe_path:
            return cls._ffprobe_path
        
        ffmpeg = cls.find_ffmpeg()
        base = os.path.dirname(ffmpeg) if os.path.dirname(ffmpeg) else ""
        probe = os.path.join(base, "ffprobe.exe")
        if os.path.exists(probe):
            cls._ffprobe_path = probe
            return probe
        
        return ffmpeg
    
    @classmethod
    def run(cls, args: List[str], progress_cb=None, duration: float = 0,
            cancel_flag: threading.Event = None, process_holder: List = None) -> Tuple[bool, str]:
        """运行 FFmpeg 并解析进度"""
        cmd = [cls.find_ffmpeg(), "-y", "-hide_banner", "-nostats"] + args
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, encoding='utf-8', errors='ignore'
        )
        # 存储进程引用以便外部终止
        if process_holder is not None:
            process_holder.append(process)

        stderr_lines = []
        started = time.time()
        last_progress = 0.0

        while True:
            # 检查取消标志
            if cancel_flag and cancel_flag.is_set():
                process.kill()
                process.wait(timeout=5)
                if process_holder:
                    process_holder.clear()
                return False, "用户取消"

            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break
            if line:
                stderr_lines.append(line)
                if progress_cb and duration > 0:
                    import re
                    m = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                    if m:
                        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                        current = h * 3600 + mn * 60 + s
                        pct = min(99.9, current / duration * 100)
                        if pct > last_progress + 0.5:
                            last_progress = pct
                            elapsed = time.time() - started
                            speed = current / elapsed if elapsed > 0 else 0
                            eta = (duration - current) / speed if speed > 0 else 0
                            progress_cb(pct, speed, eta)

        rc = process.poll()
        if process_holder:
            process_holder.clear()

        if progress_cb and duration > 0:
            progress_cb(100.0, 0, 0)

        if rc != 0:
            err = "".join(stderr_lines[-8:])
            return False, err
        return True, ""
    
    @classmethod
    def probe(cls, path: str) -> Optional[VideoMeta]:
        """获取视频元数据"""
        try:
            probe_path = cls.find_ffprobe()
            result = subprocess.run(
                [probe_path, "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", path],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            meta = VideoMeta(
                path=path,
                duration=float(fmt.get("duration", 0)),
                file_size=int(fmt.get("size", 0)),
            )
            for stream in data.get("streams", []):
                if stream["codec_type"] == "video":
                    meta.width = stream.get("width", 1920)
                    meta.height = stream.get("height", 1080)
                    fps_s = stream.get("r_frame_rate", "30/1")
                    if "/" in fps_s:
                        n, d = fps_s.split("/")
                        meta.fps = float(n) / float(d) if float(d) != 0 else 30
                    meta.codec = stream.get("codec_name", "")
                    meta.bitrate = int(stream.get("bit_rate", 0))
                elif stream["codec_type"] == "audio":
                    meta.audio_codec = stream.get("codec_name", "")
                    meta.has_audio = True
            return meta
        except Exception as e:
            logger.warning(f"probe 失败: {path} - {e}")
            return None


# ============================================================
# 硬件检测
# ============================================================

class HardwareDetector:
    """硬件加速检测"""
    
    _cache: Dict[str, Any] = {}
    
    @classmethod
    def detect(cls, force: bool = False) -> Dict[str, Any]:
        if cls._cache and not force:
            return cls._cache
        
        result = {
            "has_gpu": False,
            "gpu_vendor": "none",
            "h264_encoder": HardwareEncoder.NONE,
            "h265_encoder": HardwareEncoder.NONE,
            "available_encoders": [],
        }
        
        try:
            ffmpeg = FFmpegTool.find_ffmpeg()
            r = subprocess.run([ffmpeg, "-encoders"], capture_output=True, text=True, timeout=10)
            out = r.stdout
            
            for name, enum_val in [
                ("h264_nvenc", HardwareEncoder.NVIDIA),
                ("h264_qsv", HardwareEncoder.INTEL),
                ("h264_amf", HardwareEncoder.AMD),
            ]:
                if name in out:
                    result["available_encoders"].append(name)
                    if result["has_gpu"] is False:
                        result["h264_encoder"] = enum_val
                        result["has_gpu"] = True
                        if enum_val == HardwareEncoder.NVIDIA:
                            result["gpu_vendor"] = "nvidia"
                        elif enum_val == HardwareEncoder.INTEL:
                            result["gpu_vendor"] = "intel"
                        elif enum_val == HardwareEncoder.AMD:
                            result["gpu_vendor"] = "amd"
            
            for name, enum_val in [
                ("hevc_nvenc", HardwareEncoder.NVIDIA_HEVC),
                ("hevc_qsv", HardwareEncoder.INTEL_HEVC),
                ("hevc_amf", HardwareEncoder.AMD_HEVC),
            ]:
                if name in out:
                    result["available_encoders"].append(name)
                    if result["h265_encoder"] == HardwareEncoder.NONE:
                        result["h265_encoder"] = enum_val
        except Exception as e:
            logger.warning(f"硬件检测失败: {e}")
        
        cls._cache = result
        return result
    
    @classmethod
    def best_encoder(cls, prefer_quality: bool = False) -> HardwareEncoder:
        info = cls.detect()
        if prefer_quality:
            return info["h265_encoder"] if info["has_gpu"] else HardwareEncoder.NONE
        return info["h264_encoder"] if info["has_gpu"] else HardwareEncoder.NONE


# ============================================================
# 统一渲染管理器
# ============================================================

class RenderManager:
    """
    统一渲染管理器
    
    渲染管线: C++引擎 → FFmpeg CLI → CPU 回退
    特性: 进度+ETA / 优先级队列 / GPU 加速 / 多平台预设
    """
    
    _instance: Optional["RenderManager"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._hw = HardwareDetector.detect()
        self._backend = RenderBackend.CPP_ENGINE
        self._cpp_engine = None
        self._ffmpeg_engine = None
        self._task_queue: deque = deque()
        self._active_task: Optional[RenderTask] = None
        self._history: List[RenderResult] = []
        self._lock = threading.Lock()
        self._running = False
        self._worker: Optional[threading.Thread] = None
        self._cancel_flag = threading.Event()
        self._active_process: Optional[subprocess.Popen] = None

        self._stats = {"total": 0, "completed": 0, "failed": 0, "total_time": 0.0}
        self._cpp_success_count = 0
        self._cpp_fallback_count = 0

        self._init_backends()
    
    def _init_backends(self):
        """初始化后端"""
        # C++ 引擎 (优先)
        try:
            try:
                from app.core.video_processing.cpp_engine import is_cpp_engine_available, get_engine
            except ImportError:
                from core.video_processing.cpp_engine import is_cpp_engine_available, get_engine
            if is_cpp_engine_available():
                self._cpp_engine = get_engine()
                self._backend = RenderBackend.CPP_ENGINE
                logger.info("C++ 引擎已就绪")
        except Exception as e:
            logger.debug(f"C++ 引擎未启用: {e}")
        
        # FFmpeg 引擎 (兼容回退)
        try:
            try:
                from app.modules.lego.professional_video_engine import ProfessionalVideoEngine
            except ImportError:
                from modules.lego.professional_video_engine import ProfessionalVideoEngine
            self._ffmpeg_engine = ProfessionalVideoEngine(max_workers=4)
            if not self._cpp_engine:
                self._backend = RenderBackend.FFMPEG_CLI
            logger.info("FFmpeg 引擎已就绪")
        except Exception as e:
            logger.debug(f"FFmpeg 引擎未加载 (非关键): {e}")
    
    # ---- 配置获取 ----
    
    def get_platform_preset(self, platform: str = "通用HD", mode: RenderMode = RenderMode.STANDARD) -> RenderConfig:
        """获取平台导出预设"""
        preset = PLATFORM_PRESETS.get(platform, PLATFORM_PRESETS["通用HD"]).copy()
        quality = QUALITY_PRESETS[mode].copy()
        
        config = RenderConfig(
            width=preset["width"], height=preset["height"],
            fps=preset["fps"], video_bitrate=preset["video_bitrate"],
            crf=preset["crf"], preset=preset["preset"],
            mode=mode,
        )
        
        if mode == RenderMode.PREVIEW:
            config.width = int(config.width * quality["width_scale"])
            config.height = int(config.height * quality["width_scale"])
            config.preset = quality["preset"]
            config.crf = quality["crf"]
            config.video_bitrate = quality["video_bitrate"]
        elif mode == RenderMode.EXPORT:
            config.preset = quality["preset"]
            config.crf = quality["crf"]
            config.video_bitrate = quality["video_bitrate"]
        
        if self._hw["has_gpu"]:
            encoder = self._hw["h264_encoder"]
            config.gpu_encoder = encoder
            config.video_codec = encoder.value
        
        return config
    
    def get_hardware_info(self) -> Dict[str, Any]:
        """获取硬件信息"""
        return self._hw.copy()
    
    # ---- 视频信息 ----
    
    def probe_video(self, path: str) -> Optional[VideoMeta]:
        """获取视频信息"""
        return FFmpegTool.probe(path)
    
    # ---- 任务管理 ----
    
    def submit(self, task: RenderTask) -> str:
        """提交渲染任务"""
        with self._lock:
            self._task_queue.append(task)
            self._stats["total"] += 1
            task.status = TaskStatus.QUEUED
        logger.info(f"任务已提交: {task.task_id} [{task.operation}]")
        self._start_worker()
        return task.task_id
    
    def submit_quick(self, input_path: str, output_path: str,
                     platform: str = "通用HD", mode: RenderMode = RenderMode.STANDARD,
                     on_progress: Callable = None,
                     on_complete: Callable = None) -> str:
        """快速提交任务"""
        config = self.get_platform_preset(platform, mode)
        task = RenderTask(
            task_id=f"render_{int(time.time() * 1000)}",
            input_path=input_path,
            output_path=output_path,
            config=config,
            operation="export",
            on_progress=on_progress,
            on_complete=on_complete,
        )
        return self.submit(task)
    
    def cancel(self, task_id: str = ""):
        """取消任务"""
        if task_id:
            with self._lock:
                # deque 不支持索引删除，转换为列表操作
                remaining = list(self._task_queue)
                matched = None
                for t in remaining:
                    if t.task_id == task_id:
                        t.status = TaskStatus.CANCELLED
                        matched = t
                        break
                if matched:
                    remaining.remove(matched)
                self._task_queue = deque(remaining)
                if self._active_task and self._active_task.task_id == task_id:
                    self._cancel_flag.set()
                    # 终止 FFmpeg 子进程
                    self._kill_active_process()
        else:
            self._cancel_flag.set()
            self._kill_active_process()
            with self._lock:
                for t in self._task_queue:
                    t.status = TaskStatus.CANCELLED
                self._task_queue.clear()
    
    def _start_worker(self):
        """启动工作线程"""
        if not self._running:
            self._running = True
            self._worker = threading.Thread(target=self._process_loop, daemon=True)
            self._worker.start()
    
    def _process_loop(self):
        """任务处理循环 — 持续运行等待新任务"""
        while self._running:
            task = None
            with self._lock:
                if self._task_queue:
                    self._active_task = self._task_queue.popleft()
                    task = self._active_task

            if task is None:
                time.sleep(0.1)
                continue

            self._cancel_flag.clear()
            task.status = TaskStatus.RUNNING
            task.start_time = time.time()

            try:
                result = self._execute_task(task)
                task.status = TaskStatus.COMPLETED
                task.progress = 100.0
                task.end_time = time.time()

                with self._lock:
                    self._stats["completed"] += 1
                    self._stats["total_time"] += task.end_time - task.start_time
                    self._history.append(result)

                if task.on_complete:
                    try:
                        task.on_complete(result)
                    except Exception as cb_err:
                        logger.error(
                            f"任务 {task.task_id} 完成回调异常: {cb_err}",
                            exc_info=True
                        )

                logger.info(f"任务完成: {task.task_id} ({task.end_time - task.start_time:.1f}s)")

            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                task.end_time = time.time()
                with self._lock:
                    self._stats["failed"] += 1
                logger.error(f"任务失败: {task.task_id} - {e}")

            self._active_task = None

    def _kill_active_process(self):
        """终止当前活动的 FFmpeg 进程"""
        # 设置取消标志让所有 render 循环退出
        if hasattr(self, '_cancel_flag'):
            self._cancel_flag.set()
        if hasattr(self, '_active_process') and self._active_process:
            try:
                self._active_process.kill()
                self._active_process = None
            except Exception:
                pass
    
    def _execute_task(self, task: RenderTask) -> RenderResult:
        """执行渲染任务 — 自动选最优后端: C++引擎 → FFmpeg CLI"""
        start = time.time()
        
        meta = FFmpegTool.probe(task.input_path)
        duration = meta.duration if meta else 0
        
        def progress_cb(pct: float, speed: float, eta: float):
            task.progress = pct
            task.speed = speed
            task.eta = eta
            if task.on_progress:
                try:
                    task.on_progress(pct, speed, eta)
                except Exception:
                    pass
        
        os.makedirs(os.path.dirname(task.output_path) if os.path.dirname(task.output_path) else ".", exist_ok=True)
        
        # --- 优先尝试 C++ 引擎 (高性能路径) ---
        if self._cpp_engine:
            try:
                from app.core.video_processing.cpp_engine import ExportConfig
                cpp_config = ExportConfig()
                cpp_config.codec = task.config.video_codec
                cpp_config.preset = task.config.preset
                cpp_config.bitrate = _parse_bitrate(task.config.video_bitrate, 5000000)
                cpp_config.audio_bitrate = _parse_bitrate(task.config.audio_bitrate, 128000)
                cpp_config.width = task.config.width
                cpp_config.height = task.config.height
                cpp_config.fps = task.config.fps

                result = self._cpp_engine.convert_format(
                    task.input_path, task.output_path, cpp_config,
                    progress_callback=progress_cb
                )
                if result.success:
                    self._cpp_success_count += 1
                    elapsed = time.time() - start
                    output_size = os.path.getsize(task.output_path) if os.path.exists(task.output_path) else 0
                    logger.info(f"C++引擎渲染成功: {task.task_id} ({elapsed:.1f}s)")
                    return RenderResult(task_id=task.task_id, success=True,
                                        output_path=task.output_path, processing_time=elapsed,
                                        output_size=output_size)
            except Exception as e:
                self._cpp_fallback_count += 1
                logger.debug(f"C++ 引擎渲染失败, 回退 FFmpeg CLI: {e}")
        
        # --- FFmpeg CLI 回退 ---
        cfg = task.config
        args = []
        
        # GPU 加速参数优化（必须放在 -i 之前）
        if cfg.video_codec in ("h264_nvenc", "hevc_nvenc"):
            args += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        elif cfg.video_codec in ("h264_qsv", "hevc_qsv"):
            args += ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"]
        elif cfg.video_codec in ("h264_amf", "hevc_amf"):
            args += ["-hwaccel", "d3d11va"]
        
        args += ["-i", task.input_path]
        
        args += [
            "-c:v", cfg.video_codec, "-b:v", cfg.video_bitrate,
            "-r", str(cfg.fps), "-pix_fmt", cfg.pix_fmt, "-preset", cfg.preset,
        ]
        
        if cfg.video_codec in ("libx264", "libx265"):
            args += ["-crf", str(cfg.crf)]
        
        if cfg.video_codec in ("h264_nvenc", "hevc_nvenc"):
            args += ["-rc", "cbr", "-gpu", "0"]
        elif cfg.video_codec in ("h264_qsv", "hevc_qsv"):
            args += ["-init_qpP", "24"]
        
        args += [
            "-vf", f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=decrease,"
                   f"pad={cfg.width}:{cfg.height}:(ow-iw)/2:(oh-ih)/2",
            "-c:a", cfg.audio_codec, "-b:a", cfg.audio_bitrate,
            "-movflags", "+faststart",
        ]
        
        if cfg.video_codec in ("h264_nvenc", "hevc_nvenc"):
            args += ["-gpu", "0"]
        
        args += cfg.extra_args
        args.append(task.output_path)

        process_holder = []
        self._active_process = None
        success, error = FFmpegTool.run(args, progress_cb, duration,
                                        cancel_flag=self._cancel_flag,
                                        process_holder=process_holder)
        self._active_process = None

        elapsed = time.time() - start
        output_size = os.path.getsize(task.output_path) if success and os.path.exists(task.output_path) else 0
        
        return RenderResult(
            task_id=task.task_id, success=success, output_path=task.output_path,
            processing_time=elapsed, output_size=output_size,
            error_message=error if not success else "",
        )
    
    # ---- 简化接口 ----
    
    def render(self, input_path: str, output_path: str, platform: str = "通用HD",
               on_progress: Callable = None) -> RenderResult:
        """同步渲染一条视频"""
        config = self.get_platform_preset(platform)
        task = RenderTask(
            task_id=f"sync_{int(time.time() * 1000)}",
            input_path=input_path,
            output_path=output_path,
            config=config,
            on_progress=on_progress,
        )
        task.status = TaskStatus.RUNNING
        task.start_time = time.time()
        result = self._execute_task(task)
        task.end_time = time.time()
        with self._lock:
            self._stats["total"] += 1
            self._stats["completed" if result.success else "failed"] += 1
        return result
    
    def batch_render(self, jobs: List[Dict], on_progress: Callable = None) -> List[RenderResult]:
        """批量渲染 (阻塞模式)"""
        results = []
        for i, job in enumerate(jobs):
            cfg = self.get_platform_preset(job.get("platform", "通用HD"))
            if "width" in job:
                cfg.width, cfg.height = job["width"], job["height"]
            
            task = RenderTask(
                task_id=f"batch_{i}_{int(time.time() * 1000)}",
                input_path=job["input"],
                output_path=job["output"],
                config=cfg,
                operation=job.get("operation", "export"),
            )
            task.status = TaskStatus.RUNNING
            task.start_time = time.time()
            result = self._execute_task(task)
            task.end_time = time.time()
            results.append(result)
            if on_progress:
                on_progress(i + 1, len(jobs), result)
        return results
    
    # ---- 状态查询 ----
    
    def get_status(self) -> Dict[str, Any]:
        """获取渲染器状态"""
        with self._lock:
            active = None
            if self._active_task:
                active = {
                    "task_id": self._active_task.task_id,
                    "progress": self._active_task.progress,
                    "speed": self._active_task.speed,
                    "eta": self._active_task.eta,
                }
            return {
                "backend": self._backend.value,
                "hardware": self._hw,
                "active_task": active,
                "queue_size": len(self._task_queue),
                "stats": self._stats.copy(),
            }
    
    def get_stats(self) -> Dict[str, Any]:
        return self._stats.copy()

    def get_render_performance(self) -> Dict[str, Any]:
        """获取详细渲染性能统计（供 PerformanceModule 使用）"""
        with self._lock:
            history = list(self._history[-20:])
            stats = self._stats.copy()

        total = stats.get("total", 0)
        completed = stats.get("completed", 0)
        failed = stats.get("failed", 0)
        total_time = stats.get("total_time", 0.0)

        avg_time = total_time / completed if completed > 0 else 0.0

        recent = []
        for r in history[-5:]:
            recent.append({
                "task_id": r.task_id if hasattr(r, 'task_id') else "?",
                "success": r.success if hasattr(r, 'success') else False,
                "time": r.processing_time if hasattr(r, 'processing_time') else 0,
                "size_mb": round((r.output_size or 0) / (1024 * 1024), 1) if hasattr(r, 'output_size') else 0,
            })

        total_frames_est = total_time * 30.0
        avg_fps = completed / (total_time / 60) if total_time > 0 and completed > 0 else 0

        cpp_total = self._cpp_success_count + self._cpp_fallback_count
        cpp_success_rate = round(self._cpp_success_count / cpp_total * 100, 1) if cpp_total > 0 else 0

        return {
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / total * 100, 1) if total > 0 else 0,
            "total_time_sec": round(total_time, 1),
            "avg_time_sec": round(avg_time, 1),
            "avg_tasks_per_min": round(avg_fps, 1),
            "total_frames_est": int(total_frames_est),
            "recent_5": recent,
            "queue_size": len(self._task_queue),
            "active_task": self._active_task.task_id if self._active_task else None,
            "active_progress": self._active_task.progress if self._active_task else 0,
            "backend": self._backend.value,
            "cpp_success_count": self._cpp_success_count,
            "cpp_fallback_count": self._cpp_fallback_count,
            "cpp_success_rate": cpp_success_rate,
        }

    def shutdown(self):
        """关闭渲染器"""
        self._running = False
        self._cancel_flag.set()
        if self._ffmpeg_engine:
            self._ffmpeg_engine.shutdown()


# ============================================================
# 全局实例
# ============================================================

def get_render_manager() -> RenderManager:
    """获取全局渲染管理器"""
    return RenderManager()
