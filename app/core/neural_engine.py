"""
统一神经网络推理引擎 (NeuralEngine)
=================================
ONNX + PyTorch 双后端自动切换，为所有 AI 特效提供统一的模型推理能力。

架构:
  NeuralEngine (单例)
    ├── 后端检测: ONNX Runtime > PyTorch > OpenCV DNN > CPU fallback
    ├── 模型管理: HuggingFace/ModelScope 自动下载 → 本地缓存
    ├── 设备管理: CUDA/DML/CoreML/CPU 自动选择
    └── 统一API: load_model() + run_inference()

默认模型缓存路径: app/models/cache/
"""

import os
import sys
import logging
import threading
import numpy as np
from typing import Optional, Dict, Any, Callable, Tuple, List
from dataclasses import dataclass, field

logger = logging.getLogger("AI短剧编辑器.neural_engine")


@dataclass
class ModelSpec:
    """模型规格"""
    name: str                          # 模型名称
    url: str                           # HuggingFace/ModelScope 下载链接
    local_path: str                    # 本地缓存路径
    input_size: Tuple[int, int] = (256, 256)
    input_mean: Tuple[float, ...] = (0.485, 0.456, 0.406)
    input_std: Tuple[float, ...] = (0.229, 0.224, 0.225)
    description: str = ""


class InferenceBackend:
    """推理后端枚举"""
    ONNX = "onnx"
    PYTORCH = "torch"
    OPENCV_DNN = "opencv_dnn"
    NONE = "none"


