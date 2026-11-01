# -*- coding: utf-8 -*-
"""人物卡 → 英文提示词（2026-11-01 · C 项）。

## 为什么不是"提示词模板填空"

自由提示词的老问题：同一个角色，这次写"黑长直"，下次写"黑色长直发"，出图就不一致。
人物卡把"会变的那几个维度"（发型/服装/年龄/气质）变成**结构化字段**，
每次生成由代码按**固定顺序**拼成英文 —— 顺序固定，SD 的注意力分配才稳定。

## 排序规则（与 CLIP 77 token 截断对齐）

    主体（性别/年龄/人种） → 发型/五官 → 服装 → 动作/道具 → 场景 → 光照 → 风格

越靠前权重越高。字段为空就跳过；总长度超过 MAX_WORDS 时**从尾部裁**（风格词最先牺牲）。

## 与其它模块的关系

- 中文自由文本仍走 prompt_bridge 翻译；
- 人物卡**优先于**自由文本里的对应描述（卡是结构化真源）；
- 人种仍走 prompt_bridge.apply_face_bias 的同一套规则（卡里显式写了就用卡的）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

#: 单词数上限：CLIP 上下文 77 token，38 词是保守安全线（实测）
MAX_WORDS = 38

#: 字段顺序（决定提示词里的权重）
FIELD_ORDER = (
    "ethnicity", "gender", "age", "hair", "face", "outfit", "pose", "prop",
    "setting", "lighting", "mood", "style",
)

#: 中文值 → 英文（只覆盖最常写的枚举；未命中按原样透传，由调用方保证是英文/翻过）
VALUES: Dict[str, str] = {
    "女": "young woman", "女生": "young woman", "女性": "woman", "男": "young man",
    "男生": "young man", "男性": "man", "少女": "teenage girl", "少年": "teenage boy",
    "儿童": "child", "老人": "elderly person", "中年": "middle-aged person",
    "东亚": "East Asian", "中国": "Chinese", "亚洲": "Asian",
    "欧美": "western", "西方": "western",
    "黑色长直发": "long straight black hair", "黑长直": "long straight black hair",
    "空气刘海": "air bangs", "齐刘海": "blunt bangs", "短发": "short hair",
    "马尾": "ponytail", "丸子头": "bun hairstyle", "卷发": "curly hair",
    "染发": "dyed hair", "银发": "silver hair",
    "米白色宽松长袖衬衫": "beige loose long-sleeve shirt",
    "白衬衫": "white shirt", "西装": "suit", "汉服": "hanfu", "旗袍": "qipao",
    "连衣裙": "dress", "针织衫": "knit sweater", "校服": "school uniform",
    "休闲装": "casual outfit",
    "文创店": "indoor cultural creative shop", "办公室": "office",
    "咖啡馆": "cafe", "街道": "street", "卧室": "bedroom", "教室": "classroom",
    "古建筑": "ancient architecture", "宫殿": "palace",
    "柔和室内灯光": "soft indoor lighting", "暖光": "warm lighting",
    "自然光": "natural light", "逆光": "backlight", "昏暗": "dim lighting",
    "温馨": "cozy atmosphere", "冷峻": "cold mood", "清新": "fresh mood",
    "写实": "photorealistic", "电影感": "cinematic", "胶片": "film grain",
    "二次元": "anime style", "国风": "chinese style", "水彩": "watercolor",
    # 姿态/动作（2026-11-01 实测漏了这些：中文会原样漏进英文提示词 = 噪音）
    "侧身回眸": "looking back over shoulder", "回眸": "looking back", "侧身": "side profile",
    "正视镜头": "facing camera", "微笑": "smiling", "行走": "walking", "坐下": "sitting",
    "站立": "standing", "低头": "head slightly down", "双手捧杯": "holding mug with both hands",
}


def _en(value: Any) -> str:
    """值 → 英文短语；字典查不到就原样用（允许直接传英文）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    return VALUES.get(text, text)


def normalize_card(card: Optional[dict]) -> Dict[str, str]:
    """只保留已知字段 + 值转英文短语；未知字段丢弃（避免拼进噪音词）。"""
    if not isinstance(card, dict):
        return {}
    out: Dict[str, str] = {}
    for key in FIELD_ORDER:
        val = _en(card.get(key))
        if val:
            out[key] = val
    return out


def _translate_remaining(text: str) -> str:
    """卡里出现字典没收录的中文值时，整体交给 prompt_bridge 翻。

    不做这一步的后果（2026-11-01 实测）：'侧身回眸' 原样进英文提示词，
    CLIP 对中文 token 只会当噪音 —— 用户以为写了姿态，模型完全没看到。
    """
    try:
        from app.core.ai import prompt_bridge as PB

        if not PB.has_cjk(text):
            return text
        out = PB.translate(text)
        return out or text
    except Exception:  # stability-gate: allow-swallow（翻译不可用就保留原文，不阻塞）
        return text


def render_prompt(card: Optional[dict], *, extra: str = "", max_words: int = MAX_WORDS) -> str:
    """人物卡 → 英文提示词。

    extra：额外追加（通常是已翻译的自由文本/风格词），排最后、会被裁。
    """
    fields = normalize_card(card)
    parts: List[str] = [fields[k] for k in FIELD_ORDER if k in fields]
    if str(extra or "").strip():
        parts.append(str(extra).strip().strip(","))
    merged = ", ".join(p for p in parts if p)
    merged = _translate_remaining(merged)
    words = [w for w in merged.replace(",", " ").split() if w]
    if len(words) <= max_words:
        return merged
    # 超长从尾部裁：风格/氛围优先牺牲（它们在 CLIP 里权重最低、对主体影响最小）
    kept: List[str] = []
    count = 0
    for part in parts:
        part_words = [w for w in part.replace(",", " ").split() if w]
        if count + len(part_words) > max_words:
            break
        kept.append(part)
        count += len(part_words)
    return ", ".join(kept)


def has_card(card: Optional[dict]) -> bool:
    return bool(normalize_card(card))
