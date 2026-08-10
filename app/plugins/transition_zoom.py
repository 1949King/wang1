"""缩放转场插件 - 从中心放大/缩小过渡"""

import numpy as np


class Plugin:
    name = "缩放转场"
    version = "1.0.0"
    description = "从中心放大/缩小过渡"
    author = "官方"

    def initialize(self, context=None):
        return True

    def run(self, *args, **kwargs):
        return True


    def apply(self, from_frame: np.ndarray, to_frame: np.ndarray, progress: float,
              direction: str = "in") -> np.ndarray:
        """应用缩放转场效果"""
        h, w = from_frame.shape[:2]
        if direction == "in":
            scale = 1.0 - progress
        else:
            scale = progress
        if scale < 0.01:
            return to_frame
        import cv2
        scaled = cv2.resize(from_frame, (int(w * scale), int(h * scale)))
        sh, sw = scaled.shape[:2]
        result = to_frame.copy()
        y1, x1 = (h - sh) // 2, (w - sw) // 2
        result[y1:y1 + sh, x1:x1 + sw] = scaled
        return result
