"""
插件包初始化
"""

from .effect_gold_rush import Plugin as GoldRushEffect
from .effect_soft_light import Plugin as SoftLightEffect
from .effect_dark_tone import Plugin as DarkToneEffect
from .effect_highlight import Plugin as HighlightEffect
from .effect_action import Plugin as ActionEffect
from .effect_comedy import Plugin as ComedyEffect
from .effect_horror import Plugin as HorrorEffect
from .transition_fade import Plugin as FadeTransition
from .transition_slide import Plugin as SlideTransition
from .transition_zoom import Plugin as ZoomTransition
from .transition_wipe import Plugin as WipeTransition
from .transition_dissolve import Plugin as DissolveTransition
from .transition_glitch import Plugin as GlitchTransition
from .transition_flip import Plugin as FlipTransition
from .transition_spin import Plugin as SpinTransition

__all__ = [
    'GoldRushEffect',
    'SoftLightEffect',
    'DarkToneEffect',
    'HighlightEffect',
    'ActionEffect',
    'ComedyEffect',
    'HorrorEffect',
    'FadeTransition',
    'SlideTransition',
    'ZoomTransition',
    'WipeTransition',
    'DissolveTransition',
    'GlitchTransition',
    'FlipTransition',
    'SpinTransition'
]
