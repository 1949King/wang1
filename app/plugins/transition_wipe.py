"""擦除转场插件 - 水平/垂直擦除过度"""

import numpy as np


class Plugin:
    name = "擦除转场"
    version = "1.0.0"

    def apply(self, from_frame: np.ndarray, to_frame: np.ndarray, progress: float,
              direction: str = "right") -> np.ndarray:
        h, w = from_frame.shape[:2]
        result = from_frame.copy()
        if direction == "right":
            split = int(w * progress)
            result[:, split:] = to_frame[:, split:]
        elif direction == "left":
            split = int(w * (1 - progress))
            result[:, :split] = to_frame[:, :split]
        elif direction == "down":
            split = int(h * progress)
            result[split:, :] = to_frame[split:, :]
        elif direction == "up":
            split = int(h * (1 - progress))
            result[:split, :] = to_frame[:split, :]
        return result
