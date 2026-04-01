"""
GPU渲染器 - 第二阶段核心组件
=======================================
提供基于GPU的硬件加速渲染，支持CUDA、OpenCL等
目标：高性能渲染，支持4K视频，GPU利用率优化
"""

import os
import subprocess
import tempfile
import threading
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time

from app.modules.utils.logger import logger

class GPUBackend(Enum):
    """GPU后端类型"""
    CUDA = "cuda"      # NVIDIA CUDA
    OPENCL = "opencl"  # OpenCL
    METAL = "metal"    # Apple Metal
    VULKAN = "vulkan"  # Vulkan
    AUTO = "auto"     # 自动选择

class GPUFormat(Enum):
    """GPU格式"""
    RGBA8 = "rgba8unorm"
    RGB8 = "rgb8"
    RGB16 = "rgb16"
    RGBA16 = "rgba16"

class GPUPrecision(Enum):
    """GPU精度"""
    FP32 = "float32"
    FP16 = "float16"
    INT8 = "int8"

@dataclass
class GPUConfig:
    """GPU渲染配置"""
    backend: GPUBackend = GPUBackend.AUTO
    format: GPUFormat = GPUFormat.RGBA8
    precision: GPUPrecision = GPUPrecision.FP32
    max_batch_size: int = 32  # 最大批处理大小
    enable_tensorrt: bool = False  # 是否启用TensorRT
    memory_limit_mb: int = 2048  # GPU内存限制（MB）
    enable_async: bool = True  # 是否启用异步渲染
    fps: float = 30.0  # 帧率
    width: int = 1280  # 默认720P宽度
    height: int = 720  # 默认720P高度

@dataclass
class GPUFrameData:
    """GPU帧数据"""
    video_path: str
    frame_index: int
    timestamp: float
    effects: List[str] = field(default_factory=list)
    filters: List[str] = field(default_factory=list)
    transform: Optional[Dict[str, Any]] = None
    output_format: str = "rgba8unorm"

@dataclass
class GPURenderResult:
    """GPU渲染结果"""
    success: bool
    output_path: Optional[str] = None
    frame_count: int = 0
    duration: float = 0.0
    gpu_utilization: float = 0.0
    error_message: Optional[str] = None
    render_time: float = 0.0

