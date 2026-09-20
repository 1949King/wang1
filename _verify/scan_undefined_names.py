# -*- coding: utf-8 -*-
"""全库 AST 作用域扫描 v3：找「引用不存在的名字」这类一跑就崩的硬缺陷。

三代演进（前两代的教训都写在这，避免后人重踩）
=============================================

v1 错在「把整棵子树的 Store 名扁平并成一个集合」→ 内层函数局部名被误判成外层可见，
   闭包变量全部漏判，产出 200KB 假阳性。

v2 修了闭包（真正的词法作用域链 Frame），但**模块级语句的 in-order 检查仍错**：
   它把「该语句自己所在循环/with 的绑定目标」也算作「此前未绑定」，
   于是 `for b in objs: print(b.name)` 被报成「引用未定义名 b」——
   因为绑定目标 `b` 在 `ast.walk` 里被当成 Load 位置之外的独立节点处理。

v3 的关键修正
-------------
模块级语句按**语法顺序**逐条推进，维护一个 `seen` 集合：

* **进入**一条语句时，先把该语句的绑定目标加进 `seen`（Python 里
  `for x in ...` 的 `x` 在**首轮迭代前**就已绑定；`with ... as f` 同理），
* **再**检查这条语句里除「绑定目标位置」以外的 Load 名字。

这样 `for b in objs: print(b.name)` 里 `b` 已在 `seen` 中 ⇒ 不报。
真缺陷（引用一个从未绑定的名字）仍会被抓到。

判定线（保守，只报**确定**的）
------------------------------
名字在「本 frame → 外层 frame 链 → 模块 → 内建」上全找不到才算缺陷。
**不跟踪**：`try/except ImportError` 可选依赖、`TYPE_CHECKING`、`exec` 动态注入、
`from x import *`。命中项仍需人工确认。

用法：
    .venv312/Scripts/python.exe _verify/scan_undefined_names.py
"""
from __future__ import annotations

import ast
import builtins
import io
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git", "node_modules", ".venv312", "venv", "__pycache__",
    ".pytest_cache", "dist", "build", ".workbuddy", "_archive",
    ".mypy_cache", ".ruff_cache", "site-packages",
}

BUILTINS: Set[str] = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__class__", "__dict__",
    "__module__", "__qualname__", "WindowsError", "unicode", "basestring",
}


def target_names(t: ast.AST) -> Set[str]:
    out: Set[str] = set()
    stack = [t]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, (ast.Tuple, ast.List)):
            stack.extend(n.elts)
        elif isinstance(n, ast.Starred):
            stack.append(n.value)
    return out


class Frame:
    def __init__(self, kind: str, node: ast.AST, parent: Optional["Frame"] = None,
                 name: str = ""):
        self.kind = kind
        self.node = node
        self.parent = parent
        self.bound: Set[str] = set()
        self.globals: Set[str] = set()
        self.nonlocals: Set[str] = set()
        self.name = name or (getattr(node, "name", "?") if kind != "module" else "<module>")

    def lookup(self, name: str) -> bool:
        if name in self.globals:
            return _module_frame(self).lookup(name)
        if name in self.nonlocals:
            f = self.parent
            while f is not None and f.kind == "class":
                f = f.parent
            return f.lookup(name) if f else False
        if name in self.bound:
            return True
        f = self.parent
        # 函数/推导式不捕获类体作用域（Python 语义）
        if self.kind in ("function", "comprehension"):
            while f is not None and f.kind == "class":
                f = f.parent
        return f.lookup(name) if f is not None else False


def _module_frame(f: Frame) -> Frame:
    while f.parent is not None:
        f = f.parent
    return f


