# -*- coding: utf-8 -*-
"""回归：分镜记忆规划（app/core/ai/storyboard_memory.py）。

守的是「模型 → 剪辑推论」这一层的换算是否正确：
  1. 保留率是模型算的真值（不是硬编码的常数）
  2. 总时长守恒（按保留率再分配，不是凭空加减）
  3. 细节让位、情绪拿时长（方向不能反）
  4. 夹紧与退化输入不炸
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.ai import memory_model as mm  # noqa: E402
from app.core.ai import storyboard_memory as sm  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + name + (("  → " + detail) if not cond else ""))
    if not cond:
        fails.append(name)


print("[1] 保留率必须是模型算的真值（与 memory_model 的 λ 一致）")
for ty, fn, key in (("detail", mm.detail_retention, "detail"),
                    ("meaning", mm.meaning_retention, "meaning"),
                    ("emotion", mm.emotion_retention, "emotion")):
    got = sm.retention(ty, 24.0)
    want = fn(24.0, d0=1.0) if ty == "detail" else (
        fn(24.0, s0=1.0) if ty == "meaning" else fn(24.0, e0=1.0))
    check(f"{ty} 24h 与模型一致 ({got:.4f})", abs(got - want) < 1e-9, f"{got} vs {want}")

# 评审文档引用的三个数
check("细节 24h ≈ 11.5%", abs(sm.retention("detail", 24) - 0.1153) < 0.002)
check("意义 24h ≈ 61.9%", abs(sm.retention("meaning", 24) - 0.6188) < 0.002)
check("情绪 24h ≈ 82.5%", abs(sm.retention("emotion", 24) - 0.8253) < 0.002)
check("顺序必须是 细节 < 意义 < 情绪",
      sm.retention("detail", 24) < sm.retention("meaning", 24) < sm.retention("emotion", 24))
check("时间越久保留越低",
      sm.retention("emotion", 72) < sm.retention("emotion", 24))

print("\n[2] 总时长守恒")
rows = [
    {"id": "a", "memoryType": "detail", "duration": 3},
    {"id": "b", "memoryType": "meaning", "duration": 3},
    {"id": "c", "memoryType": "emotion", "duration": 3},
]
r = sm.plan(rows)
check("totalSuggested ≈ totalCurrent (9.0)", abs(r["totalSuggested"] - 9.0) < 0.35,
      str(r["totalSuggested"]))
check("逐行 delta 之和 ≈ 0", abs(sum(x["delta"] for x in r["rows"])) < 0.35,
      str(sum(x["delta"] for x in r["rows"])))

print("\n[3] 方向正确：细节让位、情绪拿时长")
by = {x["id"]: x for x in r["rows"]}
check("细节被压缩 (<3)", by["a"]["suggestedDuration"] < 3, str(by["a"]))
check("情绪被拉长 (>3)", by["c"]["suggestedDuration"] > 3, str(by["c"]))
check("细节 < 意义 < 情绪",
      by["a"]["suggestedDuration"] < by["b"]["suggestedDuration"] < by["c"]["suggestedDuration"],
      str([(k, v["suggestedDuration"]) for k, v in by.items()]))

print("\n[4] 夹紧")
r2 = sm.plan([{"id": "x", "memoryType": "detail", "duration": 0.5},
              {"id": "y", "memoryType": "emotion", "duration": 0.5}])
check("不低于下限 0.8", all(x["suggestedDuration"] >= 0.8 - 1e-6 for x in r2["rows"]),
      str([x["suggestedDuration"] for x in r2["rows"]]))
r3 = sm.plan([{"id": "x", "memoryType": "emotion", "duration": 30},
              {"id": "y", "memoryType": "detail", "duration": 0.01}])
check("不超过上限 12", all(x["suggestedDuration"] <= 12 + 1e-6 for x in r3["rows"]),
      str([x["suggestedDuration"] for x in r3["rows"]]))

print("\n[5] 退化输入不炸")
for name, arg in (("空列表", []), ("None", None)):
    rr = sm.plan(arg)
    check(f"{name} → ok 且 rows 空", rr["ok"] and rr["rows"] == [], str(rr)[:100])
rr = sm.plan([{"id": "z", "memoryType": "", "duration": 3}])
check("缺失类型降级为 meaning 且仍在 [lo,hi]",
      rr["rows"][0]["memoryType"] == "meaning" and 0.8 <= rr["rows"][0]["suggestedDuration"] <= 12)
rr = sm.plan([{"id": "z", "memoryType": "胡说八道", "duration": 3}])
check("非法类型有 warning", any("无法识别" in w for w in rr["warnings"]), str(rr["warnings"]))
rr = sm.plan([{"id": "z", "duration": "abc"}])
check("非法时长回退 3.0 不炸", rr["rows"][0]["currentDuration"] == 3.0)

print("\n[6] 干扰提示（模型的 I 项）")
rr = sm.plan([
    {"id": "1", "memoryType": "emotion", "duration": 3},
    {"id": "2", "memoryType": "emotion", "duration": 3},
])
check("相邻情绪锚点会告警", any("相邻情绪锚点" in w for w in rr["warnings"]), str(rr["warnings"]))
rr = sm.plan([{"id": str(i), "memoryType": "emotion", "duration": 3} for i in range(6)])
check("名场面过多会告警", any("名场面太多" in w for w in rr["warnings"]), str(rr["warnings"]))
rr = sm.plan([
    {"id": "1", "memoryType": "detail", "duration": 3},
    {"id": "2", "memoryType": "meaning", "duration": 3},
])
check("正常分镜不误报", rr["warnings"] == [], str(rr["warnings"]))

print("\n[7] 全同类型时不应改变相对关系")
rr = sm.plan([{"id": str(i), "memoryType": "meaning", "duration": 2} for i in range(5)])
check("同类型 → 建议时长仍等于原时长（10/5=2）",
      all(abs(x["suggestedDuration"] - 2.0) < 0.05 for x in rr["rows"]),
      str([x["suggestedDuration"] for x in rr["rows"]]))

print()
if fails:
    print(f"✗ {len(fails)} 项失败: {fails}")
    sys.exit(1)
print("OK 分镜记忆规划全部通过")
