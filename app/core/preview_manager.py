from app.modules.utils.logger import logger
from typing import Optional, Dict, Any
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QImage, QPixmap
import threading
import time
from collections import OrderedDict
import gc

from app.core.memory_optimization import get_memory_pool, MemoryStrategy

class PreviewManager:
    def __init__(self):
        self.current_time = 0.0
        self.is_playing = False
        self.playing_speed = 1.0
        self.preview_window = None
        self.timecode_visible = True
        
        self.preview_cache = OrderedDict()
        self.max_cache_size = 100
        self.proxy_preview_enabled = True
        self.current_proxy_task = None
        self.preview_quality = 'high'
        self._proxy_task_lock = threading.RLock()
        
        # 内存池集成
        self._memory_pool = get_memory_pool(max_size_mb=256, strategy=MemoryStrategy.LRU)
        
        # 缓存清理定时器
        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._cleanup_cache)
        self._cleanup_timer.start(30000)  # 每30秒清理一次
        
        self.preview_updated = pyqtSignal(float, str)
        self.proxy_preview_ready = pyqtSignal(QImage)
    
    def update_preview(self, time, video_data=None, effects=None):
        """实时更新预览窗口"""
        self.current_time = time
        
        if self.preview_window:
            if self.proxy_preview_enabled and self._should_use_proxy_preview(video_data):
                self._update_proxy_preview(time, effects)
            else:
                self._update_direct_preview(time, video_data, effects)
    
    def _update_direct_preview(self, time: float, video_data: Optional[Dict] = None, effects: Optional[Dict] = None):
        """直接更新预览"""
        try:
            # 生成预览帧
            frame = self._generate_preview_frame(time, video_data, effects)
            
            # 缓存预览帧
            cache_key = f"preview:{time:.2f}"
            self.preview_cache[cache_key] = (time.time(), frame)
            
            # 限制缓存大小
            while len(self.preview_cache) > self.max_cache_size:
                self.preview_cache.popitem(last=False)
            
            logger.debug(f"直接更新预览: {time:.2f}秒")
            
        except Exception as e:
            logger.error(f"直接更新预览失败: {e}")
    
    def _generate_preview_frame(self, time: float, video_data: Optional[Dict] = None, effects: Optional[Dict] = None):
        """生成预览帧"""
        try:
            import numpy as np
            
            # 生成默认帧
            width = 1920
            height = 1080
            
            if self.preview_quality == 'low':
                width = 640
                height = 360
            elif self.preview_quality == 'medium':
                width = 1280
                height = 720
            
            frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
            
            # 应用效果
            if effects:
                frame = self._apply_effects(frame, effects)
            
            # 存储到内存池
            frame_key = f"frame:{time:.2f}"
            self._memory_pool.allocate(frame_key, frame)
            
            return frame
            
        except Exception as e:
            logger.error(f"生成预览帧失败: {e}")
            return None
    
    def drag_timeline_preview(self, start_time, end_time, current_time):
        """拖拽时间轴预览"""
        # 这里应该实现拖拽时间轴时的预览逻辑
        logger.info(f"拖拽时间轴预览: 从 {start_time:.2f} 到 {end_time:.2f}，当前 {current_time:.2f}")
        
        # 更新预览
        self.update_preview(current_time)
        return True
    
    def format_timecode(self, seconds):
        """格式化时间码"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
    
    def set_timecode_visibility(self, visible):
        """设置时间码可见性"""
        self.timecode_visible = visible
        logger.info(f"时间码可见性: {visible}")
        return True
    
    def set_preview_window(self, window):
        """设置预览窗口"""
        self.preview_window = window
        logger.info("设置预览窗口成功")
        return True
    
    def play_preview(self, start_time=None, speed=1.0):
        """开始预览播放"""
        self.is_playing = True
        self.playing_speed = speed
        if start_time is not None:
            self.current_time = start_time
        
        logger.info(f"开始预览播放，从 {self.current_time:.2f} 秒开始，速度: {speed}x")
        return True
    
    def pause_preview(self):
        """暂停预览播放"""
        self.is_playing = False
        logger.info(f"暂停预览播放，当前时间: {self.current_time:.2f}秒")
        return True
    
    def stop_preview(self):
        """停止预览播放"""
        self.is_playing = False
        self.current_time = 0.0
        logger.info("停止预览播放")
        return True
    
    def _should_use_proxy_preview(self, video_data) -> bool:
        """判断是否应该使用代理预览"""
        if not video_data:
            return False
        
        video_path = video_data.get('path', '')
        if not video_path:
            return False
            
        video_size = Path(video_path).stat().st_size if Path(video_path).exists() else 0
        
        return video_size > 10 * 1024 * 1024 and self.proxy_preview_enabled
    
    def _update_proxy_preview(self, time: float, effects: Optional[Dict] = None):
        """更新代理预览（4K素材压缩预览）"""
        if not self.preview_window:
            return
            
        try:
            if self.current_proxy_task and self.current_proxy_task.is_alive():
                self.current_proxy_task.cancel()
            
            self.current_proxy_task = threading.Thread(
                target=self._generate_proxy_preview,
                args=(time, effects),
                daemon=True
            )
            self.current_proxy_task.start()
            logger.info("启动代理预览任务")
            
        except Exception as e:
            logger.error(f"代理预览任务启动失败: {e}")
    
    def _generate_proxy_preview(self, time: float, effects: Optional[Dict] = None):
        """生成代理预览帧"""
        try:
            import numpy as np
            
            width = 1920
            height = 1080
            
            if self.preview_quality == 'high':
                width = 960
                height = 540
            
            frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
            
            if effects:
                frame = self._apply_effects(frame, effects)
            
            qimage = QImage(
                frame.data,
                width,
                height,
                QImage.Format.Format_RGB888
            )
            
            pixmap = QPixmap.fromImage(qimage)
            self.proxy_preview_ready.emit(pixmap)
            logger.debug(f"生成代理预览帧: {time:.2f}秒")
            
        except Exception as e:
            logger.error(f"生成代理预览帧失败: {e}")
    
    def _apply_effects(self, frame, effects: Dict) -> np.ndarray:
        """应用效果到帧"""
        if not effects:
            return frame
            
        try:
            brightness = effects.get('brightness', 0)
            contrast = effects.get('contrast', 1.0)
            
            frame = frame.astype(np.float32)
            frame = frame * contrast + brightness
            frame = np.clip(frame, 0, 255).astype(np.uint8)
            
            return frame
            
        except Exception as e:
            logger.error(f"应用效果失败: {e}")
            return frame
    
    def set_proxy_preview_enabled(self, enabled: bool):
        """设置代理预览开关"""
        self.proxy_preview_enabled = enabled
        logger.info(f"代理预览: {'启用' if enabled else '禁用'}")
    
    def set_preview_quality(self, quality: str):
        """设置预览质量"""
        self.preview_quality = quality
        logger.info(f"预览质量设置为: {quality}")
    
    def clear_preview_cache(self):
        """清理预览缓存"""
        self.preview_cache.clear()
        logger.info("预览缓存已清理")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        memory_stats = self._memory_pool.get_stats()
        return {
            'cache_size': len(self.preview_cache),
            'max_size': self.max_cache_size,
            'usage_percent': len(self.preview_cache) / self.max_cache_size * 100,
            'memory_pool_stats': memory_stats
        }
    
    def _cleanup_cache(self):
        """清理预览缓存"""
        with self._proxy_task_lock:
            # 清理过期缓存
            current_time = time.time()
            keys_to_remove = []
            
            # 清理超过10分钟未访问的缓存项
            for key, (timestamp, _) in self.preview_cache.items():
                if current_time - timestamp > 600:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                if key in self.preview_cache:
                    del self.preview_cache[key]
            
            # 确保缓存不超过最大大小
            while len(self.preview_cache) > self.max_cache_size:
                self.preview_cache.popitem(last=False)
            
            # 优化内存池
            self._memory_pool.optimize_memory()
            
            # 触发垃圾回收
            gc.collect()
            
            if keys_to_remove:
                logger.info(f"清理了 {len(keys_to_remove)} 个过期预览缓存项")
    
    def optimize_memory(self):
        """优化内存使用"""
        self._cleanup_cache()
        self._memory_pool.optimize_memory()
        gc.collect()
        
        stats = self.get_cache_stats()
        logger.info(f"内存优化完成: 缓存大小={stats['cache_size']}, 内存使用={stats['memory_pool_stats']['current_size_mb']:.2f}MB")
    
    def shutdown(self):
        """关闭预览管理器"""
        # 停止定时器
        self._cleanup_timer.stop()
        
        # 清理缓存
        self.clear_preview_cache()
        
        # 清理内存池
        self._memory_pool.clear()
        
        # 触发垃圾回收
        gc.collect()
        
        logger.info("预览管理器已关闭")