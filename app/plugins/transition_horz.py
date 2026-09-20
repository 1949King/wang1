"""
水平开合转场插件
从中心垂直线向左右打开（horzopen）/ 左右两半向中间合拢（horzclose）
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    ITransitionPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(ITransitionPlugin):
    """插件入口 - 水平开合转场"""

    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="transition_horz",
            name="水平开合",
            version="1.0.0",
            description="画面从中心垂直线向左右打开或合拢",
            author="ShortPlayAI",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["水平", "开合", "门", "通用"]
        )

    def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    def shutdown(self) -> bool:
        return True

    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "水平开合",
            "icon": "↔️",
            "params": [
                {"name": "duration", "type": "slider", "min": 0.1, "max": 3.0, "default": 1.0, "label": "持续时间", "description": "转场持续时间"},
                {"name": "direction", "type": "select", "options": ["open", "close"], "default": "open", "label": "开合方式", "description": "打开 or 合拢"},
                {"name": "easing", "type": "select", "options": ["linear", "ease-in", "ease-out", "ease-in-out"], "default": "ease-in-out", "label": "缓动函数", "description": "转场缓动方式"}
            ]
        }

    def apply_transition(self, from_frame: Any, to_frame: Any,
                        progress: float, params: Dict[str, Any]) -> Any:
        direction = params.get("direction", "open")
        easing = params.get("easing", "ease-in-out")
        eased = self._apply_easing(progress, easing)
        if isinstance(from_frame, np.ndarray) and isinstance(to_frame, np.ndarray):
            return self._horz_transition(from_frame, to_frame, eased, direction)
        return to_frame if progress > 0.5 else from_frame

    def _horz_transition(self, from_frame: np.ndarray, to_frame: np.ndarray,
                         progress: float, mode: str) -> np.ndarray:
        h, w = from_frame.shape[:2]
        center = w / 2.0
        if mode == "close":
            band = (1.0 - progress) * center
        else:
            band = progress * center
        xx = np.arange(w, dtype=np.float32)
        mask = np.abs(xx - center) <= band
        mask3 = mask[None, :, None]
        return np.where(mask3, to_frame, from_frame).astype(np.uint8)

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
            "direction": {"type": "string", "default": "open", "description": "开合方式（open/close）"},
            "easing": {"type": "string", "default": "ease-in-out", "description": "转场缓动方式"}
        }
