# -*- coding: utf-8 -*-
"""视觉 backend 抽象 —— 本地 Ollama 保底，云端多模态显式可选。

现状与缺口（2026-11-14 核实）
----------------------------
``canvas_shot_vision._ask_vision`` 硬编码 Ollama：``client.chat(..., images=base64,
format="json")``。云端侧虽有 DeepSeek（``providers.py:30``）与火山方舟
（``providers.py:89``）两条 OpenAI 兼容通道，但**理解侧没有图片输入通道**
（现有 image 相关调用都在生成侧）。本模块补的就是这个 backend 抽象。

关于 DeepSeek-V4.1-Flash（已核实，勿凭印象）
-------------------------------------------
· 模型原生输入模态是 **Text + Image**，不是视频流。
· 「视频理解」是**火山方舟平台侧增强**：Files Id 上传、单视频 ≤50MB、平台抽帧
  （抽帧策略同 doubao-seed-2.0）；DeepSeek 官网/阿里云百炼列的是 Text+Image。
⇒ 无论本地还是云端，本质都是「抽帧序列 + 文本时序推理」。本模块因此按**帧**接口设计，
  不假装能把视频当连续时序直接喂进去。

成本与出域纪律（用户明确要求：别上来就搞用不起的）
-------------------------------------------------
· 默认 ``OllamaVisionBackend``：全本地、零费用、素材不出机。
· 云端必须同时满足：环境变量 ``SHIGUANG_VISION_CLOUD=1``（显式授权出域）
  + 显式配置 API Key。缺任一项直接诚实拒绝，不偷偷降级、也不偷偷上传。
· ``sample_frames`` 做分层采样：每镜最多 N 帧、单次调用总帧数封顶，
  避免整片逐帧喂模型烧钱。
· 每次调用记录真实 usage（拿不到就记 0，不估算、不填假数）。

加固（云端返回不可信）
----------------------
· 不依赖 ``format="json"``：部分渠道不支持 schema 强制 JSON，自己解析 + 校验 + 重试。
· 思考模型默认开思考且思考占 ``max_tokens`` ⇒ 预算小会「正文为空但仍计费」，
  这里显式检测空 content / 非空 reasoning_content，并返回明确错误而非静默 None。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "VisionResult",
    "VisionBackend",
    "OllamaVisionBackend",
    "OpenAIVisionBackend",
    "parse_json_object",
    "sample_frames",
    "default_backend",
]

# 火山方舟的 DeepSeek-V4.1-Flash 是已核实支持图像/视频理解的渠道；
# 可用 SHIGUANG_VISION_BASE_URL 覆盖成任意 OpenAI 兼容网关（含自托管/百炼）。
DEFAULT_CLOUD_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_CLOUD_MODEL = "deepseek-v4-1-flash-261017"
_DEFAULT_MAX_TOKENS = 4096          # 思考模型给足，避免空正文仍计费
_MIN_SAFE_MAX_TOKENS = 2048
_JSON_RETRY = 2
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)


@dataclass
class VisionResult:
    """一次视觉调用的可审计结果。失败原因如实回传，绝不伪装成模型判断。"""

    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    source: str = "local"           # local / cloud / unavailable
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    degraded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "data": dict(self.data), "error": self.error,
            "source": self.source, "model": self.model,
            "usage": dict(self.usage), "degraded": self.degraded,
        }


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从模型回复里稳健取 JSON 对象。

    兼容：```json 围栏、前后解释文字、尾部多余字符。失败返回 None（不猜、不补字段）。
    """
    if not text or not text.strip():
        return None
    raw = text.strip()
    fenced = _FENCE_RE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    start = raw.find("{")
    if start < 0:
        return None
    raw = raw[start:]
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def sample_frames(
    frames: Sequence[bytes],
    *,
    max_frames: int = 2,
) -> List[bytes]:
    """分层采样：保留首帧与末帧，中间均匀抽。空帧直接丢弃。"""
    valid = [f for f in frames if f]
    limit = max(1, int(max_frames))
    if len(valid) <= limit:
        return list(valid)
    if limit == 1:
        return [valid[0]]
    idx = [round(i * (len(valid) - 1) / (limit - 1)) for i in range(limit)]
    picked: List[bytes] = []
    seen = set()
    for i in idx:
        if i not in seen:
            seen.add(i)
            picked.append(valid[i])
    return picked


