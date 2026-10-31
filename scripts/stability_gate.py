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
# 2026-09-25 补：加入 gitignore 的草稿/缓存目录。
# 背景（实测）：本门禁自称扫描 product 代码，但 SKIP_DIRS 漏了 ``app/temp``，
# 而 app/temp 是 gitignore 的草稿目录（临时分析脚本都丢在那里）。
# 后果：写一次临时脚本就带进几十条 print 违规，把门禁顶红、
# 把真实违规淹没在噪声里（实测 631 项新增违规中 564 项来自草稿目录）
# ⇒ 门禁长期处于红状态、无人执行，等于没有门禁。
# 修复：把草稿/缓存类目录全部排除，让门禁只对 product 代码说话。
SKIP_DIRS = {
    "tests", "thirdparty", "__pycache__", "node_modules",
    # —— gitignore 的草稿/缓存/数据目录（非 product 源码）——
    "temp", "temp_ai_editor", "logs", "cache", "data", "models", "output",
    "openclow_data", "packaging_env", ".vscode", "素材库", "短剧AI剪辑输出",
    # —— 显式退役目录（2026-10-31 补）——
    # `app/modules/lego/_retired/` 里放的是被新实现取代的旧文件（如 smart_editing_engine.py）。
    # 它们已移出运行路径，不参与 product 行为，却因 8 处 CLI print 把门禁顶红，
    # 与上面 app/temp 完全同一个教训：门禁要只对**在跑**的 product 代码说话，
    # 否则退役一次就红一次，真实违规会被噪声淹没。
    "_retired",
}

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


def _allow_lines(path: Path, source: str) -> Set[int]:
    """收集带豁免注释的行号。

    有意的控制台输出/吞异常（如 GBK 兜底工具的实现本体）可在行尾加：
      # stability-gate: allow-print（理由）
      # stability-gate: allow-swallow（理由）
    豁免是**逐行**的，且必须写理由，防止被当成随便跳过的后门。
    """
    allowed: Set[int] = set()
    for i, line in enumerate(source.splitlines(), start=1):
        if "stability-gate: allow-" in line:
            allowed.add(i)
    return allowed


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
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # 语法错误由编译门禁（py_compile）负责，此处跳过
        return [], False

    rel = path.relative_to(ROOT).as_posix()
    issues: List[dict] = []
    allowed = _allow_lines(path, source)

    # 裸 except / 吞异常 / print
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                issues.append({
                    "rel": rel, "rule": _RULE_BARE, "line": node.lineno,
                    "msg": "裸 except: 未指定异常类型",
                })
            if _is_swallow(node) and not any(
                ln in allowed for ln in [node.lineno] + [s.lineno for s in node.body]
            ):
                issues.append({
                    "rel": rel, "rule": _RULE_SWALLOW, "line": node.lineno,
                    "msg": "except 块体仅含 pass，吞掉异常",
                })
        elif isinstance(node, ast.Call) and _is_print_call(node):
            if node.lineno in allowed:
                continue
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
    """违规的分组键，用于与基线比对。

    键**不含行号**（`file:rule[:name]`），消除「插一行代码→全部假红」的行位移误报；
    同文件同规则出现多处时靠**计数棘轮**区分（见 _scan/main 的计数比对），
    即同文件新增第二个裸 print 仍会被拦下。
    """
    if it["rule"] == _RULE_UNDEF and it.get("name"):
        return f"{it['rel']}:{it['rule']}:{it['name']}"
    return f"{it['rel']}:{it['rule']}"


def _migrate_legacy_key(old_key: str) -> str:
    """把旧版基线键（含行号）归一化为新版分组键。

    旧格式: `file.py:123:rule` 或 `file.py:123:rule:name`（行号是纯数字段）
    新格式: `file.py:rule` 或 `file.py:rule:name`
    """
    parts = old_key.split(":")
    # 行号是最后一个纯数字段（Windows 路径盘符段如 "D" 不是数字，规则/name 也不是）
    digit_idx = [i for i, p in enumerate(parts) if p.isdigit()]
    if len(digit_idx) == 1:
        parts.pop(digit_idx[0])
    return ":".join(parts)


