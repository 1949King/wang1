"""
AI特效算法模块集合
包含风格迁移、背景替换、超分辨率、智能美颜、物体移除等AI特效
"""

from .style_transfer import StyleTransferEffect
from .background_replace import BackgroundReplaceEffect
from .super_resolution import SuperResolutionEffect
from .beauty_filter import BeautyFilterEffect
from .object_removal import ObjectRemovalEffect

__all__ = [
    "StyleTransferEffect",
    "BackgroundReplaceEffect",
    "SuperResolutionEffect",
    "BeautyFilterEffect",
    "ObjectRemovalEffect"
]
