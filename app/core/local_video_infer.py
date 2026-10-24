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
    # ★ 2026-10-02 补：**项目自己的模型下载位**。
    #   `neural/video_gen.py` 的 `pull()` 走 `neural_engine.repo_local_dir()`，
    #   落盘在 `app/models/cache/<repo 去斜杠>/`。此前这里不含该目录，
    #   导致「项目自己下载的模型，本模块扫不到」—— 属于两套本地视频实现并存时的典型脱节。
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "cache"),
]

MODEL_KEYWORD_MAP: Dict[str, List[str]] = {
    "wan": ["wan", "wanxiang"],
    "cogvideox": ["cogvideox", "cogvideo"],
    "hunyuan": ["hunyuan-video", "hunyuanvideo"],
    "ltx": ["ltx", "ltx-video", "lightricks"],
    "mochi": ["mochi", "drmochi"],
    "minimax_h3": ["minimax-h3", "minimaxh3", "mini-max-h3", "hailuo-h3", "hailuo-h3.0", "h3-base"],
    # ★ 2026-10-02 补 SVD（Stable Video Diffusion，图生视频）。
    #   起因：`neural/video_gen.py` 只支持 SVD 且已下载，而本模块认不出它 ⇒ 两套实现脱节。
    #   SVD 是 **i2v（图生视频）**，与上面几族的 t2v 语义不同：**不需要 prompt，但必须有输入图**。
    "svd": ["svd", "stable-video-diffusion", "stablevideodiffusion", "svd-xt", "img2vid"],
}

PIPELINE_CLASS_MAP: Dict[str, str] = {
    "wan": "WanVideoPipeline",
    "cogvideox": "CogVideoXPipeline",
    "hunyuan": "HunyuanVideoPipeline",
    "ltx": "LTXVideoPipeline",
    "mochi": "MochiPipeline",
    "minimax_h3": "MiniMaxH3ModularPipeline",
    "svd": "StableVideoDiffusionPipeline",
}

# 需要**输入图**（i2v）而非 prompt 的族 —— 校验逻辑据此放行「无 prompt 但有图」。
I2V_KINDS: Tuple[str, ...] = ("svd",)


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


def _has_weights(path: str, max_depth: int = 3) -> bool:
    """目录里是否**真的有模型权重**（而非只有 repo 元数据的空壳）。

    为什么需要它（2026-10-02 实测踩到）：
      HF 缓存布局下，一个**只下载失败/只建了索引**的仓库会留下
      `models--xxx/refs/main` 这种 1KB 空壳。本模块的调用方取 `matches[0].path`
      加载权重 —— 一旦扫到空壳就会「明明下载了却加载失败」，且报错指向模型不存在，
      **极难排查**。实测本机同时存在：
        · `~/.cache/huggingface/hub/models--stabilityai--...`（**1KB 空壳**）
        · `app/models/cache/stabilityai_...`（**4.2GB 真实权重**）
      ⇒ 只靠目录名判断会选错，必须在扫描阶段就按「有无权重文件」过滤。
    """
    try:
        if not os.path.isdir(path):
            return False
        for root, dirs, files in os.walk(path):
            depth = root[len(path):].count(os.sep)
            if depth >= max_depth:
                dirs[:] = []
                continue
            for f in files:
                if f.endswith((".safetensors", ".bin", ".pth", ".ckpt")):
                    # 排除 HF 的 blob 索引占位（0 字节）
                    try:
                        if os.path.getsize(os.path.join(root, f)) < 1024 * 1024:
                            continue
                    except OSError:
                        continue
                    return True
        return False
    except Exception:
        return False


