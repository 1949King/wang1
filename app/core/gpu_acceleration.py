"""
GPU加速渲染模块
================
实现GPU硬件加速渲染，提升渲染性能
"""

import os
import logging
import threading
import time
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import RenderError, ErrorCode

logger = logging.getLogger(__name__)


class GPUType(Enum):
    """GPU类型"""
    NONE = "none"
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"


class HardwareAccelType(Enum):
    """硬件加速类型"""
    NONE = "none"
    CUDA = "cuda"
    OPENCL = "opencl"
    QUICKSYNC = "quicksync"
    VAAPI = "vaapi"


@dataclass
class GPUInfo:
    """GPU信息"""
    gpu_type: GPUType
    name: str
    memory_mb: int
    cuda_available: bool
    opencl_available: bool
    quicksync_available: bool
    driver_version: str
    compute_capability: Optional[str] = None


class GPUDetector:
    """GPU检测器"""
    
    def __init__(self):
        self._gpu_info: Optional[GPUInfo] = None
        self._detection_cache: Dict[str, Any] = {}
        self._lock = threading.Lock()
    
    def detect_gpu(self, force_redetect: bool = False) -> GPUInfo:
        """检测GPU信息
        
        Args:
            force_redetect: 是否强制重新检测
        
        Returns:
            GPU信息对象
        """
        if self._gpu_info is not None and not force_redetect:
            return self._gpu_info
        
        with self._lock:
            if self._gpu_info is not None and not force_redetect:
                return self._gpu_info
            
            logger.info("开始检测GPU...")
            
            # 检测NVIDIA GPU
            nvidia_info = self._detect_nvidia()
            
            # 检测AMD GPU
            amd_info = self._detect_amd()
            
            # 检测Intel GPU
            intel_info = self._detect_intel()
            
            # 合并检测结果
            self._gpu_info = self._merge_gpu_info(nvidia_info, amd_info, intel_info)
            
            logger.info(f"GPU检测完成: {self._gpu_info.name} ({self._gpu_info.gpu_type.value})")
            
            return self._gpu_info
    
    def _detect_nvidia(self) -> Optional[Dict[str, Any]]:
        """检测NVIDIA GPU"""
        try:
            import subprocess
            
            # 检查nvidia-smi
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total,driver_version,compute_cap', '--format=csv,noheader'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                info = result.stdout.strip().split(',')
                if len(info) >= 4:
                    return {
                        'gpu_type': GPUType.NVIDIA,
                        'name': info[0].strip(),
                        'memory_mb': self._parse_memory(info[1].strip()),
                        'driver_version': info[2].strip(),
                        'compute_capability': info[3].strip(),
                        'cuda_available': True,
                        'opencl_available': True,
                        'quicksync_available': False
                    }
            
            # 检查CUDA
            try:
                import torch
                if torch.cuda.is_available():
                    return {
                        'gpu_type': GPUType.NVIDIA,
                        'name': torch.cuda.get_device_name(0),
                        'memory_mb': torch.cuda.get_device_properties(0).total_memory // (1024 * 1024),
                        'driver_version': torch.version.cuda,
                        'compute_capability': f"{torch.cuda.get_device_capability(0)[0]}.{torch.cuda.get_device_capability(0)[1]}",
                        'cuda_available': True,
                        'opencl_available': True,
                        'quicksync_available': False
                    }
            except ImportError as e:
                logger.debug(f"[GPUAcceleration] PyTorch不可用: {e}")
            
        except Exception as e:
            logger.debug(f"NVIDIA GPU检测失败: {e}")
        
        return None
    
    def _detect_amd(self) -> Optional[Dict[str, Any]]:
        """检测AMD GPU"""
        try:
            import subprocess
            
            # 检查rocm-smi
            result = subprocess.run(
                ['rocm-smi', '--showproductname', '--showmem', '--usecsvformat'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    return {
                        'gpu_type': GPUType.AMD,
                        'name': lines[0].split('=')[1].strip(),
                        'memory_mb': self._parse_memory(lines[1].split('=')[1].strip()),
                        'driver_version': 'ROCm',
                        'cuda_available': False,
                        'opencl_available': True,
                        'quicksync_available': False
                    }
            
        except Exception as e:
            logger.debug(f"AMD GPU检测失败: {e}")
        
        return None
    
    def _detect_intel(self) -> Optional[Dict[str, Any]]:
        """检测Intel GPU"""
        try:
            import subprocess
            
            # 检查Intel GPU
            result = subprocess.run(
                ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                gpu_names = [line.strip() for line in result.stdout.split('\n') if 'Intel' in line]
                if gpu_names:
                    return {
                        'gpu_type': GPUType.INTEL,
                        'name': gpu_names[0],
                        'memory_mb': 0,  # Intel集成显卡内存通常与系统内存共享
                        'driver_version': 'Intel',
                        'cuda_available': False,
                        'opencl_available': True,
                        'quicksync_available': True
                    }
            
        except Exception as e:
            logger.debug(f"Intel GPU检测失败: {e}")
        
        return None
    
    def _parse_memory(self, memory_str: str) -> int:
        """解析内存字符串"""
        try:
            memory_str = memory_str.upper()
            if 'GB' in memory_str:
                return int(float(memory_str.replace('GB', '').strip()) * 1024)
            elif 'MB' in memory_str:
                return int(float(memory_str.replace('MB', '').strip()))
            elif 'KB' in memory_str:
                return int(float(memory_str.replace('KB', '').strip()) / 1024)
            else:
                return int(memory_str)
        except Exception as e:
            logger.debug(f"[GPUAcceleration] 获取GPU显存失败: {e}")
            return 0
    
    def _merge_gpu_info(self, *infos: Optional[Dict[str, Any]]) -> GPUInfo:
        """合并GPU信息"""
        for info in infos:
            if info is not None:
                return GPUInfo(**info)
        
        # 未检测到GPU
        return GPUInfo(
            gpu_type=GPUType.NONE,
            name="未检测到GPU",
            memory_mb=0,
            cuda_available=False,
            opencl_available=False,
            quicksync_available=False,
            driver_version="N/A"
        )


class GPURenderer:
    """GPU渲染器"""
    
    def __init__(self, gpu_detector: GPUDetector):
        self._gpu_detector = gpu_detector
        self._gpu_info: Optional[GPUInfo] = None
        self._accel_type: HardwareAccelType = HardwareAccelType.NONE
        self._render_queue = []
        self._lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        
        self._performance_stats = {
            'total_renders': 0,
            'gpu_renders': 0,
            'cpu_renders': 0,
            'total_time': 0.0,
            'gpu_time': 0.0,
            'cpu_time': 0.0
        }
    
    def initialize(self) -> bool:
        """初始化GPU渲染器
        
        Returns:
            是否初始化成功
        """
        try:
            # 检测GPU
            self._gpu_info = self._gpu_detector.detect_gpu()
            
            # 选择最佳加速类型
            self._accel_type = self._select_accel_type()
            
            # 初始化线程池
            self._executor = ThreadPoolExecutor(max_workers=4)
            
            logger.info(f"GPU渲染器初始化成功，加速类型: {self._accel_type.value}")
            return True
            
        except Exception as e:
            logger.error(f"GPU渲染器初始化失败: {e}")
            self._accel_type = HardwareAccelType.NONE
            return False
    
    def _select_accel_type(self) -> HardwareAccelType:
        """选择最佳加速类型"""
        if self._gpu_info is None:
            return HardwareAccelType.NONE
        
        # 优先级：CUDA > QuickSync > OpenCL > CPU
        if self._gpu_info.cuda_available:
            logger.info("选择CUDA加速")
            return HardwareAccelType.CUDA
        elif self._gpu_info.quicksync_available:
            logger.info("选择Intel QuickSync加速")
            return HardwareAccelType.QUICKSYNC
        elif self._gpu_info.opencl_available:
            logger.info("选择OpenCL加速")
            return HardwareAccelType.OPENCL
        else:
            logger.info("使用CPU渲染")
            return HardwareAccelType.NONE
    
    @monitor_performance(threshold_warning=1.0, threshold_critical=5.0)
    def render_frame(self, frame_data: np.ndarray, 
                   resolution: Tuple[int, int] = (1920, 1080)) -> np.ndarray:
        """渲染单帧
        
        Args:
            frame_data: 输入帧数据
            resolution: 目标分辨率
        
        Returns:
            渲染后的帧数据
        """
        start_time = time.time()
        
        try:
            if self._accel_type == HardwareAccelType.CUDA:
                result = self._render_with_cuda(frame_data, resolution)
            elif self._accel_type == HardwareAccelType.QUICKSYNC:
                result = self._render_with_quicksync(frame_data, resolution)
            elif self._accel_type == HardwareAccelType.OPENCL:
                result = self._render_with_opencl(frame_data, resolution)
            else:
                result = self._render_with_cpu(frame_data, resolution)
            
            # 更新性能统计
            render_time = time.time() - start_time
            self._update_stats(render_time, use_gpu=self._accel_type != HardwareAccelType.NONE)
            
            return result
            
        except Exception as e:
            logger.error(f"帧渲染失败: {e}")
            raise RenderError(
                ErrorCode.RENDER_ERROR,
                f"帧渲染失败: {str(e)}",
                details={'accel_type': self._accel_type.value, 'resolution': resolution}
            )
    
    def _render_with_cuda(self, frame_data: np.ndarray, 
                       resolution: Tuple[int, int]) -> np.ndarray:
        """使用CUDA渲染"""
        try:
            import cupy as cp
            
            # 转换为GPU数组
            gpu_frame = cp.asarray(frame_data)
            
            # 执行GPU渲染操作
            # 这里可以添加具体的渲染逻辑
            result = gpu_frame
            
            # 转换回CPU数组
            return cp.asnumpy(result)
            
        except ImportError:
            logger.warning("CuPy未安装，回退到CPU渲染")
            return self._render_with_cpu(frame_data, resolution)
        except Exception as e:
            logger.error(f"CUDA渲染失败: {e}")
            return self._render_with_cpu(frame_data, resolution)
    
    def _render_with_quicksync(self, frame_data: np.ndarray,
                             resolution: Tuple[int, int]) -> np.ndarray:
        """使用Intel QuickSync渲染"""
        try:
            # 这里需要集成Intel Media SDK或OpenCV的QuickSync支持
            # 由于OpenCV的QuickSync支持有限，这里使用OpenCV的基本功能
            
            import cv2
            
            # 调整分辨率
            if frame_data.shape[:2] != resolution:
                result = cv2.resize(frame_data, resolution)
            else:
                result = frame_data.copy()
            
            return result
            
        except Exception as e:
            logger.error(f"QuickSync渲染失败: {e}")
            return self._render_with_cpu(frame_data, resolution)
    
    def _render_with_opencl(self, frame_data: np.ndarray,
                           resolution: Tuple[int, int]) -> np.ndarray:
        """使用OpenCL渲染"""
        try:
            import pyopencl as cl
            
            # 创建OpenCL上下文
            ctx = cl.create_some_context()
            queue = cl.CommandQueue(ctx)
            
            # 转换数据格式
            frame_buffer = cl.Buffer(
                ctx,
                cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
                frame_data.nbytes,
                hostbuf=frame_data
            )
            
            # 创建输出缓冲区
            output_buffer = cl.Buffer(
                ctx,
                cl.mem_flags.WRITE_ONLY,
                frame_data.nbytes
            )
            
            # 执行OpenCL内核
            # 这里需要编写OpenCL内核代码
            # 简化版本：直接复制数据
            cl.enqueue_copy_buffer(queue, frame_buffer, output_buffer)
            
            # 读取结果
            result = np.empty_like(frame_data)
            cl.enqueue_copy_buffer(queue, output_buffer, result).wait()
            
            return result
            
        except ImportError:
            logger.warning("PyOpenCL未安装，回退到CPU渲染")
            return self._render_with_cpu(frame_data, resolution)
        except Exception as e:
            logger.error(f"OpenCL渲染失败: {e}")
            return self._render_with_cpu(frame_data, resolution)
    
    def _render_with_cpu(self, frame_data: np.ndarray,
                       resolution: Tuple[int, int]) -> np.ndarray:
        """使用CPU渲染"""
        try:
            import cv2
            
            # 调整分辨率
            if frame_data.shape[:2] != resolution:
                result = cv2.resize(frame_data, resolution, interpolation=cv2.INTER_LINEAR)
            else:
                result = frame_data.copy()
            
            return result
            
        except Exception as e:
            logger.error(f"CPU渲染失败: {e}")
            raise
    
    def render_sequence(self, frames: List[np.ndarray],
                      resolution: Tuple[int, int] = (1920, 1080)) -> List[np.ndarray]:
        """渲染帧序列
        
        Args:
            frames: 输入帧列表
            resolution: 目标分辨率
        
        Returns:
            渲染后的帧列表
        """
        if not self._executor:
            raise RenderError(
                ErrorCode.RENDER_ERROR,
                "渲染器未初始化"
            )
        
        # 批量渲染
        futures = []
        for frame in frames:
            future = self._executor.submit(self.render_frame, frame, resolution)
            futures.append(future)
        
        # 收集结果
        results = []
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"帧渲染异常: {e}")
        
        return results
    
    def _update_stats(self, render_time: float, use_gpu: bool):
        """更新性能统计"""
        with self._lock:
            self._performance_stats['total_renders'] += 1
            self._performance_stats['total_time'] += render_time
            
            if use_gpu:
                self._performance_stats['gpu_renders'] += 1
                self._performance_stats['gpu_time'] += render_time
            else:
                self._performance_stats['cpu_renders'] += 1
                self._performance_stats['cpu_time'] += render_time
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        with self._lock:
            stats = self._performance_stats.copy()
            
            if stats['total_renders'] > 0:
                stats['avg_render_time'] = stats['total_time'] / stats['total_renders']
                stats['gpu_ratio'] = stats['gpu_renders'] / stats['total_renders']
                stats['cpu_ratio'] = stats['cpu_renders'] / stats['total_renders']
                
                if stats['gpu_renders'] > 0:
                    stats['avg_gpu_time'] = stats['gpu_time'] / stats['gpu_renders']
                if stats['cpu_renders'] > 0:
                    stats['avg_cpu_time'] = stats['cpu_time'] / stats['cpu_renders']
            
            return stats
    
    def get_gpu_info(self) -> Optional[GPUInfo]:
        """获取GPU信息"""
        return self._gpu_info
    
    def get_accel_type(self) -> HardwareAccelType:
        """获取当前加速类型"""
        return self._accel_type
    
    def shutdown(self):
        """关闭渲染器"""
        if self._executor:
            self._executor.shutdown(wait=True)
            logger.info("GPU渲染器已关闭")


class AutoGPURenderer:
    """自动GPU渲染器，根据硬件自动选择最佳渲染方式"""
    
    def __init__(self):
        self._gpu_detector = GPUDetector()
        self._gpu_renderer = GPURenderer(self._gpu_detector)
        self._initialized = False
        import atexit
        atexit.register(self.shutdown)
        import weakref
        self._finalizer = weakref.finalize(self, self.shutdown)
    
    def __del__(self):
        """析构时自动清理资源"""
        self.shutdown()
    
    def initialize(self) -> bool:
        """初始化自动渲染器"""
        self._initialized = self._gpu_renderer.initialize()
        return self._initialized
    
    def render(self, frame_data: np.ndarray,
              resolution: Tuple[int, int] = (1920, 1080),
              force_gpu: bool = False,
              force_cpu: bool = False) -> np.ndarray:
        """智能渲染
        
        Args:
            frame_data: 输入帧数据
            resolution: 目标分辨率
            force_gpu: 强制使用GPU
            force_cpu: 强制使用CPU
        
        Returns:
            渲染后的帧数据
        """
        if not self._initialized:
            self.initialize()
        
        if force_cpu:
            return self._gpu_renderer._render_with_cpu(frame_data, resolution)
        elif force_gpu and self._gpu_renderer._accel_type != HardwareAccelType.NONE:
            return self._gpu_renderer.render_frame(frame_data, resolution)
        else:
            return self._gpu_renderer.render_frame(frame_data, resolution)
    
    def get_info(self) -> Dict[str, Any]:
        """获取渲染器信息"""
        return {
            'gpu_info': self._gpu_renderer.get_gpu_info(),
            'accel_type': self._gpu_renderer.get_accel_type(),
            'performance_stats': self._gpu_renderer.get_performance_stats(),
            'initialized': self._initialized
        }
    
    def shutdown(self):
        """关闭渲染器"""
        self._gpu_renderer.shutdown()
        self._initialized = False


# 全局实例
_global_gpu_detector: Optional[GPUDetector] = None
_global_gpu_renderer: Optional[GPURenderer] = None
_auto_gpu_renderer: Optional[AutoGPURenderer] = None


def get_gpu_detector() -> GPUDetector:
    """获取全局GPU检测器"""
    global _global_gpu_detector
    
    if _global_gpu_detector is None:
        _global_gpu_detector = GPUDetector()
    
    return _global_gpu_detector


def get_gpu_renderer() -> GPURenderer:
    """获取全局GPU渲染器"""
    global _global_gpu_renderer
    
    if _global_gpu_renderer is None:
        gpu_detector = get_gpu_detector()
        _global_gpu_renderer = GPURenderer(gpu_detector)
    
    return _global_gpu_renderer


def get_auto_gpu_renderer() -> AutoGPURenderer:
    """获取全局自动GPU渲染器"""
    global _auto_gpu_renderer
    
    if _auto_gpu_renderer is None:
        _auto_gpu_renderer = AutoGPURenderer()
    
    return _auto_gpu_renderer


def detect_gpu() -> GPUInfo:
    """检测GPU信息（便捷函数）"""
    detector = get_gpu_detector()
    return detector.detect_gpu()