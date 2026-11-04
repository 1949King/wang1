# -*- coding: utf-8 -*-
"""守卫：clip ↔ 画布生成参数血缘（智能时间线 P1，2026-10-17）。

验证三件事：
  ① 纯函数行为：normalize_generation 白名单清洗、extra 抽取、stamp 整块替换、
     lineage 双向索引、JSON dump/restore 往返保字段（旧工程无字段不报错）。
  ② 静态多处同步：``"generation"`` 必须同步出现在契约层 / 传输链 / 双库前端
     （仿 check_character_schema 的「多处同步」风格，删一处即红）。
  ③ 反例自检：故意违规必须被抓（守卫自身不许是哑弹）。

【sys.path 绕过】同 check_glue_contract：项目不变量 #10，
把 ``app/core`` 直接入 path，以顶层模块导入，完全不触碰 ``app`` 包。
"""
from __future__ import annotations

import io
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CORE = os.path.join(ROOT, "app", "core")
if CORE not in sys.path:
    sys.path.insert(0, CORE)

import editor_canvas_link as ecl  # noqa: E402
from glue.schema import LINK_KEYS as GLUE_LINK_KEYS  # noqa: E402
from glue.schema import normalize_generation  # noqa: E402

PASS = []
FAIL = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("  %s %-58s %s" % ("✅" if ok else "❌", name, detail))


# ---------------------------------------------------------------------------
# ① 纯函数行为
# ---------------------------------------------------------------------------
print("=" * 74)
print("① 行为：generation 抽取 / 盖章 / 索引 / 往返")
print("=" * 74)

# ①-1 白名单清洗：非白名单键丢弃、seed 转 int、空值不写
g = normalize_generation({"prompt": "p", "seed": "42", "model": "m",
                          "bogus": 1, "extra": {"a": 1}, "channel": ""})
check("normalize_generation：白名单+seed转int+空值丢",
      g == {"prompt": "p", "seed": 42, "model": "m"}, str(g))
check("normalize_generation：非 Mapping ⇒ {}",
      normalize_generation("not-a-dict") == {} and normalize_generation(None) == {})
check("normalize_generation：seed 不可转换即丢弃",
      normalize_generation({"seed": "abc", "prompt": "p"}) == {"prompt": "p"})

# ①-2 extra_from_material_payload：携带才输出、空块不输出
e1 = ecl.extra_from_material_payload({"node_id": "n1", "kind": "video",
                                      "generation": {"prompt": "p", "seed": 7}})
check("extra：generation 随载荷抽取（别名 node_id/kind 兼容）",
      e1 == {"canvas_node_id": "n1", "canvas_kind": "video",
             "generation": {"prompt": "p", "seed": 7}}, str(e1))
e2 = ecl.extra_from_material_payload({"node_id": "n2", "generation": {}})
check("extra：空块 ⇒ 不输出 generation 键", "generation" not in e2, str(e2))
e3 = ecl.extra_from_material_payload({"node_id": "n3"})
check("extra：缺键 ⇒ 不输出（绝不猜默认值）", "generation" not in e3, str(e3))

# ①-3 stamp_clip：非空整块替换、空/缺不覆盖
clip = {"id": "c1", "generation": {"prompt": "旧", "seed": 1}}
ecl.stamp_clip(clip, {"generation": {"prompt": "新", "model": "m"}})
check("stamp：generation 整块替换（旧 seed 不残留）",
      clip["generation"] == {"prompt": "新", "model": "m"}, str(clip["generation"]))
ecl.stamp_clip(clip, {})
check("stamp：空 extra ⇒ 不动已有血缘", clip["generation"] == {"prompt": "新", "model": "m"})
clip2 = {"id": "c2", "generation": {"prompt": "保"}}
ecl.stamp_clip(clip2, {"canvas_node_id": "n9"})
check("stamp：载荷缺 generation ⇒ 保留已有",
      clip2["generation"] == {"prompt": "保"} and clip2["canvas_node_id"] == "n9")

# ①-4 lineage_from_clip：无关联 None；单侧关联出记录；脏数值丢弃
check("lineage：无 node 无 generation ⇒ None（不造空记录）",
      ecl.lineage_from_clip({"id": "x", "path": "D:/v.mp4"}) is None)
rec = ecl.lineage_from_clip({"id": "c3", "canvas_node_id": "n3", "canvas_kind": "video",
                             "path": "D:/v.mp4", "duration": 5, "in_point": "abc",
                             "generation": {"prompt": "p"}})
check("lineage：记录字段齐 + 脏数值丢弃不抛",
      rec is not None and rec["clip_id"] == "c3" and rec["duration"] == 5.0
      and "in_point" not in rec and rec["generation"] == {"prompt": "p"}, str(rec))
