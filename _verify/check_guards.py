#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 guards 门面 + 四模块深度增强 —— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_guards.py

覆盖：
  1. list_guards（四守护元信息 + capability id）
  2. guard_negative_all（合并去重，含各守护项）
  3. plan_guards（全跑 / 选跑 / 未知 kind 忽略 / 空输入 → ok False）
  4. tts_guard 批量消歧（**一次调用** + index 回填 + 降级）
  5. expression_guard 关键帧稀疏化（保首尾 / 变化处保留）
  6. character_anchor 多角色批量（同名 / 同指纹冲突）
  7. prop_guard 双持武器（主副武器结构各自约束）
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


def main() -> int:
    guards = _load("_guards", "app", "core", "ai", "guards.py")
    tg = _load("_tts_guard", "app", "core", "ai", "tts_guard.py")
    eg = _load("_expression_guard", "app", "core", "ai", "expression_guard.py")
    ca = _load("_character_anchor", "app", "core", "ai", "character_anchor.py")
    pg = _load("_prop_guard", "app", "core", "ai", "prop_guard.py")

    # ── 1. list_guards ──
    lst = guards.list_guards()
    check("守护清单 4 项", len(lst) == 4)
    check("清单 kind 与 GUARD_KINDS 一致", [m["kind"] for m in lst] == list(guards.GUARD_KINDS))
    check("每项带 pipeline.* capability",
          all(str(m.get("capability", "")).startswith("pipeline.") for m in lst))

    # ── 2. guard_negative_all ──
    neg = guards.guard_negative_all()
    check("负面词非空", len(neg) > 0)
    check("含结构项（三通）", any("三通" in x for x in neg))
    check("含表情项（鼓腮）", any("鼓腮" in x for x in neg))
    check("含角色项（换脸）", any("换脸" in x for x in neg))
    check("合并结果已去重", len(neg) == len(set(neg)))

    # ── 3. plan_guards ──
    r_all = guards.plan_guards()
    check("全跑 4 守护", r_all["count"] == 4 and set(r_all["kinds"]) == set(guards.GUARD_KINDS))
    check("全跑也带负面词", len(r_all["negative"]) > 0)
    check("全跑返回每守护结果", set(r_all["results"]) == set(guards.GUARD_KINDS))

    r_sel = guards.plan_guards(["prop"], params={"prop": {"prop_type": "spear"}})
    check("选跑仅 prop", r_sel["kinds"] == ["prop"])
    check("选跑参数已透传", bool(r_sel["results"]["prop"]["prompt"]))

    r_unk = guards.plan_guards(["prop", "不存在的守护"])
    check("未知 kind 被忽略", r_unk["kinds"] == ["prop"])

    r_empty = guards.plan_guards(["tts"], params={"tts": {"text": ""}})
    check("守护 ok=False → 门面 ok=False", r_empty["ok"] is False)

    r_noname = guards.plan_guards([])
    check("空 kinds → 无结果不崩", r_noname["count"] == 0 and r_noname["ok"] is False)

    # ── 4. tts 批量消歧（一次调用）──
    calls = {"n": 0}

    def batch_llm(prompt: str) -> str:
        calls["n"] += 1
        return '[{"index":0,"word":"重庆","char":"重","pinyin":"chóng"}]'

    lists = tg.detect_polyphones_batch(["我们去了重庆。", "他还在等。"], batch_llm)
    check("批量只调一次 LLM", calls["n"] == 1)
    check("按 index 回填到对应段", len(lists[0]) == 1 and lists[1] == [])
    check("index 字段被剔除", "index" not in lists[0][0])

    def boom_llm(prompt: str) -> str:
        raise RuntimeError("模拟 LLM 挂掉")

    check("批量抛错 → 全空不崩", tg.detect_polyphones_batch(["a", "b"], boom_llm) == [[], []])
    check("无 llm → 全空", tg.detect_polyphones_batch(["a", "b"], None) == [[], []])
    check("空段列表 → 空", tg.detect_polyphones_batch([], batch_llm) == [])

    calls2 = {"n": 0}

    def count_llm(prompt: str) -> str:
        calls2["n"] += 1
        return "[]"

    tg.plan_tts("她走了。他还在等。我今天很开心！", llm=count_llm)
    check("plan_tts 只调一次 LLM（原为逐段）", calls2["n"] == 1)

    # ── 5. expression 稀疏化 ──
    frames = [{"jawOpen": 0.1}] * 5 + [{"jawOpen": 0.5}] + [{"jawOpen": 0.5}] * 5
    sp = eg.sparse_frames(frames, min_delta=0.03)
    check("重复帧被丢弃", sp["dropped"] > 0)
    check("首帧保留", sp["kept_indices"][0] == 0)
    check("尾帧保留", sp["kept_indices"][-1] == len(frames) - 1)
    check("变化处保留", 5 in sp["kept_indices"])
    check("ratio 在 (0,1]", 0 < sp["ratio"] <= 1.0)
    check("短序列不稀疏", eg.sparse_frames([{"a": 1}, {"a": 2}])["dropped"] == 0)
    check("空输入不崩", eg.sparse_frames(None)["dropped"] == 0)
    check("plan_expression 带 sparse", eg.plan_expression(frames, sparse=True)["sparse"] is not None)
    check("plan_expression 默认不稀疏", eg.plan_expression(frames)["sparse"] is None)

    # ── 6. character 多角色批量 ──
    CH = {"name": "林晚", "appearance": "长发红衣"}
    CH2 = {"name": "苏瑶", "appearance": "短发蓝衣"}
    ma = ca.plan_multi_anchor([CH, CH2])
    check("批量建 2 卡且无冲突", ma["count"] == 2 and ma["ok"] is True)
    dup_fp = ca.plan_multi_anchor([CH, dict(CH)])
    check("同指纹 → identical_traits 冲突",
          any(c["type"] == "identical_traits" for c in dup_fp["conflicts"]))
    dup_nm = ca.plan_multi_anchor([CH, {"name": "林晚", "appearance": "完全不同"}])
    check("同名 → duplicate_name 冲突",
          any(c["type"] == "duplicate_name" for c in dup_nm["conflicts"]))
    check("空列表不崩", ca.plan_multi_anchor([])["count"] == 0)
    check("非 dict 项被过滤", ca.plan_multi_anchor([CH, "x", None])["count"] == 1)

    # ── 7. prop 双持武器 ──
    check("dual 握法模板存在", "dual" in pg.GRIP_TEMPLATES)
    dp = pg.build_prop_prompt("sword", grip="dual", hand="dual", off_prop_type="axe")
    check("双持含主武器", "长剑" in dp)
    check("双持含副武器", "战斧" in dp)
    check("双持写明各自结构约束", "单一主干" in dp and "斧柄" in dp)
    pp = pg.plan_prop(prop_type="sword", grip="dual", hand="dual", off_prop_type="axe")
    check("plan_prop 双持 prompt 非空", "战斧" in pp["prompt"])
    single = pg.build_prop_prompt("spear", grip="single_hand", hand="right")
    check("单手描述不含副武器", "副武器" not in single and "长枪" in single)

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
