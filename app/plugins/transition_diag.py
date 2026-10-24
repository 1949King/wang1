"""
对角擦除转场插件
ffmpeg n9.0 vf_xfade.c diag* 同款数学（已用本机 ffmpeg 金标准渲染逐帧验证 ≤4 LSB）：
  smooth = 1 + (u/w)·(v/h) - 2q        （q = 1 - P，u/v 为「距起始角对侧」的像素坐标）
  权重  = smoothstep(0, 1, smooth)     （B 占比 = 权重，软渐变对角带）
  out   = B*权重 + A*(1-权重)，float 截断为 uint8
direction 为「B 揭示起始角」：tl 左上 / tr 右上 / bl 左下 / br 右下。
注意 ffmpeg 命名与起始角相反（diagtl 的 B 来自右下），映射见
transition_plugin_registry._DIAG_XFADE。
导出按 direction 映射对应 xfade（exact：预览与导出逐像素对齐，默认线性缓动）。
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    ITransitionPlugin, PluginInfo, PluginType, PluginCategory
)

_DIRECTIONS = ("tl", "tr", "bl", "br")


class Plugin(ITransitionPlugin):
    """插件入口 - 对角擦除"""

    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="transition_diag",
            name="对角擦除",
            version="1.0.0",
            description="软渐变对角揭示（导出 xfade=diag*，exact，金标准验证）",
            author="ShortPlayAI",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["对角", "擦除", "斜线", "通用"]
        )

    def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    def shutdown(self) -> bool:
        return True

    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "对角擦除",
            "icon": "◢",
            "params": [
                {"name": "duration", "type": "slider", "min": 0.1, "max": 3.0, "default": 0.8, "label": "持续时间", "description": "转场持续时间"},
                {"name": "direction", "type": "select", "options": list(_DIRECTIONS), "default": "tl", "label": "揭示起始角", "description": "tl 左上 / tr 右上 / bl 左下 / br 右下"},
                {"name": "easing", "type": "select", "options": ["linear", "ease-in", "ease-out", "ease-in-out"], "default": "linear", "label": "缓动函数", "description": "默认线性，与导出 xfade 严格对齐"}
            ]
        }

    def apply_transition(self, from_frame: Any, to_frame: Any,
                        progress: float, params: Dict[str, Any]) -> Any:
        direction = str((params or {}).get("direction", "tl")).lower()
        easing = (params or {}).get("easing", "linear")
        eased = self._apply_easing(progress, easing)
        if isinstance(from_frame, np.ndarray) and isinstance(to_frame, np.ndarray):
            h, w = from_frame.shape[:2]
            q = 1.0 - eased
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            # ffmpeg diag* 公式里的坐标均从「起始角的对侧」量起，且用 w/h（非 w-1）
            if direction == "tl":      # = ffmpeg diagbr
                smooth = 1.0 + ((w - 1 - xx) / w) * ((h - 1 - yy) / h) - 2.0 * q
            elif direction == "tr":    # = ffmpeg diagbl
                smooth = 1.0 + (xx / w) * ((h - 1 - yy) / h) - 2.0 * q
            elif direction == "bl":    # = ffmpeg diagtr
                smooth = 1.0 + ((w - 1 - xx) / w) * (yy / h) - 2.0 * q
            else:                      # br = ffmpeg diagtl
                smooth = 1.0 + (xx / w) * (yy / h) - 2.0 * q
            t = np.clip(smooth, 0.0, 1.0)
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
            "direction": {"type": "string", "default": "tl", "description": "B 揭示起始角（tl/tr/bl/br）"},
            "easing": {"type": "string", "default": "linear", "description": "缓动方式（默认线性，对齐 xfade）"}
        }
