"""
AI 背景替换 / 语义分割模块
==========================
基于 MODNet/U2Net 的人像分割网络，实现真实的美颜抠图换背景。

模型来源:
  - MODNet (HuggingFace: onnx-community/modnet_photographic_portrait_matting)
  - U2Net (HuggingFace: onnx-community/u2net-portrait)
  - RMBG-1.4 (HuggingFace: briaai/RMBG-1.4, 通用物体背景去除)

回退策略: ONNX → PyTorch → OpenCV GrabCut
"""

import numpy as np
import logging
from typing import Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.background_replace")

MODNET_ONNX = "onnx-community/modnet_photographic_portrait_matting"
RMBG_ONNX = "briaai/RMBG-1.4"


class BackgroundReplaceEngine:
    """
    AI 人像抠图 / 背景替换引擎。

    使用:
        engine = BackgroundReplaceEngine()
        if engine.load():
            mask = engine.segment(frame)
            bg = engine.replace_background(frame, mask, background)
    """

    def __init__(self):
        self._model_name = ""
        self._input_size = (512, 512)
        self._loaded = False
        self._session = None

    def load(self, model: str = "modnet") -> bool:
        """
        加载分割模型。

        Args:
            model: "modnet" (人像半透明边缘) | "rmbg" (通用主体)
        """
        from app.core.neural_engine import get_neural_engine, InferenceBackend
        eng = get_neural_engine()

        if not eng.is_available:
            return False

        if eng.backend == InferenceBackend.ONNX:
            hub = MODNET_ONNX if model == "modnet" else RMBG_ONNX
            try:
                model_path = eng.download_model(hub)
                if model_path:
                    self._model_name = f"bg_replace_{model}"
                    if eng.load_onnx_model(model_path, self._model_name):
                        self._loaded = True
                        logger.info(f"{model.upper()} 分割模型已加载")
                        return True
            except Exception as e:
                logger.debug(f"ONNX 分割模型下载失败: {e}")

        # 回退 PyTorch
        if eng.backend == InferenceBackend.PYTORCH:
            try:
                import torch
                if model == "modnet":
                    self._model_name = f"bg_replace_{model}"
                    self._loaded = eng.load_torch_model(
                        lambda: torch.hub.load(
                            "ZHKKKe/MODNet",
                            "mobilenetv2_human_seg",
                            pretrained=True,
                            trust_repo=True,
                        ),
                        self._model_name,
                    )
                    if self._loaded:
                        logger.info("MODNet PyTorch 模型已加载")
                        return True
            except Exception as e:
                logger.debug(f"PyTorch 分割模型下载失败: {e}")

        return False

    def segment(self, image: np.ndarray) -> Optional[np.ndarray]:
        """
        分割人像/主体，返回 alpha mask (H,W) uint8, 0=背景, 255=前景。

        Args:
            image: (H,W,3) BGR uint8
        """
        if not self._loaded:
            return self._grabcut_fallback(image)

        return self._onnx_segment(image)

    def _onnx_segment(self, image: np.ndarray) -> Optional[np.ndarray]:
        """ONNX MODNet/U2Net 推理"""
        from app.core.neural_engine import get_neural_engine
        eng = get_neural_engine()

        try:
            import cv2
            h, w = image.shape[:2]

            img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            img_rgb = cv2.resize(img_rgb, self._input_size)
            img_float = img_rgb.astype(np.float32) / 255.0
            input_tensor = np.transpose(img_float, (2, 0, 1))[np.newaxis, ...]

            outputs = eng.run_onnx_inference(self._model_name, {"input": input_tensor.astype(np.float32)})
            if outputs is None:
                return self._grabcut_fallback(image)

            # MODNet 输出: (1,1,H,W) alpha matte
            alpha = outputs[0][0, 0]  # (H,W)
            alpha = cv2.resize(alpha, (w, h), interpolation=cv2.INTER_LINEAR)
            alpha = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)

            logger.debug(f"分割完成: mask 范围 [{alpha.min()}, {alpha.max()}]")
            return alpha
        except Exception as e:
            logger.error(f"ONNX 分割失败: {e}")
            return self._grabcut_fallback(image)

    def replace_background(self, image: np.ndarray, mask: np.ndarray,
                           background: np.ndarray = None,
                           bg_color: Tuple[int, int, int] = (0, 255, 0)) -> np.ndarray:
        """
        替换背景。

        Args:
            image: (H,W,3) BGR 原图
            mask: (H,W) uint8, 0=背景 255=前景
            background: (H,W,3) 背景图，None 则用纯色
            bg_color: 纯色背景 RGB
        """
        import cv2
        h, w = image.shape[:2]

        if background is not None:
            bg = cv2.resize(background, (w, h))
        else:
            bg = np.full((h, w, 3), bg_color[::-1], dtype=np.uint8)  # BGR

        mask_f = mask.astype(np.float32) / 255.0
        mask_3ch = np.stack([mask_f, mask_f, mask_f], axis=2)
        result = (image.astype(np.float32) * mask_3ch + bg.astype(np.float32) * (1.0 - mask_3ch))
        return np.clip(result, 0, 255).astype(np.uint8)

    def _grabcut_fallback(self, image: np.ndarray) -> np.ndarray:
        """OpenCV GrabCut 回退方案"""
        import cv2
        h, w = image.shape[:2]
        # 中心矩形作为可能前景
        rect = (w // 4, h // 4, w // 2, h // 2)
        mask = np.zeros((h, w), dtype=np.uint8)
        bgd_model = np.zeros((1, 65), dtype=np.float64)
        fgd_model = np.zeros((1, 65), dtype=np.float64)

        try:
            cv2.grabCut(image, mask, rect, bgd_model, fgd_model, 3, cv2.GC_INIT_WITH_RECT)
            result_mask = np.where((mask == 2) | (mask == 0), 0, 255).astype(np.uint8)
        except Exception:
            result_mask = np.full((h, w), 128, dtype=np.uint8)

        return result_mask

    def unload(self) -> None:
        from app.core.neural_engine import get_neural_engine
        if self._model_name:
            get_neural_engine().unload_model(self._model_name)
        self._loaded = False
        self._session = None