class GPURenderer:
    """增强GPU渲染器"""
    
    def __init__(self, config: Optional[GPUConfig] = None):
        self.config = config or GPUConfig()
        self._initialized = False
        self._rendering = False
        self._current_frame = 0
        self._total_frames = 0
        self._lock = threading.Lock()
        self._temp_dir = tempfile.mkdtemp(prefix="gpu_render_")
        self._gpu_info = None
        
        logger.info(f"GPU渲染器初始化: 后端={self.config.backend.value}")
    
    def initialize(self) -> bool:
        """初始化GPU渲染器"""
        if self._initialized:
            logger.warning("GPU渲染器已初始化")
            return False
        
        try:
            # 检测GPU可用性
            self._detect_gpu()
            
            # 检查FFmpeg GPU支持
            self._check_ffmpeg_gpu()
            
            self._initialized = True
            logger.info("GPU渲染器初始化成功")
            return True
            
        except Exception as e:
            logger.error(f"GPU渲染器初始化失败: {e}")
            return False
    
    def _detect_gpu(self):
        """检测GPU信息"""
        try:
            # 检查CUDA
            import torch
            if torch.cuda.is_available():
                self._gpu_info = {
                    'backend': GPUBackend.CUDA,
                    'device_name': torch.cuda.get_device_name(0),
                    'device_count': torch.cuda.device_count(),
                    'total_memory': torch.cuda.get_device_properties(0).total_memory / (1024**3)
                }
                logger.info(f"检测到CUDA GPU: {self._gpu_info['device_name']}")
            else:
                # 检查OpenCL
                try:
                    import pyopencl
                    platforms = pyopencl.get_platforms()
                    if platforms:
                        self._gpu_info = {
                            'backend': GPUBackend.OPENCL,
                            'platform_name': platforms[0].name,
                            'device_count': len(platforms[0].get_devices())
                        }
                        logger.info(f"检测到OpenCL GPU: {self._gpu_info['platform_name']}")
                except ImportError:
                    pass
            
        except Exception as e:
            logger.warning(f"GPU检测失败: {e}")
            self._gpu_info = {
                'backend': GPUBackend.AUTO,
                'device_name': 'CPU',
                'device_count': 0
            }
    
    def _check_ffmpeg_gpu(self):
        """检查FFmpeg的GPU支持"""
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            output = result.stdout + result.stderr
            if 'nvenc' in output.lower():
                logger.info("FFmpeg支持NVIDIA NVENC")
            elif 'qsv' in output.lower():
                logger.info("FFmpeg支持Intel QSV")
            elif 'amf' in output.lower():
                logger.info("FFmpeg支持AMD AMF")
            elif 'videotoolbox' in output.lower():
                logger.info("FFmpeg支持VideoToolBox")
            else:
                logger.info("FFmpeg未检测到GPU加速")
                
        except Exception as e:
            logger.warning(f"FFmpeg GPU检查失败: {e}")
    
    def render_frame(self, frame_data: GPUFrameData) -> Optional[GPURenderResult]:
        """GPU渲染单帧"""
        if not self._initialized:
            return GPURenderResult(
                success=False,
                error_message="渲染器未初始化"
            )
        
        with self._lock:
            if self._rendering:
                logger.warning("GPU渲染器正在渲染中")
                return GPURenderResult(
                    success=False,
                    error_message="GPU渲染器忙碌"
                )
            
            self._rendering = True
            start_time = time.time()
            
            try:
                # 构建GPU渲染命令
                cmd = self._build_gpu_command(frame_data)
                
                # 执行GPU渲染
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                render_time = time.time() - start_time
                self._rendering = False
                
                if result.returncode == 0:
                    return GPURenderResult(
                        success=True,
                        frame_count=1,
                        render_time=render_time,
                        gpu_utilization=self._estimate_gpu_utilization()
                    )
                else:
                    error_msg = result.stderr if result.stderr else "未知错误"
                    return GPURenderResult(
                        success=False,
                        error_message=f"GPU渲染失败: {error_msg}"
                    )
                    
            except Exception as e:
                self._rendering = False
                logger.error(f"GPU帧渲染异常: {e}")
                return GPURenderResult(
                    success=False,
                    error_message=str(e)
                )
    
    def is_gpu_available(self) -> bool:
        """检查GPU是否可用"""
        return self._gpu_info is not None and self._gpu_info.get('device_count', 0) > 0
    
    def render_sequence(self, frame_data_list: List[GPUFrameData], 
                   output_path: str) -> GPURenderResult:
        """GPU渲染视频序列"""
        if not self._initialized:
            return GPURenderResult(
                success=False,
                error_message="渲染器未初始化"
            )
        
        if not frame_data_list:
            return GPURenderResult(
                success=False,
                error_message="帧数据列表为空"
            )
        
        with self._lock:
            if self._rendering:
                logger.warning("GPU渲染器正在渲染中")
                return GPURenderResult(
                    success=False,
                    error_message="GPU渲染器忙碌"
                )
            
            self._rendering = True
            start_time = time.time()
            
            try:
                # 创建临时文件列表
                temp_files = []
                for i, frame_data in enumerate(frame_data_list):
                    temp_file = os.path.join(
                        self._temp_dir,
                        f"frame_{i:06d}.png"
                    )
                    temp_files.append(temp_file)
                
                # GPU渲染所有帧
                success_count = 0
                for i, frame_data in enumerate(frame_data_list):
                    result = self.render_frame(frame_data)
                    if result.success:
                        success_count += 1
                    else:
                        logger.warning(f"帧{i}渲染失败: {result.error_message}")
                
                # 合成视频
                if success_count > 0:
                    video_result = self._combine_frames_to_video_gpu(
                        temp_files, output_path
                    )
                else:
                    video_result = GPURenderResult(
                        success=False,
                        error_message="所有帧渲染失败"
                    )
                
                # 清理临时文件
                for temp_file in temp_files:
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except Exception as e:
                        logger.warning(f"清理临时文件失败: {e}")
                
                self._rendering = False
                render_time = time.time() - start_time
                
                return video_result
                
            except Exception as e:
                self._rendering = False
                logger.error(f"GPU序列渲染异常: {e}")
                return GPURenderResult(
                    success=False,
                    error_message=str(e)
                )
    
    def _build_gpu_command(self, frame_data: GPUFrameData, output_path: str = None) -> List[str]:
        """构建GPU渲染命令"""
        cmd = ['ffmpeg']
        
        # 输入
        cmd.extend(['-i', frame_data.video_path])
        
        # GPU加速
        if self.config.backend == GPUBackend.CUDA:
            cmd.extend(['-hwaccel', 'cuda'])
        elif self.config.backend == GPUBackend.OPENCL:
            cmd.extend(['-hwaccel', 'opencl'])
        elif self.config.backend == GPUBackend.METAL:
            cmd.extend(['-hwaccel', 'videotoolbox'])
        elif self.config.backend == GPUBackend.VULKAN:
            cmd.extend(['-hwaccel', 'vulkan'])
        
        # 滤镜和特效
        all_filters = []
        if frame_data.effects:
            all_filters.extend(frame_data.effects)
        if frame_data.filters:
            all_filters.extend(frame_data.filters)
        if all_filters:
            filters_str = ','.join(all_filters)
            cmd.extend(['-vf', filters_str])
        
        # 输出配置
        cmd.extend([
            '-s', f'{self.config.width}x{self.config.height}',
            '-r', str(self.config.fps)
        ])
        
        # 精度和格式
        if self.config.precision == GPUPrecision.FP16:
            cmd.extend(['-pix_fmt', 'rgb48f'])
        elif self.config.precision == GPUPrecision.INT8:
            cmd.extend(['-pix_fmt', 'rgb24'])
        elif self.config.format == GPUFormat.RGBA8:
            cmd.extend(['-pix_fmt', 'rgba'])
        elif self.config.format == GPUFormat.RGB16:
            cmd.extend(['-pix_fmt', 'rgb16'])
        else:
            cmd.extend(['-pix_fmt', 'yuv420p'])
        
        # 编码器
        if self.config.backend == GPUBackend.CUDA:
            cmd.extend(['-c:v', 'h264_nvenc'])
            cmd.extend(['-preset', 'p6'])
        else:
            cmd.extend(['-c:v', 'h264'])
            cmd.extend(['-preset', 'medium'])
        
        # 音频
        cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
        
        # 输出文件
        if output_path:
            cmd.append(output_path)
        else:
            # 单帧渲染时输出到管道
            cmd.extend(['-f', 'image2pipe', '-'])
        
        return cmd
    
    def _combine_frames_to_video_gpu(self, frame_files: List[str], 
                                   output_path: str) -> GPURenderResult:
        """GPU合成视频"""
        try:
            # 构建GPU合成命令
            cmd = [
                'ffmpeg',
                '-y',
                '-framerate', str(self.config.fps),
                '-i', f"concat:{'|'.join(frame_files)}"
            ]
            
            # GPU加速
            if self.config.backend == GPUBackend.CUDA:
                cmd.extend(['-hwaccel', 'cuda'])
                cmd.extend(['-c:v', 'h264_nvenc'])
                cmd.extend(['-preset', 'p6'])
            elif self.config.backend == GPUBackend.OPENCL:
                cmd.extend(['-hwaccel', 'opencl'])
            
            # 输出配置
            cmd.extend([
                '-c:v', 'h264',
                '-preset', 'medium',
                '-s', f'{self.config.width}x{self.config.height}',
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart'
            ])
            
            # 音频
            cmd.extend([
                '-c:a', 'aac',
                '-b:a', '128k',
                '-shortest'
            ])
            
            # 输出文件
            cmd.append(output_path)
            
            # 执行合成
            start_time = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            render_time = time.time() - start_time
            
            if result.returncode == 0:
                return GPURenderResult(
                    success=True,
                    output_path=output_path,
                    frame_count=len(frame_files),
                    duration=0.0,
                    render_time=render_time,
                    gpu_utilization=self._estimate_gpu_utilization()
                )
            else:
                error_msg = result.stderr if result.stderr else "未知错误"
                return GPURenderResult(
                    success=False,
                    error_message=f"GPU视频合成失败: {error_msg}"
                    )
                
        except Exception as e:
            logger.error(f"GPU视频合成异常: {e}")
            return GPURenderResult(
                success=False,
                error_message=str(e)
                )
    
    def _estimate_gpu_utilization(self) -> float:
        """估算GPU利用率"""
        # 简单估算，实际需要更精确的监控
        base_utilization = 0.3  # 基础利用率30%
        
        if self._gpu_info and self._gpu_info.get('backend') == GPUBackend.CUDA:
            # CUDA通常有更高的利用率
            base_utilization = 0.5
        
        return base_utilization
    
    def get_gpu_info(self) -> Optional[Dict[str, Any]]:
        """获取GPU信息"""
        if not self._initialized:
            return None
        return self._gpu_info
    
    def get_render_stats(self) -> Dict[str, Any]:
        """获取渲染统计"""
        with self._lock:
            return {
                'initialized': self._initialized,
                'rendering': self._rendering,
                'current_frame': self._current_frame,
                'total_frames': self._total_frames,
                'gpu_info': self._gpu_info,
                'config': {
                    'backend': self.config.backend.value,
                    'format': self.config.format.value,
                    'precision': self.config.precision.value,
                    'max_batch_size': self.config.max_batch_size,
                    'width': self.config.width,
                    'height': self.config.height,
                    'fps': self.config.fps
                }
            }
    
    def set_backend(self, backend: GPUBackend):
        """设置GPU后端"""
        self.config.backend = backend
        logger.info(f"GPU后端设置为: {backend.value}")
    
    def set_precision(self, precision: GPUPrecision):
        """设置GPU精度"""
        self.config.precision = precision
        logger.info(f"GPU精度设置为: {precision.value}")
    
    def set_resolution(self, width: int, height: int):
        """设置渲染分辨率"""
        self.config.width = width
        self.config.height = height
        logger.info(f"GPU渲染分辨率设置为: {width}x{height}")
    
    def set_fps(self, fps: float):
        """设置帧率"""
        self.config.fps = fps
        logger.info(f"GPU渲染帧率设置为: {fps}")
    
    def shutdown(self) -> bool:
        """关闭GPU渲染器"""
        with self._lock:
            self._rendering = False
            self._initialized = False
            
            # 清理临时目录
            try:
                import shutil
                if os.path.exists(self._temp_dir):
                    shutil.rmtree(self._temp_dir)
                    logger.info("清理GPU渲染器临时目录")
            except Exception as e:
                logger.error(f"清理临时目录失败: {e}")
        
        return True

# 全局GPU渲染器实例
gpu_renderer = None

def get_gpu_renderer(config: Optional[GPUConfig] = None) -> GPURenderer:
    """获取GPU渲染器实例（单例模式）"""
    global gpu_renderer
    if gpu_renderer is None:
        gpu_renderer = GPURenderer(config)
    return gpu_renderer