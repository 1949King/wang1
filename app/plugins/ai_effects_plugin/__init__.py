"""
AI特效制作插件
基于深度学习的智能视频/图像特效处理系统
支持：风格迁移、背景替换、超分辨率、智能美颜、物体移除等
"""

import os as _os
import sys as _sys

try:
    from .main import Plugin, AIEffectsWidget
except ImportError:
    _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
    if _pkg_dir not in _sys.path:
        _sys.path.insert(0, _pkg_dir)
    from main import Plugin, AIEffectsWidget

# 插件元信息（符合 PLUGIN_STANDARD.md §1.2 规范）
PLUGIN_INFO = {
    "name": "AI特效制作",
    "version": "1.0.0",
    "author": "拾光剪影官方",
    "description": "基于深度学习的智能特效制作工具，支持风格迁移、背景替换、超分辨率、智能美颜、物体移除等多种AI特效",
    "category": "ai_function",           # AI功能分类
    "icon": "🎨",
    "entry_point": "Plugin",
    "dependencies": ["numpy", "opencv-python", "torch", "Pillow"],
    "tags": ["AI", "深度学习", "风格迁移", "背景替换", "超分辨率", "美颜", "智能特效"],
    "compatibility": {
        "min_version": "4.4.0",
        "max_version": "5.9.9"
    },
    "permissions": ["gpu_access", "model_download", "network"],
    "features": [
        {
            "id": "style_transfer",
            "name": "风格迁移",
            "description": "将图像转换为艺术风格（梵高、莫奈、赛博朋克等）"
        },
        {
            "id": "background_replace",
            "name": "AI背景替换",
            "description": "智能识别前景并替换背景"
        },
        {
            "id": "super_resolution",
            "name": "超分辨率",
            "description": "提升视频/图像分辨率，最高4倍放大"
        },
        {
            "id": "beauty_filter",
            "name": "智能美颜",
            "description": "AI驱动的磨皮、美白、瘦脸等美颜效果"
        },
        {
            "id": "object_removal",
            "name": "智能物体移除",
            "description": "移除画面中的指定物体并自动填充背景"
        }
    ]
}

__all__ = ["Plugin", "AIEffectsWidget", "PLUGIN_INFO"]
