"""
喜剧特效插件
喜剧场景的趣味特效
"""

import numpy as np
from typing import Dict, Any

from app.core.plugin_loader import (
    IEffectPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(IEffectPlugin):
    """插件入口 - 喜剧特效"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="comedy_fun_effect",
            name="喜剧特效",
            version="1.0.0",
            description="喜剧场景的趣味特效，增强幽默氛围",
            author="ShortPlayAI",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.COMEDY,
            file_path=__file__,
            tags=["喜剧", "趣味", "幽默"]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        return True
    
    def shutdown(self) -> bool:
        return True
    
    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "喜剧特效",
            "icon": "😄",
            "params": [
                {
                    "name": "intensity",
                    "label": "强度",
                    "type": "slider",
                    "min": 0.0,
                    "max": 2.0,
                    "default": 1.0,
                    "description": "特效强度"
                },
                {
                    "name": "effect_type",
                    "label": "效果类型",
                    "type": "select",
                    "options": ["bounce", "shake", "zoom", "rotate"],
                    "default": "bounce",
                    "description": "喜剧效果类型"
                },
                {
                    "name": "speed",
                    "label": "速度",
                    "type": "slider",
                    "min": 0.5,
                    "max": 3.0,
                    "default": 1.5,
                    "description": "动画速度"
                }
            ]
        }
    
    def apply_effect(self, frame_data: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        """应用喜剧特效"""
        intensity = params.get('intensity', 1.0)
        effect_type = params.get('effect_type', 'bounce')
        speed = params.get('speed', 1.5)
        
        height, width = frame_data.shape[:2]
        result = frame_data.copy()
        
        if effect_type == "bounce":
            result = self._apply_bounce_effect(result, intensity, speed)
        elif effect_type == "shake":
            result = self._apply_shake_effect(result, intensity, speed)
        elif effect_type == "zoom":
            result = self._apply_zoom_effect(result, intensity, speed)
        elif effect_type == "rotate":
            result = self._apply_rotate_effect(result, intensity, speed)
        
        return result.astype(np.uint8)
    
    def _apply_bounce_effect(self, frame: np.ndarray, intensity: float, speed: float) -> np.ndarray:
        """应用弹跳效果"""
        height, width = frame.shape[:2]
        
        # 创建弹跳变形
        y, x = np.ogrid[:height, :width]
        center_y, center_x = height // 2, width // 2
        
        # 弹跳强度
        bounce_strength = int(20 * intensity)
        
        # 应用弹跳变形
        distance = np.sqrt((x - center_x)**2 + (y - center_y)**2)
        max_distance = np.sqrt(center_x**2 + center_y**2)
        normalized_distance = distance / max_distance
        
        # 创建弹跳偏移
        bounce_offset = np.sin(normalized_distance * np.pi * 2) * bounce_strength
        
        # 应用弹跳效果
        for i in range(3):
            frame[:, :, i] = np.roll(frame[:, :, i], int(bounce_offset), axis=0)
            frame[:, :, i] = np.roll(frame[:, :, i], int(bounce_offset), axis=1)
        
        return frame
    
    def _apply_shake_effect(self, frame: np.ndarray, intensity: float, speed: float) -> np.ndarray:
        """应用震动效果"""
        shake_amount = int(5 * intensity)
        
        for i in range(3):
            # 随机震动
            offset_y = np.random.randint(-shake_amount, shake_amount + 1)
            offset_x = np.random.randint(-shake_amount, shake_amount + 1)
            
            # 应用震动
            frame[:, :, i] = np.roll(frame[:, :, i], offset_y, axis=0)
            frame[:, :, i] = np.roll(frame[:, :, i], offset_x, axis=1)
        
        return frame
    
    def _apply_zoom_effect(self, frame: np.ndarray, intensity: float, speed: float) -> np.ndarray:
        """应用缩放效果"""
        height, width = frame.shape[:2]
        center_y, center_x = height // 2, width // 2
        
        # 创建缩放效果
        zoom_factor = 1.0 + (0.1 * intensity * np.sin(speed * 0.1))
        
        # 使用numpy实现缩放
        y, x = np.ogrid[:height, :width]
        
        # 计算新的坐标
        new_y = (y - center_y) * zoom_factor + center_y
        new_x = (x - center_x) * zoom_factor + center_x
        
        # 四舍五入到整数
        new_y = np.round(new_y).astype(int)
        new_x = np.round(new_x).astype(int)
        
        # 边界检查
        valid_mask = (new_y >= 0) & (new_y < height) & (new_x >= 0) & (new_x < width)
        
        # 应用缩放
        for i in range(3):
            frame[:, :, i] = frame[new_y[valid_mask], new_x[valid_mask], i]
        
        return frame
    
    def _apply_rotate_effect(self, frame: np.ndarray, intensity: float, speed: float) -> np.ndarray:
        """应用旋转效果"""
        height, width = frame.shape[:2]
        center_y, center_x = height // 2, width // 2
        
        # 旋转角度
        angle = int(5 * intensity * np.sin(speed * 0.1))
        
        # 创建旋转矩阵
        theta = np.radians(angle)
        c, s = np.cos(theta), np.sin(theta)
        rotation_matrix = np.array([[c, -s], [s, c]])
        
        # 应用旋转
        for i in range(3):
            channel = frame[:, :, i]
            
            # 旋转图像
            y, x = np.ogrid[:height, :width]
            y_centered = y - center_y
            x_centered = x - center_x
            
            # 应用旋转
            y_rot = c * y_centered - s * x_centered + center_y
            x_rot = s * y_centered + c * x_centered + center_x
            
            # 四舍五入
            y_rot = np.round(y_rot).astype(int)
            x_rot = np.round(x_rot).astype(int)
            
            # 边界检查
            valid_mask = (y_rot >= 0) & (y_rot < height) & (x_rot >= 0) & (x_rot < width)
            
            # 应用旋转
            frame[:, :, i] = frame[y_rot[valid_mask], x_rot[valid_mask], i]
        
        return frame
    
    def get_effect_params(self) -> Dict[str, Any]:
        return {
            "intensity": {
                "type": "float",
                "range": [0.0, 2.0],
                "default": 1.0,
                "description": "特效强度"
            },
            "effect_type": {
                "type": "select",
                "options": ["bounce", "shake", "zoom", "rotate"],
                "default": "bounce",
                "description": "喜剧效果类型"
            },
            "speed": {
                "type": "float",
                "range": [0.5, 3.0],
                "default": 1.5,
                "description": "动画速度"
            }
        }