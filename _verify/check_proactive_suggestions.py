# -*- coding: utf-8 -*-
"""回归：Agent 主动建议引擎（V4.21.0 参考功能 2）。

自包含执行（不依赖 pytest）。覆盖：
  A. suggest_next_actions 规则命中（确定性、无随机）
  B. 空状态不崩溃、返回空
  C. limit 截断、priority 排序
  D. 建议执行类型合法（capability / editor_method）
  E. collect_proactive_state 从 mock editor 收集状态
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.agent_proactive import (  # noqa: E402
    suggest_next_actions,
    collect_proactive_state,
    KIND_CAPABILITY,
    KIND_EDITOR_METHOD,
)

_failures = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


print("[A] 规则命中")
# 有素材但未调色 → 应出现美学包 + 调色建议
s1 = suggest_next_actions({"clip_count": 3, "selected_has_color": False,
                            "has_transition": False, "has_subtitle": False})
ids1 = [s["id"] for s in s1]
check("apply_aesthetic_pack" in ids1, "未调色命中美学包建议")
check("add_transition" in ids1, "多片段无转场命中转场建议")
check("color_grade" in ids1, "未调色命中调色建议")

# 已有转场 + 调色 → 不再重复建议转场/调色
s2 = suggest_next_actions({"clip_count": 3, "selected_has_color": True,
                           "has_transition": True, "has_subtitle": False})
ids2 = [s["id"] for s in s2]
check("add_transition" not in ids2, "已有转场不重复建议")
check("color_grade" not in ids2, "已调色不重复建议调色")
check("apply_aesthetic_pack" not in ids2, "已调色不重复建议美学包")

print("[B] 空状态 / 缺字段健壮")
check(suggest_next_actions(None) == [], "None 状态返回空")
check(suggest_next_actions({}) == [], "空 dict 返回空")
check(isinstance(suggest_next_actions({"clip_count": "abc"}), list), "脏字段不崩溃")

print("[C] limit 截断 + priority 排序")
s3 = suggest_next_actions({"clip_count": 2, "selected_has_color": False,
                           "has_transition": False, "has_subtitle": False,
                           "is_export_ready": True}, limit=2)
check(len(s3) == 2, f"limit=2 截断（实际 {len(s3)}）")
pris = [s["priority"] for s in s3]
check(pris == sorted(pris, reverse=True), "按 priority 降序")

print("[D] 执行类型合法")
for s in s1:
    check(s["kind"] in (KIND_CAPABILITY, KIND_EDITOR_METHOD),
          f"{s['id']} kind 合法")
    check(isinstance(s.get("target"), str) and s.get("target"), f"{s['id']} 有执行目标")

print("[E] collect_proactive_state（mock editor）")
class _Clip(dict):
    pass
class _Editor:
    def __init__(self):
        self._clips = [_Clip({"id": "c1", "transition": None, "effects": {}}),
                       _Clip({"id": "c2", "transition": {"type": "fade"}})]
        self._subtitles = ["一条字幕"]
        self._current_clip = self._clips[0]

st = collect_proactive_state(_Editor())
check(st["clip_count"] == 2, "clip_count 正确")
check(st["has_transition"] is True, "has_transition 正确（c2 有转场）")
check(st["has_subtitle"] is True, "has_subtitle 正确")
check(st["selected_has_color"] is False, "当前片段未调色")

_cur = _Clip({"id": "c3", "effects": {"color_params": {"contrast": 1.2}}})
e2 = _Editor()
e2._current_clip = _cur
st2 = collect_proactive_state(e2)
check(st2["selected_has_color"] is True, "当前片段已调色被识别")

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项：")
    for f in _failures:
        print("   -", f)
    sys.exit(1)
print("OK Agent 主动建议引擎回归通过")
