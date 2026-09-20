# -*- coding: utf-8 -*-
"""Agent 动作 ↔ 能力 一致性检查。

背景
----
Agent 的动作清单（`agent_action_registry.py`）与真实能力注册
（`capability_handlers.py`）是**两个文件**。任何一处改名/漏注册，
都表现为「Agent 生成了合法 action，但执行时找不到能力」——
不报错、不崩溃，只是这条指令静默失效。

历史上已经踩过一次同类坑：`account.publish` 默认 `skill_id="account_publish"`，
而该 id 从未存在（真实为 `publish_content`），未显式传参的调用 100% 失败。

检查项
------
  1. `ACTION_TO_CAPABILITY` 里的每个 capability_id 都真实注册
  2. 同一 action 不重复定义（含剪辑侧 / 画布侧各自内部）
  3. 画布 action 的 effect 只用已定义的语义（read / canvas_write / media_write）
  4. 信息性输出：注册总量、Agent 可达的 editor.* 写类能力数量

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_agent_action_mapping.py
"""

from __future__ import annotations

import ast
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANDLERS = os.path.join(ROOT, "app", "core", "capability_handlers.py")
REGISTRY = os.path.join(ROOT, "app", "core", "agent_action_registry.py")

VALID_EFFECTS = {"read", "canvas_write", "media_write"}

# 「真能改 _clips 且可撤销」的 editor.* 能力白名单 —— 检查目标，非检查对象。
# 门槛来源：docs/_archive/knowledge/06-roadmap.md §E「≥8 个 editor.* 写能力」。
# 新增写能力时同步此处，脚本会给出门槛差距。
EDITOR_WRITE_CAPS = frozenset({
    "editor.split_clip",
    "editor.add_transition",
    "editor.apply_filter",
    "editor.ripple_delete_range",
    "editor.set_clip_properties",
    "editor.set_keyframes",
})
WRITE_CAP_GOAL = 8

problems: list[str] = []


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def literal(name: str):
    """静态取 registry 的模块级字面量，避免 import（其 import 链有副作用）。

    注意：带类型注解的赋值（``NAME: T = ...``）在 AST 里是 ``AnnAssign`` 而非 ``Assign``，
    两种都要认，否则会漏掉 registry 里几乎所有表。
    """
    tree = ast.parse(read(REGISTRY))
    for node in tree.body:
        value = None
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                value = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                value = node.value
        if value is not None:
            return ast.literal_eval(value)
    raise RuntimeError(f"未找到 {name}")


def main() -> int:
    handlers_src = read(HANDLERS)
    registered = set(re.findall(r'dispatcher\.register\(\s*"([\w.]+)"', handlers_src))

    clip_rows = literal("_AGENT_ACTION_ROWS")
    canvas_rows = literal("_CANVAS_ACTION_ROWS")

    # ---- 1. 映射的 capability 是否真实注册 ----
    mapped = {a: cap for a, _lvl, cap, _desc in clip_rows if cap}
    missing = sorted(set(mapped.values()) - registered)
    for cap in missing:
        owners = sorted(a for a, c in mapped.items() if c == cap)
        problems.append(
            f"这些 action 指向未注册的能力 {cap}：{', '.join(owners)}（执行时必然失败）"
        )

    # ---- 2. 重复 action ----
    for label, rows in (("剪辑侧", clip_rows), ("画布侧", canvas_rows)):
        dup = [a for a, n in Counter(r[0] for r in rows).items() if n > 1]
        for a in sorted(dup):
            problems.append(f"{label} action 重复定义：{a}")

    # ---- 3. 画布 effect 语义 ----
    for action, _lvl, effect, _desc in canvas_rows:
        if effect not in VALID_EFFECTS:
            problems.append(f"画布 action {action} 的 effect 非法：{effect!r}")

    # ---- 4. 信息性统计 ----
    editor_caps = sorted({
        c for c in mapped.values()
        if c and c in registered and c.startswith("editor.")
    })
    write_found = sorted(EDITOR_WRITE_CAPS & set(editor_caps))
    unknown_levels = sorted(
        {lvl for _a, lvl, _c, _d in clip_rows if lvl not in ("safe", "dangerous")}
    )
    for lvl in unknown_levels:
        problems.append(f"剪辑侧存在未识别的 danger_level：{lvl!r}")

    stats = [
        f"注册能力总数            {len(registered)}",
        f"剪辑侧 action           {len(clip_rows)}",
        f"画布侧 action           {len(canvas_rows)}",
        f"action→能力 映射        {len(mapped)}",
        f"Agent 可达 editor.* 能力 {len(editor_caps)}：{', '.join(editor_caps)}",
        f"写能力（改 _clips）      {len(write_found)} / {WRITE_CAP_GOAL}"
        f"（门槛见 06-roadmap §E，缺 {WRITE_CAP_GOAL - len(write_found)}）",
    ]
    if len(write_found) < WRITE_CAP_GOAL:
        stats.append(
            "  提示：写能力未达门槛属规划差距，不是缺陷；差距项见 06-roadmap §E"
        )

    if problems:
        print("FAIL Agent 动作表与能力注册不一致：")
        for p in problems:
            print("  -", p)
        print()
        for s in stats:
            print(" ", s)
        return 1

    print("OK Agent 动作表与能力注册一致")
    for s in stats:
        print(" ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
