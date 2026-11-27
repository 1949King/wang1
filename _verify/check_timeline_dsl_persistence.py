# -*- coding: utf-8 -*-
"""持久化 DSL canonical 守卫（OTIO 全量迁移·刀5，2026-10-18）

背景：工程文件（.timeline）真相源写入点唯一在 ``editor_module.export_project``，
读取点唯一在 ``import_project``。刀5 把「裸 clips dict 列表」切换为
``timeline-dsl`` canonical 文档：**双读单写** —— 新码只写 DSL 文档，旧格式仍可读。
桥接类型化视图实测有损（effects dict→list 丢值 / transform 子键丢 / track 跳号
归一 / 合成原不存在的键），故 DSL 文档为每个 clip 附 ``metadata["editor"]`` 整行
备份 + ``editor_index`` 原序，回灌走备份即无损。

断言：
  ① 无损往返（运行时）：代表性行（effects dict / transform 子键 / transitions /
     track 跳号 / unicode / 缺可选键 / 乱序）→ to_dsl_document → JSON 落盘往返 →
     rows_from_dsl_document，与原始行**深相等且顺序守恒**（diff=0）
  ② DSL 合法性：validate_timeline 无错；Timeline.from_json 可解析；
     轨道分组 clip 数与原始 track 分组一致
  ③ 畸形文档：非 dict / 缺 tracks → ValueError（调用方给用户提示，不静默）
  ④ 回退路径（运行时）：剥掉 editor 备份的文档（外部手写 DSL）→ 桥接回灌可用，
     条数守恒
  ⑤ 接线在册（静态）：export_project 停写裸 clips、写 format=timeline-dsl；
     import_project 双读分支在册（新格式 rows_from_dsl_document / 旧 clips fallback）

用法（项目根执行）：.venv312\\Scripts\\python.exe _verify/check_timeline_dsl_persistence.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import json
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _representative_rows():
    """覆盖桥接全部已知有损面的代表性行（值均 JSON-native，落盘往返类型不变）。"""
    return [
        # track 跳号（0→2）+ 乱序（后加的行 start_time 更小）+ effects dict 列表
        {"id": "v2", "type": "video", "path": "素材/第二段.mp4", "track": 2,
         "start_time": 1.0, "in_point": 0.0, "out_point": 3.0, "duration": 3.0,
         "effects": [{"kind": "lut", "strength": 0.8}, {"kind": "denoise"}],
         "transform": {"x": 12.5, "y": -30.0, "scale": 1.25, "rotation": 7.5,
                       "opacity": 0.9, "anchor_x": 0.3, "anchor_y": 0.7,
                       "shadow_enabled": True, "blur": 12},
         "transition": {"type": "dissolve", "duration": 0.5, "plugin_id": "dissolve",
                        "position": "end", "curve": "线性"},
         "volume": 0.8},
        # 缺可选键（无 duration/volume/transform）+ 自定义 extras
        {"id": "v1", "type": "video", "path": "a.mp4", "track": 0,
         "start_time": 5.0, "in_point": 2.0, "out_point": 8.0,
         "custom_extra": "keep-me", "notes": "备注：unicode ✓ 符号"},
        # 音频轨 + transitions 历史列表（复数键）
        {"id": "a1", "type": "audio", "path": "bgm.mp3", "track": 1,
         "start_time": 0.0, "in_point": 0.0, "out_point": 10.0, "duration": 10.0,
         "transitions": [{"type": "fade", "duration": 0.3}],
         "muted": False, "locked": True, "visible": True},
    ]


# ── ① 无损往返 ───────────────────────────────────────────────────────

def check_lossless_roundtrip() -> None:
    from app.core.timeline_store import TimelineStore, rows_from_dsl_document

    rows = _representative_rows()
    store = TimelineStore(list(rows), lock=threading.RLock())
    doc = store.to_dsl_document(width=1080, height=1920)
    # 模拟落盘：JSON 序列化/反序列化（工程文件真实路径）
    doc = json.loads(json.dumps(doc, ensure_ascii=False))
    got = rows_from_dsl_document(doc)
    if len(got) != len(rows):
        _fail(f"① 往返条数漂移：{len(got)} != {len(rows)}")
        return
    # 顺序守恒（editor_index 回原序，而非桥接的 start_time 排序）
    ids = [c.get("id") for c in got]
    if ids != ["v2", "v1", "a1"]:
        _fail(f"① 往返顺序漂移：{ids}")
    # 深相等：逐字段 diff=0
    for orig, back in zip(rows, got):
        if orig != back:
            diff_keys = sorted(set(orig) | set(back))
            bad = [k for k in diff_keys if orig.get(k) != back.get(k)
                   or (k in orig) != (k in back)]
            _fail(f"① 往返字段漂移 id={orig.get('id')}：{bad}")


# ── ② DSL 合法性 ─────────────────────────────────────────────────────

def check_dsl_valid() -> None:
    from app.core.timeline_dsl import Timeline, validate_timeline
    from app.core.timeline_store import TimelineStore

    rows = _representative_rows()
    store = TimelineStore(list(rows), lock=threading.RLock())
    doc = store.to_dsl_document(width=1080, height=1920)
    errors = validate_timeline(doc)
    if errors:
        _fail(f"② validate_timeline 报错：{errors}")
    try:
        tl = Timeline.from_json(json.loads(json.dumps(doc, ensure_ascii=False)))
    except Exception as exc:
        _fail(f"② Timeline.from_json 解析失败：{exc}")
        return
    # 轨道分组：track 0/1/2 三个非空组 → 3 条轨；clip 总数守恒
    if len(tl.tracks) != 3:
        _fail(f"② 轨道分组漂移：{len(tl.tracks)} != 3")
    n = sum(len(t.clips) for t in tl.tracks)
    if n != 3:
        _fail(f"② 类型化视图 clip 数漂移：{n}")
    # 类型化字段可供外部消费（source/range 正确映射）
    v1 = tl.get_clip("v1")
    if v1 is None or v1.source != "a.mp4" or abs(v1.range.start - 5.0) > 1e-9:
        _fail("② 类型化视图关键字段漂移（source/range）")


# ── ③ 畸形文档 ───────────────────────────────────────────────────────

def check_malformed() -> None:
    from app.core.timeline_store import rows_from_dsl_document

    for bad in (None, [], "text", {}, {"tracks": "not-a-list"}):
        try:
            rows_from_dsl_document(bad)  # type: ignore[arg-type]
            _fail(f"③ 畸形文档未抛 ValueError：{bad!r}")
        except ValueError:
            pass
        except Exception as exc:
            _fail(f"③ 畸形文档异常类型错误：{bad!r} → {type(exc).__name__}")


# ── ④ 回退路径（外部手写 DSL，无 editor 备份） ───────────────────────

def check_fallback() -> None:
    from app.core.timeline_store import TimelineStore, rows_from_dsl_document

    rows = _representative_rows()
    store = TimelineStore(list(rows), lock=threading.RLock())
    doc = store.to_dsl_document()
    for track in doc.get("tracks", []):
        for clip in track.get("clips", []):
            meta = clip.get("metadata") or {}
            meta.pop("editor", None)
            meta.pop("editor_index", None)
    try:
        got = rows_from_dsl_document(doc)
    except Exception as exc:
        _fail(f"④ 回退路径异常：{type(exc).__name__}: {exc}")
        return
    if len(got) != 3:
        _fail(f"④ 回退路径条数漂移：{len(got)}")
    if {c.get("id") for c in got} != {"v1", "v2", "a1"}:
        _fail("④ 回退路径 id 不守恒")


# ── ⑤ 接线在册（静态） ───────────────────────────────────────────────

def check_wiring() -> None:
    em = os.path.join(ROOT, "app", "modules", "lego", "editor_module.py")
    with open(em, "r", encoding="utf-8") as f:
        src = f.read()
    # 单写：export_project 停写裸 clips 列表
    if '"clips": self._clips_snapshot()' in src:
        _fail("⑤ 单写漂移：export_project 仍在写裸 clips 列表")
    if '"format": TIMELINE_DSL_FORMAT' not in src:
        _fail("⑤ export_project 未写 format=timeline-dsl 标记")
    if "self._timeline_store.to_dsl_document(" not in src:
        _fail("⑤ export_project 未走 store.to_dsl_document canonical 出口")
    # 双读：import_project 新格式回灌 + 旧格式 fallback 在册
    if "rows_from_dsl_document(project_data.get(\"timeline\")" not in src:
        _fail("⑤ import_project 缺 timeline-dsl 新格式读取分支")
    if 'project_data.get("clips", [])' not in src:
        _fail("⑤ import_project 旧格式 fallback 被误删（双读漂移）")
    # store 红线：无 Qt 顶层导入（与 STORE 守卫同口径，此处覆盖刀5 新增导入）
    store_path = os.path.join(ROOT, "app", "core", "timeline_store.py")
    with open(store_path, "r", encoding="utf-8") as f:
        ssrc = f.read()
    import re
    if re.search(r"^(import (?:PySide6|PyQt6|PyQt5)|from (?:PySide6|PyQt6|PyQt5))", ssrc, re.M):
        _fail("⑤ timeline_store 顶层 import Qt（子进程/桥接层红线）")


def main() -> int:
    check_lossless_roundtrip()
    check_dsl_valid()
    check_malformed()
    check_fallback()
    check_wiring()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  持久化DSL：无损往返/DSL合法/畸形拒绝/桥接回退/双读单写在册")
    return 0


if __name__ == "__main__":
    sys.exit(main())
