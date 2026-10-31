#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""工作流蓝图（Blueprint）目录与接线守卫（2026-10-31）

锁六件事：

  A. 节点目录不漂移：前端 ports.ts 的每个 kind 都在蓝图目录里，
     且都有**中文标签**（没标签 ⇒ LLM 拿到的是英文 kind，等于没目录）；
  B. 调色板不越界：NodePalette.tsx 的每个 kind 都在 ports.ts 里
     （palette 能建出来但端口表没有 ⇒ 连线规则缺失）；
  C. 标准链类型合法：每条「必需前置」边都过端口类型校验
     （踩过的坑：shotlist 只吃 video/grid，不吃 image）；
  D. action 在册：`applyBlueprint` 必须在 agent_action_registry 里，
     且 effect = canvas_write（不付费、不破坏性）；
  E. 接线在册：前端 applyBlueprint 分支 + 后端提示词注入 + 策略白名单，
     三处缺一不可（历史上出现过「模块写了但没人调用」的摆设）；
  F. **LLM 永不输出像素坐标**：蓝图 schema 里不许有 x/y，
     提示词里必须明确禁止（AiDiagram 的语义放置模式）。

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_canvas_blueprint_catalog.py
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LIBTV = os.path.join(ROOT, "vendor", "packages", "libtv", "src")
PORTS_TS = os.path.join(LIBTV, "ports.ts")
PALETTE_TS = os.path.join(LIBTV, "NodePalette.tsx")
LAYOUT_TS = os.path.join(LIBTV, "blueprintLayout.ts")
APPLY_TS = os.path.join(LIBTV, "applyBlueprint.ts")
AGENT_PANEL = os.path.join(LIBTV, "AgentPanel.tsx")
POLICY_PY = os.path.join(ROOT, "app", "core", "agent_policy.py")
HOST_PY = os.path.join(ROOT, "app", "core", "project_agent_host.py")
REGISTRY_PY = os.path.join(ROOT, "app", "core", "agent_action_registry.py")

