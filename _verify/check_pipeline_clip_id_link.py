#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 pipeline 全链路 clip_id 不断链（2026-10-14 demo 打磨）—— 自包含。

背景
----
60 秒 demo 链路：生成线 clip_id(uuid) → preview registry 保留 →
MATERIAL_TO_TIMELINE → _add_clip_to_timeline（内核另生成 clip_{ts} 新 id）→
editing_script.clip_order 引用生成线 id → _execute_pipeline_editing 按 id 查表。

断裂点：_clips 里只有时间线新 id，clip_order 全查不中 ⇒ paths_and_durations 为空 ⇒
成片静默失败（orchestrator 报「未产出成片」）。本脚本锁三件事：

  A. _add_clip_to_timeline 签名带 source_clip_id 可选参数（旧调用方不受影响）
  B. _on_material_dropped 批量分支透传 clip_id（alias 链入口）
  C. _execute_pipeline_editing 的 clip_map 含 source_clip_id 别名索引（alias 链出口）
  D. Provider 下拉含 kling 选项（UI 与 list_providers 对齐）
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def main() -> int:
    editor = _read(os.path.join("app", "modules", "lego", "editor_module.py"))
    panel = _read(os.path.join("app", "modules", "lego",
                               "editor_agent_panel_mixin.py"))
    dock = _read(os.path.join("app", "modules", "lego",
                              "editor_agent_dock_mixin.py"))

    # ── A. 入口签名带 source_clip_id ──
    m = re.search(r"def _add_clip_to_timeline\(self[^)]*\)", editor)
    check("A1 _add_clip_to_timeline 签名存在", m is not None)
    check("A2 source_clip_id 为带默认值的可选参数（旧调用方零影响）",
          bool(m) and "source_clip_id" in m.group(0)
          and re.search(r"source_clip_id\s*:\s*str\s*=\s*[\"']{2}", m.group(0)) is not None)
    check("A3 别名写入片段 source_clip_id 字段",
          'clip["source_clip_id"] = str(source_clip_id)' in editor)

    # ── B. 批量分支透传 clip_id ──
    dropped = re.search(
        r"clips = data\.get\(\"clips\"\).*?_add_clip_to_timeline\(p\)",
        editor, re.DOTALL)
    check("B1 _on_material_dropped 批量分支不再裸传 path（已透传别名）",
          dropped is None)
    check("B2 批量分支从载荷取 clip_id/id 作为别名",
          re.search(r"src_cid = .*clip_id.*or.*c\.get\(\"id\"\)", editor) is not None)
    check("B3 批量分支调用带别名参数",
          re.search(r"_add_clip_to_timeline\(p,\s*src_cid\)", editor) is not None)

    # ── C. 精剪查表带别名索引 ──
    check("C1 clip_map 仍按时间线 id 建索引（旧行为保留）",
          'clip_map = {c.get("id"): c for c in getattr(self, "_clips", []) if c.get("id")}'
          in panel)
    check("C2 clip_map 补 source_clip_id 别名索引",
          re.search(r'alias = c\.get\("source_clip_id"\)', panel) is not None)
    check("C3 别名不覆盖已有时间线 id（id 优先）",
          re.search(r'if alias and alias not in clip_map', panel) is not None)

    # ── D. Provider 下拉含 kling ──
    check("D1 Provider 下拉含可灵 Kling 选项",
          'addItem("可灵 Kling", "kling")' in dock)
    combo_block = re.search(
        r"self\._agent_provider_combo = QComboBox\(\).*?setCurrentIndex\((\d+)\)",
        dock, re.DOTALL)
    check("D2 Auto 是下拉首项且默认选中（行为不变）",
          bool(combo_block)
          and 'addItem("Auto（自动）", "auto")' in combo_block.group(0)
          and combo_block.group(1) == "0")

    # ── E. 端到端 alias 映射行为（纯 dict 模拟，不拉 Qt）──
    _clips = [{"id": "clip_1728000000", "path": "/tmp/a.mp4",
               "source_clip_id": "gen_abc123"},
              {"id": "clip_1728000001", "path": "/tmp/b.mp4"}]  # 旧路径无别名
    clip_map = {c.get("id"): c for c in _clips if c.get("id")}
    for c in _clips:
        alias = c.get("source_clip_id")
        if alias and alias not in clip_map:
            clip_map[alias] = c
    clip_order = ["gen_abc123"]
    resolved = [clip_map.get(cid) for cid in clip_order]
    check("E1 生成线 clip_id 可经别名解析到时间线片段",
          resolved and resolved[0] is not None and resolved[0]["path"] == "/tmp/a.mp4")
    check("E2 时间线自身 id 仍可直接解析",
          clip_map.get("clip_1728000001")["path"] == "/tmp/b.mp4")

    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} / {TOTAL}")
        for x in FAILS:
            print(f"  - {x}")
        return 1
    print(f"ALL PASS ({TOTAL} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
