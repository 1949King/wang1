#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""稳定性门禁：扫描裸 except、吞异常、product 代码 print、未定义符号，防止稳定性回归。

扫描对象: app/ 下的 .py 源码（跳过 tests/、thirdparty/、__pycache__ 目录）。

四条规则:
  - bare-except     : 裸 `except:`（未指定异常类型，吞掉 KeyboardInterrupt/SystemExit 等一切异常）
  - swallow-except  : except 块体仅含 pass（静默吞异常，隐藏 crash 根因）
  - print-statement : product 代码中的裸 print()（应使用 logger，禁止新增裸 print 作为长期日志）
  - undefined-name  : 被引用但全文件从未绑定/导入的名字（缺 import / NameError 隐患）

基线: docs/knowledge/stability_gate_baseline.json
默认运行只拦截"基线之外的新增违规"，存量通过 --update 固化，实现"防回归"。

用法:
  python scripts/stability_gate.py                 # 检查，有新增违规则 exit 1
  python scripts/stability_gate.py --report        # 列出当前全部违规（含存量）
  python scripts/stability_gate.py --update        # 用当前存量重写基线（修完增量后固化）
  python scripts/stability_gate.py --list-skipped  # 列出因星号导入跳过 undefined 检查的文件
"""
from __future__ import annotations

import argparse
import ast
import builtins
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOT = ROOT / "app"
BASELINE = ROOT / "docs" / "knowledge" / "stability_gate_baseline.json"

# product 代码扫描需跳过的目录（测试/第三方/缓存）
SKIP_DIRS = {"tests", "thirdparty", "__pycache__", "node_modules"}

_RULE_BARE = "bare-except"
_RULE_SWALLOW = "swallow-except"
_RULE_PRINT = "print-statement"
_RULE_UNDEF = "undefined-name"

# 内建名字 + 运行环境注入的特殊名，不计为未定义
_BUILTINS: Set[str] = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__annotations__",
    "exit", "quit", "copyright", "credits", "license",
}
# 约定俗成、由框架/语言机制注入的名字，不算未定义
_CONVENTIONS: Set[str] = {"self", "cls", "mcs"}


def _py_files(root: Path):
    """递归列出 root 下需扫描的 .py 文件，跳过指定目录。"""
    for child in sorted(root.rglob("*.py")):
        parts = child.relative_to(root).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        yield child


def _is_docstring(stmt: ast.stmt) -> bool:
    """判断语句是否为字符串字面量（docstring/占位注释语句）。"""
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _is_swallow(node: ast.ExceptHandler) -> bool:
    """判断 except 块体是否仅含 pass（吞异常）。"""
    real = [s for s in node.body if not _is_docstring(s)]
    return bool(real) and all(isinstance(s, ast.Pass) for s in real)


def _is_print_call(node: ast.Call) -> bool:
    """判断调用是否为裸 print(...)。"""
    return isinstance(node.func, ast.Name) and node.func.id == "print"


def _has_star_import(tree: ast.AST) -> bool:
    """判断文件是否包含 `from x import *`（污染命名空间，无法可靠判定未定义符号）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return True
    return False


def _collect_bound_names(tree: ast.AST) -> Set[str]:
    """收集全文件内被绑定过的名字（赋值、函数/类定义、参数、导入等）。"""
    bound: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler):
            # except X as e: 的 e 通过 name 字符串绑定（非 Name 节点），需单独收集
            if node.name:
                bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    bound.add(alias.asname or alias.name)
    return bound