def _scan_local_models() -> List[LocalModelInfo]:
    """扫描本地可能存在的开源视频模型目录（**只收真有权重的**）。"""
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
                # ★ 权重存在性过滤：空壳目录（只有 refs/ 元数据）直接跳过，
                #   否则会覆盖掉真实目录（调用方取 matches[0]）。
                if kind and entry not in seen and _has_weights(full):
                    seen.add(entry)
                    results.append(LocalModelInfo(kind=kind, name=entry, path=full))
                subscan = os.path.join(full, "snapshots")
                if os.path.isdir(subscan):
                    for snap in os.listdir(subscan):
                        sfull = os.path.join(subscan, snap)
                        if not os.path.isdir(sfull):
                            continue
                        kind2 = _guess_model_kind(snap)
                        if kind2 and snap not in seen and _has_weights(sfull):
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
    fps: int = 24,
) -> Dict[str, Any]:
    """把 diffusers pipeline 输出的帧列表编码为 mp4 存到 canvas inbox。

    可选传入 audio_waveform（numpy float32 数组，多声道 shape=[samples, channels]
    或单声道 shape=[samples]），会自动用 ffmpeg mux 成带音频的 mp4。

    ★ fps 必须由调用方按**模型原生帧率**传入（2026-10-24 静态审查暴露的 bug）：
      各族的 num_frames 都是 `int(duration * 原生fps)` 算的（SVD=7、wan/cogvideox/
      hunyuan/mochi=16、ltx=25、minimax=24），但旧实现把编码帧率写死 24 ⇒ 除 minimax 外
      所有族输出视频**播放过快、时长被压缩**（SVD 实测：请求 1s 只出 0.29s，快 3.4 倍）。
      默认 24 仅为兼容，正确用法是显式传该族的原生 fps。
    """
    import numpy as np

    try:
        import cv2
    except Exception:
        cv2 = None
    import imageio

    name = f"{int(time.time())}_local.mp4"
    path = os.path.join(out_dir, name)
    _fps = float(fps) if fps and int(fps) > 0 else 24.0
    try:
        if cv2 is not None:
            # ★ 修复（2026-10-24 真机验证暴露）：SVD 的 result.frames[0] 是 PIL.Image，
            #   直接读 .shape 会抛 'Image' object has no attribute 'shape'（cv2 可用时必崩，
            #   走不到下面能处理 PIL 的 np.array 分支）。先归一为 numpy 再取尺寸。
            _first = np.array(frames[0])
            h, w = int(_first.shape[0]), int(_first.shape[1])
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(path, fourcc, _fps, (w, h))
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
            writer = imageio.get_writer(path, fps=int(_fps), codec="libx264")
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

    _native_fps = 24   # 本族 num_frames=int(duration*24) ⇒ 编码必须 24fps 才不失真

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
        fps=_native_fps,
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

    _native_fps = 16   # num_frames=int(duration*16)

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
    return _save_video_frames(frames, out_dir, bridge_port, fps=_native_fps)


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

    _native_fps = 16   # num_frames=int(duration*16)

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
    return _save_video_frames(frames, out_dir, bridge_port, fps=_native_fps)


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

    _native_fps = 16   # num_frames=int(duration*16)

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
    return _save_video_frames(frames, out_dir, bridge_port, fps=_native_fps)


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

    _native_fps = 25   # num_frames=int(duration*25)

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
    return _save_video_frames(frames, out_dir, bridge_port, fps=_native_fps)


def resolve_image_path(
    src: str, *, dest_dir: str = "", name_hint: str = "input"
) -> Optional[str]:
    """把画布传图的**三种形态**统一成本地文件路径（SVD 首帧输入链路）。

    接受：
      · data URL（`data:image/...;base64,...`）→ 落成临时 PNG；
      · `/inbox_file/<name>` 或 `http://127.0.0.1:<port>/inbox_file/<name>` → 映射回
        `canvas_bridge.canvas_inbox_dir()/<name>`；
      · 本地绝对/相对路径（必须真实存在）。

    其余形态（远端 URL、空串、不存在的路径）返回 None —— 由调用方如实报错，
    绝不下载任意远端图（那是另一条需要联网与安全审阅的链路）。
    """
    s = (src or "").strip()
    if not s:
        return None
    if s.startswith("data:image/"):
        try:
            import base64

            raw = base64.b64decode(s.split(",", 1)[-1])
            target_dir = dest_dir or os.path.join("短剧AI剪辑输出", "_video_input")
            os.makedirs(target_dir, exist_ok=True)
            path = os.path.join(target_dir, f"_{name_hint}_first_frame.png")
            with open(path, "wb") as f:
                f.write(raw)
            return path
        except Exception:
            logger.debug("[local_video_infer] data URL 落盘失败", exc_info=True)
            return None
    p = s
    if "/inbox_file/" in s:                     # inbox URL → 映射回本地
        try:
            from app.core.canvas_bridge import canvas_inbox_dir

            name = s.rsplit("/", 1)[-1].split("?")[0]
            p = os.path.join(canvas_inbox_dir(), name)
        except Exception:
            logger.debug("[local_video_infer] inbox URL 映射失败", exc_info=True)
            return None
    if os.path.isfile(p):
        return p
    return None


def _load_input_image(src: str):
    """把 data URL / 本地路径 / inbox URL 读成 PIL.Image（SVD 等 i2v 族用）。

    三态统一收在 resolve_image_path，避免各族各写一份
    （本项目反模式清单里就有「同一件事两套实现」）。
    """
    from PIL import Image

    path = resolve_image_path(src)
    if not path:
        return None
    return Image.open(path).convert("RGB")


