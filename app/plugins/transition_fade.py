"""
淡入淡出转场插件
经典的淡入淡出转场效果
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    ITransitionPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(ITransitionPlugin):
    """插件入口 - 淡入淡出转场"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="transition_fade",
            name="淡入淡出",
            version="1.0.0",
            description="经典的淡入淡出转场效果",
            author="ShortPlayAI",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["淡入淡出", "经典", "通用"]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        return True
    
    def shutdown(self) -> bool:
        return True
    
    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "淡入淡出",
            "icon": "🌅",
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
        """应用淡入淡出转场"""
        easing = params.get("easing", "ease-in-out")
        
        eased_progress = self._apply_easing(progress, easing)
        
        if isinstance(from_frame, np.ndarray) and isinstance(to_frame, np.ndarray):
            return self._fade_transition(from_frame, to_frame, eased_progress)
        
        return to_frame if progress > 0.5 else from_frame
    
    def _fade_transition(self, from_frame: np.ndarray, 
                         to_frame: np.ndarray, progress: float) -> np.ndarray:
        """淡入淡出转场"""
        return (from_frame * (1 - progress) + to_frame * progress).astype(np.uint8)
    
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
            "easing": {
                "type": "string",
                "default": "ease-in-out",
                "description": "转场缓动方式"
            }
        }
