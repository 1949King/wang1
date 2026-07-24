"""
高亮特效插件
带货场景的高亮特效
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    IEffectPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(IEffectPlugin):
    """插件入口 - 高亮特效"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="selling_highlight",
            name="高亮特效",
            version="1.0.0",
            description="带货场景的高亮特效，突出商品",
            author="ShortPlayAI",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.SELLING,
            file_path=__file__,
            tags=["带货", "高亮", "商品"]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        return True
    
    def shutdown(self) -> bool:
        return True
    
    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "高亮特效",
            "icon": "💡",
            "params": [
                {
                    "name": "brightness",
                    "type": "slider",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.3,
                    "label": "亮度",
                    "description": "高亮亮度"
                },
                {
                    "name": "saturation",
                    "type": "slider",
                    "min": 0.0,
                    "max": 2.0,
                    "default": 1.2,
                    "label": "饱和度",
                    "description": "色彩饱和度"
                },
                {
                    "name": "glow",
                    "type": "slider",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.2,
                    "label": "光晕",
                    "description": "光晕强度"
                }
            ]
        }
    
    def apply_effect(self, frame_data: Any, params: Dict[str, Any]) -> Any:
        """应用高亮特效"""
        brightness = params.get("brightness", 0.3)
        saturation = params.get("saturation", 1.2)
        glow = params.get("glow", 0.2)
        
        if isinstance(frame_data, np.ndarray):
            return self._apply_highlight(frame_data, brightness, saturation, glow)
        
        return frame_data
    
    def _apply_highlight(self, frame: np.ndarray, brightness: float,
                       saturation: float, glow: float) -> np.ndarray:
        """应用高亮效果"""
        result = frame.astype(np.float32)
        
        result = result + brightness * 255
        
        gray = np.mean(result, axis=2)
        result = result * saturation + gray * (1 - saturation)
        
        if glow > 0:
            try:
                from scipy.ndimage import gaussian_filter
                glow_layer = gaussian_filter(result, sigma=10)
                result = result * (1 - glow) + glow_layer * glow
            except ImportError:
                pass
        
        result = np.clip(result, 0, 255).astype(np.uint8)
        return result
    
    def get_effect_params(self) -> Dict[str, Any]:
        return {
            "brightness": {
                "type": "float",
                "min": 0.0,
                "max": 1.0,
                "default": 0.3,
                "description": "高亮亮度"
            },
            "saturation": {
                "type": "float",
                "min": 0.0,
                "max": 2.0,
                "default": 1.2,
                "description": "色彩饱和度"
            },
            "glow": {
                "type": "float",
                "min": 0.0,
                "max": 1.0,
                "default": 0.2,
                "description": "光晕强度"
            }
        }
