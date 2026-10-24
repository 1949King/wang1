"""旋转转场插件 - 旋转退出/进入"""

import numpy as np


class Plugin:
    name = "旋转转场"
    version = "1.0.0"
    description = "旋转过渡"
    author = "官方"

    def initialize(self, context=None):
        return True

    def run(self, *args, **kwargs):
        return True


    def apply(self, from_frame: np.ndarray, to_frame: np.ndarray, progress: float) -> np.ndarray:
        import cv2
        h, w = from_frame.shape[:2]
        if progress < 0.5:
            angle = progress * 2 * 90
            src = from_frame
        else:
            angle = (progress - 0.5) * 2 * 90 - 90
            src = to_frame
        center = (w // 2, h // 2)
        mat = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(src, mat, (w, h), borderMode=cv2.BORDER_CONSTANT,
                                 borderValue=(0, 0, 0))
        return rotated
