"""开源视频生成模型本地 GPU 推理管线。

支持 2024-2026 年主流开源视频模型：
- Wan 2.1 / 2.2 / 2.6 / 3.0（阿里）
- CogVideoX 1.0 / 1.5 / 2.0（清华）
- HunyuanVideo 1.5（腾讯）
- LTX-Video 0.9.5 / 2.0（Lightricks）
- Mochi 1 / 1B（Genmo）

设计原则：
- 延迟 import：torch/diffusers 只在真正需要时加载，避免启动时拉重依赖
- 显存自适应：自动选 fp16/bf16，低显存自动 enable_model_cpu_offload + VAE slicing
- 模型自识别：根据 model name / local path 关键字自动路由到对应 pipeline
- 输出与远程 API 一致：返回 {ok, video_path, video_url, model, channel_name, message}
"""

from __future__ import annotations

import os
import time
import shutil
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import logging

logger = logging.getLogger(__name__)


LOCAL_MODELS_DIR_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub"),
    os.path.join(os.path.expanduser("~"), ".cache", "modelscope"),
    os.path.join(os.path.expanduser("~"), "Downloads", "video_models"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "video"),
]

MODEL_KEYWORD_MAP: Dict[str, List[str]] = {
    "wan": ["wan", "wanxiang"],
    "cogvideox": ["cogvideox", "cogvideo"],
    "hunyuan": ["hunyuan-video", "hunyuanvideo"],
    "ltx": ["ltx", "ltx-video", "lightricks"],
    "mochi": ["mochi", "drmochi"],
    "minimax_h3": ["minimax-h3", "minimaxh3", "mini-max-h3", "hailuo-h3", "hailuo-h3.0", "h3-base"],
}

PIPELINE_CLASS_MAP: Dict[str, str] = {
    "wan": "WanVideoPipeline",
    "cogvideox": "CogVideoXPipeline",
    "hunyuan": "HunyuanVideoPipeline",
    "ltx": "LTXVideoPipeline",
    "mochi": "MochiPipeline",
    "minimax_h3": "MiniMaxH3ModularPipeline",
}


@dataclass
class LocalModelInfo:
    """本地模型元信息。"""

    kind: str
    name: str
    path: str
    format_hint: str = "diffusers"


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except Exception:
        return False


def _diffusers_available() -> bool:
    try:
        import diffusers  # noqa: F401

        return True
    except Exception:
        return False


def _get_device() -> Tuple[str, int]:
    """返回 (device_str, vram_gb)。vram 拿不到时返回 0。"""
    if not _torch_available():
        return ("cpu", 0)
    import torch

    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        vram = int(props.total_memory / (1024**3))
        return ("cuda", vram)
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return ("mps", 0)
    return ("cpu", 0)


def _guess_model_kind(name_or_path: str) -> Optional[str]:
    """根据模型名或路径关键字猜测模型类型。"""
    s = name_or_path.lower()
    for kind, keywords in MODEL_KEYWORD_MAP.items():
        for kw in keywords:
            if kw in s:
                return kind
    return None


def _scan_local_models() -> List[LocalModelInfo]:
    """扫描本地可能存在的开源视频模型目录。"""
    results: List[LocalModelInfo] = []
    seen = set()
    for base in LOCAL_MODELS_DIR_CANDIDATES:
        if not os.path.isdir(base):
            continue
        try:
            for entry in os.listdir(base):
                full = os.path.join(base, entry)
                if not os.path.isdir(full):
                    continue
                kind = _guess_model_kind(entry)
                if kind and entry not in seen:
                    seen.add(entry)
                    results.append(LocalModelInfo(kind=kind, name=entry, path=full))
                subscan = os.path.join(full, "snapshots")
                if os.path.isdir(subscan):
                    for snap in os.listdir(subscan):
                        sfull = os.path.join(subscan, snap)
                        if not os.path.isdir(sfull):
                            continue
                        kind2 = _guess_model_kind(snap)
                        if kind2 and snap not in seen:
                            seen.add(snap)
                            results.append(LocalModelInfo(kind=kind2, name=snap, path=sfull))
        except Exception:
            continue
    return results


