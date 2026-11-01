# -*- coding: utf-8 -*-
"""提示词桥：把中文提示词翻成英文再喂给本地 SD 系引擎（2026-11-01）。

## 为什么必须有这一步（这不是"锦上添花"）

SD1.5 / SDXL 的文本编码器是 **CLIP（英文语料训练）**。中文提示词进去后，
CLIP 只能抓到零散 token ⇒ 画面"大概是个室内场景"但**细节全丢**。
实测案例：用户写了「黑色长直发的年轻女生，双手捧浅棕色马克杯，文创店」，
出图是一张**空店铺**（人没有出现）—— 这不是模型坏了，是它没读懂。

本机 Ollama（qwen3.5:4b）离线可用，实测一次翻译 **~0.9s**（模型已载）：
```
中文：一位留着黑色长直发的年轻女生，站在文创店里，双手捧着一个浅棕色马克杯，柔和室内灯光
英文：young woman with long straight hair, standing in a cultural creative shop,
      holding a light brown mug with both hands, soft indoor lighting, photorealistic, 8k
```

## 纪律（三条，都是"宁可不翻也不搞砸"）

1. **翻译失败绝不阻塞生成**：Ollama 不可用/超时 ⇒ 用原文 + 在返回值里说明"未翻译"，
   让用户知道为什么画面可能不跟；
2. **结果可审计**：响应带 `prompt_original` / `prompt_used` / `prompt_translated`，
   用户能一眼看出"送进模型的是什么"；
3. **可关闭**：`SHIGUANG_PROMPT_TRANSLATE=0` 直接关掉（离线排查/不想联网跑 LLM 时）。

## 边界

- 只对**本地 SD 系**（sd15/sdxl）生效；云端渠道（硅基/OpenAI）本来就支持中文，不翻；
- 视频族（SVD/Wan）先不动：SVD 不吃文本、Wan 用的是 UMT5（多语更好），换语义风险大于收益。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: 默认 Ollama 地址（与项目既有 ollama_config 一致）
DEFAULT_HOST = "http://127.0.0.1:11434"
#: 翻译超时（秒）。首次调用要载模型，给宽一点；失败只是不翻，不影响出图
DEFAULT_TIMEOUT = 60.0
#: LRU 上限（同一提示词反复点生成时省掉重复翻译）
CACHE_MAX = 64

_CACHE: Dict[str, str] = {}

#: 判断是否含 CJK 字符（中日韩统一表意文字 + 兼容区）
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

#: 关键约束：CLIP 的上下文是 **77 token**，超了会被**静默截断**（尾部关键词直接消失）。
#: 所以翻译必须"短且按重要性排序"——主语/动作/场景放前面，风格词放最后。
#: 实测：不限制长度时，翻译出来 ~60 词，「马克杯/店铺背景」这类靠后的元素会被截掉，
#: 出图是"女生 + 纯色背景"，与提示词不符。
_INSTRUCTION = (
    "Translate the Chinese image prompt below into ONE concise English Stable Diffusion prompt. "
    "Rules: (1) under 38 words total; (2) order by visual importance — main subject first, "
    "then clothing/pose, then setting/background, then lighting/mood, then style; "
    "(3) comma-separated keywords, no sentences; (4) output ONLY the prompt, "
    "no quotes, no explanation, no Chinese characters."
)


def enabled() -> bool:
    """总开关。默认开；`SHIGUANG_PROMPT_TRANSLATE=0` 关闭。"""
    return str(os.environ.get("SHIGUANG_PROMPT_TRANSLATE", "1")).strip().lower() not in ("0", "false", "off", "no")


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def _host() -> str:
    return str(os.environ.get("SHIGUANG_OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")


def _timeout() -> float:
    try:
        return max(3.0, float(os.environ.get("SHIGUANG_TRANSLATE_TIMEOUT") or DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def _pick_model() -> str:
    """优先用显式配置；否则取 Ollama 上第一个模型（/api/tags）。都没有返回空串。"""
    want = str(os.environ.get("SHIGUANG_TRANSLATE_MODEL") or "").strip()
    if want:
        return want
    try:
        import json
        import urllib.request

        with urllib.request.urlopen(_host() + "/api/tags", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        models = [str(m.get("name") or "") for m in (data.get("models") or []) if m.get("name")]
        return models[0] if models else ""
    except Exception:  # stability-gate: allow-swallow（探测失败 = 不翻译，绝不影响出图）
        logger.debug("[prompt_bridge] 读取 Ollama 模型列表失败", exc_info=True)
        return ""


def translate(text: str, *, model: str = "", timeout: Optional[float] = None) -> str:
    """调用本机 Ollama 翻译。失败返回空串（调用方据此保留原文）。"""
    src = str(text or "").strip()
    if not src or not has_cjk(src):
        return ""
    mid = model or _pick_model()
    if not mid:
        logger.info("[prompt_bridge] 无可用 Ollama 模型 ⇒ 跳过翻译（画面可能不跟提示词）")
        return ""
    body = {
        "model": mid,
        "prompt": _INSTRUCTION + "\n\n" + src,
        "stream": False,
        # qwen3.x 是混合推理模型：不关 think 的话 response 可能是空的（实测踩过）
        "think": False,
        "options": {"temperature": 0.2, "num_predict": 260},
    }
    try:
        import json
        import urllib.request

        req = urllib.request.Request(
            _host() + "/api/generate",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout or _timeout()) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        out = str(data.get("response") or "").strip().strip('"').strip()
        if not out or has_cjk(out):
            logger.warning("[prompt_bridge] 翻译结果不可用（空串或仍含中文），保留原文")
            return ""
        logger.info("[prompt_bridge] 翻译完成 %.1fs：%s", time.time() - t0, out[:80])
        return out
    except Exception as e:  # stability-gate: allow-swallow（翻译失败必须回落到原文）
        logger.warning("[prompt_bridge] 翻译失败（保留原文）：%s: %s", type(e).__name__, e)
        return ""


def cached_out(text: str) -> str:
    """已翻译过就返回英文（供调用方回报 `prompt_used`）；没翻过返回空串。"""
    return _CACHE.get(hashlib.sha1(str(text or "").encode("utf-8")).hexdigest(), "")


def prepare_for_local(prompt: str) -> Tuple[str, Dict[str, Any]]:
    """本地生图前处理：中文 ⇒ 英文。

    返回 `(prompt_for_engine, info)`；info 恒含：
      - `original`：原文
      - `translated`：是否真的翻译了
      - `reason`：没翻的原因（"已关闭"/"无中文"/"翻译失败"/"无本地模型"），翻成功为空
    """
    src = str(prompt or "")
    info: Dict[str, Any] = {"original": src, "translated": False, "reason": ""}
    if not enabled():
        info["reason"] = "已关闭（SHIGUANG_PROMPT_TRANSLATE=0）"
        return src, info
    if not has_cjk(src):
        info["reason"] = "无中文，无需翻译"
        return src, info

    key = hashlib.sha1(src.encode("utf-8")).hexdigest()
    hit = _CACHE.get(key)
    if hit:
        info.update({"translated": True, "reason": "", "cached": True})
        return hit, info

    out = translate(src)
    if not out:
        info["reason"] = "翻译失败（Ollama 不可用/超时/输出异常）"
        return src, info
    _CACHE[key] = out
    while len(_CACHE) > CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    info["translated"] = True
    return out, info
