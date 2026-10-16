#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""路由 mixin 属性可解析性守卫（2026-09-27 A4 血泪教训）

背景（真实踩坑）
----------------
A4 把 canvas_server 的端点迁到 `canvas_routes_get.py` / `canvas_routes_post.py`
后，端点代码里的模块级符号改成 `cs.xxx` 延迟取用（cs = canvas_server 模块）。
但迁出后 canvas_server **本身不再直接调用**这些符号 ⇒ `ruff --fix` 的 F401
判定它们「未使用」并**自动删除 import** ⇒ mixin 的 `cs.xxx` 变成
AttributeError，端点静默失效（e2e 抓到 `/host/plugins`、`/host/characters`
两个；`build_host_ai_config_patch` 影响 5 个 `*-models` 端点且当时无测试覆盖）。

本守卫做两件事（**不 import app，避免 wmic 沙箱链**）：
  1. 收集两个 mixin 文件里所有 `cs.<name>` 引用
  2. 到 canvas_server.py 的顶层 import 绑定名里查找；找不到即失败，
     并提示「把该名字加回 import 并标 noqa」

纯静态、零依赖、毫秒级，适合进 pre-commit / run_all_checks。
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "app", "core", "canvas_server.py")
MIXINS = [
    os.path.join(ROOT, "app", "core", "canvas_routes_get.py"),
    os.path.join(ROOT, "app", "core", "canvas_routes_post.py"),
    # 2026-10-15：配音编排端点迁至 canvas_routes_dub.py（同样用 cs.xxx 延迟取用）。
    os.path.join(ROOT, "app", "core", "canvas_routes_dub.py"),
]


def bound_names(src: str) -> set:
    """canvas_server.py 顶层绑定的名字（import / def / class / 赋值）。"""
    tree = ast.parse(src)
    out = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
                elif isinstance(t, (ast.Tuple, ast.List)):
                    for e in t.elts:
                        if isinstance(e, ast.Name):
                            out.add(e.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add(a.asname or a.name.split(".")[0])
    return out


def main() -> int:
    if not os.path.exists(SERVER):
        print(f"[route-attrs] 缺文件 {SERVER}")
        return 1
    have = bound_names(io.open(SERVER, encoding="utf-8-sig").read())

    problems = []
    for path in MIXINS:
        if not os.path.exists(path):
            continue
        src = io.open(path, encoding="utf-8-sig").read()
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        used = sorted(set(re.findall(r"\bcs\.([A-Za-z_]\w*)", src)))
        missing = [u for u in used if u not in have]
        print(f"{rel}: cs. 引用 {len(used)} 个")
        for m in missing:
            problems.append((rel, m))

    if problems:
        print()
        print("✗ 以下 `cs.xxx` 在 canvas_server 里解析不到（端点会静默失效）：")
        for rel, name in problems:
            print(f"    {rel}  →  cs.{name}")
        print()
        print("修复：把该名字加回 canvas_server.py 的顶层 import，并标 `# noqa: F401`")
        print("      （它已不在本文件直接使用，不加 noqa 会被 ruff --fix 再次删除）")
        return 1

    print("OK 路由 mixin 的 cs.* 引用全部可解析")
    return 0


if __name__ == "__main__":
    sys.exit(main())