class VisionBackend(ABC):
    """视觉理解后端。``ask`` 兼容既有 ``_ask_vision`` 的 dict/None 契约。"""

    name: str = "base"
    source: str = "local"
    model: str = ""
    supports_video_input: bool = False   # 是否支持直接上传视频文件（平台侧能力）

    @abstractmethod
    def ask_detailed(
        self,
        model: str,
        frames: Sequence[bytes],
        prompt: str,
    ) -> VisionResult:
        """带完整错误与用量的调用。实现方不得抛异常到调用链。"""

    def ask(self, model: str, frames: Sequence[bytes], prompt: str) -> Optional[Dict[str, Any]]:
        """兼容 ``canvas_shot_vision._ask_vision``：成功返回 dict，失败返回 None。"""
        try:
            res = self.ask_detailed(model, frames, prompt)
        except Exception as e:  # backend 边界：任何异常都不外溢到拉片链
            logger.debug("[vision-backend] %s 调用异常：%s", self.name, e, exc_info=True)
            return None
        if not res.ok:
            logger.debug("[vision-backend] %s 不可用：%s", self.name, res.error)
            return None
        return res.data


class OllamaVisionBackend(VisionBackend):
    """复用 ``canvas_shot_vision`` 既有的本地 Ollama 客户端，行为与改造前一致。"""

    name = "ollama"
    source = "local"

    def __init__(self, model: str = "", *, max_frames: int = 2) -> None:
        self.model = str(model or "")
        self.max_frames = max(1, int(max_frames))

    def ask_detailed(
        self,
        model: str,
        frames: Sequence[bytes],
        prompt: str,
    ) -> VisionResult:
        picked = sample_frames(frames, max_frames=self.max_frames)
        if not picked:
            return VisionResult(ok=False, error="无可用帧", source="local", model=model)
        try:
            from app.core.canvas_shot_vision import _ollama_client
        except ImportError:
            try:
                from core.canvas_shot_vision import _ollama_client  # type: ignore
            except ImportError as e:
                return VisionResult(ok=False, error=f"本地视觉客户端不可用：{e}", source="local")
        try:
            client = _ollama_client()
            images = [base64.b64encode(f).decode("ascii") for f in picked]
            parts = list(client.chat(
                model or self.model,
                [{"role": "user", "content": prompt}],
                stream=False, think=False, images=images, format="json",
            ))
            text = "".join(str(p) for p in parts).strip()
        except Exception as e:
            logger.debug("[vision-backend] Ollama 调用失败：%s", e, exc_info=True)
            return VisionResult(ok=False, error=f"{type(e).__name__}: {e}", source="local", model=model)
        data = parse_json_object(text)
        if data is None:
            return VisionResult(
                ok=False, error="本地视觉模型未返回可解析 JSON", source="local",
                model=model, degraded=True,
            )
        return VisionResult(ok=True, data=data, source="local", model=model or self.model)


