# -*- coding: utf-8 -*-
"""Breeze TTS 2 语音合成客户端（外部服务适配，非库内推理）。

为什么是「外部 HTTP 服务」而不是本地推理
--------------------------------------
官方运行时只有 Linux + CUDA 形态：
- `requirements.txt` 含 flash-attn，Docker 镜像默认按 H100/Hopper(sm90) 编译；
- eager 推理约 **7.7 GiB** 显存，`--fast-all` 需 14.4 GiB，官方推荐 12GB 起。

本机是 Windows + RTX 4060 Laptop **8 GiB**（2026-10-31 实测空闲约 6.1 GiB），
**既装不了也跑不动**。而本仓库对 ComfyUI 已经确立同款范式：
重运行时放外部进程，这里只做 HTTP 客户端（见 `comfy_client.py`）。

所以本模块只做三件事：探测服务、拼参数、把 PCM 流转 float32。
服务不在 ⇒ 返回 None，让上层回退现有链（Coqui/Piper/gTTS/edge-tts），
**绝不返回假音频**（同 YuE / Piper 的诚实失败纪律）。

服务端启动（在有 Linux + 12GB 卡的机器上）::

    python -m breeze_infer.api BreezeBlue/breeze-tts-2 --host 0.0.0.0 --port 7860

配置
----
- ``SHIGUANG_BREEZE_TTS_URL``：服务地址。**默认空 ⇒ 完全不探测**（零开销、零行为变化）；
  显式设置后才走 Breeze，例如 ``http://127.0.0.1:7860`` 或局域网 ``http://192.168.1.10:7860``。
- ``SHIGUANG_BREEZE_TTS_CFG``：CFG 强度，默认 4.0（README 建议 4 以强化指令遵循）。
- ``SHIGUANG_BREEZE_TTS_TIMEOUT``：单次合成超时秒数，默认 120。

🔴 授权提示（接入前必读）
------------------------
代码 Apache 2.0，但**模型权重、衍生模型与自托管输出仅限研究与非商业用途**；
商用输出必须走 BreezeBlue 的托管平台（付费订阅）。自托管拿不到商用授权。
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.ai.breeze_tts")

ENV_URL = "SHIGUANG_BREEZE_TTS_URL"
ENV_CFG = "SHIGUANG_BREEZE_TTS_CFG"
ENV_TIMEOUT = "SHIGUANG_BREEZE_TTS_TIMEOUT"

DEFAULT_CFG_SCALE = 4.0
DEFAULT_TIMEOUT = 120.0
PROBE_TIMEOUT = 1.5

#: Breeze TTS 2 输出固定 24 kHz / 单声道 / s16le（README「Streaming API」节）
OUTPUT_SAMPLE_RATE = 24000

# ── 枚举 → 中文指令片段（VoiceProfile 的性别/年龄/风格映射成自然语言）──
_GENDER_ZH = {
    "male": "男声",
    "female": "女声",
    "child": "童声",
    "neutral": "中性音色",
}
_AGE_ZH = {
    "young": "年轻",
    "adult": "成年",
    "senior": "年长",
}
_STYLE_ZH = {
    "calm": "语调平稳克制",
    "energetic": "语气有活力",
    "emotional": "情绪饱满",
    "professional": "播音般专业清晰",
    "casual": "口语化自然",
    "dramatic": "戏剧化、张力强",
    "humorous": "带幽默感",
}
_EMOTION_ZH = {
    "neutral": "情绪中性",
    "happy": "情绪愉悦",
    "sad": "情绪悲伤",
    "angry": "情绪愤怒",
    "fear": "情绪紧张",
    "surprise": "情绪惊讶",
}


def breeze_tts_url() -> str:
    """服务基址（去掉尾部斜杠）；未配置返回空串。"""
    return (os.environ.get(ENV_URL, "") or "").strip().rstrip("/")


def breeze_tts_enabled() -> bool:
    """是否显式启用了 Breeze（默认关 —— 未配置就不探测，避免每条配音多一次超时）。"""
    return bool(breeze_tts_url())


def breeze_cfg_scale() -> float:
    raw = (os.environ.get(ENV_CFG, "") or "").strip()
    try:
        return float(raw) if raw else DEFAULT_CFG_SCALE
    except ValueError:
        logger.debug("[BreezeTTS] CFG 配置非法（%r），回落默认 %.1f", raw, DEFAULT_CFG_SCALE)
        return DEFAULT_CFG_SCALE


def breeze_timeout() -> float:
    raw = (os.environ.get(ENV_TIMEOUT, "") or "").strip()
    try:
        return float(raw) if raw else DEFAULT_TIMEOUT
    except ValueError:
        return DEFAULT_TIMEOUT


def build_instruction(
    gender: str = "",
    age: str = "",
    style: str = "",
    description: str = "",
    emotion: str = "",
) -> str:
    """把项目的声线枚举拼成 Breeze 能吃的自然语言「声音设计」指令。

    只做纯字符串拼接（可单测）：身份 → 年龄 → 风格 → 情绪 → 用户自述。
    未知枚举值直接忽略，不抛错 —— 配音不该因为一个枚举拼错就整条失败。
    """
    parts = []
    g = _GENDER_ZH.get((gender or "").strip().lower(), "")
    a = _AGE_ZH.get((age or "").strip().lower(), "")
    identity = f"{a}{g}".strip()
    if identity:
        parts.append(f"一位{identity}")
    s = _STYLE_ZH.get((style or "").strip().lower(), "")
    if s:
        parts.append(s)
    e = _EMOTION_ZH.get((emotion or "").strip().lower(), "")
    if e:
        parts.append(e)
    head = "，".join(parts)
    tail = (description or "").strip()
    if head and tail:
        return f"{head}。{tail}"
    return head or tail


def decode_pcm_s16le(data: bytes) -> "list[float]":
    """24kHz mono s16le PCM → [-1, 1) 浮点样本（纯函数，可单测）。

    用标准库 array 而不是 numpy：本模块被 dub 路由与 voice_generator 共用，
    不希望因为调用方环境差异引入额外 import 顺序问题。
    """
    from array import array

    if not data:
        return []
    if len(data) % 2:  # 半个样本（流被截断）就丢掉尾字节，不崩
        data = data[:-1]
    arr = array("h")
    arr.frombytes(data)
    # 小端：Windows/Linux x86 都是 little-endian，无需 byteswap
    return [v / 32768.0 for v in arr]


def pcm_to_float32(data: bytes):
    """24kHz mono s16le PCM → numpy float32 一维数组（numpy 不可用时返回 None）。"""
    try:
        import numpy as np
    except ImportError:
        logger.debug("[BreezeTTS] numpy 不可用，无法转 float32")
        return None
    samples = decode_pcm_s16le(data)
    if not samples:
        return None
    return np.asarray(samples, dtype=np.float32)


def probe_service(timeout: float = PROBE_TIMEOUT) -> bool:
    """探测服务是否活着。未配置 / 不可达 / 报错 一律 False（不抛异常）。"""
    base = breeze_tts_url()
    if not base:
        return False
    try:
        import requests

        # 用根路径而不是 /v1/... ：只要能建立 HTTP 并被 FastAPI 处理，
        # 说明服务在跑（根路径返回 404 也算活）。比猜具体端点稳。
        resp = requests.get(base + "/", timeout=timeout)
        return resp.status_code < 500
    except Exception as exc:
        logger.debug("[BreezeTTS] 服务探测失败（%s）：%s", base, exc)
        return False


def synthesize(
    text: str,
    *,
    instruction: str = "",
    ref_audio_path: str = "",
    ref_text: str = "",
    cfg_scale: Optional[float] = None,
    seed: Optional[int] = None,
    timeout: Optional[float] = None,
) -> Optional[Tuple[bytes, int]]:
    """请求 Breeze 合成，返回 ``(pcm_bytes, sample_rate)``；失败返回 None。

    三种模式由参数自动选择（与官方 README 一致）：
    - 只有 ``instruction``           → **Voice Design**（无参考音频，造音色）
    - ``ref_audio_path`` + ``ref_text``（无 instruction）→ **Voice Clone**
    - 两者都给                        → **Voice Direction**（克隆音色 + 导演情绪）

    服务不可达 / 非 200 / 空音频 ⇒ None（由上层回退，绝不造假）。
    """
    base = breeze_tts_url()
    if not base:
        logger.debug("[BreezeTTS] 未配置 %s，跳过", ENV_URL)
        return None
    body = (text or "").strip()
    if not body:
        return None

    data = {
        "text": body,
        "cfg_scale": str(cfg_scale if cfg_scale is not None else breeze_cfg_scale()),
    }
    if seed is not None:
        data["seed"] = str(seed)
    if (instruction or "").strip():
        data["instruction"] = instruction.strip()
    if (ref_text or "").strip():
        data["ref_text"] = ref_text.strip()

    files = None
    ref = (ref_audio_path or "").strip()
    if ref:
        if not os.path.isfile(ref):
            logger.warning("[BreezeTTS] 参考音频不存在：%s（降级为 Voice Design）", ref)
        else:
            try:
                fh = open(ref, "rb")
                files = {"ref_audio": (os.path.basename(ref), fh)}
            except OSError as exc:
                logger.warning("[BreezeTTS] 参考音频打不开：%s（%s）", ref, exc)
                files = None

    try:
        import requests

        resp = requests.post(
            base + "/v1/audio/speech",
            data=data,
            files=files,
            timeout=timeout or breeze_timeout(),
            stream=True,
        )
        if resp.status_code != 200:
            logger.warning(
                "[BreezeTTS] 合成失败 HTTP %s：%s",
                resp.status_code,
                (resp.text or "")[:200],
            )
            return None
        # 流式响应：逐块收齐（本调用方要完整音频，不做边收边播）
        chunks = []
        for chunk in resp.iter_content(chunk_size=16384):
            if chunk:
                chunks.append(chunk)
        pcm = b"".join(chunks)
        if len(pcm) < 480:  # 24kHz s16le 下不足 10ms，视为空音频
            logger.warning("[BreezeTTS] 返回空音频（%d 字节）", len(pcm))
            return None
        return pcm, OUTPUT_SAMPLE_RATE
    except Exception as exc:
        logger.warning("[BreezeTTS] 调用异常：%s", exc)
        return None
    finally:
        if files:
            for _name, (fname, fh) in files.items():
                try:
                    fh.close()
                except Exception:
                    logger.debug("[BreezeTTS] 关闭参考音频句柄失败：%s", fname, exc_info=True)