_failures: list = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _strip_comments(src: str) -> str:
    """去掉 /* */ 与 // 注释 —— 静态判定必须看**代码**，不能看注释里的字样。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


# ── A. 节点目录 ↔ ports.ts ───────────────────────────────────────────────
print("[A] 蓝图节点目录 ↔ 前端 ports.ts")
from app.core import canvas_blueprint as cb

cat = cb.node_kind_catalog()
kinds = {row["kind"] for row in cat}
_ports_src = _read(PORTS_TS)
_ports_kinds = set(re.findall(r"^\s{2}([A-Za-z][A-Za-z0-9_]*)\s*:\s*\{", _ports_src, re.M))
check(len(_ports_kinds) >= 20, f"ports.ts 解析到 {len(_ports_kinds)} 个节点 kind")
_missing = sorted(_ports_kinds - kinds)
check(not _missing, f"ports.ts 的 kind 全部进目录（缺失：{_missing[:5]}）")
_no_label = sorted(row["kind"] for row in cat if row["label"] == row["kind"])
check(not _no_label, f"每个 kind 都有中文标签（无标签：{_no_label[:5]}）")

# ── B. 调色板 ↔ ports.ts ─────────────────────────────────────────────────
print("[B] NodePalette.tsx ↔ ports.ts")
_palette_src = _read(PALETTE_TS)
_palette_kinds = set(
    re.findall(r'type:\s*"([A-Za-z][A-Za-z0-9_]*)",\s*label:', _palette_src)
)
check(len(_palette_kinds) >= 20, f"调色板解析到 {len(_palette_kinds)} 个 kind")
_p_out = sorted(_palette_kinds - _ports_kinds)
check(not _p_out, f"调色板 kind 全部在 ports.ts（越界：{_p_out[:5]}）")
_p_missing = sorted(_ports_kinds - _palette_kinds)
check(not _p_missing, f"ports.ts 的 kind 全部在调色板（漏：{_p_missing[:5]}）")

# ── C. 标准路径类型合法 ───────────────────────────────────────────────────
print("[C] 标准路径（相邻两环）类型合法")
from app.core.canvas_port_model import can_connect

_bad = []
_checked = 0
for _key, _path in cb.CANONICAL_PATHS.items():
    for _i in range(len(_path) - 1):
        _checked += 1
        _v = can_connect(_path[_i], _path[_i + 1])
        if not _v.get("ok"):
            _bad.append(f"{_path[_i]} → {_path[_i + 1]}：{_v.get('reason')}")
check(not _bad, f"标准路径 {_checked} 条相邻边全部类型兼容（不合：{_bad[:3]}）")
check(len(cb.CANONICAL_PATHS) >= 5, f"标准路径 {len(cb.CANONICAL_PATHS)} 条")
# 终点判别：scope 信号不能被风格描述误触发
check(cb.detect_ceiling("从剧本到成片") == "codeVideo", "终点判别：成片")
check(cb.detect_ceiling("完整流程，画面要二次元风格") is None,
      "终点判别：风格描述不误触发 scope")

# ── D. action 在册 ────────────────────────────────────────────────────────
print("[D] applyBlueprint 在 action 注册表")
from app.core import agent_action_registry as reg

_rows = {a: (lvl, eff, desc) for a, lvl, eff, desc in reg._CANVAS_ACTION_ROWS}
check("applyBlueprint" in _rows, "applyBlueprint 在 _CANVAS_ACTION_ROWS 里")
if "applyBlueprint" in _rows:
    _lvl, _eff, _desc = _rows["applyBlueprint"]
    check(_eff == "canvas_write", f"effect = canvas_write（实际 {_eff}）")
    check(_lvl == "safe", f"danger = safe（实际 {_lvl}）")

# ── E. 接线在册 ───────────────────────────────────────────────────────────
print("[E] 前后端接线在册")
check(os.path.isfile(LAYOUT_TS), "前端 blueprintLayout.ts 存在")
check(os.path.isfile(APPLY_TS), "前端 applyBlueprint.ts 存在")
_ap_src = _read(APPLY_TS)
check("layoutBlueprint" in _ap_src, "applyBlueprint.ts 依赖本地布局引擎（坐标本地算）")
_panel_src = _read(AGENT_PANEL)
check('case "applyBlueprint"' in _panel_src, "AgentPanel.tsx 有 applyBlueprint 分支")
check('from "./applyBlueprint"' in _panel_src, "AgentPanel.tsx 导入了 applyBlueprint")
_policy_src = _read(POLICY_PY)
check("applyBlueprint" in _policy_src, "agent_policy.py 的允许 action 含 applyBlueprint")
_host_src = _read(HOST_PY)
check("blueprint_prompt_block" in _host_src, "project_agent_host 注入蓝图提示词")
check("normalize_canvas_tools" in _host_src, "project_agent_host 调用蓝图归一化")

# ── F. LLM 永不输出像素坐标 ───────────────────────────────────────────────
print("[F] 蓝图 schema 不含坐标（语义放置模式）")
_block = cb.blueprint_prompt_block()
check("禁止输出 x/y 坐标" in _block, "提示词明确禁止输出 x/y 坐标")
_layout_src = _read(LAYOUT_TS)
check('"x"' not in _layout_src.split("export interface BlueprintNodeSpec")[1].split("}")[0],
      "BlueprintNodeSpec 里没有 x 字段")
# 注：判定前先剥注释 —— 文件头文档里会**引用** Math.random 来说明问题，
#     那是说明不是调用（踩过一次：注释里的 `Math.random()` 把守卫判红了）。
_layout_code = _strip_comments(_layout_src)
_ap_code = _strip_comments(_ap_src)
check(not re.search(r"Math\.random\s*\(", _layout_code), "布局引擎不含随机调用（确定性坐标）")
check(not re.search(r"Math\.random\s*\(", _ap_code), "落图模块不含随机调用")
check(not re.search(r"Date\.now\s*\(", _layout_code), "布局引擎不含时间戳（确定性坐标）")

# ── G. 后端合成兜底（模型不吐蓝图时也要有完整流程）────────────────────────
print("[G] 后端合成兜底（模型只给计划 ⇒ 照样铺出完整流程）")
check(hasattr(cb, "ensure_workflow_blueprint"), "canvas_blueprint 暴露 ensure_workflow_blueprint")
check(hasattr(cb, "synthesize_workflow_blueprint"), "canvas_blueprint 暴露 synthesize_workflow_blueprint")
check("ensure_workflow_blueprint" in _host_src,
      "project_agent_host 调用 ensure_workflow_blueprint（兜底层在链路上）")
# 合成结果必须**一次铺出整条链**（用户抱怨的核心：只能出 1~3 张卡）
_synth = cb.synthesize_workflow_blueprint("帮我做一集 60 秒的竖屏漫剧，从剧本到成片")
check(bool(_synth), "命中「完整流程」的需求能合成出蓝图")
if _synth:
    _snodes = _synth["blueprint"]["nodes"]
    _sedges = _synth["blueprint"]["edges"]
    check(len(_snodes) >= 5, f"合成出 {len(_snodes)} 个节点（≥5，不是 1~3 张卡）")
    check(len(_sedges) >= 3, f"合成出 {len(_sedges)} 条连线（≥3）")
    _skinds = {n["kind"] for n in _snodes}
    _unknown = sorted(_skinds - kinds)
    check(not _unknown, f"合成节点 kind 全在目录（越界：{_unknown[:3]}）")
    _no_prompt = [n["kind"] for n in _snodes if not (n.get("prompt") or "").strip()]
    check(not _no_prompt, f"合成节点都带提示词正文（缺：{_no_prompt[:3]}）")
# 单步需求不得乱铺（不臆造端点）
check(cb.synthesize_workflow_blueprint("帮我生张图") is None, "单步需求不合成（不乱铺）")
# 提示词必须和真实审批机制一致：确认由系统弹框，模型不必等用户点头
from app.core.agent_policy import mode_prompt_block

_collab = mode_prompt_block("collaborative")
check("等用户确认" not in _collab,
      "协作模式段不再要求模型「等用户确认」（那正是只出计划的根因）")
check("不要在文字里停下来等用户点头" in _collab, "协作模式段明说：说明与指令同批输出")
print()
if _failures:
    print(f"❌ 蓝图目录 + 接线守卫失败 {len(_failures)} 项：")
    for f in _failures:
        print(f"   - {f}")
    sys.exit(1)
print("OK 工作流蓝图目录 + 接线守卫全绿")
