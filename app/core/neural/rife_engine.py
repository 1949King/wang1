"""RIFE v4.9 神经补帧引擎（探测 / 加载 / 单帧推理）。

设计纪律（2026-11-20 T4 项二）
================================
- **绝不自动下载权重**：模型由用户自取放置（见 RIFE_MODEL_GUIDANCE）。
  探测沿用 ESPCN 单文件先例（super_resolution.espcn_search_paths），
  不进 LOCAL_FAMILY_MODELS（那是生成模型族，RIFE 是单文件工具权重）。
- **诚实降级**：模型缺失 ⇒ find_rife_model 返回 ""（上层 ok:false + guidance）；
  权重损坏 / 架构不符 ⇒ load 返回 False（上层降级光流，degraded=True）；
  torch 不可用 ⇒ 抛 RifeUnavailableError（类型化，区别于损坏）；
  显存不足 ⇒ 抛 RifeOOMError（上层据此降级光流）。
- **懒 import torch / rife_net**：使 find_rife_model / is_available 在无 torch
  环境也能探测（rife_net 顶部 import torch，故不在本模块顶部引入）。

架构与许可见 rife_net.py（vendor 自 ECCV2022-RIFE / Practical-RIFE，MIT）。
"""
from __future__ import annotations

import logging
import os
from typing import List

import numpy as np

logger = logging.getLogger("AI短剧编辑器.rife_engine")

# 官方发布的 v4.9 权重文件名（作者 hzwer 以 MIT 许可发布）
RIFE_MODEL_FILENAME = "rife49.pth"

# 模型缺失引导：资源地址自取 + 部署步骤 + 明确不自动下载（打包不捆绑模型）
RIFE_MODEL_GUIDANCE = (
    "未检测到 RIFE v4.9 神经补帧模型（rife49.pth）。本软件绝不自动下载模型，"
    "请自行获取并放置后重试：\n"
    "【资源地址（MIT 许可，作者 hzwer 发布）】\n"
    "  · Google Drive: https://drive.google.com/file/d/1UssCvbL8N-ty0xIKM5G5ZTEgp9o4w3hp/view\n"
    "  · 百度网盘: https://pan.baidu.com/s/18cbx3EP4HWgSa1vkcXvvyw?pwd=swr9\n"
    "【部署步骤】\n"
    "  1. 下载 rife49.pth（v4.9 权重）。\n"
    "  2. 放到以下任一位置（按优先级）：\n"
    "     ① 环境变量 SHIGUANG_RIFE_PATH 指向的完整文件路径；\n"
    "     ② 环境变量 SHIGUANG_RIFE_DIR 指定目录下的 rife49.pth；\n"
    f"     ③ 仓库 thirdparty/models/{RIFE_MODEL_FILENAME}；\n"
    f"     ④ 模块目录 app/core/neural/{RIFE_MODEL_FILENAME}。\n"
    "  3. 需已安装 PyTorch（.venv312 自带）；重启画布桥后再次点击「神经补帧」。\n"
    "放置后无需联网即可本地推理；模型缺失时本功能诚实报错，不会静默降级冒充神经补帧。"
)


def rife_search_paths() -> List[str]:
    """RIFE 权重候选路径（按优先级）。

    ① SHIGUANG_RIFE_PATH（整文件路径，用户自备出口）
    ② SHIGUANG_RIFE_DIR（目录）下的 rife49.pth
    ③ <仓库>/thirdparty/models/rife49.pth
    ④ 本模块同级目录下的 rife49.pth
    """
    paths: List[str] = []
    env_file = os.environ.get("SHIGUANG_RIFE_PATH", "").strip()
    if env_file:
        paths.append(env_file)
    roots: List[str] = []
    env_dir = os.environ.get("SHIGUANG_RIFE_DIR", "").strip()
    if env_dir:
        roots.append(env_dir)
    try:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        roots.append(os.path.join(repo, "thirdparty", "models"))
    except Exception:  # stability-gate: allow-swallow（可选搜索根探测：算不出 repo 根只是少一个候选目录，不影响正确性）
        pass
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    for r in roots:
        paths.append(os.path.join(r, RIFE_MODEL_FILENAME))
    return paths