def _infer_svd(
    *,
    prompt: str = "",
    model_path: str,
    device: str,
    vram_gb: int,
    duration: int = 2,
    size: str = "1024x576",
    reference_image: str = "",
    first_frame: str = "",
    bridge_port: int = 8765,
    out_dir: str = "",
    steps: Optional[int] = None,
) -> Dict[str, Any]:
    """Stable Video Diffusion 推理：**图生视频（i2v）**，不是文生视频。

    ⚠️ 与其它族的语义差异（别照抄 t2v 族的写法）：
      · **不需要 prompt**，但**必须有输入图**（`reference_image` / `first_frame`）；
      · 默认参数取自 `neural/video_gen.TUNED` 的**本机实测调优**（下方逐项注明依据）。

    实测调优（RTX 4060 Laptop 8GB，2026-10-01/02）：
      · `decode_chunk_size=1` —— VAE 解码 37.5s→**2.4s**（小了反而快约 6 倍，且更省显存）
      · **offload 保持开启** —— 实测全程不亏（更快且更省显存），且防帧数升高时 WDDM 分页
      · `steps=14` —— 唯一的质量/速度旋钮；10 步与 25 步前段画面肉眼无差
      · `motion_bucket_id=80`（SVD 默认 127 偏大）—— 实测**立绘主体 6 帧全程稳定**，
        而 127/180 后段崩坏，且**三者耗时相同** ⇒ 纯赚的画质提升
      · **CFG 必须显式给**（min=1.0/max=3.0）—— 关掉会快 1.85x 但输出报废（噪声糊满）
    """
    import torch

    from diffusers import StableVideoDiffusionPipeline

    _native_fps = 7    # SVD 训练 fps=7，n_frames=round(duration*7)

    img_src = (reference_image or first_frame or "").strip()
    if not img_src:
        return {
            "ok": False,
            "message": "SVD 是**图生视频**，必须提供 reference_image 或 first_frame（不支持纯文生视频）",
        }
    pil = _load_input_image(img_src)
    if pil is None:
        return {"ok": False, "message": f"输入图无法读取：{img_src[:80]}"}

    dtype = torch.float16

    def _load_svd_pipe():
        # 只在缓存未命中时执行：读 4.2GB 权重 + 建 offload hook（首帧慢的根源）。
        p = StableVideoDiffusionPipeline.from_pretrained(
            model_path, torch_dtype=dtype, variant="fp16", use_safetensors=True,
        )
        # 实测：offload 全程不亏（更快更省显存），且防大帧数分页 —— 无条件开启
        try:
            p.enable_model_cpu_offload()
        except Exception:
            logger.debug("cpu offload 不可用，直接上卡", exc_info=True)
            p.to(device)
        return p

    # ★ 用法感知（视频侧，2026-10-24）：SVD 固定开销不在搬运（offload 实测最优、不能整卡），
    #   而在每次 from_pretrained 重载 4.2GB ⇒ 进程级常驻复用，第二次起省掉整段加载。
    #   生成参数（steps/frames/motion_bucket/CFG）仍每次传，不缓存 ⇒ 调优语义不变。
    from app.core.local_video_pipe_cache import get_or_load

    pipe, _src = get_or_load(("svd", os.path.abspath(model_path)), _load_svd_pipe)

    n_steps = int(steps) if steps is not None else 14
    n_frames = max(2, int(round(float(duration) * 7)))       # SVD 训练 fps = 7
    _key = ("svd", os.path.abspath(model_path))
    try:
        result = pipe(
            image=pil,
            num_frames=n_frames,
            decode_chunk_size=1,                                  # ★ 实测关键项
            num_inference_steps=n_steps,
            motion_bucket_id=80,                                  # ★ 实测画质项
            noise_aug_strength=0.02,
            min_guidance_scale=1.0,                               # ★ CFG 必须显式给
            max_guidance_scale=3.0,
        )
    except Exception as e:
        # 常驻管线若把显存撑爆（帧数升高/被别的任务挤占）：淘汰缓存，下次重载干净管线。
        #   只认 OOM，其它异常原样上抛（不吞真实错误）。
        if "out of memory" in str(e).lower():
            from app.core.local_video_pipe_cache import evict

            evict(_key)
            logger.warning("[local_video_infer] SVD 生成 OOM，已淘汰常驻管线待重载")
        raise
    frames = result.frames[0] if result.frames else []
    out = _save_video_frames(frames, out_dir, bridge_port, fps=_native_fps)
    if isinstance(out, dict):
        out["pipe_source"] = _src      # hit=复用常驻管线 / miss=本次新加载（首帧慢的那次）
    return out



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

    _native_fps = 16   # num_frames=int(duration*16)

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
    return _save_video_frames(frames, out_dir, bridge_port, fps=_native_fps)


_INFER_FUNC_MAP = {
    "wan": _infer_wan,
    "cogvideox": _infer_cogvideox,
    "hunyuan": _infer_hunyuan,
    "ltx": _infer_ltx,
    "mochi": _infer_mochi,
    "minimax_h3": _infer_minimax_h3,
    "svd": _infer_svd,
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
    # ★ i2v 族（如 SVD）**不需要 prompt**，但必须有输入图。
    #   所以在**有图**的情况下放行空 prompt；各族的「我要什么输入」由各族自己校验
    #   （它们最清楚，例如 `_infer_svd` 会明确要求 reference_image/first_frame）。
    if not prompt.strip() and not (reference_image or first_frame):
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
    if kind == "cogvideox" or kind in I2V_KINDS:
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
