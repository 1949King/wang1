"""AST 作用域扫描：全库猎捕 NameError 类硬缺陷（scan_nameerror_scope）

判定线：名字在「本 frame → 外层 frame 链 → 模块 → 内建」上全找不到才算缺陷。
这类命中 = 该代码路径 100% 崩溃（不是风格问题）。

历代踩坑（改本文件前必读，详见技能 ast-scope-nameerror-hunt）：
1. 必须真词法作用域链 Frame——扁平集合会把闭包变量全漏判（曾产出 200KB 假阳性）。
2. global/nonlocal 只在本 frame 收，绝不用 ast.walk 跨层（曾 13 条假阳性）。
3. 绑定收集先看根节点再递归 children；loads 收集对 FunctionDef/ClassDef/Lambda 早退
   （曾因此 2.2MB / 21622 条假阳性）。
4. 推导式「最外层 for 的 iter」在外围作用域求值，要用 parent frame 判——
   其余部分（元素/if/后续 iter）在推导式作用域，且推导式不捕获类体作用域。
   实测：`{e: i for i, e in enumerate(D)}` OK；`[D[0] for _ in range(1)]` NameError。
5. 读文件必须 utf-8-sig（BOM 文件 ast.parse 会炸；带 BOM 不是项目缺陷）。
6. 含 import * 的文件整体跳过并在报告列出（否则 Qt 文件 42 处全误报）。
7. 注解（annotation）一律跳过——PEP 649 后求值时机变了，跳过只可能漏报、不会误报。
8. 统计自检：合理命中量级 = 个位数到几十条；报出上千条先怀疑检测器。

用法：.venv312/Scripts/python.exe _verify/scan_nameerror_scope.py [目录...]
"""

import ast
import builtins
import sys
from pathlib import Path

BUILTINS = set(dir(builtins))
IGNORE_NAMES = {
    "self", "cls", "__name__", "__file__", "__doc__", "__class__",
    "__package__", "__spec__", "__loader__", "__builtins__",
    "__annotations__", "__qualname__", "__module__",
}


class Frame:
    __slots__ = ("kind", "node", "parent", "name", "bound", "globals",
                 "nonlocals", "loads")

    def __init__(self, kind, node, parent=None, name=""):
        self.kind = kind  # module | function | class | comprehension
        self.node = node
        self.parent = parent
        self.name = name
        self.bound = set()
        self.globals = set()
        self.nonlocals = set()
        self.loads = []  # [(name, lineno)]

    def lookup(self, name):
        if name in self.globals:
            f = self
            while f.parent is not None:
                f = f.parent
            return name in f.bound or name in BUILTINS
        if name in self.nonlocals:
            f = self.parent
            while f is not None and f.kind == "class":
                f = f.parent
            return f.lookup(name) if f else name in BUILTINS
        if name in self.bound:
            return True
        f = self.parent
        # 函数/推导式不捕获类体作用域（Python 语义）
        if self.kind in ("function", "comprehension"):
            while f is not None and f.kind == "class":
                f = f.parent
        if f is not None:
            return f.lookup(name)
        return name in BUILTINS