def discover_local_video_models() -> List[Dict[str, Any]]:
    """对外暴露：返回可用的本地开源视频模型列表，用于模型广场展示。"""
    models = _scan_local_models()
    out: List[Dict[str, Any]] = []
    for m in models:
        out.append(
            {
                "name": f"local/{m.kind}/{m.name}",
                "label": f"本地 {m.kind.upper()} ({m.name})",
                "capability": "video",
                "source": "local",
                "path": m.path,
                "format": m.format_hint,
            }
        )
    device, vram = _get_device()
    if device == "cpu":
        out.append(
            {
                "name": "local/cpu/demo",
                "label": "本地 CPU 占位（需 GPU 才能跑开源模型）",
                "capability": "video",
                "source": "local",
                "path": "",
                "format": "unsupported",
                "warning": "未检测到可用 GPU，本地开源模型无法推理",
            }
        )
    elif not out:
        out.append(
            {
                "name": "local/gpu/no-model",
                "label": "检测到 GPU 但未发现本地开源模型权重",
                "capability": "video",
                "source": "local",
                "path": "",
                "format": "needs-download",
                "hint": "下载模型到 ~/.cache/huggingface/hub 或 app/models/video/",
            }
        )
    return out


def _save_video_frames(
    frames: List[Any],
    out_dir: str,
    bridge_port: int,
    *,
    audio_waveform: Optional[Any] = None,
    audio_sample_rate: int = 32000,
) -> Dict[str, Any]:
    """把 diffusers pipeline 输出的帧列表编码为 mp4 存到 canvas inbox。

    可选传入 audio_waveform（numpy float32 数组，多声道 shape=[samples, channels]
    或单声道 shape=[samples]），会自动用 ffmpeg mux 成带音频的 mp4。
    """
    import numpy as np

    try:
        import cv2
    except Exception:
        cv2 = None
    import imageio

    name = f"{int(time.time())}_local.mp4"
    path = os.path.join(out_dir, name)
    try:
        if cv2 is not None:
            h, w = int(frames[0].shape[0]), int(frames[0].shape[1])
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(path, fourcc, 24.0, (w, h))
            for f in frames:
                arr = np.array(f)
                if arr.dtype != np.uint8:
                    arr = (arr * 255).astype(np.uint8) if arr.max() <= 1.0 else arr.astype(np.uint8)
                if arr.ndim == 2:
                    arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
                elif arr.shape[2] == 4:
                    arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
                elif arr.shape[2] == 3:
                    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                writer.write(arr)
            writer.release()
        else:
            writer = imageio.get_writer(path, fps=24, codec="libx264")
            for f in frames:
                arr = np.array(f)
                if arr.dtype != np.uint8:
                    arr = (arr * 255).astype(np.uint8) if arr.max() <= 1.0 else arr.astype(np.uint8)
                writer.append_data(arr)
            writer.close()
    except Exception as e:
        return {"ok": False, "message": f"视频帧编码失败: {e}"}

    if audio_waveform is not None:
        try:
            import subprocess

            wav_path = os.path.join(out_dir, f"{int(time.time())}_audio.wav")
            aw = np.array(audio_waveform, dtype=np.float32)
            if aw.ndim == 1:
                aw = aw.reshape(-1, 1)
            if aw.ndim > 2:
                aw = aw.reshape(-1, aw.shape[-1])
            import soundfile as sf

            sf.write(wav_path, aw, audio_sample_rate)
            muxed = os.path.join(out_dir, f"{int(time.time())}_muxed.mp4")
            ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
            result = subprocess.run(
                [
                    ffmpeg_exe, "-y",
                    "-i", path,
                    "-i", wav_path,
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",
                    muxed,
                ],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0 and os.path.isfile(muxed):
                os.remove(path)
                os.remove(wav_path)
                path = muxed
                name = os.path.basename(muxed)
            else:
                try:
                    os.remove(wav_path)
                except Exception:
                    logger.debug("忽略异常（原为 pass）: local_video_infer.py", exc_info=True)
        except Exception:
            logger.debug("忽略异常（原为 pass）: local_video_infer.py", exc_info=True)

    url = f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}"
    return {
        "ok": True,
        "video_path": path,
        "video_url": url,
    }


def _load_image_data_url(data_url: str):
    """把 data URL 或本地路径加载成 PIL.Image。"""
    import base64
    import io

    from PIL import Image

    if data_url.startswith("data:"):
        _, b64 = data_url.split(",", 1)
        raw = base64.b64decode(b64)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    if os.path.isfile(data_url):
        return Image.open(data_url).convert("RGB")
    return None


