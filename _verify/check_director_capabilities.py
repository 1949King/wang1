# -*- coding: utf-8 -*-
"""导演分身能力化回归测试（P0-2，2026-09-26）

覆盖：
  A. 目录一致性守卫（verify_catalog_consistency）零问题
  B. pipeline.director_breakdown / director_camera_plan 已注册
  C. breakdown：剧本 → 分镜表（启发式，不依赖 LLM）
  D. camera_plan：剧本 → 机位 + 运镜路径；shots 直传路径
  E. agent_policy effect 明确登记（read，不落 FILE_WRITE 兜底）
  F. 启动自检 catalog 项为零

运行：python _verify/check_director_capabilities.py
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest  # noqa: E402
from app.core.capability_handlers import (  # noqa: E402
    register_builtin_handlers, get_startup_selfcheck)
from app.core import agent_policy  # noqa: E402
from app.core.agent_capability_catalog import verify_catalog_consistency  # noqa: E402

_failures = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


register_builtin_handlers(capability_dispatcher, editor_module_ref=lambda: None)

print("[A] 目录一致性守卫")
listed = capability_dispatcher.list_capabilities()
ids = {c["capability_id"] if isinstance(c, dict) else getattr(c, "capability_id", "")
       for c in listed}
problems = verify_catalog_consistency(ids)
check(not problems, f"目录 ↔ 注册 双向一致（问题：{problems[:3]}）" if problems
      else "目录 ↔ 注册 双向一致")

print("[B] 导演能力注册")
for cap in ("pipeline.director_breakdown", "pipeline.director_camera_plan"):
    check(cap in ids, f"{cap} 已注册")

print("[C] director_breakdown（启发式，零 LLM）")
script = "开场镜头推近展现主角。主角举起手中的剑。镜头拉远，主角站在城墙上。"
r = capability_dispatcher.invoke(CapabilityRequest(
    capability_id="pipeline.director_breakdown",
    params={"script": script, "use_llm": False}))
check(r.success, f"invoke 成功（{r.error or ''}）")
out = r.output or {}
shots = out.get("shots") or []
check(len(shots) >= 2, f"拆出 {len(shots)} 镜（≥2）")
check(all(isinstance(s.get("id"), int) and s.get("duration") for s in shots),
      "每镜含 id/duration 字段")

print("[D] director_camera_plan")
r2 = capability_dispatcher.invoke(CapabilityRequest(
    capability_id="pipeline.director_camera_plan",
    params={"script": script}))
check(r2.success, f"invoke 成功（{r2.error or ''}）")
cameras = (r2.output or {}).get("cameras") or []
check(len(cameras) == len(shots), f"机位数 {len(cameras)} == 分镜数 {len(shots)}")
if cameras:
    c0 = cameras[0]
    check(all(k in c0 for k in ("position", "lookAt", "fov", "shotSize", "movement",
                                "pathPoints", "pathDuration")),
          f"机位含 position/lookAt/fov/shotSize/movement/pathPoints/pathDuration：{sorted(c0.keys())}")

# shots 直传路径
r3 = capability_dispatcher.invoke(CapabilityRequest(
    capability_id="pipeline.director_camera_plan",
    params={"shots": [{"id": 1, "duration": 5, "shot": "特写", "description": "x"}]}))
check(r3.success and (r3.output or {}).get("cameras", [{}])[0].get("shotSize") == "特写",
      "shots 直传：特写景别机位生效")

print("[E] agent_policy effect 登记")
for cap in ("pipeline.director_breakdown", "pipeline.director_camera_plan"):
    eff = agent_policy._CAPABILITY_EFFECTS.get(cap)
    check(eff is not None and eff[0] == "read",
          f"{cap} → {eff}（应为 read，不落 FILE_WRITE 兜底）")

print("[F] 启动自检")
selfcheck = get_startup_selfcheck()
check(not selfcheck["catalog"], f"自检 catalog 项为零（{selfcheck['catalog'][:2]}）"
      if selfcheck["catalog"] else "自检 catalog 项为零")

print()
if _failures:
    print(f"FAIL：{len(_failures)} 项")
    sys.exit(1)
print("ALL_PASS")
