"""
预览渲染器 - 优化实时预览性能
==================================
基于preview_manager.py的代理预览机制，提供实时预览渲染能力
"""

import numpy as np
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import QObject, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPixmap
import logging
import time

from . import IRenderer, RenderStats

logger = logging.getLogger("AI短剧编辑器.preview_render")


class PreviewRenderer(QObject, IRenderer):
    """预览渲染器 - 优化实时预览性能"""
    
    def __init__(self):
        super().__init__()
        self._initialized = False
        self._width = 1920
        self._height = 1080
        self._quality = "high"
        self._proxy_enabled = True
        self._proxy_scale = 0.5  # 代理预览缩放比例
        self._stats = RenderStats()
        self._preview_cache = {}
        self._max_cache_size = 50
        self._render_thread: Optional[QThread] = None
        self._is_rendering = False
    
    def initialize(self) -> bool:
        """初始化预览渲染器"""
        try:
            logger.info("初始化预览渲染器")
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"预览渲染器初始化失败: {e}")
            return False
    
    def render_frame(self, frame_data: Dict[str, Any]) -> Optional[QImage]:
        """渲染单帧（支持代理预览+帧缓存）"""
        if not self._initialized:
            logger.error("预览渲染器未初始化")
            return None
        
        try:
            width = frame_data.get('width', self._width)
            height = frame_data.get('height', self._height)
            
            if 'image_data' in frame_data:
                image_data = frame_data['image_data']
                frame_id = frame_data.get('frame_id') or hash(image_data.tobytes()[:1024])
                if frame_id in self._preview_cache:
                    return self._preview_cache[frame_id]
                
                if self._proxy_enabled and self._should_use_proxy(width, height):
                    result = self._render_proxy_frame(image_data, width, height)
                else:
                    result = self._render_full_frame(image_data, width, height)
                
                if result and len(self._preview_cache) >= self._max_cache_size:
                    self._preview_cache.popitem(last=False)
                if result:
                    self._preview_cache[frame_id] = result
                return result
            
            logger.warning(f"无法渲染帧，缺少图像数据: {list(frame_data.keys())}")
            return None
            
        except Exception as e:
            logger.error(f"预览渲染帧失败: {e}")
            return None
    
    def _should_use_proxy(self, width: int, height: int) -> bool:
        """判断是否应该使用代理预览"""
        total_pixels = width * height
        return total_pixels > 1920 * 1080  # 超过1080p则使用代理预览
    
    def _render_proxy_frame(self, image_data: np.ndarray, width: int, height: int) -> QImage:
        """渲染代理预览帧 - NumPy矢量化缩放"""
        try:
            step = max(1, int(1.0 / self._proxy_scale))
            if len(image_data.shape) == 3:
                proxy = image_data[::step, ::step, :].copy()
            else:
                proxy = image_data[::step, ::step].copy()
            h, w = proxy.shape[:2]
            channels = 3 if len(proxy.shape) == 3 else 1
            fmt = QImage.Format.Format_RGB888 if channels == 3 else QImage.Format.Format_Grayscale8
            return QImage(proxy.data, w, h, w * channels, fmt)
        except Exception as e:
            logger.error(f"代理预览渲染失败: {e}")
            return None
    
    def _render_full_frame(self, image_data: np.ndarray, width: int, height: int) -> QImage:
        """渲染完整帧"""
        try:
            qimage = QImage(
                image_data.data,
                width,
                height,
                QImage.Format.Format_RGB888
            )
            
            return qimage
            
        except Exception as e:
            logger.error(f"完整预览渲染失败: {e}")
            return None
    
    def render_sequence(self, sequence_data: List[Dict[str, Any]]) -> bool:
        """渲染序列（预览模式）"""
        if not self._initialized:
            logger.error("预览渲染器未初始化")
            return False
        
        try:
            start_time = time.time()
            success_count = 0
            
            for frame_data in sequence_data:
                image = self.render_frame(frame_data)
                if image:
                    success_count += 1
            
            end_time = time.time()
            total_time = end_time - start_time
            
            if self._stats:
                self._stats.frames_rendered = success_count
                self._stats.total_time = total_time
                if total_time > 0:
                    self._stats.average_fps = len(sequence_data) / total_time
            
            logger.info(f"预览渲染序列完成: {success_count}/{len(sequence_data)} 帧，耗时: {total_time:.2f}秒")
            return success_count == len(sequence_data)
            
        except Exception as e:
            logger.error(f"预览渲染序列失败: {e}")
            return False
    
    def cleanup(self) -> None:
        """清理预览渲染器资源"""
        try:
            logger.info("清理预览渲染器资源")
            self._preview_cache.clear()
            self._initialized = False
            self._is_rendering = False
            
            if self._render_thread and self._render_thread.is_alive():
                self._render_thread.quit()
                self._render_thread.wait()
            
            self._stats = None
            
        except Exception as e:
            logger.error(f"清理预览渲染器失败: {e}")
    
    def get_capabilities(self) -> Dict[str, Any]:
        """获取渲染能力"""
        return {
            'renderer_type': 'preview',
            'hardware_acceleration': False,
            'proxy_preview': self._proxy_enabled,
            'proxy_scale': self._proxy_scale,
            'max_resolution': '3840x2160',  # 4K素材支持
            'supported_formats': ['RGB', 'RGBA'],
            'supported_effects': ['brightness', 'contrast', 'saturation'],
            'quality_levels': ['low', 'medium', 'high'],
            'threading': True,
            'memory_efficient': True,
            'realtime': True,
            'cache_enabled': True,
            'max_cache_size': self._max_cache_size
        }
    
    def set_quality(self, quality: str) -> None:
        """设置预览质量"""
        if quality in ['low', 'medium', 'high']:
            self._quality = quality
            logger.info(f"预览渲染器质量设置为: {quality}")
        else:
            logger.warning(f"无效的质量设置: {quality}")
    
    def get_quality(self) -> str:
        """获取当前预览质量"""
        return self._quality
    
    def set_proxy_enabled(self, enabled: bool) -> None:
        """设置代理预览开关"""
        self._proxy_enabled = enabled
        logger.info(f"代理预览: {'启用' if enabled else '禁用'}")
    
    def set_proxy_scale(self, scale: float) -> None:
        """设置代理预览缩放比例"""
        if 0.1 <= scale <= 1.0:
            self._proxy_scale = scale
            logger.info(f"代理预览缩放比例设置为: {scale}")
        else:
            logger.warning(f"无效的缩放比例: {scale}")
    
    def get_proxy_scale(self) -> float:
        """获取代理预览缩放比例"""
        return self._proxy_scale
    
    def clear_cache(self) -> None:
        """清理预览缓存"""
        self._preview_cache.clear()
        logger.info("预览缓存已清理")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            'cache_size': len(self._preview_cache),
            'max_size': self._max_cache_size,
            'usage_percent': len(self._preview_cache) / self._max_cache_size * 100
        }