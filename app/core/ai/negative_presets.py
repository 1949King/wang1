# -*- coding: utf-8 -*-
"""分档负面词库（2026-11-01 · B 项）—— 按题材给 negative prompt，而不是一句通用词。

## 为什么需要分档

负面词不是"越多越好"：写一堆通用词（bad anatomy / lowres / watermark）只能压住**画坏**，
压不住**画歪**。真正影响观感的是题材错位：
  · 古装戏里出运动鞋、现代衬衫；
  · 职场戏里出校服、卡通背景；
  · 短剧里出欧美脸（底座先验）。
这些只能靠**题材专属词**压。

## 分档与合并规则

| 分档 | 何时生效 |
|---|---|
| base | 永远（低质/畸形/水印/文字） |
| short_drama | 默认（现代中文短剧） |
| ancient | 提示词含 古装/汉服/古风/仙侠/武侠/宫廷 |
| office | 含 职场/西装/办公/都市/通勤 |
| anime | 含 二次元/动漫/漫画/Q版/插画风 |
| product | 含 产品/商品/静物/电商/海报 |

**去重**：合并时按词条去重（大小写不敏感），避免同一句里重复出现 bad hands。
**用户优先级**：用户显式传的 negative 永远保留，不被覆盖。
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, List

#: 永远生效的"画坏"压制（与题材无关）
BASE = (
    "lowres, low quality, worst quality, blurry, jpeg artifacts",
    "bad anatomy, bad hands, extra fingers, extra limbs, fused fingers",
    "watermark, signature, text, logo, username",
    # 2026-11-12 用户反馈"恐怖谷"：老人/近景脸最容易出蜡像感、五官不对称、比例畸变
    "waxy skin, plastic skin, uncanny valley, doll-like, asymmetric face",
    "distorted facial features, disproportionate features, malformed eyes",
)

#: CLIP 上下文 77 token 是硬上限；74 是实测留余量的安全线（1 个逗号片段 ≈ 词数+1 token）
MAX_NEG_TOKENS_EST = 74

#: 人种相关词：命中即视为「anchor 段」，在 build_negatives 里前置（丢了会直接跑成欧美脸）
_ETHNIC_WORDS = ("western", "caucasian", "european", "american", "african", "asian")


def _is_ethnic(segment: str) -> bool:
    low = str(segment or "").lower()
    return any(w in low for w in _ETHNIC_WORDS)


GENRES: Dict[str, Dict[str, object]] = {
    "short_drama": {
        "label": "现代短剧",
        # ★ 2026-11-01：人种负向词**只在 prompt_bridge.apply_face_bias 一处**出
        #   （`western, caucasian, american, european face`）。此前这里也写了一份
        #   `western face, caucasian, european features`，两处语义相同、字面不同 ⇒
        #   去重逻辑（按逗号拆）去不掉，负向总长 80 token 超 CLIP 上限 77，
        #   尾部 `western, american, european face` 被**静默截断**。
        "extra": (
            "cartoon, anime, illustration, 3d render",
            "oversaturated, plastic skin, doll-like",
        ),
    },
    "ancient": {
        "label": "古装/国风",
        "extra": (
            "modern clothing, t-shirt, jeans, sneakers, sneaker, backpack",
            "modern city, car, phone, watch, glasses",
        ),
    },
    "office": {
        "label": "都市职场",
        "extra": (
            "school uniform, cosplay, fantasy costume",
            "cartoon, anime, illustration",
            "messy room, cluttered background",
        ),
    },
    "anime": {
        "label": "二次元",
        "extra": (
            "photorealistic, photo, realistic skin texture",
            "extra fingers, bad hands",
        ),
    },
    "product": {
        "label": "产品/静物",
        "extra": (
            "person, people, human, hands",
            "busy background, cluttered",
        ),
    },
}

#: 题材关键词 → 分档（顺序敏感：先匹配到的赢）
_HINTS = (
    ("ancient", ("古装", "汉服", "古风", "仙侠", "武侠", "宫廷", "朝代", "民国", "旗袍")),
    ("anime", ("二次元", "动漫", "漫画", "Q版", "插画", "赛璐璐")),
    ("product", ("产品", "商品", "静物", "电商", "海报", "包装")),
    ("office", ("职场", "西装", "办公", "都市", "通勤", "白领")),
)


def guess_genre(text: str) -> str:
    """按提示词猜分档；猜不到给 short_drama（本项目主场景）。"""
    src = str(text or "")
    for genre, keys in _HINTS:
        if any(k in src for k in keys):
            return genre
    return "short_drama"


def genre_override() -> str:
    """环境变量 SHIGUANG_NEGATIVE_GENRE 可强制指定；非法值忽略。"""
    raw = str(os.environ.get("SHIGUANG_NEGATIVE_GENRE", "")).strip().lower()
    return raw if raw in GENRES else ""


def _split(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    for chunk in items:
        for part in str(chunk or "").split(","):
            p = part.strip()
            if p:
                out.append(p)
    return out


def build_negatives(
    *,
    prompt: str = "",
    genre: str = "",
    user_negative: str = "",
    extra: Iterable[str] = (),
) -> str:
    """合成最终负向提示词（去重、保序：用户 → base → 题材 → extra）。"""
    key = (genre or genre_override() or guess_genre(prompt))
    if key not in GENRES:
        key = "short_drama"
    chunks: List[str] = []
    if str(user_negative or "").strip():
        chunks.append(str(user_negative))
    chunks.extend(BASE)
    # ★ 2026-11-01：人种锚定段**前置**。它由 prompt_bridge.apply_face_bias 作为 extra
    #   传进来，原本排在末尾 —— 一旦总长超 CLIP 的 77 token 就会被静默截掉，
    #   而「人脸跑成欧美」比「皮肤塑料感」严重得多，顺序必须体现这个优先级。
    _ethnic: List[str] = []
    _rest: List[str] = []
    for seg in (extra or ()):
        (_ethnic if _is_ethnic(seg) else _rest).append(seg)
    chunks.extend(_ethnic)
    chunks.extend(GENRES[key]["extra"])  # type: ignore[arg-type]
    chunks.extend(_rest)
    seen = set()
    merged: List[str] = []
    for word in _split(chunks):
        low = word.lower()
        if low in seen:
            continue
        seen.add(low)
        merged.append(word)
    # ★ 硬上限守卫：CLIP 只吃 77 token，超了 diffusers **静默截断**（不报错、无提示）。
    #   实测 1 个逗号片段 ≈ 词数+1 个 token（60 词 ≈ 80 token）⇒ 74 是留余量的安全线。
    kept: List[str] = []
    est = 0
    for word in merged:
        cost = len(word.split()) + 1
        if kept and est + cost > MAX_NEG_TOKENS_EST:
            break
        kept.append(word)
        est += cost
    return ", ".join(kept)


def describe(genre: str = "") -> Dict[str, object]:
    """面板/诊断用：当前分档与词表（不含用户词）。"""
    key = genre or genre_override() or "short_drama"
    item = GENRES.get(key) or GENRES["short_drama"]
    return {
        "genre": key,
        "label": item["label"],
        "words": _split(list(BASE) + list(item["extra"])),  # type: ignore[arg-type]
    }
