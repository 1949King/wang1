# -*- coding: utf-8 -*-
"""自包含回归：V4.28.2 靠近即吸附 · 所有等级拖拽中直接 snap。

不依赖 React/Vite：直接 grep 源码关键断言。
V4.28.2 起「instant 单独直接 snap + 其它三档渐进吸引」改为「进入磁吸范围即直接吸附」，
magneticStrength / getMagneticOffset 两个函数已删除。
"""
import os, re

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(REPO, "vendor", "packages", "canvas-core", "src", "magnetic")


def read(name):
    with open(os.path.join(SRC, name), "r", encoding="utf-8") as fh:
        return fh.read()


types_src = read("types.ts")
engine_src = read("MagneticEngine.ts")
drag_src = read("useMagneticDrag.ts")

# ── 1. 磁吸阈值不变（weak/medium/strong/instant = 120/50/60/10）──
def num(name, src):
    m = re.search(rf"\b{name}\s*:\s*(\d+)", src)
    assert m, f"{name} 未在源码找到"
    return int(m.group(1))

cfg = {
    "weak": num("weakDistance", types_src),
    "medium": num("mediumDistance", types_src),
    "strong": num("strongDistance", types_src),
    "instant": num("instantDistance", types_src),
}
print(f"  DEFAULT_MAG_CONFIG.weak    = {cfg['weak']}  (期望 120)")
print(f"  DEFAULT_MAG_CONFIG.medium  = {cfg['medium']}  (期望 50)")
print(f"  DEFAULT_MAG_CONFIG.strong  = {cfg['strong']}  (期望 60)")
print(f"  DEFAULT_MAG_CONFIG.instant = {cfg['instant']} (期望 10)")
assert cfg["weak"] == 120, f"weak 阈值漂移（实际 {cfg['weak']}）"
assert cfg["medium"] == 50, f"medium 阈值漂移（实际 {cfg['medium']}）"
assert cfg["strong"] == 60, f"strong 阈值漂移（实际 {cfg['strong']}）"
assert cfg["instant"] == 10, f"instant 阈值漂移（实际 {cfg['instant']}）"
print("OK 4 个阈值数值正确")

# ── 2. 靠近即吸附：onNodeDrag 对所有非 none 等级直接 writeNodePos 到 snapX/snapY ──
assert 'if (result.level !== "none" && result.targetId)' in drag_src, \
    "onNodeDrag 未统一为「非 none 即吸附」分支"
# 直接写 snapX/snapY（不再 getMagneticOffset 渐进）
assert re.search(r"x:\s*result\.snapX\s*,\s*y:\s*result\.snapY", drag_src), \
    "onNodeDrag 未直接 writeNodePos({x: snapX, y: snapY})"
assert "getMagneticOffset(" not in drag_src, "useMagneticDrag 不应再调 getMagneticOffset"
# 松手钉回落点
assert "writeNodePos(draggingNode.id, { x: magState.snapX, y: magState.snapY })" in drag_src, \
    "onNodeDragStop 未把卡片钉回落点"
print("OK 靠近即吸附：所有等级直接 snap，松手钉回落点")

# ── 3. MagneticEngine 死函数已删 ──
assert "magneticStrength" not in engine_src, "MagneticEngine 仍残留 magneticStrength"
assert "getMagneticOffset" not in engine_src, "MagneticEngine 仍残留 getMagneticOffset"
# levelRank 仍须含 instant:4（最高档，目标优先级）
assert "instant: 4" in engine_src or re.search(r"instant\s*:\s*4", engine_src), \
    "levelRank 未保留 instant:4 最高档"
print("OK magneticStrength/getMagneticOffset 已删，levelRank 保留 instant:4")

# ── 4. 未触碰的不变量数值 ──
assert "overshootPx: 5" in types_src
assert "snapAnimationMs: 200" in types_src
assert "stretchThreshold: 30" in types_src
assert "breakThreshold: 50" in types_src
assert "bondTolerance: 2" in types_src
assert "bondGiveRatio: 0.28" in types_src
print("OK 未触碰不变量仍正确（过冲5/回弹200/拉伸30/断裂50/bond 2/0.28）")

print("\n全部断言通过 · V4.28.2 靠近即吸附回归全绿")