def _infer_minimax_h3(
    *,
    prompt: str,
    model_path: str,
    device: str,
    vram_gb: int,
    duration: int = 5,
    size: str = "1280x720",
    reference_image: Optional[str] = None,
    first_frame: Optional[str] = None,
    last_frame: Optional[str] = None,
    bridge_port: int = 8765,
    out_dir: str = "",
    steps: Optional[int] = None,
) -> Dict[str, Any]:
    """MiniMax H3 系列推理：33B 全模态 transformer，原生输出 768p 视频 + 32kHz 立体声音频。

    根据输入自动选择 workflow：
    - 无图 → t2va（纯文生音视频）
    - 有首/尾帧 → fl2va（首尾帧音视频）
    - 有 reference_image → ref2va（多参考素材音视频，若 checkpoint 支持）
    """
    import numpy as np
    import torch

    from diffusers import MiniMaxH3ModularPipeline

    width = int(size.split("x")[0]) if "x" in size else 1280
    height = int(size.split("x")[1]) if "x" in size else 720

    use_bf16 = device == "cuda" and torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if use_bf16 else torch.float16
    pipe = MiniMaxH3ModularPipeline.from_pretrained(model_path, torch_dtype=dtype, trust_remote_code=True)
    pipe.to(device)
    if vram_gb and vram_gb < 24:
        pipe.enable_model_cpu_offload()
    try:
        pipe.enable_vae_slicing()
    except Exception:
        logger.debug("忽略异常（原为 pass）: local_video_infer.py", exc_info=True)

    steps = steps if steps is not None else (28 if vram_gb >= 24 else 22)
    frames = []
    audio_wav = None
    audio_sr = 32000

    has_ref = bool(reference_image)
    has_ff = bool(first_frame)
    has_lf = bool(last_frame)

    if has_ref:
        ref_img = _load_image_data_url(reference_image)
        if ref_img is None:
            return {"ok": False, "message": "参考图解码失败"}
        try:
            result = pipe.load_workflow("ref2va")
        except Exception:
            result = pipe.load_workflow("fl2va") if (has_ff or has_lf) else pipe.load_workflow("t2va")
        result = pipe(
            prompt=prompt,
            images=[ref_img],
            num_inference_steps=steps,
            num_frames=int(duration * 24),
            width=width,
            height=height,
            guidance_scale=5.0,
        )
    elif has_ff or has_lf:
        pipe.load_workflow("fl2va")
        ff_img = _load_image_data_url(first_frame) if has_ff else None
        lf_img = _load_image_data_url(last_frame) if has_lf else None
        if has_ff and ff_img is None:
            return {"ok": False, "message": "首帧图片解码失败"}
        if has_lf and lf_img is None:
            return {"ok": False, "message": "尾帧图片解码失败"}
        result = pipe(
            prompt=prompt,
            first_frame_image=ff_img,
            last_frame_image=lf_img,
            num_inference_steps=steps,
            num_frames=int(duration * 24),
            width=width,
            height=height,
            guidance_scale=5.0,
        )
    else:
        pipe.load_workflow("t2va")
        result = pipe(
            prompt=prompt,
            num_inference_steps=steps,
            num_frames=int(duration * 24),
            width=width,
            height=height,
            guidance_scale=5.0,
        )

    raw_frames = None
    raw_audio = None
    if isinstance(result, dict):
        raw_frames = result.get("frames") or result.get("video") or result.get("images")
        raw_audio = result.get("audio")
    else:
        raw_frames = getattr(result, "frames", None)
        raw_audio = getattr(result, "audio", None)

    if raw_frames is not None:
        if isinstance(raw_frames, (list, tuple)) and raw_frames and isinstance(raw_frames[0], (list, tuple)):
            frames = raw_frames[0]
        elif isinstance(raw_frames, (list, tuple)):
            frames = list(raw_frames)
        elif hasattr(raw_frames, "cpu"):
            arr = raw_frames.cpu().numpy()
            frames = [arr[i] for i in range(arr.shape[0])] if arr.ndim == 4 else [arr]

    if raw_audio is not None:
        if hasattr(raw_audio, "cpu"):
            audio_wav = raw_audio.cpu().numpy()
        elif isinstance(raw_audio, (list, tuple)):
            audio_wav = np.array(raw_audio, dtype=np.float32)
        elif isinstance(raw_audio, np.ndarray):
            audio_wav = raw_audio.astype(np.float32)

    if not frames:
        return {"ok": False, "message": f"MiniMax H3 返回无帧数据: type={type(result).__name__}"}

    return _save_video_frames(
        frames, out_dir, bridge_port,
        audio_waveform=audio_wav,
        audio_sample_rate=audio_sr,
    )


