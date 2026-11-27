# -*- coding: utf-8 -*-
"""工具权重登记（T1 下载中心，2026-11-20）。

为什么单独一个文件
==================
RIFE / ESPCN / RealESRGAN / LaMa / 深度 / 蒸馏 LoRA 都是**单文件工具权重**，
不是生成模型族 ⇒ 不进 `LOCAL_FAMILY_MODELS`（那是 diffusers 目录族），
也不进 `--pull` 自动下载通道。本模块只做三件事：
  · 探测：复用各引擎已有的 `find_*` 函数，不重新发明搜索逻辑；
  · guidance：资源地址自取 + 放置步骤，**绝不自动下载、不随包**（用户红线）；
  · `tool_rows()`：产出 capability="tool" 的视图行，供「本地模型」页与 check_models 共用。

许可门禁（T0，2026-11-20）
==========================
8 项均由许可核实代理**实抓 LICENSE 原文 / 模型卡声明**核实：
RIFE MIT · ESPCN Apache-2.0 · RealESRGAN BSD-3-Clause · LaMa Apache-2.0（带注）·
depth-small Apache-2.0（large 为 NC，不接）· Wan2.2-Lightning Apache-2.0。
资源地址均已核实可达；权重只由用户自取放置，程序不替他下载。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from app.core import video_depth
from app.core.neural import inpainting, rife_engine, super_resolution, video_gen

logger = logging.getLogger("AI短剧编辑器.core.neural.tool_weights")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _find_single_file(env_name: str, filename: str) -> str:
    """通用单文件探测：env 整文件路径 → thirdparty/models/<filename>；都没有返空串。"""
    env = os.environ.get(env_name, "").strip()
    if env and os.path.isfile(env):
        return env
    p = os.path.join(_REPO_ROOT, "thirdparty", "models", filename)
    if os.path.isfile(p):
        return p
    return ""


# ★ T4（2026-11-20）：LoRA 探测与 guidance 的单一真源迁至 video_gen
#   （find_lightning_lora / LIGHTNING_LORA_GUIDANCE）—— 生成引擎 load() 与
#   下载中心共用同一套搜索逻辑，不两套实现。本模块只委托。


# ── 资源地址（T0 许可门禁 2026-11-20 实抓核实，仅自取不自动下载）──────────────
_RIFE_SOURCES = [
    {"name": "Google Drive（官方 v4.9）",
     "url": "https://drive.google.com/file/d/1UssCvbL8N-ty0xIKM5G5ZTEgp9o4w3hp/view",
     "note": "MIT 许可，作者 hzwer 发布；下载 rife49.pth（与 RIFE_MODEL_GUIDANCE 同源）"},
    {"name": "百度网盘（官方 v4.9）",
     "url": "https://pan.baidu.com/s/18cbx3EP4HWgSa1vkcXvvyw?pwd=swr9",
     "note": "MIT 许可，提取码 swr9；下载 rife49.pth"},
]
_ESPCN_SOURCE = {
    "name": "GitHub · TF-ESPCN",
    "url": "https://github.com/fannymonori/TF-ESPCN",
    "note": "Apache-2.0；仓库内附 ESPCN_x2/x3/x4.pb（OpenCV dnn_superres 用冻结图）",
}
_REALESRGAN_SOURCE = {
    "name": "HuggingFace · qualcomm Real-ESRGAN-x4plus",
    "url": "https://huggingface.co/qualcomm/Real-ESRGAN-x4plus",
    "note": "BSD-3-Clause；ONNX 导出版（原 onnx-community 仓已不存在，T0 核实改此）",
}
_LAMA_SOURCE = {
    "name": "HuggingFace · Carve LaMa-ONNX",
    "url": "https://huggingface.co/Carve/LaMa-ONNX",
    "note": "Apache-2.0（代码许可已核；README 权重声明未核，使用前请自行确认）",
}
_DEPTH_SOURCE = {
    "name": "hf-mirror · Depth-Anything-V2-Small ONNX",
    "url": video_depth.MODEL_URL,
    "note": "Apache-2.0（small；large 为 NC 不接）；约 26MB 量化版，现有深度功能已在用",
}
_LORA_SOURCE = {
    "name": "HuggingFace · lightx2v Wan2.2-Lightning",
    "url": "https://huggingface.co/lightx2v/Wan2.2-Lightning",
    "note": "Apache-2.0；蒸馏 LoRA（.safetensors，文件名含 lightning），6 步加速用",
}


def _espcn_spec(scale: int) -> Dict[str, Any]:
    """ESPCN x2/x3/x4 三档共用一套登记模板（探测复用 super_resolution.find_espcn_model）。"""
    name = "ESPCN_x%d.pb" % scale
    return {
        "label": "ESPCN x%d 轻量超分" % scale,
        "filename": name,
        "probe": lambda: super_resolution.find_espcn_model(scale),
        "place": "SHIGUANG_ESPCN_DIR 目录 / thirdparty/models/%s" % name,
        "guidance": (
            "未检测到 ESPCN x%d 超分模型（%s）。本软件绝不自动下载模型，请自取放置：\n"
            "【资源地址（Apache-2.0，T0 已核）】\n"
            "  · %s\n"
            "【部署步骤】\n"
            "  1. 从仓库获取 %s。\n"
            "  2. 放到以下任一位置（按优先级）：\n"
            "     ① 环境变量 SHIGUANG_ESPCN_DIR 指定目录下的 %s；\n"
            "     ② 仓库 thirdparty/models/%s；\n"
            "     ③ 模块目录 app/core/neural/%s。\n"
            "  3. 重启画布桥后重试「画质增强」。缺失时诚实降级双三次插值（degraded=True）。"
        ) % (scale, name, _ESPCN_SOURCE["url"], name, name, name, name),
        "sources": [_ESPCN_SOURCE],
        "license": "Apache-2.0",
    }


#: 工具权重登记表（有序）。每项＝探测函数 + 放置路径 + guidance + 已核资源地址 + 许可。
#: **绝不自动下载**：probe 只找本地文件；sources 只供用户自己去挑版本。
TOOL_WEIGHTS: Dict[str, Dict[str, Any]] = {
    "rife49": {
        "label": "RIFE v4.9 神经补帧",
        "filename": rife_engine.RIFE_MODEL_FILENAME,
        "probe": rife_engine.find_rife_model,
        "place": "SHIGUANG_RIFE_PATH 整文件 / SHIGUANG_RIFE_DIR 目录 / thirdparty/models/rife49.pth",
        "guidance": rife_engine.RIFE_MODEL_GUIDANCE,
        "sources": _RIFE_SOURCES,
        "license": "MIT",
    },
    "espcn_x2": _espcn_spec(2),
    "espcn_x3": _espcn_spec(3),
    "espcn_x4": _espcn_spec(4),
    "realesrgan_x4plus": {
        "label": "RealESRGAN x4plus 超分（ONNX）",
        "filename": "realesrgan_x4plus.onnx",
        # T2：probe/guidance 统一走 super_resolution 的本地优先实现（单一真源，绝不自动下载）
        "probe": super_resolution.find_realesrgan_onnx,
        "place": "SHIGUANG_REALESRGAN_PATH 整文件 / thirdparty/models/realesrgan_x4plus.onnx",
        "guidance": super_resolution.REALESRGAN_GUIDANCE,
        "sources": [_REALESRGAN_SOURCE],
        "license": "BSD-3-Clause",
    },
    "lama_dilated": {
        "label": "LaMa 局部修补（ONNX）",
        "filename": inpainting.LAMA_FILENAME,
        # T3：probe/guidance 统一走 inpainting 的本地优先实现（单一真源，绝不自动下载）
        "probe": inpainting.find_lama_onnx,
        "place": "SHIGUANG_LAMA_PATH 整文件 / thirdparty/models/lama_dilated.onnx",
        "guidance": inpainting.LAMA_GUIDANCE,
        "sources": [_LAMA_SOURCE],
        "license": "Apache-2.0",
    },
    "depth_anything_v2_small": {
        "label": "Depth-Anything-V2-Small 深度（ONNX）",
        "filename": "model_quantized.onnx",
        "probe": video_depth.find_model,
        "place": "models/depth/*.onnx / SHIGUANG_DEPTH_MODEL 整文件",
        "guidance": (
            "未检测到 Depth-Anything-V2-Small 深度模型（model_quantized.onnx，约 26MB）。"
            "本软件绝不自动下载模型：\n"
            "【资源地址（Apache-2.0 small，T0 已核；large 为 NC 不接）】\n"
            "  · %s\n"
            "【部署步骤】\n"
            "  1. 下载 model_quantized.onnx，放到仓库 models/depth/ 下（任意 *.onnx 名均可被认出）。\n"
            "  2. 或用环境变量 SHIGUANG_DEPTH_MODEL 指向已有的 .onnx 文件。\n"
            "  3. 重启画布桥后重试「深度提取 / 图片转3D」。缺失时诚实报错，不用灰度冒充深度。"
        ) % video_depth.MODEL_URL,
        "sources": [_DEPTH_SOURCE],
        "license": "Apache-2.0",
    },
    "wan22_lightning_lora": {
        "label": "Wan2.2-Lightning 蒸馏 LoRA（6 步加速）",
        "filename": "*lightning*.safetensors",
        # T4：probe/guidance 统一走 video_gen 的单一真源（生成引擎 load 与下载中心同源）
        "probe": video_gen.find_lightning_lora,
        "place": "SHIGUANG_LORA_DIR 目录 / thirdparty/models/loras/（*lightning*.safetensors）",
        "guidance": video_gen.LIGHTNING_LORA_GUIDANCE,
        "sources": [_LORA_SOURCE],
        "license": "Apache-2.0",
    },
}


def tool_rows() -> List[Dict[str, Any]]:
    """产出「本地模型」视图的工具行（capability="tool"，family="tool"）。

    与生成模型族分列：不进 LOCAL_FAMILY_MODELS、不进 --pull 通道。
    sources 自带（仅 T0 已核链接），调用方须在 model_sources.attach_sources **之后**追加，
    否则会被按族查表的 attach_sources 覆盖成空。
    """
    rows: List[Dict[str, Any]] = []
    for tid, spec in TOOL_WEIGHTS.items():
        path = ""
        try:
            path = str(spec["probe"]() or "")
        except Exception:
            logger.debug("[tool_weights] 探测 %s 失败", tid, exc_info=True)
        size_gb = None
        if path:
            try:
                size_gb = round(os.path.getsize(path) / 1024**3, 2)
            except OSError:
                size_gb = None
        rows.append({
            "id": tid, "label": spec["label"], "capability": "tool",
            "family": "tool", "verification": "",
            "downloaded": bool(path), "size_gb": size_gb,
            "vram_gb": None, "ram_gb": None, "native_fps": 0, "modes": [],
            "dir": path, "note": spec["place"],
            "sources": list(spec.get("sources") or []),
        })
    return rows
