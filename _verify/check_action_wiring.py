#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三向一致校验：catalog ↔ dispatcher ↔ 对话面 action —— 自包含可执行。

跑法: python _verify/check_action_wiring.py

**为什么需要它**：`run_all_checks.py` 的 AGENTMAP 用例只覆盖「目录 ↔ dispatcher」，
而「对话面」（`_AGENT_ACTION_ROWS` 的 action 白名单 + 帮助文案）**任何守卫都不覆盖** ——
漏了这两处，能力全绿但 Agent 根本调不到（静默失效）。

本脚本**自动从 catalog 派生**要校验的清单（不写死），因此新增能力后无需改它。
"""

from __future__ import annotations

import os
import sys

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


def main() -> int:
    import app.core.agent_action_registry as reg
    import app.core.agent_capability_catalog as cat

    ids = set(cat.registered_capability_ids())

    # dispatcher 注册
    handlers = set()
    try:
        from app.core.capability_dispatcher import CapabilityDispatcher
        from app.core.capability_handlers import register_builtin_handlers

        d = CapabilityDispatcher()
        register_builtin_handlers(d)
        handlers = set(getattr(d, "_handlers", {}).keys())
        check("dispatcher 可构建并注册", bool(handlers))
    except Exception as e:  # pragma: no cover
        check(f"dispatcher 可构建并注册（异常：{e}）", False)

    # ① 目录 ↔ dispatcher（守卫已覆盖，这里冗余确认）
    problems = cat.verify_catalog_consistency(handlers) if handlers else ["dispatcher 未就绪"]
    check(f"目录 ↔ dispatcher 一致（{len(problems)} 个问题）", problems == [])
    for p in problems:
        print(f"    ! {p}")

    # ② 目录登记的能力都真的注册了
    missing = sorted(ids - handlers)
    check(f"目录能力均已注册（缺 {len(missing)}）", not missing)
    for m in missing:
        print(f"    ! 未注册: {m}")

    # ③ 对话面：action → capability 映射指向的能力必须真实存在
    a2c = dict(reg.ACTION_TO_CAPABILITY)
    allowed = set(reg.get_allowed_actions())
    bad_targets = sorted({cap for cap in a2c.values() if cap not in ids})
    check(f"action → capability 目标均存在（坏 {len(bad_targets)}）", not bad_targets)
    for b in bad_targets:
        print(f"    ! action 指向未登记能力: {b}")

    # ④ 映射里的 action 都在白名单。
    #    ⚠️ 只校验**剪辑侧**（agent 侧）action —— 画布侧 action 由**前端** executeRemoteTask
    #    本地执行（无后端 capability handler），本就不在后端白名单里（见 agent_action_registry
    #    第 55-59 行注释）。不剔除画布侧会造成 28 条假阳性。
    canvas_actions = set(reg.canvas_action_to_capability())
    agent_side = set(a2c) - canvas_actions
    not_allowed = sorted(agent_side - allowed)
    check(f"剪辑侧映射 action 均在白名单（缺 {len(not_allowed)}）", not not_allowed)
    for n in not_allowed:
        print(f"    ! 不在白名单: {n}")
    print(f"    （画布侧 {len(canvas_actions)} 个 action 由前端本地执行，已剔除）")

    # ⑤ 白名单 action 都能反查到 capability 或明确为「本地动作」
    prompt_line = reg.build_agent_actions_prompt_line()
    not_in_prompt = sorted(a for a in allowed if a not in prompt_line)
    check(f"白名单 action 均进提示词（缺 {len(not_in_prompt)}）", not not_in_prompt)
    for n in not_in_prompt[:10]:
        print(f"    ! 不在提示词: {n}")

    # ⑥ pipeline.* 能力必须在 help_block 里有参数说明（新能力的常见漏项）
    help_block = reg.build_agent_actions_help_block()
    pipeline_actions = sorted(a for a, c in a2c.items() if str(c).startswith("pipeline."))
    missing_help = [a for a in pipeline_actions if f"{a} 参数" not in help_block]
    check(f"pipeline.* action 均有帮助文案（缺 {len(missing_help)}）", not missing_help)
    for n in missing_help:
        print(f"    ! 缺参数说明: {n}")

    print()
    print(f"能力总数 {len(ids)} · 已注册 {len(handlers)} · 对话面 action {len(a2c)} · 白名单 {len(allowed)}")
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} / {TOTAL}")
        return 1
    print(f"ALL PASS ({TOTAL} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