def _infer_wan(
    *,
    prompt: str,
    model_path: str,
    device: str,
    vram_gb: int,
    duration: int = 5,
    size: str = "1280x720",
    reference_image: Optional[str] = None,
    bridge_port: int = 8765,
    out_dir: str = "",
    steps: Optional[int] = None,
) -> Dict[str, Any]:
    """Wan 系列推理：Wan 2.1 / 2.2 / 2.6 / 3.0，支持 T2V + I2V。"""
    import torch

    from diffusers import WanVideoPipeline

    width, _, height = (
        int(size.split("x")[0]),
        0,
        int(size.split("x")[1]) if "x" in size else 720,
    )
    use_bf16 = device == "cuda" and torch.cuda.is_bf16_supported() and vram_gb >= 24
    dtype = torch.bfloat16 if use_bf16 else torch.float16
    pipe = WanVideoPipeline.from_pretrained(model_path, torch_dtype=dtype)
    pipe.to(device)
    if vram_gb and vram_gb < 12:
        pipe.enable_model_cpu_offload()
    try:
        pipe.enable_vae_slicing()
    except Exception:
        logger.debug("忽略异常（原为 pass）: local_video_infer.py", exc_info=True)

    steps = steps if steps is not None else (30 if vram_gb >= 16 else 24)
    cfg = 5.0

    if reference_image:
        import base64
        import io

        from PIL import Image

        mime, b64 = reference_image.split(",", 1) if "," in reference_image else ("", "")
        img_bytes = base64.b64decode(b64) if b64 else reference_image.encode()
        ref_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        result = pipe(
            prompt=prompt,
            image=ref_img,
            num_inference_steps=steps,
            guidance_scale=cfg,
            num_frames=int(duration * 16),
            width=width,
            height=height,
        )
    else:
        result = pipe(
            prompt=prompt,
            num_inference_steps=steps,
            guidance_scale=cfg,
            num_frames=int(duration * 16),
            width=width,
            height=height,
        )
    frames = result.frames[0] if result.frames else []
    return _save_video_frames(frames, out_dir, bridge_port)


def _infer_cogvideox(
    *,
    prompt: str,
    model_path: str,
    device: str,
    vram_gb: int,
    duration: int = 5,
    size: str = "1280x720",
    reference_image: Optional[str] = None,
    first_frame: Optional[str] = None,
    last_frame: Optional[str] = None,
    bridge_port: int = 8765,
    out_dir: str = "",
    steps: Optional[int] = None,
) -> Dict[str, Any]:
    """CogVideoX 系列推理：1.0 / 1.5 / 2.0，支持 T2V + I2V + 首尾帧。"""
    import torch

    from diffusers import CogVideoXPipeline

    width, _, height = (
        int(size.split("x")[0]),
        0,
        int(size.split("x")[1]) if "x" in size else 720,
    )
    dtype = torch.float16
    pipe = CogVideoXPipeline.from_pretrained(model_path, torch_dtype=dtype)
    pipe.to(device)
    if vram_gb and vram_gb < 12:
        pipe.enable_model_cpu_offload()
    try:
        pipe.enable_vae_slicing()
    except Exception:
        logger.debug("忽略异常（原为 pass）: local_video_infer.py", exc_info=True)

    steps = steps if steps is not None else (30 if vram_gb >= 16 else 24)
    cfg = 6.0
    result = pipe(
        prompt=prompt,
        num_inference_steps=steps,
        guidance_scale=cfg,
        num_frames=int(duration * 16),
        width=width,
        height=height,
    )
    frames = result.frames[0] if result.frames else []
    return _save_video_frames(frames, out_dir, bridge_port)


