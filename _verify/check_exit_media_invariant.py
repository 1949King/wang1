# -*- coding: utf-8 -*-
"""退出链路不变量校验（`exit-media` 冻结区的语义守卫）。

为什么需要这个脚本
------------------
`scripts/frozen_zone_guard.py` 只比对**哈希**：它能告诉你「这段冻结代码被改过」，
但**说不出改得对不对**。2026-10-11 实测过一次真实漏网 —— 并发会话把「会话保存」
插到了 `closeEvent` 的第一句、`_stop_all_media_on_exit()` **之前**，
字面违反了 `exit-media` 的不变量「closeEvent 必须先 _stop_all_media_on_exit」。

守卫确实报了漂移（哈希变了），但**报的是「文件被改」而不是「不变量被破」**——
人若只看到「有漂移」就去重锁，这条不变量就静默失效了。
故把 zone 的三条不变量变成**可执行的断言**，进全量回归与 pre-commit。

校验的三条不变量（与 docs/knowledge/frozen_zones.json 的 exit-media.invariants 一一对应）
--------------------------------------------------------------------------------------------
A. `MainWindow.closeEvent` 必须**先** `_stop_all_media_on_exit()`
   —— 口径：跳过 docstring 与纯 `logger.*` 调用后，第一条真正产生副作用的语句
      必须是 `self._stop_all_media_on_exit()`。（原实现首句就是 `logger.info`，
      故不能死抠「绝对第一句」；这里卡的是「第一个动作」。）
B. `EditorModule.cleanup` 必须调 `self._shutdown_media(release_source=True)`
C. `MainWindow._stop_all_media_on_exit` 须齐备「mute + stop + setSource 空 URL」三件套

用法::

    python _verify/check_exit_media_invariant.py
"""
from __future__ import annotations

import ast
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_MAIN_WINDOW = os.path.join("app", "modules", "lego", "main_window.py")
_EDITOR = os.path.join("app", "modules", "lego", "editor_module.py")

_FAILS: list[str] = []


def _parse(rel: str) -> ast.Module:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=rel)


def _find_funcs(tree: ast.Module, name: str) -> list[ast.AST]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]


def _call_name(node: ast.AST) -> str:
    """把 Call 的 func 渲染成 'self._foo' / 'obj.bar' / 'baz' 形式，便于比对。"""
    if not isinstance(node, ast.Call):
        return ""
    parts: list[str] = []
    cur: ast.AST = node.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _is_logger_call(stmt: ast.stmt) -> bool:
    """纯日志语句（logger.xxx(...) / logging.xxx(...)）——不算「动作」。"""
    if not isinstance(stmt, ast.Expr):
        return False
    return _call_name(stmt.value).startswith(("logger.", "logging."))


def _first_action(func: ast.AST) -> ast.stmt | None:
    body = list(getattr(func, "body", []))
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # 跳过 docstring
    for stmt in body:
        if isinstance(stmt, ast.Pass) or _is_logger_call(stmt):
            continue
        return stmt
    return None


def check_a() -> None:
    """A. closeEvent 的第一个动作必须是 _stop_all_media_on_exit()。"""
    tree = _parse(_MAIN_WINDOW)
    funcs = _find_funcs(tree, "closeEvent")
    if not funcs:
        _FAILS.append(f"A: {_MAIN_WINDOW} 里找不到 closeEvent")
        return
    first = _first_action(funcs[0])
    if first is None:
        _FAILS.append("A: closeEvent 内没有任何动作语句")
        return
    got = _call_name(first.value) if isinstance(first, ast.Expr) else ""
    if got != "self._stop_all_media_on_exit":
        _FAILS.append(
            "A: closeEvent 的第一个动作不是 self._stop_all_media_on_exit()"
            f"（实得 {got or ast.dump(first)[:60]}，行 {first.lineno}）"
            " —— 不变量：关程序必须先停声，否则 Windows WMF 关窗后仍出声"
        )
        return
    print("  ✓ A closeEvent 第一个动作 = self._stop_all_media_on_exit()")


def check_b() -> None:
    """B. EditorModule.cleanup 必须调 _shutdown_media(release_source=True)。"""
    tree = _parse(_EDITOR)
    funcs = _find_funcs(tree, "cleanup")
    if not funcs:
        _FAILS.append(f"B: {_EDITOR} 里找不到 cleanup")
        return
    ok = False
    for node in ast.walk(funcs[0]):
        if not isinstance(node, ast.Call) or not _call_name(node).endswith("_shutdown_media"):
            continue
        for kw in node.keywords:
            if kw.arg == "release_source" and isinstance(kw.value, ast.Constant):
                if kw.value.value is True:
                    ok = True
    if not ok:
        _FAILS.append(
            "B: EditorModule.cleanup 未以 release_source=True 调 _shutdown_media"
            "（关进程必须释放 source，否则播放器持有文件句柄）"
        )
        return
    print("  ✓ B EditorModule.cleanup → _shutdown_media(release_source=True)")


def check_c() -> None:
    """C. _stop_all_media_on_exit 须齐备 mute + stop + setSource 空 URL。"""
    tree = _parse(_MAIN_WINDOW)
    funcs = _find_funcs(tree, "_stop_all_media_on_exit")
    if not funcs:
        _FAILS.append(f"C: {_MAIN_WINDOW} 里找不到 _stop_all_media_on_exit")
        return
    calls: set[str] = set()
    empty_url_source = False
    for node in ast.walk(funcs[0]):
        if not isinstance(node, ast.Call):
            continue
        calls.add(_call_name(node))
        # setSource(QUrl()) —— 参数为空 QUrl 才算「清空 source」
        if _call_name(node).endswith("setSource") and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Call) and _call_name(arg).endswith("QUrl") and not arg.args:
                empty_url_source = True
    mute_ok = any(c.endswith("setMuted") for c in calls)
    stop_ok = any(c.endswith("stop") for c in calls)
    missing = []
    if not mute_ok:
        missing.append("mute(setMuted)")
    if not stop_ok:
        missing.append("stop")
    if not empty_url_source:
        missing.append("setSource(QUrl()) 清空")
    if missing:
        _FAILS.append("C: _stop_all_media_on_exit 缺 " + "/".join(missing))
        return
    print("  ✓ C _stop_all_media_on_exit 齐备 mute + stop + setSource(QUrl())")


def main() -> int:
    print("=" * 62)
    print("退出链路不变量校验（exit-media zone 的语义守卫）")
    print("=" * 62)
    check_a()
    check_b()
    check_c()
    if _FAILS:
        print()
        for item in _FAILS:
            print(f"  ✗ {item}")
        print()
        print("✗ 退出链路不变量被破坏 —— 改动需先获用户「解冻 exit-media」，并同步更新 zone 不变量或恢复原序")
        return 1
    print()
    print("OK 退出链路三条不变量全部成立（closeEvent 先停媒体 / cleanup release_source / mute+stop+清源）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
