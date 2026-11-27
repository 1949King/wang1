#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""「代码 × 扩散」混合视频契约门禁（V4.44 · 2026-10-19）

锁死五件事（改 app/core/code_video/ 或三处注册前先跑本脚本）：
  A. 契约域零依赖：import code_video 不拉起 PySide6/PyQt6/PyQt5/WebEngine（渲染刀才允许拖重依赖）
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

_heavy = [m for m in ("PySide6", "PyQt6", "PyQt5", "QtWebEngineWidgets", "webview") if m in sys.modules]
check(not _heavy, f"import 后无重依赖模块{'' if not _heavy else f'：{_heavy}'}")
check(hasattr(cv, "compile_spec") and hasattr(cv, "from_storyboard"),
      "spec 域导出面完整（compile_spec / from_storyboard）")

# ── B. 注册 ↔ 目录 ↔ action 别名 ──
print("[B] pipeline.code_video_plan / code_video_render 三处注册一致")
from app.core import agent_capability_catalog as cat
from app.core.agent_action_registry import (
    ACTION_TO_CAPABILITY,
    get_dangerous_actions,
)

_CAP_ID = "pipeline.code_video_plan"
_CAP_RENDER = "pipeline.code_video_render"
cat_ids = cat.registered_capability_ids()
check(_CAP_ID in cat_ids, "能力目录 CAPABILITY_ROWS 含 code_video_plan")
if _CAP_ID in cat_ids:
    row = next(r for r in cat.CAPABILITY_ROWS if r[0] == _CAP_ID)
    check(row[2] == "read" and row[3] is False,
          f"effect=read / paid=False（计划态只读，收到 {row[2]}/{row[3]}）")

# 2026-10-20：注册已拆分到 capability_handlers_*.py，静态扫描同族模块（不 import dispatcher）
_handler_files = sorted(
    os.path.join(ROOT, "app", "core", f)
    for f in os.listdir(os.path.join(ROOT, "app", "core"))
    if f.startswith("capability_handlers") and f.endswith(".py")
)
_handlers_src = "\n".join(open(p, encoding="utf-8").read() for p in _handler_files)
check(bool(re.search(rf'dispatcher\.register\(\s*"{re.escape(_CAP_ID)}"', _handlers_src)),
      "能力模块有 code_video_plan register 字面量")

check(ACTION_TO_CAPABILITY.get("code_video_plan") == _CAP_ID,
      f"action 别名 code_video_plan → {ACTION_TO_CAPABILITY.get('code_video_plan')}")

from app.core.agent_policy import _CAPABILITY_EFFECTS

check(_CAPABILITY_EFFECTS.get(_CAP_ID) == ("read", False),
      f"policy effect 表同步（{_CAPABILITY_EFFECTS.get(_CAP_ID)}）")

# V4.45 渲染能力：file_write + dangerous（长耗时写盘需确认）
check(_CAP_RENDER in cat_ids, "能力目录 CAPABILITY_ROWS 含 code_video_render")
if _CAP_RENDER in cat_ids:
    row = next(r for r in cat.CAPABILITY_ROWS if r[0] == _CAP_RENDER)
    check(row[2] == "file_write" and row[3] is False,
          f"effect=file_write / paid=False（收到 {row[2]}/{row[3]}）")
check(bool(re.search(rf'dispatcher\.register\(\s*"{re.escape(_CAP_RENDER)}"', _handlers_src)),
      "capability_handlers.py 有 code_video_render register 字面量")
check(ACTION_TO_CAPABILITY.get("code_video_render") == _CAP_RENDER,
      f"action 别名 code_video_render → {ACTION_TO_CAPABILITY.get('code_video_render')}")
check(_CAPABILITY_EFFECTS.get(_CAP_RENDER) == ("file_write", False),
      f"policy effect 表同步（{_CAPABILITY_EFFECTS.get(_CAP_RENDER)}）")
check("code_video_render" in get_dangerous_actions(),
      "action 级别 = dangerous（长耗时写盘，collaborative 需确认）")

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
print("[E] 行数棘轮（code_video 域 + 能力薄壳）")
_TOLERANCE = 10
_BASELINE = {
    "app/core/code_video/spec.py": 680,
    "app/core/code_video/security.py": 260,
    "app/core/code_video/page_builder.py": 369,
    "app/core/code_video/render_worker.py": 263,
    "app/core/code_video/render_host.py": 438,
    "app/core/code_video/audio_graph.py": 107,
    "app/core/code_video/video_critic.py": 145,
    "app/core/capability_handlers_code_video.py": 188,
}
for rel, base in _BASELINE.items():
    n = sum(1 for _ in open(os.path.join(ROOT, rel), encoding="utf-8"))
    check(n <= base + _TOLERANCE,
          f"{rel} {n} 行（基线 {base} + 容差 {_TOLERANCE}）"
          + ("" if n <= base else " ⇒ 拆分或下调基线，别放任增长"))

# ── F. 渲染引擎隔离 / 诚实失败 ──
print("[F] 渲染引擎隔离与诚实失败")
import ast

import app.core.code_video.render_host as _host  # noqa: F401

_heavy2 = [m for m in ("PySide6", "PyQt6", "PyQt5", "playwright", "torch", "diffusers") if m in sys.modules]
check(not _heavy2, f"import render_host 后无重依赖{'' if not _heavy2 else f'：{_heavy2}'}")


def _top_level_imports(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


for rel in ("app/core/code_video/render_host.py", "app/core/code_video/render_worker.py"):
    imports = _top_level_imports(rel)
    check(not ({"PySide6", "PyQt6", "PyQt5", "playwright"} & imports),
          f"{rel} 顶层不 import Qt/playwright（实际 {sorted(imports)[:6]}）")

_host_src = open(os.path.join(ROOT, "app/core/code_video/render_host.py"), encoding="utf-8").read()
_worker_src = open(os.path.join(ROOT, "app/core/code_video/render_worker.py"), encoding="utf-8").read()
check("_fail(" in _host_src and '"stage"' in _host_src,
      "render_host 失败带 stage（诚实失败，不交半成品）")
check("worker_error.json" in _worker_src,
      "render_worker 失败写 worker_error.json（失败可定位）")
check(not re.search(r"\b(?:eval|exec)\s*\(", _host_src),
      "render_host 不 eval/exec 任何模板（主进程零 RCE 面）")

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项")
    sys.exit(1)
print("OK 「代码 × 扩散」契约门禁全绿")
