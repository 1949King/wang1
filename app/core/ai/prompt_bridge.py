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


def sanitize_en(text: str) -> str:
    """从翻译输出里**剔掉中文片段、保留英文**（而不是整段丢弃）。

    为什么不能整段丢（2026-11-01 实测踩坑）：
    用户那句 200+ 字的长提示词，模型输出末尾带了几个中文词（"+空气刘海"之类），
    旧逻辑"含中文 ⇒ 整段作废" ⇒ 回退成原始中文 ⇒ CLIP 只画出"空店铺"，
    **人物完全消失**。丢一句坏掉的部分，好过丢掉整段好的。
    """
    raw = str(text or "").replace("\n", ",")
    keep = [seg.strip() for seg in raw.split(",") if seg.strip() and not has_cjk(seg)]
    out = ", ".join(keep).strip().strip(",")
    # 英文太少（<3 词）说明这段输出基本没用，宁可不要
    return out if len(out.split()) >= 3 else ""


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
        "options": {"temperature": 0.2, "num_predict": 420},
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
        raw_out = str(data.get("response") or "").strip().strip('"').strip()
        if not raw_out:
            logger.warning("[prompt_bridge] 翻译结果为空，保留原文")
            return ""
        # 纯英文：直接用；含中文：先清洗掉中文片段（保留英文），不要整段丢
        out = raw_out if not has_cjk(raw_out) else sanitize_en(raw_out)
        if not out:
            logger.warning("[prompt_bridge] 翻译结果清洗后无有效英文，保留原文")
            return ""
        logger.info("[prompt_bridge] 翻译完成 %.1fs（%s）：%s", time.time() - t0,
                    "原样" if out == raw_out else "已剔除中文片段", out[:80])
        return out
    except Exception as e:  # stability-gate: allow-swallow（翻译失败必须回落到原文）
        logger.warning("[prompt_bridge] 翻译失败（保留原文）：%s: %s", type(e).__name__, e)
        return ""


# ── 人种锚定（2026-11-01）──────────────────────────────────────────
# 为什么需要：SD1.5/SDXL 的底座先验来自 LAION 英文图文对，人像**默认偏西方面孔**；
# 中文「年轻女生」翻成 young woman 后没有任何地域线索 ⇒ 模型回落到先验（实测全是美式脸）。
# 本项目是中文短剧 ⇒ **默认锚定东亚面孔**；用户明确写欧美/西方时尊重用户。

_WEST_MARKERS = ("欧美", "西方", "白人", "外国", "金发", "碧眼", "混血", "俄式", "法式")
_EAST_MARKERS = ("中国", "亚洲", "东方", "东亚", "中式", "汉服", "古风", "国风",
                 "日系", "韩系", "古装", "旗袍", "唐装", "民国")
#: 英文侧已显式写了地域就不重复注入（避免 "East Asian chinese girl" 这种叠词）
_EN_EAST = ("east asian", "asian", "chinese", "japanese", "korean", "chinese girl")


def face_bias_mode() -> str:
    """人种锚定模式：`east_asian`（默认）/ `none`（关闭，完全交给模型先验）。"""
    raw = str(os.environ.get("SHIGUANG_FACE_BIAS", "east_asian")).strip().lower()
    return raw if raw in ("east_asian", "none") else "east_asian"


def detect_face_bias(text: str) -> str:
    """从**中文原文**判断用户想要哪类面孔：`west` / `east` / ``（未表态）。"""
    src = str(text or "")
    if any(m in src for m in _WEST_MARKERS):
        return "west"
    if any(m in src for m in _EAST_MARKERS):
        return "east"
    return ""


def apply_face_bias(en_prompt: str, zh_original: str) -> Tuple[str, str]:
    """给英文提示词补地域锚 + 返回要追加的负向词。

    返回 `(prompt, negative_extra)`；negative_extra 为空表示不动负向。
    规则：
      · 关闭 / 用户写了欧美 ⇒ 原样返回（尊重用户）；
      · 英文里已有 asian/chinese… ⇒ 只补负向（不叠词）；
      · 其余 ⇒ 句首加 "East Asian"（靠前的 token 权重高）+ 负向压 western。
    """
    src = str(en_prompt or "").strip()
    if not src or face_bias_mode() == "none":
        return src, ""
    want = detect_face_bias(zh_original) or "east"
    if want == "west":
        return src, ""
    neg = "western, caucasian, american, european face"
    low = src.lower()
    if any(k in low for k in _EN_EAST):
        return src, neg
    return "East Asian, " + src, neg


def cached_out(text: str) -> str:
    """已翻译过就返回英文（供调用方回报 `prompt_used`）；没翻过返回空串。"""
    return _CACHE.get(hashlib.sha1(str(text or "").encode("utf-8")).hexdigest(), "")


#: 英文提示词词数上限（CLIP 上下文 77 token，38 词是实测安全线）
MAX_EN_WORDS = 38


def cap_words(text: str, max_words: int = MAX_EN_WORDS) -> str:
    """按逗号边界截到 max_words 词以内。

    超了不会报错，CLIP 会**静默截断**（尾部关键词直接消失）——
    与其让模型随机丢，不如我们按"重要性排序"的逗号段落明确地丢。
    """
    parts = [p.strip() for p in str(text or "").split(",") if p.strip()]
    kept: list = []
    count = 0
    for part in parts:
        n = len(part.split())
        if count + n > max_words and kept:
            break
        kept.append(part)
        count += n
    return ", ".join(kept)


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
    out = cap_words(out)
    _CACHE[key] = out
    while len(_CACHE) > CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    info["translated"] = True
    return out, info
