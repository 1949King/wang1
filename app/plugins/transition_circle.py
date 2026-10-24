"""
圆形开合转场插件
圆形从中心展开（circleopen）/ 向中心收缩（circleclose）
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    ITransitionPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(ITransitionPlugin):
    """插件入口 - 圆形开合转场"""

    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="transition_circle",
            name="圆形开合",
            version="1.0.0",
            description="圆形从中心展开或向中心收缩",
            author="ShortPlayAI",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["圆形", "开合", "圈", "通用"]
        )

    def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    def shutdown(self) -> bool:
        return True

    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "圆形开合",
            "icon": "⭕",
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
                    "options": ["open", "close"],
                    "default": "open",
                    "label": "开合方式",
                    "description": "展开 or 收缩"
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
        direction = params.get("direction", "open")
        easing = params.get("easing", "ease-in-out")
        eased = self._apply_easing(progress, easing)
        if isinstance(from_frame, np.ndarray) and isinstance(to_frame, np.ndarray):
            return self._circle_transition(from_frame, to_frame, eased, direction)
        return to_frame if progress > 0.5 else from_frame

    def _circle_transition(self, from_frame: np.ndarray, to_frame: np.ndarray,
                           progress: float, mode: str) -> np.ndarray:
        h, w = from_frame.shape[:2]
        cy, cx = h / 2.0, w / 2.0
        max_r = float(np.hypot(cx, cy))
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        if mode == "close":
            r = (1.0 - progress) * max_r
            mask = dist > r  # 圆外为 to（from 收缩）
        else:
            r = progress * max_r
            mask = dist <= r  # 圆内为 to（from 展开）
        mask3 = mask[:, :, None]
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
