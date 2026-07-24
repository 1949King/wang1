"""
动作特效插件
动作场景的动感特效
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    IEffectPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(IEffectPlugin):
    """插件入口 - 动作特效"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="action_dynamic_effect",
            name="动作特效",
            version="1.0.0",
            description="动作场景的动感特效，增强视觉冲击力",
            author="ShortPlayAI",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.ACTION,
            file_path=__file__,
            tags=["动作", "动感", "冲击力"]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        return True
    
    def shutdown(self) -> bool:
        return True
    
    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "动作特效",
            "icon": "💥",
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
                    "name": "motion_blur",
                    "label": "动态模糊",
                    "type": "slider",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.3,
                    "description": "动态模糊程度"
                },
                {
                    "name": "speed_lines",
                    "label": "速度线",
                    "type": "checkbox",
                    "default": True,
                    "description": "显示速度线"
                },
                {
                    "name": "color_boost",
                    "label": "色彩增强",
                    "type": "slider",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.5,
                    "description": "色彩增强程度"
                }
            ]
        }
    
    def apply_effect(self, frame_data: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        """应用动作特效"""
        intensity = params.get('intensity', 1.0)
        motion_blur = params.get('motion_blur', 0.3)
        speed_lines = params.get('speed_lines', True)
        color_boost = params.get('color_boost', 0.5)
        
        height, width = frame_data.shape[:2]
        result = frame_data.copy().astype(np.float32)
        
        # 应用色彩增强
        if color_boost > 0:
            result = result * (1.0 + color_boost * 0.5)
            result = np.clip(result, 0, 255)
        
        # 应用动态模糊（模拟运动）
        if motion_blur > 0:
            kernel_size = int(5 + motion_blur * 10)
            if kernel_size % 2 == 0:
                kernel_size += 1
            
            # 创建运动模糊核
            kernel = np.zeros((kernel_size, kernel_size))
            for i in range(kernel_size):
                for j in range(kernel_size):
                    if i == j:
                        kernel[i, j] = 1.0
                    else:
                        kernel[i, j] = motion_blur / (abs(i - j) + 1)
            
            kernel = kernel / kernel.sum()
            
            # 应用模糊
            for c in range(3):
                result[:, :, c] = self._apply_convolution(result[:, :, c], kernel)
        
        # 添加速度线效果
        if speed_lines:
            result = self._add_speed_lines(result, intensity)
        
        return result.astype(np.uint8)
    
    def _apply_convolution(self, image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        """应用卷积"""
        from scipy import ndimage
        return ndimage.convolve(image, kernel, mode='reflect')
    
    def _add_speed_lines(self, frame: np.ndarray, intensity: float) -> np.ndarray:
        """添加速度线"""
        height, width = frame.shape[:2]
        
        # 创建速度线
        num_lines = int(10 + intensity * 20)
        for _ in range(num_lines):
            # 随机选择起点和方向
            start_y = np.random.randint(0, height)
            start_x = np.random.randint(0, width)
            length = np.random.randint(20, 100)
            angle = np.random.uniform(0, 2 * np.pi)
            
            # 计算终点
            end_y = int(start_y + length * np.sin(angle))
            end_x = int(start_x + length * np.cos(angle))
            
            # 绘制线条
            y_coords = np.linspace(start_y, end_y, 100, dtype=int)
            x_coords = np.linspace(start_x, end_x, 100, dtype=int)
            
            # 边界检查
            valid_mask = (y_coords >= 0) & (y_coords < height) & (x_coords >= 0) & (x_coords < width)
            y_coords = y_coords[valid_mask]
            x_coords = x_coords[valid_mask]
            
            if len(y_coords) > 1:
                # 绘制白色线条
                for i in range(len(y_coords) - 1):
                    y1, y2 = y_coords[i], y_coords[i + 1]
                    x1, x2 = x_coords[i], x_coords[i + 1]
                    
                    # 使用Bresenham算法绘制线条
                    points = self._bresenham_line(x1, y1, x2, y2)
                    for px, py in points:
                        if 0 <= py < height and 0 <= px < width:
                            # 添加发光效果
                            for dy in range(-2, 3):
                                for dx in range(-2, 3):
                                    ny, nx = py + dy, px + dx
                                    if 0 <= ny < height and 0 <= nx < width:
                                        frame[ny, nx, :] = np.minimum(
                                            frame[ny, nx, :] + np.array([255, 255, 255]) * intensity * 0.5,
                                            255
                                        )
        
        return frame
    
    def _bresenham_line(self, x0: int, y0: int, x1: int, y1: int):
        """Bresenham直线算法"""
        points = []
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        
        if dx > dy:
            err = dx // 2
            while x0 != x1:
                points.append((x0, y0))
                err -= dy
                if err < 0:
                    err += dx
                    y0 += sy
                else:
                    x0 += sx
        else:
            err = dy // 2
            while y0 != y1:
                points.append((x0, y0))
                err -= dx
                if err < 0:
                    err += dy
                    x0 += sx
                else:
                    y0 += sy
        
        points.append((x1, y1))
        return points
    
    def get_effect_params(self) -> Dict[str, Any]:
        return {
            "intensity": {
                "type": "float",
                "range": [0.0, 2.0],
                "default": 1.0,
                "description": "特效强度"
            },
            "motion_blur": {
                "type": "float",
                "range": [0.0, 1.0],
                "default": 0.3,
                "description": "动态模糊程度"
            },
            "speed_lines": {
                "type": "boolean",
                "default": True,
                "description": "显示速度线"
            },
            "color_boost": {
                "type": "float",
                "range": [0.0, 1.0],
                "default": 0.5,
                "description": "色彩增强程度"
            }
        }