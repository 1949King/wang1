# -*- coding: utf-8 -*-
"""DirectorSkill「落地时间线」功能测试（P0-1，2026-09-26）

覆盖 4 个场景：
  1. 有素材目录 + 有总线订阅者（模拟剪辑模块已打开）→ 应落地，载荷=分镜数
  2. 无素材目录 → 步骤跳过，applied=False，保持"只出报告"
  3. 素材目录为空 → applied=False，reason=没有可用视频文件
  4. 有素材目录但无订阅者（剪辑模块未打开）→ applied=False，reason=剪辑模块未打开

运行：python _verify/test_director_timeline_apply.py
产物：_verify/out_director_timeline_apply.json
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.modules.lego.skill_engine import skill_engine  # noqa: E402
from app.modules.lego.core import EventBus, EventType  # noqa: E402
from app.modules.lego.video_editing_skill import register_skills  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "out_director_timeline_apply.json")

register_skills()


def run(inputs, listen=False):
    received = []
    bus = EventBus.get_instance()
    listener = (lambda e: received.append(e.data)) if listen else None
    if listener:
        bus.on(EventType.MATERIAL_TO_TIMELINE, listener)
    try:
        res = skill_engine.execute_skill("director", inputs)
    finally:
        if listener:
            bus.off(EventType.MATERIAL_TO_TIMELINE, listener)
    return res, received


def report_of(res):
    return res.get("outputs", {}).get("director_report", {}) or {}


results = {"cases": {}, "assertions": []}


def check(name, cond, detail=""):
    results["assertions"].append(
        {"name": name, "ok": bool(cond), "detail": str(detail)[:300]})
    return bool(cond)


# ── 素材目录（2 个假视频文件，仅用于路径存在性）──
media_dir = tempfile.mkdtemp(prefix="director_media_")
for i in range(2):
    with open(os.path.join(media_dir, f"shot{i}.mp4"), "wb") as fh:
        fh.write(b"\x00" * 16)
empty_dir = tempfile.mkdtemp(prefix="director_empty_")

# ── 场景 1：有素材 + 有订阅者 ──
res1, rec1 = run({"topic": "测试主题", "source_dir": media_dir}, listen=True)
r1 = report_of(res1)
check("case1.skill_success", res1.get("success"), res1.get("state"))
check("case1.applied_true", r1.get("edit_instructions_applied_to_timeline") is True,
      r1.get("timeline_apply_note"))
check("case1.one_event", len(rec1) == 1, len(rec1))
shots_n = len(r1.get("storyboard", []))
payload_clips = (rec1[0].get("clips") if rec1 else []) or []
check("case1.payload_matches_storyboard", len(payload_clips) == shots_n,
      f"payload={len(payload_clips)} shots={shots_n}")
check("case1.payload_paths_exist",
      payload_clips and all(os.path.exists(c.get("path", "")) for c in payload_clips))
check("case1.source_tag", rec1 and rec1[0].get("source") == "director_skill",
      rec1[0].get("source") if rec1 else None)

# ── 场景 2：无素材目录 → 只出报告 ──
res2, rec2 = run({"topic": "测试主题"}, listen=True)
r2 = report_of(res2)
check("case2.skill_success", res2.get("success"), res2.get("state"))
check("case2.applied_false", r2.get("edit_instructions_applied_to_timeline") is False,
      r2.get("timeline_apply_note"))
check("case2.no_event", len(rec2) == 0, len(rec2))

# ── 场景 3：素材目录为空 ──
res3, _ = run({"topic": "t", "source_dir": empty_dir}, listen=True)
r3 = report_of(res3)
check("case3.applied_false", r3.get("edit_instructions_applied_to_timeline") is False)
check("case3.reason_no_media",
      "没有可用视频文件" in str(r3.get("timeline_apply_note", "")),
      r3.get("timeline_apply_note"))

# ── 场景 4：有素材但无订阅者（剪辑模块未打开）──
res4, _ = run({"topic": "t", "source_dir": media_dir}, listen=False)
r4 = report_of(res4)
check("case4.applied_false", r4.get("edit_instructions_applied_to_timeline") is False)
check("case4.reason_no_listener",
      "剪辑模块未打开" in str(r4.get("timeline_apply_note", "")),
      r4.get("timeline_apply_note"))

results["cases"] = {
    "case1_note": r1.get("timeline_apply_note"),
    "case2_note": r2.get("timeline_apply_note"),
    "case3_note": r3.get("timeline_apply_note"),
    "case4_note": r4.get("timeline_apply_note"),
    "case1_shots": shots_n,
}

ok_all = all(a["ok"] for a in results["assertions"])
results["ALL_PASS"] = ok_all

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)

print("ALL_PASS" if ok_all else "FAIL")
for a in results["assertions"]:
    print(("PASS " if a["ok"] else "FAIL ") + a["name"] + " :: " + a["detail"])