class NeuralEngine:
    """
    统一神经网络推理引擎 — 线程安全单例。

    使用方式:
        engine = get_neural_engine()
        engine.load_esrgan("realesrgan_x2")
        result = engine.upscale(frame, scale=2)
    """

    _instance: Optional['NeuralEngine'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized: bool = True

        self._backend = InferenceBackend.NONE
        self._device = "cpu"
        self._loaded_models: Dict[str, Any] = {}
        self._ort_session = None
        self._torch_available = False
        self._onnx_available = False
        self._cache_dir: str = ""
        self._model_registry: Dict[str, ModelSpec] = {}

        self._detect_backend()
        self._setup_cache_dir()

    # ── 后端检测 ──────────────────────────────────────────

    def _detect_backend(self) -> None:
        """检测最优推理后端"""
        # 1. 优先 ONNX Runtime
        try:
            import onnxruntime
            providers = onnxruntime.get_available_providers()
            logger.info(f"ONNX Runtime 可用, providers: {providers}")
            self._onnx_available = True
            self._backend = InferenceBackend.ONNX

            if "CUDAExecutionProvider" in providers:
                self._device = "cuda"
            elif "DmlExecutionProvider" in providers:
                self._device = "dml"
            logger.info(f"后端: ONNX ({self._device})")
            return
        except ImportError:
            logger.debug("ONNX Runtime 未安装")

        # 2. 回退 PyTorch
        try:
            import torch
            self._torch_available = True
            self._backend = InferenceBackend.PYTORCH
            if torch.cuda.is_available():
                self._device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                self._device = "mps"
            logger.info(f"后端: PyTorch ({self._device})")
            return
        except ImportError:
            logger.debug("PyTorch 未安装")

        # 3. 回退 OpenCV DNN
        try:
            import cv2
            _ = cv2.dnn
            self._backend = InferenceBackend.OPENCV_DNN
            logger.info(f"后端: OpenCV DNN (cpu)")
            return
        except Exception:
            pass

        logger.warning("无可用的神经网络推理后端")

    def _setup_cache_dir(self) -> None:
        """设置模型缓存目录"""
        here = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.normpath(os.path.join(here, ".."))
        self._cache_dir = os.path.join(project_root, "models", "cache")
        os.makedirs(self._cache_dir, exist_ok=True)

    # ── 公开状态查询 ──────────────────────────────────────

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def device(self) -> str:
        return self._device

    @property
    def is_available(self) -> bool:
        return self._backend != InferenceBackend.NONE

    def is_model_loaded(self, name: str) -> bool:
        return name in self._loaded_models and self._loaded_models[name] is not None

    # ── 模型下载（从 HuggingFace hub）────────────────────

    def download_model(self, model_name: str,
                       progress_cb: Callable[[str], None] = None) -> Optional[str]:
        """
        从 HuggingFace/ModelScope 下载模型到本地缓存。
        
        参数:
          model_name: 如 "onnx-community/RealESRGAN_x2plus"
          progress_cb: 进度回调
        返回:
          本地文件路径，失败返回 None
        """
        cache_path = os.path.join(self._cache_dir, model_name.replace("/", "_"))
        if os.path.isfile(cache_path):
            if progress_cb:
                progress_cb(f"模型已缓存: {cache_path}")
            return cache_path

        if progress_cb:
            progress_cb(f"正在下载模型: {model_name}...")

        # 方式1: huggingface_hub
        try:
            from huggingface_hub import hf_hub_download, list_repo_files
            if progress_cb:
                progress_cb(f"从 HuggingFace Hub: {model_name}")
            path = hf_hub_download(
                repo_id=model_name,
                filename="model.onnx",
                cache_dir=self._cache_dir,
                local_files_only=False,
            )
            if progress_cb:
                progress_cb(f"下载完成: {path}")
            return path
        except Exception as e:
            logger.debug(f"HuggingFace 下载失败: {e}")

        # 方式2: modelscope（国内加速）
        try:
            from modelscope.hub.snapshot_download import snapshot_download
            if progress_cb:
                progress_cb(f"从 ModelScope: {model_name}")
            path = snapshot_download(
                model_name,
                cache_dir=self._cache_dir,
            )
            if progress_cb:
                progress_cb(f"下载完成: {path}")
            return path
        except Exception as e:
            logger.debug(f"ModelScope 下载失败: {e}")

        return None

    # ── ONNX 推理 ─────────────────────────────────────────

    def load_onnx_model(self, model_path: str, model_name: str) -> bool:
        """加载 ONNX 模型"""
        if not self._onnx_available or not os.path.isfile(model_path):
            return False

        try:
            import onnxruntime as ort

            providers = []
            if self._device == "cuda":
                providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            elif self._device == "dml":
                providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
            else:
                providers = ["CPUExecutionProvider"]

            session = ort.InferenceSession(
                model_path,
                providers=providers,
                sess_options=ort.SessionOptions(),
            )
            self._loaded_models[model_name] = session
            logger.info(f"ONNX 模型已加载: {model_name} ({model_path})")
            return True
        except Exception as e:
            logger.error(f"ONNX 模型加载失败: {model_name} - {e}")
            return False

    def run_onnx_inference(self, model_name: str, input_dict: Dict[str, np.ndarray]) -> Optional[List[np.ndarray]]:
        """执行 ONNX 推理"""
        session = self._loaded_models.get(model_name)
        if session is None:
            logger.error(f"ONNX 模型未加载: {model_name}")
            return None
        try:
            inputs = {k: v for k, v in input_dict.items()}
            outputs = session.run(None, inputs)
            return outputs
        except Exception as e:
            logger.error(f"ONNX 推理失败: {model_name} - {e}")
            return None

    # ── PyTorch 推理 ──────────────────────────────────────

    def load_torch_model(self, model_builder: Callable[[], Any], model_name: str) -> bool:
        """加载 PyTorch 模型"""
        if not self._torch_available:
            return False

        try:
            import torch
            model = model_builder()
            model.eval()
            if self._device == "cuda":
                model = model.to("cuda")
            self._loaded_models[model_name] = model
            logger.info(f"PyTorch 模型已加载: {model_name}")
            return True
        except Exception as e:
            logger.error(f"PyTorch 模型加载失败: {model_name} - {e}")
            return False

    def run_torch_inference(self, model_name: str,
                            preprocess: Callable[[np.ndarray], Any],
                            postprocess: Callable[[Any], np.ndarray],
                            image: np.ndarray) -> Optional[np.ndarray]:
        """执行 PyTorch 推理"""
        model = self._loaded_models.get(model_name)
        if model is None:
            logger.error(f"PyTorch 模型未加载: {model_name}")
            return None
        try:
            import torch
            with torch.no_grad():
                tensor = preprocess(image)
                output = model(tensor)
                return postprocess(output)
        except Exception as e:
            logger.error(f"PyTorch 推理失败: {model_name} - {e}")
            return None

    # ── 图像预处理/后处理 工具 ─────────────────────────────

    @staticmethod
    def preprocess_onnx(image: np.ndarray, input_size: Tuple[int, int],
                        mean: Tuple[float, ...] = (0.485, 0.456, 0.406),
                        std: Tuple[float, ...] = (0.229, 0.224, 0.225)) -> np.ndarray:
        """标准 ONNX 输入预处理 (HWC → NCHW, normalize)"""
        import cv2
        if image.shape[:2] != input_size:
            image = cv2.resize(image, input_size)
        image = image.astype(np.float32) / 255.0
        image = (image - np.array(mean, dtype=np.float32)) / np.array(std, dtype=np.float32)
        image = np.transpose(image, (2, 0, 1))  # HWC → CHW
        image = np.expand_dims(image, axis=0)    # CHW → NCHW
        return image.astype(np.float32)

    @staticmethod
    def postprocess_onnx(output: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
        """标准 ONNX 输出后处理 (NCHW → HWC, de-normalize)"""
        result = output[0]  # NCHW → CHW
        result = np.transpose(result, (1, 2, 0))  # CHW → HWC
        result = np.clip(result * 255.0, 0, 255).astype(np.uint8)
        if result.shape[:2] != (target_h, target_w):
            import cv2
            result = cv2.resize(result, (target_w, target_h))
        return result

    # ── 资源管理 ──────────────────────────────────────────

    def unload_model(self, model_name: str) -> None:
        """卸载指定模型"""
        if model_name in self._loaded_models:
            del self._loaded_models[model_name]
            logger.info(f"模型已卸载: {model_name}")

    def unload_all(self) -> None:
        """卸载所有模型"""
        self._loaded_models.clear()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info("所有模型已卸载")


# ── 全局单例 ──────────────────────────────────────────────

_neural_engine: Optional[NeuralEngine] = None


def get_neural_engine() -> NeuralEngine:
    """获取神经网络引擎单例"""
    global _neural_engine
    if _neural_engine is None:
        _neural_engine = NeuralEngine()
    return _neural_engine
