# -*- coding: utf-8 -*-
"""回归：Agent 写能力门槛 —— `06-roadmap.md §E` 要求「≥8 个真能改 `_clips` 且可撤销的 editor.*」。

自包含执行（不依赖 pytest）：沙箱下 pytest 启动链会触发硬件探测被拦截。

覆盖：
  A. 8 个写能力全部在 dispatcher 注册
  B. 每个写能力都在 agent_policy 有明确 effect（不能落到「未登记 = FILE_WRITE」兜底）
  C. 对话 action 与 capability 的映射齐备（trim_clip / move_clip 不再是 None）
  D. 写能力实现必须能追到撤销栈（_record_action / _resize_clip / move_clip）
  E. 旧缺陷不回归：ai_agent_panel 不得再直接写 clip["duration"]
"""
from __future__ import annotations

import ast
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.capability_dispatcher import capability_dispatcher  # noqa: E402
from app.core.capability_handlers import register_builtin_handlers  # noqa: E402
from app.core import agent_policy  # noqa: E402
from app.core.agent_action_registry import ACTION_TO_CAPABILITY  # noqa: E402

# 真能改 _clips 的写能力（读/建议类不计入）
WRITE_CAPS = {
    "editor.split_clip",
    "editor.apply_filter",
    "editor.add_transition",
    "editor.ripple_delete_range",
    "editor.set_clip_properties",
    "editor.set_keyframes",
    "editor.trim_clip",
    "editor.move_clip",
}
THRESHOLD = 8

_failures = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


print("[A] dispatcher 注册")
register_builtin_handlers(capability_dispatcher, editor_module_ref=lambda: None)
listed = capability_dispatcher.list_capabilities()
ids = {c["capability_id"] if isinstance(c, dict) else getattr(c, "capability_id", "")
       for c in listed}
missing = sorted(WRITE_CAPS - ids)
check(not missing, f"8 个写能力全部注册（缺：{missing}）" if missing else "8 个写能力全部注册")
check(len(WRITE_CAPS & ids) >= THRESHOLD,
      f"写能力数量 {len(WRITE_CAPS & ids)} ≥ 门槛 {THRESHOLD}")

print("[B] agent_policy effect 明确登记")
for cap in sorted(WRITE_CAPS):
    eff = agent_policy._CAPABILITY_EFFECTS.get(cap)
    check(eff is not None,
          f"{cap} → {eff if eff else '未登记(会落 FILE_WRITE 兜底)'}")
check(all(agent_policy._CAPABILITY_EFFECTS.get(c, (None,))[0]
          == agent_policy.EFFECT_CANVAS_WRITE for c in WRITE_CAPS),
      "写能力统一为 canvas_write（与 split_clip 等同类一致）")

print("[C] 对话 action → capability 映射")
for act, cap in (("trim_clip", "editor.trim_clip"),
                 ("move_clip", "editor.move_clip"),
                 ("split_clip", "editor.split_clip")):
    check(ACTION_TO_CAPABILITY.get(act) == cap,
          f"{act} → {ACTION_TO_CAPABILITY.get(act)}")

print("[D] 写能力可撤销（AST 静态追踪）")
src = open(os.path.join(ROOT, "app", "modules", "lego", "editor_module.py"),
           encoding="utf-8").read()
tree = ast.parse(src)
funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _called_names(fn) -> set:
    return {n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


for fname, needed in (
    ("agent_trim_clip", {"_record_action", "_resize_clip"}),
    ("agent_move_clip", {"move_clip"}),
):
    fn = funcs.get(fname)
    if fn is None:
        check(False, f"{fname} 存在")
        continue
    names = _called_names(fn)
    check(bool(names & needed),
          f"{fname} 调用栈含撤销路径 {sorted(names & needed)}")

print("[E] 旧缺陷不回归")
panel = open(os.path.join(ROOT, "app", "modules", "lego", "ai_agent_panel.py"),
             encoding="utf-8").read()
check('clip["duration"] = float(duration)' not in panel,
      "ai_agent_panel 不再直接写 clip[\"duration\"]（改走 editor.trim_clip）")
check('self._agent_dispatch("editor.trim_clip"' in panel,
      "trim_clip 走 capability 派发")
check('self._agent_dispatch(\n                "editor.move_clip"' in panel
      or 'self._agent_dispatch(\n                "editor.move_clip"' in panel
      or '"editor.move_clip"' in panel,
      "move_clip 走 capability 派发")

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项：")
    for f in _failures:
        print("   -", f)
    sys.exit(1)
print(f"OK 写能力门槛达成：{len(WRITE_CAPS)}/8")
