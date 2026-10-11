"""
文本生剧本引擎 —— LibTV 对标补强 刀2a（2026-10-12）
================================================
背景：LibTV v1.5 五大独家之首「剧本原创与改编」。对标核对我方 LLM 剧本生成
**早已存在**（director_skill._generate_script，2026-09-24 起），但埋在 Skill
步骤里 —— 只有跑整条导演技能才用得上，Agent 侧没有独立入口。

本模块把剧本生成抽成**单一真源**的引擎函数：
  - DirectorSkill 步骤 1 改为薄委托（行为零变化，test_director_timeline_apply 回归）
  - 新 Agent 能力 `pipeline.script_write` 直接调用本函数
  - 将来画布 ScriptNode 的 UI 入口也接这里（不再从 Skill 里抄）

三级降级：云 → Ollama 本地 → 模板占位（与 Skill 原行为一致）；
模板降级时 `fallback=True` **如实标注**，绝不把占位剧本说成 LLM 原创。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 与 DirectorSkill 原版完全一致的系统提示词（迁移，不改写）
_SYSTEM_PROMPT = (
    "你是专业短视频编剧。根据用户主题创作 30 秒短视频剧本，"
    "包含 3-5 个场景，每场景标注：场景描述、对白、动作、时长。"
    "输出纯文本，不要 Markdown 代码块。"
)


def fallback_script(topic: str) -> str:
    """LLM 不可用时的占位剧本（与 DirectorSkill 原实现一致，迁移不改写）。"""
    return (
        f"# {topic}\n\n"
        "【场景1 · 0-5s · 开场】\n"
        "动作：镜头从远景推近，展现主体。\n"
        "对白：今天，带你看一个不一样的故事。\n\n"
        "【场景2 · 5-20s · 主体展示】\n"
        "动作：特写镜头，展示核心内容。\n"
        "对白：这就是主角，专注每一个细节。\n\n"
        "【场景3 · 20-30s · 收尾】\n"
        "动作：镜头拉远，定格。\n"
        "对白：感谢观看，期待下次相遇。\n"
    )


def write_script(
    topic: str,
    duration_seconds: int = 30,
    scene_count: Optional[int] = None,
    style: str = "",
) -> Dict[str, Any]:
    """主题/梗概 → LLM 完整剧本（场景/对白/动作/时长）。

    三级降级：云 → Ollama → 模板。**绝不抛异常**，降级时 fallback=True 如实标注。

    返回::

        {"ok", "script", "fallback", "source"}  # source: "llm" | "template"
    """
    topic = (topic or "").strip() or "30秒短视频"
    sys_prompt = _SYSTEM_PROMPT
    if duration_seconds != 30 or scene_count or style:
        sys_prompt = (
            f"你是专业短视频编剧。根据用户主题创作 {duration_seconds} 秒短视频剧本，"
            f"包含 {scene_count or '3-5'} 个场景，每场景标注：场景描述、对白、动作、时长。"
            f"风格要求：{style or '不限'}。"
            "输出纯文本，不要 Markdown 代码块。"
        )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"主题：{topic}\n\n请创作剧本。"},
    ]
    try:
        from app.core.ai_engine import AIEngine
        engine = AIEngine()
        full = ""
        for chunk in engine.chat_with_fallback(
            messages,
            template=lambda: fallback_script(topic),
        ):
            full += chunk
        is_fallback = not full.strip()
        full = full.strip() or fallback_script(topic)
        return {
            "ok": True,
            "script": full,
            "fallback": is_fallback,
            "source": "template" if is_fallback else "llm",
        }
    except Exception as e:
        logger.debug("[script_writer] LLM 剧本生成异常，走模板降级", exc_info=True)
        return {
            "ok": True,
            "script": fallback_script(topic),
            "fallback": True,
            "source": "template",
            "error": str(e),
        }
