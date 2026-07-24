"""溶解转场插件 - 像素随机渐进替换"""

import numpy as np


class Plugin:
    name = "溶解转场"
    version = "1.0.0"

    def apply(self, from_frame: np.ndarray, to_frame: np.ndarray, progress: float,
              grain: float = 0.05) -> np.ndarray:
        h, w = from_frame.shape[:2]
        np.random.seed(42)
        noise = np.random.rand(h, w) < progress
        result = from_frame.copy()
        if result.ndim == 3:
            result[noise] = to_frame[noise]
        else:
            result[noise] = to_frame[noise]
        return result
