#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""「代码 × 扩散」混合视频契约门禁（V4.44 · 2026-10-19）

锁死五件事（改 app/core/code_video/ 或三处注册前先跑本脚本）：
  A. 契约域零依赖：import code_video 不拉起 PyQt6/WebEngine（渲染刀才允许拖重依赖）
  B. 注册 ↔ 目录 ↔ action 别名三处一致（pipeline.code_video_plan）
  C. lineage 六键白名单与 glue GENERATION_KEYS 同源（入轨血缘单一事实来源）
  D. 契约行为冒烟：正常分镜编译过 + 文字层铁律反例被拒
  E. 行数棘轮（只减不增）：契约三文件基线 + 容差

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_code_video.py
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_failures: list = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


# ── A. 契约域零依赖 ──
print("[A] 契约域可独立导入（不拉 Qt/WebEngine 重依赖）")
import app.core.code_video as cv

_heavy = [m for m in ("PyQt6", "PyQt5", "QtWebEngineWidgets", "webview") if m in sys.modules]
check(not _heavy, f"import 后无重依赖模块{'' if not _heavy else f'：{_heavy}'}")
check(hasattr(cv, "compile_spec") and hasattr(cv, "from_storyboard"),
      "spec 域导出面完整（compile_spec / from_storyboard）")

# ── B. 注册 ↔ 目录 ↔ action 别名 ──
print("[B] pipeline.code_video_plan 三处注册一致")
from app.core import agent_capability_catalog as cat
from app.core.agent_action_registry import ACTION_TO_CAPABILITY

_CAP_ID = "pipeline.code_video_plan"
cat_ids = cat.registered_capability_ids()
check(_CAP_ID in cat_ids, "能力目录 CAPABILITY_ROWS 含该能力")
if _CAP_ID in cat_ids:
    row = next(r for r in cat.CAPABILITY_ROWS if r[0] == _CAP_ID)
    check(row[2] == "read" and row[3] is False,
          f"effect=read / paid=False（计划态只读，收到 {row[2]}/{row[3]}）")

with open(os.path.join(ROOT, "app", "core", "capability_handlers.py"), encoding="utf-8") as f:
    _handlers_src = f.read()
check(bool(re.search(rf'dispatcher\.register\(\s*"{re.escape(_CAP_ID)}"', _handlers_src)),
      "capability_handlers.py 有 register 字面量")

check(ACTION_TO_CAPABILITY.get("code_video_plan") == _CAP_ID,
      f"action 别名 code_video_plan → {ACTION_TO_CAPABILITY.get('code_video_plan')}")

from app.core.agent_policy import _CAPABILITY_EFFECTS

check(_CAPABILITY_EFFECTS.get(_CAP_ID) == ("read", False),
      f"policy effect 表同步（{_CAPABILITY_EFFECTS.get(_CAP_ID)}）")

# ── C. lineage 六键同源 ──
print("[C] lineage 六键白名单与 glue GENERATION_KEYS 同源")
from app.core.glue.schema import GENERATION_KEYS, normalize_generation

check(GENERATION_KEYS == ("prompt", "seed", "model", "channel", "character_id", "reference"),
      f"GENERATION_KEYS 六键未漂移：{GENERATION_KEYS}")
_spec_src = open(os.path.join(ROOT, "app", "core", "code_video", "spec.py"), encoding="utf-8").read()
check("normalize_generation" in _spec_src,
      "spec.py 经 normalize_generation 清洗 assets.lineage（同源，不自造白名单）")
_cleaned = normalize_generation({"prompt": "p", "seed": "42", "evil": "x", "model": None})
check(set(_cleaned) == {"prompt", "seed"} and _cleaned["seed"] == 42,
      f"normalize_generation 冒烟：{_cleaned}")

# ── D. 契约行为冒烟 ──
print("[D] 契约行为冒烟")
spec, errs = cv.from_storyboard([
    {"shot": 1, "description": "雨夜街头", "duration": 6.0},
    {"shot": 2, "description": "特写", "duration": 4.5},
], spec_id="verify")
check(errs == [] and spec is not None, "from_storyboard 正常案例无 errors")
compiled, cerrs = cv.compile_spec(spec)
check(compiled is not None and not cerrs, f"compile_spec 通过（clip 数 {len(compiled['tracks'])}）")

spec2, _ = cv.from_storyboard([{"shot": 1, "description": "x", "duration": 2.0}])
# 文字层铁律反例：把镜头 clip 的 kind 改成 text，却仍指向 asset://
spec2.tracks[0].clips[1].kind = "text"
compiled2, cerrs2 = cv.compile_spec(spec2)
check(compiled2 is None and any("文字层铁律" in e for e in cerrs2),
      "文字层铁律反例被拒（text+asset:// ⇒ 编译失败）")

# ── E. 行数棘轮（只减不增）──
print("[E] 行数棘轮（契约三文件）")
_TOLERANCE = 10
_BASELINE = {
    "app/core/code_video/spec.py": 678,
    "app/core/capability_handlers_code_video.py": 96,
    "app/tests/test_code_video_spec.py": 290,
}
for rel, base in _BASELINE.items():
    n = sum(1 for _ in open(os.path.join(ROOT, rel), encoding="utf-8"))
    check(n <= base + _TOLERANCE,
          f"{rel} {n} 行（基线 {base} + 容差 {_TOLERANCE}）"
          + ("" if n <= base else " ⇒ 拆分或下调基线，别放任增长"))

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项")
    sys.exit(1)
print("OK 「代码 × 扩散」契约门禁全绿")
