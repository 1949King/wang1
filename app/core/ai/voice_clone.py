# -*- coding: utf-8 -*-
"""多角色音色库 + 声音克隆 + 情感解耦（2026-10-09，刀 T2 第一刀）。

为什么需要（对照 T0 核实）
========================
现有 `voice_generator.py` 的 `VoiceProfile` 是**枚举型声线**（gender×age×style 组合），
不是"每个角色一个真实音色"；`VoiceGenerationRequest.emotion` 字段**存在但引擎没消费**
（Coqui/gTTS/edge-tts 都不支持情感参数）—— 所以"情感解耦"目前是摆设。

本模块补三件事（**纯逻辑 + 契约先行，模型后装**）：
  ① **音色资产**（`VoiceAsset`）：一个角色绑定一个真实音色，音色可由参考音频克隆而来；
  ② **角色 ↔ 音色绑定**：纯函数 `bind/unbind_character_voice()`，在角色 dict 上加/删
     `voice_id` 字段 —— 这是 T4「一键换词重配」的前置（重配时要"按角色挑音色"）；
  ③ **情感解耦契约**：`EMOTIONS` 标签 + `build_voice_request()`（音色与情感分离传）。

⚠️ 诚实边界（本模块的红线）
==========================
· 克隆引擎（CosyVoice2 / IndexTTS-2）**未安装**时，`clone_voice()` **诚实失败**
  （返回 `{ok: False, reason}`），**绝不返回假音频、绝不用枚举声线冒充克隆结果**。
· 「角色↔音色」字段走**非 schema 资产字段**（`voice_id`），**不碰** `CHARACTER_FIELD_SCHEMA`
  的六处同步不变量（音色不是生图提示词字段，塞进去只会污染 `build_character_prompt`）。
  角色数据里本就有非 schema 字段 `id` 先例 ⇒ 加 `voice_id` 安全。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 情感标签（契约：音色与情感分离 —— 同一个角色音色，换情感只改这一个字段）
EMOTIONS: List[str] = [
    "neutral", "happy", "sad", "angry", "fearful", "surprised",
    "gentle", "excited", "cold", "panic",
]

# 角色 dict 上挂音色的字段名（非 schema 资产字段）
VOICE_FIELD = "voice_id"


@dataclass
class VoiceAsset:
    """一个音色资产（可绑定到一个角色，可由参考音频克隆而来）。

    serialization-field-symmetry：新增字段必须同步 to_dict / from_dict。
    """
    voice_id: str
    name: str
    character_id: Optional[str] = None        # 绑定角色（None = 未绑定）
    reference_audio: Optional[str] = None     # 克隆源音频（None = 未克隆，用默认音色）
    engine: str = ""                          # 实际克隆引擎（cosyvoice2/indextts2/...）；空 = 尚未生成
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VoiceAsset":
        return cls(
            voice_id=str(d.get("voice_id", "")),
            name=str(d.get("name", "")),
            character_id=d.get("character_id") or None,
            reference_audio=d.get("reference_audio") or None,
            engine=str(d.get("engine", "")),
            created_at=str(d.get("created_at", "")),
        )


# ── 角色 ↔ 音色绑定（纯函数，不碰六处同步不变量）────────────────────

def bind_character_voice(character: Dict[str, Any], voice_id: str) -> Dict[str, Any]:
    """把音色绑定到角色（**纯函数**）：在角色 dict 上加 `voice_id` 字段。

    不改原对象（返回浅拷贝）；`voice_id` 为空串 = 解绑语义（见 unbind）。
    """
    out = dict(character or {})
    if voice_id:
        out[VOICE_FIELD] = voice_id
    else:
        out.pop(VOICE_FIELD, None)
    return out


def unbind_character_voice(character: Dict[str, Any]) -> Dict[str, Any]:
    """解绑角色音色（**纯函数**）：移除 `voice_id` 字段。"""
    out = dict(character or {})
    out.pop(VOICE_FIELD, None)
    return out


def character_voice_id(character: Dict[str, Any]) -> Optional[str]:
    """读角色绑定的音色 id（无则 None）。"""
    v = (character or {}).get(VOICE_FIELD)
    return str(v) if v else None


# ── 声音克隆：契约 + 诚实失败 ─────────────────────────────────────

def clone_available() -> bool:
    """克隆引擎是否可 import（**只检测依赖，不下载模型**）。"""
    for mod in ("cosyvoice", "indextts"):
        try:
            __import__(mod)
            return True
        except Exception:
            continue
    return False


def clone_unavailable_reason() -> str:
    """诚实报告为什么不能克隆（给用户看的话）。"""
    if clone_available():
        return "克隆引擎已安装，但模型可能未下载；首次克隆会拉取模型（GB 级），请保证网络与磁盘。"
    return ("缺少本地声音克隆引擎（CosyVoice2 / IndexTTS-2）。"
            "安装后即可从参考音频克隆角色音色。"
            "在装好之前，本功能**诚实降级**为枚举声线，不会冒充克隆结果。")


def clone_voice(reference_audio: str, name: str,
                character_id: Optional[str] = None) -> Dict[str, Any]:
    """从参考音频克隆一个音色（**诚实失败**）。

    ⚠️ 引擎未装 ⇒ `{ok: False, available: False, reason}`；**绝不返回假音频**，
    也绝不拿枚举声线冒充"克隆成功"。模型接入是后续刀（与 funasr 一起统一安装）。
    """
    # 2026-10-09 优化：先验参考音频存在性 —— 文件不存在时给出**准确**的错误
    # （旧版会落进「引擎未装」的提示，把排查方向带偏）。
    import os
    if reference_audio and not os.path.isfile(reference_audio):
        return {"ok": False, "available": None,
                "reason": f"参考音频不存在：{reference_audio}", "asset": None}
    if not clone_available():
        return {"ok": False, "available": False,
                "reason": clone_unavailable_reason(), "asset": None}
    # 引擎在位时由后续刀实现真正的克隆（加载参考音频 → 提取声纹 → 注册音色）。
    # 这里保留契约：成功返回 {"ok": True, "asset": VoiceAsset(...)}。
    return {"ok": False, "available": True,
            "reason": "克隆引擎在库但尚未接线（后续刀实现）", "asset": None}


# ── 情感解耦：契约 ─────────────────────────────────────────────────

def build_voice_request(text: str, voice_id: str,
                        emotion: str = "neutral") -> Dict[str, Any]:
    """构造「音色 + 情感解耦」的配音请求（**纯函数**）。

    音色（voice_id）与情感（emotion）分开传：同一个角色音色，换情感只改 emotion。
    """
    emo = emotion if emotion in EMOTIONS else "neutral"
    return {"text": text, "voice_id": voice_id, "emotion": emo}
