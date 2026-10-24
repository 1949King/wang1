# -*- coding: utf-8 -*-
"""模型上下文压缩：只改发给模型的窗口，不删除原始历史。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _chars(messages: List[Dict[str, Any]]) -> int:
    n = 0
    for m in messages:
        n += len(str(m.get("content") or ""))
    return n


def compress_messages(
    messages: List[Dict[str, Any]],
    *,
    max_chars: Optional[int] = None,
    keep_tail: int = 6,
    model: str = "",
    provider: str = "",
) -> List[Dict[str, Any]]:
    """接近上限时把中间轮次收成一条摘要。system 始终保留。

    ``max_chars``（V4.33.4 起可为 ``None``）：
      * 显式传数值 → **以它为准**（向后兼容，原默认 12000）；
      * 传 ``None``（默认）+ 给了 ``model`` / ``provider`` → 按**模型窗口**推导
        （见 `context_budget.resolve_max_chars`：128K 窗口 ≈ 15 万字符，比写死的 12000 大 12 倍）；
      * 两者都不给 → 保守默认 12000 —— **与改造前逐字一致**（零行为变化）。
    """
    from app.core.context_budget import resolve_max_chars

    if max_chars is None:
        max_chars = resolve_max_chars(model, provider)
    if not messages or _chars(messages) <= max_chars:
        return messages

    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if len(rest) <= keep_tail:
        # 仍超限：截断最早 user 正文
        out = list(system) + rest
        budget = max_chars
        trimmed: List[Dict[str, Any]] = []
        for m in reversed(out):
            c = str(m.get("content") or "")
            if len(c) > budget:
                c = c[: max(400, budget)] + "\n…[已压缩]"
            trimmed.append({**m, "content": c})
            budget -= len(c)
            if budget <= 0:
                break
        trimmed.reverse()
        return trimmed

    head, tail = rest[:-keep_tail], rest[-keep_tail:]
    goals = []
    for m in head:
        role = m.get("role")
        text = str(m.get("content") or "").replace("\n", " ")
        if role == "user":
            goals.append(f"用户: {text[:180]}")
        elif role == "assistant":
            goals.append(f"助手: {text[:180]}")
    summary = {
        "role": "system",
        "content": (
            "[压缩上下文 · 原始历史未删]\n"
            "须保留：目标、约束、决定、未完成计划、节点 ID、失败原因。\n"
            + "\n".join(goals[-12:])
        ),
    }
    out = system + [summary] + tail
    # 边界加固（V4.33.3）：若**保留下来的 tail 本身就顶超上限**（工具参数极大的场景，
    # 例：单轮 params 数千字符），只把中间轮次收成摘要并不足以降到 max_chars 以下 ——
    # 此时对 tail 按预算裁剪内容（**从最早的开始**，优先保留最近的上下文），
    # 与上面 `len(rest) <= keep_tail` 分支的截断策略保持一致。
    if _chars(out) > max_chars:
        budget = max_chars - _chars(system) - len(str(summary["content"]))
        trimmed_tail: List[Dict[str, Any]] = []
        for m in reversed(tail):
            c = str(m.get("content") or "")
            if len(c) > budget:
                c = c[: max(400, budget)] + "\n…[已压缩]"
            trimmed_tail.append({**m, "content": c})
            budget -= len(c)
            if budget <= 0:
                break
        trimmed_tail.reverse()
        out = system + [summary] + trimmed_tail
    return out
