#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 pipeline.expression_clamp（表情幅度守护）—— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_expression_guard.py

覆盖本能力**独有风险面**：
  1. 幅度上限表（cheekPuff 显著小于 jawOpen —— 鼓腮最易夸张）
  2. 单帧钳制（超限压回 / 未超限不动）
  3. profile 缩放 + overrides 覆盖
  4. 帧间限幅（治「变化过于剧烈」）
  5. 质检定位（超限帧 / 跳变）
  6. 脏数据容错（None / 非 dict 帧 / 字符串 / 负值 / 超 1 / 未知名维度）
  7. 提示词约束 + 负面词
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


def main() -> int:
    eg = _load("_expression_guard", "app", "core", "ai", "expression_guard.py")

    # ── 1. 幅度上限表 ──
    check("cheekPuff 上限 < jawOpen（鼓腮最易夸张）",
          eg.NATURAL_CAPS["cheekPuff"] < eg.NATURAL_CAPS["jawOpen"])
    check("caps 覆盖常见维度",
          all(k in eg.NATURAL_CAPS for k in ("jawOpen", "cheekPuff", "browDownLeft",
                                            "mouthSmileLeft", "eyeWideLeft", "noseSneerLeft")))
    check("caps 全部在 (0,1]", all(0 < v <= 1.0 for v in eg.NATURAL_CAPS.values()))

    # ── 2. 单帧钳制 ──
    cap_cp = eg.NATURAL_CAPS["cheekPuff"]
    f = eg.clamp_frame({"cheekPuff": 0.9, "jawOpen": 0.3})
    check("超限被压回上限", f["params"]["cheekPuff"] == round(cap_cp, 4))
    check("未超限不动", f["params"]["jawOpen"] == 0.3)
    check("changed=True + reductions 记录",
          f["changed"] is True and len(f["reductions"]) == 1
          and f["reductions"][0]["key"] == "cheekPuff")
    f2 = eg.clamp_frame({"cheekPuff": 0.2})
    check("全合规 → 无改动", f2["changed"] is False and f2["reductions"] == [])

    # ── 3. profile + overrides ──
    sub, nat, inten = eg.resolve_caps("subtle"), eg.resolve_caps("natural"), eg.resolve_caps("intense")
    check("subtle < natural < intense",
          sub["cheekPuff"] < nat["cheekPuff"] < inten["cheekPuff"])
    check("overrides 生效", eg.resolve_caps("natural", {"cheekPuff": 0.1})["cheekPuff"] == 0.1)
    check("overrides 非法值跳过", eg.resolve_caps("natural", {"cheekPuff": "bad"})["cheekPuff"] == nat["cheekPuff"])

    # ── 4. 帧间限幅（治变化剧烈）──
    frames = [{"cheekPuff": 0.0}, {"cheekPuff": 0.9}]
    cs = eg.clamp_sequence(frames)
    check("帧间跳变被限幅", cs["frames"][1]["cheekPuff"] <= eg.DEFAULT_MAX_DELTA + 1e-9)
    check("jump_reductions 记录", len(cs["jump_reductions"]) >= 1)
    cs2 = eg.clamp_sequence([{"jawOpen": 0.1}, {"jawOpen": 0.2}, {"jawOpen": 0.3}])
    check("平缓序列无跳变记录", cs2["jump_reductions"] == [])

    # ── 5. 质检定位 ──
    chk = eg.check_amplitude(frames)
    check("质检发现超限", chk["ok"] is False and 1 in chk["over_frames"])
    check("超限维度定位", "cheekPuff" in chk["over_dims"])
    chk2 = eg.check_amplitude([{"cheekPuff": 0.1}, {"cheekPuff": 0.2}])
    check("合规序列 ok", chk2["ok"] is True and chk2["over_frames"] == [])

    # ── 6. 脏数据容错 ──
    check("None frames 不崩", eg.clamp_sequence(None)["frame_count"] == 0)
    check("非 dict 帧被跳过", eg.clamp_sequence([{"cheekPuff": 0.1}, "x", None])["frame_count"] == 1)
    check("字符串值降级 0", eg.clamp_frame({"cheekPuff": "abc"})["params"]["cheekPuff"] == 0.0)
    check("负值归零", eg.clamp_frame({"cheekPuff": -5})["params"]["cheekPuff"] == 0.0)
    check("未知名维度受兜底约束",
          eg.clamp_frame({"某未知维度": 0.95})["params"]["某未知维度"] <= eg.FALLBACK_CAP + 1e-9)
    check("None frame 不崩", eg.clamp_frame(None)["params"] == {})

    # ── 7. 提示词约束 ──
    check("hint 非空", bool(eg.build_expression_hint("生气")))
    check("hint 含情绪", "生气" in eg.build_expression_hint("生气"))
    check("hint 不含情绪时也非空", bool(eg.build_expression_hint("")))
    check("negative 非空且含鼓腮项", len(eg.expression_negative()) > 0
          and any("鼓腮" in x for x in eg.expression_negative()))

    # ── 8. 统一入口 ──
    p = eg.plan_expression(frames, emotion="生气")
    check("plan 含 clamped + check", p["clamped"] is not None and p["check"] is not None)
    check("plan 含 hint + negative + caps", bool(p["hint"]) and bool(p["negative"]) and bool(p["caps"]))
    p2 = eg.plan_expression(None)
    check("无 frames 只出提示词", p2["clamped"] is None and bool(p2["hint"]))

    # ── 9. 四处接线（静态断言）──
    cat_src = _read("app", "core", "agent_capability_catalog.py")
    check("接线1 catalog 含 pipeline.expression_clamp", '"pipeline.expression_clamp"' in cat_src)
    h_src = _read("app", "core", "capability_handlers.py")
    check("接线2 handlers 含 def expression_clamp", "def expression_clamp" in h_src)
    check("接线2 handlers 含 register", 'dispatcher.register("pipeline.expression_clamp"' in h_src)
    a_src = _read("app", "core", "agent_action_registry.py")
    check("接线3 action 白名单含 expression_clamp", '"expression_clamp"' in a_src)
    check("接线3 映射到 pipeline.expression_clamp", '"pipeline.expression_clamp"' in a_src)
    check("接线4 帮助文案含参数说明", "expression_clamp 参数" in a_src)

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