def find_rife_model() -> str:
    """返回**实际存在**的 RIFE 权重路径；都没有则返回空串（绝不返回裸文件名）。"""
    for p in rife_search_paths():
        if os.path.isfile(p):
            return p
    return ""


class RifeEngine:
    """RIFE v4.9 推理引擎（单帧对插值）。

    使用::

        engine = RifeEngine()
        if engine.load():           # 模型缺失/损坏 ⇒ False
            mid_rgb = engine.interpolate_pair(prev_rgb, cur_rgb, 0.5)
    """

    def __init__(self) -> None:
        self._model = None            # rife_net.Model（懒加载）
        self._device = "cpu"
        self._loaded = False
        self._model_path = ""

    def is_available(self) -> bool:
        """是否可用：模型文件存在且 torch 可导入（不触发加载）。"""
        if not find_rife_model():
            return False
        try:
            import torch  # noqa: F401
            return True
        except ImportError:
            return False

    def load(self, model_path: str = "") -> bool:
        """加载权重。

        - torch 不可用 ⇒ 抛 RifeUnavailableError（类型化环境错误）。
        - 模型缺失 / 损坏 / 架构不符 ⇒ 返回 False（不抛，上层诚实降级）。
        - 成功 ⇒ True，自动选 cuda（若可用）否则 cpu。
        """
        try:
            import torch
        except ImportError as e:
            from app.core.neural.rife_net import RifeUnavailableError
            raise RifeUnavailableError(f"PyTorch 不可用：{e}") from e

        from app.core.neural import rife_net

        path = model_path or find_rife_model()
        if not path or not os.path.isfile(path):
            logger.info("[RIFE] 模型缺失，跳过加载（上层据 guidance 提示自取）")
            return False
        try:
            ckpt = torch.load(path, map_location="cpu", weights_only=False)
            # 兼容 {'flownet': state_dict} 与裸 state_dict 两种 checkpoint 形态
            state = ckpt.get("flownet", ckpt) if isinstance(ckpt, dict) else ckpt
            model = rife_net.Model()
            rife_net.load_flownet_state(model.flownet, state)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model.eval().to(device)
            self._model = model
            self._device = device
            self._loaded = True
            self._model_path = path
            logger.info("[RIFE] v4.9 已加载: %s (device=%s)", path, device)
            return True
        except Exception as e:
            # 损坏 / 架构不符 / 反序列化失败：诚实返回 False，不静默产出错误画面
            logger.warning("[RIFE] 权重加载失败（降级光流）: %s", e)
            self._model = None
            self._loaded = False
            return False

    def interpolate_pair(self, prev_rgb: np.ndarray, cur_rgb: np.ndarray,
                         timestep: float = 0.5) -> np.ndarray:
        """在 prev→cur 之间按 timestep 插一帧。

        输入/输出均为 HxWx3 **RGB uint8**。内部按上游 inference_video 管线：
        pad 到 128 倍数 → /255 归一化 → 前向 → *255 取整 → 裁剪回原尺寸。
        显存不足抛 RifeOOMError；其它推理错误抛 RifeError（上层降级光流）。
        """
        import torch
        from app.core.neural import rife_net

        if self._model is None:
            raise rife_net.RifeError("RIFE 模型未加载")
        h, w = prev_rgb.shape[:2]
        tmp = 128  # scale=1.0 时的对齐基数（镜像上游 tmp=max(128,int(128/scale))）
        ph = ((h - 1) // tmp + 1) * tmp
        pw = ((w - 1) // tmp + 1) * tmp
        p0 = np.pad(prev_rgb, ((0, ph - h), (0, pw - w), (0, 0)), mode="edge")
        p1 = np.pad(cur_rgb, ((0, ph - h), (0, pw - w), (0, 0)), mode="edge")
        t0 = torch.from_numpy(p0.transpose(2, 0, 1).copy()).float().div_(255).unsqueeze(0).to(self._device)
        t1 = torch.from_numpy(p1.transpose(2, 0, 1).copy()).float().div_(255).unsqueeze(0).to(self._device)
        try:
            mid = self._model.inference(t0, t1, timestep, 1.0)
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                raise rife_net.RifeOOMError(str(e)) from e
            raise rife_net.RifeError(str(e)) from e
        out = (mid[0] * 255).byte().cpu().numpy().transpose(1, 2, 0)[:h, :w]
        return np.ascontiguousarray(out)
