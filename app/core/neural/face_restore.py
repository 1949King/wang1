"""
人脸修复/增强引擎
==================
人脸区域增强，提供两条路径（诚实降级）：

  默认路径（无需下载模型，始终可用）：
    1. 人脸检测：OpenCV Haar cascade（内置）
    2. 人脸增强：对检测到的人脸区域做超分（RealESRGAN/ESPCN/双三次），再贴回

  增强路径（可选，ONNX GFPGAN）：
    1. 检测到人脸后，把方形人脸 crop 缩放到 512×512 送 GFPGAN ONNX 修复
    2. 模型来自 huggingface: hacksider/deep-live-cam（生产验证过的 GFPGAN 转换版）
    3. 模型下载失败 / 无 ONNX 后端 / 推理失败 → 自动回退默认路径

  无人脸 → 原图返回，不报错；任何失败都不拖垮生成链路。
"""

import logging
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger("AI短剧编辑器.face_restore")

# 原图放大倍数峰值上限，避免超大图内存爆炸
_MAX_DIM = 4096

# GFPGAN ONNX 人脸修复模型（社区转换，生产验证来自 Deep-Live-Cam / FaceFusion）
_GFPGAN_ONNX_REPO = "hacksider/deep-live-cam"
# 不同版本仓库内模型文件名不同，按序尝试（GFPGANv1.4.onnx 旧版，gfpgan-1024.onnx 新版）
_GFPGAN_ONNX_FILES = ("GFPGANv1.4.onnx", "gfpgan-1024.onnx")
_GFPGAN_MODEL_NAME = "gfpgan"
_GFPGAN_INPUT_SIZE = 512


def _max_side(image: np.ndarray) -> int:
    return max(image.shape[:2])


def _detect_faces(image: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """用 OpenCV 内置 Haar cascade 检测人脸，返回 (x, y, w, h) 列表。"""
    try:
        import cv2
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            logger.debug("[FaceRestore] Haar cascade 不可用")
            return []
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48)
        )
        return [tuple(map(int, f)) for f in faces]
    except Exception as exc:
        logger.debug(f"[FaceRestore] 人脸检测失败: {exc}")
        return []


