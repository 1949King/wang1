# -*- coding: utf-8 -*-
"""时间线真相源切换守卫（OTIO 全量迁移·刀1，2026-10-18 用户授权解冻）

背景：``EditorModule._clips`` 的结构写入历史上散落在 28 个调用点（整段重赋值 /
append / clear）。2026-10-18 真相源切换到 ``app/core/timeline_store.py::TimelineStore``
（adopt 同一 list 对象，strangler 渐进收拢）。本守卫把切换不变量锁成可执行断言，
防止「store 在位、无锁必漂」。

断言：
  ① 同一性不变量（运行时）：add/remove_by_id/replace_all/clear 全部原地突变，
     ``store.rows()`` 与宿主 adopt 的列表**永远是同一个对象**（688 读点零破坏的根基）
  ② serialize 往返守恒：serialize→deserialize 内容一致且保持同一性
  ③ to_timeline ≡ 桥接：store.to_timeline() 与 bridge.clips_to_timeline(rows)
     轨道分组/clip 数/关键字段一致（canonical 视图出口不另起炉灶）
  ④ 接线在册（静态）：editor_module 初始化处 adopt store 且复用 _clips_lock；
     glue 策略已登记 store 四个结构写入 API；store 源码无 Qt 顶层导入（子进程红线）
  ⑤ 重绑定收敛（静态）：app/ 下（除 tests 与 timeline_widget 私有副本）
     不允许出现 ``self._clips =`` / ``editor._clips =`` 整段重绑定
     ——唯一豁免：editor_module 初始化行（store adopt 的宿主列表创建点）

用法（项目根执行）：.venv312\\Scripts\\python.exe _verify/check_timeline_store.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _rich_clips():
    return [
        {"id": "v1", "type": "video", "path": "a.mp4", "duration": 5.0,
         "start_time": 0.0, "in_point": 1.0, "out_point": 4.0, "track": 0},
        {"id": "v2", "type": "video", "path": "b.mp4", "duration": 3.0,
         "start_time": 6.0, "in_point": 0.0, "out_point": 3.0, "track": 0,
         "custom_extra": "keep-me"},
        {"id": "a1", "type": "audio", "path": "bgm.mp3", "duration": 10.0,
         "start_time": 0.0, "in_point": 0.0, "out_point": 10.0, "track": 1},
    ]


# ── ① 同一性不变量（运行时） ─────────────────────────────────────────

def check_identity() -> None:
    import threading
    from app.core.timeline_store import TimelineStore

    rows = _rich_clips()
    store = TimelineStore(rows, lock=threading.RLock())
    if store.rows() is not rows:
        _fail("① adopt 未保持列表同一性（store.rows() 不是宿主列表）")
        return
    store.add({"id": "v3", "type": "video", "path": "c.mp4", "track": 0,
               "start_time": 9.0, "in_point": 0.0, "out_point": 2.0})
    if store.rows() is not rows or len(rows) != 4:
        _fail("① add 破坏同一性或内容")
    n = store.remove_by_id("v1")
    if n != 1 or store.rows() is not rows or len(rows) != 3:
        _fail("① remove_by_id 破坏同一性或内容")
    store.replace_all(_rich_clips())
    if store.rows() is not rows or len(rows) != 3:
        _fail("① replace_all 破坏同一性或内容")
    store.clear()
    if store.rows() is not rows or len(rows) != 0:
        _fail("① clear 破坏同一性或内容")
    # 非 dict 行必须被拒绝/过滤（契约防御）
    try:
        store.add("not-a-dict")  # type: ignore[arg-type]
        _fail("① add 未拒绝非 dict")
    except TypeError:
        pass


# ── ② serialize 往返守恒 ─────────────────────────────────────────────

def check_serialize_roundtrip() -> None:
    import threading
    from app.core.timeline_store import TimelineStore

    rows = _rich_clips()
    store = TimelineStore(rows, lock=threading.RLock())
    text = store.serialize()
    rows.append({"id": "junk", "type": "video"})  # 灌回前的扰动
    got = store.deserialize(text)
    if store.rows() is not rows:
        _fail("② deserialize 破坏列表同一性")
    if got != 3:
        _fail(f"② deserialize 条数漂移：{got}")
    ids = [c.get("id") for c in rows]
    if ids != ["v1", "v2", "a1"]:
        _fail(f"② serialize 往返内容漂移：{ids}")
    v2 = next(c for c in rows if c["id"] == "v2")
    if v2.get("custom_extra") != "keep-me":
        _fail("② serialize 往返丢 extras")


# ── ③ to_timeline ≡ 桥接 ─────────────────────────────────────────────

def check_to_timeline_equiv() -> None:
    import threading
    from app.core.interchange.editor_timeline_bridge import clips_to_timeline
    from app.core.timeline_store import TimelineStore

    rows = _rich_clips()
    store = TimelineStore(rows, lock=threading.RLock())
    tl_store = store.to_timeline(fps=30.0)
    tl_bridge = clips_to_timeline(list(rows), fps=30.0)
    if len(tl_store.tracks) != len(tl_bridge.tracks):
        _fail("③ to_timeline 轨道分组与桥接不一致")
    n_s = sum(len(t.clips) for t in tl_store.tracks)
    n_b = sum(len(t.clips) for t in tl_bridge.tracks)
    if n_s != n_b or n_s != 3:
        _fail(f"③ to_timeline clip 数漂移：store={n_s} bridge={n_b}")
    v1 = next((c for t in tl_store.tracks for c in t.clips if c.id == "v1"), None)
    if v1 is None or v1.source != "a.mp4":
        _fail("③ to_timeline 关键字段漂移（path→source）")


# ── ④ 接线在册（静态） ───────────────────────────────────────────────

def check_wiring() -> None:
    em = os.path.join(ROOT, "app", "modules", "lego", "editor_module.py")
    with open(em, "r", encoding="utf-8") as f:
        src = f.read()
    if "TimelineStore(self._clips, lock=self._clips_lock)" not in src:
        _fail("④ editor_module 未在册 adopt store（或换了锁实例——必须复用 _clips_lock）")
    # 刀2（2026-10-18）：撤销区结构写入必须全部收敛 store API，宿主不得残留裸写
    for token in ("self._clips.append(", "self._clips[:]", "self._clips.remove(",
                  "self._clips.insert(", "self._clips.pop(", "self._clips.clear("):
        if token in src:
            _fail(f"④ 刀2收敛漂移：editor_module 残留裸结构写入 {token!r}")
    if "self._timeline_store.snapshot()" not in src:
        _fail("④ 持久化 canonical 出口漂移：_clips_snapshot 未委托 store.snapshot()")
    store_path = os.path.join(ROOT, "app", "core", "timeline_store.py")
    with open(store_path, "r", encoding="utf-8") as f:
        ssrc = f.read()
    if re.search(r"^(import PyQt6|from PyQt6)", ssrc, re.M):
        _fail("④ timeline_store 顶层 import Qt（子进程/桥接层红线）")
    from app.core.glue import policies
    for sym in ("add", "remove_by_id", "replace_all", "clear"):
        if not policies.is_declared_timeline_writer("app/core/timeline_store.py", sym):
            _fail(f"④ glue 策略未登记 store 写入 API：{sym}")


# ── ⑤ 重绑定收敛（静态） ─────────────────────────────────────────────

_REBIND = re.compile(r"(?:self|editor)\._clips\s*=[^=]")
_EXEMPT_LINE = "self._clips = []  # 存储视频片段"
_SKIP_FILES = {os.path.join("app", "modules", "lego", "timeline_widget.py")}


def check_rebind_convergence() -> None:
    app_dir = os.path.join(ROOT, "app")
    for dirpath, dirnames, filenames in os.walk(app_dir):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT)
            if rel in _SKIP_FILES:
                continue  # timeline_widget._clips 是控件私有副本，不在切换范围
            if rel.startswith(os.path.join("app", "tests") + os.sep):
                continue  # 测试替身自管列表
            with open(full, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if not _REBIND.search(line):
                        continue
                    if line.lstrip().startswith("#"):
                        continue  # 注释行（glue 策略文档）不算
                    if _EXEMPT_LINE in line:
                        continue  # 唯一豁免：宿主列表创建点（store adopt 的同一对象）
                    _fail(f"⑤ 整段重绑定绕过 store：{rel}:{i} → {line.strip()}")


def main() -> int:
    check_identity()
    check_serialize_roundtrip()
    check_to_timeline_equiv()
    check_wiring()
    check_rebind_convergence()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  时间线真相源：同一性不变量/serialize往返/to_timeline≡桥接/接线在册/重绑定收敛")
    return 0


if __name__ == "__main__":
    sys.exit(main())
