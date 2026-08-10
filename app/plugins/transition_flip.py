"""翻转转场插件 - 3D翻转效果"""

import numpy as np


class Plugin:
    name = "翻转转场"
    version = "1.0.0"
    description = "画面翻转过渡"
    author = "官方"

    def initialize(self, context=None):
        return True

    def run(self, *args, **kwargs):
        return True


    def apply(self, from_frame: np.ndarray, to_frame: np.ndarray, progress: float,
              direction: str = "horizontal") -> np.ndarray:
        import cv2
        h, w = from_frame.shape[:2]
        if progress < 0.5:
            factor = 1.0 - 2 * progress
            src = from_frame
        else:
            factor = 2 * progress - 1.0
            src = to_frame
        new_w = max(1, int(w * abs(factor)))
        if new_w < 2:
            return to_frame if progress > 0.5 else from_frame
        resized = cv2.resize(src, (new_w, h), interpolation=cv2.INTER_AREA)
        if factor > 0:
            resized = cv2.flip(resized, 1)
        x_offset = (w - new_w) // 2
        result = np.zeros_like(from_frame)
        x1, x2 = x_offset, x_offset + new_w
        result[:, x1:x2] = resized
        return result
