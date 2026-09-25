"""
径向擦除转场插件（时钟擦除）
ffmpeg n9.0 vf_xfade.c radial 同款数学（已用本机 ffmpeg 金标准渲染逐帧验证 ≤4 LSB）：
  smooth = atan2(x - w//2, y - h//2) - (q - 0.5) * 2.5π      （q = 1 - P，w//2 整除）
  权重  = smoothstep(0, 1, smooth)  （B 占比 = 权重）
  out   = B*权重 + A*(1-权重)，float 截断为 uint8
效果：B 从 12 点方向起沿顺时针扇形揭示（P≈0.23 起现，带 smoothstep 抗锯齿过渡带）。
导出映射 xfade=radial（exact：预览双帧混合与导出逐像素对齐，默认线性缓动）。
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    ITransitionPlugin, PluginInfo, PluginType, PluginCategory
)


class Plugin(ITransitionPlugin):
    """插件入口 - 径向擦除"""

    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="transition_radial",
            name="径向擦除",
            version="1.0.0",
            description="时钟式扇形揭示（导出 xfade=radial，exact，金标准验证）",
            author="ShortPlayAI",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["径向", "时钟", "扇形", "通用"]
        )

    def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    def shutdown(self) -> bool:
        return True

    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "径向擦除",
            "icon": "🕐",
            "params": [
                {"name": "duration", "type": "slider", "min": 0.1, "max": 3.0, "default": 0.8, "label": "持续时间", "description": "转场持续时间"},
                {"name": "easing", "type": "select", "options": ["linear", "ease-in", "ease-out", "ease-in-out"], "default": "linear", "label": "缓动函数", "description": "默认线性，与导出 xfade 严格对齐"}
            ]
        }

    def apply_transition(self, from_frame: Any, to_frame: Any,
                        progress: float, params: Dict[str, Any]) -> Any:
        easing = (params or {}).get("easing", "linear")
        eased = self._apply_easing(progress, easing)
        if isinstance(from_frame, np.ndarray) and isinstance(to_frame, np.ndarray):
            h, w = from_frame.shape[:2]
            q = 1.0 - eased
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            smooth = np.arctan2(xx - (w // 2), yy - (h // 2)) - (q - 0.5) * (np.pi * 2.5)
            t = np.clip(smooth, 0.0, 1.0)               # smoothstep(0,1,·) 的 clip
            s = t * t * (3.0 - 2.0 * t)
            out = to_frame.astype(np.float32) * s[:, :, None] + \
                  from_frame.astype(np.float32) * (1.0 - s[:, :, None])
            return np.clip(out, 0, 255).astype(np.uint8)  # C 截断对齐
        return to_frame if progress > 0.5 else from_frame

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
            "duration": {"type": "float", "min": 0.1, "max": 3.0, "default": 0.8, "description": "转场持续时间"},
            "easing": {"type": "string", "default": "linear", "description": "缓动方式（默认线性，对齐 xfade）"}
        }
