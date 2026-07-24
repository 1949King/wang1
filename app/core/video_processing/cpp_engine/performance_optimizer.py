"""
Py+C++ 混合内核 - 性能优化模块
================================
提供 C++ 引擎的性能优化功能，包括 GPU 加速、多线程、内存优化等
"""

import os
import sys
import time
import psutil
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("AI短剧编辑器.performance_optimizer")


class GPUEncoder(Enum):
    """GPU 编码器枚举"""
    NVIDIA_NVENC = "h264_nvenc"
    NVIDIA_HEVC = "hevc_nvenc"
    AMD_AMF = "h264_amf"
    INTEL_QSV = "h264_qsv"
    CPU_X264 = "libx264"
    CPU_X265 = "libx265"


@dataclass
class SystemResources:
    """系统资源信息"""
    cpu_count: int
    cpu_usage: float
    memory_total: float
    memory_used: float
    memory_percent: float
    gpu_available: bool
    gpu_name: str
    gpu_memory_total: float
    gpu_memory_used: float


@dataclass
class PerformanceConfig:
    """性能配置"""
    thread_count: int
    gpu_enabled: bool
    gpu_encoder: str
    cache_size_mb: int
    batch_size: int
    quality_preset: str


class PerformanceOptimizer:
    """性能优化器"""
    
    def __init__(self):
        """初始化性能优化器"""
        self._config = self._detect_optimal_config()
        self._gpu_encoder = self._detect_gpu_encoder()
    
    def _detect_optimal_config(self) -> PerformanceConfig:
        """检测最优配置"""
        cpu_count = psutil.cpu_count(logical=True)
        memory = psutil.virtual_memory()
        
        # 根据 CPU 核心数设置线程数
        thread_count = max(4, cpu_count - 2)
        
        # 根据内存设置缓存大小
        cache_size_mb = min(2048, int(memory.total * 0.3 / (1024 * 1024)))
        
        # 根据内存设置批量大小
        batch_size = 16 if memory.total > 8 * 1024 * 1024 * 1024 else 8
        
        return PerformanceConfig(
            thread_count=thread_count,
            gpu_enabled=False,
            gpu_encoder="libx264",
            cache_size_mb=cache_size_mb,
            batch_size=batch_size,
            quality_preset="fast"
        )
    
    def _detect_gpu_encoder(self) -> str:
        """检测 GPU 编码器 — 统一入口 GPUDetector"""
        try:
            from app.core.gpu_acceleration import get_gpu_detector
            gpu = get_gpu_detector().detect_gpu()
            if gpu.gpu_type.value == "nvidia":
                return "h264_nvenc"
            elif gpu.gpu_type.value == "amd":
                return "h264_amf"
            elif gpu.gpu_type.value == "intel":
                return "h264_qsv"
            return "libx264"
        except Exception:
            # 回退: 直接查 FFmpeg 编码器
            try:
                import subprocess
                result = subprocess.run(
                    ["ffmpeg", "-encoders"], capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                out = result.stdout
                if "h264_nvenc" in out: return "h264_nvenc"
                elif "h264_amf" in out: return "h264_amf"
                elif "h264_qsv" in out: return "h264_qsv"
                return "libx264"
            except Exception:
                return "libx264"
    
    def get_system_resources(self) -> SystemResources:
        """获取系统资源信息"""
        cpu_count = psutil.cpu_count(logical=True)
        cpu_usage = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        
        gpu_available = self._gpu_encoder != "libx264"
        gpu_name = ""
        gpu_memory_total = 0
        gpu_memory_used = 0
        
        if gpu_available:
            try:
                from app.core.gpu_acceleration import get_gpu_detector
                gpu = get_gpu_detector().detect_gpu()
                gpu_name = gpu.name
                gpu_memory_total = gpu.memory_mb
                gpu_memory_used = 0
            except Exception:
                pass
        
        return SystemResources(
            cpu_count=cpu_count, cpu_usage=cpu_usage,
            memory_total=memory.total / (1024 * 1024),
            memory_used=memory.used / (1024 * 1024),
            memory_percent=memory.percent,
            gpu_available=gpu_available,
            gpu_name=gpu_name,
            gpu_memory_total=gpu_memory_total,
            gpu_memory_used=gpu_memory_used
        )
    
    def get_optimal_config(self) -> PerformanceConfig:
        """获取最优配置"""
        resources = self.get_system_resources()
        
        config = PerformanceConfig(
            thread_count=self._config.thread_count,
            gpu_enabled=resources.gpu_available,
            gpu_encoder=self._gpu_encoder,
            cache_size_mb=self._config.cache_size_mb,
            batch_size=self._config.batch_size,
            quality_preset=self._config.quality_preset
        )
        
        # 根据系统资源调整配置
        if resources.memory_percent > 80:
            config.cache_size_mb = max(256, config.cache_size_mb // 2)
            config.batch_size = max(4, config.batch_size // 2)
        
        if resources.cpu_usage > 70:
            config.thread_count = max(2, config.thread_count // 2)
        
        return config
    
    def optimize_for_export(self, video_duration: float,
                           resolution: Tuple[int, int]) -> PerformanceConfig:
        """
        针对导出优化配置
        
        Args:
            video_duration: 视频时长（秒）
            resolution: 分辨率 (width, height)
            
        Returns:
            优化后的配置
        """
        config = self.get_optimal_config()
        
        width, height = resolution
        
        # 根据分辨率调整质量预设
        if width >= 3840:  # 4K
            config.quality_preset = "medium"
            config.batch_size = max(4, config.batch_size // 2)
        elif width >= 1920:  # 1080p
            config.quality_preset = "fast"
        else:  # 720p 或更低
            config.quality_preset = "ultrafast"
            config.batch_size = min(32, config.batch_size * 2)
        
        # 根据视频时长调整线程数
        if video_duration > 300:  # 5 分钟以上
            config.thread_count = min(8, config.thread_count)
        elif video_duration > 60:  # 1 分钟以上
            config.thread_count = min(6, config.thread_count)
        
        return config
    
    def get_encoder_command(self, config: PerformanceConfig) -> str:
        """
        获取编码器命令行参数
        
        Args:
            config: 性能配置
            
        Returns:
            FFmpeg 编码器参数
        """
        if config.gpu_enabled:
            if config.gpu_encoder == "h264_nvenc":
                return f"-c:v h264_nvenc -preset p4 -tune hq"
            elif config.gpu_encoder == "h264_amf":
                return f"-c:v h264_amf -quality quality"
            elif config.gpu_encoder == "h264_qsv":
                return f"-c:v h264_qsv -preset veryfast"
        
        return f"-c:v libx264 -preset {config.quality_preset} -threads {config.thread_count}"
    
    def estimate_processing_time(self, video_duration: float,
                                resolution: Tuple[int, int],
                                config: PerformanceConfig) -> float:
        """
        估算处理时间
        
        Args:
            video_duration: 视频时长（秒）
            resolution: 分辨率
            config: 性能配置
            
        Returns:
            估算处理时间（秒）
        """
        width, height = resolution
        pixels = width * height
        
        # 基准处理速度（像素/秒）
        base_speed = 50_000_000  # 5000 万像素/秒
        
        # GPU 加速
        if config.gpu_enabled:
            base_speed *= 3
        
        # 分辨率影响
        resolution_factor = pixels / (1920 * 1080)
        
        # 质量预设影响
        quality_factors = {
            "ultrafast": 0.3,
            "fast": 0.6,
            "medium": 1.0,
            "slow": 1.5,
            "veryslow": 2.5
        }
        quality_factor = quality_factors.get(config.quality_preset, 1.0)
        
        # 计算处理时间
        processing_time = (video_duration * resolution_factor * quality_factor *
                          (1920 * 1080) / base_speed)
        
        return max(processing_time, 1.0)
    
    def get_performance_report(self) -> Dict:
        """
        获取性能报告
        
        Returns:
            性能报告字典
        """
        resources = self.get_system_resources()
        config = self.get_optimal_config()
        
        return {
            "system": {
                "cpu_count": resources.cpu_count,
                "cpu_usage": resources.cpu_usage,
                "memory_total_mb": resources.memory_total,
                "memory_used_mb": resources.memory_used,
                "memory_percent": resources.memory_percent,
                "gpu_available": resources.gpu_available,
                "gpu_name": resources.gpu_name
            },
            "config": {
                "thread_count": config.thread_count,
                "gpu_enabled": config.gpu_enabled,
                "gpu_encoder": config.gpu_encoder,
                "cache_size_mb": config.cache_size_mb,
                "batch_size": config.batch_size,
                "quality_preset": config.quality_preset
            },
            "recommendations": self._get_recommendations(resources, config)
        }
    
    def _get_recommendations(self, resources: SystemResources,
                           config: PerformanceConfig) -> List[str]:
        """获取优化建议"""
        recommendations = []
        
        if resources.memory_percent > 80:
            recommendations.append("内存使用率过高，建议关闭其他应用")
        
        if resources.cpu_usage > 70:
            recommendations.append("CPU 使用率过高，建议降低线程数")
        
        if not resources.gpu_available:
            recommendations.append("未检测到 GPU，建议使用 GPU 加速以提高性能")
        
        if config.cache_size_mb < 512:
            recommendations.append("缓存较小，建议增加内存以提高缓存大小")
        
        return recommendations


# 全局优化器实例
_optimizer = None


def get_optimizer() -> PerformanceOptimizer:
    """获取全局性能优化器实例"""
    global _optimizer
    if _optimizer is None:
        _optimizer = PerformanceOptimizer()
    return _optimizer