class Scanner:
    def __init__(self):
        self.frames = []

    # ---- 绑定辅助 ------------------------------------------------------
    @staticmethod
    def _bind_params(args, frame):
        for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            frame.bound.add(a.arg)
        if args.vararg:
            frame.bound.add(args.vararg.arg)
        if args.kwarg:
            frame.bound.add(args.kwarg.arg)

    def _bind_target(self, node, frame):
        """绑定赋值/循环/with 目标位置的名字（Store 语义）。"""
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store,)):
                frame.bound.add(n.id)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef, ast.Lambda)):
                # 目标里不会出现这些，防御性跳过
                continue

    # ---- loads 收集（遇嵌套作用域委托 process） -------------------------
    def _record_loads(self, node, frame):
        if node is None:
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda,
                             ast.ListComp, ast.SetComp, ast.DictComp,
                             ast.GeneratorExp)):
            self._process(node, frame)  # 委托：自身绑定/loads 规则各归各
            return
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                frame.loads.append((node.id, node.lineno))
            return
        # 注解不求值（坑 7）
        if isinstance(node, ast.AnnAssign):
            self._record_loads(node.value, frame)
            return
        if isinstance(node, ast.arg):
            return
        for child in ast.iter_child_nodes(node):
            self._record_loads(child, frame)

    # ---- 主递归 ---------------------------------------------------------
    def _process(self, node, frame):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            frame.bound.add(node.name)
            for d in node.decorator_list:
                self._record_loads(d, frame)
            for d in list(node.args.defaults) + [x for x in node.args.kw_defaults if x]:
                self._record_loads(d, frame)
            nf = Frame("function", node, frame, node.name)
            self.frames.append(nf)
            self._bind_params(node.args, nf)
            for s in node.body:
                self._process(s, nf)
            return
        if isinstance(node, ast.ClassDef):
            frame.bound.add(node.name)
            for d in node.decorator_list:
                self._record_loads(d, frame)
            for b in node.bases:
                self._record_loads(b, frame)
            for k in node.keywords:
                self._record_loads(k.value, frame)
            nf = Frame("class", node, frame, node.name)
            self.frames.append(nf)
            for s in node.body:
                self._process(s, nf)
            return
        if isinstance(node, ast.Lambda):
            for d in list(node.args.defaults) + [x for x in node.args.kw_defaults if x]:
                self._record_loads(d, frame)
            nf = Frame("function", node, frame, "<lambda>")
            self.frames.append(nf)
            self._bind_params(node.args, nf)
            self._process(node.body, nf)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            gens = node.generators
            # 坑 4：最外层 iter 在外围作用域求值
            self._record_loads(gens[0].iter, frame)
            nf = Frame("comprehension", node, frame, "<comp>")
            self.frames.append(nf)
            for g in gens:
                self._bind_target(g.target, nf)
            for g in gens[1:]:
                self._record_loads(g.iter, nf)
            for g in gens:
                for cond in g.ifs:
                    self._record_loads(cond, nf)
            if isinstance(node, ast.DictComp):
                self._process(node.key, nf)
                self._process(node.value, nf)
            else:
                self._process(node.elt, nf)
            return
        if isinstance(node, ast.Import):
            for a in node.names:
                frame.bound.add(a.asname or a.name.split(".")[0])
            return
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != "*":
                    frame.bound.add(a.asname or a.name)
            return
        if isinstance(node, ast.Global):
            frame.globals.update(node.names)
            return
        if isinstance(node, ast.Nonlocal):
            frame.nonlocals.update(node.names)
            return
        if isinstance(node, ast.ExceptHandler):
            if node.type:
                self._record_loads(node.type, frame)
            if node.name:
                frame.bound.add(node.name)
            for s in node.body:
                self._process(s, frame)
            return
        if isinstance(node, ast.Match):
            self._record_loads(node.subject, frame)
            for case in node.cases:
                for n in ast.walk(case.pattern):
                    if isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
                        frame.bound.add(n.name)
                    elif isinstance(n, ast.MatchMapping) and n.rest:
                        frame.bound.add(n.rest)
                if case.guard:
                    self._record_loads(case.guard, frame)
                for s in case.body:
                    self._process(s, frame)
            return
        # 复合语句必须显式处理并逐条 _process 子语句——
        # 否则 if/try/for 体内的 import/赋值/except as 不登记绑定，
        # loads 却照收 → 海量假阳性（本文件 v1 实测 341KB，全是这个坑）
        if isinstance(node, ast.If):
            self._record_loads(node.test, frame)
            for s in node.body + node.orelse:
                self._process(s, frame)
            return
        if isinstance(node, ast.While):
            self._record_loads(node.test, frame)
            for s in node.body + node.orelse:
                self._process(s, frame)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self._record_loads(node.iter, frame)
            self._bind_target(node.target, frame)
            for s in node.body + node.orelse:
                self._process(s, frame)
            return
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self._record_loads(item.context_expr, frame)
                if item.optional_vars:
                    self._bind_target(item.optional_vars, frame)
            for s in node.body:
                self._process(s, frame)
            return
        if isinstance(node, (ast.Try, ast.TryStar)):
            for s in node.body:
                self._process(s, frame)
            for h in node.handlers:
                self._process(h, frame)
            for s in node.orelse + node.finalbody:
                self._process(s, frame)
            return
        # 简单语句（Assign/Expr/Return/Raise/Assert/AugAssign 等）：
        # 表达式里不可能再有语句，绑 Store 目标 + 收 loads 即可
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                frame.bound.add(n.id)
        self._record_loads(node, frame)

    def scan_tree(self, tree):
        module = Frame("module", tree, None, "<module>")
        self.frames.append(module)
        for s in tree.body:
            self._process(s, module)
        return module


