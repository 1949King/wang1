"""
渲染性能优化器 - Week 4核心组件
=====================================
提供渲染性能优化，包括FFmpeg参数优化、缓存机制、批处理
目标：4K导出速度提升30%，GPU利用率优化
"""

import os
import subprocess
import threading
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time
from collections import deque
import platform

from app.modules.utils.logger import logger

try:
    from modules.lego.render.gpu_render import get_gpu_renderer
    GPU_RENDER_AVAILABLE = True
except ImportError:
    GPU_RENDER_AVAILABLE = False

class OptimizationStrategy(Enum):
    """优化策略"""
    SPEED = "speed"          # 速度优先
    QUALITY = "quality"      # 质量优先
    BALANCED = "balanced"    # 平衡模式
    MEMORY = "memory"        # 内存优先

class FFmpegPreset(Enum):
    """FFmpeg预设"""
    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slower"
    VERYSLOW = "veryslow"

class VideoCodec(Enum):
    """视频编码器"""
    H264 = "libx264"
    H265 = "libx265"
    VP9 = "libvpx-vp9"
    PRORES = "prores_ks"
    NVENC_H264 = "h264_nvenc"
    NVENC_H265 = "hevc_nvenc"
    AMF_H264 = "h264_amf"
    AMF_H265 = "hevc_amf"
    QSV_H264 = "h264_qsv"
    QSV_H265 = "hevc_qsv"
    VIDEOTOOLBOX = "h264_videotoolbox"

class HardwareAcceleration(Enum):
    """硬件加速类型"""
    CUDA = "cuda"
    DXVA2 = "dxva2"
    D3D11VA = "d3d11va"
    VIDEOTOOLBOX = "videotoolbox"
    VAAPI = "vaapi"
    QSV = "qsv"
    NONE = "none"

@dataclass
class RenderCacheItem:
    """渲染缓存项"""
    cache_key: str
    frame_data: Any
    rendered_result: Any
    timestamp: float
    size_bytes: int

@dataclass
class BatchRenderTask:
    """批渲染任务"""
    task_id: str
    frame_data_list: List[Any]
    output_path: str
    config: Dict[str, Any]
    status: str = "pending"  # pending, processing, completed, failed
    progress: float = 0.0
    error_message: Optional[str] = None

@dataclass
class PerformanceMetrics:
    """性能指标"""
    total_frames: int = 0
    rendered_frames: int = 0
    total_time: float = 0.0
    avg_fps: float = 0.0
    peak_memory_mb: float = 0.0
    gpu_utilization: float = 0.0

