#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 agent_loop 的上下文压缩（V4.33.3）—— 自包含可执行。

跑法: python _verify/check_agent_loop_context.py

**背景**：`agent_loop.run()` 的轮内 messages 此前**未走窗口压缩**，只靠 12 轮预算兜底 ——
12 轮 × 大工具参数可能撑爆**窄窗口模型**的上下文（对 128K 模型无碍）。
本脚本验证三件事：
  ① **静态**：循环体含 `compress_messages` 调用，且位置在「预算检查之前」；
  ② **行为**：注入大 params 的工具跑满多轮，发给模型的 messages **被压在阈值附近、不线性膨胀**；
  ③ **反证**：给出「不压缩」的估算值，证明压缩确实在起作用（否则该断言会失败）。
"""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as f:
        return f.read()


def main() -> int:
    # ── ① 静态断言 ──
    src = _read("app", "core", "agent_loop.py")
    check("agent_loop 导入 compress_messages",
          "from app.core.agent_context import compress_messages" in src)
    # 注意：断言须与**当前**调用形态一致（V4.33.4 起带上 model/provider 自适应传参）
    _COMPRESS_CALL = "messages = compress_messages(messages, model=model, provider=provider)"
    check("循环体调用 compress_messages（含模型自适应传参）", _COMPRESS_CALL in src)
    try:
        i_loop = src.index("while rounds < max_rounds")
        i_compress = src.index(_COMPRESS_CALL)
        i_budget = src.index("begin_model_round(session_id)", i_loop)
        check("压缩在循环内、且在预算检查之前", i_loop < i_compress < i_budget)
    except ValueError:
        check("压缩在循环内、且在预算检查之前", False)

    # ── ② 行为断言（跑真循环）──
    from app.core.agent_loop import AgentLoop

    loop = AgentLoop()
    sizes = []
    PARAM_PAD = 3000          # 每轮 params 故意塞大，制造上下文压力

    def fake_model(messages):
        sizes.append(sum(len(str(m.get("content") or "")) for m in messages))
        if len(sizes) <= 10:
            return json.dumps({"commands": [{"action": "inspect_media",
                                             "params": {"pad": "y" * PARAM_PAD}}]})
        return "任务完成"

    def fake_exec(action, params):
        return {"ok": True, "payload": {"r": "z" * 500}}

    res = loop.run(
        goal="验证上下文压缩" + "g" * 200,
        mode="autonomous",
        session_id=f"ctx_compress_test_{int(time.time() * 1000)}",
        model_fn=fake_model,
        tool_executor=fake_exec,
        max_rounds=12,
    )

    check("循环跑了多轮（≥8）", len(sizes) >= 8)
    check("循环正常收敛（拿到最终答复）", res.success is True)
    print(f"    每轮 messages 字符数：{sizes}")

    # 不压缩的估算：首轮 + 轮数 × 每轮增量（assistant params + user 观测）
    per_round = PARAM_PAD + 700
    no_compress_est = (sizes[0] if sizes else 0) + len(sizes) * per_round
    peak = max(sizes) if sizes else 0
    check("长度不随轮数线性膨胀（峰值 < 不压缩估算的 60%）",
          bool(sizes) and peak < no_compress_est * 0.6)
    check("末轮被压住（< 不压缩估算的一半）",
          bool(sizes) and sizes[-1] < no_compress_est * 0.5)
    print(f"    不压缩估算 ≈ {no_compress_est} 字符 · 实测峰值 {peak} 字符")

    # ── 汇总 ──
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} / {TOTAL}")
        for x in FAILS:
            print(f"  - {x}")
        return 1
    print(f"ALL PASS ({TOTAL} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
