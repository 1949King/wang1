"""
渲染模块 - ShortPlayAI Engine V1.0
===================================
提供软渲染、GPU渲染、预览渲染、导出渲染四大核心能力
对应第一阶段：性能优化
对应第二阶段：渲染模块开发
"""

from .proxy_preview import ProxyPreviewRenderer, get_proxy_preview_renderer
from .soft_render import SoftwareRenderer
from .gpu_render import GPURenderer
from .preview_render import PreviewRenderer
from .export_render import ExportRenderer
from .render_manager import RenderManager, get_render_manager
from .render_performance_optimizer import RenderPerformanceOptimizer, get_render_performance_optimizer

__all__ = [
    'ProxyPreviewRenderer',
    'get_proxy_preview_renderer',
    'SoftwareRenderer',
    'GPURenderer',
    'PreviewRenderer',
    'ExportRenderer',
    'RenderManager',
    'get_render_manager',
    'RenderPerformanceOptimizer',
    'get_render_performance_optimizer'
]