# -*- coding: utf-8 -*-
"""转场撑开回归：14 种转场加载 + xfade 映射 + numpy 渲染（只读验证）"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "app"))

from core import transition_plugin_registry as reg

trans = reg.list_transitions()
ids = [t["id"] for t in trans]
print("转场数量:", len(ids))
print("转场ID:", ids)

tests = [
    ({"plugin_id": "transition_circle", "direction": "open"}, "circleopen"),
    ({"plugin_id": "transition_circle", "direction": "close"}, "circleclose"),
    ({"plugin_id": "transition_vert", "direction": "open"}, "vertopen"),
    ({"plugin_id": "transition_horz", "direction": "close"}, "horzclose"),
    ({"plugin_id": "transition_cover", "direction": "left"}, "coverleft"),
    ({"plugin_id": "transition_reveal", "direction": "right"}, "revealright"),
    ({"plugin_id": "transition_smooth", "direction": "up"}, "smoothup"),
]
ok = True
for t, expected in tests:
    got = reg.xfade_name_for_transition(t)
    status = "OK" if got == expected else "FAIL"
    if got != expected:
        ok = False
    print(f"{status} {t} -> {got} (期望 {expected})")

for t, _ in tests:
    plan = reg.export_fidelity_for_transition(t)
    print(f"fidelity {t['plugin_id']} mode={plan['mode']} xfade={plan['xfade']}")

import numpy as np
from_frame = np.full((120, 160, 3), 255, np.uint8)
to_frame = np.full((120, 160, 3), 0, np.uint8)
for pid in ["transition_circle", "transition_vert", "transition_horz",
            "transition_cover", "transition_reveal", "transition_smooth"]:
    d = "open" if pid in ("transition_circle", "transition_vert", "transition_horz") else "left"
    out = reg.apply_frames(pid, from_frame, to_frame, 0.5, {"direction": d})
    shape = out.shape if out is not None else "None"
    print(f"渲染 {pid}: {'OK' if out is not None else 'FAIL'} shape={shape}")

print("ALL OK" if ok else "HAS FAIL")
sys.exit(0 if ok else 1)
