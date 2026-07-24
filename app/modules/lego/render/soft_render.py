"""
软件渲染器 - 基于Qt6的CPU渲染
=========================================
兼容性好，支持低配设备，作为轻量级内核的基础渲染器
"""

import numpy as np
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import QObject, QThread
from PyQt6.QtGui import QImage, QPixmap, QPainter
import logging
import time

from . import IRenderer, RenderContext, RenderStats

logger = logging.getLogger("AI短剧编辑器.soft_render")


class SoftRenderer(QObject, IRenderer):
    """软件渲染器 - 基于Qt6的CPU渲染"""
    
    def __init__(self):
        super().__init__()
        self._initialized = False
        self._width = 1920
        self._height = 1080
        self._quality = "high"
        self._stats = RenderStats()
        self._render_thread: Optional[QThread] = None
        self._is_rendering = False
    
    def initialize(self) -> bool:
        """初始化软件渲染器"""
        try:
            logger.info("初始化软件渲染器")
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"软件渲染器初始化失败: {e}")
            return False
    
    def render_frame(self, frame_data: Dict[str, Any]) -> Optional[QImage]:
        """渲染单帧"""
        if not self._initialized:
            logger.error("渲染器未初始化")
            return None
        
        try:
            width = frame_data.get('width', self._width)
            height = frame_data.get('height', self._height)
            
            if 'image_data' in frame_data:
                image_data = frame_data['image_data']
                if isinstance(image_data, np.ndarray):
                    qimage = QImage(
                        image_data.data,
                        image_data.shape[1],
                        image_data.shape[0],
                        QImage.Format.Format_RGB888
                    )
                    
                    if self._quality == 'low':
                        qimage = qimage.scaled(
                            width // 2,
                            height // 2,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        )
                    
                    return qimage
            
            if 'pixels' in frame_data:
                pixels = frame_data['pixels']
                if isinstance(pixels, (list, tuple)):
                    qimage = QImage(
                        pixels,
                        width,
                        height,
                        QImage.Format.Format_RGB888
                    )
                    
                    if self._quality == 'low':
                        qimage = qimage.scaled(
                            width // 2,
                            height // 2,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        )
                    
                    return qimage
            
            logger.warning(f"无法渲染帧，缺少图像数据: {list(frame_data.keys())}")
            return None
            
        except Exception as e:
            logger.error(f"渲染帧失败: {e}")
            return None
    
    def render_sequence(self, sequence_data: List[Dict[str, Any]]) -> bool:
        """渲染序列"""
        if not self._initialized:
            logger.error("渲染器未初始化")
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
            
            logger.info(f"软件渲染序列完成: {success_count}/{len(sequence_data)} 帧，耗时: {total_time:.2f}秒")
            return success_count == len(sequence_data)
            
        except Exception as e:
            logger.error(f"渲染序列失败: {e}")
            return False
    
    def cleanup(self) -> None:
        """清理资源"""
        try:
            logger.info("清理软件渲染器资源")
            self._initialized = False
            self._is_rendering = False
            
            if self._render_thread and self._render_thread.is_alive():
                self._render_thread.quit()
                self._render_thread.wait()
            
            self._stats = None
            
        except Exception as e:
            logger.error(f"清理软件渲染器失败: {e}")
    
    def get_capabilities(self) -> Dict[str, Any]:
        """获取渲染能力"""
        return {
            'renderer_type': 'software',
            'hardware_acceleration': False,
            'max_resolution': '4096x2160',
            'supported_formats': ['RGB', 'RGBA', 'YUV'],
            'supported_effects': ['brightness', 'contrast', 'saturation', 'hue'],
            'quality_levels': ['low', 'medium', 'high'],
            'threading': True,
            'memory_efficient': True,
            'cpu_only': True
        }
    
    def set_quality(self, quality: str) -> None:
        """设置渲染质量"""
        if quality in ['low', 'medium', 'high']:
            self._quality = quality
            logger.info(f"软件渲染器质量设置为: {quality}")
        else:
            logger.warning(f"无效的质量设置: {quality}")
    
    def get_quality(self) -> str:
        """获取当前渲染质量"""
        return self._quality
    
    def set_resolution(self, width: int, height: int) -> None:
        """设置分辨率"""
        self._width = width
        self._height = height
        logger.info(f"软件渲染器分辨率设置为: {width}x{height}")
    
    def get_resolution(self) -> tuple:
        """获取当前分辨率"""
        return (self._width, self._height)
    
    def _apply_effects(self, image: QImage, effects: List[Dict[str, Any]]) -> QImage:
        """应用效果到图像"""
        if not effects:
            return image
        
        try:
            painter = QPainter(image)
            
            for effect in effects:
                effect_type = effect.get('type')
                params = effect.get('params', {})
                
                if effect_type == 'brightness':
                    brightness = params.get('value', 0)
                    painter.fillRect(0, 0, image.width(), image.height(), QColor(brightness, brightness, brightness, 100))
                
                elif effect_type == 'contrast':
                    contrast = params.get('value', 1.0)
                    image = self._apply_contrast(image, contrast)
                
                elif effect_type == 'saturation':
                    saturation = params.get('value', 1.0)
                    image = self._apply_saturation(image, saturation)
                
                elif effect_type == 'hue':
                    hue = params.get('value', 0)
                    image = self._apply_hue(image, hue)
            
            painter.end()
            return image
            
        except Exception as e:
            logger.error(f"应用效果失败: {e}")
            return image
    
    def _apply_contrast(self, image: QImage, contrast: float) -> QImage:
        """应用对比度效果 - 修复uint32→float32类型转换"""
        try:
            width, height = image.width(), image.height()
            ptr = image.bits()
            arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 4))[:, :, :3]
            arr = arr.astype(np.float32)
            arr = (arr - 128.0) * contrast + 128.0
            arr = np.clip(arr, 0, 255).astype(np.uint8)
            qimg = QImage(arr.data, width, height, width * 3, QImage.Format.Format_RGB888)
            return qimg.copy()
        except Exception as e:
            logger.error(f"应用对比度失败: {e}")
            return image
    
    def _apply_saturation(self, image: QImage, saturation: float) -> QImage:
        """应用饱和度效果"""
        try:
            import numpy as np
            
            width = image.width()
            height = image.height()
            
            ptr = image.bits()
            ptr = ptr.astype(np.uint32)
            
            arr = np.frombuffer(ptr, np.uint32).reshape((height, width, 4))
            
            rgb = arr[:, :, :3].astype(np.float32)
            gray = np.dot(rgb, [0.299, 0.587, 0.114])
            result = rgb + (rgb - gray[:, :, np.newaxis]) * saturation
            result = np.clip(result, 0, 255).astype(np.uint8)
            
            qimage = QImage(result.data, width, height, QImage.Format.Format_RGBA8888)
            return qimage
            
        except Exception as e:
            logger.error(f"应用饱和度失败: {e}")
            return image
    
    def _apply_hue(self, image: QImage, hue: int) -> QImage:
        """应用色调效果 - cv2 HSV矢量化"""
        try:
            width, height = image.width(), image.height()
            ptr = image.bits()
            rgb = np.frombuffer(ptr, np.uint8).reshape((height, width, 4))[:, :, :3]
            hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
            hsv[:, :, 0] = (hsv[:, :, 0].astype(np.int32) + hue) % 180
            result = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
            qimg = QImage(result.data, width, height, width * 3, QImage.Format.Format_RGB888)
            return qimg.copy()
        except Exception as e:
            logger.error(f"应用色调失败: {e}")
            return image