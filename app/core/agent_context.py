# -*- coding: utf-8 -*-
"""模型上下文压缩：只改发给模型的窗口，不删除原始历史。"""
from __future__ import annotations

from typing import Any, Dict, List


def _chars(messages: List[Dict[str, Any]]) -> int:
    n = 0
    for m in messages:
        n += len(str(m.get("content") or ""))
    return n


def compress_messages(
    messages: List[Dict[str, Any]],
    *,
    max_chars: int = 12000,
    keep_tail: int = 6,
) -> List[Dict[str, Any]]:
    """接近上限时把中间轮次收成一条摘要。system 始终保留。"""
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
    return system + [summary] + tail