class OpenAIVisionBackend(VisionBackend):
    """OpenAI 兼容多模态网关（DeepSeek-V4.1-Flash / 方舟 / 百炼 / 自托管）。

    **默认拒绝出域**：``allow_upload=False`` 时 ``ask`` 直接返回不可用，
    必须显式构造为 True（或走 ``from_env`` 且设置了 ``SHIGUANG_VISION_CLOUD=1``）。
    """

    name = "openai-compatible"
    source = "cloud"

    def __init__(
        self,
        *,
        base_url: str = "",
        api_key: str = "",
        model: str = DEFAULT_CLOUD_MODEL,
        allow_upload: bool = False,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        max_frames_per_call: int = 2,
        timeout: float = 90.0,
        temperature: float = 0.2,
    ) -> None:
        self.base_url = str(base_url or DEFAULT_CLOUD_BASE_URL).rstrip("/")
        self.api_key = str(api_key or "")
        self.model = str(model or DEFAULT_CLOUD_MODEL)
        self.allow_upload = bool(allow_upload)
        self.max_tokens = max(_MIN_SAFE_MAX_TOKENS, int(max_tokens))
        self.max_frames_per_call = max(1, int(max_frames_per_call))
        self.timeout = float(timeout)
        self.temperature = float(temperature)
        self.last_usage: Dict[str, int] = {}

    @classmethod
    def from_env(cls) -> "OpenAIVisionBackend":
        """按环境变量构造。注意：``SHIGUANG_VISION_CLOUD=1`` 是出域的显式授权。"""
        return cls(
            base_url=os.getenv("SHIGUANG_VISION_BASE_URL", DEFAULT_CLOUD_BASE_URL),
            api_key=os.getenv("SHIGUANG_VISION_API_KEY", ""),
            model=os.getenv("SHIGUANG_VISION_MODEL", DEFAULT_CLOUD_MODEL),
            allow_upload=os.getenv("SHIGUANG_VISION_CLOUD", "0") == "1",
            max_tokens=int(os.getenv("SHIGUANG_VISION_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS))),
            max_frames_per_call=int(os.getenv("SHIGUANG_VISION_MAX_FRAMES", "2")),
        )

    def _availability_error(self) -> str:
        if not self.allow_upload:
            return "素材出域未获显式授权：需设置 SHIGUANG_VISION_CLOUD=1 并确认素材可上传"
        if not self.api_key:
            return "未配置 SHIGUANG_VISION_API_KEY（不猜凭据）"
        return ""

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        import requests
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if not isinstance(body, dict):
            raise RuntimeError("响应不是 JSON 对象")
        return body

    @staticmethod
    def _extract_message(body: Mapping[str, Any]) -> tuple[str, str, Dict[str, int]]:
        """返回 (content, reasoning, usage)。空正文 + 有思考 ⇒ 思考耗尽预算。"""
        usage_raw = body.get("usage") or {}
        usage = {
            "prompt_tokens": int(usage_raw.get("prompt_tokens") or 0),
            "completion_tokens": int(usage_raw.get("completion_tokens") or 0),
        }
        try:
            msg = (body.get("choices") or [])[0].get("message") or {}
        except (IndexError, AttributeError, TypeError):
            msg = {}
        content = str(msg.get("content") or "")
        reasoning = str(msg.get("reasoning_content") or msg.get("reasoning") or "")
        return content, reasoning, usage

    def ask_detailed(
        self,
        model: str,
        frames: Sequence[bytes],
        prompt: str,
    ) -> VisionResult:
        err = self._availability_error()
        if err:
            return VisionResult(ok=False, error=err, source="unavailable", model=self.model)
        picked = sample_frames(frames, max_frames=self.max_frames_per_call)
        if not picked:
            return VisionResult(ok=False, error="无可用帧", source="cloud", model=self.model)

        content_blocks: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for f in picked:
            content_blocks.append({
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(f).decode("ascii")},
            })
        base_payload = {
            "model": self.model,       # 忽略传入的本地模型名，云端 backend 自己决定模型
            "messages": [{"role": "user", "content": content_blocks}],
            "stream": False,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        last_error = "未知错误"
        usage: Dict[str, int] = {}
        for attempt in range(_JSON_RETRY):
            payload = dict(base_payload)
            if attempt:
                # 重试时收紧输出要求，不重新抽帧、不重复上传图片字节之外的内容
                payload["messages"] = [{
                    "role": "user",
                    "content": content_blocks + [{
                        "type": "text",
                        "text": "上一次输出不是合法 JSON。只输出一个 JSON 对象，不要任何解释文字。",
                    }],
                }]
            try:
                body = self._post(payload)
            except Exception as e:
                logger.debug("[vision-backend] 云端调用失败（第 %d 次）：%s", attempt + 1, e, exc_info=True)
                last_error = f"{type(e).__name__}: {e}"
                break
            content, reasoning, usage = self._extract_message(body)
            self.last_usage = usage
            if not content.strip():
                if reasoning.strip():
                    last_error = (
                        "思考耗尽 max_tokens：正文为空但仍计费，"
                        f"请提高 SHIGUANG_VISION_MAX_TOKENS（当前 {self.max_tokens}）"
                    )
                else:
                    last_error = "云端返回空正文（无 content 也无 reasoning_content）"
                break
            data = parse_json_object(content)
            if data is not None:
                return VisionResult(
                    ok=True, data=data, source="cloud", model=self.model, usage=usage,
                )
            last_error = "云端输出不是可解析的 JSON 对象"

        return VisionResult(
            ok=False, error=last_error, source="cloud", model=self.model,
            usage=usage, degraded=True,
        )


def default_backend() -> VisionBackend:
    """默认选路：优先本地 Ollama（免费、不出域）；仅显式授权时才上云。"""
    if os.getenv("SHIGUANG_VISION_CLOUD", "0") == "1":
        cloud = OpenAIVisionBackend.from_env()
        if not cloud._availability_error():
            return cloud
        logger.debug("[vision-backend] 云端未就绪，回退本地：%s", cloud._availability_error())
    return OllamaVisionBackend(model=os.getenv("SHIGUANG_VISION_LOCAL_MODEL", ""))
