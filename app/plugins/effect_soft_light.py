"""
柔光特效插件
情感场景的柔光特效
"""

import logging

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    IEffectPlugin, PluginInfo, PluginType, PluginCategory
)

logger = logging.getLogger(__name__)


class Plugin(IEffectPlugin):
    """插件入口 - 柔光特效"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="emotion_soft_light",
            name="柔光特效",
            version="1.0.0",
            description="情感场景的柔光特效，营造温馨氛围",
            author="ShortPlayAI",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.EMOTION,
            file_path=__file__,
            tags=["情感", "柔光", "温馨"]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        return True
    
    def shutdown(self) -> bool:
        return True
    
    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "柔光特效",
            "icon": "🌸",
            "params": [
                {
                    "name": "intensity",
                    "type": "slider",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.5,
                    "label": "强度",
                    "description": "柔光强度"
                },
                {
                    "name": "color",
                    "type": "color",
                    "default": "#ffb6c1",
                    "label": "色调",
                    "description": "柔光色调"
                },
                {
                    "name": "blur",
                    "type": "slider",
                    "min": 0,
                    "max": 20,
                    "default": 5,
                    "label": "模糊度",
                    "description": "柔光模糊程度"
                }
            ]
        }
    
    def apply_effect(self, frame_data: Any, params: Dict[str, Any]) -> Any:
        """应用柔光特效"""
        intensity = params.get("intensity", 0.5)
        color = params.get("color", "#ffb6c1")
        blur = params.get("blur", 5)
        
        if isinstance(frame_data, np.ndarray):
            return self._apply_soft_light(frame_data, intensity, color, blur)
        
        return frame_data
    
    def _apply_soft_light(self, frame: np.ndarray, intensity: float, 
                        color: str, blur: int) -> np.ndarray:
        """应用柔光效果"""
        soft_r, soft_g, soft_b = self._hex_to_rgb(color)
        soft_layer = np.full_like(frame, [soft_r, soft_g, soft_b], dtype=np.float32)
        
        if blur > 0:
            try:
                from scipy.ndimage import gaussian_filter
                soft_layer[:, :, 0] = gaussian_filter(soft_layer[:, :, 0], sigma=blur)
                soft_layer[:, :, 1] = gaussian_filter(soft_layer[:, :, 1], sigma=blur)
                soft_layer[:, :, 2] = gaussian_filter(soft_layer[:, :, 2], sigma=blur)
            except ImportError as e:
                logger.debug(f"scipy未安装，跳过高斯柔光处理: {e}")
        
        result = frame.astype(np.float32) * (1 - intensity) + soft_layer * intensity
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
                "max": 1.0,
                "default": 0.5,
                "description": "柔光强度"
            },
            "color": {
                "type": "string",
                "default": "#ffb6c1",
                "description": "柔光色调"
            },
            "blur": {
                "type": "int",
                "min": 0,
                "max": 20,
                "default": 5,
                "description": "柔光模糊程度"
            }
        }
