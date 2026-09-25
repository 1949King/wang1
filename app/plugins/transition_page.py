"""
翻页转场插件
to 画面像书页一样从一侧翻入，翻页脊线附近在 from 画面上投出卷曲阴影。
ffmpeg xfade 无 pagecurl 对应项：导出走插件帧烘焙（bake），
烘焙失败回退近似 xfade=coverleft/coverright（见 transition_plugin_registry._EXPORT_FIDELITY）。
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    ITransitionPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(ITransitionPlugin):
    """插件入口 - 翻页"""

    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="transition_page",
            name="翻页",
            version="1.0.0",
            description="书页式翻入，带卷曲阴影（导出烘焙，失败回退 cover 近似）",
            author="ShortPlayAI",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["翻页", "书页", "卷曲", "通用"]
        )

    def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    def shutdown(self) -> bool:
        return True

    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "翻页",
            "icon": "📖",
            "params": [
                {"name": "duration", "type": "slider", "min": 0.1, "max": 3.0, "default": 0.9, "label": "持续时间", "description": "转场持续时间"},
                {"name": "direction", "type": "select", "options": ["left", "right"], "default": "left", "label": "翻页方向", "description": "left：页面向左翻（to 从右来）"},
                {"name": "easing", "type": "select", "options": ["linear", "ease-in", "ease-out", "ease-in-out"], "default": "ease-in-out", "label": "缓动函数", "description": "翻页手感，默认缓入缓出"}
            ]
        }

    def apply_transition(self, from_frame: Any, to_frame: Any,
                        progress: float, params: Dict[str, Any]) -> Any:
        direction = str((params or {}).get("direction", "left")).lower()
        easing = (params or {}).get("easing", "ease-in-out")
        eased = self._apply_easing(progress, easing)
        if isinstance(from_frame, np.ndarray) and isinstance(to_frame, np.ndarray):
            return self._page_transition(from_frame, to_frame, eased, direction)
        return to_frame if progress > 0.5 else from_frame

    def _page_transition(self, from_frame: np.ndarray, to_frame: np.ndarray,
                         progress: float, direction: str) -> np.ndarray:
        h, w = from_frame.shape[:2]
        if progress <= 0.0:
            return from_frame.copy()
        if progress >= 1.0:
            return to_frame.copy()
        # 脊线位置：direction=left 时 to 从右侧翻入，脊线 x_e 由 w 走到 0
        xs = np.arange(w, dtype=np.float32)[None, :]
        if direction == "right":
            edge = progress * w          # to 从左侧翻入：x < edge 为 to
            reveal = xs < edge
            dist = xs - edge             # from 侧（x >= edge）到脊线距离（>0）
        else:
            edge = (1.0 - progress) * w  # to 从右侧翻入：x >= edge 为 to
            reveal = xs >= edge
            dist = edge - xs             # from 侧（x < edge）到脊线距离（>0）
        band = max(8.0, w * 0.12)
        # 卷曲阴影：脊线附近 band 内 from 画面线性压暗（最暗 0.45）
        shade = np.clip(1.0 - 0.55 * (1.0 - dist / band), 0.45, 1.0)
        shade = np.where((dist > 0) & (dist < band), shade, 1.0).astype(np.float32)
        out = from_frame.astype(np.float32) * shade[:, :, None]
        out = np.where(reveal[:, :, None], to_frame.astype(np.float32), out)
        return np.clip(np.rint(out), 0, 255).astype(np.uint8)

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
            "duration": {"type": "float", "min": 0.1, "max": 3.0, "default": 0.9, "description": "转场持续时间"},
            "direction": {"type": "string", "default": "left", "description": "翻页方向（left/right）"},
            "easing": {"type": "string", "default": "ease-in-out", "description": "缓动方式"}
        }