def has_star_import(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names):
            return True
    return False


def module_order_defects(tree):
    """模块级变量「使用在赋值之前」检测（跳过 def/class 体——调用时才求值）。"""
    top_def = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.asname or a.name.split(".")[0] for a in node.names]
            else:
                names = [a.asname or a.name for a in node.names if a.name != "*"]
            for nm in names:
                top_def.setdefault(nm, node.lineno)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        top_def.setdefault(n.id, node.lineno)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            top_def.setdefault(node.target.id, node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top_def.setdefault(node.name, node.lineno)
    defects = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Import, ast.ImportFrom)):
            continue
        for x in ast.walk(node):
            if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                              ast.Lambda)) and x is not node:
                continue  # 内层定义体调用时才求值
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load):
                if x.id in top_def and x.lineno < top_def[x.id] \
                        and x.id not in BUILTINS and x.id not in IGNORE_NAMES:
                    defects.append((x.id, x.lineno, top_def[x.id]))
    return defects


def scan_file(path):
    """返回 (hits, order_hits, skipped_reason)。hits=[(line, name, ctx)]"""
    try:
        src = path.read_text(encoding="utf-8-sig")
    except Exception:
        return [], [], "read_error"
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        return [], [], f"syntax_error:{e.lineno}"
    if has_star_import(tree):
        return [], [], "star_import"
    sc = Scanner()
    sc.scan_tree(tree)
    hits = []
    for fr in sc.frames:
        for name, line in fr.loads:
            if name in IGNORE_NAMES:
                continue
            if not fr.lookup(name):
                hits.append((line, name, f"{fr.kind}:{fr.name}"))
    order = module_order_defects(tree)
    return hits, order, None


def main():
    roots = [Path(p) for p in (sys.argv[1:] or ["app", "scripts"])]
    root_files = list(Path(".").glob("*.py"))
    files = []
    for r in roots:
        if r.is_dir():
            files.extend(p for p in r.rglob("*.py")
                         if "__pycache__" not in p.parts and "temp" not in p.parts)
    files.extend(root_files)
    files = sorted(set(files))

    total_hits = total_order = 0
    skipped, parse_bad = [], []
    for p in files:
        hits, order, skip = scan_file(p)
        if skip:
            (parse_bad if skip.startswith("syntax_error") else skipped).append((p, skip))
            continue
        for line, name, ctx in hits:
            print(f"SCOPE  {p}:{line}: 未定义名 `{name}`（{ctx}）")
            total_hits += 1
        for name, use, defin in order:
            print(f"ORDER  {p}:{use}: `{name}` 使用先于赋值（赋值在 :{defin}）")
            total_order += 1
    print("=" * 70)
    print(f"扫描 {len(files)} 个文件 | SCOPE 命中 {total_hits} | ORDER 命中 {total_order}")
    print(f"跳过（import *）{len(skipped)} 个：")
    for p, why in skipped:
        print(f"  SKIP   {p} ({why})")
    if parse_bad:
        print(f"解析失败 {len(parse_bad)} 个：")
        for p, why in parse_bad:
            print(f"  PARSE  {p} ({why})")
    if total_hits == 0 and total_order == 0:
        print("OK 无 NameError 类硬缺陷（合成用例自测见 selftest_scan_nameerror_scope.py）")
    return 1 if (total_hits or total_order) else 0


if __name__ == "__main__":
    sys.exit(main())