class FaceRestoreEngine:
    """人脸修复引擎：优先 GFPGAN ONNX，回退「人脸检测 + 区域超分」，无人脸原样返回。"""

    def __init__(self) -> None:
        self._sr_engine = None
        self._sr_loaded = False
        self._gfpgan_loaded = False

    def _ensure_sr(self) -> bool:
        """延迟加载超分引擎，成功返回 True。"""
        if self._sr_loaded:
            return True
        try:
            from app.core.neural.super_resolution import SuperResolutionEngine

            engine = SuperResolutionEngine()
            # 仅轻量 ESPCN / 双三次即可满足人脸区域增强，避免首发下载大模型
            if engine.load(scale=2, use_realesrgan=False):
                self._sr_engine = engine
                self._sr_loaded = True
                return True
        except Exception as exc:
            logger.debug(f"[FaceRestore] 超分引擎加载失败: {exc}")
        return False

    def enhance(self, image: np.ndarray) -> np.ndarray:
        """对人脸区域做增强，返回处理后的图像；无人脸/失败时返回原图。

        优先走 GFPGAN ONNX（下载成功才启用），否则回退「区域超分」。

        Args:
            image: 输入图像 (H,W,3) BGR uint8 numpy array
        """
        if _max_side(image) > _MAX_DIM:
            logger.debug("[FaceRestore] 图像过大，跳过人脸修复")
            return image

        faces = _detect_faces(image)
        if not faces:
            return image

        # 优先 GFPGAN ONNX（首次调用触发下载，失败自动降级）
        if self._ensure_gfpgan():
            restored = self._restore_faces_gfpgan(image, faces)
            if restored is not None:
                return restored

        # 回退：区域超分
        if not self._ensure_sr():
            return image

        result = image.copy()
        import cv2

        for x, y, w, h in faces:
            try:
                pad = int(max(w, h) * 0.15)
                x0 = max(0, x - pad)
                y0 = max(0, y - pad)
                x1 = min(image.shape[1], x + w + pad)
                y1 = min(image.shape[0], y + h + pad)
                if x1 - x0 < 8 or y1 - y0 < 8:
                    continue
                face_crop = image[y0:y1, x0:x1]
                upscaled = self._sr_engine.upscale(face_crop)
                if upscaled is None:
                    continue
                restored = cv2.resize(
                    upscaled, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LANCZOS4
                )
                result[y0:y1, x0:x1] = restored
            except Exception as exc:
                logger.debug(f"[FaceRestore] 单张人脸增强失败: {exc}")
                continue

        return result

    def _ensure_gfpgan(self) -> bool:
        """本地缓存命中则加载 GFPGAN ONNX；未就绪返回 False（调用方回退，不阻塞下载）。

        下载由 canvas_bridge 的 start_gfpgan_preload() 在后台负责抓取 + 回传进度。
        """
        if self._gfpgan_loaded:
            return True
        try:
            from app.core.neural_engine import get_neural_engine, InferenceBackend

            eng = get_neural_engine()
            if not eng.is_available or eng.backend != InferenceBackend.ONNX:
                return False

            model_path = None
            for filename in _GFPGAN_ONNX_FILES:
                cached = eng.get_cached_model_path(_GFPGAN_ONNX_REPO, filename)
                if cached:
                    model_path = cached
                    break
            if not model_path:
                return False
            if not eng.load_onnx_model(model_path, _GFPGAN_MODEL_NAME):
                return False
            self._gfpgan_loaded = True
            logger.info("[FaceRestore] GFPGAN ONNX 已加载")
            return True
        except Exception as exc:
            logger.debug(f"[FaceRestore] GFPGAN 加载失败: {exc}")
            return False

    def _restore_faces_gfpgan(self, image: np.ndarray, faces: list) -> Optional[np.ndarray]:
        """对全图所有检测到的人脸逐个做 GFPGAN 修复并贴回；全部失败返回 None。"""
        result = image.copy()
        any_done = False
        for x, y, w, h in faces:
            try:
                pad = int(max(w, h) * 0.15)
                x0 = max(0, x - pad)
                y0 = max(0, y - pad)
                x1 = min(image.shape[1], x + w + pad)
                y1 = min(image.shape[0], y + h + pad)
                if x1 - x0 < 8 or y1 - y0 < 8:
                    continue
                crop = image[y0:y1, x0:x1]
                restored = self._restore_face_gfpgan(crop)
                if restored is None:
                    continue
                result[y0:y1, x0:x1] = restored
                any_done = True
            except Exception as exc:
                logger.debug(f"[FaceRestore] GFPGAN 单张人脸修复失败: {exc}")
                continue
        return result if any_done else None

    def _restore_face_gfpgan(self, face_crop: np.ndarray) -> Optional[np.ndarray]:
        """把单张人脸 crop 送 GFPGAN 修复，返回同尺寸结果；失败返回 None。

        GFPGAN 输入：512×512 RGB、[-1,1]；输出：RGB、[-1,1]（512 或 1024 动态）。
        """
        import cv2

        from app.core.neural_engine import get_neural_engine

        h, w = face_crop.shape[:2]
        if h < 8 or w < 8:
            return None
        try:
            input_bgr = cv2.resize(face_crop, (_GFPGAN_INPUT_SIZE, _GFPGAN_INPUT_SIZE))
            input_rgb = input_bgr[:, :, ::-1].astype("float32") / 127.5 - 1.0
            tensor = np.transpose(input_rgb, (2, 0, 1))[np.newaxis, ...].astype("float32")

            eng = get_neural_engine()
            outputs = eng.run_onnx_inference(_GFPGAN_MODEL_NAME, {"input": tensor})
            if not outputs or outputs[0] is None:
                return None

            out = outputs[0][0]  # CHW
            out = np.transpose(out, (1, 2, 0))  # HWC RGB
            out = np.clip((out + 1.0) * 127.5, 0, 255).astype("uint8")
            out_bgr = out[:, :, ::-1]
            return cv2.resize(out_bgr, (w, h), interpolation=cv2.INTER_LANCZOS4)
        except Exception as exc:
            logger.debug(f"[FaceRestore] GFPGAN 推理失败: {exc}")
            return None