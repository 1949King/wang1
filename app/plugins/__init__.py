"""
插件包初始化
"""

from .effect_gold_rush import Plugin as GoldRushEffect
from .effect_soft_light import Plugin as SoftLightEffect
from .effect_dark_tone import Plugin as DarkToneEffect
from .effect_highlight import Plugin as HighlightEffect
from .transition_fade import Plugin as FadeTransition
from .transition_slide import Plugin as SlideTransition

__all__ = [
    'GoldRushEffect',
    'SoftLightEffect',
    'DarkToneEffect',
    'HighlightEffect',
    'FadeTransition',
    'SlideTransition'
]
