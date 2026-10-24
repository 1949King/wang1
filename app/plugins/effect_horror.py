"""
恐怖特效插件
恐怖场景的惊悚特效
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    IEffectPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(IEffectPlugin):
    """插件入口 - 恐怖特效"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="horror_scary_effect",
            name="恐怖特效",
            version="1.0.0",
            description="恐怖场景的惊悚特效，增强恐怖氛围",
            author="ShortPlayAI",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.HORROR,
            file_path=__file__,
            tags=["恐怖", "惊悚", "诡异"]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        return True
    
    def shutdown(self) -> bool:
        return True
    
    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "恐怖特效",
            "icon": "👻",
            "params": [
                {
                    "name": "intensity",
                    "label": "强度",
                    "type": "slider",
                    "min": 0.0,
                    "max": 2.0,
                    "default": 1.0,
                    "description": "恐怖强度"
                },
                {
                    "name": "effect_type",
                    "label": "效果类型",
                    "type": "select",
                    "options": ["glitch", "distortion", "vignette", "noise"],
                    "default": "glitch",
                    "description": "恐怖效果类型"
                },
                {
                    "name": "color_tint",
                    "label": "色调",
                    "type": "color",
                    "default": "#2d0000",
                    "description": "恐怖色调"
                },
                {
                    "name": "flicker_speed",
                    "label": "闪烁速度",
                    "type": "slider",
                    "min": 1.0,
                    "max": 10.0,
                    "default": 5.0,
                    "description": "画面闪烁速度"
                }
            ]
        }
    
    def apply_effect(self, frame_data: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        """应用恐怖特效"""
        intensity = params.get('intensity', 1.0)
        effect_type = params.get('effect_type', 'glitch')
        color_tint = params.get('color_tint', '#2d0000')
        flicker_speed = params.get('flicker_speed', 5.0)
        
        height, width = frame_data.shape[:2]
        result = frame_data.copy().astype(np.float32)
        
        # 应用色调
        color_rgb = self._hex_to_rgb(color_tint)
        for i in range(3):
            result[:, :, i] = result[:, :, i] * (1.0 + 0.3 * intensity * (color_rgb[i] / 255.0 - 0.3))
        
        # 应用恐怖效果
        if effect_type == "glitch":
            result = self._apply_glitch_effect(result, intensity, flicker_speed)
        elif effect_type == "distortion":
            result = self._apply_distortion_effect(result, intensity)
        elif effect_type == "vignette":
            result = self._apply_vignette_effect(result, intensity)
        elif effect_type == "noise":
            result = self._apply_noise_effect(result, intensity)
        
        return np.clip(result, 0, 255).astype(np.uint8)
    
    def _hex_to_rgb(self, hex_color: str) -> tuple:
        """十六进制颜色转RGB"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def _apply_glitch_effect(self, frame: np.ndarray, intensity: float, speed: float) -> np.ndarray:
        """应用故障效果"""
        height, width, channels = frame.shape
        
        # 随机故障偏移
        offset_x = np.random.randint(-10, 11) * int(10 * intensity)
        offset_y = np.random.randint(-10, 11) * int(10 * intensity)
        
        # 应用故障偏移
        for c in range(channels):
            frame[:, :, c] = np.roll(frame[:, :, c], offset_x, axis=1)
            frame[:, :, c] = np.roll(frame[:, :, c], offset_y, axis=0)
        
        # 添加色彩故障
        if np.random.random() > 0.5:
            channel = np.random.randint(0, channels)
            frame[:, :, channel] = np.roll(frame[:, :, channel], np.random.randint(-20, 21), axis=1)
        
        return frame
    
    def _apply_distortion_effect(self, frame: np.ndarray, intensity: float) -> np.ndarray:
        """应用扭曲效果"""
        height, width = frame.shape[:2]
        
        # 创建扭曲映射
        y, x = np.ogrid[:height, :width]
        center_y, center_x = height // 2, width // 2
        
        # 波浪扭曲
        distortion_strength = 10 * intensity
        wave = np.sin(x * 0.05 * distortion_strength) * 5
        
        # 应用扭曲
        for c in range(frame.shape[2]):
            frame[:, :, c] = np.roll(frame[:, :, c], int(wave), axis=1)
        
        return frame
    
    def _apply_vignette_effect(self, frame: np.ndarray, intensity: float) -> np.ndarray:
        """应用暗角效果"""
        height, width = frame.shape[:2]
        
        # 创建暗角遮罩
        y, x = np.ogrid[:height, :width]
        center_y, center_x = height // 2, width // 2
        
        # 计算到中心的距离
        distance = np.sqrt((x - center_x)**2 + (y - center_y)**2)
        max_distance = np.sqrt(center_x**2 + center_y**2)
        
        # 创建暗角渐变
        vignette = 1.0 - (distance / max_distance) ** 2 * intensity
        
        # 应用暗角
        for c in range(frame.shape[2]):
            frame[:, :, c] = frame[:, :, c] * vignette
        
        return frame
    
    def _apply_noise_effect(self, frame: np.ndarray, intensity: float) -> np.ndarray:
        """应用噪点效果"""
        # 添加随机噪点
        noise = np.random.normal(0, 30 * intensity, frame.shape).astype(np.float32)
        
        # 应用噪点
        for c in range(frame.shape[2]):
            frame[:, :, c] = frame[:, :, c] + noise
        
        return frame
    
    def get_effect_params(self) -> Dict[str, Any]:
        return {
            "intensity": {
                "type": "float",
                "range": [0.0, 2.0],
                "default": 1.0,
                "description": "恐怖强度"
            },
            "effect_type": {
                "type": "select",
                "options": ["glitch", "distortion", "vignette", "noise"],
                "default": "glitch",
                "description": "恐怖效果类型"
            },
            "color_tint": {
                "type": "color",
                "default": "#2d0000",
                "description": "恐怖色调"
            },
            "flicker_speed": {
                "type": "float",
                "range": [1.0, 10.0],
                "default": 5.0,
                "description": "闪烁速度"
            }
        }