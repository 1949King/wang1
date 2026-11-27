# -*- coding: utf-8 -*-
"""导出/渲染消费出口真相源守卫（OTIO 真相源迁移·刀7，EXPORTSRC）

背景：导出面（editor_export.py / editor_export_panel.py）历史上直读
``EditorModule._clips``（裸属性读 / ``getattr(x, "_clips")`` 兜底）。刀7 把全部
消费出口切换为 ``store.snapshot()``——锁内浅拷 list、元素仍是 live dict 引用，
与旧直读字段级等价；``build_edited_video`` 内「代理→原片」``clip["path"] = alt``
原地回写为既有行为，保持不变（故 snapshot 元素**不做** deepcopy）。

本守卫零 Qt、纯 AST 扫描两文件（仿 check_timeline_write_surface.py 形态）：

  ① ``_clips`` 属性读计数**硬零**：``x._clips``（Load）与 ``getattr(x, "_clips")``
     字面形态全计（硬零非棘轮，回流即 FAIL）；
  ② Protocol ``_EditorExportHost`` 体内无 ``_clips`` 声明、含 ``_timeline_store`` 声明；
  ③ 两文件 ``snapshot()`` 调用点合计 ≥ 9（消费出口接线在册，防「改回直读」漂移）；
  ④ editor_export.py 顶层无 PySide6/PyQt6/PyQt5 import（Qt 红线：核心层可被子进程复用）。

用法（项目根执行）：
  .venv312\\Scripts\\python.exe _verify/check_export_store_consumption.py
退出码 0 = 达标；1 = 回流/接线漂移。
"""
from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 本刀收口的两个消费面文件（相对项目根）
TARGETS = [
    os.path.join("app", "modules", "lego", "editor_export.py"),
    os.path.join("app", "modules", "lego", "editor_export_panel.py"),
]
#: snapshot() 接线在册最低计数（刀7 落地为 11 处，留 ≥9 容差）
MIN_SNAPSHOT_CALLS = 9

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _load(rel: str):
    """读取并解析目标文件（SyntaxError 由调用方兜底报 FAIL）。"""
    path = os.path.join(ROOT, rel)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    return src, ast.parse(src, filename=rel)


def count_clips_reads(tree: ast.AST) -> int:
    """① ``_clips`` 属性读计数：ast.Attribute(Load) + getattr 字符串字面量形态。"""
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_clips" \
                and isinstance(node.ctx, ast.Load):
            n += 1
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "getattr" and len(node.args) >= 2 \
                and isinstance(node.args[1], ast.Constant) \
                and node.args[1].value == "_clips":
            n += 1
    return n


def check_protocol(tree: ast.AST) -> None:
    """② Protocol ``_EditorExportHost``：无 ``_clips`` 声明、``_timeline_store`` 在册。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "_EditorExportHost":
            declared = set()
            for st in node.body:
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    declared.add(st.target.id)
                elif isinstance(st, ast.Assign):
                    for t in st.targets:
                        if isinstance(t, ast.Name):
                            declared.add(t.id)
            if "_clips" in declared:
                _fail("② _EditorExportHost 仍声明 _clips（Protocol 应切换为 _timeline_store）")
            if "_timeline_store" not in declared:
                _fail("② _EditorExportHost 缺 _timeline_store 声明（消费出口接线漂移）")
            return
    _fail("② 未找到 Protocol _EditorExportHost（结构漂移）")


def count_snapshot_calls(tree: ast.AST) -> int:
    """③ ``<expr>.snapshot()`` 调用计数。"""
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "snapshot":
            n += 1
    return n


def check_no_qt_top_level(tree: ast.AST, rel: str) -> None:
    """④ 顶层（模块级）无 Qt 绑定 import；函数内延迟导入不计。"""
    qt_bindings = ("PySide6", "PyQt6", "PyQt5")
    for st in tree.body:
        if isinstance(st, ast.Import):
            for a in st.names:
                if a.name.split(".")[0] in qt_bindings:
                    _fail(f"④ {rel} 顶层 import Qt 绑定（Qt 红线）")
        elif isinstance(st, ast.ImportFrom):
            mod = (st.module or "").split(".")[0]
            if st.level == 0 and mod in qt_bindings:
                _fail(f"④ {rel} 顶层 from Qt 绑定导入（Qt 红线）")


def main() -> int:
    total_snap = 0
    for rel in TARGETS:
        try:
            _src, tree = _load(rel)
        except (OSError, SyntaxError) as e:
            _fail(f"⓪ {rel} 读取/解析失败：{e}")
            continue
        n = count_clips_reads(tree)
        if n:
            _fail(f"① {rel} 残留 {n} 处 _clips 属性读（导出消费必须走 _timeline_store.snapshot()）")
        total_snap += count_snapshot_calls(tree)
        if rel.endswith("editor_export.py"):
            check_protocol(tree)
            check_no_qt_top_level(tree, rel)
    if total_snap < MIN_SNAPSHOT_CALLS:
        _fail(f"③ snapshot() 消费点仅 {total_snap} 处（< {MIN_SNAPSHOT_CALLS}，接线漂移）")
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print(f"PASS  导出消费出口全部走 store.snapshot()："
          f"_clips 属性读=0、Protocol 已切 _timeline_store、snapshot()={total_snap} 处、无 Qt 红线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
