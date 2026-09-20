# -*- coding: utf-8 -*-
"""画布桥 AIGC 层：模型广场渠道配置、生图/生视频/生音频/生音乐、分镜拉片。

从 canvas_bridge.py 拆分而来（大文件治理）。自研导演台 /host/* 暴露的所有 AI
能力集中于此。画布 HTTP 服务（_BridgeHandler / CanvasBridgeServer）仍留在
canvas_bridge.py，并通过 re-export 引用本模块。

端口冻结约束（stage3d-core）仍以 canvas_bridge.py 为准：本模块 DEFAULT_PORT 仅作
默认值镜像，不得单独改动端口 18765。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import json
import logging
import math
import os
import re
import shutil
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.canvas_bridge")

# 取消感知的 urlopen：任务线程内会把响应登记到取消令牌，取消即可中断在途请求。
# 非任务线程（旧同步路径）行为与 urllib.request.urlopen 完全一致。
try:
    from app.core.canvas_gen_jobs import open_url as _open_url_cancellable
except ImportError:  # 兼容扁平导入（scripts/ 直跑）
    try:
        from canvas_gen_jobs import open_url as _open_url_cancellable  # type: ignore
    except ImportError:  # 兜底：退回原生 urlopen
        import urllib.request as _urllib_request

        def _open_url_cancellable(req: Any, timeout: float, **kw: Any) -> Any:
            return _urllib_request.urlopen(req, timeout=timeout, **kw)

# 与 canvas_bridge.DEFAULT_PORT 保持一致（stage3d-core 冻结：端口 18765 不得更改）
DEFAULT_PORT = 18765


def _canvas_inbox_dir() -> str:
    """画布收件目录（惰性取 canvas_bridge.canvas_inbox_dir，拆模块后避免循环导入）。"""
    from app.core.canvas_bridge import canvas_inbox_dir

    return canvas_inbox_dir()


VIDEO_KEYWORDS = (
    # ── 2024-2025 元老 ──
    "seedance", "video", "sora", "veo", "kling", "wan", "hailuo",
    # ── 2026 头部新模型 ──
    "flux-3", "flux3", "black-forest-labs", "bfl",
    "runway", "gen-4", "gen4", "gen-4.5", "gen4.5", "runwayml",
    "minimax", "h3", "vidu", "shengshu", "mini-max",
    "happyhorse", "happy-horse", "happy_horse", "alibaba", "aliyun-wan",
    "grok-imagine", "aurora-video", "xai-video",
    "ltx", "ltx-video", "lightricks",
    "pika", "pika-labs",
    "luma", "dream-machine", "labs-ray", "ray-3", "ray3",
    # ── 开源本地部署 ──
    "cogvideox", "cogvideo", "hunyuan-video", "hunyuanvideo",
    "mochi", "drmochi", "ltx-2", "ltx2", "wan2", "wan3",
)
AUDIO_KEYWORDS = (
    "audio", "tts", "speech", "voice", "music", "sound",
    # ── 2026 新增 ──
    "suno", "udio", "chirp", "elevenlabs", "fish-audio",
    "fishaudio", "gpt-s4o", "s4o-audio", "flux-audio",
)
IMAGE_KEYWORDS = (
    "seedream",
    "gpt-image",
    "codex-gpt-image",
    "image",
    "dall-e",
    "dalle",
    "imagen",
    "flux",
    "flux-1", "flux1",
    "sdxl",
    "stable-diffusion",
    "sd3", "sd3.5",
    "midjourney",
    "kolors",
    "cogview",
    "hunyuan-image",
    "seedream-4", "seedream4",
    "grok-image",
    "aurora-image",
)


# ───────────────────── 生成能力常量（收敛散落的能力魔法字符串） ─────────────────────
CAPABILITY_TEXT = "text"
CAPABILITY_IMAGE = "image"
CAPABILITY_VIDEO = "video"
CAPABILITY_AUDIO = "audio"
CAPABILITY_MUSIC = "music"
ALL_CAPABILITIES = (
    CAPABILITY_TEXT,
    CAPABILITY_IMAGE,
    CAPABILITY_VIDEO,
    CAPABILITY_AUDIO,
    CAPABILITY_MUSIC,
)


def guess_capability(name: str) -> str:
    """按模型名关键词猜测生成能力（text/image/video/audio）。

    仅作「模型名 → 能力」的启发式兜底；AIGC 目录里显式 capability（含 music）优先于
    本函数返回值（见 :func:`build_host_ai_config_patch` 的 ``_merge_models``）。"""
    value = (name or "").lower()
    if any(k in value for k in VIDEO_KEYWORDS):
        return CAPABILITY_VIDEO
    if any(k in value for k in AUDIO_KEYWORDS):
        return CAPABILITY_AUDIO
    if any(k in value for k in IMAGE_KEYWORDS):
        return CAPABILITY_IMAGE
    return CAPABILITY_TEXT


class LocalGenerationBackend(ABC):
    """本地生成后端统一抽象。

    统一「本地推理」后端的能力声明、可用性探测与生成分派，取代 generate_* 里各自
    硬编码的本地回退。约束：
      - 统一的是「能力声明 + 可用性 + 分派」；各后端返回结构保留原约定
        （视频 {ok,...} / 音频 {success,...}），调用方读取字段不变，避免破坏行为。
      - comfy_provider（ComfyUI 工作流引擎，走 /host/comfy/*）与 neural_engine
        （剪辑特效 ONNX/Torch 推理，走特效插件）属不同域，不纳入本抽象。
    """

    backend_id: str = ""
    capabilities: Tuple[str, ...] = ()

    @abstractmethod
    def is_available(self) -> bool:
        """后端是否可用（依赖可导入、权重/引擎可探测等）。"""

    @abstractmethod
    def generate(self, capability: str, **params: Any) -> Dict[str, Any]:
        """按能力执行本地生成，返回 {ok|success, ...}（字段约定见各实现）。"""


class LocalVideoInferBackend(LocalGenerationBackend):
    """本地开源视频模型推理后端（local_video_infer.generate_video_local）。"""

    backend_id = "local_video_infer"
    capabilities = (CAPABILITY_VIDEO,)

    @staticmethod
    def _import_fn() -> Optional[Any]:
        try:
            from app.core.local_video_infer import generate_video_local
        except ImportError:
            try:
                from core.local_video_infer import generate_video_local  # type: ignore
            except ImportError:
                return None
        return generate_video_local

    def is_available(self) -> bool:
        return self._import_fn() is not None

    def generate(self, capability: str, **params: Any) -> Dict[str, Any]:
        fn = self._import_fn()
        if fn is None:
            return {
                "ok": False,
                "message": "本地推理模块 local_video_infer.py 不可用，请检查文件是否存在",
            }
        return fn(**params)


class LocalVoiceBackend(LocalGenerationBackend):
    """本地 TTS 后端（voice_generator.VoiceGenerator）。音乐生成本地后端暂缺（诚实缺口）。"""

    backend_id = "local_voice"
    capabilities = (CAPABILITY_AUDIO,)

    def is_available(self) -> bool:
        try:
            from app.core.voice_generator import VoiceGenerator
        except ImportError:
            try:
                from core.voice_generator import VoiceGenerator  # type: ignore
            except ImportError:
                return False
        return True

    def generate(self, capability: str, **params: Any) -> Dict[str, Any]:
        text = str(params.get("text") or params.get("prompt") or "")
        output_path = str(params.get("output_path") or "")
        try:
            from app.core.voice_generator import VoiceGenerator
        except ImportError:
            from core.voice_generator import VoiceGenerator  # type: ignore
        # guard=True：长台词自动**分段合成**（治「长片段后面发音错 / 与字幕不符」，见 app/core/ai/tts_guard.py）；
        # 短句（≤ guard_max_chars）不分段、走原路径，零影响。
        return VoiceGenerator().generate_audio(
            text, output_path=output_path, guard=bool(params.get("guard", True)))


class GenerationRegistry:
    """生成能力 → 本地后端注册表。

    统一「能力 → 可用本地后端」查找；云端渠道解析仍走 :func:`_resolve_aigc_channel`，
    两者一本地一云端，共同构成画布生成的统一路由（收敛原散装硬编码回退）。"""

    def __init__(self) -> None:
        self._backends: Dict[str, LocalGenerationBackend] = {}

    def register(self, backend: LocalGenerationBackend) -> None:
        """登记一个本地后端（按 backend_id 覆盖，惰性、不做重 import）。"""
        self._backends[backend.backend_id] = backend

    def resolve(self, capability: str) -> List[LocalGenerationBackend]:
        """返回该能力下所有「可用」的本地后端（按登记顺序）。"""
        return [
            b
            for b in self._backends.values()
            if capability in b.capabilities and b.is_available()
        ]

    def backend_ids(self) -> List[str]:
        """列出已登记后端 id（调试/UI 展示用）。"""
        return list(self._backends.keys())


# 全局本地生成后端注册表（实例化即登记内建本地后端；适配器 __init__ 均无重 import）
local_generation_registry = GenerationRegistry()
local_generation_registry.register(LocalVideoInferBackend())
local_generation_registry.register(LocalVoiceBackend())


# ───────────────────── 参数翻译层（语义层 → 各后端实现层） ─────────────────────
# 与 vendor/shiguang-canvas/src/novice/types.ts 的 QualityTier / MotionLevel 对齐，
# 作为后端「唯一语义真值」。前端只回传语义档位字符串（quality = draft/standard/fine/cinema，
# motion = low/medium/high），具体的 steps / size / fps 等实现层参数由这里统一翻译，
# 杜绝各后端、各渠道各写一套映射。
QUALITY_TIERS = ("draft", "standard", "fine", "cinema")
MOTION_LEVELS = ("low", "medium", "high")

# 语义画质档位 → 通用实现层参数（镜像 types.ts QUALITY_PRESET 的语义契约；
# steps/upscale 等字段供支持的后端选用，size 为 provider 无关的通用分辨率映射）
QUALITY_PRESET: Dict[str, Dict[str, Any]] = {
    "draft": {"steps": 12, "upscale": False, "face_restore": False, "frame_interpolate": False},
    "standard": {"steps": 22, "upscale": False, "face_restore": True, "frame_interpolate": False},
    "fine": {"steps": 30, "upscale": True, "face_restore": True, "frame_interpolate": True},
    "cinema": {"steps": 45, "upscale": True, "face_restore": True, "frame_interpolate": True},
}

# 语义运动幅度 → 强度（0-100，镜像 types.ts MOTION_LEVELS 的 value）
MOTION_PRESET: Dict[str, int] = {"low": 20, "medium": 55, "high": 90}

# 语义画质档位 → 默认分辨率（provider 无关，所有图片/视频生成 API 通用）
_QUALITY_SIZE_IMAGE: Dict[str, str] = {
    "draft": "1024x576",
    "standard": "1024x576",
    "fine": "1280x720",
    "cinema": "1920x1080",
}
_QUALITY_SIZE_VIDEO: Dict[str, str] = {
    "draft": "960x540",
    "standard": "1280x720",
    "fine": "1280x720",
    "cinema": "1920x1080",
}


def translate_quality(quality: str, capability: str = CAPABILITY_IMAGE) -> Dict[str, Any]:
    """把语义画质档位翻译成该能力下的「通用实现层参数」。

    返回：
      - size：该档位默认分辨率（provider 无关）
      - steps/upscale/face_restore/frame_interpolate：语义契约字段，供支持的后端选用。
    未知档位退回 standard，保证不抛错、不越级降低质量。"""
    tier = quality if quality in QUALITY_PRESET else "standard"
    size_map = _QUALITY_SIZE_VIDEO if capability == CAPABILITY_VIDEO else _QUALITY_SIZE_IMAGE
    translated = dict(QUALITY_PRESET[tier])
    translated["size"] = size_map[tier]
    return translated


def translate_motion(motion: str) -> int:
    """把语义运动幅度（low/medium/high）翻译成 0-100 强度；未知值退回 medium。"""
    return MOTION_PRESET.get(motion, MOTION_PRESET["medium"])


def _json_request(
    method: str,
    url: str,
    api_key: str,
    body: Optional[Dict[str, Any]] = None,
    timeout: float = 60,
) -> Any:
    """带 Bearer 鉴权的 JSON 请求（收敛 generate_video/music 里重复的 _json_req）。"""
    import urllib.request

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with _open_url_cancellable(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def build_host_ai_config_patch() -> Dict[str, Any]:
    """从模型广场组装画布 channels（id 前缀 shiguang-），含 AIGC 生图/生视频。"""
    channels: List[Dict[str, Any]] = []
    try:
        from app.modules.lego.model_config import (
            PROVIDERS,
            AIGC_MODELS,
            AIGC_CATALOG_PLACEHOLDER,
            AIGC_KEY_PRIORITY,
        )
    except ImportError:
        try:
            from modules.lego.model_config import (  # type: ignore
                PROVIDERS,
                AIGC_MODELS,
                AIGC_CATALOG_PLACEHOLDER,
                AIGC_KEY_PRIORITY,
            )
        except ImportError:
            PROVIDERS = {}
            AIGC_MODELS = {}
            AIGC_CATALOG_PLACEHOLDER = {}
            AIGC_KEY_PRIORITY = ()

    def _merge_models(
        text_names: List[str], aigc_entries: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        by_name: Dict[str, Dict[str, str]] = {}
        for n in text_names:
            if not n:
                continue
            by_name[n] = {"name": n, "capability": guess_capability(n)}
        for ent in aigc_entries or []:
            name = str(ent.get("name") or "")
            if not name:
                continue
            by_name[name] = {
                "name": name,
                "capability": str(ent.get("capability") or guess_capability(name)),
            }
        return list(by_name.values())

    # Ollama（默认渠道；模型列表尽力探测，失败不阻塞）
    ollama_models: List[Dict[str, str]] = [{"name": "llama3.2", "capability": "text"}]
    try:
        import socket

        with socket.create_connection(("127.0.0.1", 11434), timeout=0.4):
            pass
        try:
            from app.modules.lego.ollama_client import ollama_client
        except ImportError:
            try:
                from modules.lego.ollama_client import ollama_client  # type: ignore
            except ImportError:
                ollama_client = None  # type: ignore
        if ollama_client is not None:
            try:
                listed = ollama_client.list_models() or []
                names = []
                for m in listed:
                    name = getattr(m, "name", None) or str(m)
                    if name:
                        names.append({"name": name, "capability": guess_capability(name)})
                if names:
                    ollama_models = names
            except Exception as e:
                logger.debug("ollama list failed: %s", e)
    except OSError:
        logger.debug("ollama client init failed", exc_info=True)
    channels.append(
        {
            "id": "shiguang-ollama",
            "name": "拾光·Ollama",
            "baseUrl": "http://127.0.0.1:11434/v1",
            "apiKey": "ollama",
            "apiFormat": "openai",
            "models": ollama_models,
        }
    )

    # Cloud providers with keys (+ AIGC extras)
    try:
        from app.modules.lego.cloud_api import cloud_api_service
    except ImportError:
        try:
            from modules.lego.cloud_api import cloud_api_service  # type: ignore
        except ImportError:
            cloud_api_service = None  # type: ignore

    configured: Dict[str, Dict[str, Any]] = {}
    if cloud_api_service is not None:
        for pid, meta in (PROVIDERS or {}).items():
            if pid == "ollama" or not isinstance(meta, dict):
                continue
            try:
                if not cloud_api_service.is_configured(pid):
                    continue
            except Exception as exc:
                logger.warning("查询渠道是否已配置失败, pid=%s: %s", pid, exc, exc_info=True)
                continue
            cfg = cloud_api_service.get_config(pid)
            api_key = (cfg.api_key if cfg else "") or ""
            if not api_key:
                continue
            base = (cfg.base_url if cfg and cfg.base_url else "") or str(meta.get("url") or "")
            if not base:
                continue
            model_names = list(meta.get("models") or [])
            if cfg and cfg.model and cfg.model not in model_names:
                model_names.insert(0, cfg.model)
            aigc = list((AIGC_MODELS or {}).get(pid) or [])
            models = _merge_models(model_names, aigc)
            if not models:
                models = [{"name": "default", "capability": "text"}]
            ch = {
                "id": f"shiguang-{pid}",
                "name": f"拾光·{meta.get('name') or pid}",
                "baseUrl": base.rstrip("/"),
                "apiKey": api_key,
                "apiFormat": "ark" if "ark.cn-beijing" in base else "openai",
                "models": models,
            }
            channels.append(ch)
            configured[pid] = ch

    # 专用 AIGC 渠道：优先复用已配置 Key；否则挂目录占位（画布内提示补 Key，不作为默认可生成渠道）
    aigc_channel = None
    for pid in AIGC_KEY_PRIORITY or ():
        if pid in configured:
            src = configured[pid]
            aigc_channel = {
                "id": "shiguang-aigc",
                "name": f"拾光·AIGC（{PROVIDERS.get(pid, {}).get('name') or pid}）",
                "baseUrl": src["baseUrl"],
                "apiKey": src["apiKey"],
                "apiFormat": src.get("apiFormat") or "openai",
                "models": list((AIGC_MODELS or {}).get(pid) or src.get("models") or []),
            }
            break
    # 回退：任意已配置渠道若挂有 image/video 目录，也可作 AIGC
    if aigc_channel is None:
        for pid, src in configured.items():
            aigc_ents = list((AIGC_MODELS or {}).get(pid) or [])
            if any(str(e.get("capability")) in ("image", "video", "audio") for e in aigc_ents):
                aigc_channel = {
                    "id": "shiguang-aigc",
                    "name": f"拾光·AIGC（{PROVIDERS.get(pid, {}).get('name') or pid}）",
                    "baseUrl": src["baseUrl"],
                    "apiKey": src["apiKey"],
                    "apiFormat": src.get("apiFormat") or "openai",
                    "models": aigc_ents or list(src.get("models") or []),
                }
                break
    placeholder_only = False
    if aigc_channel is None and AIGC_CATALOG_PLACEHOLDER:
        aigc_channel = dict(AIGC_CATALOG_PLACEHOLDER)
        aigc_channel["id"] = "shiguang-aigc"
        aigc_channel["name"] = "拾光·AIGC（请在模型管理填硅基流动/OpenAI 等 Key）"
        aigc_channel["needsKey"] = True
        placeholder_only = True
    if aigc_channel:
        channels.append(aigc_channel)

    # 画布默认选中模型（channelId::model）——仅对有 Key 的渠道设默认，避免空 Key 假默认
    defaults: Dict[str, str] = {}
    prefer_ch = None
    if aigc_channel and (aigc_channel.get("apiKey") or "").strip() and not placeholder_only:
        prefer_ch = aigc_channel
    else:
        for c in channels:
            if c.get("id") == "shiguang-ollama":
                continue
            if not (c.get("apiKey") or "").strip():
                continue
            if any((m.get("capability") == "image") for m in (c.get("models") or [])):
                prefer_ch = c
                break
        if prefer_ch is None:
            for c in channels:
                if (c.get("apiKey") or "").strip() and c.get("id") != "shiguang-ollama":
                    prefer_ch = c
                    break
    if prefer_ch:
        cid = prefer_ch["id"]
        for m in prefer_ch.get("models") or []:
            cap = m.get("capability") or "text"
            key = {"image": "imageModel", "video": "videoModel", "text": "textModel", "audio": "audioModel"}.get(
                cap
            )
            if key and key not in defaults:
                defaults[key] = f"{cid}::{m['name']}"
        if "imageModel" in defaults:
            defaults["model"] = defaults["imageModel"]
        elif "textModel" in defaults:
            defaults["model"] = defaults["textModel"]

    warnings: List[str] = []
    keyed = [c for c in channels if (c.get("apiKey") or "").strip() and c.get("id") != "shiguang-ollama"]
    has_img = any(
        (c.get("apiKey") or "").strip()
        and any(m.get("capability") == "image" for m in (c.get("models") or []))
        for c in channels
    )
    has_vid = any(
        (c.get("apiKey") or "").strip()
        and any(m.get("capability") == "video" for m in (c.get("models") or []))
        for c in channels
    )
    has_aud = any(
        (c.get("apiKey") or "").strip()
        and any(m.get("capability") == "audio" for m in (c.get("models") or []))
        for c in channels
    )
    if not keyed:
        warnings.append("模型管理尚未配置任何云端 Key，请到「模型管理」填写后点同步模型池。")
    elif not has_img:
        names = "、".join(
            str((PROVIDERS or {}).get(pid, {}).get("name") or pid) for pid in configured
        ) or "已配置渠道"
        warnings.append(
            f"当前仅有对话渠道（{names}），无生图 Key。"
            "请在模型管理为「硅基流动 / OpenAI / 通义」等填写 Key，再同步模型池。"
        )
    if keyed and not has_vid:
        warnings.append("暂无生视频 Key；视频节点会诚实失败，不影响生图/拉片。")

    active_provider = ""
    active_label = ""
    try:
        from app.modules.lego.model_config import load_active_provider, PROVIDERS as _P

        active_provider = load_active_provider() or ""
        active_label = str((_P.get(active_provider) or {}).get("name") or active_provider)
    except Exception:
        try:
            from modules.lego.model_config import load_active_provider, PROVIDERS as _P  # type: ignore

            active_provider = load_active_provider() or ""
            active_label = str((_P.get(active_provider) or {}).get("name") or active_provider)
        except Exception:
            logger.debug("load_active_provider failed", exc_info=True)

    return {
        "channels": channels,
        "defaults": defaults,
        "source": "shiguang_model_square",
        "aigc": True,
        "warnings": warnings,
        "configured_providers": list(configured.keys()),
        "active_provider": active_provider,
        "active_provider_label": active_label,
        "has_image_models": has_img,
        "has_video_models": has_vid,
        "has_audio_models": has_aud,
    }


def _data_url_to_b64(data_url: str) -> tuple:
    """返回 (mime, raw_b64) ；失败 ("", "")。"""
    import base64 as _b64
    import re

    s = (data_url or "").strip()
    if not s:
        return "", ""
    if s.startswith("data:") and "," in s:
        header, payload = s.split(",", 1)
        m = re.match(r"data:([^;]+)", header)
        mime = m.group(1) if m else "image/png"
        # 去掉空白
        payload = "".join(payload.split())
        try:
            _b64.b64decode(payload, validate=False)
        except Exception:
            return "", ""
        return mime, payload
    # 已是裸 b64
    try:
        _b64.b64decode(s, validate=False)
        return "image/png", "".join(s.split())
    except Exception:
        return "", ""


def generate_image_openai_compatible(
    *,
    prompt: str,
    model: str = "",
    size: str = "1024x576",
    channel_id: str = "",
    reference_image: str = "",
    strength: float = 0.65,
    quality: str = "standard",
) -> Dict[str, Any]:
    """用模型广场同步的 AIGC 渠道调用 OpenAI-compatible ``/images/generations``。

    供自研导演台「生成选中节点」走宿主代理（避免浏览器 CORS）。
    若提供 ``reference_image``（data URL / b64），优先尝试图生图；失败则降级文生图。
    """
    import base64
    import urllib.error
    import urllib.request

    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "message": "提示词为空"}

    # 语义画质档位 → 实现层参数（size 作为 provider 无关兜底；steps 供支持的后端选用）
    quality_params = translate_quality(quality, CAPABILITY_IMAGE)
    size = size or (quality_params.get("size") or "1024x576")

    patch = build_host_ai_config_patch()
    channels = list(patch.get("channels") or [])
    defaults = dict(patch.get("defaults") or {})

    ch = None
    if channel_id:
        ch = next((c for c in channels if c.get("id") == channel_id), None)
    if ch is None:
        ch = next((c for c in channels if c.get("id") == "shiguang-aigc"), None)
    if ch is None:
        # 任一带 image 模型且有 Key 的渠道
        for c in channels:
            if not (c.get("apiKey") or "").strip():
                continue
            if any((m.get("capability") == "image") for m in (c.get("models") or [])):
                ch = c
                break
    if ch is None or not (ch.get("apiKey") or "").strip():
        return {
            "ok": False,
            "message": "没有可用的 AIGC 生图渠道。请到「模型管理」填写硅基流动/OpenAI 等 Key，并在画布点「同步模型池」。",
            "fallback_placeholder": True,
        }

    if not model:
        # defaults: "shiguang-aigc::FLUX..."
        raw = str(defaults.get("imageModel") or defaults.get("model") or "")
        if "::" in raw:
            model = raw.split("::", 1)[-1]
        if not model:
            for m in ch.get("models") or []:
                if m.get("capability") == "image":
                    model = str(m.get("name") or "")
                    break
    if not model:
        return {"ok": False, "message": "渠道内没有生图模型", "fallback_placeholder": True}

    base = str(ch.get("baseUrl") or "").rstrip("/")
    if not base:
        return {"ok": False, "message": "渠道缺少 baseUrl"}

    def _post(body: Dict[str, Any], endpoint: str = "/images/generations") -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            base + endpoint,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ch['apiKey']}",
            },
        )
        try:
            with _open_url_cancellable(req, timeout=120) as resp:
                return {
                    "ok": True,
                    "payload": json.loads(resp.read().decode("utf-8", errors="replace")),
                }
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            return {
                "ok": False,
                "message": f"生图 API HTTP {e.code}: {err_body or e.reason}",
            }
        except Exception as e:
            return {"ok": False, "message": f"生图请求失败: {e}"}

    def _parse_payload(payload: Any, mode: str) -> Dict[str, Any]:
        items = payload.get("data") if isinstance(payload, dict) else None
        if not items and isinstance(payload, dict):
            items = payload.get("images")
        if not isinstance(items, list) or not items:
            return {
                "ok": False,
                "message": f"生图返回无法解析: {str(payload)[:200]}",
                "model": model,
                "fallback_placeholder": True,
            }
        first = items[0] if isinstance(items[0], dict) else {}
        b64 = first.get("b64_json") or first.get("base64")
        img_url = first.get("url")
        if b64:
            return {
                "ok": True,
                "image_data_url": f"data:image/png;base64,{b64}",
                "model": model,
                "channel_id": ch.get("id"),
                "channel_name": ch.get("name"),
                "mode": mode,
                "message": f"已生成（{mode} · {ch.get('name')} / {model}）",
            }
        if img_url:
            try:
                with _open_url_cancellable(img_url, timeout=60) as r:
                    raw_img = r.read()
                mime = "image/png"
                ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
                if ctype.startswith("image/"):
                    mime = ctype
                data_url = f"data:{mime};base64,{base64.b64encode(raw_img).decode('ascii')}"
                return {
                    "ok": True,
                    "image_data_url": data_url,
                    "image_url": img_url,
                    "model": model,
                    "channel_id": ch.get("id"),
                    "channel_name": ch.get("name"),
                    "mode": mode,
                    "message": f"已生成（{mode} · {ch.get('name')} / {model}）",
                }
            except Exception as e:
                return {
                    "ok": True,
                    "image_url": img_url,
                    "model": model,
                    "channel_id": ch.get("id"),
                    "mode": mode,
                    "message": f"已生成 URL（本地下载失败可仍用外链）: {e}",
                }
        return {"ok": False, "message": "返回中无图像数据", "fallback_placeholder": True}

    mime, ref_b64 = _data_url_to_b64(reference_image)
    used_img2img = False
    img2img_err = ""
    if ref_b64:
        # 硅基 / 兼容渠道常见字段：image + image_size；部分用 images 数组
        strength_clamped = max(0.1, min(0.95, float(strength or 0.65)))
        img2_body: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
            "image": f"data:{mime};base64,{ref_b64}",
            "strength": strength_clamped,
        }
        if "siliconflow" in base.lower():
            img2_body["image_size"] = size or "1024x576"
            img2_body["num_inference_steps"] = int(quality_params.get("steps") or 22)
        else:
            img2_body["size"] = size or "1024x576"
        r2 = _post(img2_body)
        if r2.get("ok"):
            parsed = _parse_payload(r2.get("payload"), "img2img")
            if parsed.get("ok"):
                used_img2img = True
                return parsed
            img2img_err = str(parsed.get("message") or "img2img 解析失败")
        else:
            img2img_err = str(r2.get("message") or "img2img 失败")

    body: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size or "1024x576",
        "response_format": "b64_json",
    }
    if "siliconflow" in base.lower():
        body["image_size"] = size or "1024x576"
        body["num_inference_steps"] = int(quality_params.get("steps") or 22)
        body.pop("size", None)

    r = _post(body)
    if not r.get("ok"):
        return {
            "ok": False,
            "message": (
                f"{r.get('message')}"
                + (f"（img2img 已降级：{img2img_err}）" if img2img_err else "")
            ),
            "model": model,
            "channel_id": ch.get("id"),
            "fallback_placeholder": True,
        }
    parsed = _parse_payload(r.get("payload"), "txt2img")
    if img2img_err and parsed.get("ok"):
        parsed["message"] = (
            f"{parsed.get('message')}；首帧 img2img 不可用已降级文生图（{img2img_err[:120]}）"
        )
        parsed["img2img_fallback"] = True
    elif used_img2img:
        parsed["mode"] = "img2img"

    # 本地增强后处理：按画质档位做人脸修复 + 超分
    if parsed.get("ok") and parsed.get("image_data_url") and (
        quality_params.get("face_restore") or quality_params.get("upscale")
    ):
        try:
            from app.core.generation_postprocess import apply_image_postprocess

            enhanced = apply_image_postprocess(parsed["image_data_url"], quality_params)
            if enhanced and enhanced != parsed["image_data_url"]:
                parsed["image_data_url"] = enhanced
                parsed["postprocessed"] = True
        except Exception as exc:
            logger.debug(f"生图后处理跳过: {exc}")
    return parsed


def inpaint_via_host(
    *,
    prompt: str,
    image: str,
    mask: str,
    model: str = "",
    channel_id: str = "",
    size: str = "1024x576",
) -> Dict[str, Any]:
    """局部重绘：优先 OpenAI-compatible ``/images/edits``；否则用 mask 提示 + img2img。

    不支持时诚实失败（不返回假图）。
    """
    import base64
    import urllib.error
    import urllib.request

    prompt = (prompt or "").strip() or "inpaint the masked region"
    if not image or not mask:
        return {"ok": False, "message": "inpaint 需要原图与蒙版"}

    # 先尝试 edits 端点
    patch = build_host_ai_config_patch()
    channels = list(patch.get("channels") or [])
    ch = None
    if channel_id:
        ch = next((c for c in channels if c.get("id") == channel_id), None)
    if ch is None:
        ch = next((c for c in channels if c.get("id") == "shiguang-aigc"), None)
    if ch is None:
        for c in channels:
            if (c.get("apiKey") or "").strip() and any(
                (m.get("capability") == "image") for m in (c.get("models") or [])
            ):
                ch = c
                break
    if ch is None or not (ch.get("apiKey") or "").strip():
        return {
            "ok": False,
            "message": "没有可用生图渠道，无法 inpaint。请到模型管理填写 AIGC Key 后同步。",
        }

    if not model:
        for m in ch.get("models") or []:
            if m.get("capability") == "image":
                model = str(m.get("name") or "")
                break
    base = str(ch.get("baseUrl") or "").rstrip("/")
    mime_i, b64_i = _data_url_to_b64(image)
    mime_m, b64_m = _data_url_to_b64(mask)
    if not b64_i or not b64_m:
        return {"ok": False, "message": "原图或蒙版不是有效 data URL"}

    # 1) /images/edits（部分兼容站支持）
    try:
        boundary = "----ShiguangInpaintBoundary"
        parts = []

        def _add(name: str, value: bytes, filename: str | None = None, ctype: str | None = None):
            parts.append(f"--{boundary}\r\n".encode())
            if filename:
                parts.append(
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
                )
                parts.append(f"Content-Type: {ctype or 'application/octet-stream'}\r\n\r\n".encode())
                parts.append(value)
                parts.append(b"\r\n")
            else:
                parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
                parts.append(value)
                parts.append(b"\r\n")

        _add("model", model.encode("utf-8"))
        _add("prompt", prompt.encode("utf-8"))
        _add("n", b"1")
        _add("size", (size or "1024x576").encode("utf-8"))
        _add("response_format", b"b64_json")
        _add("image", base64.b64decode(b64_i), "image.png", mime_i or "image/png")
        _add("mask", base64.b64decode(b64_m), "mask.png", mime_m or "image/png")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        req = urllib.request.Request(
            base + "/images/edits",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {ch['apiKey']}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        with _open_url_cancellable(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        items = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(items, list) and items:
            first = items[0] if isinstance(items[0], dict) else {}
            b64 = first.get("b64_json") or first.get("base64")
            if b64:
                return {
                    "ok": True,
                    "image_data_url": f"data:image/png;base64,{b64}",
                    "model": model,
                    "mode": "inpaint-edits",
                    "message": f"局部重绘成功（edits · {ch.get('name')} / {model}）",
                }
    except Exception as e:
        edits_err = str(e)
    else:
        edits_err = "edits 返回无图像"

    # 2) 降级：把蒙版意图写入提示 + img2img
    strengthened = (
        f"{prompt}\n\n"
        "Inpaint only the white-masked regions; keep unmasked areas unchanged. "
        "High fidelity to the original composition."
    )
    fallback = generate_image_openai_compatible(
        prompt=strengthened,
        model=model,
        size=size,
        channel_id=str(ch.get("id") or ""),
        reference_image=image,
        strength=0.55,
    )
    if fallback.get("ok"):
        fallback["mode"] = "inpaint-img2img-fallback"
        fallback["message"] = (
            f"{fallback.get('message')}（/images/edits 不可用：{edits_err[:120]}，已用 img2img 降级）"
        )
        return fallback
    return {
        "ok": False,
        "message": (
            f"局部重绘失败。edits: {edits_err[:160]}；"
            f"img2img: {fallback.get('message')}"
        ),
    }


def _resolve_aigc_channel(
    *,
    channel_id: str = "",
    capability: str = "image",
    default_model_key: str = "imageModel",
) -> tuple[Optional[Dict[str, Any]], str, Dict[str, Any]]:
    """解析带 Key 的 AIGC 渠道与默认模型名。"""
    patch = build_host_ai_config_patch()
    channels = list(patch.get("channels") or [])
    defaults = dict(patch.get("defaults") or {})

    ch: Optional[Dict[str, Any]] = None
    if channel_id:
        ch = next((c for c in channels if c.get("id") == channel_id), None)
    if ch is None:
        ch = next((c for c in channels if c.get("id") == "shiguang-aigc"), None)
    if ch is None:
        for c in channels:
            if not (c.get("apiKey") or "").strip():
                continue
            if any((m.get("capability") == capability) for m in (c.get("models") or [])):
                ch = c
                break
    if ch is None or not (ch.get("apiKey") or "").strip():
        return None, "", patch

    model = ""
    raw = str(defaults.get(default_model_key) or "")
    if "::" in raw:
        model = raw.split("::", 1)[-1]
    return ch, model, patch


def generate_audio_via_host(
    *,
    prompt: str,
    model: str = "",
    channel_id: str = "",
    voice: str = "",
    bridge_port: int = DEFAULT_PORT,
) -> Dict[str, Any]:
    """生音频：优先模型广场云端 TTS（OpenAI-compatible /audio/speech）；失败降级本地 VoiceGenerator。"""
    import time
    import urllib.error
    import urllib.request

    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "message": "音频提示词为空"}

    ch, default_model, _patch = _resolve_aigc_channel(
        channel_id=channel_id,
        capability="audio",
        default_model_key="audioModel",
    )
    if not model and default_model:
        model = default_model
    if ch and not model:
        for m in ch.get("models") or []:
            if m.get("capability") == "audio":
                model = str(m.get("name") or "")
                break

    cloud_err = ""
    if ch and model and (ch.get("apiKey") or "").strip():
        base = str(ch.get("baseUrl") or "").rstrip("/")
        api_key = str(ch.get("apiKey") or "")
        tts_voice = (voice or "alloy").strip() or "alloy"
        body = {
            "model": model,
            "input": prompt,
            "voice": tts_voice,
            "response_format": "mp3",
        }
        speech_url = f"{base}/audio/speech" if base.endswith("/v1") else f"{base}/v1/audio/speech"
        if base:
            try:
                req = urllib.request.Request(
                    speech_url,
                    data=json.dumps(body).encode("utf-8"),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                )
                with _open_url_cancellable(req, timeout=120) as resp:
                    raw = resp.read()
                    ctype = resp.headers.get("Content-Type") or ""
                if raw:
                    ext = ".wav" if "wav" in ctype else ".mp3"
                    name = f"tts_{int(time.time())}_{abs(hash(prompt)) % 100000}{ext}"
                    dest = os.path.join(_canvas_inbox_dir(), name)
                    with open(dest, "wb") as f:
                        f.write(raw)
                    audio_url = f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}"
                    return {
                        "ok": True,
                        "audio_url": audio_url,
                        "audio_path": dest,
                        "model": model,
                        "message": f"TTS 已生成（{ch.get('name') or '云端'} · {model}）",
                    }
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:200]
                except Exception:
                    logger.debug("read HTTP error body failed", exc_info=True)
                cloud_err = f"HTTP {e.code} {detail}".strip()
            except Exception as e:
                cloud_err = str(e)[:200]

    try:
        name = f"tts_{int(time.time())}_{abs(hash(prompt)) % 100000}.wav"
        dest = os.path.join(_canvas_inbox_dir(), name)
        local_backends = local_generation_registry.resolve(CAPABILITY_AUDIO)
        if not local_backends:
            raise RuntimeError("本地 VoiceGenerator 不可用")
        result = local_backends[0].generate(CAPABILITY_AUDIO, text=prompt, output_path=dest)
        if result.get("success") and os.path.isfile(dest):
            url = f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}"
            msg = "TTS 已生成（本地 VoiceGenerator · edge-tts/gTTS 可用时更佳）"
            if cloud_err:
                msg += f"；云端不可用：{cloud_err[:120]}"
            return {
                "ok": True,
                "audio_url": url,
                "audio_path": dest,
                "message": msg,
                "fallback_local": True,
            }
        err = str(result.get("error") or "TTS 生成失败")
    except Exception as e:
        err = str(e)

    hint = ""
    if cloud_err:
        hint = f"云端：{cloud_err[:120]}；"
    elif not ch or not model:
        hint = "请在模型管理配置 OpenAI 等 TTS Key 并同步模型池；"
    return {
        "ok": False,
        "message": (
            f"宿主 TTS 失败：{hint}本地：{err[:160]}。"
            "可上传音频到音频节点，或检查模型管理中的 gpt-4o-mini-tts / speech-01。"
        ),
    }


def agent_chat_proxy(message: str) -> Dict[str, Any]:
    """把自然语言转发到外部 Node canvas-agent（:17371，@basketikun/canvas-agent）。

    ⚠️ DEPRECATED：这是旧 MCP 路径。自研画布请看
    ``project_agent_host.project_agent_chat()`` 和端点 ``/host/project-agent/chat``。
    本函数保留仅为兼容 character_management_module 的「连接 Agent」按钮。
    """
    import urllib.error
    import urllib.request

    message = (message or "").strip()
    if not message:
        return {"ok": False, "message": "消息为空"}
    try:
        from app.core.canvas_agent_runtime import get_canvas_agent_runtime
    except ImportError:
        from core.canvas_agent_runtime import get_canvas_agent_runtime  # type: ignore

    rt = get_canvas_agent_runtime()
    if not rt.is_listening():
        return {"ok": False, "message": "Agent 未启动，请先点「连接 Agent」"}
    base = (rt.url or "http://127.0.0.1:17371").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if rt.token:
        headers["Authorization"] = f"Bearer {rt.token}"
        headers["X-Canvas-Agent-Token"] = rt.token
    bodies = [
        ("/v1/chat/completions", {"model": "canvas-agent", "messages": [{"role": "user", "content": message}]}),
        ("/chat", {"message": message}),
        ("/api/chat", {"message": message, "content": message}),
    ]
    errors = []
    for path, body in bodies:
        try:
            req = urllib.request.Request(
                base + path,
                data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers=headers,
            )
            with _open_url_cancellable(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except Exception:
                return {"ok": True, "reply": raw[:2000], "message": f"已代理 {path}"}
            # OpenAI style
            choices = data.get("choices") if isinstance(data, dict) else None
            if isinstance(choices, list) and choices:
                msg = (choices[0].get("message") or {}).get("content") or choices[0].get("text")
                if msg:
                    return {"ok": True, "reply": str(msg), "message": "Agent 已回复"}
            reply = None
            if isinstance(data, dict):
                reply = data.get("reply") or data.get("message") or data.get("content")
            if reply:
                return {"ok": True, "reply": str(reply), "message": "Agent 已回复"}
            return {"ok": True, "reply": raw[:2000], "message": f"已代理 {path}（原始响应）"}
        except Exception as e:
            errors.append(f"{path}: {e}")
    return {
        "ok": False,
        "message": (
            "canvas-agent 未提供可用聊天 HTTP（多为 MCP 工具通道）。"
            f"请用面板 / 指令操作画布，或接 Codex MCP。详情：{'; '.join(errors)[:240]}"
        ),
    }


def _normalize_reference_video(
    reference_video: str,
    bridge_port: int = DEFAULT_PORT,
) -> Dict[str, Any]:
    """把参考视频统一为 inbox 引用：data URL 落盘；inbox URL / 本地路径校验后复用。

    返回 {ok, url, path} 或 {ok: False, message}。motion-ref 模式 A/B 的公共前置。
    """
    value = (reference_video or "").strip()
    if not value:
        return {"ok": False, "message": "参考视频为空"}

    inbox = _canvas_inbox_dir()
    try:
        os.makedirs(inbox, exist_ok=True)
    except Exception as e:
        logger.warning("[motion-ref] inbox 目录创建失败: %s", e)
        return {"ok": False, "message": f"收件目录不可用: {e}"}

    # 形态 1：data URL（小视频直传）→ 落盘 inbox
    if value.startswith("data:"):
        try:
            import base64

            header, b64 = value.split(",", 1)
            raw = base64.b64decode(b64)
        except Exception:
            return {"ok": False, "message": "参考视频 data URL 解码失败"}
        ext = ".mp4"
        m = re.search(r"data:video/([\w-]+)", header)
        if m and m.group(1).lower() not in ("quicktime", "x-msvideo"):
            ext = f".{m.group(1).lower()}"
        name = f"{int(time.time())}_refvideo{ext}"
        path = os.path.join(inbox, name)
        try:
            with open(path, "wb") as f:
                f.write(raw)
        except Exception as e:
            logger.warning("[motion-ref] 参考视频落盘失败: %s", e)
            return {"ok": False, "message": f"参考视频落盘失败: {e}"}
        if os.path.getsize(path) < 1024:
            return {"ok": False, "message": "参考视频文件过小，可能不是有效视频"}
        return {"ok": True, "url": f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}", "path": path}

    # 形态 2：画布 inbox URL（upload-asset 上传后的标准引用）→ 校验后透传
    if value.startswith("http://") or value.startswith("https://"):
        name = value.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        path = os.path.join(inbox, name)
        if os.path.isfile(path):
            return {"ok": True, "url": value, "path": path}
        # URL 不指向本地 inbox（外链）：保留 URL，路径留空
        return {"ok": True, "url": value, "path": ""}

    # 形态 3：本地路径 → 复制进 inbox 保证可播放 URL
    if os.path.isfile(value):
        name = os.path.basename(value)
        target = os.path.join(inbox, name)
        try:
            if os.path.abspath(value) != os.path.abspath(target):
                shutil.copyfile(value, target)
        except Exception as e:
            logger.warning("[motion-ref] 参考视频复制进 inbox 失败: %s", e)
            return {"ok": False, "message": f"参考视频复制失败: {e}"}
        return {"ok": True, "url": f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}", "path": target}

    return {"ok": False, "message": f"参考视频文件不存在: {value}"}


def _probe_video_motion_support(*, channel_id: str = "", model: str = "") -> Dict[str, Any]:
    """探测渠道/模型是否支持视频运动参考（capability == video_motion）。

    当前模型池尚无该能力标记 —— 诚实返回不可用；待接入 motion-ref 模型（可灵/即梦进阶款
    或 Wan-Fun 类）并在 model_config 标记 capability=video_motion 后自动点亮。
    """
    try:
        patch = build_host_ai_config_patch()
    except Exception:
        logger.debug("[motion-ref] 模型池读取失败", exc_info=True)
        return {"ok": False, "message": "模型池读取失败，无法探测视频运动参考能力"}

    channels = list(patch.get("channels") or [])
    ch = None
    if channel_id:
        ch = next((c for c in channels if c.get("id") == channel_id), None)
    if ch is None:
        ch = next((c for c in channels if c.get("id") == "shiguang-aigc"), None)
    if ch is None:
        # 未指定渠道时：任一渠道含 video_motion 模型即可用
        for c in channels:
            if any(str(m.get("capability") or "") == "video_motion" for m in (c.get("models") or [])):
                ch = c
                break

    models = list((ch or {}).get("models") or [])
    if model:
        entry = next((m for m in models if str(m.get("name") or "") == model), None)
        if entry and str(entry.get("capability") or "") == "video_motion":
            return {"ok": True, "channel_id": ch.get("id") if ch else "", "model": model}
        return {
            "ok": False,
            "message": (
                f"当前模型「{model or '未指定'}」不支持视频运动参考（motion-ref）。"
                "请在模型池选择带 video_motion 能力的模型，或改用图片条件 / 3D 白模模式。"
            ),
        }
    if any(str(m.get("capability") or "") == "video_motion" for m in models):
        return {"ok": True, "channel_id": ch.get("id") if ch else ""}
    return {
        "ok": False,
        "message": "当前渠道/模型池暂无支持视频运动参考（motion-ref）的模型；参考视频已保存，接入后可直接复用。",
    }


def generate_video_via_host(
    *,
    prompt: str,
    model: str = "",
    channel_id: str = "",
    duration: float = 5.0,
    size: str = "1280x720",
    reference_image: str = "",
    reference_video: str = "",
    first_frame: str = "",
    last_frame: str = "",
    bridge_port: int = DEFAULT_PORT,
    quality: str = "standard",
    postprocess_progress_callback: Optional[Callable[[int, str], None]] = None,
    postprocess_done_callback: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """用模型广场 AIGC 渠道尝试生视频；失败返回明确错误（不假成功占位）。

    分支优先级：
    0) reference_video 非空：motion-ref 门禁 —— 落 inbox + video_motion 能力探测，不支持诚实失败
    1) Zhipu CogVideoX 首尾帧：base 含 bigmodel.cn，first_frame + last_frame 同时存在
       → POST /videos/generations → 轮询 GET /async-result/{id}（支持 image_url 数组）
    2) 硅基流动 Wan：submit + poll 异步
    3) 通用 OpenAI-compatible：/videos、/video/generations、/videos/generations
    成功后文件写入 canvas inbox，返回可播放 URL。
    """
    import urllib.error
    import urllib.request

    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "message": "提示词为空"}

    # 语义画质档位 → 实现层参数（size 作为 provider 无关兜底；steps 供本地/支持的后端选用）
    quality_params = translate_quality(quality, CAPABILITY_VIDEO)
    size = size or (quality_params.get("size") or "1280x720")

    def _apply_local_postprocess(result: Dict[str, Any]) -> Dict[str, Any]:
        """对已落盘的本地视频按画质档位做补帧/超分；后台线程执行，立即返回原始结果。"""
        if not result.get("ok") or not result.get("video_path"):
            return result
        if not (quality_params.get("frame_interpolate") or quality_params.get("upscale")):
            return result

        src_path = result["video_path"]
        # 标记后处理进行中，主流程无需等待；前端按 job_id 轮询进度与最终产物
        result["postprocessing"] = True
        result["postprocessed"] = False

        def _run_postprocess() -> None:
            from app.core.generation_postprocess import apply_video_postprocess

            final_path = src_path
            try:
                enhanced = apply_video_postprocess(
                    src_path,
                    quality_params,
                    progress_callback=postprocess_progress_callback,
                )
                if enhanced and enhanced != src_path and os.path.isfile(enhanced):
                    final_path = enhanced
            except Exception as exc:
                logger.debug(f"生视频后处理跳过: {exc}")
            if postprocess_done_callback:
                try:
                    postprocess_done_callback(src_path, final_path)
                except Exception as exc:
                    logger.debug(f"后处理完成回调异常: {exc}")

        import threading

        threading.Thread(target=_run_postprocess, daemon=True, name="video-postprocess").start()
        return result

    # ── 参考视频运动驱动（motion-ref 模式 A）：先落 inbox，再能力探测；不支持则诚实失败 ──
    if (reference_video or "").strip():
        normalized = _normalize_reference_video(reference_video, bridge_port=bridge_port)
        if not normalized.get("ok"):
            return {
                "ok": False,
                "message": str(normalized.get("message") or "参考视频无效"),
                "supports_motion_ref": False,
            }
        ref_url = str(normalized.get("url") or "")
        ref_path = str(normalized.get("path") or "")
        if channel_id and channel_id.startswith("local/"):
            return {
                "ok": False,
                "message": "本地推理管线暂不支持视频运动参考（motion-ref）；参考视频已保存，可改用图片条件。",
                "supports_motion_ref": False,
                "reference_video_url": ref_url,
                "reference_video_path": ref_path,
            }
        support = _probe_video_motion_support(channel_id=channel_id, model=model)
        if not support.get("ok"):
            logger.info(
                "[motion-ref] 参考视频已落盘 %s，能力探测不通过: %s",
                ref_path or ref_url, support.get("message"),
            )
            return {
                "ok": False,
                "message": str(support.get("message") or "当前模型不支持视频运动参考"),
                "supports_motion_ref": False,
                "reference_video_url": ref_url,
                "reference_video_path": ref_path,
            }
        # 能力通过：参考视频引用已就绪（provider 分支消费点在 motion-ref 模型接入时点亮）
        logger.info("[motion-ref] 参考视频已挂载 %s，走 %s / %s 生成", ref_url, channel_id, model)

    # ── 本地 GPU 推理 fallback：channel_id 以 "local/" 开头强制本地 ──
    if channel_id and channel_id.startswith("local/"):
        local_backends = local_generation_registry.resolve(CAPABILITY_VIDEO)
        if not local_backends:
            return {
                "ok": False,
                "message": "本地推理模块 local_video_infer.py 不可用，请检查文件是否存在",
            }
        return _apply_local_postprocess(local_backends[0].generate(
            CAPABILITY_VIDEO,
            prompt=prompt,
            model=model,
            duration=duration,
            size=size,
            reference_image=reference_image,
            first_frame=first_frame,
            last_frame=last_frame,
            bridge_port=bridge_port,
            steps=quality_params.get("steps"),
        ))

    patch = build_host_ai_config_patch()
    channels = list(patch.get("channels") or [])
    defaults = dict(patch.get("defaults") or {})

    ch = None
    if channel_id:
        ch = next((c for c in channels if c.get("id") == channel_id), None)
    if ch is None:
        ch = next((c for c in channels if c.get("id") == "shiguang-aigc"), None)
    if ch is None:
        for c in channels:
            if not (c.get("apiKey") or "").strip():
                continue
            if any((m.get("capability") == "video") for m in (c.get("models") or [])):
                ch = c
                break
    if ch is None or not (ch.get("apiKey") or "").strip():
        return {
            "ok": False,
            "message": (
                "没有可用的 AIGC 生视频渠道。请到「模型管理」填写硅基流动等 Key，"
                "并确认 AIGC 目录含视频模型后点「同步模型池」。"
            ),
        }

    if not model:
        raw = str(defaults.get("videoModel") or "")
        if "::" in raw:
            model = raw.split("::", 1)[-1]
        if not model:
            for m in ch.get("models") or []:
                if m.get("capability") == "video":
                    model = str(m.get("name") or "")
                    break
    if not model:
        return {"ok": False, "message": "渠道内没有生视频模型"}

    base = str(ch.get("baseUrl") or "").rstrip("/")
    if not base:
        return {"ok": False, "message": "渠道缺少 baseUrl"}

    api_key = str(ch.get("apiKey") or "")
    errors: List[str] = []

    def _json_req(method: str, url: str, body: Optional[Dict[str, Any]] = None, timeout: float = 60):
        return _json_request(method, url, api_key, body=body, timeout=timeout)

    def _json_req_retryable(
        method: str, url: str, body: Optional[Dict[str, Any]] = None, timeout: float = 60,
        max_retry: int = 1,
    ):
        """带自动重试的 JSON 请求：遇到 429 (rate limit) 自动等 retry-after；遇到 5xx 短暂重试。"""
        import urllib.error as _ue
        for attempt in range(max_retry + 1):
            try:
                return _json_req(method, url, body, timeout)
            except _ue.HTTPError as he:
                # 429：限流 — 从响应头或 body 里提取 retry-after，等完重试
                if he.code == 429 and attempt < max_retry:
                    wait_sec = 60.0  # 默认等 60s
                    try:
                        ra = he.headers.get("Retry-After") or he.headers.get("retry-after")
                        if ra:
                            wait_sec = max(1.0, min(float(ra), 120.0))
                    except Exception:
                        logger.debug("parse retry-after header failed", exc_info=True)
                    try:
                        raw = he.read().decode("utf-8", errors="replace")
                        m = re.search(r'"reset_in"\s*:\s*(\d+)', raw)
                        if m:
                            wait_sec = max(1.0, min(float(m.group(1)) + 1, 120.0))
                        else:
                            m2 = re.search(r'"rate_limit_reset"\s*:\s*(\d+)', raw)
                            if m2:
                                wait_sec = max(1.0, min(float(m2.group(1)) + 1, 120.0))
                    except Exception:
                        logger.debug("parse rate-limit reset failed", exc_info=True)
                    logger.warning(
                        "API 429 限流，等待 %.0fs 后第 %d/%d 次重试 (%s %s)",
                        wait_sec, attempt + 1, max_retry, method, url.split("?")[0],
                    )
                    time.sleep(wait_sec)
                    continue
                # 5xx：服务器抖动 — 短暂等待 5s 重试一次
                if 500 <= he.code <= 599 and attempt < max_retry:
                    logger.warning(
                        "API %d 服务器错误，等待 5s 后第 %d/%d 次重试 (%s %s)",
                        he.code, attempt + 1, max_retry, method, url.split("?")[0],
                    )
                    time.sleep(5)
                    continue
                raise

    def _save_video_bytes(raw: bytes, ext: str = ".mp4") -> Dict[str, Any]:
        name = f"{int(time.time())}_gen{ext}"
        path = os.path.join(_canvas_inbox_dir(), name)
        with open(path, "wb") as f:
            f.write(raw)
        url = f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}"
        return _apply_local_postprocess({
            "ok": True,
            "video_path": path,
            "video_url": url,
            "model": model,
            "channel_id": ch.get("id"),
            "channel_name": ch.get("name"),
            "message": f"已生成视频（{ch.get('name')} / {model}）",
        })

    def _download_url(file_url: str) -> Dict[str, Any]:
        req = urllib.request.Request(file_url, headers={"Authorization": f"Bearer {api_key}"})
        with _open_url_cancellable(req, timeout=180) as resp:
            raw = resp.read()
        return _save_video_bytes(raw, ".mp4")

    # ── Zhipu CogVideoX 首尾帧 → POST /videos/generations + 轮询 /async-result/{id} ──
    if "bigmodel.cn" in base.lower() and first_frame and last_frame:
        try:
            mf, bf64 = _data_url_to_b64(first_frame)
            ml, bl64 = _data_url_to_b64(last_frame)
            if not bf64 or not bl64:
                errors.append("首尾帧不是有效 data URL（需要 data:image/png;base64,... 格式）")
            else:
                body: Dict[str, Any] = {
                    "model": model or "cogvideox-3",
                    "prompt": prompt,
                    "image_url": [
                        f"data:{mf or 'image/png'};base64,{bf64}",
                        f"data:{ml or 'image/png'};base64,{bl64}",
                    ],
                    "duration": int(max(5, min(15, duration))),
                    "size": size or "1920x1080",
                    "fps": 30,
                    "quality": "quality" if quality in ("fine", "cinema") else "speed",
                    "with_audio": False,
                }
                # 参考图（角色正脸）用于身份锚定，CogVideoX 兼容该字段
                if reference_image:
                    mr, br64 = _data_url_to_b64(reference_image)
                    if br64:
                        body["reference_image"] = f"data:{mr or 'image/png'};base64,{br64}"
                submit = _json_req_retryable("POST", base + "/videos/generations", body, timeout=60)
                task_id = str(submit.get("id") or submit.get("request_id") or "")
                if not task_id:
                    errors.append(f"CogVideoX submit 无任务 ID: {str(submit)[:200]}")
                else:
                    # 快速路径：部分渠道 submit 直接返回结果（task_status=SUCCESS 且含 video_url）
                    submit_data = submit.get("data") if isinstance(submit, dict) else None
                    submit_status = str(
                        (submit.get("task_status") if isinstance(submit, dict) else "")
                        or (submit_data.get("task_status") if isinstance(submit_data, dict) else "")
                        or ""
                    ).upper()
                    submit_video_url = ""
                    if isinstance(submit_data, dict):
                        submit_video_url = str(submit_data.get("video_url") or submit_data.get("url") or "")
                    if not submit_video_url and isinstance(submit, dict):
                        submit_video_url = str(submit.get("video_url") or "")
                    if submit_status in ("SUCCESS", "SUCCEEDED") and submit_video_url:
                        return _download_url(submit_video_url)
                    if submit_status in ("FAIL", "FAILED", "ERROR", "CANCELLED"):
                        errors.append(f"CogVideoX submit 即失败: {str(submit)[:200]}")
                    else:
                        deadline = time.time() + 600
                        while time.time() < deadline:
                            status_resp = _json_req_retryable(
                                "GET",
                                base + f"/async-result/{task_id}",
                                None,
                                timeout=30,
                            )
                            data = status_resp.get("data") if isinstance(status_resp, dict) else None
                            task_status = str(
                                (status_resp.get("task_status") if isinstance(status_resp, dict) else "")
                                or (data.get("task_status") if isinstance(data, dict) else "")
                                or ""
                            ).upper()
                            if task_status in ("SUCCESS", "SUCCEEDED"):
                                video_url = ""
                                if isinstance(data, dict):
                                    video_url = str(data.get("video_url") or data.get("url") or "")
                                if not video_url and isinstance(status_resp, dict):
                                    video_url = str(status_resp.get("video_url") or "")
                                if video_url:
                                    return _download_url(video_url)
                                errors.append(f"CogVideoX 成功但无 video_url: {str(status_resp)[:200]}")
                                break
                            if task_status in ("FAIL", "FAILED", "ERROR", "CANCELLED"):
                                errors.append(f"CogVideoX 生成失败: {str(status_resp)[:200]}")
                                break
                            time.sleep(3.0)
                        else:
                            errors.append("CogVideoX 轮询超时（300s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            errors.append(f"CogVideoX HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"CogVideoX 异常: {e}")

    # ── 硅基流动 Wan：submit + poll ──
    if "siliconflow" in base.lower() or "Wan" in model or "Wan-AI" in model:
        try:
            body: Dict[str, Any] = {
                "model": model,
                "prompt": prompt,
            }
            # 部分渠道用 image 做 I2V
            mime, ref_b64 = _data_url_to_b64(reference_image)
            if ref_b64:
                body["image"] = f"data:{mime};base64,{ref_b64}"
            if duration:
                body["duration"] = max(1, min(10, int(duration)))
            submit = _json_req_retryable("POST", base + "/video/submit", body, timeout=90)
            request_id = (
                (submit.get("requestId") if isinstance(submit, dict) else None)
                or (submit.get("id") if isinstance(submit, dict) else None)
                or ((submit.get("data") or {}).get("requestId") if isinstance(submit, dict) else None)
            )
            if not request_id:
                errors.append(f"硅基 submit 无 requestId: {str(submit)[:200]}")
            else:
                deadline = time.time() + 180
                while time.time() < deadline:
                    st = _json_req_retryable(
                        "POST",
                        base + "/video/status",
                        {"requestId": request_id},
                        timeout=60,
                    )
                    status = str(
                        (st.get("status") if isinstance(st, dict) else "")
                        or ((st.get("data") or {}).get("status") if isinstance(st, dict) else "")
                        or ""
                    ).lower()
                    results = []
                    if isinstance(st, dict):
                        results = st.get("results") or (st.get("data") or {}).get("results") or []
                        if not results and st.get("videos"):
                            results = st.get("videos")
                    if status in ("succeed", "succeeded", "success", "completed", "done"):
                        file_url = ""
                        if isinstance(results, list) and results:
                            first = results[0]
                            if isinstance(first, dict):
                                file_url = str(first.get("url") or first.get("video") or "")
                            elif isinstance(first, str):
                                file_url = first
                        if not file_url and isinstance(st, dict):
                            file_url = str(st.get("video_url") or st.get("url") or "")
                        if file_url:
                            return _download_url(file_url)
                        errors.append(f"状态成功但无视频 URL: {str(st)[:200]}")
                        break
                    if status in ("failed", "error", "canceled", "cancelled"):
                        errors.append(f"硅基视频失败: {str(st)[:200]}")
                        break
                    time.sleep(2.5)
                else:
                    errors.append("硅基视频轮询超时（180s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            errors.append(f"硅基视频 HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"硅基视频异常: {e}")

    # ── FLUX 3 Video（BFL API，2026.8 GA，原生音画，20s） ──
    if "bfl" in base.lower() or "black-forest" in base.lower() or "flux" in model.lower():
        try:
            body: Dict[str, Any] = {
                "model": model or "flux-3-video",
                "prompt": prompt,
            }
            mime, ref_b64 = _data_url_to_b64(reference_image)
            if ref_b64:
                body["first_frame"] = f"data:{mime};base64,{ref_b64}"
            if duration:
                body["duration"] = max(1, min(20, int(duration)))
            submit = _json_req_retryable("POST", base + "/v1/video", body, timeout=90)
            task_id = str(
                (submit.get("id") or "")
                or (submit.get("task_id") or "")
                or ((submit.get("data") or {}).get("id") or "")
                or ((submit.get("data") or {}).get("task_id") or "")
            )
            if not task_id:
                # BFL submit 有时直接返回 video_url
                if isinstance(submit, dict):
                    d = submit.get("data") if isinstance(submit.get("data"), dict) else submit
                    direct_url = str(d.get("video_url") or d.get("url") or "")
                    if direct_url:
                        return _download_url(direct_url)
                errors.append(f"FLUX 3 submit 无任务 ID: {str(submit)[:200]}")
            else:
                deadline = time.time() + 240
                while time.time() < deadline:
                    st = _json_req_retryable("GET", base + f"/v1/video/{task_id}", None, timeout=30)
                    status = str(
                        (st.get("status") if isinstance(st, dict) else "")
                        or ((st.get("data") or {}).get("status") if isinstance(st, dict) else "")
                        or ""
                    ).lower()
                    if status in ("succeeded", "success", "completed", "done"):
                        d = st.get("data") if isinstance(st.get("data"), dict) else st
                        video_url = str(
                            (d.get("video_url") or "")
                            or (d.get("url") or "")
                            or ((d.get("videos") or [{}])[0].get("url") if isinstance(d.get("videos"), list) else "")
                        )
                        if video_url:
                            return _download_url(video_url)
                        errors.append(f"FLUX 3 成功但无 video_url: {str(st)[:200]}")
                        break
                    if status in ("failed", "error", "canceled", "cancelled"):
                        errors.append(f"FLUX 3 失败: {str(st)[:200]}")
                        break
                    time.sleep(3.0)
                else:
                    errors.append("FLUX 3 轮询超时（240s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            errors.append(f"FLUX 3 HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"FLUX 3 异常: {e}")

    # ── Runway Gen-4.5（submit /v1/generate → poll /v1/tasks/{id}） ──
    if "runway" in base.lower() or "runwayml" in base.lower() or "gen-4" in model.lower() or "gen4" in model.lower():
        try:
            body: Dict[str, Any] = {
                "model": model or "gen4.5_turbo",
                "prompt": prompt,
            }
            mime, ref_b64 = _data_url_to_b64(reference_image)
            if ref_b64:
                body["image"] = f"data:{mime};base64,{ref_b64}"
            if duration:
                body["duration"] = max(1, min(10, int(duration)))
            submit = _json_req_retryable("POST", base + "/v1/generate", body, timeout=90)
            task_id = str(
                (submit.get("id") or "")
                or (submit.get("task_id") or "")
                or ((submit.get("data") or {}).get("id") or "")
            )
            if not task_id:
                errors.append(f"Runway submit 无任务 ID: {str(submit)[:200]}")
            else:
                deadline = time.time() + 240
                while time.time() < deadline:
                    st = _json_req_retryable("GET", base + f"/v1/tasks/{task_id}", None, timeout=30)
                    status = str(
                        (st.get("status") if isinstance(st, dict) else "")
                        or ((st.get("task") or {}).get("status") if isinstance(st, dict) else "")
                        or ""
                    ).lower()
                    if status in ("succeeded", "success", "completed", "done"):
                        data = st.get("data") if isinstance(st.get("data"), dict) else st
                        outputs = data.get("outputs") if isinstance(data.get("outputs"), list) else []
                        video_url = ""
                        for out in outputs:
                            if isinstance(out, dict) and out.get("type") == "video":
                                video_url = str(out.get("url") or "")
                                break
                        if not video_url and isinstance(data.get("video_url"), str):
                            video_url = str(data["video_url"])
                        if video_url:
                            return _download_url(video_url)
                        errors.append(f"Runway 成功但无 video_url: {str(st)[:200]}")
                        break
                    if status in ("failed", "error", "canceled", "cancelled"):
                        errors.append(f"Runway 失败: {str(st)[:200]}")
                        break
                    time.sleep(2.5)
                else:
                    errors.append("Runway 轮询超时（240s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            errors.append(f"Runway HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"Runway 异常: {e}")

    # ── Kling 3.0（快手开放平台 submit + poll） ──
    if "kling" in base.lower() or "klingai" in base.lower() or "kling" in model.lower():
        try:
            endpoint = "/kling/v1/videos/text2video" if not reference_image else "/kling/v1/videos/image2video"
            body: Dict[str, Any] = {
                "model_name": model or "kling-v2.6",
                "prompt": prompt,
                "mode": "std",
            }
            if reference_image:
                mime, ref_b64 = _data_url_to_b64(reference_image)
                if ref_b64:
                    body["image"] = f"data:{mime};base64,{ref_b64}"
            submit = _json_req_retryable("POST", base + endpoint, body, timeout=90)
            task_id = str(
                (submit.get("task_id") or "")
                or ((submit.get("data") or {}).get("task_id") or "")
                or (submit.get("id") or "")
            )
            if not task_id:
                errors.append(f"Kling submit 无任务 ID: {str(submit)[:200]}")
            else:
                deadline = time.time() + 600
                while time.time() < deadline:
                    st = _json_req_retryable("GET", base + f"/kling/v1/videos/{task_id}", None, timeout=30)
                    data = st.get("data") if isinstance(st.get("data"), dict) else st
                    status = str(
                        (data.get("task_status") if isinstance(data, dict) else "")
                        or ((st.get("task_status") if isinstance(st, dict) else ""))
                        or ""
                    ).lower()
                    if status in ("succeed", "succeeded", "success", "completed", "done"):
                        videos = data.get("task_result", {}).get("videos", []) if isinstance(data, dict) else []
                        video_url = ""
                        if isinstance(videos, list) and videos:
                            video_url = str((videos[0] or {}).get("url") or "")
                        if not video_url and isinstance(data, dict):
                            video_url = str(data.get("video_url") or data.get("url") or "")
                        if video_url:
                            return _download_url(video_url)
                        errors.append(f"Kling 成功但无 video_url: {str(st)[:200]}")
                        break
                    if status in ("fail", "failed", "error", "canceled", "cancelled"):
                        errors.append(f"Kling 失败: {str(st)[:200]}")
                        break
                    time.sleep(3.0)
                else:
                    errors.append("Kling 轮询超时（300s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            errors.append(f"Kling HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"Kling 异常: {e}")

    # ── MiniMax Hailuo / Vidu（submit + poll） ──
    if "minimax" in base.lower() or "hailuo" in model.lower() or "vidu" in model.lower():
        try:
            body: Dict[str, Any] = {
                "model": model or "hailuo-02",
                "prompt": prompt,
            }
            mime, ref_b64 = _data_url_to_b64(reference_image)
            if ref_b64:
                body["image_first_frame"] = f"data:{mime};base64,{ref_b64}"
            if duration:
                body["duration"] = max(5, min(15, int(duration)))
            submit = _json_req_retryable("POST", base + "/v1/video/generations", body, timeout=90)
            task_id = str(
                (submit.get("task_id") or "")
                or ((submit.get("data") or {}).get("task_id") or "")
                or (submit.get("id") or "")
            )
            if not task_id:
                errors.append(f"MiniMax submit 无任务 ID: {str(submit)[:200]}")
            else:
                deadline = time.time() + 240
                while time.time() < deadline:
                    st = _json_req_retryable("GET", base + f"/v1/query/video/{task_id}", None, timeout=30)
                    data = st.get("data") if isinstance(st.get("data"), dict) else st
                    status = str(
                        (data.get("status") if isinstance(data, dict) else "")
                        or (st.get("status") if isinstance(st, dict) else "")
                        or ""
                    ).lower()
                    if status in ("succeeded", "success", "completed", "done", "finished"):
                        video_url = ""
                        if isinstance(data, dict):
                            video_url = str(
                                (data.get("video_url") or "")
                                or (data.get("url") or "")
                                or (data.get("file_url") or "")
                            )
                        if not video_url and isinstance(st, dict):
                            video_url = str(st.get("video_url") or "")
                        if video_url:
                            return _download_url(video_url)
                        errors.append(f"MiniMax 成功但无 video_url: {str(st)[:200]}")
                        break
                    if status in ("failed", "error", "canceled", "cancelled"):
                        errors.append(f"MiniMax 失败: {str(st)[:200]}")
                        break
                    time.sleep(2.5)
                else:
                    errors.append("MiniMax 轮询超时（240s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            errors.append(f"MiniMax HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"MiniMax 异常: {e}")

    # ── 通用兜底：先同步 → 再通用异步 submit+poll ──
    # 第一阶段：尝试同步返回
    def _extract_video_url(payload: Any) -> str:
        """从任意 JSON 响应结构里尽力挖出 video_url。"""
        if isinstance(payload, dict):
            direct = str(payload.get("url") or payload.get("video_url") or payload.get("file_url") or "")
            if direct:
                return direct
            for key in ("data", "result", "video"):
                child = payload.get(key)
                if isinstance(child, dict):
                    direct = str(child.get("url") or child.get("video_url") or child.get("file_url") or "")
                    if direct:
                        return direct
                elif isinstance(child, list) and child:
                    first = child[0]
                    if isinstance(first, dict):
                        direct = str(first.get("url") or first.get("video_url") or first.get("file_url") or "")
                        if direct:
                            return direct
        return ""

    def _extract_task_id(payload: Any) -> str:
        """从任意 JSON 响应结构里尽力挖出 task_id / id / request_id。"""
        if not isinstance(payload, dict):
            return ""
        candidates = [
            "id", "task_id", "taskId", "request_id", "requestId", "job_id", "jobId",
        ]
        for key in candidates:
            v = payload.get(key)
            if isinstance(v, str) and v:
                return v
        data = payload.get("data")
        if isinstance(data, dict):
            for key in candidates:
                v = data.get(key)
                if isinstance(v, str) and v:
                    return v
        return ""

    def _poll_generic(task_id: str, submit_endpoint: str) -> Optional[Dict[str, Any]]:
        """通用轮询：猜测 status endpoint 格式并轮询直到有 video_url。"""
        # 猜测轮询 endpoint：/tasks/{id}, /task/{id}, /status/{id}, /async-result/{id}, /video/{id}
        poll_endpoints = [
            lambda tid: f"/tasks/{tid}",
            lambda tid: f"/task/{tid}",
            lambda tid: f"/status/{tid}",
            lambda tid: f"/async-result/{tid}",
            lambda tid: f"/video/{tid}",
            lambda tid: f"/videos/{tid}",
        ]
        deadline = time.time() + 240
        while time.time() < deadline:
            last_err = ""
            for pf in poll_endpoints:
                try:
                    st = _json_req_retryable("GET", base + pf(task_id), None, timeout=30)
                    # 直接挖到 video_url → 成功
                    v = _extract_video_url(st)
                    if v:
                        return {"ok": True, "video_url": v}
                    # 检测状态 → 完成/失败
                    data = st.get("data") if isinstance(st.get("data"), dict) else st
                    status = str(
                        (data.get("status") if isinstance(data, dict) else "")
                        or (st.get("status") if isinstance(st, dict) else "")
                        or (data.get("task_status") if isinstance(data, dict) else "")
                        or ""
                    ).lower()
                    if status in ("succeeded", "success", "completed", "done", "finished"):
                        break  # 挖到 video_url 才真的成功，不然继续换下一个 poll endpoint
                    if status in ("failed", "error", "canceled", "cancelled"):
                        return {"ok": False, "message": f"通用轮询检测到失败: {status}"}
                except Exception as e:
                    last_err = str(e)
                    continue
            time.sleep(2.5)
        return None

    for endpoint in ("/videos", "/video/generations", "/videos/generations"):
        try:
            body2: Dict[str, Any] = {
                "model": model,
                "prompt": prompt,
            }
            mime, ref_b64 = _data_url_to_b64(reference_image)
            if ref_b64:
                body2["image"] = f"data:{mime};base64,{ref_b64}"
            if duration:
                body2["seconds"] = str(int(max(1, min(10, float(duration) or 5))))
                body2["duration"] = int(max(1, min(10, float(duration) or 5)))
            if size:
                body2["size"] = size
            payload = _json_req_retryable("POST", base + endpoint, body2, timeout=120)

            # 路径 A：同步直接返回 video_url
            direct_url = _extract_video_url(payload)
            if direct_url:
                return _download_url(direct_url)

            # 路径 B：拿到 task_id → 通用异步轮询
            tid = _extract_task_id(payload)
            if tid:
                poll_result = _poll_generic(tid, endpoint)
                if poll_result and poll_result.get("ok"):
                    return _download_url(str(poll_result["video_url"]))
                elif poll_result and not poll_result.get("ok"):
                    errors.append(f"{endpoint} 轮询失败: {poll_result.get('message','')}")
                else:
                    errors.append(f"{endpoint} 轮询超时（240s）")
            else:
                errors.append(f"{endpoint} 返回无法解析（无 url 也无 task_id）: {str(payload)[:200]}")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            errors.append(f"{endpoint} HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"{endpoint}: {e}")

    return {
        "ok": False,
        "message": "生视频失败：" + ("；".join(errors[:4]) if errors else "未知错误"),
        "model": model,
        "channel_id": ch.get("id"),
        "channel_name": ch.get("name"),
    }


def generate_music_via_host(
    *,
    prompt: str,
    model: str = "",
    channel_id: str = "",
    style: str = "",
    lyrics: str = "",
    title: str = "",
    instrumental: bool = False,
    bridge_port: int = DEFAULT_PORT,
) -> Dict[str, Any]:
    """Suno / Suno 中转站 文生音乐。异步提交 → 轮询 → 下载 mp3 到 inbox。

    支持三种主流 Suno API 格式：
    1) 官方 platform.suno.com   → POST /v0/audio → GET /v0/audio/{id}
    2) sunoapi.org / record-info → POST /api/v1/generate → GET /api/v1/generate/record-info?taskId=
    3) 神马 / openai-hk 中转   → POST /suno/submit/music → GET /suno/fetch?task_id=

    落盘前校验文件有效性（>1KB），避免返回 0 字节假成功。
    """
    import urllib.error
    import urllib.request

    prompt = (prompt or "").strip()
    if not prompt and not lyrics.strip():
        return {"ok": False, "message": "音乐提示词或歌词不能为空"}

    ch, model, patch = _resolve_aigc_channel(
        channel_id=channel_id,
        capability="music",
        default_model_key="musicModel",
    )

    # 若渠道没有 capability=music，尝试用 "audio" capability 兜底（TTS 渠道不算）
    if ch is None or not (ch.get("apiKey") or "").strip():
        for c in list((patch.get("channels") or [])):
            if not (c.get("apiKey") or "").strip():
                continue
            if any((m.get("capability") in ("music",) for m in (c.get("models") or []))):
                ch = c
                break

    if ch is None or not (ch.get("apiKey") or "").strip():
        return {
            "ok": False,
            "message": (
                "没有可用的 Suno 音乐生成渠道。请到「模型管理」添加 Suno 渠道 "
                "（capability 设为 music，key 填 suno.com 或 sunoapi.org 的 API Key）。"
            ),
        }

    if not model:
        defaults = dict(patch.get("defaults") or {})
        raw = str(defaults.get("musicModel") or "")
        if "::" in raw:
            model = raw.split("::", 1)[-1]
        if not model:
            for m in ch.get("models") or []:
                if m.get("capability") == "music":
                    model = str(m.get("name") or "")
                    break

    base = str(ch.get("baseUrl") or "").rstrip("/")
    if not base:
        return {"ok": False, "message": "渠道缺少 baseUrl（Suno 官方用 https://api.suno.com，中转站各有不同）"}

    api_key = str(ch.get("apiKey") or "")
    errors: List[str] = []

    def _json_req(method: str, url: str, body: Optional[Dict[str, Any]] = None, timeout: float = 120):
        return _json_request(method, url, api_key, body=body, timeout=timeout)

    def _download_to_inbox(file_url: str, ext: str = ".mp3") -> Dict[str, Any]:
        """下载音频到 canvas inbox 并返回可播放 URL。下载后校验文件有效性（>1KB）。"""
        try:
            req = urllib.request.Request(
                file_url,
                headers={"Authorization": f"Bearer {api_key}"} if file_url.startswith(base) else {},
            )
            with _open_url_cancellable(req, timeout=300) as resp:
                raw = resp.read()
        except Exception as e:
            return {"ok": False, "message": f"下载音乐失败: {e}"}

        # 有效性防线：0 字节或极小文件视为无效
        if not raw or len(raw) < 1024:
            return {"ok": False, "message": f"下载到的音乐文件无效（{len(raw)} 字节，可能是 CDN 404 页）"}

        name = f"music_{int(time.time())}_{abs(hash(prompt or lyrics)) % 100000}{ext}"
        dest = os.path.join(_canvas_inbox_dir(), name)
        with open(dest, "wb") as f:
            f.write(raw)
        url = f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}"
        return {
            "ok": True,
            "audio_path": dest,
            "audio_url": url,
            "title": title or "AI 生成音乐",
            "duration_hint": None,
            "model": model,
            "channel_id": ch.get("id"),
            "channel_name": ch.get("name"),
            "message": f"音乐已生成（{ch.get('name') or 'Suno'} · {model}）",
        }

    # ── 分支 1：Suno 官方 API（api.suno.com / v0/audio） ──
    if "suno.com" in base.lower():
        try:
            body: Dict[str, Any] = {}
            if lyrics.strip():
                body["lyrics"] = lyrics.strip()
                if style.strip():
                    body["style"] = style.strip()
            else:
                body["description"] = prompt
            if title.strip():
                body["title"] = title.strip()
            if instrumental:
                body["instrumental"] = True

            submit = _json_req("POST", base + "/v0/audio", body, timeout=120)
            task_id = str((submit.get("id") or "")) if isinstance(submit, dict) else ""
            if not task_id:
                errors.append(f"Suno 官方 submit 无 id: {str(submit)[:200]}")
            else:
                deadline = time.time() + 600
                while time.time() < deadline:
                    st = _json_req("GET", f"{base}/v0/audio/{task_id}", timeout=60)
                    status = str((st.get("status") if isinstance(st, dict) else "") or "").lower()
                    if status in ("complete", "completed"):
                        audio_url = str((st.get("audio_url") if isinstance(st, dict) else "") or "")
                        if audio_url:
                            return _download_to_inbox(audio_url)
                        errors.append(f"Suno 完成但无 audio_url: {str(st)[:200]}")
                        break
                    if status in ("error", "failed"):
                        errors.append(f"Suno 失败: {str(st.get('error') or st)[:200] if isinstance(st, dict) else str(st)[:200]}")
                        break
                    time.sleep(4)
                else:
                    errors.append("Suno 官方轮询超时（300s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            errors.append(f"Suno 官方 HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"Suno 官方异常: {e}")

    # ── 分支 2：sunoapi.org / record-info 格式 ──
    elif "sunoapi" in base.lower() or base.endswith("/api/v1/generate".rsplit("/", 1)[0]):
        try:
            body2: Dict[str, Any] = {
                "prompt": lyrics.strip() or prompt,
                "customMode": bool(lyrics.strip()),
                "instrumental": instrumental,
                "model": model or "V4_5ALL",
            }
            if lyrics.strip():
                body2["title"] = title.strip() if title else "AI Song"

            submit2 = _json_req("POST", base + "/api/v1/generate", body2, timeout=120)
            task_id2 = ""
            if isinstance(submit2, dict):
                d = submit2.get("data")
                if isinstance(d, dict):
                    task_id2 = str(d.get("taskId") or "")
                elif isinstance(d, str):
                    task_id2 = d
                task_id2 = task_id2 or str(submit2.get("taskId") or "")

            if not task_id2:
                errors.append(f"sunoapi submit 无 taskId: {str(submit2)[:200]}")
            else:
                deadline = time.time() + 600
                while time.time() < deadline:
                    st2 = _json_req(
                        "GET",
                        f"{base}/api/v1/generate/record-info?taskId={task_id2}",
                        timeout=60,
                    )
                    d2 = (st2.get("data") if isinstance(st2, dict) else None) or {}
                    status2 = str((d2.get("status") if isinstance(d2, dict) else "") or "").lower()
                    resp = (d2.get("response") if isinstance(d2, dict) else None) or {}
                    suno_list = (resp.get("sunoData") if isinstance(resp, dict) else None) or []
                    if status2 == "success" and suno_list:
                        first = suno_list[0] if isinstance(suno_list[0], dict) else {}
                        audio_url2 = str(first.get("audioUrl") or "")
                        if audio_url2:
                            result = _download_to_inbox(audio_url2)
                            if result.get("ok") and isinstance(first.get("duration"), (int, float)):
                                result["duration_hint"] = float(first["duration"])
                                if first.get("title"):
                                    result["title"] = str(first["title"])
                            return result
                        errors.append(f"sunoapi 成功但无 audioUrl: {str(st2)[:200]}")
                        break
                    if status2 in ("failed", "error", "canceled", "cancelled"):
                        errors.append(f"sunoapi 失败: {str(d2.get('errorMessage') or st2)[:200]}")
                        break
                    time.sleep(4)
                else:
                    errors.append("sunoapi 轮询超时（300s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            errors.append(f"sunoapi HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"sunoapi 异常: {e}")

    # ── 分支 3：神马 / openai-hk 等中转（/suno/submit/music + /suno/fetch） ──
    else:
        try:
            body3: Dict[str, Any]
            if lyrics.strip():
                body3 = {
                    "prompt": lyrics.strip(),
                    "tags": style.strip() or "pop",
                    "mv": model or "chirp-v3-5",
                    "title": title.strip() or "AI Song",
                }
            else:
                body3 = {
                    "gpt_description_prompt": prompt,
                    "model": model or "chirp-v3-5",
                }
            if instrumental:
                body3["make_instrumental"] = True

            submit3 = _json_req("POST", base + "/suno/submit/music", body3, timeout=120)
            task_id3 = ""
            if isinstance(submit3, dict):
                d3 = submit3.get("data")
                if isinstance(d3, str):
                    task_id3 = d3
                elif isinstance(d3, dict):
                    task_id3 = str(d3.get("task_id") or d3.get("taskId") or "")
                elif isinstance(d3, list) and d3:
                    first = d3[0] if isinstance(d3[0], dict) else {}
                    task_id3 = str(first.get("task_id") or first.get("taskId") or "")
                task_id3 = task_id3 or str(submit3.get("task_id") or submit3.get("taskId") or "")

            if not task_id3:
                errors.append(f"中转站 submit 无 taskId: {str(submit3)[:200]}")
            else:
                deadline = time.time() + 600
                while time.time() < deadline:
                    try:
                        st3 = _json_req(
                            "GET",
                            f"{base}/suno/fetch?task_id={task_id3}",
                            timeout=60,
                        )
                    except Exception:
                        st3 = _json_req(
                            "GET",
                            f"{base}/suno/fetch?taskId={task_id3}",
                            timeout=60,
                        )
                    data3 = (st3.get("data") if isinstance(st3, dict) else None) or {}
                    if isinstance(data3, list) and data3:
                        data3 = data3[0] if isinstance(data3[0], dict) else {}
                    status3 = str((data3.get("status") if isinstance(data3, dict) else "") or "").lower()
                    clips = (data3.get("clips") if isinstance(data3, dict) else None) or []
                    if isinstance(data3, dict) and data3.get("audio_url"):
                        return _download_to_inbox(str(data3["audio_url"]))
                    if clips and isinstance(clips[0], dict):
                        audio_url3 = str(clips[0].get("audio_url") or clips[0].get("audioUrl") or "")
                        if audio_url3:
                            return _download_to_inbox(audio_url3)
                    if status3 in ("failed", "error"):
                        errors.append(f"中转站失败: {str(st3)[:200]}")
                        break
                    time.sleep(4)
                else:
                    errors.append("中转站轮询超时（300s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                logger.debug("read HTTP error body failed", exc_info=True)
            errors.append(f"中转站 HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"中转站异常: {e}")

    return {
        "ok": False,
        "message": "音乐生成失败：" + ("；".join(errors[:4]) if errors else "未知错误"),
        "model": model,
        "channel_id": ch.get("id") if ch else "",
        "channel_name": ch.get("name") if ch else "",
    }


def _parse_storyboard_json(text: str) -> List[Dict[str, Any]]:
    """从 LLM 输出中提取 JSON 数组（兼容代码块包裹）。"""
    try:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start >= 0 and end > start:
            data = json.loads(cleaned[start : end + 1])
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.debug("parse storyboard json failed", exc_info=True)
    return []


def _heuristic_storyboard(script: str) -> List[Dict[str, Any]]:
    """LLM 不可用时：按段落/句号切分启发式分镜。"""
    text = (script or "").strip()
    if not text:
        return [
            {
                "id": 1,
                "duration": 5,
                "shot": "远景",
                "description": "开场镜头",
                "dialogue": "",
            },
            {
                "id": 2,
                "duration": 5,
                "shot": "中景",
                "description": "主体展示",
                "dialogue": "",
            },
            {
                "id": 3,
                "duration": 5,
                "shot": "特写",
                "description": "收尾定格",
                "dialogue": "",
            },
        ]
    parts: List[str] = []
    for block in text.replace("\r\n", "\n").split("\n"):
        block = block.strip()
        if not block:
            continue
        for piece in block.replace("。", "。\n").split("\n"):
            piece = piece.strip()
            if piece:
                parts.append(piece)
    if not parts:
        parts = [text[:200]]
    parts = parts[:25]
    shotsizes = ["远景", "全景", "中景", "近景", "特写"]
    out: List[Dict[str, Any]] = []
    for i, p in enumerate(parts):
        dialogue = ""
        desc = p
        if "「" in p and "」" in p:
            try:
                dialogue = p[p.index("「") + 1 : p.index("」")]
                desc = (p[: p.index("「")] + p[p.index("」") + 1 :]).strip() or p
            except ValueError:
                logger.debug("parse dialogue delimiter failed", exc_info=True)
        out.append(
            {
                "id": i + 1,
                "duration": max(3, min(12, 2 + len(p) // 20)),
                "shot": shotsizes[i % len(shotsizes)],
                "description": desc[:200],
                "dialogue": dialogue[:120],
            }
        )
    return out


def storyboard_breakdown(script: str, use_llm: bool = False) -> Dict[str, Any]:
    """一键拉片：剧本 → 分镜表。

    默认 use_llm=False：直接启发式拆解（逗号/句号/换行切场景，不二次 LLM 不优化剧本）。
    use_llm=True：调 AIEngine 做结构化拆解（更智能但多一次模型调用，可能对剧本做润色）。
    """
    script = (script or "").strip()
    if not script:
        return {"ok": False, "shots": [], "message": "剧本为空"}

    if use_llm:
        try:
            from app.core.ai_engine import AIEngine

            engine = AIEngine()
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是分镜师。严格按剧本原文拆解，不要添加/修改/润色剧本内容，"
                        "不要优化或重新创作。把每一段落/场景对应成结构化分镜，"
                        '每镜一行 JSON：{"id":1,"duration":5,"shot":"特写/中景/远景",'
                        '"description":"画面描述（用剧本原文，不要自由发挥）","dialogue":"对白"}。'
                        "输出 JSON 数组，不要其他文字。"
                    ),
                },
                {"role": "user", "content": f"剧本：\n{script}\n\n请输出分镜表 JSON。"},
            ]
            full = ""
            for chunk in engine.chat_with_fallback(
                messages, template=lambda: json.dumps(_heuristic_storyboard(script), ensure_ascii=False)
            ):
                full += chunk
            shots = _parse_storyboard_json(full.strip())
            if shots:
                norm: List[Dict[str, Any]] = []
                for i, s in enumerate(shots):
                    if not isinstance(s, dict):
                        continue
                    norm.append(
                        {
                            "id": int(s.get("id") or i + 1),
                            "duration": float(s.get("duration") or 5),
                            "shot": str(s.get("shot") or "中景"),
                            "description": str(s.get("description") or ""),
                            "dialogue": str(s.get("dialogue") or ""),
                        }
                    )
                if norm:
                    return {
                        "ok": True,
                        "shots": norm,
                        "fallback": False,
                        "message": f"拉片完成（LLM）{len(norm)} 镜",
                    }
        except Exception as e:
            logger.warning("LLM 拆剧本失败，降级启发式: %s", e)

    # 默认：启发式拆解（快速、不优化剧本原文）
    shots = _heuristic_storyboard(script)
    return {
        "ok": True,
        "shots": shots,
        "fallback": True,
        "message": f"拉片完成（启发式）{len(shots)} 镜",
    }


# ── WS4#2 相机路径规划：分镜表 → StageCamera + 运镜 pathPoints ─────
# 景别 → 机位预设（position / lookAt / fov / shotSize），与前端 Stage3D 的 CAM_PRESETS 对齐。
_SHOT_SIZE_CAMERA_PRESETS: Dict[str, Dict[str, Any]] = {
    "远景": {"position": [0.0, 3.0, 11.0], "lookAt": [0.0, 1.0, 0.0], "fov": 55, "shotSize": "远景"},
    "全景": {"position": [0.0, 2.2, 7.0], "lookAt": [0.0, 1.0, 0.0], "fov": 50, "shotSize": "全景"},
    "中景": {"position": [0.0, 1.6, 4.2], "lookAt": [0.0, 1.2, 0.0], "fov": 40, "shotSize": "中景"},
    "近景": {"position": [0.0, 1.5, 2.8], "lookAt": [0.0, 1.35, 0.0], "fov": 38, "shotSize": "近景"},
    "特写": {"position": [0.0, 1.55, 2.2], "lookAt": [0.0, 1.45, 0.0], "fov": 35, "shotSize": "特写"},
}

# 景别 → 默认运镜（分镜表不含运镜字段时按景别推导，生成自然且有变化的镜头运动）。
_SHOT_SIZE_MOVEMENT: Dict[str, str] = {
    "远景": "static",
    "全景": "pan-right",
    "中景": "push-in",
    "近景": "push-in",
    "特写": "static",
}


def _vec_sub(a: List[float], b: List[float]) -> List[float]:
    """三维向量减法。"""
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _vec_norm(v: List[float]) -> List[float]:
    """三维向量归一化（零向量原样返回）。"""
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return [v[0] / n, v[1] / n, v[2] / n] if n > 1e-9 else [0.0, 0.0, 0.0]


def _vec_cross(a: List[float], b: List[float]) -> List[float]:
    """三维向量叉积。"""
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _build_camera_path(
    start: List[float],
    look: List[float],
    movement: str,
    steps: int = 8,
) -> List[Dict[str, Any]]:
    """按运镜类型从起点生成 pathPoints（位置 + lookAt 点插值序列）。

    复刻前端 Stage3D.applyCameraMove 的运镜语义：push-in/pull-out 沿视线进退、
    pan-left/pan-right 绕目标水平摇、tilt-up/tilt-down 抬/压视线、dolly 侧移、crane 升降。
    static 返回空列表（仅摆机位不运镜）。
    """
    if movement == "static" or steps <= 0:
        return []

    dir_ = _vec_norm(_vec_sub(look, start))
    dist = math.sqrt(
        (look[0] - start[0]) ** 2 + (look[1] - start[1]) ** 2 + (look[2] - start[2]) ** 2
    )
    # 右向量（水平垂直于视线的单位向量）
    right = _vec_norm(_vec_cross(dir_, [0.0, 1.0, 0.0]))

    points: List[Dict[str, Any]] = []
    for i in range(1, steps + 1):
        t = i / steps
        pos = list(start)
        look_p = list(look)
        if movement == "push-in":
            d = min(dist * 0.6, dist - 0.5) * t
            pos = [
                start[0] + dir_[0] * d,
                start[1] + dir_[1] * d * 0.3,
                start[2] + dir_[2] * d,
            ]
        elif movement == "pull-out":
            d = dist * 0.6 * t
            pos = [
                start[0] - dir_[0] * d,
                start[1] + dir_[1] * d * 0.2,
                start[2] - dir_[2] * d,
            ]
        elif movement in ("pan-left", "pan-right"):
            sign = 1.0 if movement == "pan-left" else -1.0
            ang = sign * (math.pi / 6) * t  # 30° 摇镜
            pos = [
                start[0] + right[0] * sign * math.sin(ang) * dist * 0.4,
                start[1],
                start[2] + right[2] * sign * math.sin(ang) * dist * 0.4,
            ]
        elif movement == "tilt-up":
            look_p = [look[0], look[1] + 1.2 * t, look[2]]
        elif movement == "tilt-down":
            look_p = [look[0], look[1] - 1.2 * t, look[2]]
        elif movement == "dolly":
            pos = [start[0] + right[0] * 2.0 * t, start[1], start[2] + right[2] * 2.0 * t]
        elif movement == "crane":
            pos = [start[0], start[1] + 2.5 * t, start[2]]
            look_p = [look[0], look[1] - 0.5 * t, look[2]]
        else:
            # 未知运镜：线性向目标推进一档，保证非空
            d = dist * 0.3 * t
            pos = [
                start[0] + dir_[0] * d,
                start[1] + dir_[1] * d,
                start[2] + dir_[2] * d,
            ]
        points.append({"pos": [round(v, 3) for v in pos], "look": [round(v, 3) for v in look_p]})
    return points


def storyboard_to_camera_plan(shots: List[Dict[str, Any]]) -> Dict[str, Any]:
    """WS4#2 相机路径规划入口：分镜表 → StageCamera 计划（AI 自动摆机位）。

    把每镜景别映射为 StageCamera（position/lookAt/fov/shotSize），并按运镜类型生成
    pathPoints / pathDuration，供画布桥推送到 Stage3D 沿点插值播放，实现 AI 自动摆机位。

    每镜可携带 `movement` 字段覆盖默认运镜（支持 static/push-in/pull-out/pan-left/
    pan-right/tilt-up/tilt-down/dolly/crane）。
    """
    cameras: List[Dict[str, Any]] = []
    for idx, raw in enumerate(shots or []):
        shot = raw if isinstance(raw, dict) else {}
        shot_size = str(shot.get("shot") or "中景").strip()
        preset = _SHOT_SIZE_CAMERA_PRESETS.get(shot_size) or _SHOT_SIZE_CAMERA_PRESETS["中景"]

        movement = str(shot.get("movement") or _SHOT_SIZE_MOVEMENT.get(shot_size, "push-in")).strip()
        start = list(preset["position"])
        look = list(preset["lookAt"])
        path_points = _build_camera_path(start, look, movement)

        # 运镜时长贴合分镜时长（秒 → 毫秒），无时长字段则固定 3s
        try:
            duration_ms = int(round(float(shot.get("duration") or 0) * 1000))
        except (TypeError, ValueError):
            duration_ms = 0
        duration_ms = duration_ms if duration_ms > 0 else 3000

        cameras.append(
            {
                "id": f"shot_{idx + 1}",
                "name": f"分镜{idx + 1} · {shot_size}",
                "position": start,
                "lookAt": look,
                "fov": int(preset["fov"]),
                "shotSize": shot_size,
                "movement": movement,
                "pathPoints": path_points,
                "pathDuration": duration_ms,
            }
        )
    return {"ok": True, "cameras": cameras, "count": len(cameras)}


# ── 一键拉片：参考视频 → 可编辑分镜表 ───────────────────────────────
# 上传参考片 → ffprobe 读时长 → SceneAnalyzer 检测镜头边界（PySceneDetect 优先，
# 缺库降级帧差法，再降级均匀切段）→ ffmpeg 抽代表帧 → cv2 算色调/亮度 →
# 按镜头时长启发式推断景别 → 生成可编辑分镜表（不伪造画面内容，诚实标注时间区间）。


def _extract_shot_frame(ffmpeg: str, path: str, t: float, width: int = 256) -> Optional[bytes]:
    """用 ffmpeg 抽 t 秒处的 1 帧 JPEG（缩到 width 宽），失败返回 None。"""
    import subprocess
    import sys
    import tempfile

    fd, out = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        cmd = [
            ffmpeg, "-y", "-ss", f"{t:.3f}", "-i", path,
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", out,
        ]
        r = subprocess.run(
            cmd, capture_output=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if r.returncode != 0 or not os.path.isfile(out) or os.path.getsize(out) == 0:
            return None
        with open(out, "rb") as f:
            return f.read()
    except Exception as e:
        logger.warning("抽帧失败 t=%.2f: %s", t, e)
        return None
    finally:
        try:
            os.remove(out)
        except OSError:
            logger.debug("清理临时抽帧文件失败: %s", out, exc_info=True)


def _analyze_frame_tone(jpeg_bytes: bytes) -> Optional[Dict[str, Any]]:
    """从 JPEG 帧算平均亮度与冷暖色调（cv2 缺库时返回 None，诚实降级）。"""
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(jpeg_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            return None
        b = float(img[:, :, 0].mean())
        g = float(img[:, :, 1].mean())
        r = float(img[:, :, 2].mean())
        brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
        warmth = r - b
        tone = "暖" if warmth > 12 else ("冷" if warmth < -12 else "中性")
        return {
            "tone": tone,
            "brightness": round(brightness, 3),
            "r": round(r, 1),
            "g": round(g, 1),
            "b": round(b, 1),
        }
    except Exception as e:
        logger.debug("帧色调分析失败: %s", e)
        return None


def _infer_shot_size(dur: float) -> str:
    """镜头时长 → 景别启发式（短镜头多为特写/近景，长镜头多为全景/远景）。"""
    if dur < 1.5:
        return "特写"
    if dur < 3.0:
        return "近景"
    if dur < 5.0:
        return "中景"
    if dur < 8.0:
        return "全景"
    return "远景"


def _infer_camera(shot_size: str) -> str:
    """景别 → 默认运镜（无光流估计时的确定性启发式，不伪装成真实检测）。"""
    return "推" if shot_size in ("特写", "近景") else "固定"


def video_storyboard_breakdown(
    path: str,
    use_llm: bool = False,
    max_shots: int = 30,
    frames_dir: Optional[str] = None,
    frame_url_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """一键拉片：参考视频 → 可编辑分镜表。

    返回值 shots 每镜：
      id / start / end / duration / shot(景别) / camera(运镜) /
      description(镜头语言描述) / dialogue / tone(色调) / brightness(亮度) /
      frame(代表帧 URL 或 dataURL，供前端分镜表「画面」列直接展示)。

    use_llm 当前为占位：宿主无视觉模型，无法从帧解析真实画面内容；
    保留参数位供后续接入视觉模型，届时描述可升级为真实镜头语言。
    """
    if not path or not os.path.isfile(path):
        return {"ok": False, "shots": [], "message": "视频文件不存在"}

    # 1. 时长
    duration = 0.0
    try:
        from app.core.ffmpeg_utils import probe_video_duration
    except ImportError:
        from core.ffmpeg_utils import probe_video_duration  # type: ignore
    try:
        duration = float(probe_video_duration(path) or 0.0)
    except Exception:
        duration = 0.0

    # 2. 镜头边界检测（PySceneDetect → 帧差法 → 均匀切段）
    try:
        from app.core.ai_editing_assistant import SceneAnalyzer
    except ImportError:
        from core.ai_editing_assistant import SceneAnalyzer  # type: ignore
    scenes: List[Tuple[float, float]] = []
    scene_source = "none"
    try:
        detected = SceneAnalyzer().analyze_scenes(video_path=path)
        if detected:
            for s in detected:
                scenes.append((float(s.start_time), float(s.end_time)))
            scene_source = "pyscene"
    except Exception as e:
        logger.warning("场景检测失败: %s", e)

    # 帧差法降级：直接用 SceneAnalyzer 的帧差法需要先读帧，这里改为均匀切段兜底
    if not scenes and duration > 0:
        seg = 4.0
        n = max(1, min(int(max_shots), int(math.ceil(duration / seg))))
        scenes = [(i * seg, min((i + 1) * seg, duration)) for i in range(n)]
        scene_source = "uniform"
    if not scenes:
        return {"ok": False, "shots": [], "message": "未检测到有效镜头"}

    # 3. 合并过短镜头 + 截断到 max_shots
    merged: List[Tuple[float, float]] = []
    for start, end in scenes:
        if end - start < 0.4:  # 忽略 <0.4s 的碎镜头
            if merged:
                merged[-1] = (merged[-1][0], end)
            continue
        merged.append((start, end))
    if not merged:
        merged = scenes
    merged = merged[: max(1, min(int(max_shots), len(merged)))]

    # 4. ffmpeg + cv2 准备
    ffmpeg: Optional[str] = None
    try:
        from app.core.ffmpeg_utils import find_ffmpeg
    except ImportError:
        from core.ffmpeg_utils import find_ffmpeg  # type: ignore
    try:
        ffmpeg = find_ffmpeg()
    except Exception:
        ffmpeg = None

    if frames_dir is None:
        import tempfile
        frames_dir = tempfile.mkdtemp(prefix="shiguang_storyboard_")
    os.makedirs(frames_dir, exist_ok=True)

    import base64
    import uuid

    shots: List[Dict[str, Any]] = []
    for i, (start, end) in enumerate(merged):
        mid = (start + end) / 2.0
        frame_bytes: Optional[bytes] = None
        frame_url: Optional[str] = None
        tone_info: Optional[Dict[str, Any]] = None

        if ffmpeg:
            frame_bytes = _extract_shot_frame(ffmpeg, path, mid)
        if frame_bytes:
            tone_info = _analyze_frame_tone(frame_bytes)
            fname = f"storyboard_{uuid.uuid4().hex[:12]}.jpg"
            try:
                with open(os.path.join(frames_dir, fname), "wb") as f:
                    f.write(frame_bytes)
                if frame_url_prefix:
                    frame_url = f"{frame_url_prefix.rstrip('/')}/{fname}"
                else:
                    frame_url = "data:image/jpeg;base64," + base64.b64encode(frame_bytes).decode("ascii")
            except OSError:
                frame_url = None

        dur = round(end - start, 3)
        shot_size = _infer_shot_size(dur)
        camera = _infer_camera(shot_size)
        tone = tone_info.get("tone") if tone_info else "中性"
        brightness = tone_info.get("brightness") if tone_info else None
        desc_parts = [f"镜头{i + 1}", f"{start:.1f}s-{end:.1f}s", shot_size]
        if tone_info:
            desc_parts.append(f"{tone}色调")
        if brightness is not None:
            desc_parts.append(f"亮度{int(round(brightness * 100))}%")

        shots.append(
            {
                "id": i + 1,
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": dur,
                "shot": shot_size,
                "camera": camera,
                "description": " · ".join(desc_parts),
                "dialogue": "",
                "tone": tone,
                "brightness": brightness,
                "frame": frame_url,
            }
        )

    return {
        "ok": True,
        "shots": shots,
        "fallback": scene_source in ("uniform",),
        "scene_source": scene_source,
        "duration": round(duration, 3),
        "message": f"拉片完成：{len(shots)} 镜（{scene_source} 检测）",
    }
