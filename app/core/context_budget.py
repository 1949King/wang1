"""上下文预算：把「模型窗口」换算成「发给模型的消息字符上限」
================================================================

**背景（V4.33.4 的起因）**：`agent_context.compress_messages` 的 `max_chars` 曾**写死 12000 字符**
（按 `ai_engine._estimate_tokens` 的「中文 0.6 token/字」折算 ≈ **7200 token**），
**与接入的模型无关** —— 结果：

  * 接 **8K 窗口**模型：12000 字符 ≈ 7200 token 反而**偏大**（输入预算本就只剩几千）；
  * 接 **128K 窗口**模型：只占 **5.6%**，**白白浪费 94% 的窗口**。

本模块让预算**跟着模型走**：

  ==============================  ==============================================
  ``window_for(model, provider)``  查模型上下文窗口（token）；未知返回 ``None``
  ``chars_budget(window_tokens)``  窗口 → 安全的字符上限（预留输出与波动）
  ``resolve_max_chars(...)``       一步到位：显式 override > 窗口推导 > 保守默认
  ==============================  ==============================================

**保守默认**：查不到模型时返回 ``DEFAULT_MAX_CHARS = 12000`` —— 与改造前**完全一致**（零行为变化）。

设计纪律：只依赖标准库、不 import app 包（可脱离 Qt / 硬件探测单测）。
"""

from __future__ import annotations

from typing import Dict, Optional

# 保守默认：查不到模型窗口时用它 —— 与改造前的硬编码值一致，保证零行为变化
DEFAULT_MAX_CHARS = 12000

# 给「输出 + 波动」预留的 token（与 cloud_api / cloud_providers 的 max_tokens 默认 4096 对齐）
OUTPUT_RESERVE_TOKENS = 4096
# 最多只用窗口的这个比例（留 system 增长、消息头等开销余量）
MAX_USABLE_RATIO = 0.7
# token ↔ 字符换算：与 ai_engine._estimate_tokens 的「中文 ~0.6 token/字」对齐
#   1 字符 ≈ 0.6 token  ⇒  1 token ≈ 1.67 字符
CHARS_PER_TOKEN = 1.0 / 0.6
# 字符预算下限（避免小窗口模型算出个位数，反而让压缩无意义）
MIN_MAX_CHARS = 2000

# ── 常见模型的上下文窗口（token）──
# 匹配规则：把 model/provider 拼成小写串，**取最长匹配的键**（故更具体的键要先写）。
# ⚠️ 厂商会更新窗口值，此表可按需修正；查不到时一律走 DEFAULT_MAX_CHARS（安全）。
KNOWN_WINDOWS: Dict[str, int] = {
    # OpenAI
    "gpt-4o": 128000,
    "gpt-4.1": 1047576,
    "gpt-4-turbo": 128000,
    "gpt-4-32k": 32768,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    "gpt-3.5": 16385,
    "o1": 200000,
    "o3": 200000,
    "o4": 200000,
    # Anthropic
    "claude-3-5": 200000,
    "claude-3-7": 200000,
    "claude-3": 200000,
    "claude-2": 100000,
    "claude": 200000,
    # Google
    "gemini-1.5-pro": 2097152,
    "gemini-1.5-flash": 1048576,
    "gemini-1.5": 1048576,
    "gemini-2": 1048576,
    "gemini": 32768,
    # 国内
    "deepseek": 65536,
    "qwen-long": 10000000,
    "qwen": 131072,
    "glm": 131072,
    "moonshot": 131072,
    "kimi": 131072,
    "doubao": 32768,
    "ernie": 131072,
    "hunyuan": 32768,
    "minimax": 245760,
    "spark": 32768,
    "step": 32768,
    # 开源
    "llama-3.1": 131072,
    "llama-3": 131072,
    "mistral": 32768,
}


# ═══════════════════════════════════════════════════════════
# 1) 查窗口
# ═══════════════════════════════════════════════════════════


def window_for(model: str = "", provider: str = "") -> Optional[int]:
    """查模型的上下文窗口（token）；**未知返回 None**（调用方据此走保守默认）。

    匹配：把 ``model`` / ``provider`` 拼成小写串，取**最长命中的键** ——
    否则 ``"gemini"``（32K）会抢先匹配 ``"gemini-1.5-pro"``（2M），把大窗口算成小窗口。

    >>> window_for("gpt-4o-mini")
    128000
    >>> window_for("gemini-1.5-pro-latest")
    2097152
    >>> window_for("某不存在的模型") is None
    True
    """
    hay = f"{model or ''} {provider or ''}".lower().strip()
    if not hay:
        return None
    hit = ""
    for key in KNOWN_WINDOWS:
        if key in hay and len(key) > len(hit):
            hit = key
    return KNOWN_WINDOWS[hit] if hit else None


# ═══════════════════════════════════════════════════════════
# 2) 窗口 → 字符预算
# ═══════════════════════════════════════════════════════════


def chars_budget(
    window_tokens: Optional[int],
    *,
    reserve_tokens: int = OUTPUT_RESERVE_TOKENS,
) -> int:
    """窗口（token）→ 安全的字符上限。

    取两约束的**较小者**（都要满足）：

      ① ``窗口 × 0.7``  —— 留 message 头 / system 增长等开销余量；
      ② ``窗口 − 4096`` —— 给输出预留（与 ``max_tokens`` 默认一致）。

    再按 ``CHARS_PER_TOKEN``（≈1.67）折算成字符。窗口非法 / 太小 → 返回保守默认。

    >>> chars_budget(8192)          # 8K 窗口 → 6826 字符（比写死的 12000 更保守）
    6826
    >>> chars_budget(128000)        # 128K 窗口 → 约 15 万字符（放大 12 倍）
    149333
    """
    if not window_tokens or window_tokens <= 0:
        return DEFAULT_MAX_CHARS
    usable = min(int(window_tokens * MAX_USABLE_RATIO), int(window_tokens) - reserve_tokens)
    if usable <= 0:
        return DEFAULT_MAX_CHARS
    return max(MIN_MAX_CHARS, int(usable * CHARS_PER_TOKEN))


def resolve_max_chars(
    model: str = "",
    provider: str = "",
    override: Optional[int] = None,
) -> int:
    """一步到位：**显式 override > 按模型窗口推导 > 保守默认**。

    >>> resolve_max_chars()                       # 不知道模型 → 与改造前一致
    12000
    >>> resolve_max_chars("gpt-4o")               # 大窗口 → 自动放大
    149333
    >>> resolve_max_chars("gpt-4o", override=30000)
    30000
    """
    if override is not None:
        try:
            n = int(override)
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
    w = window_for(model, provider)
    return chars_budget(w) if w else DEFAULT_MAX_CHARS


def describe(model: str = "", provider: str = "") -> Dict[str, object]:
    """诊断用：返回「该模型窗口 / 推导预算 / 是否命中已知表」。"""
    w = window_for(model, provider)
    return {
        "model": model,
        "provider": provider,
        "window_tokens": w,
        "known": w is not None,
        "max_chars": chars_budget(w) if w else DEFAULT_MAX_CHARS,
    }
