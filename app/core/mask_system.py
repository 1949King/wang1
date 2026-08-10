"""
遮罩系统 (Mask System)
======================
对标 OpenShot 的 Mask 系统 (Simple Shape, From File, Chroma Key)。

特性:
- 5 种基础遮罩形状: 矩形, 椭圆, 圆角矩形, 三角形, 菱形
- 文件遮罩: 从 PNG 加载 (灰度图作为 alpha)
- 色度键遮罩: 基于 HSV 的色度键
- 软化边缘 (羽化)
- 反相
- 关键帧动画
"""
import os
import math
import logging
import threading
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

logger = logging.getLogger("AI短剧编辑器.mask")


class MaskShape(str, Enum):
    """遮罩形状"""
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    ROUNDED_RECT = "rounded_rect"
    TRIANGLE = "triangle"
    DIAMOND = "diamond"
    FILE = "file"           # 来自图片文件
    CHROMA_KEY = "chroma"   # 色度键


@dataclass
class MaskKeyframe:
    """遮罩关键帧"""
    time: float          # 时间 (秒)
    feather: float = 0.0 # 边缘羽化 (0-100)
    inverted: bool = False
    opacity: float = 1.0


@dataclass
class Mask:
    """遮罩定义"""
    id: str
    name: str
    shape: MaskShape
    # 几何参数
    x: float = 0.5           # 中心 X (归一化 0-1)
    y: float = 0.5           # 中心 Y
    width: float = 0.5       # 宽度 (归一化)
    height: float = 0.5      # 高度
    rotation: float = 0.0    # 旋转角度
    # 文件遮罩
    file_path: str = ""      # 灰度图片路径
    # 色度键
    key_color: Tuple[int, int, int] = (0, 255, 0)  # 绿幕默认
    threshold: float = 0.3
    # 动态
    keyframes: List[MaskKeyframe] = field(default_factory=list)
    enabled: bool = True

    def get_mask_at(self, time: float, frame_size: Tuple[int, int]) -> Optional["np.ndarray"]:
        """
        生成指定时间点的遮罩数组 (shape: H, W), 值 0-1
        """
        if not self.enabled or not HAS_NUMPY:
            return None
        h, w = frame_size
        if h == 0 or w == 0:
            return None
        # 应用关键帧
        feather = 0.0
        inverted = False
        opacity = 1.0
        if self.keyframes:
            # 找到最近关键帧
            sorted_kf = sorted(self.keyframes, key=lambda k: k.time)
            for kf in sorted_kf:
                if kf.time <= time:
                    feather = kf.feather
                    inverted = kf.inverted
                    opacity = kf.opacity
                else:
                    break
        # 几何参数转换为像素
        cx, cy = self.x * w, self.y * h
        mw, mh = self.width * w, self.height * h
        # 生成坐标网格
        y_grid, x_grid = np.mgrid[0:h, 0:w]
        if self.shape == MaskShape.RECTANGLE:
            mask = (
                (np.abs(x_grid - cx) <= mw / 2) &
                (np.abs(y_grid - cy) <= mh / 2)
            ).astype(np.float32)
        elif self.shape == MaskShape.ELLIPSE:
            nx = (x_grid - cx) / (mw / 2 + 1e-6)
            ny = (y_grid - cy) / (mh / 2 + 1e-6)
            mask = (nx ** 2 + ny ** 2 <= 1).astype(np.float32)
        elif self.shape == MaskShape.ROUNDED_RECT:
            radius = min(mw, mh) * 0.15
            dx = np.abs(x_grid - cx) - (mw / 2 - radius)
            dy = np.abs(y_grid - cy) - (mh / 2 - radius)
            out = np.maximum(dx, 0) ** 2 + np.maximum(dy, 0) ** 2
            mask = (out <= radius ** 2).astype(np.float32)
        elif self.shape == MaskShape.TRIANGLE:
            mask = np.zeros((h, w), dtype=np.float32)
            vertices = np.array([
                [cx, cy - mh / 2],
                [cx - mw / 2, cy + mh / 2],
                [cx + mw / 2, cy + mh / 2],
            ])
            # 简化: 三角形内点检测
            for y in range(h):
                for x in range(w):
                    p = (x, y)
                    v0 = vertices[2] - vertices[0]
                    v1 = vertices[1] - vertices[0]
                    v2 = np.array([p[0] - vertices[0][0], p[1] - vertices[0][1]])
                    dot00 = v0 @ v0
                    dot01 = v0 @ v1
                    dot02 = v0 @ v2
                    dot11 = v1 @ v1
                    dot12 = v1 @ v2
                    denom = dot00 * dot11 - dot01 * dot01
                    if denom == 0:
                        continue
                    u = (dot11 * dot02 - dot01 * dot12) / denom
                    v = (dot00 * dot12 - dot01 * dot02) / denom
                    if u >= 0 and v >= 0 and (u + v) <= 1:
                        mask[y, x] = 1.0
        elif self.shape == MaskShape.DIAMOND:
            nx = np.abs(x_grid - cx) / (mw / 2 + 1e-6)
            ny = np.abs(y_grid - cy) / (mh / 2 + 1e-6)
            mask = (nx + ny <= 1).astype(np.float32)
        elif self.shape == MaskShape.FILE:
            return self._load_file_mask()
        elif self.shape == MaskShape.CHROMA_KEY:
            return None  # 需要结合实际帧计算, 此处仅返回 None
        else:
            mask = np.zeros((h, w), dtype=np.float32)
        # 羽化
        if feather > 0:
            feather_pixels = int(feather * min(h, w) / 100)
            if feather_pixels > 0:
                from scipy.ndimage import distance_transform_edt
                try:
                    dist = distance_transform_edt(mask)
                    mask = np.clip(dist / feather_pixels, 0, 1)
                except ImportError as e:
                    logger.debug(f"[MaskSystem] scipy不可用: {e}")
        # 反相
        if inverted:
            mask = 1.0 - mask
        # 透明度
        mask *= opacity
        return mask

    def _load_file_mask(self) -> Optional["np.ndarray"]:
        """从图片文件加载遮罩"""
        if not self.file_path or not os.path.exists(self.file_path):
            return None
        try:
            import cv2
            img = cv2.imread(self.file_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return None
            return img.astype(np.float32) / 255.0
        except Exception as e:
            logger.error(f"加载遮罩文件失败: {e}")
            return None

    def add_keyframe(self, time: float, **kwargs):
        """添加关键帧"""
        kf = MaskKeyframe(time=time, **kwargs)
        self.keyframes.append(kf)
        self.keyframes.sort(key=lambda k: k.time)


# 内置遮罩预设
MASK_PRESETS: Dict[str, Dict] = {
    "center_circle": {
        "shape": MaskShape.ELLIPSE,
        "x": 0.5, "y": 0.5, "width": 0.3, "height": 0.3,
        "name": "中心圆",
    },
    "vignette": {
        "shape": MaskShape.ELLIPSE,
        "x": 0.5, "y": 0.5, "width": 1.0, "height": 1.0,
        "name": "暗角效果",
    },
    "picture_in_picture": {
        "shape": MaskShape.ROUNDED_RECT,
        "x": 0.75, "y": 0.75, "width": 0.3, "height": 0.3,
        "name": "画中画",
    },
    "horizontal_split": {
        "shape": MaskShape.RECTANGLE,
        "x": 0.5, "y": 0.5, "width": 1.0, "height": 0.5,
        "name": "上下分屏",
    },
    "left_half": {
        "shape": MaskShape.RECTANGLE,
        "x": 0.25, "y": 0.5, "width": 0.5, "height": 1.0,
        "name": "左半屏",
    },
    "right_half": {
        "shape": MaskShape.RECTANGLE,
        "x": 0.75, "y": 0.5, "width": 0.5, "height": 1.0,
        "name": "右半屏",
    },
}


class MaskManager:
    """
    遮罩管理器
    """

    _instance: Optional["MaskManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init = False
        return cls._instance

    def __init__(self):
        if self._init:
            return
        self._init = True
        self._masks: Dict[str, Mask] = {}

    def create_mask(self, mask_id: str, preset: str = "") -> Mask:
        """从预设创建遮罩"""
        if preset and preset in MASK_PRESETS:
            cfg = MASK_PRESETS[preset].copy()
            name = cfg.pop("name", "遮罩")
            cfg["id"] = mask_id
            cfg["name"] = name
            mask = Mask(**cfg)
        else:
            mask = Mask(id=mask_id, name="新遮罩", shape=MaskShape.RECTANGLE)
        self._masks[mask_id] = mask
        return mask

    def get_mask(self, mask_id: str) -> Optional[Mask]:
        return self._masks.get(mask_id)

    def delete_mask(self, mask_id: str) -> bool:
        return self._masks.pop(mask_id, None) is not None

    def list_presets(self) -> List[str]:
        return list(MASK_PRESETS.keys())


mask_manager = MaskManager()
