# -*- coding: utf-8 -*-
"""拾光剪影 · 代码健康度体检（只读，不改任何文件）

对应报告：docs/_reports/2026-09-14-代码实测体检与产品定位.md

用法：
    python _verify/check_code_health.py            # 打印报告
    python _verify/check_code_health.py --strict   # 超阈值返回非 0（可挂 CI）

检测项：
  1. 代码规模（文件数 / 行数 / 最大文件 TOP20）
  2. 同类内重复方法定义（F811 静默覆盖 —— 已排除 @property + @setter 正常配对）
  3. except: pass 静默失败
  4. 超 50 行函数（可维护性红线）
  5. 空壳 / stub 函数
  6. 零引用大文件（孤岛 / 死代码）
  7. 硬编码凭据
  8. 裸 print() 调用

扫描口径：app/ + scripts/ + _verify/ 下全部 .py，
跳过 __pycache__ / node_modules / logs / .venv* / dist / build / _archive /
site-packages / app/skills/external（第三方 skill helper）。
不 import 被测模块，纯 AST + 正则静态扫描，无副作用。

基线（2026-09-14）：401 文件 / 163,563 行 / except:pass 249 / 超长函数 561 /
空壳 59 / 孤岛 23 个 10,359 行 / 重复定义 2（待修）/ 硬编码凭据 0。
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", "logs", ".venv", "venv", ".venv312",
    "dist", "build", "site-packages", "_archive", "external",
}
SCAN_DIRS = ("app", "scripts", "_verify")

# 阈值（--strict 时用于判定）
LIMITS = {
    "dup_method": 0,        # 重复定义必须为 0
    "hardcoded_secret": 0,  # 硬编码凭据必须为 0
    "except_pass": 249,     # 已存量基线（只许降不许升，与 2026-09-14 报告对齐）
    "long_func_ratio": 0.10,
}

SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}"
    r"|api[_-]?key\s*=\s*[\"'][A-Za-z0-9\-_]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|password\s*=\s*[\"'][^\"']{4,}[\"'])",
    re.I,
)
EXCEPT_PASS_RE = re.compile(r"except[^:]*:\s*\n\s*(pass|\.\.\.)", re.M)
EXCEPT_PASS_INLINE_RE = re.compile(r"except[^:]*:\s*(pass|\.\.\.)\s*$", re.M)
TODO_RE = re.compile(r"#\s*(TODO|FIXME|XXX|HACK)\b", re.I)


def iter_py():
    for sub in SCAN_DIRS:
        base = os.path.join(ROOT, sub)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def rel(p: str) -> str:
    return os.path.relpath(p, ROOT)


def read(p: str) -> str:
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except (UnicodeDecodeError, OSError):
        return ""


def is_property_pair(node: ast.ClassDef, name: str) -> bool:
    """判断同名方法是否为 @property + @x.setter 正常配对（非缺陷）。"""
    kinds = []
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == name:
            decs = {getattr(d, "attr", getattr(d, "id", "")) for d in item.decorator_list}
            kinds.append("setter" if "setter" in decs else
                         ("property" if "property" in decs else "plain"))
    if len(kinds) == 2 and set(kinds) == {"property", "setter"}:
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="超阈值返回非 0")
    args = ap.parse_args()

    files = list(iter_py())
    srcs = {p: read(p) for p in files}

    total = blank = comment = 0
    sizes: list[tuple[int, str]] = []
    dup: list[tuple[str, str, str, int, int]] = []
    expass: list[tuple[str, int]] = []
    longf: list[tuple[int, str, str, int]] = []
    stubs: list[tuple[str, str, int, str]] = []
    todos: list[tuple[str, int]] = []
    prints = 0
    secrets: list[tuple[str, int, str]] = []
    parse_fail: list[tuple[str, int, str]] = []
    parent_class: dict[str, dict[str, tuple[int, ast.ClassDef]]] = {}

    for p in files:
        src = srcs[p]
        r = rel(p)
        lines = src.splitlines()
        total += len(lines)
        for ln in lines:
            s = ln.strip()
            if not s:
                blank += 1
            elif s.startswith("#"):
                comment += 1
        sizes.append((len(lines), r))
        prints += len(re.findall(r"(?<![\w.])print\s*\(", src))
        for m in EXCEPT_PASS_RE.finditer(src):
            expass.append((r, src[: m.start()].count("\n") + 1))
        for m in EXCEPT_PASS_INLINE_RE.finditer(src):
            expass.append((r, src[: m.start()].count("\n") + 1))
        for m in TODO_RE.finditer(src):
            todos.append((r, src[: m.start()].count("\n") + 1))
        if not os.path.basename(p).startswith("test_"):
            for m in SECRET_RE.finditer(src):
                secrets.append((r, src[: m.start()].count("\n") + 1, m.group(0)[:40]))

        try:
            tree = ast.parse(src, filename=p)
        except SyntaxError as e:
            parse_fail.append((r, e.lineno or 0, e.msg))
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                seen: dict[str, int] = {}
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        if item.name in seen and not is_property_pair(node, item.name):
                            dup.append((r, node.name, item.name,
                                        seen[item.name], item.lineno))
                        seen[item.name] = item.lineno
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n = (node.end_lineno or node.lineno) - node.lineno + 1
                if n > 50:
                    longf.append((n, r, node.name, node.lineno))
                body = [b for b in node.body if not (
                    isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant)
                    and isinstance(b.value.value, str))]
                if not body:
                    stubs.append((r, node.name, node.lineno, "空函数体"))
                    continue
                only = body[0]
                if len(body) == 1 and isinstance(only, ast.Pass):
                    stubs.append((r, node.name, node.lineno, "pass"))
                elif len(body) == 1 and isinstance(only, ast.Raise) and \
                        "NotImplemented" in ast.dump(only.exc):
                    stubs.append((r, node.name, node.lineno, "NotImplementedError"))

    # ── 孤岛探测（按模块名全库引用计数）─────────────────────────
    mod_index: dict[str, list[str]] = defaultdict(list)
    for p in files:
        bn = os.path.splitext(os.path.basename(p))[0]
        mod_index[bn].append(p)
    orphans: list[tuple[int, str]] = []
    for bn, paths in mod_index.items():
        if bn.startswith("__") or bn.startswith(("test_", "check_")):
            continue
        loc = len(srcs[paths[0]].splitlines())
        if loc < 200:
            continue
        hit = False
        for q, s in srcs.items():
            if q in paths:
                continue
            if re.search(rf"\b{re.escape(bn)}\b", s):
                hit = True
                break
        if not hit:
            orphans.append((loc, rel(paths[0])))
    orphans.sort(reverse=True)

    # ── 输出 ────────────────────────────────────────────────
    bar = "=" * 72
    print(bar)
    print("拾光剪影 · 代码健康度体检")
    print(bar)
    print(f"Python 文件      {len(files)}")
    print(f"总行数           {total}   （空行 {blank} / 纯注释 {comment}）"
          f"  有效 ≈ {total - blank - comment}")
    print(f"AST 解析失败     {len(parse_fail)}")
    for r, ln, msg in parse_fail:
        print(f"    {r}:{ln}  {msg}")

    print()
    print(bar)
    print("最大 20 个文件")
    print(bar)
    for n, r in sorted(sizes, reverse=True)[:20]:
        print(f"{n:>7} 行  {r}")

    print()
    print(bar)
    print(f"重复方法定义（静默覆盖）  {len(dup)}")
    print(bar)
    for r, cls, meth, a, b in dup:
        print(f"  {r} :: {cls}.{meth}()  :{a} 被 :{b} 覆盖")
    if not dup:
        print("  未发现 —— OK")

    print()
    print(bar)
    print(f"except: pass 静默失败  {len(expass)} 处 / "
          f"{len({r for r, _ in expass})} 文件")
    print(bar)
    per = defaultdict(int)
    for r, _ in expass:
        per[r] += 1
    for r, c in sorted(per.items(), key=lambda x: -x[1])[:12]:
        print(f"{c:>4} 处  {r}")

    print()
    print(bar)
    print(f"超 50 行函数  {len(longf)}")
    print(bar)
    for n, r, name, ln in sorted(longf, reverse=True)[:15]:
        print(f"{n:>5} 行  {r}::{name}()  :{ln}")

    print()
    print(bar)
    print(f"空壳函数（空体 / 仅 pass / 仅 NotImplementedError）  {len(stubs)}      "
          f"TODO/FIXME  {len(todos)}      裸 print()  {prints}")
    print(bar)
    sper = defaultdict(int)
    for r, _, _, _ in stubs:
        sper[r] += 1
    for r, c in sorted(sper.items(), key=lambda x: -x[1])[:10]:
        print(f"{c:>4} 个  {r}")

    print()
    print(bar)
    print(f"硬编码凭据  {len(secrets)}")
    print(bar)
    for r, ln, s in secrets[:15]:
        print(f"  {r}:{ln}  {s}")
    if not secrets:
        print("  未发现 —— OK")

    print()
    print(bar)
    print(f"零引用大文件（孤岛，>200 行）  {len(orphans)} 个 / "
          f"{sum(n for n, _ in orphans)} 行")
    print(bar)
    for n, r in orphans:
        print(f"{n:>6} 行  {r}")
    if not orphans:
        print("  未发现 —— OK")

    # ── 判定 ────────────────────────────────────────────────
    violations = []
    if len(dup) > LIMITS["dup_method"]:
        violations.append(f"重复方法定义 {len(dup)} > {LIMITS['dup_method']}")
    if len(secrets) > LIMITS["hardcoded_secret"]:
        violations.append(f"硬编码凭据 {len(secrets)} > {LIMITS['hardcoded_secret']}")
    if len(expass) > LIMITS["except_pass"]:
        violations.append(f"except:pass {len(expass)} > 存量上限 {LIMITS['except_pass']}")

    print()
    print(bar)
    if violations:
        print("判定：需处理")
        for v in violations:
            print(f"  ✗ {v}")
    else:
        print("判定：OK（无阻断项）")
    print(bar)

    if args.strict and violations:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
