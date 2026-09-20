# -*- coding: utf-8 -*-
"""回归：本地美学预设包（V4.21.0 参考功能 1）。

自包含执行（不依赖 pytest）。覆盖：
  A. PresetManager 默认数据：5 类预设 + 4 个默认美学包
  B. 美学包解析 apply_pack 只认 PACK_STEP_KINDS
  C. 落盘 roundtrip：用户自定义预设/包 save → 新实例 load 后仍在
  D. import_preset / export_preset / import_pack / export_pack 真读写 JSON
  E. editor_module.apply_aesthetic_pack 存在且 AST 追踪：写真相源 _clips + 可撤销
"""
from __future__ import annotations

import ast
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.preset_manager import PresetManager, PACK_STEP_KINDS  # noqa: E402

_failures = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


print("[A] 默认数据")
pm = PresetManager()
check(set(pm.presets.keys()) == {"effect", "transition", "export", "audio", "subtitle"},
      "5 类预设齐全")
check(len(pm.list_packs()) >= 4, f"默认美学包 ≥4（实际 {len(pm.list_packs())}）")
for pid in ("aesthetic_pack_cinema", "aesthetic_pack_retro",
            "aesthetic_pack_fresh", "aesthetic_pack_bw"):
    check(pm.get_pack(pid) is not None, f"默认包 {pid} 存在")

print("[B] 美学包解析")
steps = pm.apply_pack("aesthetic_pack_cinema")
check(isinstance(steps, list) and steps, "cinema 包能解析出步骤")
check(all(s.get("kind") in PACK_STEP_KINDS for s in steps), "步骤 kind 全部合法")
check(pm.apply_pack("nonexistent") is None, "未知包返回 None")

print("[C] 落盘 roundtrip（用户自定义持久化）")
pm2 = PresetManager()
custom_pack = pm2.create_pack("我的测试包", [{"kind": "filter", "filter_name": "电影", "intensity": 0.5}])
check(custom_pack is not None, "create_pack 成功")
custom_preset = pm2.create_preset("我的导出预设", "export", {"resolution": "1x1"})
check(custom_preset is not None, "create_preset 成功")
# 新实例重新加载，应包含用户自定义
pm3 = PresetManager()
check(pm3.get_pack(custom_pack["id"]) is not None, "重载后自定义包仍在")
check(pm3.get_preset(custom_preset["id"]) is not None, "重载后自定义预设仍在")
# 清理：删掉测试数据，避免污染后续
pm3.delete_pack(custom_pack["id"])
pm3.delete_preset(custom_preset["id"])

print("[D] 导入/导出真读写 JSON")
with tempfile.TemporaryDirectory() as td:
    # 导出预设
    p_out = os.path.join(td, "preset.json")
    check(pm.export_preset("effect_preset_1", p_out), "export_preset 写入文件")
    check(os.path.isfile(p_out), "导出文件存在")
    # 导出包
    pk_out = os.path.join(td, "pack.json")
    check(pm.export_pack("aesthetic_pack_cinema", pk_out), "export_pack 写入文件")
    with open(pk_out, "r", encoding="utf-8") as f:
        pk_data = json.load(f)
    check(pk_data.get("id") == "aesthetic_pack_cinema", "导出包 JSON 内容正确")
    # 导入预设（改 id 避免覆盖默认）
    with open(p_out, "r", encoding="utf-8") as f:
        pdata = json.load(f)
    pdata["id"] = "effect_import_test"
    p_in = os.path.join(td, "import_preset.json")
    with open(p_in, "w", encoding="utf-8") as f:
        json.dump(pdata, f, ensure_ascii=False)
    imported = pm.import_preset(p_in)
    check(any(p["id"] == "effect_import_test" for p in imported), "import_preset 生效")
    pm.delete_preset("effect_import_test")
    # 导入包
    pk_data["id"] = "aesthetic_pack_import_test"
    pk_in = os.path.join(td, "import_pack.json")
    with open(pk_in, "w", encoding="utf-8") as f:
        json.dump(pk_data, f, ensure_ascii=False)
    imported_packs = pm.import_pack(pk_in)
    check(any(p["id"] == "aesthetic_pack_import_test" for p in imported_packs), "import_pack 生效")
    pm.delete_pack("aesthetic_pack_import_test")

print("[E] editor_module.apply_aesthetic_pack（AST 静态）")
src = open(os.path.join(ROOT, "app", "modules", "lego", "editor_module.py"),
           encoding="utf-8").read()
tree = ast.parse(src)
funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _names(fn) -> set:
    return {n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


fn = funcs.get("apply_aesthetic_pack")
check(fn is not None, "apply_aesthetic_pack 存在")
if fn is not None:
    names = _names(fn)
    check("_ensure_preset_manager" in names, "调用 _ensure_preset_manager（拿包）")
    check("_record_action" in names, "调用 _record_action（可撤销）")
    check("_sync_timeline_widget_state" in names, "同步时间线控件")
    check("_refresh_preview_with_effects" in names, "刷新预览")
    # 写真相源：方法体内有对 self._clips 的赋值/遍历，且有 target[k]=v 类写入
    body_src = ast.get_source_segment(src, fn) or ""
    check("self._clips" in body_src, "读写真相源 self._clips")
    check("target[k]" in body_src or "target[" in body_src, "写目标片段字段")

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项：")
    for f in _failures:
        print("   -", f)
    sys.exit(1)
print("OK 美学预设包回归通过")