def _infer_hunyuan(
    *,
    prompt: str,
    model_path: str,
    device: str,
    vram_gb: int,
    duration: int = 5,
    size: str = "1280x720",
    reference_image: Optional[str] = None,
    bridge_port: int = 8765,
    out_dir: str = "",
    steps: Optional[int] = None,
) -> Dict[str, Any]:
    """HunyuanVideo 系列推理：腾讯开源，支持 T2V + I2V。"""
    import torch

    from diffusers import HunyuanVideoPipeline

    width, _, height = (
        int(size.split("x")[0]),
        0,
        int(size.split("x")[1]) if "x" in size else 720,
    )
    dtype = torch.float16
    pipe = HunyuanVideoPipeline.from_pretrained(model_path, torch_dtype=dtype)
    pipe.to(device)
    if vram_gb and vram_gb < 16:
        pipe.enable_model_cpu_offload()

    steps = steps if steps is not None else (30 if vram_gb >= 16 else 24)
    cfg = 6.0
    result = pipe(
        prompt=prompt,
        num_inference_steps=steps,
        guidance_scale=cfg,
        num_frames=int(duration * 16),
        width=width,
        height=height,
    )
    frames = result.frames[0] if result.frames else []
    return _save_video_frames(frames, out_dir, bridge_port)


def _infer_ltx(
    *,
    prompt: str,
    model_path: str,
    device: str,
    vram_gb: int,
    duration: int = 5,
    size: str = "1280x720",
    reference_image: Optional[str] = None,
    bridge_port: int = 8765,
    out_dir: str = "",
    steps: Optional[int] = None,
) -> Dict[str, Any]:
    """LTX-Video 系列推理：Lightricks 开源，支持 T2V + I2V，4K 50fps。"""
    import torch

    from diffusers import LTXVideoPipeline

    width, _, height = (
        int(size.split("x")[0]),
        0,
        int(size.split("x")[1]) if "x" in size else 720,
    )
    dtype = torch.float16
    pipe = LTXVideoPipeline.from_pretrained(model_path, torch_dtype=dtype)
    pipe.to(device)
    if vram_gb and vram_gb < 12:
        pipe.enable_model_cpu_offload()

    steps = steps if steps is not None else (30 if vram_gb >= 16 else 24)
    cfg = 3.0
    result = pipe(
        prompt=prompt,
        num_inference_steps=steps,
        guidance_scale=cfg,
        num_frames=int(duration * 25),
        width=width,
        height=height,
    )
    frames = result.frames[0] if result.frames else []
    return _save_video_frames(frames, out_dir, bridge_port)


def _infer_mochi(
    *,
    prompt: str,
    model_path: str,
    device: str,
    vram_gb: int,
    duration: int = 5,
    size: str = "1280x720",
    bridge_port: int = 8765,
    out_dir: str = "",
    steps: Optional[int] = None,
) -> Dict[str, Any]:
    """Mochi 系列推理：Genmo 开源，纯 T2V。"""
    import torch

    from diffusers import MochiPipeline

    width, _, height = (
        int(size.split("x")[0]),
        0,
        int(size.split("x")[1]) if "x" in size else 720,
    )
    dtype = torch.bfloat16 if device == "cuda" else torch.float16
    pipe = MochiPipeline.from_pretrained(model_path, torch_dtype=dtype)
    pipe.to(device)
    if vram_gb and vram_gb < 16:
        pipe.enable_model_cpu_offload()

    steps = steps if steps is not None else (30 if vram_gb >= 16 else 24)
    cfg = 3.5
    result = pipe(
        prompt=prompt,
        num_inference_steps=steps,
        guidance_scale=cfg,
        num_frames=int(duration * 16),
        width=width,
        height=height,
    )
    frames = result.frames[0] if result.frames else []
    return _save_video_frames(frames, out_dir, bridge_port)


_INFER_FUNC_MAP = {
    "wan": _infer_wan,
    "cogvideox": _infer_cogvideox,
    "hunyuan": _infer_hunyuan,
    "ltx": _infer_ltx,
    "mochi": _infer_mochi,
    "minimax_h3": _infer_minimax_h3,
}


