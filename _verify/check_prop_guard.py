#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 pipeline.prop_consistency（手持道具守护）—— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_prop_guard.py

覆盖本能力**独有风险面**：
  1. 结构模板：覆盖常见武器，且**每条都含「无分支 / 单一主干」类约束**（治「三通结构」）
  2. 未知道具类型 → 降级仍带结构约束（宁可有、不可无）
  3. 提示词组合（武器名 + 手别 + 握法）
  4. 负面词含结构项（三通 / 分支）与接触项（融合 / 穿过手）
  5. 道具锚定 + 漂移定位
  6. 手部关键点规则（点数不足 / 低置信度 / 指尖粘连 / 手掌塌缩 / 正常）
  7. 脏数据容错
  8. 四处接线静态断言

说明：按**文件路径**加载纯函数模块，不 import app 包（不触发硬件探测）。
"""

from __future__ import annotations

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _load(name: str, *parts: str):
    """加载 app/core/ai 下的模块（伪包方式，使相对导入可用且不 import app 包）。"""
    import types
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    fname = parts[-1]
    modname = fname[:-3] if fname.endswith(".py") else fname
    full = f"{pkg}.{modname}"
    spec = importlib.util.spec_from_file_location(full, os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as f:
        return f.read()


def _hand(conf: float = 1.0, tips_spread: float = 1.0):
    """构造 21 点手部关键点：腕(0,0)、中指根(0,1)、五指指尖横向分散。"""
    pts = [{"x": 0.0, "y": 0.0, "confidence": conf} for _ in range(21)]
    pts[0] = {"x": 0.0, "y": 0.0, "confidence": conf}      # 腕
    pts[9] = {"x": 0.0, "y": 1.0, "confidence": conf}      # 中指根（定掌尺度）
    for j, idx in enumerate((4, 8, 12, 16, 20)):           # 五指指尖
        pts[idx] = {"x": (j - 2) * 0.5 * tips_spread, "y": 1.5, "confidence": conf}
    return pts


def main() -> int:
    pg = _load("_prop_guard", "app", "core", "ai", "prop_guard.py")

    # ── 1. 结构模板（每条都须含「无分支」类约束）──
    check("模板覆盖常见武器",
          all(k in pg.PROP_STRUCTURE_TEMPLATES for k in ("spear", "sword", "staff", "axe", "bow")))
    for k, (_name, desc) in pg.PROP_STRUCTURE_TEMPLATES.items():
        check(f"{k} 含「无分支/单一主干」约束",
              any(w in desc for w in ("无分支", "无任何分支", "无多余", "无枝节", "无分叉", "无凸起")))

    # ── 2. 结构提示 + 降级 ──
    check("spear 结构提示含无分支", "无任何分支" in pg.structure_hint("spear"))
    check("未知类型降级仍含结构约束", "无多余分支" in pg.structure_hint("某未知武器"))
    check("custom 覆盖模板", pg.structure_hint("spear", custom="自定义结构约束") == "自定义结构约束")

    # ── 3. 提示词组合 ──
    p = pg.build_prop_prompt("spear", grip="two_hand", hand="both")
    check("prompt 含武器名", "长枪" in p)
    check("prompt 含手别", "双手" in p)
    check("prompt 含握法描述", "双手握持" in p)
    check("未知武器 prompt 不崩", bool(pg.build_prop_prompt("某物")))

    # ── 4. 负面词 ──
    neg = pg.prop_negative()
    check("negative 含结构项（三通/分支）",
          any("三通" in x for x in neg) and any("分支" in x for x in neg))
    check("negative 含接触项（融合/穿过手）",
          any("融合" in x for x in neg) and any("穿过手" in x for x in neg))

    # ── 5. 道具锚定 + 漂移 ──
    prop = {"prop_type": "spear", "prop_color": "银白", "prop_material": "金属", "prop_length": "长"}
    a = pg.build_prop_anchor(prop)
    check("anchor ok + 指纹 12 位", a["ok"] is True and len(a["fingerprint"]) == 12)
    check("未改 → 无漂移", pg.diff_prop_anchor(a, prop)["ok"] is True)
    d = pg.diff_prop_anchor(a, dict(prop, prop_color="暗红"))
    check("改颜色 → 定位 prop_color", d["drifted"] == ["prop_color"])
    check("空锚定卡 → ok False", pg.diff_prop_anchor(None, prop)["ok"] is False)
    check("None prop → 空 traits", pg.extract_prop_traits(None) == {})

    # ── 6. 手部关键点规则 ──
    h_ok = pg.check_hand_keypoints(_hand())
    check("正常手 → ok", h_ok["ok"] is True and h_ok["valid"] is True)
    h_low = pg.check_hand_keypoints(_hand(conf=0.2))
    check("低置信度 → 判不可信", h_low["ok"] is False and len(h_low["low_conf"]) == 21)
    h_fused = pg.check_hand_keypoints(_hand(tips_spread=0.01))
    check("指尖挤在一起 → 判粘连", h_fused["fused"] is True and h_fused["ok"] is False)
    check("点数不足 → valid False", pg.check_hand_keypoints([{"x": 0, "y": 0}])["valid"] is False)
    check("None → valid False 不崩", pg.check_hand_keypoints(None)["valid"] is False)
    check("手掌塌缩 → valid False", pg.check_hand_keypoints([{"x": 0, "y": 0}] * 21)["valid"] is False)
    check("非法坐标 → valid False",
          pg.check_hand_keypoints([{"x": "bad", "y": 0}] * 21)["valid"] is False)

    # ── 7. 统一入口 ──
    pp = pg.plan_prop(prop, prop_type="spear", grip="two_hand")
    check("plan 含 prompt + negative + anchor",
          bool(pp["prompt"]) and bool(pp["negative"]) and pp["anchor"] is not None)
    pp2 = pg.plan_prop(prop, anchor=a)
    check("plan 带 anchor → 出 drift", pp2["drift"] is not None)
    pp3 = pg.plan_prop(prop, hand_points=_hand())
    check("plan 带 hand_points → 出 hand", pp3["hand"] is not None)
    pp4 = pg.plan_prop()
    check("plan 无参不崩", pp4["ok"] is True and bool(pp4["prompt"]))

    # ── 8. 四处接线（静态断言）──
    cat_src = _read("app", "core", "agent_capability_catalog.py")
    check("接线1 catalog 含 pipeline.prop_consistency", '"pipeline.prop_consistency"' in cat_src)
    h_src = _read("app", "core", "capability_handlers.py")
    check("接线2 handlers 含 def prop_consistency", "def prop_consistency" in h_src)
    check("接线2 handlers 含 register", 'dispatcher.register("pipeline.prop_consistency"' in h_src)
    a_src = _read("app", "core", "agent_action_registry.py")
    check("接线3 action 白名单含 prop_consistency", '"prop_consistency"' in a_src)
    check("接线3 映射到 pipeline.prop_consistency", '"pipeline.prop_consistency"' in a_src)
    check("接线4 帮助文案含参数说明", "prop_consistency 参数" in a_src)

    # ── 汇总 ──
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} / {TOTAL}")
        for x in FAILS:
            print(f"  - {x}")
        return 1
    print(f"ALL PASS ({TOTAL} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
