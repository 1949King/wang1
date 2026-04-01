"""
暗调特效插件
悬疑场景的暗调特效
"""

import numpy as np
from typing import Dict, Any

from app.core.plugin_loader import (
    IEffectPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(IEffectPlugin):
    """插件入口 - 暗调特效"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="suspense_dark_tone",
            name="暗调特效",
            version="1.0.0",
            description="悬疑场景的暗调特效，增强紧张氛围",
            author="ShortPlayAI",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.SUSPENSE,
            file_path=__file__,
            tags=["悬疑", "暗调", "紧张"]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        return True
    
    def shutdown(self) -> bool:
        return True
    
    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "暗调特效",
            "icon": "🌑",
            "params": [
                {
                    "name": "darkness",
                    "type": "slider",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.5,
                    "label": "暗度",
                    "description": "暗调程度"
                },
                {
                    "name": "contrast",
                    "type": "slider",
                    "min": 0.5,
                    "max": 2.0,
                    "default": 1.2,
                    "label": "对比度",
                    "description": "对比度调整"
                },
                {
                    "name": "vignette",
                    "type": "slider",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.3,
                    "label": "暗角",
                    "description": "暗角强度"
                }
            ]
        }
    
    def apply_effect(self, frame_data: Any, params: Dict[str, Any]) -> Any:
        """应用暗调特效"""
        darkness = params.get("darkness", 0.5)
        contrast = params.get("contrast", 1.2)
        vignette = params.get("vignette", 0.3)
        
        if isinstance(frame_data, np.ndarray):
            return self._apply_dark_tone(frame_data, darkness, contrast, vignette)
        
        return frame_data
    
    def _apply_dark_tone(self, frame: np.ndarray, darkness: float,
                        contrast: float, vignette: float) -> np.ndarray:
        """应用暗调效果"""
        result = frame.astype(np.float32) * (1 - darkness)
        result = (result - 128) * contrast + 128
        
        if vignette > 0:
            height, width = frame.shape[:2]
            center_x, center_y = width // 2, height // 2
            max_radius = min(width, height) // 2
            
            y, x = np.ogrid[:height, :width]
            radius = np.sqrt((x - center_x)**2 + (y - center_y)**2)
            vignette_mask = (radius / max_radius) ** 2 * vignette
            
            result = result * (1 - vignette_mask[..., np.newaxis])
        
        result = np.clip(result, 0, 255).astype(np.uint8)
        return result
    
    def get_effect_params(self) -> Dict[str, Any]:
        return {
            "darkness": {
                "type": "float",
                "min": 0.0,
                "max": 1.0,
                "default": 0.5,
                "description": "暗调程度"
            },
            "contrast": {
                "type": "float",
                "min": 0.5,
                "max": 2.0,
                "default": 1.2,
                "description": "对比度调整"
            },
            "vignette": {
                "type": "float",
                "min": 0.0,
                "max": 1.0,
                "default": 0.3,
                "description": "暗角强度"
            }
        }
