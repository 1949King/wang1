# -*- coding: utf-8 -*-
"""MCP 工具清单导出守卫（Agent 编排演进 · 工具化第一步，2026-10-18）

断言：
  ① MCP spec 形状：每工具 name/description/inputSchema 必备；name 唯一、
     形如 capability id（含点分命名空间）
  ② 完整性：工具数与能力目录行数一致（目录漂移即报警）
  ③ 注解诚实：read ⇒ readOnlyHint；四类写 effect ⇒ destructiveHint；
     effect/category/paid/hemisphere 注解与目录登记逐项一致
  ④ 导出往返：SG_MCP_MANIFEST 隔离路径写盘 → 读回一致；空目录/坏路径
     诚实失败绝不抛异常

用法（项目根执行）：.venv312\\Scripts\\python.exe _verify/check_mcp_manifest.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

try:
    _SG_TMP = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".workbuddy", "tmp",
    )
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


# ── ①②③ 形状 / 完整性 / 注解诚实 ────────────────────────────────────

def check_manifest() -> None:
    from app.core.mcp_tool_manifest import build_tool_manifest
    try:
        from app.core.agent_capability_catalog import CAPABILITY_ROWS
    except ImportError:
        from core.agent_capability_catalog import CAPABILITY_ROWS  # type: ignore

    tools = build_tool_manifest()
    if not tools:
        _fail("① 工具清单为空（能力目录不可用？）")
        return

    names = [t["name"] for t in tools]
    if len(names) != len(set(names)):
        _fail("① name 有重复（MCP tools/list 要求唯一）")
    for t in tools:
        for field in ("name", "description", "inputSchema"):
            if not t.get(field):
                _fail(f"① 工具 {t.get('name')!r} 缺 MCP 必备字段：{field}")
        if "." not in t["name"]:
            _fail(f"① 工具名不符合 capability id 命名：{t['name']}")
        schema = t.get("inputSchema") or {}
        if schema.get("type") != "object":
            _fail(f"① {t['name']} inputSchema.type 应为 object")

    # ② 完整性：与目录行数一致
    if len(tools) != len(CAPABILITY_ROWS):
        _fail(f"② 工具数 {len(tools)} ≠ 目录行数 {len(CAPABILITY_ROWS)}（漂移）")

    # ③ 注解与目录逐项一致 + 诚实映射
    by_name = {t["name"]: t for t in tools}
    for cid, category, effect, paid, _desc, hemi, _label, _kw in CAPABILITY_ROWS:
        t = by_name.get(cid)
        if t is None:
            _fail(f"② 目录行未进工具清单：{cid}")
            continue
        ann = t.get("annotations") or {}
        if (ann.get("effect"), ann.get("category")) != (effect, category):
            _fail(f"③ {cid} effect/category 注解与目录不一致")
        if ann.get("paid") != bool(paid):
            _fail(f"③ {cid} paid 注解与目录不一致")
        if ann.get("hemisphere") != hemi:
            _fail(f"③ {cid} hemisphere 注解与目录不一致")
        if ann.get("readOnlyHint") != (effect == "read"):
            _fail(f"③ {cid} readOnlyHint 与 effect 不符（诚实红线）")
        if ann.get("destructiveHint") != (effect != "read"):
            _fail(f"③ {cid} destructiveHint 与 effect 不符（诚实红线）")


# ── ④ 导出往返 ───────────────────────────────────────────────────────

def check_export() -> None:
    root = tempfile.mkdtemp(prefix="sg_mcpm_")
    target = os.path.join(root, "manifest.json")
    os.environ["SG_MCP_MANIFEST"] = target
    try:
        from app.core.mcp_tool_manifest import export_manifest, build_tool_manifest

        if export_manifest() is not True:
            _fail("④ 导出应成功（env 隔离路径）")
            return
        with open(target, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if [t["name"] for t in loaded.get("tools") or []] != \
           [t["name"] for t in build_tool_manifest()]:
            _fail("④ 落盘往返与内存清单不一致")

        # 坏路径：诚实失败、绝不抛异常
        if export_manifest("z:/__no_such_dir__/m.json") is not False:
            _fail("④ 坏路径应返回 False（绝不抛出）")
    finally:
        os.environ.pop("SG_MCP_MANIFEST", None)


def main() -> int:
    check_manifest()
    check_export()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  MCP 工具清单：spec 形状/目录完整性/注解诚实/导出往返")
    return 0


if __name__ == "__main__":
    sys.exit(main())
