"""
渲染接口抽象层
==================
定义统一的渲染接口，支持多种渲染后端。
实现类已提取到 render_core.py，此处保持向后兼容的 re-export。
"""

from .render_core import (
    IRenderer,
    RenderContext,
    RenderStats,
    RenderManager,
    render_manager,
)
