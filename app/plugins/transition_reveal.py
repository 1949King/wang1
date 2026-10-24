"""
揭示转场插件
from 画面向指定方向移出，露出 to 画面（revealleft/right/up/down）
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    ITransitionPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(ITransitionPlugin):
    """插件入口 - 揭示转场"""

    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="transition_reveal",
            name="揭示转场",
            version="1.0.0",
            description="from 画面移出，揭示后面的 to",
            author="ShortPlayAI",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["揭示", "移出", "方向", "通用"]
        )

    def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    def shutdown(self) -> bool:
        return True

    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "揭示转场",
            "icon": "👀",
            "params": [
                {"name": "duration", "type": "slider", "min": 0.1, "max": 3.0, "default": 1.0, "label": "持续时间", "description": "转场持续时间"},
                {"name": "direction", "type": "select", "options": ["left", "right", "up", "down"], "default": "left", "label": "揭示方向", "description": "from 移出方向"},
                {"name": "easing", "type": "select", "options": ["linear", "ease-in", "ease-out", "ease-in-out"], "default": "ease-in-out", "label": "缓动函数", "description": "转场缓动方式"}
            ]
        }

    def apply_transition(self, from_frame: Any, to_frame: Any,
                        progress: float, params: Dict[str, Any]) -> Any:
        direction = params.get("direction", "left")
        easing = params.get("easing", "ease-in-out")
        eased = self._apply_easing(progress, easing)
        if isinstance(from_frame, np.ndarray) and isinstance(to_frame, np.ndarray):
            return self._reveal_transition(from_frame, to_frame, eased, direction)
        return to_frame if progress > 0.5 else from_frame

    def _reveal_transition(self, from_frame: np.ndarray, to_frame: np.ndarray,
                           progress: float, direction: str) -> np.ndarray:
        h, w = from_frame.shape[:2]
        result = to_frame.copy()
        off_w = int(progress * w)
        off_h = int(progress * h)
        if direction == "left":
            result[:, :w - off_w] = from_frame[:, off_w:]
        elif direction == "right":
            result[:, off_w:] = from_frame[:, :w - off_w]
        elif direction == "up":
            result[:h - off_h, :] = from_frame[off_h:, :]
        elif direction == "down":
            result[off_h:, :] = from_frame[:h - off_h, :]
        return result

    def _apply_easing(self, progress: float, easing: str) -> float:
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
            "duration": {"type": "float", "min": 0.1, "max": 3.0, "default": 1.0, "description": "转场持续时间"},
            "direction": {"type": "string", "default": "left", "description": "揭示方向"},
            "easing": {"type": "string", "default": "ease-in-out", "description": "转场缓动方式"}
        }