def _analyze_file(path: Path) -> Tuple[List[dict], bool]:
    """分析单个文件，返回 (违规列表, 是否因星号导入跳过 undefined 检查)。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        # 语法错误由编译门禁（py_compile）负责，此处跳过
        return [], False

    rel = path.relative_to(ROOT).as_posix()
    issues: List[dict] = []

    # 裸 except / 吞异常 / print
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                issues.append({
                    "rel": rel, "rule": _RULE_BARE, "line": node.lineno,
                    "msg": "裸 except: 未指定异常类型",
                })
            if _is_swallow(node):
                issues.append({
                    "rel": rel, "rule": _RULE_SWALLOW, "line": node.lineno,
                    "msg": "except 块体仅含 pass，吞掉异常",
                })
        elif isinstance(node, ast.Call) and _is_print_call(node):
            issues.append({
                "rel": rel, "rule": _RULE_PRINT, "line": node.lineno,
                "msg": "product 代码使用 print()，应改用 logger",
            })

    # 未定义符号（星号导入的文件跳过，避免误报）
    skipped_undef = _has_star_import(tree)
    if not skipped_undef:
        bound = _collect_bound_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id in bound or node.id in _BUILTINS or node.id in _CONVENTIONS:
                    continue
                issues.append({
                    "rel": rel, "rule": _RULE_UNDEF, "line": node.lineno,
                    "msg": f"未定义/未导入的名字: {node.id}", "name": node.id,
                })

    return issues, skipped_undef


def _key(it: dict) -> str:
    """违规的唯一键，用于与基线比对（同文件同行同规则去重）。"""
    if it["rule"] == _RULE_UNDEF and it.get("name"):
        return f"{it['rel']}:{it['line']}:{it['rule']}:{it['name']}"
    return f"{it['rel']}:{it['line']}:{it['rule']}"


def _scan() -> Tuple[Dict[str, str], List[str]]:
    """扫描整个 product 树，返回 (键->描述, 因星号导入跳过的文件列表)。"""
    found: Dict[str, str] = {}
    skipped: List[str] = []
    for path in _py_files(SCAN_ROOT):
        issues, skip_undef = _analyze_file(path)
        if skip_undef:
            skipped.append(path.relative_to(ROOT).as_posix())
        for it in issues:
            found[_key(it)] = f"{it['rel']}:{it['line']}  [{it['rule']}]  {it['msg']}"
    return found, skipped


def _print_issues(issues: Dict[str, str], title: str) -> None:
    """按规则分组打印违规清单。"""
    print(f"\n{'=' * 68}")
    print(f"  {title}（{len(issues)} 项）")
    print("=" * 68)
    by_rule: Dict[str, List[str]] = {}
    for desc in issues.values():
        rule = desc.split("[", 1)[1].split("]", 1)[0]
        by_rule.setdefault(rule, []).append(desc)
    for rule in (_RULE_BARE, _RULE_SWALLOW, _RULE_PRINT, _RULE_UNDEF):
        if rule not in by_rule:
            continue
        print(f"\n[{rule}] 共 {len(by_rule[rule])} 项:")
        for desc in by_rule[rule]:
            print(f"  - {desc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="稳定性门禁：防止稳定性回归")
    ap.add_argument("--report", action="store_true", help="列出当前全部违规（含存量）")
    ap.add_argument("--update", action="store_true", help="用当前存量重写基线")
    ap.add_argument("--list-skipped", action="store_true", help="列出因星号导入跳过 undefined 检查的文件")
    args = ap.parse_args()

    found, skipped = _scan()

    if args.list_skipped:
        for s in skipped:
            print(f"- {s}")
        print(f"\n共 {len(skipped)} 个文件因 `from x import *` 跳过未定义符号检查")
        return 0

    if args.update:
        payload = {
            "updated_note": "由 stability_gate.py --update 生成；勿手改",
            "entries": sorted(found.keys()),
        }
        BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已更新基线 {BASELINE}（{len(found)} 项存量）")
        return 0

    if args.report:
        _print_issues(found, "全部违规（含存量）")
        if skipped:
            print(f"\n（另有 {len(skipped)} 个文件因星号导入跳过 undefined 检查）")
        return 0

    # 默认模式：只拦截基线之外的新增违规
    if not BASELINE.is_file():
        print(f"缺少基线，请先固化当前存量: python scripts/stability_gate.py --update")
        return 2

    baseline_set = set(json.loads(BASELINE.read_text(encoding="utf-8")).get("entries") or [])
    new = {k: v for k, v in found.items() if k not in baseline_set}
    removed = baseline_set - set(found.keys())

    if not new:
        suffix = f"（另有 {len(removed)} 项已清除的存量）" if removed else ""
        print(f"OK stability gate clean — 当前 {len(found)} 项，存量 {len(baseline_set)} 项，无新增{suffix}")
        return 0

    print(f"STABILITY GATE FAIL — 发现 {len(new)} 项新增违规（未入基线）")
    _print_issues(new, "新增违规")
    print("\n修复并验证后运行: python scripts/stability_gate.py --update")
    return 1


if __name__ == "__main__":
    sys.exit(main())