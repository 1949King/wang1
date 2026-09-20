# -*- coding: utf-8 -*-
"""回归：画布生成 capability（canvas.generate_* / comfyui_run / concat_videos / image_to_video）。

自包含执行（不依赖 pytest）。

覆盖：
  A. 5 个新能力已注册（dispatcher）
  B. 目录 ↔ 注册 双向一致（verify_catalog_consistency 无问题）
  C. effect/paid 正确（generate_image/video = media_write 且付费；concat/image_to_video = media_write 免费）
  D. policy：协作模式 canvas.generate_image → require_approval（确认后执行红线）
  E. handler 诚实失败（缺参 / 非法入参不发真实请求）：
     - comfyui_run 缺 workflow_json / 非法 JSON → error
     - concat_videos < 2 路径 / 路径不存在 → error
     - image_to_video 缺 image_path / 文件不存在 → error
     - generate_image 空 prompt → ok=False（"提示词为空"，早退不发网络）

安全：不真实生图/生视频（不发网络、不花钱）；只测入参校验与早退分支。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.capability_dispatcher import CapabilityRequest, capability_dispatcher  # noqa: E402
from app.core.capability_handlers import (  # noqa: E402
    CanvasCapabilityHandlers, register_builtin_handlers,
)
from app.core.agent_capability_catalog import (  # noqa: E402
    capability_effect_paid, verify_catalog_consistency,
)
from app.core.agent_policy import (  # noqa: E402
    DECISION_REQUIRE_APPROVAL, EFFECT_MEDIA_WRITE, MODE_COLLABORATIVE, decide, lookup_tool,
)

NEW_CAPS = [
    "canvas.generate_image",
    "canvas.generate_video",
    "canvas.comfyui_run",
    "canvas.concat_videos",
    "canvas.image_to_video",
]

_failures = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


print("[A] 已注册")
register_builtin_handlers(capability_dispatcher)
registered = {e["capability_id"] for e in capability_dispatcher.list_capabilities()}
for c in NEW_CAPS:
    check(c in registered, f"{c} 已注册进 dispatcher")

print("[B] 目录一致性")
problems = verify_catalog_consistency(registered)
check(not problems, f"verify_catalog_consistency 无问题（{len(problems)} 项）")
if problems:
    for p in problems[:10]:
        print("     -", p)

print("[C] effect / paid")
eff_paid = capability_effect_paid()
check(eff_paid.get("canvas.generate_image") == ("media_write", True), "generate_image = media_write 付费")
check(eff_paid.get("canvas.generate_video") == ("media_write", True), "generate_video = media_write 付费")
check(eff_paid.get("canvas.comfyui_run") == ("media_write", False), "comfyui_run = media_write 免费")
check(eff_paid.get("canvas.concat_videos") == ("media_write", False), "concat_videos = media_write 免费")
check(eff_paid.get("canvas.image_to_video") == ("media_write", False), "image_to_video = media_write 免费")

print("[D] policy 确认后执行")
d = decide(tool_id="canvas.generate_image", mode=MODE_COLLABORATIVE)
check(d.action == DECISION_REQUIRE_APPROVAL, f"协作模式生图需确认（{d.action}）")
check(d.effect == EFFECT_MEDIA_WRITE, "effect 正确识别为 media_write")
d2 = decide(tool_id="canvas.concat_videos", mode=MODE_COLLABORATIVE)
check(d2.action == DECISION_REQUIRE_APPROVAL, "协作模式拼接也需确认")
check(lookup_tool("canvas.generate_video") == ("media_write", True), "lookup_tool 派生正确")

print("[E] handler 诚实失败（不发真实请求）")
h = CanvasCapabilityHandlers()
r = h.comfyui_run(CapabilityRequest(capability_id="canvas.comfyui_run", params={}))
check(not r.success, "comfyui_run 缺 workflow_json → error")
r = h.comfyui_run(CapabilityRequest(capability_id="canvas.comfyui_run", params={"workflow_json": "not-json"}))
check(not r.success, "comfyui_run 非法 JSON → error")
r = h.concat_videos(CapabilityRequest(capability_id="canvas.concat_videos", params={"paths": ["a.mp4"]}))
check(not r.success, "concat_videos < 2 路径 → error")
r = h.concat_videos(CapabilityRequest(capability_id="canvas.concat_videos",
                                       params={"paths": ["/no/such/a.mp4", "/no/such/b.mp4"]}))
check(not r.success, "concat_videos 路径不存在 → error")
r = h.image_to_video(CapabilityRequest(capability_id="canvas.image_to_video", params={}))
check(not r.success, "image_to_video 缺 image_path → error")
r = h.image_to_video(CapabilityRequest(capability_id="canvas.image_to_video",
                                       params={"image_path": "C:/no/such/file.png"}))
check(not r.success, "image_to_video 文件不存在 → error")
r = h.generate_image(CapabilityRequest(capability_id="canvas.generate_image", params={"prompt": ""}))
check(not r.success, "generate_image 空 prompt → ok=False（早退，不发网络）")

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项：")
    for f in _failures:
        print("   -", f)
    sys.exit(1)
print("OK 画布生成 capability 全部断言通过")