# ══════════════════════════════════════════════════════════════════
# 绑定收集：一条语句**自身**会绑定哪些名字
# ══════════════════════════════════════════════════════════════════
def stmt_bound(node: ast.AST) -> Set[str]:
    out: Set[str] = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        out.add(node.name)
    elif isinstance(node, ast.Import):
        for a in node.names:
            out.add((a.asname or a.name).split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        for a in node.names:
            if a.name == "*":
                continue
            out.add(a.asname or a.name)
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            out.update(target_names(t))
    elif isinstance(node, ast.AnnAssign):
        out.update(target_names(node.target))
    elif isinstance(node, ast.AugAssign):
        out.update(target_names(node.target))
    elif isinstance(node, (ast.For, ast.AsyncFor)):
        out.update(target_names(node.target))
        for sub in node.body + node.orelse:
            out |= stmt_bound(sub)
    elif isinstance(node, ast.With):
        for it in node.items:
            if it.optional_vars is not None:
                out.update(target_names(it.optional_vars))
        for sub in node.body:
            out |= stmt_bound(sub)
    elif isinstance(node, ast.Try):
        for sub in node.body + node.orelse + node.finalbody:
            out |= stmt_bound(sub)
        for h in node.handlers:
            if h.name:
                out.add(h.name)
            for sub in h.body:
                out |= stmt_bound(sub)
    elif isinstance(node, ast.If):
        for sub in node.body + node.orelse:
            out |= stmt_bound(sub)
    elif isinstance(node, (ast.While,)):
        for sub in node.body + node.orelse:
            out |= stmt_bound(sub)
    elif isinstance(node, ast.Match):
        for case in node.cases:
            for sub in case.body:
                out |= stmt_bound(sub)
    return out


# ══════════════════════════════════════════════════════════════════
# 绑定**位置**节点集合（这些位置上的 Name 是「写入」而非「读取」）
# ══════════════════════════════════════════════════════════════════
def _binding_target_nodes(node: ast.AST) -> Set[int]:
    """返回「作为绑定目标」的 Name / Tuple 节点 id 集合（含循环/with 目标）。"""
    ids: Set[int] = set()

    def mark(t: ast.AST) -> None:
        ids.add(id(t))
        if isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                mark(e)
        elif isinstance(t, ast.Starred):
            mark(t.value)

    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ids.add(id(n))
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                mark(t)
        elif isinstance(n, ast.AnnAssign):
            mark(n.target)
        elif isinstance(n, ast.AugAssign):
            mark(n.target)
        elif isinstance(n, (ast.For, ast.AsyncFor)):
            mark(n.target)
        elif isinstance(n, ast.With):
            for it in n.items:
                if it.optional_vars is not None:
                    mark(it.optional_vars)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            pass  # 字符串字段，不是 Name 节点
        elif isinstance(n, ast.comprehension):
            mark(n.target)
        elif isinstance(n, ast.Global) or isinstance(n, ast.Nonlocal):
            ids.add(id(n))
    return ids


def loads_of(node: ast.AST) -> List[Tuple[str, int]]:
    """语句里**真正读取**的名字（排除绑定目标位置、排除嵌套作用域内部）。

    ⚠️ 若 node 自身就是 FunctionDef/ClassDef，直接返回空 ——
    它的函数体属于**子 frame**，由 `visit()` 单独处理。
    （v3 初版漏了这条，导致函数体内的局部名被当成「模块级引用」，
    产出 2.2MB 假阳性。）
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return []

    skip = _binding_target_nodes(node)
    out: List[Tuple[str, int]] = []

    def walk(n: ast.AST) -> None:
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue  # 交给子 frame
            # lambda 自带一层作用域，其参数与体内自由名都不属于外层
            if isinstance(child, ast.Lambda):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) \
                    and id(child) not in skip:
                out.append((child.id, child.lineno))
            walk(child)

    walk(node)
    return out


# ══════════════════════════════════════════════════════════════════
class Scanner:
    def __init__(self, path: Path):
        self.path = path
        self._src = ""
        self.issues: List[Tuple[int, str, str, str]] = []
        self.star_import = False

    # ── 模块级 ──
    def scan(self, tree: ast.Module) -> List[Tuple[int, str, str, str]]:
        mod = Frame("module", tree)
        for node in tree.body:
            mod.bound |= stmt_bound(node)

        # ⚠️ `from x import *` 会注入任意名字 ⇒ 整个模块无法做静态判定，
        # 直接放弃该模块（否则会产出大量假阳性）。这是诚实的能力边界。
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if any(a.name == "*" for a in node.names):
                    self.star_import = True
                    return []

        seen: Set[str] = set()
        for node in tree.body:
            # ① 先把本条语句的绑定目标并入 seen（循环/with 目标在首轮前即绑定）
            own = stmt_bound(node)
            # ② 再检查本条语句的 Load（排除它自己的绑定位置）
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                seen |= own
                continue
            for nm, ln in loads_of(node):
                if nm in BUILTINS or nm in seen or nm in own:
                    continue
                if self._shadowed_by_comp(node, nm):
                    continue
                self._add(ln, "导入期引用未定义名",
                          f"模块级语句引用 `{nm}`，此前无绑定")
            if isinstance(node, ast.ClassDef):
                self._check_class(node, seen, mod)
            seen |= own

        # ③ 各函数/lambda/推导式
        for node in tree.body:
            self.visit(node, mod)
        return self.issues

    # ── 类体（导入期执行） ──
    def _check_class(self, cls: ast.ClassDef, seen: Set[str], parent: Frame) -> None:
        cf = Frame("class", cls, parent, name=cls.name)
        for s in cls.body:
            cf.bound |= stmt_bound(s)
        inner_seen = set(seen)
        for s in cls.body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner_seen |= stmt_bound(s)
                continue
            own = stmt_bound(s)
            for nm, ln in loads_of(s):
                if nm in BUILTINS or nm in inner_seen or nm in own:
                    continue
                if self._shadowed_by_comp(s, nm):
                    continue
                self._add(ln, "类体引用未定义名",
                          f"class {cls.name} 类体（导入期执行）引用 `{nm}`")
            inner_seen |= own

    @staticmethod
    def _shadowed_by_comp(node: ast.AST, name: str) -> bool:
        """该名字是所在推导式的循环目标（推导式内可见，外面不可见）。"""
        for c in ast.walk(node):
            if isinstance(c, ast.comprehension) and name in target_names(c.target):
                return True
        return False

    # ── 函数 / 推导式遍历 ──
    def visit(self, node: ast.AST, frame: Frame) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = Frame("function", node, frame, name=node.name)
            self._collect(fn)
            self._check_body(node, fn, f"{node.name}()")
            for s in node.body:
                self.visit(s, fn)
        elif isinstance(node, ast.Lambda):
            fn = Frame("function", node, frame, name="<lambda>")
            self._collect(fn)
            self._check_body(node, fn, "<lambda>")
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            cf = Frame("comprehension", node, frame, name="<comprehension>")
            for g in node.generators:
                cf.bound |= target_names(g.target)
                for if_ in g.ifs:
                    self.visit(if_, cf)
            self._check_body(node, cf, "<comprehension>")
        elif isinstance(node, ast.ClassDef):
            cf = Frame("class", node, frame, name=node.name)
            for s in node.body:
                cf.bound |= stmt_bound(s)
            for s in node.body:
                self.visit(s, cf)
        else:
            for child in ast.iter_child_nodes(node):
                self.visit(child, frame)

    def _collect(self, fn: Frame) -> None:
        """收集 frame 内（不跨嵌套函数/类）的绑定 + global/nonlocal。

        ⚠️ `global` / `nonlocal` 是**作用域专属**声明，绝不能跨嵌套函数收集。
        踩过的坑：用 `ast.walk(fn.node)` 会走进内层函数，把内层的
        `nonlocal buf` 当成外层函数的声明 ⇒ 外层 `lookup('buf')` 误以为
        「buf 要到我父层找」而跳过自己的 `bound` ⇒ 内层访问 `buf` 被判未定义
        （project_agent_host.py 13 条假阳性全出在这）。
        """
        self._collect_scope(fn)

    def _collect_scope(self, fn: Frame) -> None:
        """只收本 frame 的语句，遇到嵌套函数/类只登记名字、不深入。"""
        body: List[ast.AST]
        if isinstance(fn.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = fn.node.body
        elif isinstance(fn.node, ast.Lambda):
            body = [fn.node.body]
        elif isinstance(fn.node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            body = []
            for g in fn.node.generators:
                body.append(g.iter)
                body.extend(g.ifs)
            if isinstance(fn.node, ast.DictComp):
                body.extend([fn.node.key, fn.node.value])
            else:
                body.append(fn.node.elt)  # type: ignore[attr-defined]
        else:
            body = list(getattr(fn.node, "body", []))

        def absorb(n: ast.AST) -> None:
            """登记 n **自身**会绑定的名字（不递归）。"""
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    if a.name == "*":
                        continue
                    fn.bound.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                fn.bound.add(n.id)
            elif isinstance(n, ast.arg):
                fn.bound.add(n.arg)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                fn.bound.add(n.name)
            elif isinstance(n, ast.Global):
                fn.globals.update(n.names)
            elif isinstance(n, ast.Nonlocal):
                fn.nonlocals.update(n.names)
            elif isinstance(n, ast.comprehension):
                fn.bound |= target_names(n.target)
            elif isinstance(n, ast.Lambda):
                args = n.args
                for lst in (args.posonlyargs, args.args, args.kwonlyargs):
                    fn.bound.update(a.arg for a in lst)
                if args.vararg:
                    fn.bound.add(args.vararg.arg)
                if args.kwarg:
                    fn.bound.add(args.kwarg.arg)

        def visit(n: ast.AST) -> None:
            # ⚠️ 必须**先看 n 自身**再递归子节点。
            # 踩过的坑：只 iter_child_nodes 不看根节点 ⇒
            # 函数体里的 `import x as mod` 整条语句被漏登记，
            # `mod` 被误报为未定义（verify_mlt_api.py 等大量假阳性全出在这）。
            absorb(n)
            for child in ast.iter_child_nodes(n):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    fn.bound.add(child.name)  # 登记名字，不深入
                    continue
                if isinstance(child, ast.Lambda):
                    absorb(child)  # 只收它的参数名，不深入体内
                    continue
                visit(child)

        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                fn.bound.add(stmt.name)
                continue
            visit(stmt)

        # 参数
        args = getattr(fn.node, "args", None)
        if isinstance(args, ast.arguments):
            for lst in (args.posonlyargs, args.args, args.kwonlyargs):
                fn.bound.update(a.arg for a in lst)
            if args.vararg:
                fn.bound.add(args.vararg.arg)
            if args.kwarg:
                fn.bound.add(args.kwarg.arg)

    def _check_body(self, node: ast.AST, frame: Frame, label: str) -> None:
        """检查 frame 内的自由变量。

        对 FunctionDef/Lambda：遍历它的**参数默认值 + 函数体语句**。
        对推导式：遍历其 elt / 各 generator 的 iter 与 ifs。

        ⚠️ 推导式的**最外层可迭代对象**在 Python 里于「外围作用域」求值
        （本框架记为 frame.parent），不在推导式自己的作用域里。
        实测（Python 3.13）：
            class A:
                D = ['a','b']
                I = {e: i for i, e in enumerate(D)}   # OK（enumerate(D) 在外层求值）
                J = [D[0] for _ in range(1)]          # NameError（D[0] 在推导式作用域）
        漏掉这条规则会把 `drama_understanding_engine.py:542` 这类正确代码误报。
        """
        targets: List[ast.AST] = []
        outer_targets: List[ast.AST] = []  # 在 frame.parent 作用域求值的部分
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = node.args
            for d in list(a.defaults) + [d for d in a.kw_defaults if d is not None]:
                outer_targets.append(d)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                targets.extend(node.body)
            else:
                targets.append(node.body)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            # 最外层 for 的 iter 属于外层作用域
            if node.generators:
                outer_targets.append(node.generators[0].iter)
            if isinstance(node, ast.DictComp):
                targets.extend([node.key, node.value])
            else:
                targets.append(node.elt)  # type: ignore[attr-defined]
            for gi, g in enumerate(node.generators):
                if gi > 0:
                    targets.append(g.iter)
                targets.extend(g.ifs)
        else:
            targets.append(node)

        outer_scope = frame.parent if frame.kind == "comprehension" else None
        for t in outer_targets:
            sc = outer_scope if outer_scope is not None else frame
            for nm, ln in loads_of(t):
                if nm in BUILTINS or sc.lookup(nm):
                    continue
                self._add(ln, "函数体引用未定义名",
                          f"{label} 引用 `{nm}`，整条作用域链上都找不到"
                          f"（调用到即 NameError）")

        for t in targets:
            for nm, ln in loads_of(t):
                if nm in BUILTINS or frame.lookup(nm):
                    continue
                self._add(ln, "函数体引用未定义名",
                          f"{label} 引用 `{nm}`，整条作用域链上都找不到"
                          f"（调用到即 NameError）")

    def _add(self, ln: int, kind: str, detail: str) -> None:
        self.issues.append((ln, kind, detail, self._line(ln)))

    def _line(self, ln: int) -> str:
        try:
            return self._src.splitlines()[ln - 1].strip()[:140]
        except Exception:  # noqa: BLE001
            return ""


def main() -> int:
    print("=" * 74)
    print("全库 AST 作用域扫描 v3 —— 找「引用不存在的名字」（NameError 级硬缺陷）")
    print("=" * 74)

    files: List[Path] = []
    for root, dirs, fnames in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fnames:
            if f.endswith(".py"):
                files.append(Path(root) / f)

    rows: List[Tuple[str, int, str, str, str]] = []
    syntax_err = 0
    scanned = 0
    scan_err = 0

    for p in sorted(files):
        rel = str(p.relative_to(ROOT))
        try:
            # ⚠️ 必须用 utf-8-sig：全库有 5 个文件带 UTF-8 BOM
            # （app/__init__.py、app/modules/__init__.py、core/__init__.py、
            #   mcp_server.py、start_mcp.py）。
            # 用纯 utf-8 读会把 BOM 留成 U+FEFF 字符，ast.parse 直接报
            # "invalid non-printable character U+FEFF" —— 这是**扫描器的假警报**，
            # 不是项目缺陷：CPython 本身按 utf-8-sig 解码源码，这些文件运行完全正常。
            src = io.open(p, encoding="utf-8-sig").read()
            tree = ast.parse(src, filename=rel)
        except SyntaxError as e:
            syntax_err += 1
            print(f"❌ SYNTAX  {rel}:{e.lineno}  {e.msg}")
            continue
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  READ    {rel}: {type(e).__name__}: {e}")
            continue
        scanned += 1
        sc = Scanner(p)
        sc._src = src
        try:
            for ln, kind, detail, code in sc.scan(tree):
                rows.append((rel, ln, kind, detail, code))
        except Exception as e:  # noqa: BLE001
            scan_err += 1
            print(f"⚠️  SCAN    {rel}: {type(e).__name__}: {e}")

    def prio(r):
        rel = r[0]
        tier = 0
        if rel.startswith(("_verify", "scripts", "tools", "temp", "tests")):
            tier = 1
        return (tier, rel, r[1])

    rows.sort(key=prio)
    cur = None
    for rel, ln, kind, detail, code in rows:
        if rel != cur:
            cur = rel
            print(f"\n──── {rel} ────")
        print(f"  L{ln}  [{kind}]")
        if code:
            print(f"        {code}")
        print(f"        → {detail}")

    by_kind: Dict[str, int] = {}
    by_top: Dict[str, int] = {}
    for rel, ln, kind, detail, code in rows:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        top = rel.split(os.sep)[0] if os.sep in rel else "(root)"
        by_top[top] = by_top.get(top, 0) + 1

    print("\n" + "=" * 74)
    print(f"扫描 {scanned} 个 .py（语法错误 {syntax_err} · 扫描器异常 {scan_err}）")
    print(f"可疑项合计：{len(rows)}")
    for k, v in sorted(by_kind.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v}")
    print("  按顶层目录：")
    for k, v in sorted(by_top.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v}")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
