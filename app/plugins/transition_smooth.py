"""
平滑滑动转场插件
位移 + 交叉淡化的平滑滑动（smoothleft/right/up/down）
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    ITransitionPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(ITransitionPlugin):
    """插件入口 - 平滑滑动转场"""

    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="transition_smooth",
            name="平滑滑动",
            version="1.0.0",
            description="位移与交叉淡化结合的平滑滑动",
            author="ShortPlayAI",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["平滑", "滑动", "渐变", "通用"]
        )

    def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    def shutdown(self) -> bool:
        return True

    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "平滑滑动",
            "icon": "🌊",
            "params": [
                {"name": "duration", "type": "slider", "min": 0.1, "max": 3.0, "default": 1.0, "label": "持续时间", "description": "转场持续时间"},
                {"name": "direction", "type": "select", "options": ["left", "right", "up", "down"], "default": "left", "label": "滑动方向", "description": "滑动方向"},
                {"name": "easing", "type": "select", "options": ["linear", "ease-in", "ease-out", "ease-in-out"], "default": "ease-in-out", "label": "缓动函数", "description": "转场缓动方式"}
            ]
        }

    def apply_transition(self, from_frame: Any, to_frame: Any,
                        progress: float, params: Dict[str, Any]) -> Any:
        direction = params.get("direction", "left")
        easing = params.get("easing", "ease-in-out")
        eased = self._apply_easing(progress, easing)
        if isinstance(from_frame, np.ndarray) and isinstance(to_frame, np.ndarray):
            return self._smooth_transition(from_frame, to_frame, eased, direction)
        return to_frame if progress > 0.5 else from_frame

    def _smooth_transition(self, from_frame: np.ndarray, to_frame: np.ndarray,
                           progress: float, direction: str) -> np.ndarray:
        h, w = from_frame.shape[:2]
        a = np.zeros_like(from_frame)
        b = np.zeros_like(to_frame)
        if direction == "left":
            shift = int(progress * w)
            a[:, :w - shift] = from_frame[:, shift:]
            b[:, shift:] = to_frame[:, :w - shift]
        elif direction == "right":
            shift = int(progress * w)
            a[:, shift:] = from_frame[:, :w - shift]
            b[:, :w - shift] = to_frame[:, shift:]
        elif direction == "up":
            shift = int(progress * h)
            a[:h - shift, :] = from_frame[shift:, :]
            b[shift:, :] = to_frame[:h - shift, :]
        else:  # down
            shift = int(progress * h)
            a[shift:, :] = from_frame[:h - shift, :]
            b[:h - shift, :] = to_frame[shift:, :]
        blended = a.astype(np.float32) * (1 - progress) + b.astype(np.float32) * progress
        return blended.astype(np.uint8)

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
            "direction": {"type": "string", "default": "left", "description": "滑动方向"},
            "easing": {"type": "string", "default": "ease-in-out", "description": "转场缓动方式"}
        }