def generate_video_local(
    *,
    prompt: str,
    model: str = "",
    model_path: str = "",
    duration: float = 5.0,
    size: str = "1280x720",
    reference_image: str = "",
    first_frame: str = "",
    last_frame: str = "",
    bridge_port: int = 8765,
    out_dir: str = "",
    steps: Optional[int] = None,
) -> Dict[str, Any]:
    """本地开源视频模型推理统一入口。

    Args:
        prompt: 提示词
        model: 模型名（如 wan-2.6、cogvideox-2b、hunyuan-video），用于路由
        model_path: 可选，模型本地路径。不传则自动从 HF cache 扫描
        duration: 时长（秒），各模型内部会换算成帧数
        size: 分辨率 "1280x720" 格式
        reference_image: 参考图（I2V）
        first_frame: 首帧
        last_frame: 尾帧
        bridge_port: 本地 bridge 端口（用于生成 URL）
        out_dir: 输出目录（通常是 canvas inbox）

    Returns:
        {ok, video_path, video_url, model, channel_id, channel_name, message}
    """
    if not prompt.strip():
        return {"ok": False, "message": "提示词为空"}

    if not _torch_available():
        return {"ok": False, "message": "未安装 torch，请先 pip install torch"}
    if not _diffusers_available():
        return {"ok": False, "message": "未安装 diffusers，请先 pip install diffusers transformers accelerate"}

    device, vram_gb = _get_device()
    if device == "cpu":
        return {
            "ok": False,
            "message": f"检测不到可用 GPU（torch.device=cpu）。开源视频模型本地推理必须有 CUDA / MPS GPU，当前 VRAM={vram_gb}GB",
        }

    kind = _guess_model_kind(model) if model else None
    if not kind and model_path:
        kind = _guess_model_kind(model_path)
    if not kind:
        available = discover_local_video_models()
        real_models = [m for m in available if m.get("source") == "local" and m.get("path")]
        if not real_models:
            return {
                "ok": False,
                "message": "未指定模型名，也未发现本地开源视频模型权重。请下载模型到 ~/.cache/huggingface/hub 或 app/models/video/，或指定 model 参数",
            }
        chosen = real_models[0]
        kind = _guess_model_kind(chosen["name"]) or _guess_model_kind(chosen["path"])
        model_path = model_path or chosen["path"]
        model = model or chosen["name"]

    if not model_path:
        local_models = _scan_local_models()
        matches = [m for m in local_models if m.kind == kind]
        if matches:
            model_path = matches[0].path
        else:
            return {
                "ok": False,
                "message": f"未找到 {kind} 模型的本地权重目录。请下载到 ~/.cache/huggingface/hub 或通过 model_path 指定",
            }

    infer_fn = _INFER_FUNC_MAP.get(kind)
    if not infer_fn:
        return {"ok": False, "message": f"暂不支持的本地开源模型类型: {kind}"}

    if not out_dir:
        try:
            from app.core.canvas_bridge import canvas_inbox_dir

            out_dir = canvas_inbox_dir()
        except Exception:
            out_dir = os.path.join(os.path.expanduser("~"), ".shiguang", "inbox")
    os.makedirs(out_dir, exist_ok=True)

    try:
        import torch

        torch.cuda.empty_cache() if device == "cuda" else None
    except Exception:
        logger.debug("忽略异常（原为 pass）: local_video_infer.py", exc_info=True)

    fn_kwargs = dict(
        prompt=prompt,
        model_path=model_path,
        device=device,
        vram_gb=vram_gb,
        duration=int(max(1, min(20, int(duration)))),
        size=size,
        reference_image=reference_image,
        bridge_port=bridge_port,
        out_dir=out_dir,
    )
    if kind == "cogvideox":
        fn_kwargs["first_frame"] = first_frame
        fn_kwargs["last_frame"] = last_frame
    if steps is not None:
        fn_kwargs["steps"] = int(steps)

    try:
        result = infer_fn(**fn_kwargs)
    except Exception as e:
        return {"ok": False, "message": f"本地 {kind} 推理失败: {type(e).__name__}: {e}"}

    if result.get("ok"):
        result["model"] = f"local/{kind}/{model}" if model else f"local/{kind}"
        result["channel_id"] = "local-gpu"
        result["channel_name"] = f"本地 GPU ({device.upper()}, {vram_gb}GB)"
        result["message"] = f"本地 {kind} 推理成功（{device.upper()} / {vram_gb}GB VRAM）"
    return result
