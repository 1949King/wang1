"""故障转场插件 - RGB通道偏移+块位移"""

import numpy as np


class Plugin:
    name = "故障转场"
    version = "1.0.0"
    description = "故障抖动过渡"
    author = "官方"

    def initialize(self, context=None):
        return True

    def run(self, *args, **kwargs):
        return True


    def apply(self, from_frame: np.ndarray, to_frame: np.ndarray, progress: float) -> np.ndarray:
        h, w = from_frame.shape[:2]
        intensity = min(1.0, progress * 1.5)
        if intensity < 0.05:
            return from_frame
        result = to_frame.copy() if progress > 0.5 else from_frame.copy()
        if result.ndim == 3:
            shift_r = int(20 * intensity)
            shift_b = int(-15 * intensity)
            ch_r = np.roll(result[:, :, 0], shift_r, axis=1)
            ch_g = result[:, :, 1]
            ch_b = np.roll(result[:, :, 2], shift_b, axis=1)
            result[:, :, 0] = ch_r
            result[:, :, 2] = ch_b
        block_h = max(4, int(h * 0.03 * intensity))
        for _ in range(max(1, int(5 * intensity))):
            y = np.random.randint(0, h - block_h)
            x = np.random.randint(0, w - 50)
            shift = np.random.randint(-30, 30)
            block = result[y:y + block_h, x:x + 50].copy()
            if 0 <= x + shift < w - 50:
                result[y:y + block_h, x + shift:x + 50 + shift] = block
        return result
