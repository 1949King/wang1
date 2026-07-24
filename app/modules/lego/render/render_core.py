"""
render/render_core.py — 渲染核心类
===================================
从 __init__.py 提取的实现类：
- IRenderer: 渲染器抽象接口
- RenderContext: 渲染上下文
- RenderStats: 渲染统计
- RenderManager: 渲染管理器 + 全局实例
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
import logging

logger = logging.getLogger("AI短剧编辑器.render_interface")


class IRenderer(ABC):
    """渲染器抽象接口"""

    @abstractmethod
    def initialize(self) -> bool:
        """初始化渲染器"""
        pass

    @abstractmethod
    def render_frame(self, frame_data: Dict[str, Any]) -> Optional[QImage]:
        """渲染单帧"""
        pass

    @abstractmethod
    def render_sequence(self, sequence_data: List[Dict[str, Any]]) -> bool:
        """渲染序列"""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """清理资源"""
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        """获取渲染能力"""
        pass

    @abstractmethod
    def set_quality(self, quality: str) -> None:
        """设置渲染质量"""
        pass

    @abstractmethod
    def get_quality(self) -> str:
        """获取当前渲染质量"""
        pass


class RenderContext:
    """渲染上下文"""

    def __init__(self):
        self.width = 1920
        self.height = 1080
        self.fps = 30
        self.quality = "high"
        self.effects = []
        self.metadata = {}

    def set_resolution(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def set_fps(self, fps: int) -> None:
        self.fps = fps

    def add_effect(self, effect: Dict[str, Any]) -> None:
        self.effects.append(effect)

    def clear_effects(self) -> None:
        self.effects.clear()

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value


class RenderStats:
    """渲染统计"""

    def __init__(self):
        self.frames_rendered = 0
        self.total_time = 0.0
        self.average_fps = 0.0
        self.errors = 0
        self.warnings = 0

    def update_frame_stats(self, render_time: float) -> None:
        self.frames_rendered += 1
        self.total_time += render_time
        if self.frames_rendered > 0:
            self.average_fps = self.frames_rendered / self.total_time

    def reset(self) -> None:
        self.frames_rendered = 0
        self.total_time = 0.0
        self.average_fps = 0.0
        self.errors = 0
        self.warnings = 0

    def get_stats(self) -> Dict[str, Any]:
        return {
            'frames_rendered': self.frames_rendered,
            'total_time': self.total_time,
            'average_fps': self.average_fps,
            'errors': self.errors,
            'warnings': self.warnings
        }


class RenderManager(QObject):
    """渲染管理器"""

    frame_rendered = pyqtSignal(QImage)
    sequence_completed = pyqtSignal(bool)
    render_error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._current_renderer: Optional[IRenderer] = None
        self._renderers: Dict[str, IRenderer] = {}
        self._context: Optional[RenderContext] = None
        self._stats: Optional[RenderStats] = None
        self._is_rendering = False

    def register_renderer(self, name: str, renderer: IRenderer) -> None:
        self._renderers[name] = renderer
        logger.info(f"注册渲染器: {name}")

    def set_renderer(self, name: str) -> bool:
        if name not in self._renderers:
            logger.error(f"渲染器不存在: {name}")
            return False
        if self._is_rendering:
            logger.warning("正在渲染中，无法切换渲染器")
            return False
        if self._current_renderer:
            self._current_renderer.cleanup()
        self._current_renderer = self._renderers[name]
        self._stats = RenderStats()
        success = self._current_renderer.initialize()
        if success:
            logger.info(f"切换到渲染器: {name}")
            return True
        else:
            logger.error(f"渲染器初始化失败: {name}")
            return False

    def get_current_renderer(self) -> Optional[IRenderer]:
        return self._current_renderer

    def get_available_renderers(self) -> List[str]:
        return list(self._renderers.keys())

    def set_context(self, context: RenderContext) -> None:
        self._context = context

    def get_context(self) -> Optional[RenderContext]:
        return self._context

    def render_frame(self, frame_data: Dict[str, Any]) -> None:
        if not self._current_renderer:
            logger.error("没有设置渲染器")
            return
        try:
            import time
            start_time = time.time()
            image = self._current_renderer.render_frame(frame_data)
            if image:
                end_time = time.time()
                if self._stats:
                    self._stats.update_frame_stats(end_time - start_time)
                self.frame_rendered.emit(image)
            else:
                logger.warning("渲染失败，返回空图像")
                if self._stats:
                    self._stats.errors += 1
        except Exception as e:
            logger.error(f"渲染帧失败: {e}")
            self.render_error.emit(str(e))
            if self._stats:
                self._stats.errors += 1

    def render_sequence(self, sequence_data: List[Dict[str, Any]]) -> None:
        if not self._current_renderer:
            logger.error("没有设置渲染器")
            return
        self._is_rendering = True
        try:
            import time
            start_time = time.time()
            success = self._current_renderer.render_sequence(sequence_data)
            end_time = time.time()
            if self._stats:
                self._stats.total_time = end_time - start_time
                self._stats.frames_rendered = len(sequence_data)
                if end_time - start_time > 0:
                    self._stats.average_fps = len(sequence_data) / (end_time - start_time)
            self.sequence_completed.emit(success)
        except Exception as e:
            logger.error(f"渲染序列失败: {e}")
            self.render_error.emit(str(e))
            if self._stats:
                self._stats.errors += 1
        finally:
            self._is_rendering = False

    def get_stats(self) -> Optional[Dict[str, Any]]:
        if self._stats:
            return self._stats.get_stats()
        return None

    def reset_stats(self) -> None:
        if self._stats:
            self._stats.reset()

    def cleanup(self) -> None:
        if self._current_renderer:
            self._current_renderer.cleanup()
        for renderer in self._renderers.values():
            try:
                renderer.cleanup()
            except Exception as e:
                logger.error(f"清理渲染器失败: {e}")
        self._current_renderer = None
        self._stats = None
        logger.info("渲染管理器已清理")


# 全局渲染管理器实例
render_manager = RenderManager()
