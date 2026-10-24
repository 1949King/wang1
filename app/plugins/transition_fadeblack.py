"""
黑场过渡转场插件
A 经黑场两段式过渡到 B（ffmpeg n9.0 vf_xfade.c fadeblack 同款数学：
phase=0.2 的 smoothstep 双相混合，mix(a,b,m)=a*m+b*(1-m)，进度取 q=1-P）。
本机 ffmpeg 9.0(gyan) 的 fadeblack 曲线与 n9.0 源码存在版本漂移（实测偏差 >10 LSB），
为保证「预览=导出」，导出走插件帧烘焙（bake），烘焙失败回退 xfade=fadeblack 近似。
"""

import numpy as np
from typing import Dict, Any

from core.plugin_loader import (
    ITransitionPlugin, PluginInfo, PluginType, PluginCategory
)

_PHASE = 0.2


def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


class Plugin(ITransitionPlugin):
    """插件入口 - 黑场过渡"""

    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="transition_fadeblack",
            name="黑场过渡",
            version="1.0.0",
            description="经黑场两段式过渡（导出烘焙，预览=导出）",
            author="ShortPlayAI",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["黑场", "淡入淡出", "电影", "通用"]
        )

    def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    def shutdown(self) -> bool:
        return True

    def get_ui_config(self) -> Dict[str, Any]:
        return {
            "name": "黑场过渡",
            "icon": "⬛",
            "params": [
                {"name": "duration", "type": "slider", "min": 0.1, "max": 3.0, "default": 0.8, "label": "持续时间", "description": "转场持续时间"},
                {"name": "easing", "type": "select", "options": ["linear", "ease-in", "ease-out", "ease-in-out"], "default": "linear", "label": "缓动函数", "description": "默认线性"}
            ]
        }

    def apply_transition(self, from_frame: Any, to_frame: Any,
                        progress: float, params: Dict[str, Any]) -> Any:
        easing = (params or {}).get("easing", "linear")
        eased = self._apply_easing(progress, easing)
        if isinstance(from_frame, np.ndarray) and isinstance(to_frame, np.ndarray):
            q = 1.0 - eased  # ffmpeg 进度反向：q=1 在转场起点
            a = from_frame.astype(np.float32)
            b = to_frame.astype(np.float32)
            ss_a = _smoothstep(1.0 - _PHASE, 1.0, q)   # A→黑 权重
            ss_b = _smoothstep(_PHASE, 1.0, q)         # 黑→B 权重
            m1 = a * ss_a                                # mix(xf0, bg=0, ss_a)
            m2 = b * (1.0 - ss_b)                        # mix(bg=0, xf1, ss_b)
            out = m1 * q + m2 * (1.0 - q)                # mix(m1, m2, q)
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
            "easing": {"type": "string", "default": "linear", "description": "缓动方式"}
        }
