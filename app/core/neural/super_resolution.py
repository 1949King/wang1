"""
超分辨率神经网络推理模块
========================
基于神经网络引擎实现真实的 2x/3x/4x 超分辨率推理。

模型来源:
  - RealESRGAN_x4plus (HuggingFace: onnx-community/RealESRGAN_x4plus)
  - ESPCN x2/x3/x4 (OpenCV DNN 内置)
  - BSRGAN (HuggingFace: Faldom/BSRGAN)

回退策略: ONNX → PyTorch → OpenCV DNN → 传统插值

T2 本地优先（2026-11-20）:
  - 模型权重**绝不自动下载、不随包**：只探测用户自取放置的本地文件，
    缺失时诚实降级并给出 guidance（获取方式见「下载中心」tool_weights）。
  - 自取路径：SHIGUANG_REALESRGAN_PATH 整文件 / thirdparty/models/realesrgan_x4plus.onnx。
  - 原 onnx-community/RealESRGAN_x4plus 仓已不存在（T0 核实），
    资源地址改 https://huggingface.co/qualcomm/Real-ESRGAN-x4plus（BSD-3-Clause）。
"""

import numpy as np
import logging
import os
from typing import List, Optional

logger = logging.getLogger("AI短剧编辑器.super_resolution")

# ── 模型规格 ──────────────────────────────────────────────

# 历史仓 id：不再用于下载（T2：绝不自动下载；仅留作历史标识）
REALESRGAN_ONNX = "onnx-community/RealESRGAN_x4plus"
BSRGAN_ONNX = "Faldom/BSRGAN"

ESPCN_MODELS = {
    2: "ESPCN_x2",
    3: "ESPCN_x3",
    4: "ESPCN_x4",
}


def espcn_search_paths(scale: int) -> List[str]:
    """ESPCN 模型文件的**候选路径**（按优先级）。

    A-6（2026-10-05）：`cv2.dnn_superres` 需要一个**真实存在的 .pb 文件**，
    而仓库里没有随附（也不该静默假装有）。候选顺序：
      ① 环境变量 `SHIGUANG_ESPCN_DIR` 指定的目录（用户自备模型的出口）
      ② `<仓库>/thirdparty/models/`
      ③ 本模块同级目录
    """
    name = f"{ESPCN_MODELS.get(scale, 'ESPCN_x2')}.pb"
    roots = []
    env_dir = os.environ.get("SHIGUANG_ESPCN_DIR", "").strip()
    if env_dir:
        roots.append(env_dir)
    try:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        roots.append(os.path.join(repo, "thirdparty", "models"))
    except Exception:  # stability-gate: allow-swallow（可选搜索根探测：算不出 repo 根就只是少一个候选目录，不影响正确性）
        pass
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    return [os.path.join(r, name) for r in roots]


def find_espcn_model(scale: int) -> str:
    """返回**实际存在**的 ESPCN 模型路径；都没有则返回空串（绝不返回裸文件名）。"""
    for p in espcn_search_paths(scale):
        if os.path.isfile(p):
            return p
    return ""


# ── T2（2026-11-20）：RealESRGAN 本地优先 —— 绝不自动下载，只认用户自取放置的权重 ──

REALESRGAN_FILENAME = "realesrgan_x4plus.onnx"

#: 权重缺失时给用户的自取指引（与 tool_weights 下载中心同一文案，单一真源）。
REALESRGAN_GUIDANCE = (
    "未检测到 RealESRGAN x4plus 超分权重（realesrgan_x4plus.onnx）。本软件绝不自动下载模型：\n"
    "【资源地址（BSD-3-Clause，T0 已核）】\n"
    "  · https://huggingface.co/qualcomm/Real-ESRGAN-x4plus\n"
    "【部署步骤】\n"
    "  1. 获取 RealESRGAN_x4plus 的 ONNX 权重，放置时命名为 realesrgan_x4plus.onnx。\n"
    "  2. 放到以下任一位置：\n"
    "     ① 环境变量 SHIGUANG_REALESRGAN_PATH 指向的完整文件路径；\n"
    "     ② 仓库 thirdparty/models/realesrgan_x4plus.onnx。\n"
    "  3. 重启画布桥后重试「画质增强」。缺失时诚实降级双三次插值（degraded=True）。"
)


