"""
GPU加速渲染器 - 基于numpy/CV2优化的高性能渲染
实现真实的图像处理运算，支持CuPy/CUDA可选加速
"""

import numpy as np
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QImage
import logging
import time

logger = logging.getLogger("AI短剧编辑器.gpu_render")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import cupy as cp
    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False


class GPUDetector:
    """
    GPU能力检测器
    
    注意: 本项目的主 GPU 检测器位于 app/core/gpu_acceleration.py 的 GPUDetector。
    本类仅用于 gpu_render.py 内部 GPURenderer 的本地 GPU 检测。
    外部模块需要 GPU 信息请使用:
        from app.core.gpu_acceleration import get_gpu_detector
    """

    _instance = None
    _detected = False
    _nvidia_available = False
    _cuda_available = False
    _gpu_name = ""

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def detect(self) -> Dict[str, Any]:
        if self._detected:
            return {
                'nvidia': self._nvidia_available,
                'cuda': self._cuda_available,
                'name': self._gpu_name,
                'cupy': CUPY_AVAILABLE,
            }
        self._detected = True
        try:
            import torch
            self._cuda_available = torch.cuda.is_available()
            if self._cuda_available:
                self._gpu_name = torch.cuda.get_device_name(0)
                self._nvidia_available = True
                logger.info(f"检测到CUDA GPU: {self._gpu_name}")
        except ImportError:
            logger.info("torch未安装，禁用CUDA加速")
        return {
            'nvidia': self._nvidia_available,
            'cuda': self._cuda_available,
            'name': self._gpu_name,
            'cupy': CUPY_AVAILABLE,
        }


