"""
滑动转场插件
平滑的滑动转场效果
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    ITransitionPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(ITransitionPlugin):
    """插件入口 - 滑动转场"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="transition_slide",
            name="滑动转场",
            version="1.0.0",
            description="平滑的滑动转场效果",
            author="ShortPlayAI",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["滑动", "平滑", "通用"]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        return True
    
    def shutdown(self) -> bool:
        return True
    
    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "滑动转场",
            "icon": "➡️",
            "params": [
                {
                    "name": "duration",
                    "type": "slider",
                    "min": 0.1,
                    "max": 3.0,
                    "default": 1.0,
                    "label": "持续时间",
                    "description": "转场持续时间"
                },
                {
                    "name": "direction",
                    "type": "select",
                    "options": ["left", "right", "up", "down"],
                    "default": "left",
                    "label": "滑动方向",
                    "description": "滑动方向"
                },
                {
                    "name": "easing",
                    "type": "select",
                    "options": ["linear", "ease-in", "ease-out", "ease-in-out"],
                    "default": "ease-in-out",
                    "label": "缓动函数",
                    "description": "转场缓动方式"
                }
            ]
        }
    
    def apply_transition(self, from_frame: Any, to_frame: Any,
                        progress: float, params: Dict[str, Any]) -> Any:
        """应用滑动转场"""
        direction = params.get("direction", "left")
        easing = params.get("easing", "ease-in-out")
        
        eased_progress = self._apply_easing(progress, easing)
        
        if isinstance(from_frame, np.ndarray) and isinstance(to_frame, np.ndarray):
            return self._slide_transition(from_frame, to_frame, eased_progress, direction)
        
        return to_frame if progress > 0.5 else from_frame
    
    def _slide_transition(self, from_frame: np.ndarray, to_frame: np.ndarray,
                         progress: float, direction: str) -> np.ndarray:
        """滑动转场"""
        height, width = from_frame.shape[:2]
        offset = int(progress * width)
        
        result = np.zeros_like(from_frame)
        
        if direction == "left":
            result[:, :offset] = to_frame[:, :offset]
            result[:, offset:] = from_frame[:, offset:]
        elif direction == "right":
            result[:, :width-offset] = from_frame[:, :width-offset]
            result[:, width-offset:] = to_frame[:, width-offset:]
        elif direction == "up":
            result[:offset, :] = to_frame[:offset, :]
            result[offset:, :] = from_frame[offset:, :]
        elif direction == "down":
            result[:height-offset, :] = from_frame[:height-offset, :]
            result[height-offset:, :] = to_frame[height-offset:, :]
        
        return result
    
    def _apply_easing(self, progress: float, easing: str) -> float:
        """应用缓动函数"""
        if easing == "linear":
            return progress
        elif easing == "ease-in":
            return progress * progress
        elif easing == "ease-out":
            return progress * (2 - progress)
        elif easing == "ease-in-out":
            return progress * progress * (3 - 2 * progress)
        return progress
    
    def get_transition_params(self) -> Dict[str, Any]:
        return {
            "duration": {
                "type": "float",
                "min": 0.1,
                "max": 3.0,
                "default": 1.0,
                "description": "转场持续时间"
            },
            "direction": {
                "type": "string",
                "default": "left",
                "description": "滑动方向"
            },
            "easing": {
                "type": "string",
                "default": "ease-in-out",
                "description": "转场缓动方式"
            }
        }