def _scan() -> Tuple[Dict[str, int], Dict[str, List[str]], List[str]]:
    """扫描整个 product 树。

    返回 (分组键->当前计数, 分组键->描述列表(含行号，仅供展示), 星号导入跳过的文件列表)。
    """
    counts: Dict[str, int] = {}
    descs: Dict[str, List[str]] = {}
    skipped: List[str] = []
    for path in _py_files(SCAN_ROOT):
        issues, skip_undef = _analyze_file(path)
        if skip_undef:
            skipped.append(path.relative_to(ROOT).as_posix())
        for it in issues:
            k = _key(it)
            counts[k] = counts.get(k, 0) + 1
            descs.setdefault(k, []).append(
                f"{it['rel']}:{it['line']}  [{it['rule']}]  {it['msg']}"
            )
    return counts, descs, skipped


def _print_issues(descs: Dict[str, List[str]], title: str) -> None:
    """按规则分组打印违规清单。"""
    total = sum(len(v) for v in descs.values())
    print(f"\n{'=' * 68}")
    print(f"  {title}（{total} 项）")
    print("=" * 68)
    by_rule: Dict[str, List[str]] = {}
    for ds in descs.values():
        for desc in ds:
            rule = desc.split("[", 1)[1].split("]", 1)[0]
            by_rule.setdefault(rule, []).append(desc)
    for rule in (_RULE_BARE, _RULE_SWALLOW, _RULE_PRINT, _RULE_UNDEF):
        if rule not in by_rule:
            continue
        print(f"\n[{rule}] 共 {len(by_rule[rule])} 项:")
        for desc in by_rule[rule]:
            print(f"  - {desc}")


def _load_baseline() -> Dict[str, int]:
    """读取基线，兼容旧版（entries 为含行号的键列表）并自动迁移为计数棘轮。"""
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if isinstance(entries, dict):  # 新版：键->计数
        return {str(k): int(v) for k, v in entries.items()}
    counts: Dict[str, int] = {}
    for old_key in (entries or []):  # 旧版：含行号键列表，归一化后聚合计数
        k = _migrate_legacy_key(str(old_key))
        counts[k] = counts.get(k, 0) + 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="稳定性门禁：防止稳定性回归")
    ap.add_argument("--report", action="store_true", help="列出当前全部违规（含存量）")
    ap.add_argument("--update", action="store_true", help="用当前存量重写基线")
    ap.add_argument("--list-skipped", action="store_true", help="列出因星号导入跳过 undefined 检查的文件")
    args = ap.parse_args()

    counts, descs, skipped = _scan()

    if args.list_skipped:
        for s in skipped:
            print(f"- {s}")
        print(f"\n共 {len(skipped)} 个文件因 `from x import *` 跳过未定义符号检查")
        return 0

    if args.update:
        payload = {
            "version": 2,
            "updated_note": "由 stability_gate.py --update 生成；勿手改。键=file:rule[:name]（不含行号），值=计数棘轮",
            "entries": dict(sorted(counts.items())),
        }
        BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已更新基线 {BASELINE}（{sum(counts.values())} 项存量 / {len(counts)} 个分组键）")
        return 0

    if args.report:
        _print_issues(descs, "全部违规（含存量）")
        if skipped:
            print(f"\n（另有 {len(skipped)} 个文件因星号导入跳过 undefined 检查）")
        return 0

    # 默认模式：只拦截基线之外的新增违规（计数棘轮：当前计数 > 基线计数 即拦）
    if not BASELINE.is_file():
        print("缺少基线，请先固化当前存量: python scripts/stability_gate.py --update")
        return 2

    baseline = _load_baseline()
    new_descs: Dict[str, List[str]] = {}
    new_count = 0
    for k, cur in counts.items():
        base = baseline.get(k, 0)
        if cur > base:
            # 超出的才算新增；展示该键全部位置便于定位（行号见描述）
            new_descs[k] = descs[k]
            new_count += cur - base
    removed = sum(max(0, b - counts.get(k, 0)) for k, b in baseline.items())

    if not new_descs:
        suffix = f"（另有 {removed} 项已清除的存量）" if removed else ""
        print(f"OK stability gate clean — 当前 {sum(counts.values())} 项，存量 {sum(baseline.values())} 项，无新增{suffix}")
        return 0

    print(f"STABILITY GATE FAIL — 发现 {new_count} 项新增违规（超出基线计数）")
    _print_issues(new_descs, "新增违规")
    print("\n修复并验证后运行: python scripts/stability_gate.py --update")
    return 1


if __name__ == "__main__":
    sys.exit(main())