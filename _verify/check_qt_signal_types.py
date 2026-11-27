#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 PySide6 Signal 参数类型并识别旧 pyqtSignal 残留 —— 纯 AST，毫秒级。

跑法: python _verify/check_qt_signal_types.py

为什么需要这个守卫（2026-10-09 实测事故）：
    `app/core/ai_interpolation.py:249` 写的是
        interpolation_ready = pyqtSignal(float, List[np.ndarray])
    pyqtSignal 只接受**真实 Python 类型 / bytes / ASCII 字符串**；typing 的泛型
    别名（`typing.List[np.ndarray]` 是 `_GenericAlias`）会在**类体执行期**抛
        TypeError: bytes or ASCII string expected not '_GenericAlias'
    异常发生在模块顶层 ⇒ **整个模块 import 失败**。连锁后果：
      * preview_manager._process_frame 里那句 import 无 try/except
        ⇒ 用户一开启补帧就崩渲染线程；
      * deformity_repair_skill._try_real_interpolation 被 try/except 吞掉
        ⇒ Agent 补帧能力永远返回「不可用」，**静默失效且无人发现**；
      * 覆盖率 0% 也有它一份 —— 模块根本进不来。
    这类缺陷 ruff / tsc / stability_gate 全都看不见（语法完全合法），
    只有真去 import 才炸。所以用 AST 静态扫一遍最划算。

判定：`pyqtSignal(...)` / `Signal(...)` 的实参里出现 typing 泛型的
      * 下标用法  `List[X]` / `Dict[K,V]` / `Optional[X]` …
      * 裸名字    `List` / `Dict` / `Any` …（它们本身就是 _GenericAlias）
      * 属性用法  `typing.List[X]` / `QtCore.pyqtSignal` 之外的 `tt.List`
      一律 FAIL，并给出文件:行号 + 建议改法。

退出码：0=通过；1=发现问题。
"""
from __future__ import annotations

import ast
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCAN_DIRS = ("app",)
SKIP_PARTS = {
    "__pycache__", "node_modules", ".venv312", "venv312", "venv",
    "build", "dist", ".mypy_cache", ".ruff_cache", "thirdparty",
}

# typing 里那些「不能进 Signal/pyqtSignal」的名字（都是 _GenericAlias / _SpecialForm）
BAD_TYPING_NAMES = {
    "List", "Dict", "Tuple", "Set", "FrozenSet", "Deque", "DefaultDict",
    "Optional", "Union", "Callable", "Sequence", "Mapping", "MutableMapping",
    "Iterable", "Iterator", "Generator", "Awaitable", "Coroutine",
    "Type", "ClassVar", "Final", "Literal", "Annotated", "Any", "NoReturn",
    "NamedTuple", "TypedDict",
}

SIGNAL_NAMES = {"pyqtSignal", "Signal", "pyqtBoundSignal"}

# 建议改法：载荷取什么样的对象就用 object / list / dict（都是真实类型）
SUGGEST = {
    "list": "object 或 list",
    "dict": "object 或 dict",
    "tuple": "object 或 tuple",
}
GENERIC_HINT = "object（或对应的内建类型 list/dict/tuple）"


def _iter_py_files():
    for base in SCAN_DIRS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, base)):
            dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS]
            for fn in filenames:
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def _call_name(node: ast.AST) -> str:
    """取调用名（支持 QtCore.Signal / QtCore.pyqtSignal 这类属性访问）。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _bad_arg(arg: ast.AST) -> str:
    """若该实参是 typing 泛型别名 → 返回人话描述；否则返回空串。"""
    # List[X] / Dict[K, V] / Optional[X] / typing.List[X]
    if isinstance(arg, ast.Subscript):
        base = arg.value
        name = _call_name(base)
        if name in BAD_TYPING_NAMES:
            return f"{name}[...] 泛型下标"
        return ""
    # 裸 List / Dict / Any（无下标，本身仍是 _GenericAlias）
    if isinstance(arg, ast.Name) and arg.id in BAD_TYPING_NAMES:
        return f"裸 typing.{arg.id}"
    # typing.List / tt.Any 形式的属性访问
    if isinstance(arg, ast.Attribute) and arg.attr in BAD_TYPING_NAMES:
        return f"{_call_name(arg.value)}.{arg.attr} 属性访问"
    return ""


def main() -> int:
    problems = []
    scanned = 0
    signal_calls = 0
    legacy_signal_calls = 0

    for path in _iter_py_files():
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "pyqtSignal" not in src and "Signal(" not in src:
            continue
        scanned += 1
        try:
            tree = ast.parse(src, filename=path)
        except SyntaxError as e:
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            problems.append((rel, e.lineno or 0, f"语法错误：{e.msg}", ""))
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name not in SIGNAL_NAMES:
                continue
            signal_calls += 1
            if name == "pyqtSignal":
                legacy_signal_calls += 1
            for arg in node.args:
                why = _bad_arg(arg)
                if why:
                    rel = os.path.relpath(path, ROOT).replace("\\", "/")
                    # 试着给出更贴近的建议
                    hint = GENERIC_HINT
                    if isinstance(arg, ast.Subscript):
                        inner = _call_name(arg.value)
                        if inner in ("List", "Sequence", "Iterable", "Set", "FrozenSet"):
                            hint = SUGGEST["list"]
                        elif inner in ("Dict", "Mapping", "MutableMapping", "DefaultDict"):
                            hint = SUGGEST["dict"]
                        elif inner in ("Tuple",):
                            hint = SUGGEST["tuple"]
                    problems.append((rel, node.lineno, why, hint))

    print(f"── 扫描完成：{scanned} 个含信号声明的 .py，{signal_calls} 处 Signal/pyqtSignal 调用")
    print(f"── 旧 pyqtSignal 残留：{legacy_signal_calls} 处（仍执行 typing 泛型检查）")
    if problems:
        print()
        for rel, line, why, hint in problems:
            print(f"✗ {rel}:{line}  {why}")
            if hint:
                print(f"     ⇒ 建议改用 {hint}（typing 泛型不能进 Qt Signal）")
        print()
        print(f"FAILED ({len(problems)} 处)")
        print("  说明：这会让整个模块 import 失败，不是风格问题。")
        return 1
    print(f"ALL PASS（{scanned} 文件 / {signal_calls} 处信号声明全部合法）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
