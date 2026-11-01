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
)

GENRES: Dict[str, Dict[str, object]] = {
    "short_drama": {
        "label": "现代短剧",
        "extra": (
            "western face, caucasian, european features",
            "cartoon, anime, illustration, 3d render",
            "oversaturated, plastic skin, doll-like",
        ),
    },
    "ancient": {
        "label": "古装/国风",
        "extra": (
            "modern clothing, t-shirt, jeans, sneakers, sneaker, backpack",
            "western face, caucasian",
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
    chunks.extend(GENRES[key]["extra"])  # type: ignore[arg-type]
    chunks.extend(extra or ())
    seen = set()
    merged: List[str] = []
    for word in _split(chunks):
        low = word.lower()
        if low in seen:
            continue
        seen.add(low)
        merged.append(word)
    return ", ".join(merged)


def describe(genre: str = "") -> Dict[str, object]:
    """面板/诊断用：当前分档与词表（不含用户词）。"""
    key = genre or genre_override() or "short_drama"
    item = GENRES.get(key) or GENRES["short_drama"]
    return {
        "genre": key,
        "label": item["label"],
        "words": _split(list(BASE) + list(item["extra"])),  # type: ignore[arg-type]
    }
