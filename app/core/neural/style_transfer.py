"""
风格迁移神经网络推理模块
========================
基于 VGG 网络的真实神经风格迁移（Neural Style Transfer）。

模型来源:
  - PyTorch hub: mosaic_style_transfer (VGG-19 backbone)
  - ONNX: onnx-community/mosaic-style-transfer (更快)

算法: Gatys et al. "A Neural Algorithm of Artistic Style" 的实时版本，通过预训练前馈
      网络一次性完成风格迁移，无需逐帧优化。
"""

import numpy as np
import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger("AI短剧编辑器.style_transfer")

STYLE_PRESETS_MAP = {
    "vangogh": 0,
    "monet": 1,
    "picasso": 2,
    "cyberpunk": 3,
    "anime": 4,
    "oil_painting": 5,
    "watercolor": 6,
    "sketch": 7,
}


class StyleTransferEngine:
    """
    真实神经风格迁移引擎。

    使用:
        engine = StyleTransferEngine()
        if engine.load():
            styled = engine.transfer(frame, style="cyberpunk", strength=0.8)
    """

    def __init__(self):
        self._model = None
        self._device = "cpu"
        self._loaded = False
        self._input_size = (512, 320)

    def load(self) -> bool:
        """加载风格迁移模型"""
        from app.core.neural_engine import get_neural_engine, InferenceBackend
        eng = get_neural_engine()

        if not eng.is_available:
            return False

        self._device = eng.device

        # 优先 ONNX（最快）
        if eng.backend == InferenceBackend.ONNX:
            try:
                model_path = eng.download_model("onnx-community/mosaic-style-transfer")
                if model_path:
                    if eng.load_onnx_model(model_path, "style_transfer"):
                        self._loaded = True
                        logger.info("风格迁移 ONNX 模型已加载")
                        return True
            except Exception as e:
                logger.debug(f"ONNX 风格迁移加载失败: {e}")

        # 回退 PyTorch hub
        if eng.backend == InferenceBackend.PYTORCH:
            try:
                import torch
                self._model = torch.hub.load(
                    "zhanghang1989/PyTorch-Multi-Style-Transfer",
                    "mosaic_style_transfer",
                    pretrained=True,
                    skip_validation=True,
                    trust_repo=True,
                )
                self._model.eval()
                if self._device == "cuda":
                    self._model = self._model.to("cuda")
                self._loaded = True
                logger.info("风格迁移 PyTorch 模型已加载")
                return True
            except Exception as e:
                logger.debug(f"PyTorch 风格迁移加载失败: {e}")

        return False

    def transfer(self, image: np.ndarray, style: str = "cyberpunk",
                 strength: float = 0.8, preserve_color: bool = True) -> Optional[np.ndarray]:
        """
        执行风格迁移。

        Args:
            image: 输入图像 (H,W,3) BGR uint8
            style: 风格名
            strength: 风格强度 0-1
            preserve_color: 是否保留原图颜色

        Returns:
            风格化后的图像
        """
        if not self._loaded:
            return self._cpu_fallback(image, style, strength, preserve_color)

        h, w = image.shape[:2]

        if self._model is not None:
            # PyTorch 路径
            return self._torch_transfer(image, style, strength, preserve_color, h, w)
        else:
            # ONNX 路径
            return self._onnx_transfer(image, style, strength, preserve_color, h, w)

    def _torch_transfer(self, image: np.ndarray, style: str, strength: float,
                        preserve_color: bool, h: int, w: int) -> Optional[np.ndarray]:
        """PyTorch 风格迁移"""
        import torch
        import cv2

        # 预处理: BGR → RGB → resize → normalize → tensor
        img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        img_rgb = cv2.resize(img_rgb, self._input_size)
        tensor = torch.from_numpy(img_rgb).permute(2, 0, 1).unsqueeze(0).float()
        tensor = tensor / 255.0
        tensor = tensor * 2.0 - 1.0  # [-1, 1]

        idx = STYLE_PRESETS_MAP.get(style, 0)
        style_idx = torch.tensor([idx], dtype=torch.long)

        if self._device == "cuda":
            tensor = tensor.to("cuda")
            style_idx = style_idx.to("cuda")

        with torch.no_grad():
            output = self._model(tensor, style_idx)
            output = output.squeeze(0).cpu()

        # 后处理: tensor → numpy RGB → resize → blend
        output = output.permute(1, 2, 0).numpy()
        output = (output + 1.0) / 2.0  # → [0, 1]
        output = np.clip(output * 255.0, 0, 255).astype(np.uint8)
        output = cv2.resize(output, (w, h))
        output_bgr = cv2.cvtColor(output, cv2.COLOR_RGB2BGR)

        # 强度混合
        if strength < 1.0:
            output_bgr = cv2.addWeighted(image, 1.0 - strength, output_bgr, strength, 0)

        return output_bgr

    def _onnx_transfer(self, image: np.ndarray, style: str, strength: float,
                       preserve_color: bool, h: int, w: int) -> Optional[np.ndarray]:
        """ONNX 风格迁移"""
        from app.core.neural_engine import get_neural_engine
        eng = get_neural_engine()

        try:
            import cv2
            img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            idx = STYLE_PRESETS_MAP.get(style, 0)

            input_tensor = eng.preprocess_onnx(img_rgb, self._input_size)
            style_tensor = np.array([[idx]], dtype=np.int64)

            outputs = eng.run_onnx_inference("style_transfer", {
                "input": input_tensor,
                "style_index": style_tensor,
            })

            if outputs is None:
                return self._cpu_fallback(image, style, strength, preserve_color)

            result = eng.postprocess_onnx(outputs[0], h, w)
            result_bgr = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)

            if strength < 1.0:
                result_bgr = cv2.addWeighted(image, 1.0 - strength, result_bgr, strength, 0)

            return result_bgr
        except Exception as e:
            logger.error(f"ONNX 风格迁移失败: {e}")
            return self._cpu_fallback(image, style, strength, preserve_color)

    def _cpu_fallback(self, image: np.ndarray, style: str, strength: float,
                      preserve_color: bool) -> np.ndarray:
        """
        CPU 风格化回退（基于 OpenCV 的传统图像处理，非神经网络）。
        保持功能可用，等待神经网络后端就绪。
        """
        import cv2

        result = image.astype(np.float32)
        h, w = image.shape[:2]

        style_params = {
            "vangogh":   {"hue": 15,  "sat": 1.3, "blur": 15},
            "monet":     {"hue": 8,   "sat": 1.2, "blur": 20},
            "picasso":   {"hue": 25,  "sat": 1.5, "blur": 5},
            "cyberpunk": {"hue": 180, "sat": 1.8, "blur": 3},
            "anime":     {"hue": 10,  "sat": 1.4, "blur": 7},
            "oil_painting": {"hue": 5, "sat": 1.25, "blur": 18},
            "watercolor": {"hue": 12, "sat": 1.35, "blur": 22},
            "sketch":    {"hue": 0,   "sat": 0.1, "blur": 0},
        }

        params = style_params.get(style, style_params["cyberpunk"])
        s = strength

        if style == "sketch":
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
            inv = 255.0 - gray
            blured = cv2.GaussianBlur(inv, (21, 21), sigmaX=0, sigmaY=0)
            sketch = np.clip(gray / (255 - blured + 0.001) * 255, 0, 255)
            return cv2.cvtColor(sketch.astype(np.uint8), cv2.COLOR_GRAY2BGR)
        else:
            hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 0] = (hsv[:, :, 0] + params["hue"] * s) % 180
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 + (params["sat"] - 1.0) * s), 0, 255)
            result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)

            if params["blur"] > 0 and style in ("oil_painting", "vangogh", "watercolor"):
                d = int(params["blur"] * s)
                if d > 1:
                    result = cv2.bilateralFilter(
                        (result / 255).astype(np.uint8), d=d * 2 + 1, sigmaColor=75, sigmaSpace=75
                    ).astype(np.float32) * 255

            result = np.clip(result, 0, 255).astype(np.uint8)

            if s < 1.0:
                result = cv2.addWeighted(image, 1.0 - s, result, s, 0)

            return result

    def unload(self) -> None:
        from app.core.neural_engine import get_neural_engine
        get_neural_engine().unload_model("style_transfer")
        self._model = None
        self._loaded = False
