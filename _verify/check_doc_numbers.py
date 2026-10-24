#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""文档数字一致性守卫（2026-10-20 · WS-A A5 / WS-F F4）

防止交接文档再次漂移成「旧数字」：
  A. 交接/零基础/求职文档不得出现已过时的 726 / 62 项 / 9 道 / 85 把锁；
  B. 技术文档的端点数字必须等于运行时实测唯一路由数；
  C. 技术文档/设计文档的能力总数必须等于能力目录实测；
  D. 关键文档必须含当前体检项数（从 run_all_checks 的 CHECKS 长度推导）。

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_doc_numbers.py
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_failures: list = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


# ── A. 过时数字不得回流 ──
print("[A] 交接文档不含过时数字")
_STALE = {
    "726": "测试数（现为 1,722 passed）",
    "62 项": "体检项数（现为 96）",
    "9 道": "提交卡点数（现为 14）",
    "85 把锁": "冻结锁数（现为 107）",
    "~45 端点": "画布端点数（现为 98 唯一）",
}
for rel in ("docs/接手速查卡.md", "docs/零基础学习路径与恶补计划.md",
            "docs/求职准备-技术面清单与角色定位.md"):
    text = _read(rel)
    hits = [f"{token}（{why}）" for token, why in _STALE.items() if token in text]
    check(not hits, f"{rel} 无过时数字{'' if not hits else '：' + '；'.join(hits)}")

# ── B. 端点数字 = 运行时实测 ──
print("[B] 技术文档端点数字 ↔ 运行时路由")
paths: list[str] = []
for name in os.listdir(os.path.join(ROOT, "app", "core")):
    if name.startswith("canvas_routes_") and name.endswith(".py"):
        paths.append(os.path.join(ROOT, "app", "core", name))
paths.append(os.path.join(ROOT, "app", "core", "canvas_server.py"))
_routes: list[str] = []
for path in paths:
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    _routes += re.findall(r"@_route_(?:get|post)\(\s*[\"']([^\"']+)", src)
_unique = len(set(_routes))
_tech = _read("docs/现行技术文档.md")
check(f"{_unique} 唯一端点" in _tech, f"技术文档写明 {_unique} 唯一端点（实测 {_unique}）")

# ── C. 能力总数 = 能力目录实测 ──
print("[C] 技术文档能力总数 ↔ 能力目录")
from app.core import agent_capability_catalog as cat

_count = len(cat.registered_capability_ids())
check(f"总计 {_count} 个" in _tech or f"总计 **{_count}** 个" in _tech,
      f"技术文档写明总计 {_count} 个能力（实测 {_count}）")
_design = _read("docs/设计文档_深度迭代版.md")
check(f"{_count} 个能力" in _design, f"设计文档写明 {_count} 个能力")

# ── D. 体检项数 = run_all_checks 实测 ──
print("[D] 交接文档体检项数 ↔ run_all_checks")
with open(os.path.join(ROOT, "_verify", "run_all_checks.py"), "r", encoding="utf-8") as fh:
    tree = ast.parse(fh.read())
_checks = None
for node in tree.body:
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "CHECKS" for t in node.targets
    ):
        _checks = len(node.value.elts)
check(_checks is not None, "run_all_checks.CHECKS 可解析")
if _checks is not None:
    for rel in ("docs/接手速查卡.md", "docs/零基础学习路径与恶补计划.md"):
        check(f"{_checks} 项" in _read(rel), f"{rel} 写明 {_checks} 项体检")

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项（更新文档或守卫基线后重跑）")
    sys.exit(1)
print("OK 文档数字一致性守卫全绿")
