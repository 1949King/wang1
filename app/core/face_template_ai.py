# -*- coding: utf-8 -*-
"""捏脸 AI 生成：提示词 → FaceParams 结构（2026-10-21）。

定位
====
「永劫无间式」捏脸的第三层：AI 生成新形象 / 补全细节。它只产出**参数结构**，
不生成图片、不落库 —— 前端拿到后走既有 normalizeFaceParams 再预览/保存。

三条纪律
========
1. 白名单：只接受 faceParams 的枚举 id 与色板值（直接从 canvas_bridge 的镜像表取全集），
   AI 乱给的值一律丢弃，不猜、不扩展；
2. 诚实失败：没有可用模型 / 解析不出 JSON / 没有任何可识别字段 ⇒ ok=False + 明确 message，
   绝不返回一份「假随机」参数冒充生成结果；
3. 纯函数：merge_and_validate() 不依赖网络，可单测（LLM 调用只在外层）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 枚举全集：直接复用 canvas_bridge 的镜像表（避免第二份白名单）
from app.core.canvas_bridge import (
    _FACE_ACCESSORY_LABELS,
    _FACE_BROW_LABELS,
    _FACE_EYE_COLOR_LABELS,
    _FACE_EYE_LABELS,
    _FACE_LIP_LABELS,
    _FACE_SKIN_LABELS,
)

#: 允许 AI 输出的枚举字段 → 合法取值集合
ENUM_FIELDS: Dict[str, set] = {
    "browStyle": set(_FACE_BROW_LABELS),
    "eyeStyle": set(_FACE_EYE_LABELS),
    "lipStyle": set(_FACE_LIP_LABELS),
    "hairAccessory": set(_FACE_ACCESSORY_LABELS),
    "eyeColor": set(_FACE_EYE_COLOR_LABELS),
    "eyeColorRight": set(_FACE_EYE_COLOR_LABELS),
}
#: 色板字段（只接受 hex）
PALETTE_FIELDS = {"skinTone": set(_FACE_SKIN_LABELS)}
#: 数值字段 → (下界, 上界)
NUM_FIELDS: Dict[str, Tuple[float, float]] = {
    "emotionIntensity": (0.0, 1.0),
    "browLift": (-1.0, 1.0),
    "eyeOpen": (0.0, 2.0),
    "mouthOpen": (0.0, 1.0),
    "mouthCurve": (-1.0, 1.0),
    "headWidth": (-1.0, 1.0),
    "headHeight": (-1.0, 1.0),
    "jawWidth": (-1.0, 1.0),
    "cheekbone": (-1.0, 1.0),
    "chin": (-1.0, 1.0),
}
COLOR_FIELDS = ("browColor", "blush", "eyeshadow", "lipColor", "accessoryColor", "accessoryColor2")

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# markdown 围栏用 chr(96) 构造，避免源码出现三个反引号
_FENCE_RE = re.compile(
    chr(96) * 3 + r"(?:json)?\s*(\{.*?\})\s*" + chr(96) * 3,
    re.DOTALL | re.IGNORECASE,
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _validate_fields(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    out: Dict[str, Any] = {}
    dropped: List[str] = []
    for key, value in data.items():
        if key in ENUM_FIELDS:
            if isinstance(value, str) and value in ENUM_FIELDS[key]:
                out[key] = value
            else:
                dropped.append(key)
        elif key in PALETTE_FIELDS:
            if isinstance(value, str) and value.lower() in PALETTE_FIELDS[key]:
                out[key] = value.lower()
            else:
                dropped.append(key)
        elif key in NUM_FIELDS:
            try:
                number = float(value)
            except (TypeError, ValueError):
                dropped.append(key)
                continue
            low, high = NUM_FIELDS[key]
            out[key] = _clamp(number, low, high)
        elif key in COLOR_FIELDS:
            if value is None:
                out[key] = None
            elif isinstance(value, str) and _HEX_RE.match(value):
                out[key] = value
            else:
                dropped.append(key)
        elif key == "emotion":
            if isinstance(value, str) and value:
                out[key] = value  # 表情 id 由前端 normalize 兜底（非视觉字段）
            else:
                dropped.append(key)
        else:
            # 未知字段：不采纳、不猜测，但计入 dropped 便于日志排查（不回传给前端 UI）
            dropped.append(key)
    return out, dropped


def merge_and_validate(raw: Any, base: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], List[str]]:
    """把 AI 输出收敛成合法 FaceParams 子集。

    返回 (params, dropped)：params 只含白名单内且合法的字段；dropped 是被丢弃的字段名。
    base（前端传入的模板参数）同样过白名单 —— 前端数据也不可信。
    """
    dropped: List[str] = []
    out: Dict[str, Any] = {}
    if isinstance(base, dict):
        safe_base, base_dropped = _validate_fields(base)
        out.update(safe_base)
        dropped.extend(base_dropped)
    if not isinstance(raw, dict):
        return out, dropped
    safe, field_dropped = _validate_fields(raw)
    out.update(safe)
    dropped.extend(field_dropped)
    return out, dropped


def build_messages(prompt: str) -> List[Dict[str, str]]:
    """构造给 LLM 的严格 JSON 指令（只描述可用取值，不夹带产品文案）。"""
    def keys(mapping: Dict[str, Any]) -> str:
        return "、".join(sorted(mapping.keys()))

    schema = (
        "只输出一个 JSON 对象，不要解释、不要 markdown 代码块。字段全部可选，只写你要改的：\n"
        f"- browStyle: {keys(_FACE_BROW_LABELS)}\n"
        f"- eyeStyle: {keys(_FACE_EYE_LABELS)}\n"
        f"- lipStyle: {keys(_FACE_LIP_LABELS)}\n"
        f"- hairAccessory: {keys(_FACE_ACCESSORY_LABELS)}\n"
        f"- eyeColor / eyeColorRight: {keys(_FACE_EYE_COLOR_LABELS)}\n"
        f"- skinTone: {keys(_FACE_SKIN_LABELS)}（十六进制色值）\n"
        "- 数值（-1~1 或 0~1）：emotionIntensity / browLift / eyeOpen / mouthOpen / mouthCurve / "
        "headWidth / headHeight / jawWidth / cheekbone / chin\n"
        "- 颜色（#rrggbb 或 null）：browColor / blush / eyeshadow / lipColor\n"
    )
    system = (
        "你是角色捏脸参数生成器。根据用户的中文描述，输出符合给定 schema 的 JSON。"
        "取值必须严格使用下列 id，不得自造；不确定的字段直接省略。\n" + schema
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从可能带解释/代码块的模型输出里取第一个 JSON 对象；失败返回 None。"""
    if not text:
        return None
    cleaned = text.strip()
    fence = _FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _chat_text(messages: Iterable[Dict[str, str]]) -> str:
    from app.core.ai_engine import AIEngine

    engine = AIEngine()
    chunks = list(engine.chat_with_fallback(list(messages), stream=False))
    return "".join(chunks)


def generate_face_params_from_prompt(prompt: str, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """对外入口：调 LLM → 解析 → 白名单校验。失败一律如实返回 ok=False。"""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "message": "请先描述想要的脸"}

    try:
        text = _chat_text(build_messages(prompt))
    except Exception as exc:  # 引擎异常要如实回报，不吞
        return {"ok": False, "message": f"AI 调用失败：{exc}"}

    if not text or "错误: 没有可用的 AI 提供者" in text:
        return {"ok": False, "message": "未配置可用的 AI 模型，请先到「模型广场」配置"}

    raw = extract_json(text)
    if raw is None:
        return {"ok": False, "message": "AI 返回的内容不是合法 JSON，请换个描述再试"}

    params, dropped = merge_and_validate(raw, base)
    if not params:
        return {"ok": False, "message": "AI 没有给出可识别的捏脸参数，请补充描述（如：猫眼、冷白皮、戴眼镜）"}

    return {"ok": True, "params": params, "dropped": dropped}