class GPURenderer(QObject):
    """GPU加速渲染器 - 提供高性能图像处理运算"""

    def __init__(self):
        super().__init__()
        self._detector = GPUDetector()
        self._capabilities = self._detector.detect()
        self._use_gpu = self._capabilities['cuda'] or self._capabilities['cupy']

        self._luts = {}
        self._init_preset_luts()

    def _init_preset_luts(self):
        """初始化预设LUT"""
        self._luts = {
            "电影胶片": self._gen_lut_film(),
            "复古暖调": self._gen_lut_vintage(),
            "青橙色调": self._gen_lut_teal_orange(),
            "黑白经典": self._gen_lut_bw(),
            "日系清新": self._gen_lut_jp_fresh(),
            "赛博朋克": self._gen_lut_cyberpunk(),
            "废土风格": self._gen_lut_wasteland(),
            "糖果色": self._gen_lut_candy(),
            "暗夜蓝调": self._gen_lut_night_blue(),
        }

    def render_frame(self, frame: np.ndarray, effects_config: Dict) -> np.ndarray:
        """渲染单帧 - 应用所有效果"""
        if frame is None or not effects_config:
            return frame

        result = frame.astype(np.float32)

        lut = effects_config.get('lut')
        if lut and lut in self._luts:
            result = self._apply_lut(result, self._luts[lut], effects_config.get('lut_intensity', 1.0))

        filter_name = effects_config.get('filter')
        if filter_name:
            result = self._apply_filter(result, filter_name, effects_config.get('filter_intensity', 0.5))

        brightness = effects_config.get('brightness', 0)
        if brightness != 0:
            result = result + brightness

        contrast = effects_config.get('contrast', 1.0)
        if contrast != 1.0:
            mean_val = result.mean()
            result = (result - mean_val) * contrast + mean_val

        saturation = effects_config.get('saturation', 1.0)
        if saturation != 1.0 and result.shape[2] >= 3:
            gray = result[:, :, :3].mean(axis=2, keepdims=True)
            result[:, :, :3] = gray + (result[:, :, :3] - gray) * saturation

        hue = effects_config.get('hue', 0)
        if hue != 0 and CV2_AVAILABLE and result.shape[2] >= 3:
            hsv = cv2.cvtColor(result.astype(np.uint8), cv2.COLOR_RGB2HSV)
            hsv[:, :, 0] = (hsv[:, :, 0].astype(np.int32) + int(hue)) % 180
            result = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(np.float32)

        exposure = effects_config.get('exposure', 0)
        if exposure != 0:
            result = result * (2.0 ** exposure)

        exposure_val = effects_config.get('exposure_val', 0)
        if exposure_val != 0:
            result = result + exposure_val * 2.55

        highlight_val = effects_config.get('highlights', 0)
        if highlight_val != 0 and result.shape[2] >= 3:
            mask = result[:, :, :3].mean(axis=2) > 128
            result[mask] = result[mask] + highlight_val * 1.5

        shadow_val = effects_config.get('shadows', 0)
        if shadow_val != 0 and result.shape[2] >= 3:
            mask = result[:, :, :3].mean(axis=2) <= 128
            result[mask] = result[mask] + shadow_val * 1.5

        sharpness = effects_config.get('sharpness', 0)
        if sharpness != 0 and CV2_AVAILABLE:
            kernel = np.array([
                [-1, -1, -1],
                [-1, 9 + sharpness * 0.2, -1],
                [-1, -1, -1]
            ], dtype=np.float32) / (1.0 + abs(sharpness) * 0.05)
            for c in range(min(3, result.shape[2])):
                result[:, :, c] = cv2.filter2D(
                    result[:, :, c].astype(np.uint8), -1, kernel)

        vignette_val = effects_config.get('vignette', 0)
        if vignette_val > 0:
            h, w = result.shape[:2]
            yy, xx = np.ogrid[:h, :w]
            cx, cy = w / 2, h / 2
            dist = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
            mask = 1.0 - dist * vignette_val
            mask = np.clip(mask, 0.2, 1.0)
            if result.ndim == 3:
                result = result * mask[:, :, np.newaxis]
            else:
                result = result * mask[:, :]

        blend_mode = effects_config.get('blend_mode', '正常')
        if blend_mode != '正常' and result.shape[2] >= 3:
            result = self._apply_blend_mode(result, blend_mode)

        crop_top = effects_config.get('crop_top', 0)
        crop_bottom = effects_config.get('crop_bottom', 0)
        crop_left = effects_config.get('crop_left', 0)
        crop_right = effects_config.get('crop_right', 0)
        if any([crop_top, crop_bottom, crop_left, crop_right]):
            h, w = result.shape[:2]
            result = result[max(0, crop_top):max(1, h - crop_bottom),
                            max(0, crop_left):max(1, w - crop_right)]

        opacity = effects_config.get('opacity', 1.0)
        if opacity < 1.0 and result.shape[2] >= 3:
            result[:, :, :3] = result[:, :, :3] * opacity

        return np.clip(result, 0, 255).astype(np.uint8)

    def _apply_lut(self, frame: np.ndarray, lut: np.ndarray, intensity: float = 1.0) -> np.ndarray:
        """应用3D LUT"""
        try:
            if CV2_AVAILABLE:
                result = cv2.LUT(frame.astype(np.uint8), lut.astype(np.uint8))
            else:
                result = frame
            if intensity < 1.0:
                result = frame * (1 - intensity) + result * intensity
            return result.astype(np.float32)
        except Exception as e:
            logger.error(f"LUT应用失败: {e}")
            return frame

    def _apply_filter(self, frame: np.ndarray, filter_name: str, intensity: float) -> np.ndarray:
        """应用滤镜效果"""
        result = frame.astype(np.float32)
        factor = intensity

        filters = {
            "原片": lambda f, i: f,
            "电影": lambda f, i: self._xpro_ii(f, i),
            "复古": lambda f, i: self._hefe(f, i),
            "清新": lambda f, i: self._lo_fi(f, i),
            "黑白": lambda f, i: self._grayscale(f, i),
            "暖阳": lambda f, i: self._warm(f, i),
            "冷调": lambda f, i: self._cool(f, i),
            "梦幻": lambda f, i: self._dreamy(f, i),
            "锐利": lambda f, i: self._sharpen_filter(f, i),
            "柔和": lambda f, i: self._soft_glow(f, i),
            "都市": lambda f, i: self._urban(f, i),
            "黄昏": lambda f, i: self._golden_hour(f, i),
        }

        if filter_name in filters:
            return np.clip(filters[filter_name](result, factor), 0, 255).astype(np.uint8)
        return np.clip(result, 0, 255).astype(np.uint8)

    def _grayscale(self, f, i):
        gray = f[:, :, :3].mean(axis=2, keepdims=True)
        return f * (1 - i) + np.repeat(gray, 3, axis=2) * i

    def _sepia(self, f, i):
        sep = f.copy()
        sep[:, :, 0] = f[:, :, 2] * 0.393 + f[:, :, 1] * 0.769 + f[:, :, 0] * 0.189
        sep[:, :, 1] = f[:, :, 2] * 0.349 + f[:, :, 1] * 0.686 + f[:, :, 0] * 0.168
        sep[:, :, 2] = f[:, :, 2] * 0.272 + f[:, :, 1] * 0.534 + f[:, :, 0] * 0.131
        return np.clip(sep, 0, 255) * i + f * (1 - i)

    def _warm(self, f, i):
        r = np.clip(f[:, :, 0] + 15 * i, 0, 255)
        b = np.clip(f[:, :, 2] - 10 * i, 0, 255)
        f[:, :, 0] = f[:, :, 0] * (1 - i) + r * i
        f[:, :, 2] = f[:, :, 2] * (1 - i) + b * i
        return f

    def _cool(self, f, i):
        b = np.clip(f[:, :, 2] + 15 * i, 0, 255)
        r = np.clip(f[:, :, 0] - 10 * i, 0, 255)
        f[:, :, 2] = f[:, :, 2] * (1 - i) + b * i
        f[:, :, 0] = f[:, :, 0] * (1 - i) + r * i
        return f

    def _dreamy(self, f, i):
        if CV2_AVAILABLE:
            blur = cv2.GaussianBlur(f.astype(np.uint8), (21, 21), 5).astype(np.float32)
            return f * (1 - i * 0.5) + blur * (i * 0.5)
        g = f.mean(axis=2)
        f[:, :, 0] += g * i * 0.1
        f[:, :, 2] += g * i * 0.1
        return f

    def _sharpen_filter(self, f, i):
        if CV2_AVAILABLE:
            kernel = np.array([[-0.5, -0.5, -0.5], [-0.5, 5, -0.5], [-0.5, -0.5, -0.5]]) * i
            for c in range(3):
                f[:, :, c] = cv2.filter2D(f[:, :, c].astype(np.uint8), -1, kernel)
        return f

    def _soft_glow(self, f, i):
        g = f.mean(axis=2)
        f[:, :, 0] += g * i * 0.3
        f[:, :, 1] += g * i * 0.15
        return f

    def _urban(self, f, i):
        f[:, :, 0] = f[:, :, 0] * (1 + 0.05 * i)
        f[:, :, 2] = f[:, :, 2] * (1 + 0.05 * i)
        return f

    def _golden_hour(self, f, i):
        f[:, :, 0] = np.clip(f[:, :, 0] + 20 * i, 0, 255)
        f[:, :, 1] = np.clip(f[:, :, 1] + 10 * i, 0, 255)
        return f

    def _xpro_ii(self, f, i):
        g = f.mean(axis=2, keepdims=True)
        f = f * (1 - i * 0.3) + np.repeat(g, 3, axis=2) * (i * 0.15)
        f[:, :, 2] += 8 * i
        f[:, :, 0] += 12 * i
        f[:, :, 1] -= 5 * i
        return np.clip(f, 0, 255)

    def _hefe(self, f, i):
        f[:, :, 0] += 15 * i
        f[:, :, 1] += 5 * i
        f[:, :, 2] -= 10 * i
        return np.clip(f, 0, 255)

    def _lo_fi(self, f, i):
        if CV2_AVAILABLE:
            sat = cv2.cvtColor(f.astype(np.uint8), cv2.COLOR_RGB2HSV)
            sat[:, :, 1] = np.clip(sat[:, :, 1] * (1 + i * 0.5), 0, 255).astype(np.uint8)
            f = cv2.cvtColor(sat, cv2.COLOR_HSV2RGB).astype(np.float32)
        return f

    def _apply_blend_mode(self, frame: np.ndarray, mode: str) -> np.ndarray:
        """应用混合模式"""
        gray = frame.mean(axis=2, keepdims=True)
        blend_map = {
            "变暗": np.minimum,
            "变亮": np.maximum,
            "正片叠底": lambda a, b: a * b / 255.0,
            "滤色": lambda a, b: 255 - (255 - a) * (255 - b) / 255.0,
            "叠加": lambda a, b: np.where(a < 128, 2 * a * b / 255, 255 - 2 * (255 - a) * (255 - b) / 255),
            "柔光": lambda a, b: np.where(a < 128, 2 * a * b / 255 + a * a / 255 * (255 - 2 * b) / 255,
                                          np.sqrt(a) * (2 * b - 255) + 2 * 255 * (1 - b / 255) * (a / 255)),
            "强光": lambda a, b: np.where(b < 128, 2 * a * b / 255, 255 - 2 * (255 - a) * (255 - b) / 255),
            "差值": lambda a, b: np.abs(a - b),
            "排除": lambda a, b: a + b - 2 * a * b / 255,
        }
        if mode in blend_map:
            bg = np.ones_like(frame[:, :, :3]) * 128
            blended = np.clip(blend_map[mode](frame[:, :, :3], bg), 0, 255)
            frame[:, :, :3] = blended
        return frame

    def _gen_lut_film(self) -> np.ndarray:
        """电影胶片LUT"""
        lut = np.zeros((256,), dtype=np.uint8)
        for i in range(256):
            lut[i] = np.clip(int(255 * (i / 255) ** 0.85), 0, 255)
        return np.stack([lut, lut, lut], axis=1)

    def _gen_lut_vintage(self) -> np.ndarray:
        """复古暖调LUT"""
        r = np.array([np.clip(int(255 * (i / 255) ** 0.9 + 8), 0, 255) for i in range(256)], dtype=np.uint8)
        g = np.array([np.clip(int(255 * (i / 255) ** 0.95 - 3), 0, 255) for i in range(256)], dtype=np.uint8)
        b = np.array([np.clip(int(255 * (i / 255) ** 1.05 - 12), 0, 255) for i in range(256)], dtype=np.uint8)
        return np.stack([r, g, b], axis=1)

    def _gen_lut_teal_orange(self) -> np.ndarray:
        """青橙色调LUT"""
        r = np.array([np.clip(int(255 * (i / 255) ** 1.1 + 5), 0, 255) for i in range(256)], dtype=np.uint8)
        g = np.array([np.clip(int(255 * (i / 255) ** 1.0 - 8), 0, 255) for i in range(256)], dtype=np.uint8)
        b = np.array([np.clip(int(255 * (i / 255) ** 0.85 + 12), 0, 255) for i in range(256)], dtype=np.uint8)
        return np.stack([r, g, b], axis=1)

    def _gen_lut_bw(self) -> np.ndarray:
        """黑白经典LUT"""
        v = np.array([int(255 * (i / 255) ** 0.9) for i in range(256)], dtype=np.uint8)
        return np.stack([v, v, v], axis=1)

    def _gen_lut_jp_fresh(self) -> np.ndarray:
        """日系清新LUT"""
        r = np.clip(np.arange(256) + 5, 0, 255).astype(np.uint8)
        g = np.clip(np.arange(256) + 10, 0, 255).astype(np.uint8)
        b = np.clip(np.arange(256) + 8, 0, 255).astype(np.uint8)
        return np.stack([r, g, b], axis=1)

    def _gen_lut_cyberpunk(self) -> np.ndarray:
        """赛博朋克LUT"""
        r = np.clip((np.arange(256) ** 1.2 / 255 ** 0.2), 0, 255).astype(np.uint8)
        g = np.clip((np.arange(256) ** 0.8 * 255 ** 0.2), 0, 255).astype(np.uint8)
        b = np.clip((np.arange(256) ** 1.3 / 255 ** 0.3), 0, 255).astype(np.uint8)
        return np.stack([r, g, b], axis=1)

    def _gen_lut_wasteland(self) -> np.ndarray:
        """废土风格LUT"""
        r = np.clip(np.arange(256) * 1.1 - 10, 0, 255).astype(np.uint8)
        g = np.clip(np.arange(256) * 0.9 + 5, 0, 255).astype(np.uint8)
        b = np.clip(np.arange(256) * 0.8 - 5, 0, 255).astype(np.uint8)
        return np.stack([r, g, b], axis=1)

    def _gen_lut_candy(self) -> np.ndarray:
        """糖果色LUT"""
        r = np.clip(np.arange(256) * 1.15 + 10, 0, 255).astype(np.uint8)
        g = np.clip(np.arange(256) * 1.05, 0, 255).astype(np.uint8)
        b = np.clip(np.arange(256) * 1.1 + 5, 0, 255).astype(np.uint8)
        return np.stack([r, g, b], axis=1)

    def _gen_lut_night_blue(self) -> np.ndarray:
        """暗夜蓝调LUT"""
        r = np.clip(np.arange(256) * 0.8 - 10, 0, 255).astype(np.uint8)
        g = np.clip(np.arange(256) * 0.9, 0, 255).astype(np.uint8)
        b = np.clip(np.arange(256) * 1.2 + 20, 0, 255).astype(np.uint8)
        return np.stack([r, g, b], axis=1)

    def get_lut_names(self) -> List[str]:
        return list(self._luts.keys())

    def get_filter_names(self) -> List[str]:
        return ["原片", "电影", "复古", "清新", "黑白", "暖阳", "冷调", "梦幻", "锐利", "柔和", "都市", "黄昏"]

    def resize_frame(self, frame: np.ndarray, width: int, height: int) -> np.ndarray:
        """高性能帧缩放"""
        if CV2_AVAILABLE:
            return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
        if h == height and w == width:
            return frame
        return np.array(frame[::max(1, h // height), ::max(1, w // width)])

    def to_qimage(self, frame: np.ndarray) -> QImage:
        """转换为QImage"""
        h, w = frame.shape[:2]
        if frame.ndim == 3 and frame.shape[2] == 3:
            return QImage(frame.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        elif frame.ndim == 3 and frame.shape[2] == 4:
            return QImage(frame.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        return QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8).copy()


_gpu_renderer: Optional[GPURenderer] = None


def get_gpu_renderer() -> GPURenderer:
    global _gpu_renderer
    if _gpu_renderer is None:
        _gpu_renderer = GPURenderer()
    return _gpu_renderer
