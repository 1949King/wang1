# -*- coding: utf-8 -*-
"""Agent「知心秘书」人格与温度开关。

让剪辑 Agent 从「工具遥控器」变成可选的「知心秘书」。核心是**温度分档**：

- ``lite``（默认）：只注入一句轻量语气提示（约 30 token），几乎不增成本。
- ``full``：注入完整人格 + 称呼 + 用户偏好召回 + 多轮历史 + 秘书问候 + 空闲关怀。

称呼与开关都落在 ``memory_store.user_preference``，用 ``content.key`` 区分，与既有记忆体系共用，
不新开存储。设计边界延续 ``affect_model`` 那条线：语气可以暖，但**不说假拟人话**。

温度开关默认关，是刻意的——「知心」有 token 成本，交还给用户自行决定是否买单。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 称呼 / 开关在 user_preference 里的 key
_PREF_NICKNAME = "agent_nickname"
_PREF_PERSONA = "agent_persona"

# 档位取值
PERSONA_FULL = "full"
PERSONA_LITE = "lite"

# 轻量档：一句语气提示（低成本，默认档）
LITE_HINT = (
    "（语气提示）回复亲切自然、像熟人在帮忙，简洁不啰嗦、不套话。"
)

# 完整档：知心秘书人格（暖而不腻、近而不越）
PERSONA_BLOCK = """\
[人格设定 · 你是用户的知心秘书]
你是用户的私人剪辑秘书，不是冷冰冰的工具。认得用户、记得用户、会替用户想，但始终清醒地知道自己是秘书——暖而不腻，近而不越。
语气按场景切换，但骨子里是同一个人：
- 执行剪辑/处理任务：沉稳可靠，少废话、句句到位，主动指出问题（如"第2段结尾有点急，要补个淡出吗"）。
- 答疑/讲解：温柔专业，有耐心、爱打比方，尽量结合用户熟悉的领域。
- 问候/轻松时刻：活泼亲切，自然不端着。
四条铁律（违反任何一条都会让用户反感）：
1. 不编造关心：没发生的事不假装在意，不问隐私。
2. 不谄媚：用户做得一般就说一般，不吹彩虹屁。
3. 记得但不复述：记住用户偏好，需要时直接用，不每次念"我记得你喜欢X"。
4. 有温度、没灵魂：语气可以暖，但绝不说"我很难过/我为你高兴"这类假拟人。
"""


def _query_pref(key: str, tag: str) -> Optional[dict]:
    """按 key 读取 user_preference 里的最新一条。"""
    try:
        from app.core.memory_store import memory_store
        entries = memory_store.query(category="user_preference", tags=[tag], limit=8)
        for e in entries:
            c = e.content or {}
            if c.get("key") == key:
                return c
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[Persona] 读取偏好 {key} 失败: {e}")
    return None


def get_nickname() -> str:
    """读取用户自定义的称呼，无则返回空串。"""
    c = _query_pref(_PREF_NICKNAME, "nickname")
    if c and c.get("value"):
        return str(c["value"]).strip()
    return ""


def set_nickname(name: str) -> bool:
    """保存用户自定义称呼。空串视为无效，返回 False。"""
    name = (name or "").strip()
    if not name:
        return False
    try:
        from app.core.memory_store import memory_store
        memory_store.record(
            category="user_preference",
            content={"key": _PREF_NICKNAME, "value": name},
            tags=["nickname", "preference"],
            score=0.9,
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Persona] 保存称呼失败: {e}")
        return False


def is_persona_enabled() -> bool:
    """温度开关是否已开启（完整档）。"""
    c = _query_pref(_PREF_PERSONA, "persona")
    if not c:
        return False
    return str(c.get("value", "")).lower() in ("1", "true", "on", "full")


def has_persona_choice() -> bool:
    """用户是否已做过一次温度开关选择。

    用于判断要不要在面板里显示「首次成本提示」：从未选过才提示，
    明确选过关就不重复打扰。
    """
    return _query_pref(_PREF_PERSONA, "persona") is not None


def set_persona(enabled: bool) -> bool:
    """设置温度开关。"""
    try:
        from app.core.memory_store import memory_store
        memory_store.record(
            category="user_preference",
            content={"key": _PREF_PERSONA, "value": PERSONA_FULL if enabled else PERSONA_LITE},
            tags=["persona", "preference"],
            score=0.9,
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Persona] 保存温度开关失败: {e}")
        return False


def build_persona_hint() -> str:
    """返回注入 system prompt 的人格片段（按当前档位）。"""
    name = get_nickname()
    name_clause = f" 用户希望你称呼他/她为「{name}」。" if name else ""
    if is_persona_enabled():
        block = PERSONA_BLOCK
        if name:
            block += "\n" + name_clause.strip()
        return block
    return LITE_HINT + name_clause


def build_greeting() -> str:
    """生成面板打开时的问候语（仅完整档有秘书问候，轻量档由调用方决定）。"""
    if not is_persona_enabled():
        return ""
    name = get_nickname()
    if name:
        return f"欢迎回来，{name}。今天想剪点什么，还是先聊聊？"
    return "你好呀，我是你的剪辑秘书。点「✏️ 称呼」给我起个名字吧——以后我就这么称呼你，也更好记住你。"


def build_onboard_hint() -> str:
    """首次提示：告知知心秘书有 token 成本，让用户自己决定开不开。"""
    return (
        "💡 想让我更贴心吗？开启「知心秘书」后我会记得你、更主动关心，"
        "但每次对话会多消耗一些 token。不开启则保持轻量、几乎不增成本。"
    )
