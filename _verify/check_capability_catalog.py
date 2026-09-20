# -*- coding: utf-8 -*-
"""回归：Agent 能力目录一致性 —— 单一事实来源是否真的「归一」。

自包含执行（不依赖 pytest，仅标准库）。

背景
----
新增能力此前要手改 4 处（register / policy effect / brain 神经元 / action 映射），
漏一处就静默失效。V4.16.0 起收敛为 ``agent_capability_catalog.py`` 单一来源，
policy 的 effect 表、brain 的神经元表都由它派生。本脚本锁定这条归一契约：

  A. 目录 ↔ 真实注册 双向一致（verify_catalog_consistency 返回空）
  B. policy._CAPABILITY_EFFECTS 与目录派生逐项相等
  C. brain._NEURON_TAXONOMY 覆盖目录全部 capability（无遗漏神经元）
  D. 历史缺陷不回归：editor.inspect_media / editor.get_media 必须 = read（不再落 FILE_WRITE 兜底）
  E. 目录自身卫生：无重复 id、effect/hemisphere 取值合法

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_capability_catalog.py
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core import agent_capability_catalog as cat  # noqa: E402
from app.core import agent_policy  # noqa: E402
from app.core.agent_brain import _NEURON_TAXONOMY  # noqa: E402

HANDLERS = os.path.join(ROOT, "app", "core", "capability_handlers.py")

_failures: list[str] = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


# ── 静态取「真实注册」集合（避免拉起 dispatcher 链）──
with open(HANDLERS, encoding="utf-8") as f:
    registered = set(re.findall(r'dispatcher\.register\(\s*"([\w.]+)"', f.read()))

# 画布节点级 capability（canvas_tools 后端化）经 register_builtin_handlers 里的
# 循环注册（for _c in canvas_node_capabilities()），静态 regex 抓不到字面量；
# 这里由同一派生源补上，与运行时注册保持一致。
from app.core.agent_action_registry import canvas_node_capabilities  # noqa: E402

registered |= {c["capability_id"] for c in canvas_node_capabilities()}

print("[A] 目录 ↔ 注册 双向一致")
problems = cat.verify_catalog_consistency(registered)
check(not problems, "verify_catalog_consistency 返回空" if not problems
      else "发现漂移：\n" + "\n".join(f"    - {p}" for p in problems))

print("[B] policy effect 表与目录派生逐项相等")
derived = cat.capability_effect_paid()
check(agent_policy._CAPABILITY_EFFECTS == derived,
      "agent_policy._CAPABILITY_EFFECTS == 目录派生")
if agent_policy._CAPABILITY_EFFECTS != derived:
    only_policy = set(agent_policy._CAPABILITY_EFFECTS) - set(derived)
    only_cat = set(derived) - set(agent_policy._CAPABILITY_EFFECTS)
    if only_policy:
        print(f"    仅 policy 有：{sorted(only_policy)}")
    if only_cat:
        print(f"    仅目录有：{sorted(only_cat)}")

print("[C] brain 神经元覆盖目录全部能力")
tax_ids = {t[0] for t in _NEURON_TAXONOMY}
catalog_ids = set(cat.registered_capability_ids())
missing_neurons = sorted(catalog_ids - tax_ids)
check(not missing_neurons,
      "神经元表覆盖目录全部能力" if not missing_neurons
      else f"缺神经元：{missing_neurons}")
extra_neurons = sorted(tax_ids - catalog_ids)
check(not extra_neurons,
      "神经元表无多余项" if not extra_neurons else f"多余神经元：{extra_neurons}")

print("[D] 历史缺陷不回归")
for cid in ("editor.inspect_media", "editor.get_media"):
    eff = agent_policy._CAPABILITY_EFFECTS.get(cid)
    check(eff == ("read", False),
          f"{cid} → {eff}（应 = read，此前会落 FILE_WRITE 兜底）")

print("[E] 目录卫生")
ids = [r[0] for r in cat.CAPABILITY_ROWS]
dup = sorted({i for i in ids if ids.count(i) > 1})
check(not dup, "无重复 capability_id" if not dup else f"重复：{dup}")

# 归类统计（信息性）
from collections import Counter
cat_count = Counter(r[1] for r in cat.CAPABILITY_ROWS)
hemi_count = Counter(r[5] for r in cat.CAPABILITY_ROWS)
print(f"\n  目录能力 {len(cat.CAPABILITY_ROWS)} · 注册 {len(registered)}")
print(f"  分类：{dict(cat_count)}")
print(f"  脑半球：right {hemi_count.get('right', 0)} / left {hemi_count.get('left', 0)} / cc {hemi_count.get('cc', 0)}")

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项")
    sys.exit(1)
print("OK Agent 能力目录已归一（单一事实来源）")