class RenderPerformanceOptimizer:
    """渲染性能优化器"""
    
    def __init__(self):
        self._cache: Dict[str, RenderCacheItem] = {}
        self._cache_lock = threading.Lock()
        self._cache_size_limit = 1000  # 最大缓存项数
        self._cache_memory_limit_mb = 256  # 最大缓存内存（MB）
        self._current_cache_memory_mb = 0.0
        
        self._batch_queue: deque[BatchRenderTask] = deque()
        self._batch_processing = False
        self._batch_lock = threading.Lock()
        
        self._metrics = PerformanceMetrics()
        self._lock = threading.Lock()
        
        # 硬件加速检测
        self._detect_hardware_acceleration()
        
        logger.info("渲染性能优化器初始化")
    
    def _detect_hardware_acceleration(self):
        """检测可用的硬件加速"""
        self._hardware_acceleration = HardwareAcceleration.NONE
        self._available_codecs = []
        self._platform = platform.system().lower()
        
        # 优先使用本地FFmpeg
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self._ffmpeg_path = os.path.join(base, 'thirdparty', 'ffmpeg', 'bin', 'ffmpeg.exe')
        if not os.path.exists(self._ffmpeg_path):
            # 回退到系统PATH中的FFmpeg
            self._ffmpeg_path = 'ffmpeg'
        
        try:
            # 检测FFmpeg是否可用
            result = subprocess.run([self._ffmpeg_path, '-version'], 
                                 capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                logger.warning("FFmpeg不可用，使用软件编码")
                return
            
            # 检测硬件加速
            if self._platform == 'windows':
                # 检测NVIDIA GPU
                result = subprocess.run([self._ffmpeg_path, '-hwaccels'], 
                                     capture_output=True, text=True, timeout=5)
                if 'cuda' in result.stdout.lower():
                    self._hardware_acceleration = HardwareAcceleration.CUDA
                    self._available_codecs.extend([
                        VideoCodec.NVENC_H264,
                        VideoCodec.NVENC_H265
                    ])
                    logger.info("检测到NVIDIA GPU，支持NVENC硬件编码")
                elif 'dxva2' in result.stdout.lower():
                    self._hardware_acceleration = HardwareAcceleration.DXVA2
                    logger.info("检测到DXVA2硬件加速")
            elif self._platform == 'darwin':
                # 检测macOS VideoToolbox
                result = subprocess.run([self._ffmpeg_path, '-hwaccels'], 
                                     capture_output=True, text=True, timeout=5)
                if 'videotoolbox' in result.stdout.lower():
                    self._hardware_acceleration = HardwareAcceleration.VIDEOTOOLBOX
                    self._available_codecs.append(VideoCodec.VIDEOTOOLBOX)
                    logger.info("检测到VideoToolbox硬件加速")
            elif self._platform == 'linux':
                # 检测VAAPI
                result = subprocess.run([self._ffmpeg_path, '-hwaccels'], 
                                     capture_output=True, text=True, timeout=5)
                if 'vaapi' in result.stdout.lower():
                    self._hardware_acceleration = HardwareAcceleration.VAAPI
                    logger.info("检测到VAAPI硬件加速")
        except Exception as e:
            logger.warning(f"硬件加速检测失败: {e}")
    
    def optimize_ffmpeg_params(self, mode: OptimizationStrategy, 
                            resolution: Tuple[int, int],
                            codec: VideoCodec = VideoCodec.H264, 
                            use_hardware_acceleration: bool = True) -> Dict[str, str]:
        """优化FFmpeg参数
        
        Args:
            mode: 优化策略
            resolution: 分辨率（width, height）
            codec: 编码器
            use_hardware_acceleration: 是否使用硬件加速
            
        Returns:
            优化后的FFmpeg参数字典
        """
        width, height = resolution
        
        # 检测是否使用硬件编码
        final_codec = codec
        if use_hardware_acceleration:
            # 根据平台和硬件选择合适的硬件编码器
            if self._platform == 'windows' and self._hardware_acceleration == HardwareAcceleration.CUDA:
                if codec == VideoCodec.H264:
                    final_codec = VideoCodec.NVENC_H264
                elif codec == VideoCodec.H265:
                    final_codec = VideoCodec.NVENC_H265
            elif self._platform == 'darwin' and self._hardware_acceleration == HardwareAcceleration.VIDEOTOOLBOX:
                final_codec = VideoCodec.VIDEOTOOLBOX
        
        # 基础参数
        params = {
            '-c:v': final_codec.value,
        }
        
        # 硬件加速参数
        if use_hardware_acceleration and self._hardware_acceleration != HardwareAcceleration.NONE:
            if self._hardware_acceleration == HardwareAcceleration.CUDA:
                params.update({
                    '-hwaccel': 'cuda',
                    '-hwaccel_output_format': 'cuda'
                })
            elif self._hardware_acceleration == HardwareAcceleration.DXVA2:
                params.update({
                    '-hwaccel': 'dxva2'
                })
            elif self._hardware_acceleration == HardwareAcceleration.VIDEOTOOLBOX:
                params.update({
                    '-hwaccel': 'videotoolbox'
                })
            elif self._hardware_acceleration == HardwareAcceleration.VAAPI:
                params.update({
                    '-hwaccel': 'vaapi',
                    '-vaapi_device': '/dev/dri/renderD128'
                })
        
        # 软件编码器参数
        if final_codec in [VideoCodec.H264, VideoCodec.H265, VideoCodec.VP9]:
            params.update({
                '-preset': self._get_preset(mode, resolution),
                '-tune': self._get_tune(mode)
            })
        
        # 分辨率优化
        if width >= 3840:  # 4K
            if final_codec in [VideoCodec.H264, VideoCodec.H265, VideoCodec.VP9]:
                params.update({
                    '-crf': '18',  # 高质量
                    '-maxrate': '60M',  # 最大码率
                    '-bufsize': '100M'  # 缓冲区大小
                })
        elif width >= 1920:  # 1080P
            if final_codec in [VideoCodec.H264, VideoCodec.H265, VideoCodec.VP9]:
                params.update({
                    '-crf': '20',
                    '-maxrate': '30M',
                    '-bufsize': '50M'
                })
        else:  # 720P及以下
            if final_codec in [VideoCodec.H264, VideoCodec.H265, VideoCodec.VP9]:
                params.update({
                    '-crf': '23',
                    '-maxrate': '20M',
                    '-bufsize': '30M'
                })
        
        # 编码器特定优化
        if final_codec == VideoCodec.H264:
            params.update({
                '-profile:v': 'high',
                '-level': '4.2',
                '-movflags': '+faststart'
            })
        elif final_codec == VideoCodec.H265:
            params.update({
                '-profile:v': 'main',
                '-level': '5.0',
                '-x265-params': 'log-level=error'
            })
        elif final_codec == VideoCodec.NVENC_H264:
            params.update({
                '-preset': 'medium',
                '-rc': 'vbr',
                '-cq': '20',
                '-b:v': '30M',
                '-maxrate': '45M',
                '-bufsize': '90M'
            })
        elif final_codec == VideoCodec.NVENC_H265:
            params.update({
                '-preset': 'medium',
                '-rc': 'vbr',
                '-cq': '23',
                '-b:v': '20M',
                '-maxrate': '30M',
                '-bufsize': '60M'
            })
        
        # 多线程优化
        params.update({
            '-threads': '0',  # 自动使用所有可用线程
            '-async': '1'
        })
        
        logger.debug(f"FFmpeg参数优化: {mode.value}模式, {width}x{height}, 编码器: {final_codec.value}")
        return params
    
    def _get_preset(self, mode: OptimizationStrategy, 
                   resolution: Tuple[int, int]) -> str:
        """获取FFmpeg预设"""
        width, height = resolution
        
        if mode == OptimizationStrategy.SPEED:
            # 速度优先：使用最快预设
            if width >= 3840:
                return FFmpegPreset.FASTER.value
            elif width >= 1920:
                return FFmpegPreset.FAST.value
            else:
                return FFmpegPreset.VERYFAST.value
        
        elif mode == OptimizationStrategy.QUALITY:
            # 质量优先：使用中等预设
            if width >= 3840:
                return FFmpegPreset.MEDIUM.value
            else:
                return FFmpegPreset.FAST.value
        
        elif mode == OptimizationStrategy.BALANCED:
            # 平衡模式：根据分辨率选择
            if width >= 3840:
                return FFmpegPreset.MEDIUM.value
            elif width >= 1920:
                return FFmpegPreset.FAST.value
            else:
                return FFmpegPreset.VERYFAST.value
        
        else:  # MEMORY优先：使用最快预设节省内存
            return FFmpegPreset.ULTRAFAST.value
    
    def _get_tune(self, mode: OptimizationStrategy) -> str:
        """获取FFmpeg调优参数"""
        if mode == OptimizationStrategy.SPEED:
            return 'zerolatency'  # 零延迟
        elif mode == OptimizationStrategy.QUALITY:
            return 'film'  # 电影质量
        elif mode == OptimizationStrategy.BALANCED:
            return 'fastdecode'  # 快速解码
        else:  # MEMORY
            return 'fast'  # 快速处理
    
    def add_to_cache(self, cache_key: str, frame_data: Any, 
                   result: Any, size_bytes: int = 0) -> bool:
        """添加到渲染缓存"""
        with self._cache_lock:
            # 检查缓存大小
            if len(self._cache) >= self._cache_size_limit:
                self._cleanup_cache()
            
            # 检查缓存内存
            if self._current_cache_memory_mb >= self._cache_memory_limit_mb:
                self._cleanup_cache()
            
            # 添加到缓存
            cache_item = RenderCacheItem(
                cache_key=cache_key,
                frame_data=frame_data,
                rendered_result=result,
                timestamp=time.time(),
                size_bytes=size_bytes
            )
            
            self._cache[cache_key] = cache_item
            self._current_cache_memory_mb += size_bytes / (1024 * 1024)
            
            logger.debug(f"添加到缓存: {cache_key}, 当前内存: {self._current_cache_memory_mb:.2f}MB")
            return True
    
    def get_from_cache(self, cache_key: str) -> Optional[Any]:
        """从缓存获取"""
        with self._cache_lock:
            if cache_key in self._cache:
                cache_item = self._cache[cache_key]
                # 更新访问时间
                cache_item.timestamp = time.time()
                return cache_item.rendered_result
            
            return None
    
    def _cleanup_cache(self):
        """清理缓存"""
        with self._cache_lock:
            if not self._cache:
                return
            
            # 按LRU策略清理
            sorted_items = sorted(
                self._cache.items(),
                key=lambda x: x[1].timestamp
            )
            
            # 清理最旧的50%
            items_to_remove = sorted_items[:len(sorted_items) // 2]
            
            for cache_key, cache_item in items_to_remove:
                self._current_cache_memory_mb -= cache_item.size_bytes / (1024 * 1024)
                del self._cache[cache_key]
            
            logger.debug(f"清理缓存: {len(items_to_remove)}个项, 释放内存: {self._current_cache_memory_mb:.2f}MB")
    
    def submit_batch_render(self, task: BatchRenderTask) -> str:
        """提交批渲染任务"""
        with self._batch_lock:
            if self._batch_processing:
                logger.warning("批处理正在进行中")
                return None
            
            self._batch_queue.append(task)
            logger.debug(f"批渲染任务已提交: {task.task_id}")
            return task.task_id
    
    def process_batch_queue(self):
        """处理批渲染队列"""
        while self._batch_queue and not self._batch_processing:
            task = self._batch_queue.popleft()
            self._batch_processing = True
            
            try:
                # 执行批渲染
                self._execute_batch_render(task)
                
                # 更新性能指标
                self._update_metrics(task)
                
            except Exception as e:
                task.status = "failed"
                task.error_message = str(e)
                logger.error(f"批渲染失败: {task.task_id}, 错误: {e}")
            
            self._batch_processing = False
    
    def _execute_batch_render(self, task: BatchRenderTask):
        """执行批渲染"""
        start_time = time.time()
        
        # 尝试从缓存获取
        cached_results = []
        for frame_data in task.frame_data_list:
            cache_key = f"batch_{task.task_id}_{frame_data.get('frame_index', 0)}"
            cached = self.get_from_cache(cache_key)
            if cached:
                cached_results.append(cached)
                logger.debug(f"使用缓存: {cache_key}")
        
        if GPU_RENDER_AVAILABLE:
            gpu_renderer = get_gpu_renderer()
            results = []
            for frame_data in task.frame_data_list:
                frame_array = frame_data.get('data')
                if frame_array is not None:
                    effects_config = frame_data.get('effects_config', {})
                    result = gpu_renderer.render_frame(frame_array, effects_config)
                    results.append(result)
            task.results = results
        else:
            task.results = []
        
        render_time = time.time() - start_time
        
        task.status = "completed"
        task.progress = 100.0
        
        logger.info(f"批渲染完成: {task.task_id}, 耗时: {render_time:.2f}秒")
    
    def _update_metrics(self, task: BatchRenderTask):
        """更新性能指标"""
        with self._lock:
            self._metrics.total_frames += len(task.frame_data_list)
            self._metrics.rendered_frames += len(task.frame_data_list)
            
            # 计算平均FPS
            if task.progress > 0:
                self._metrics.total_time += task.progress / 100.0
                if self._metrics.total_time > 0:
                    self._metrics.avg_fps = self._metrics.rendered_frames / self._metrics.total_time
            
            logger.debug(f"性能指标更新: 总帧数={self._metrics.total_frames}, 已渲染={self._metrics.rendered_frames}, 平均FPS={self._metrics.avg_fps:.2f}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._cache_lock:
            return {
                'cache_size': len(self._cache),
                'cache_memory_mb': self._current_cache_memory_mb,
                'cache_size_limit': self._cache_size_limit,
                'memory_limit_mb': self._cache_memory_limit_mb
            }
    
    def get_batch_stats(self) -> Dict[str, Any]:
        """获取批处理统计"""
        with self._batch_lock:
            return {
                'queue_size': len(self._batch_queue),
                'processing': self._batch_processing,
                'total_submitted': len(self._batch_queue) + self._metrics.total_frames
            }
    
    def get_performance_metrics(self) -> PerformanceMetrics:
        """获取性能指标"""
        with self._lock:
            return self._metrics
    
    def reset_metrics(self):
        """重置性能指标"""
        with self._lock:
            self._metrics = PerformanceMetrics()
            logger.info("性能指标已重置")
    
    def clear_cache(self):
        """清空缓存"""
        with self._cache_lock:
            self._cache.clear()
            self._current_cache_memory_mb = 0.0
            logger.info("缓存已清空")
    
    def clear_batch_queue(self):
        """清空批处理队列"""
        with self._batch_lock:
            self._batch_queue.clear()
            logger.info("批处理队列已清空")
    
    def detect_video_format(self, video_path: str) -> Dict[str, Any]:
        """检测视频格式信息
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            视频格式信息字典
        """
        try:
            # 使用本地ffprobe检测视频信息
            ffprobe_path = os.path.join(os.path.dirname(self._ffmpeg_path), 'ffprobe.exe')
            if not os.path.exists(ffprobe_path):
                ffprobe_path = 'ffprobe'
            
            cmd = [
                ffprobe_path,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                video_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                logger.error(f"格式检测失败: {result.stderr}")
                return {}
            
            import json
            info = json.loads(result.stdout)
            
            # 提取关键信息
            format_info = {
                'format': info.get('format', {}).get('format_name', 'unknown'),
                'duration': float(info.get('format', {}).get('duration', 0)),
                'size': int(info.get('format', {}).get('size', 0)),
                'bit_rate': int(info.get('format', {}).get('bit_rate', 0)),
                'streams': []
            }
            
            # 提取流信息
            for stream in info.get('streams', []):
                if stream.get('codec_type') == 'video':
                    format_info['streams'].append({
                        'type': 'video',
                        'codec': stream.get('codec_name', 'unknown'),
                        'width': int(stream.get('width', 0)),
                        'height': int(stream.get('height', 0)),
                        'fps': (lambda s: (lambda parts: int(parts[0]) / int(parts[1]) if len(parts) == 2 and int(parts[1]) != 0 else 0.0)(s.split('/')))((stream.get('r_frame_rate') or '0/1'))
                    })
                elif stream.get('codec_type') == 'audio':
                    format_info['streams'].append({
                        'type': 'audio',
                        'codec': stream.get('codec_name', 'unknown'),
                        'sample_rate': int(stream.get('sample_rate', 0)),
                        'channels': int(stream.get('channels', 0))
                    })
            
            logger.debug(f"视频格式检测完成: {video_path}")
            return format_info
        except Exception as e:
            logger.error(f"格式检测异常: {e}")
            return {}
    
    def repair_video_index(self, input_path: str, output_path: str) -> bool:
        """修复视频索引
        
        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            
        Returns:
            是否修复成功
        """
        try:
            # 使用本地FFmpeg修复索引
            cmd = [
                self._ffmpeg_path,
                '-i', input_path,
                '-c', 'copy',
                '-map', '0',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                logger.error(f"索引修复失败: {result.stderr}")
                return False
            
            logger.info(f"视频索引修复成功: {input_path} -> {output_path}")
            return True
        except Exception as e:
            logger.error(f"索引修复异常: {e}")
            return False
    
    def get_lossless_params(self) -> Dict[str, str]:
        """获取无损剪辑参数
        
        Returns:
            无损剪辑参数字典
        """
        return {
            '-c:v': 'copy',
            '-c:a': 'copy',
            '-map': '0',
            '-movflags': '+faststart'
        }
    
    def get_hardware_acceleration_info(self) -> Dict[str, Any]:
        """获取硬件加速信息
        
        Returns:
            硬件加速信息字典
        """
        return {
            'hardware_acceleration': self._hardware_acceleration.value,
            'available_codecs': [codec.value for codec in self._available_codecs],
            'platform': self._platform
        }
    
    def optimize_for_low_end(self) -> Dict[str, str]:
        """为低配机优化参数
        
        Returns:
            优化后的参数字典
        """
        return {
            '-c:v': 'libx264',
            '-preset': 'ultrafast',
            '-crf': '28',
            '-threads': '2',
            '-b:v': '5M',
            '-maxrate': '10M',
            '-bufsize': '20M'
        }

# 全局性能优化器实例
render_performance_optimizer = None

def get_render_performance_optimizer() -> RenderPerformanceOptimizer:
    """获取渲染性能优化器实例（单例模式）"""
    global render_performance_optimizer
    if render_performance_optimizer is None:
        render_performance_optimizer = RenderPerformanceOptimizer()
    return render_performance_optimizer