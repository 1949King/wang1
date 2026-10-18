# -*- coding: utf-8 -*-
"""撤销栈 diff-v1 格式守卫（OTIO 真相源迁移·刀6，UNDO）。

钉死刀6 建立的四件事，都是**很容易被后人无意改回去**的：

  ① **schema 中央盖章** —— ``_record_action`` 对每条 action 盖
     ``schema=diff-v1``；撤销快照自此承诺「深拷 + 按 id 还原」。
  ② **构造点深拷化** —— split/复制粘贴/删除的 clip 快照、键帧/滤镜/转场的
     before/after、贴纸整表快照一律 ``copy.deepcopy``；浅拷（``dict(live)`` /
     ``dict(clip)`` / ``list(...)``）会让快照与活体共享嵌套可变值，任一侧
     原地突变即串改撤销快照（代码审查实证缺陷，浅拷回流由本守卫封死）。
  ③ **split 双格式并存** —— 读侧同时保留「新格式按 ``original_clip_id`` 走
     store.set_fields 还原」与「旧格式整段引用直接还原」两条分支；
     edit_commands/粗剪仍产旧格式，**清理旧分支即炸粗剪撤销**。
  ④ **成员判据** —— 读侧「片段是否已在真相源」一律 ``find_by_id`` 按 id 判定；
     ``not in self._clips`` 的 dict 全等比较在深拷快照下既慢又错，禁止回流。

另锁：冻结符号体内、FROZEN 标记块内**零压栈**（动态读 frozen_zones.json，
防「在冻结函数里加撤销记录」这类误触）。

零项目依赖：只读源码 + AST 定位，不 import editor_module（避免拉 Qt）。
用法（项目根执行）：
  .venv312\\Scripts\\python.exe _verify/check_undo_diff_format.py
退出码 0 = 达标；1 = 断言失败。
"""
import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EM_REL = os.path.join("app", "modules", "lego", "editor_module.py")
ZONES_REL = os.path.join("docs", "knowledge", "frozen_zones.json")

_fails = []


def _fail(msg: str) -> None:
    _fails.append(msg)


def _read(rel: str) -> str:
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        _fail(f"文件缺失：{rel}")
        return ""
    return open(p, encoding="utf-8").read()


def _strip_comments(src: str) -> str:
    """剥除行内 ``#`` 注释后的源码（「浅拷回流」禁判只看代码，不被注释文本误命中）。"""
    out = []
    for ln in src.split("\n"):
        idx = ln.find("#")
        out.append(ln[:idx] if idx >= 0 else ln)
    return "\n".join(out)


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


def check_schema_stamp() -> None:
    """① _record_action 中央盖章 diff-v1。"""
    src = _read(EM_REL)
    if not src:
        return
    body = _func_src(src, "_record_action")
    if not body:
        _fail("① 找不到 _record_action")
        return
    if 'action.setdefault("schema", "diff-v1")' not in body:
        _fail("① _record_action 缺 schema 中央盖章（diff-v1 承诺失效）")


def check_deepcopy_construction() -> None:
    """② 构造点深拷化：深拷在册 + 浅拷回流封死。"""
    src = _read(EM_REL)
    if not src:
        return
    # split：无 dict(live) 残留，deepcopy 在册，original_clip_id 在册
    body = _func_src(src, "_perform_split_clip")
    if not body:
        _fail("② 找不到 _perform_split_clip")
    else:
        code = _strip_comments(body)
        if "dict(live)" in code:
            _fail("② _perform_split_clip 浅拷 dict(live) 回流（快照与活体共享嵌套值）")
        if "copy.deepcopy(live)" not in code:
            _fail("② _perform_split_clip 缺 copy.deepcopy(live)")
        if '"original_clip_id"' not in code:
            _fail("② _perform_split_clip 的 action 缺 original_clip_id 键（新格式还原锚点）")
    # 复制粘贴
    body = _func_src(src, "_copy_clip_data_to_timeline")
    if not body:
        _fail("② 找不到 _copy_clip_data_to_timeline")
    else:
        code = _strip_comments(body)
        if "dict(clip)" in code or "copy.deepcopy(clip)" not in code:
            _fail("② _copy_clip_data_to_timeline 浅拷回流/缺 deepcopy")
    # 删除快照
    body = _func_src(src, "_delete_one_clip_internal")
    if not body:
        _fail("② 找不到 _delete_one_clip_internal")
    elif "copy.deepcopy(deleted_clip)" not in body:
        _fail("② _delete_one_clip_internal 的 payload 快照缺 deepcopy")
    # 键帧 before/after
    body = _func_src(src, "add_keyframes_to_clip")
    if not body:
        _fail("② 找不到 add_keyframes_to_clip")
    elif "before = list(" in body or "copy.deepcopy" not in body:
        _fail("② add_keyframes_to_clip 的 before/after 浅拷回流")
    # 滤镜 before/after
    body = _func_src(src, "_apply_filter_to_clip")
    if not body:
        _fail("② 找不到 _apply_filter_to_clip")
    elif 'before = {"effects": dict(' in body or "copy.deepcopy" not in body:
        _fail("② _apply_filter_to_clip 的 before/after 浅拷回流")
    # 转场 before/after
    body = _func_src(src, "_apply_transition_to_clip")
    if not body:
        _fail("② 找不到 _apply_transition_to_clip")
    elif '"transitions": list(clip.get("transitions")' in body or "copy.deepcopy" not in body:
        _fail("② _apply_transition_to_clip 的 before/after 浅拷回流")
    # 贴纸整表快照
    body = _func_src(src, "_snapshot_stickers")
    if not body:
        _fail("② 找不到 _snapshot_stickers")
    elif "[dict(s) for s in" in body or "copy.deepcopy" not in body:
        _fail("② _snapshot_stickers 浅拷回流（dict(s) 与活体共享嵌套参数）")


