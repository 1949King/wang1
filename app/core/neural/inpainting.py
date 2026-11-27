"""
AI 物体移除 / Inpainting 模块
=============================
基于 LaMa (Large Mask Inpainting) 的真实神经网络图像修复。

模型来源:
  - LaMa ONNX (HuggingFace: onnx-community/lama_dilated)
  - LaMa PyTorch (GitHub: advimman/lama)

算法:
  Dilated ResNet + FFC (Fast Fourier Convolutions) + Perceptual Loss，
  对大面积缺失区域的修复效果远超传统的 Telea/Navier-Stokes.

回退策略: ONNX → PyTorch → OpenCV Telea/Navier-Stokes
"""

import numpy as np
import logging
import os
from typing import List, Optional

logger = logging.getLogger("AI短剧编辑器.inpainting")

# 历史仓 id：不再用于下载（T3：绝不自动下载；仅留作历史标识）。
# onnx-community/lama_dilated 仓已不存在（T0 许可核实），资源地址改 Carve/LaMa-ONNX。
LAMA_ONNX = "onnx-community/lama_dilated"

# ── T3（2026-11-20）：LaMa 本地优先 —— 绝不自动下载，只认用户自取放置的权重 ──

LAMA_FILENAME = "lama_dilated.onnx"

#: 权重缺失时给用户的自取指引（与 tool_weights 下载中心同一文案，单一真源）。
LAMA_GUIDANCE = (
    "未检测到 LaMa 局部修补权重（lama_dilated.onnx）。本软件绝不自动下载模型：\n"
    "【资源地址（Apache-2.0，T0 已核；README 权重声明未核，请自行确认）】\n"
    "  · https://huggingface.co/Carve/LaMa-ONNX\n"
    "【部署步骤】\n"
    "  1. 获取 LaMa dilated 的 ONNX 权重，放置时命名为 lama_dilated.onnx。\n"
    "  2. 放到以下任一位置：\n"
    "     ① 环境变量 SHIGUANG_LAMA_PATH 指向的完整文件路径；\n"
    "     ② 仓库 thirdparty/models/lama_dilated.onnx。\n"
    "  3. 重启画布桥后重试「局部修补」。缺失时诚实降级 Telea（degraded=True）。"
)


def lama_search_paths() -> List[str]:
    """LaMa 权重的**候选路径**（按优先级，T3 本地优先）。

    与 super_resolution.realesrgan_search_paths 同纪律：只找本地文件，绝不触发下载。
      ① 环境变量 `SHIGUANG_LAMA_PATH` 指向的**整文件**路径
      ② `<仓库>/thirdparty/models/lama_dilated.onnx`
    """
    paths = []
    env_file = os.environ.get("SHIGUANG_LAMA_PATH", "").strip()
    if env_file:
        paths.append(env_file)
    try:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        paths.append(os.path.join(repo, "thirdparty", "models", LAMA_FILENAME))
    except Exception:  # stability-gate: allow-swallow（可选搜索根探测：算不出 repo 根就只是少一个候选路径，不影响正确性）
        pass
    return paths


def find_lama_onnx() -> str:
    """返回**实际存在**的 LaMa 权重路径；都没有则返回空串（绝不自动下载）。"""
    for p in lama_search_paths():
        if os.path.isfile(p):
            return p
    return ""


class InpaintingEngine:
    """
    AI 图像修复 / 物体移除引擎。

    使用:
        engine = InpaintingEngine()
        if engine.load():
            result = engine.inpaint(image, mask)
    """

    def __init__(self):
        self._model_name = "lama_inpaint"
        self._input_size = (512, 512)
        self._loaded = False

    def load(self) -> bool:
        """加载 LaMa Inpainting 模型"""
        from app.core.neural_engine import get_neural_engine, InferenceBackend
        eng = get_neural_engine()

        if not eng.is_available:
            return False

        # ONNX 路径
        # T3（2026-11-20）：**绝不自动下载** —— 只认用户自取放置的本地权重；
        # 缺失时打 guidance 后诚实返 False（上层落 Telea 并如实标 degraded，不冒充 AI）。
        if eng.backend == InferenceBackend.ONNX:
            model_path = find_lama_onnx()
            if model_path:
                try:
                    if eng.load_onnx_model(model_path, self._model_name):
                        self._loaded = True
                        logger.info("LaMa Inpainting ONNX 模型已加载（本地自取权重: %s）", model_path)
                        return True
                    # 加载失败 ⇒ 不认领（与 A-6「回退冒充 AI」同纪律）
                    logger.warning("LaMa 权重在盘但加载失败（%s），不认领 lama_inpaint", model_path)
                except Exception as e:
                    logger.debug(f"ONNX LaMa 加载失败: {e}")
            else:
                logger.info("LaMa 权重缺失，绝不自动下载。%s", LAMA_GUIDANCE)

        return False

    def inpaint(self, image: np.ndarray, mask: np.ndarray) -> Optional[np.ndarray]:
        """
        执行图像修复。mask 中 255=需要修复的区域，0=保留的区域。

        Args:
            image: (H,W,3) BGR uint8
            mask: (H,W) uint8, 255=修复区, 0=保留区

        Returns:
            修复后图像
        """
        if not self._loaded:
            return self._traditional_inpaint(image, mask)

        from app.core.neural_engine import get_neural_engine
        eng = get_neural_engine()

        try:
            import cv2
            h, w = image.shape[:2]

            # 预处理: BGR → RGB → normalize → resize → NCHW
            img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            img_rgb = cv2.resize(img_rgb, self._input_size)
            img_float = img_rgb.astype(np.float32) / 255.0

            # LaMa 输入格式: (image, mask) concatenated
            m = cv2.resize(mask, self._input_size)
            m_float = m.astype(np.float32) / 255.0
            if m_float.ndim == 2:
                m_float = m_float[..., np.newaxis]
            elif m_float.ndim == 3 and m_float.shape[2] == 3:
                m_float = m_float[:, :, 0:1]

            img_chw = np.transpose(img_float, (2, 0, 1))  # (3,H,W)
            mask_chw = np.transpose(m_float, (2, 0, 1)) if m_float.shape[2] == 1 else m_float[np.newaxis, ...]
            combined = np.concatenate([img_chw, mask_chw], axis=0)  # (4,H,W)
            input_tensor = combined[np.newaxis, ...].astype(np.float32)  # (1,4,H,W)

            outputs = eng.run_onnx_inference(self._model_name, {"input": input_tensor})
            if outputs is None:
                return self._traditional_inpaint(image, mask)

            result = outputs[0][0]  # (3,H,W)
            result = np.transpose(result, (1, 2, 0))  # → HWC
            result = np.clip(result * 255.0, 0, 255).astype(np.uint8)
            result = cv2.resize(result, (w, h))
            result_bgr = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)

            # 仅替换 mask 区域，保留不相干区域
            if mask.ndim == 2:
                mask_3ch = np.stack([mask, mask, mask], axis=2)
            else:
                mask_3ch = mask
            mask_bool = mask_3ch > 128
            final = image.copy()
            final[mask_bool] = result_bgr[mask_bool]

            return final
        except Exception as e:
            logger.error(f"AI Inpainting 失败: {e}")
            return self._traditional_inpaint(image, mask)

    def _traditional_inpaint(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """传统 Telea/Navier-Stokes 回退"""
        import cv2
        try:
            # Telea 算法（快速，适合小面积）
            return cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA)
        except Exception:
            return image.copy()

    def unload(self) -> None:
        from app.core.neural_engine import get_neural_engine
        get_neural_engine().unload_model(self._model_name)
        self._loaded = False
