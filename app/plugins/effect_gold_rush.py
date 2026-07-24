"""
金光特效插件
逆袭时刻的金光特效
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    IEffectPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(IEffectPlugin):
    """插件入口 - 金光特效"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="counterattack_gold_rush",
            name="金光特效",
            version="1.0.0",
            description="逆袭时刻的金光特效，增强视觉冲击力",
            author="ShortPlayAI",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.COUNTERATTACK,
            file_path=__file__,
            tags=["逆袭", "金光", "高光"]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        return True
    
    def shutdown(self) -> bool:
        return True
    
    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "金光特效",
            "icon": "✨",
            "params": [
                {
                    "name": "intensity",
                    "type": "slider",
                    "min": 0.0,
                    "max": 2.0,
                    "default": 1.0,
                    "label": "强度",
                    "description": "金光强度"
                },
                {
                    "name": "color",
                    "type": "color",
                    "default": "#ffd700",
                    "label": "颜色",
                    "description": "金光颜色"
                },
                {
                    "name": "duration",
                    "type": "slider",
                    "min": 0.1,
                    "max": 3.0,
                    "default": 1.0,
                    "label": "持续时间",
                    "description": "特效持续时间"
                }
            ]
        }
    
    def apply_effect(self, frame_data: Any, params: Dict[str, Any]) -> Any:
        """应用金光特效"""
        intensity = params.get("intensity", 1.0)
        color = params.get("color", "#ffd700")
        duration = params.get("duration", 1.0)
        
        if isinstance(frame_data, np.ndarray):
            return self._apply_gold_rush(frame_data, intensity, color)
        
        return frame_data
    
    def _apply_gold_rush(self, frame: np.ndarray, intensity: float, color: str) -> np.ndarray:
        """应用金光效果"""
        height, width = frame.shape[:2]
        
        center_x, center_y = width // 2, height // 2
        max_radius = min(width, height) // 2
        
        y, x = np.ogrid[:height, :width]
        radius = np.sqrt((x - center_x)**2 + (y - center_y)**2)
        
        gold_gradient = np.maximum(0, 1 - radius / max_radius) * intensity
        
        gold_r, gold_g, gold_b = self._hex_to_rgb(color)
        gold_layer = np.zeros_like(frame)
        gold_layer[:, :, 0] = gold_r * gold_gradient
        gold_layer[:, :, 1] = gold_g * gold_gradient
        gold_layer[:, :, 2] = gold_b * gold_gradient
        
        result = frame + gold_layer
        result = np.clip(result, 0, 255).astype(np.uint8)
        
        return result
    
    def _hex_to_rgb(self, hex_color: str) -> tuple:
        """十六进制颜色转RGB"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def get_effect_params(self) -> Dict[str, Any]:
        return {
            "intensity": {
                "type": "float",
                "min": 0.0,
                "max": 2.0,
                "default": 1.0,
                "description": "金光强度"
            },
            "color": {
                "type": "string",
                "default": "#ffd700",
                "description": "金光颜色"
            },
            "duration": {
                "type": "float",
                "min": 0.1,
                "max": 3.0,
                "default": 1.0,
                "description": "特效持续时间"
            }
        }
