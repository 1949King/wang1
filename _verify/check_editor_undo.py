# -*- coding: utf-8 -*-
"""撤销覆盖与加锁守卫（刀 A3，2026-10-05）。

钉死三件在 2026-10-05 才修好的事 —— 都是**很容易被后人无意改回去**的：

  ① **转场 / 贴纸必须入撤销栈**。此前这两类操作不进 `_action_history`，
     用户改了撤不回（「一切皆可撤销」是剪辑器的第一条铁律，这是它最大的洞）。
  ② **`_apply_action` 必须整段持 `_clips_lock`**。它多步改真相源
     （delete/batch_delete/split/drop/add/edit_clip/stickers/compound），
     不持锁时画布桥的 `_clips_snapshot()` 与 autosave 会读到**半新半旧**的 `_clips`
     —— 这是本文件自写纪律（L473-479）的自违反。
  ③ **撤销/重做栈必须互斥**。`_record_action`（Agent 线程压栈）与 `_undo`
     （UI 线程弹栈）此前无互斥；「pop 后 append 到另一条栈」不是原子操作，
     并发下会出现同一个 action 同时留在两条栈（一次 Ctrl+Z 撤销两步）或凭空消失。

另锁：三个零引用孤儿函数不得回流（它们占体量、又误导真相源边界）。

零项目依赖：只读源码 + AST 定位，不 import editor_module（避免拉 Qt）。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EM_REL = os.path.join("app", "modules", "lego", "editor_module.py")

_fails = []


def _fail(msg: str) -> None:
    _fails.append(msg)


def _read(rel: str) -> str:
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        _fail(f"文件缺失：{rel}")
        return ""
    return open(p, encoding="utf-8").read()


def _func_src(src: str, name: str) -> str:
    """用 AST 取某函数/方法的源码段（**避免 docstring 里提到名字也命中**）。"""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        _fail(f"editor_module.py 语法错误：{e}")
        return ""
    lines = src.split("\n")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return ""


def check_undo_coverage() -> None:
    src = _read(EM_REL)
    if not src:
        return
    # ① 三处入栈
    for fn, what in (("_apply_transition_to_clip", "转场"),
                     ("_apply_sticker", "贴纸参数"),
                     ("_clear_stickers", "清除贴纸")):
        body = _func_src(src, fn)
        if not body:
            _fail(f"① 找不到 {fn}")
        elif "_record_action(" not in body:
            _fail(f"① {what}（{fn}）未入撤销栈 ⇒ 用户改了撤不回")
    if 'atype == "stickers"' not in src:
        _fail("① _apply_action 缺 stickers 分支（贴纸撤销无处落地）")


def check_apply_action_locked() -> None:
    src = _read(EM_REL)
    if not src:
        return
    wrapper = _func_src(src, "_apply_action")
    inner = _func_src(src, "_apply_action_locked")
    if not wrapper or not inner:
        _fail("② 缺 _apply_action / _apply_action_locked（加锁包装被拆掉？）")
        return
    if "_clips_lock" not in wrapper:
        _fail("② _apply_action 未取 _clips_lock（真相源会被读到半新半旧）")
    if "_apply_action_locked(action, mode)" not in wrapper:
        _fail("② _apply_action 未委托给 _apply_action_locked")
    if "atype" in wrapper:
        _fail("② _apply_action 里出现业务分支（应只做加锁 + 委托）")
    # 撤销/重做必须走带锁入口
    for call in ("_apply_action(action, mode='undo')", "_apply_action(action, mode='do')"):
        if call not in src:
            _fail(f"② 撤销/重做未走带锁入口：找不到 {call}")


def check_history_lock() -> None:
    src = _read(EM_REL)
    if not src:
        return
    helper = _func_src(src, "_get_history_lock")
    if not helper:
        _fail("③ 缺 _get_history_lock（撤销栈无互斥）")
        return
    if "threading.RLock()" not in helper:
        _fail("③ _get_history_lock 未用 RLock（重入会死锁）")
    for fn in ("_record_action", "_undo", "_redo"):
        body = _func_src(src, fn)
        if not body:
            _fail(f"③ 找不到 {fn}")
        elif "_get_history_lock()" not in body:
            _fail(f"③ {fn} 未持历史锁（并发压/弹栈会丢 action）")


def check_orphans_removed() -> None:
    """三个零引用孤儿不得回流（A3 顺手清掉，回收体量预算）。"""
    src = _read(EM_REL)
    if not src:
        return
    for name in ("_optimize_workflow", "_remove_fillers_and_silence",
                 "_fallback_subtitle_generation"):
        if _func_src(src, name):
            _fail(f"④ 孤儿函数 {name} 回流（零引用，占用体量且误导真相源）")


def main() -> int:
    print("=" * 62)
    print("编辑器撤销覆盖与加锁守卫（刀 A3）")
    print("=" * 62)
    for fn in (check_undo_coverage, check_apply_action_locked,
               check_history_lock, check_orphans_removed):
        try:
            fn()
        except Exception as e:  # 守卫自身异常也算失败，不静默
            _fail(f"{fn.__name__} 抛异常: {type(e).__name__}: {e}")

    if _fails:
        print("✗ 失败项：")
        for p in _fails:
            print(f"  - {p}")
        return 1
    print("OK 撤销覆盖（转场/贴纸）· _apply_action 持锁 · 撤销栈互斥 · 孤儿已清")
    return 0


if __name__ == "__main__":
    sys.exit(main())