rec_gen_only = ecl.lineage_from_clip({"id": "c4", "generation": {"seed": 9}})
check("lineage：仅 generation 也算关联", rec_gen_only is not None
      and rec_gen_only["canvas_node_id"] == "")

# ①-5 lineage_index 双向：同节点多次入轨 ⇒ node 方向列表
idx = ecl.lineage_index([
    {"id": "a", "canvas_node_id": "n1", "generation": {"prompt": "p1"}},
    {"id": "b", "canvas_node_id": "n1"},
    {"id": "c", "path": "D:/plain.mp4"},
])
check("lineage_index：by_clip_id 命中 / 无关联不入索引",
      set(idx["by_clip_id"]) == {"a", "b"})
check("lineage_index：by_node_id 同节点聚合为列表",
      [r["clip_id"] for r in idx["by_node_id"].get("n1", [])] == ["a", "b"])

# ①-6 JSON 往返（工程保存 export_project 全量 dump 语义）+ 旧工程兼容
dumped = json.dumps({"id": "z", "canvas_node_id": "n7",
                     "generation": {"prompt": "雨夜", "seed": 42}}, ensure_ascii=False)
restored = json.loads(dumped)
check("JSON dump/restore 往返保 generation 字段",
      restored["generation"] == {"prompt": "雨夜", "seed": 42})
legacy = {"id": "old", "path": "D:/v.mp4"}  # 旧工程：无该字段
check("旧工程兼容：读取一律 .get 不 KeyError",
      ecl.lineage_from_clip(legacy) is None
      and (legacy.get("generation") or {}) == {})

# ①-7 LINK_KEYS 单一来源仍等价（glue 守卫之外的双保险）
check("LINK_KEYS 双侧同值且含 generation",
      tuple(ecl.LINK_KEYS) == tuple(GLUE_LINK_KEYS)
      and "generation" in ecl.LINK_KEYS, str(ecl.LINK_KEYS))

# ---------------------------------------------------------------------------
# ② 静态多处同步
# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("② 静态：generation 同步出现于契约/传输链/双库前端（删一处即红）")
print("=" * 74)


def _read(rel: str) -> str:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.exists(p):
        return ""
    return io.open(p, encoding="utf-8", errors="replace").read()


SYNC_FILES = [
    "app/core/editor_canvas_link.py",
    "app/core/glue/schema.py",
    "app/core/glue/convert.py",
    "app/core/canvas_bridge.py",
    "app/core/canvas_server.py",
    "app/core/canvas_routes_post.py",
    # P0-1 Phase 2（2026-10-18）：tauri 侧 libtv 副本已删除，画布前端只扫真源包。
    "vendor/packages/canvas-core/src/bridge.ts",
    "vendor/packages/canvas-core/src/editorIngress.ts",
]
missing = [rel for rel in SYNC_FILES if "generation" not in _read(rel)]
check('"generation" 同步出现于 %d 处' % len(SYNC_FILES), not missing, str(missing))

# 传输契约两端：query 键名必须逐字一致（改一端忘另一端即红）
missing2 = [rel for rel in
            ["vendor/packages/canvas-core/src/bridge.ts",
             "app/core/canvas_server.py"]
            if "generation_json" not in _read(rel)]
check("传输键 generation_json 两端一致", not missing2, str(missing2))

# 入轨身份唯一构造点：nodeLink 双库定义 + 双库 App.tsx 使用
missing3 = [rel for rel in
            ["vendor/packages/canvas-core/src/editorIngress.ts"]
            if "export function nodeLink" not in _read(rel)]
missing3 += [rel for rel in
             ["vendor/packages/canvas-core/src/App.tsx"]
             if "nodeLink(" not in _read(rel)]
check("nodeLink 唯一构造点双库齐备", not missing3, str(missing3))

# 只读端点已注册（不进能力目录，但路由必须在）
check("GET /host/clip-lineage 已注册",
      "/host/clip-lineage" in _read("app/core/canvas_routes_get.py"))

# ---------------------------------------------------------------------------
# ③ 反例自检（守卫不许是哑弹）
# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("③ 反例自检")
print("=" * 74)
check("反例：故意缺 token 的文本被静态扫描判为缺失",
      "generation" not in "def f():\n    return {'canvas_node_id': 'n1'}\n")
check("反例：载荷塞非白名单键被清洗丢弃",
      "evil" not in normalize_generation({"evil": "x"}))
bad_clip = {"id": "b"}
ecl.stamp_clip(bad_clip, {"generation": {}})
check("反例：空块盖章不产生 generation 键", "generation" not in bad_clip)

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("LINEAGE 汇总：通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    for f in FAIL:
        print("   ❌ %s" % f)
print("=" * 74)
sys.exit(1 if FAIL else 0)
