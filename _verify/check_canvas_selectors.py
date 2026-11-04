# -*- coding: utf-8 -*-
"""画布 selector 反模式守卫（2026-10-14 新增）。

背景（React error #185 = Maximum update depth exceeded）
========================================================
zustand v5 + React 19 内部走 `useSyncExternalStore`。若 selector 每次调用都返回
**新引用**（新数组 / 新对象，如 `(s) => s.nodes.filter(...)` 或 `(s) => ({a:s.a})`），
React 就判定「快照一直在变」⇒ 无限重渲染 ⇒ 画布白屏「画布遇到渲染错误」。

这是**一类**脆弱写法，不盯住就会「修一个漏一个」。本守卫把它变成红线：
凡是 zustand 的 `use<X>Store((s) => ...)` 选择器里出现下列任一「造新引用」写法即判失败
（除非显式包了 `useShallow(` / `useCanvasShallow(`）：
  · 返回新数组的方法：`.filter(` / `.map(` / `.slice(` / `.sort(` / `.concat(` / `.reduce(`
    / `.reverse(` / `.flatMap(` / `.flat(` / `.fill(` / `.toSorted(` / `.toReversed(` / `.toSpliced(` / `.with(`
  · 构造/静态方法：`new Set(` / `new Map(` / `new Array(` / `Array.of(` / `Array.from(` / `Object.assign(`
    / `Object.keys(` / `Object.values(` / `Object.entries(` / `JSON.parse(`
  · 直接返回对象/数组字面量 `=> ({` / `=> [`
  · 对象/数组**展开**（`{ ...` / `[ ...`）——即便不是字面量开头（如 `s.a ? { ...s.o } : {}`）

零项目依赖：纯文本扫描，按文件路径直接读，不 import app 包。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_REL = os.path.join("vendor", "packages", "canvas-core", "src")

# 会「制造新引用」的数组方法（出现在 selector 体内即为反模式）
FRESH_REF_CALLS = (
    ".filter(", ".map(", ".slice(", ".sort(", ".concat(",
    ".reduce(", ".reverse(", ".flatMap(", ".flat(", ".fill(",
    ".toSorted(", ".toReversed(", ".toSpliced(", ".with(",
)
# 会「制造新引用」的构造 / 静态方法
FRESH_REF_BUILDERS = (
    "new Set(", "new Map(", "new Array(", "Array.of(", "Array.from(",
    "Object.assign(", "Object.keys(", "Object.values(", "Object.entries(",
    "JSON.parse(",
)
# selector 直接返回字面量（body 以 `({` / `[` / `{` 开头）
FRESH_REF_LITERAL = re.compile(r"\s*(?:\(\s*)?[\[{]")
# selector 体内出现对象/数组展开（`{ ...` / `[ ...`）⇒ 必是新引用
FRESH_REF_SPREAD = re.compile(r"[\{\[]\s*\.\.\.")

STORE_CALL = re.compile(r"use[A-Za-z_]*Store\(")


def _strip_comments(text):
    """去掉注释（保留行号）：先抹块注释（保留换行），再按行裁 `//` 行注释（尊重引号）。"""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    out = []
    for line in text.split("\n"):
        quote = None
        cut = None
        i = 0
        while i < len(line):
            ch = line[i]
            if quote:
                if ch == "\\":
                    i += 2
                    continue
                if ch == quote:
                    quote = None
            elif ch in "'\"`":
                quote = ch
            elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                cut = i
                break
            i += 1
        out.append(line[:cut] if cut is not None else line)
    return "\n".join(out)

_fails = []


def check(name, ok, detail=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        _fails.append(name)


def _iter_sources():
    """遍历 src 下的 ts/tsx（跳过测试与 d.ts）。"""
    for base, _dirs, files in os.walk(os.path.join(ROOT, SRC_REL)):
        for fn in files:
            if fn.endswith((".ts", ".tsx")) and not fn.endswith(".test.ts") and not fn.endswith(".test.tsx"):
                yield os.path.join(base, fn)


def _matching_close(text, open_idx):
    """返回 text 中以 open_idx 处 '(' 起始的配对 ')' 下标；找不到返回 -1。"""
    depth = 0
    for i in range(open_idx, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def scan_file(path):
    """返回该文件里所有违规 selector 的 (行号, 片段)。"""
    with open(path, encoding="utf-8") as f:
        text = _strip_comments(f.read())
    hits = []
    for m in STORE_CALL.finditer(text):
        open_idx = m.end() - 1  # '(' 的位置
        close_idx = _matching_close(text, open_idx)
        if close_idx < 0:
            continue
        slice_ = text[open_idx + 1:close_idx]
        # 必须真的带 `(s) =>` 形式的选择器
        arrow = re.search(r"\(\s*\w+\s*\)\s*=>", slice_)
        if not arrow:
            continue
        body = slice_[arrow.end():]
        # 显式浅比较 ⇒ 放行（zustand 原生 useShallow 或本项目入口 useCanvasShallow）
        if "useShallow(" in slice_ or "useCanvasShallow(" in slice_:
            continue
        bad = None
        for call in FRESH_REF_CALLS + FRESH_REF_BUILDERS:
            if call in body:
                bad = call.rstrip("(")
                break
        if not bad and FRESH_REF_LITERAL.match(body):
            bad = "对象/数组字面量"
        if not bad and FRESH_REF_SPREAD.search(body):
            bad = "对象/数组展开"
        if bad:
            line_no = text.count("\n", 0, m.start()) + 1
            hits.append((line_no, bad))
    return hits


def main() -> int:
    print("== 画布 selector 反模式守卫（防 React #185）==")

    src_dir = os.path.join(ROOT, SRC_REL)
    check("画布源码目录存在", os.path.isdir(src_dir), SRC_REL)
    if not os.path.isdir(src_dir):
        print("\nFAILED 1: 画布源码目录缺失")
        return 1

    # 自检：守卫自身的判据要对（喂一段合成代码，必须能抓出各种反模式、放行合规写法）
    samples = [
        'const a = useCanvasStore((s) => s.nodes.filter((n) => n.selected));',   # 1 bad: filter
        'const b = useCanvasStore((s) => ({ x: s.a, y: s.b }));',                # 2 bad: 字面量
        'const f = useCanvasStore((s) => (s.a ? { ...s.o } : {}));',             # 3 bad: 展开
        'const g = useCanvasStore((s) => Object.values(s.map));',                # 4 bad: 静态方法
        'const c = useCanvasStore((s) => s.nodes);',                             # 5 ok: 稳定引用
        'const d = useCanvasStore(useShallow((s) => ({ x: s.a, y: s.b })));',    # 6 ok: useShallow
    ]
    tmp = os.path.join(ROOT, SRC_REL, "__guard_selftest__.ts")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(samples))
        self_hits = scan_file(tmp)
        hit_lines = sorted(h[0] for h in self_hits)
        check("守卫自检：抓出 filter/字面量/展开/静态方法 四类反模式",
              hit_lines == [1, 2, 3, 4], str(self_hits))
        check("守卫自检：放行稳定引用与 useShallow 写法",
              all(h[0] not in (5, 6) for h in self_hits), str(self_hits))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    # 全量扫描
    total = 0
    offenders = []
    for path in _iter_sources():
        for line_no, bad in scan_file(path):
            total += 1
            rel = os.path.relpath(path, ROOT)
            offenders.append(f"{rel}:{line_no} — {bad}")

    check("画布无 selector 新引用反模式（防 #185）", total == 0,
          "; ".join(offenders[:10]) + (" …" if total > 10 else ""))

    print()
    if _fails:
        print(f"FAILED {len(_fails)}: {_fails}")
        return 1
    print("OK 画布 selector 全部安全（稳定引用 / useShallow）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
