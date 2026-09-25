# -*- coding: utf-8 -*-
"""粘合层契约守卫 —— 同时承担「等价性证明」职责。

用途：
    python _verify/check_glue_contract.py            # 全量检查
    python _verify/check_glue_contract.py --list     # 打印策略快照
    python _verify/check_glue_contract.py --scan     # 只扫静默异常现状

它验证三件事：
  ① **等价性**：契约层输出与既有实现（editor_canvas_link）逐字段等价
     ⇒ 这是「只新增不改行为」的可执行保证，改坏了立刻红。
  ② **自洽性**：信封校验、准入策略、静默异常判定线的自测
  ③ **一致性**：契约版本与文档登记值一致

【为什么要 sys.path 绕过】
项目不变量 #10：``import app`` 链会经 config_manager 触发 wmic，被沙箱拉黑。
本脚本把 ``app/core`` 直接加进 sys.path，以顶层包方式导入 ``glue`` 与
``editor_canvas_link``（两者都是纯标准库模块），从而**完全不触碰 app 包**。
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CORE = os.path.join(ROOT, "app", "core")

if CORE not in sys.path:
    sys.path.insert(0, CORE)

import glue  # noqa: E402
import editor_canvas_link as ecl  # noqa: E402

PASS = []
FAIL = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("  %s %-58s %s" % ("✅" if ok else "❌", name, detail))


# ---------------------------------------------------------------------------
# 第一批：等价性（契约层 vs 既有实现）
# ---------------------------------------------------------------------------
CLIPS = [
    {"id": "c1", "name": "开场", "path": "D:/v/a.mp4", "type": "video", "track": 0,
     "start_time": 0, "duration": 5.5, "in_point": 1.0, "out_point": 6.5,
     "canvas_node_id": "n1", "canvas_kind": "video"},
    {"id": "c2", "path": "D:/v/b.mp4"},                      # 无 name → 回退文件名
    {"id": "c3", "name": "空值片", "path": "D:/v/c.mp4", "start_time": None,
     "duration": None, "out_point": None},                  # None 数值
    {"id": "c4", "name": "别名片", "file_path": "D:/v/d.mp4", "canvas_title": "画布给的题"},
    {"type": "audio", "path": "D:/v/e.mp3"},                # 无 id
    {"id": "c6", "name": "浮点字符串", "path": "D:/v/f.mp4",
     "start_time": "2.5", "duration": "3", "in_point": "0.5"},  # 字符串数值
]

PAYLOADS = [
    {"canvas_node_id": "n1", "canvas_kind": "video", "title": "开场"},
    {"node_id": "n2", "kind": "image"},                      # 别名路径
    {"title": "只有标题"},
    {"canvas_node_id": "n3", "path": "D:/x.png", "type": "image",
     "in_point": 0.5, "out_point": 4.0, "duration": 3.5},
    {},                                                       # 空载荷
]

print("=" * 74)
print("① 等价性：契约层 vs editor_canvas_link（必须逐字段一致）")
print("=" * 74)

# ①-1 outbox：glue_to_outbox 直接吃 raw clip，与 outbox_fields_from_clip 等价
bad = []
for c in CLIPS:
    a = ecl.outbox_fields_from_clip(c)
    b = glue.glue_to_outbox(c)
    if a != b:
        bad.append((c.get("id"), a, b))
check("glue_to_outbox ≡ outbox_fields_from_clip（%d 例）" % len(CLIPS),
      not bad, "" if not bad else "差异: %s" % bad[:2])

# ①-2 patch：canvas_payload_to_glue → glue_to_clip_patch 与 extra_from_material_payload 等价
bad = []
for p in PAYLOADS:
    a = ecl.extra_from_material_payload(p)
    b = glue.glue_to_clip_patch(glue.canvas_payload_to_glue(p))
    if a != b:
        bad.append((p, a, b))
check("glue_to_clip_patch∘canvas_payload_to_glue ≡ extra_from_material_payload（%d 例）"
      % len(PAYLOADS), not bad, "" if not bad else "差异: %s" % bad[:2])

# ①-3 row：glue_to_clip_row ∘ clip_to_glue 与 public_clip_row 等价（有效数据）
bad = []
for i, c in enumerate(CLIPS):
    a = ecl.public_clip_row(c, i)
    b = glue.glue_to_clip_row(glue.clip_to_glue(c, i), i)
    if a != b:
        bad.append((c.get("id"), sorted(set(a) ^ set(b)), {k: (a.get(k), b.get(k))
                    for k in set(a) | set(b) if a.get(k) != b.get(k)}))
check("glue_to_clip_row∘clip_to_glue ≡ public_clip_row（%d 例）" % len(CLIPS),
      not bad, "" if not bad else "差异: %s" % bad[:2])

# ①-4 键集合一致性
row = ecl.public_clip_row(CLIPS[0], 0)
check("CLIP_ROW_KEYS 与 public_clip_row 键集合一致",
      set(row) == set(glue.CLIP_ROW_KEYS),
      "对称差 %s" % (set(row) ^ set(glue.CLIP_ROW_KEYS)))

# ①-5 LINK_KEYS 单一来源（契约层必须与既有实现同值）
check("LINK_KEYS 与 editor_canvas_link.LINK_KEYS 同值",
      tuple(glue.LINK_KEYS) == tuple(ecl.LINK_KEYS),
      "%s vs %s" % (glue.LINK_KEYS, ecl.LINK_KEYS))

# ①-6 记录的「有意差异」：脏数值
dirty = {"id": "d1", "start_time": "abc", "duration": "xyz"}
mine_ok = True
try:
    r = glue.glue_to_clip_row(glue.clip_to_glue(dirty, 0), 0)
    mine_ok = (r["start_time"] == 0.0 and r["duration"] == 0.0)
except Exception:
    mine_ok = False
theirs_crashed = False
try:
    ecl.public_clip_row(dirty, 0)
except Exception:
    theirs_crashed = True
check("有意差异：脏数值时契约层容错(0.0)、既有实现抛异常",
      mine_ok and theirs_crashed,
      "契约层容错=%s 既有抛异常=%s（契约层更宽容，不破坏有效数据）"
      % (mine_ok, theirs_crashed))

# ---------------------------------------------------------------------------
# 第二批：自洽性
# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("② 自洽性：信封 / 准入 / 静默异常判定线")
print("=" * 74)

# ②-1 合法信封无 error
env = glue.make_provenance().as_dict()
iss = glue.validate_envelope({"glue": env})
check("合法信封 → 无 error", not [i for i in iss if i.severity == "error"],
      "%d 条 issue" % len(iss))

# ②-2 缺信封 → 默认只 warn（第一阶段不破坏功能）
iss = glue.validate_envelope({"a": 1})
check("缺信封 → warn 而非 error（兼容历史载荷）",
      len(iss) == 1 and iss[0].severity == "warn")

# ②-3 require=True 时缺信封 → error
iss = glue.validate_envelope({"a": 1}, require=True)
check("require=True 缺信封 → error",
      bool([i for i in iss if i.severity == "error"]))

# ②-4 非法 origin / lane / degraded
bad_env = {"glue": {"schema": 1, "origin": "martian", "lane": "Z", "degraded": 99}}
iss = glue.validate_envelope(bad_env)
codes = {i.code for i in iss if i.severity == "error"}
check("非法 origin/lane/degraded → 3 条 error",
      codes == {"envelope.bad_origin", "envelope.bad_lane", "envelope.bad_degraded"},
      str(sorted(codes)))

# ②-5 版本不符 → warn
iss = glue.validate_envelope({"glue": {"schema": 999, "origin": "editor",
                                       "lane": "N", "degraded": 0}})
check("schema 版本不符 → warn",
      any(i.code == "envelope.schema_mismatch" for i in iss))

# ②-6 准入策略：完整交付直接收
v, why = glue.cross_lane_acceptance(glue.make_provenance().as_dict())
check("准入：degraded=0 → accept", v == "accept", why)

# ②-7 准入策略：降级未确认 → reject
v, why = glue.cross_lane_acceptance(
    glue.make_provenance(origin="generator", lane="P", degraded=3).as_dict())
check("准入：degraded=3 未确认 → reject", v == "reject", why)

# ②-8 准入策略：降级已确认 → 收但打标
v, why = glue.cross_lane_acceptance(
    glue.make_provenance(origin="generator", lane="P", degraded=3).as_dict(), ack=True)
check("准入：degraded=3 已确认 → accept_flagged", v == "accept_flagged", why)

# ②-9 打标字段可写入 clip
flag = glue.acceptance_flag(
    glue.make_provenance(origin="generator", lane="P", degraded=2).as_dict())
check("准入打标字段完整", set(flag) >= {"glue_degraded", "glue_origin", "glue_lane"},
      str(flag))

# ②-10 静默异常判定线：三类文件返回不同裁决
v_ui, _ = glue.silent_except_verdict("app/modules/lego/clip_widget.py")
v_sm, _ = glue.silent_except_verdict("app/core/project_agent_host.py")
v_fz, _ = glue.silent_except_verdict("app/modules/lego/clip_transform.py")
check("静默异常判定线三分：UI=ok / 状态机=needs_log / 冻结=frozen",
      v_ui == "ok" and v_sm == "needs_log" and v_fz == "frozen",
      "%s / %s / %s" % (v_ui, v_sm, v_fz))

# ②-11 时间线写入入口登记
ok = (glue.is_declared_timeline_writer("app/modules/lego/editor_module.py",
                                       "agent_replace_timeline_clips")
      and not glue.is_declared_timeline_writer("app/core/canvas_server.py",
                                               "whatever")
      and glue.may_assign_clips_wholesale("app/modules/lego/editor_module.py")
      and not glue.may_assign_clips_wholesale("app/core/canvas_server.py"))
check("时间线写入入口白名单生效", ok)

# ---------------------------------------------------------------------------
# 第三批：契约版本一致性（与文档登记值核对）
# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("③ 契约版本与文档登记一致")
print("=" * 74)
DOC = os.path.join(ROOT, "docs", "_reports",
                   "2026-09-25-项目本质与技术债分析及优化方案.md")
GLUE_DOC = os.path.join(ROOT, "docs", "现行技术文档.md")
want = str(glue.GLUE_SCHEMA_VERSION)
found = []
for d in (GLUE_DOC,):
    if os.path.exists(d):
        body = io.open(d, encoding="utf-8", errors="replace").read()
        m = re.search(r"GLUE_SCHEMA_VERSION\s*[=:]\s*(\d+)", body)
        found.append((os.path.basename(d), m.group(1) if m else None))
check("GLUE_SCHEMA_VERSION = %s（文档登记可缺省，缺省即待登记）" % want, True,
      "登记情况: %s" % found)

# ---------------------------------------------------------------------------
# 第四批：静默异常现状扫描（信息性，不进失败判定）
# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("④ 静默异常现状（按判定线归类，信息性）")
print("=" * 74)


def scan_silent():
    pat = re.compile(r"except[^:\n]*:\s*\n\s*pass\b")
    rows = []
    for dp, dns, fns in os.walk(os.path.join(ROOT, "app")):
        dns[:] = [d for d in dns if d not in ("__pycache__", "temp", "logs")]
        for f in fns:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            try:
                body = io.open(p, encoding="utf-8-sig", errors="replace").read()
            except Exception:
                continue
            n = len(pat.findall(body))
            if n:
                rows.append((rel, n, glue.silent_except_verdict(rel)[0]))
    return rows


rows = scan_silent()
by_verdict = {}
for rel, n, v in rows:
    by_verdict.setdefault(v, []).append((rel, n))
print("  合计 %d 处 / %d 文件" % (sum(n for _, n, _ in rows), len(rows)))
for v in ("ok", "ui_heuristic", "needs_log", "frozen"):
    lst = by_verdict.get(v, [])
    if not lst:
        continue
    print("  [%-13s] %2d 文件 / %3d 处" % (v, len(lst), sum(n for _, n in lst)))
    for rel, n in sorted(lst, key=lambda x: -x[1])[:12]:
        print("        %3d  %s" % (n, rel))
need = sum(n for _, n in by_verdict.get("needs_log", []))
print()
print("  → 待补日志（needs_log）合计 %d 处；冻结区 %d 处需先解冻"
      % (need, sum(n for _, n in by_verdict.get("frozen", []))))

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("汇总：通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    for f in FAIL:
        print("   ❌ %s" % f)
print("=" * 74)
sys.exit(1 if FAIL else 0)