def realesrgan_search_paths() -> List[str]:
    """RealESRGAN 权重的**候选路径**（按优先级，T2 本地优先）。

    与 espcn_search_paths 同纪律：只找本地文件，绝不触发下载。
      ① 环境变量 `SHIGUANG_REALESRGAN_PATH` 指向的**整文件**路径
      ② `<仓库>/thirdparty/models/realesrgan_x4plus.onnx`
    """
    paths = []
    env_file = os.environ.get("SHIGUANG_REALESRGAN_PATH", "").strip()
    if env_file:
        paths.append(env_file)
    try:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        paths.append(os.path.join(repo, "thirdparty", "models", REALESRGAN_FILENAME))
    except Exception:  # stability-gate: allow-swallow（可选搜索根探测：算不出 repo 根就只是少一个候选路径，不影响正确性）
        pass
    return paths


def find_realesrgan_onnx() -> str:
    """返回**实际存在**的 RealESRGAN 权重路径；都没有则返回空串（绝不自动下载）。"""
    for p in realesrgan_search_paths():
        if os.path.isfile(p):
            return p
    return ""


class SuperResolutionEngine:
    """
    超分辨率神经网络推理引擎。

    使用:
        engine = SuperResolutionEngine()
        if engine.load(scale=2):
            result = engine.upscale(frame)
    """

    def __init__(self):
        self._model_name = ""
        self._scale = 2
        self._loaded = False
        self._espcn_loaded = False
        self._espcn_model_path = ""   # A-6：只有模型文件**真实存在**时才填（防回退冒充 AI）

    def load(self, scale: int = 2, use_realesrgan: bool = False) -> bool:
        """
        加载超分辨率模型。

        Args:
            scale: 放大倍数 (2/3/4)
            use_realesrgan: 是否尝试 RealESRGAN（需要 ONNX Runtime）
        """
        self._scale = scale

        from app.core.neural_engine import get_neural_engine, InferenceBackend
        eng = get_neural_engine()

        if not eng.is_available:
            logger.warning("无神经网络后端，将使用传统插值")
            return False

        # 方案1: RealESRGAN ONNX（最高质量）
        # T2（2026-11-20）：**绝不自动下载** —— 只认用户自取放置的本地权重；
        # 缺失时打 guidance 后落 ESPCN/双三次旧链（诚实降级，不冒充 AI）。
        if use_realesrgan and eng.backend == InferenceBackend.ONNX:
            model_path = find_realesrgan_onnx()
            if model_path:
                self._model_name = "realesrgan"
                if eng.load_onnx_model(model_path, self._model_name):
                    self._loaded = True
                    logger.info(f"RealESRGAN 已加载: {scale}x（本地自取权重: {model_path}）")
                    return True
                # 加载失败 ⇒ 不认领（与 A-6 同纪律：防回退冒充 AI）
                self._model_name = ""
                logger.warning("RealESRGAN 权重在盘但加载失败（%s），不认领 realesrgan", model_path)
            else:
                logger.info("RealESRGAN 权重缺失，绝不自动下载。%s", REALESRGAN_GUIDANCE)

        # 方案2: OpenCV DNN ESPCN（轻量）
        #
        # ⚠️ A-6 诚实性修复（2026-10-05）：旧实现只要 `cv2.__path__` 存在就
        # `_model_name="espcn"` + 打日志「ESPCN 就绪」并 return True —— **从不校验模型文件**。
        # 而 `_espcn_upscale` 用的是**裸文件名** `ESPCN_x2.pb`（cv2.dnn_superres 会去 cwd 找），
        # 仓库里根本没有这个文件 ⇒ 推理必然失败并**静默回退双三次**，
        # 但 `canvas_enhance._step_sharpen` 据 `_model_name` 上报 `engine="espcn" degraded=False`
        # ⇒ **把双三次插值冒充 AI 超分**（正是「回退冒充 AI」红线）。
        # 现在：**先找模型文件，找不到就不认领 espcn**（返回 False、_model_name 保持空），
        # 于是 `_step_sharpen` 会自动算出 model="bicubic" + degraded=True + 诚实 reason。
        try:
            import cv2  # noqa: F401  （确认 OpenCV 可用；模型另需 .pb 文件）

            model_path = find_espcn_model(scale)
            if model_path:
                self._model_name = "espcn"
                self._espcn_model_path = model_path
                self._espcn_loaded = True
                self._loaded = True
                logger.info("OpenCV ESPCN 就绪: %sx（%s）", scale, model_path)
                return True
            logger.info(
                "ESPCN 模型文件缺失（查找 %s）⇒ 超分将降级为双三次插值，"
                "并如实上报 degraded（不再谎称 espcn）",
                ", ".join(espcn_search_paths(scale)) or "无候选路径",
            )
        except Exception as e:
            logger.debug(f"ESPCN 加载跳过: {e}")

        return False

    def upscale(self, image: np.ndarray) -> Optional[np.ndarray]:
        """
        执行超分辨率推理。

        Args:
            image: 输入图像 (H,W,3) uint8 numpy array

        Returns:
            放大后的图像，失败返回 None
        """
        if not self._loaded:
            return self._bicubic_upscale(image)

        h, w = image.shape[:2]

        # ── ONNX 推理 ──
        if self._model_name == "realesrgan":
            return self._onnx_upscale(image, h, w)

        # ── OpenCV ESPCN ──
        if self._espcn_loaded:
            return self._espcn_upscale(image, h, w)

        # ── 传统回退 ──
        return self._bicubic_upscale(image)

    def _onnx_upscale(self, image: np.ndarray, h: int, w: int) -> Optional[np.ndarray]:
        """ONNX RealESRGAN 推理"""
        from app.core.neural_engine import get_neural_engine
        eng = get_neural_engine()

        # RealESRGAN 输入: RGB float32 BCHW, 不需要 normalize
        try:
            import cv2
            img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        except Exception:
            img_rgb = image

        img_float = img_rgb.astype(np.float32) / 255.0
        input_tensor = np.transpose(img_float, (2, 0, 1))[np.newaxis, ...]

        outputs = eng.run_onnx_inference(self._model_name, {"input": input_tensor.astype(np.float32)})
        if outputs is None:
            return self._bicubic_upscale(image)

        result = outputs[0][0]  # (C,H,W)
        result = np.transpose(result, (1, 2, 0))  # → HWC
        result = np.clip(result * 255.0, 0, 255).astype(np.uint8)

        try:
            import cv2
            result = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)
        except Exception as e:
            logger.debug(f"[SuperResolution] 颜色空间转换失败: {e}")

        return result

    def _espcn_upscale(self, image: np.ndarray, h: int, w: int) -> Optional[np.ndarray]:
        """OpenCV ESPCN 推理。

        ⚠️ A-6（2026-10-05）：必须用 `load()` **验证过存在**的路径。
        旧写法 `f"ESPCN_x{scale}.pb"` 是**裸文件名**，`cv2.dnn_superres.readModel` 会去 cwd 找、
        必然失败后静默回退双三次 —— 而 `_model_name` 已被置为 "espcn" ⇒ 上层会把
        双三次插值上报成 AI 超分。这里再兜一道：路径不可用就不认领、明确回退。
        """
        try:
            import cv2
            model_file = self._espcn_model_path or find_espcn_model(self._scale)
            if not model_file or not os.path.isfile(model_file):
                logger.debug("ESPCN 模型缺失 ⇒ 回退双三次（调用方按 _model_name 如实标 degraded）")
                return self._bicubic_upscale(image)
            sr = cv2.dnn_superres.DnnSuperResImpl_create()
            sr.readModel(model_file)
            sr.setModel("espcn", self._scale)
            return sr.upsample(image)
        except Exception as e:
            logger.debug(f"ESPCN 推理失败: {e}")
            return self._bicubic_upscale(image)

    def _bicubic_upscale(self, image: np.ndarray) -> np.ndarray:
        """双三次插值回退"""
        import cv2
        h, w = image.shape[:2]
        return cv2.resize(image, (w * self._scale, h * self._scale), interpolation=cv2.INTER_CUBIC)

    def unload(self) -> None:
        """卸载模型"""
        from app.core.neural_engine import get_neural_engine
        if self._model_name:
            get_neural_engine().unload_model(self._model_name)
        self._loaded = False
        self._espcn_loaded = False