def check_split_dual_format() -> None:
    """③ split 双格式分支并存（新格式 set_fields + 旧格式整段还原）。"""
    src = _read(EM_REL)
    if not src:
        return
    body = _func_src(src, "_apply_action_locked")
    if not body:
        _fail("③ 找不到 _apply_action_locked")
        return
    if 'action.get("original_clip_id")' not in body:
        _fail("③ split 读侧缺新格式分支（original_clip_id → store.set_fields 还原）")
    if "set_fields(" not in body:
        _fail("③ split 新格式分支未走 store.set_fields")
    if 'original["duration"] = action["original_duration"]' not in body:
        _fail("③ split 旧格式分支被清理（edit_commands/粗剪仍产旧格式，撤销会炸）")


def check_membership_by_id() -> None:
    """④ 成员判据 find_by_id：dict 全等比较禁止回流。"""
    src = _read(EM_REL)
    if not src:
        return
    body = _func_src(src, "_apply_action_locked")
    if not body:
        _fail("④ 找不到 _apply_action_locked")
        return
    if "not in self._clips" in body:
        _fail("④ _apply_action_locked 残留 `not in self._clips` 全等比较"
              "（深拷快照下必须 find_by_id 按 id 判成员）")
    if 'self._timeline_store.find_by_id(clip.get("id")) is None' not in body:
        _fail("④ _apply_action_locked 缺 find_by_id 成员判据")


def check_frozen_zones_no_record() -> None:
    """⑤ 冻结符号体内、FROZEN 标记块内零压栈（动态读 frozen_zones.json）。"""
    src = _read(EM_REL)
    zones_src = _read(ZONES_REL)
    if not src or not zones_src:
        return
    try:
        zones = json.loads(zones_src)
    except (ValueError, TypeError) as e:
        _fail(f"⑤ frozen_zones.json 解析失败：{e}")
        return
    for zone in zones.get("zones", []):
        for sym in zone.get("symbols", []):
            if sym.get("file", "").replace("/", os.sep) != EM_REL:
                continue
            body = _func_src(src, sym.get("name", ""))
            if body and "_record_action(" in body:
                _fail(f"⑤ 冻结符号 {zone.get('id')}::{sym.get('name')} 体内出现压栈"
                      "（冻结区新增撤销记录=触碰冻结语义，须先解冻）")
    # FROZEN 标记块（>>> BEGIN / <<< END 之间）同样零压栈
    lines = src.split("\n")
    in_block, start = False, 0
    for i, ln in enumerate(lines, 1):
        if ">>> FROZEN:" in ln:
            in_block, start = True, i
        elif "<<< FROZEN:" in ln:
            in_block = False
        elif in_block and "_record_action(" in ln:
            _fail(f"⑤ FROZEN 标记块（起于 L{start}）内出现压栈：L{i}")


def main() -> int:
    print("=" * 62)
    print("撤销栈 diff-v1 格式守卫（OTIO 迁移·刀6）")
    print("=" * 62)
    for fn in (check_schema_stamp, check_deepcopy_construction,
               check_split_dual_format, check_membership_by_id,
               check_frozen_zones_no_record):
        try:
            fn()
        except Exception as e:  # 守卫自身异常也算失败，不静默
            _fail(f"{fn.__name__} 抛异常: {type(e).__name__}: {e}")

    if _fails:
        print("✗ 失败项：")
        for p in _fails:
            print(f"  - {p}")
        return 1
    print("OK 撤销 diff-v1：schema 盖章 · 构造点深拷 · split 双格式并存 · find_by_id 成员判据 · 冻结区零压栈")
    return 0


if __name__ == "__main__":
    sys.exit(main())
