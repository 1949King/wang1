#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 guard_pipeline（守护 ↔ 生成管线适配层）—— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_guard_pipeline.py

覆盖：
  1. make_llm 降级（LLM 不可用 → None）
  2. enhance_prompt 生成前注入（角色卡 / 道具结构 / 表情幅度 + 全量负面词）
  3. augment_inspection 规则层（道具漂移 / 角色漂移）
  4. augment_inspection LLM 层（假 LLM：报问题 / 无问题 / 抛错降级）
  5. revise_hint
  6. run_guard_round 闭环
  7. 脏数据
  8. **管线已接入的静态断言**（execute 有 guards / _gen_prompts 调 enhance_prompt /
     _guard_inspect 存在 / _revise_prompt 有 guard_hint / handler 透传）
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
    gp = _load("_guard_pipeline", "app", "core", "ai", "guard_pipeline.py")

    # ── 1. make_llm 降级 ──
    lm = gp.make_llm()
    check("make_llm 返回 None 或 callable", lm is None or callable(lm))

    # ── 2. enhance_prompt 生成前注入 ──
    base = "a cinematic shot of a warrior"
    r = gp.enhance_prompt(base, guards={
        "character": {"name": "林晚", "appearance": "长发红衣"},
        "prop": {"prop_type": "spear", "grip": "two_hand", "hand": "both"},
        "expression": {"profile": "natural", "emotion": "愤怒"},
    })
    check("增强后 prompt 变长", len(r["prompt"]) > len(base))
    check("注入了 3 段约束", len(r["parts"]) == 3)
    check("含角色名", "林晚" in r["prompt"])
    check("含道具结构约束", "长枪" in r["prompt"])
    check("含表情约束", "表情" in r["prompt"])
    check("返回全量负面词", len(r["negative"]) > 0 and any("三通" in x for x in r["negative"]))
    check("changed=True", r["changed"] is True)

    r2 = gp.enhance_prompt(base, guards=None)
    check("无 guards → 原样不改", r2["prompt"] == base and r2["changed"] is False)
    check("无 guards 仍返回负面词", len(r2["negative"]) > 0)
    check("空 prompt 不崩", gp.enhance_prompt("", guards={"prop": {"prop_type": "sword"}})["prompt"].startswith(" |") is False)

    # ── 3. augment_inspection 规则层 ──
    prop = {"prop_type": "spear", "prop_color": "银白"}
    anchor = {"traits": {"prop_type": "spear", "prop_color": "银白"}, "fingerprint": "abc123"}
    a_ok = gp.augment_inspection("p", guards={"prop": prop}, anchor=anchor, use_llm=False)
    check("道具未漂移 → ok", a_ok["ok"] is True and a_ok["layers"]["rule"] is True)

    a_drift = gp.augment_inspection(
        "p", guards={"prop": dict(prop, prop_color="暗红")}, anchor=anchor, use_llm=False)
    check("道具漂移 → 报问题", a_drift["ok"] is False
          and any("道具" in x for x in a_drift["issues"]))

    ch_anchor = {"traits": {"name": "林晚", "appearance": "长发红衣"}, "fingerprint": "def456"}
    a_cd = gp.augment_inspection(
        "p",
        guards={"character": {"name": "林晚", "appearance": "短发蓝衣"},
                "character_anchor": ch_anchor},
        use_llm=False,
    )
    check("角色漂移 → 报问题", a_cd["ok"] is False
          and any("角色" in x for x in a_cd["issues"]))

    a_noanchor = gp.augment_inspection("p", guards={"character": {"name": "林晚"}}, use_llm=False)
    check("无锚定卡 → 不误报", a_noanchor["ok"] is True)

    # ── 4. augment_inspection LLM 层 ──
    def fake_llm(prompt: str) -> str:
        return '{"issues": ["武器出现多余分支"], "suggestion": "移除多余分支"}'

    a_llm = gp.augment_inspection("p", guards={}, llm=fake_llm, use_llm=True)
    check("LLM 层报问题", a_llm["ok"] is False and "武器出现多余分支" in a_llm["issues"])
    check("LLM 层已标记执行", a_llm["layers"]["llm"] is True)
    check("suggestion 透传", a_llm["suggestion"] == "移除多余分支")

    def good_llm(prompt: str) -> str:
        return '{"issues": [], "suggestion": ""}'

    check("LLM 未报问题 → ok", gp.augment_inspection("p", guards={}, llm=good_llm)["ok"] is True)

    def bad_llm(prompt: str) -> str:
        raise RuntimeError("模拟 LLM 挂掉")

    a_bad = gp.augment_inspection("p", guards={}, llm=bad_llm, use_llm=True)
    check("LLM 抛错 → 降级不崩", a_bad["ok"] is True and a_bad["layers"]["llm"] is False)

    a_badjson = gp.augment_inspection("p", guards={}, llm=lambda _: "完全不是 JSON")
    check("LLM 返回非 JSON → 降级", a_badjson["ok"] is True)

    check("use_llm=False 不调 LLM", gp.augment_inspection("p", guards={}, use_llm=False)["layers"]["llm"] is False)

    # ── 5. revise_hint ──
    check("revise_hint 拼多个问题", gp.revise_hint(["问题A", "问题B"]) == "问题A；问题B")
    check("revise_hint 无问题时透传 suggestion", gp.revise_hint([], "建议X") == "建议X")
    check("revise_hint 全空 → 空", gp.revise_hint([]) == "")
    check("revise_hint 脏输入不崩", gp.revise_hint(None) == "")

    # ── 6. run_guard_round 闭环 ──
    rr = gp.run_guard_round("prompt", guards={"prop": {"prop_type": "spear"}}, use_llm=False)
    check("闭环返回 prompt+negative+inspection",
          bool(rr["prompt"]) and bool(rr["negative"]) and rr["inspection"] is not None)
    check("闭环含 message", bool(rr["message"]))

    # ── 7. 脏数据 ──
    check("guards 非 dict 不崩", gp.enhance_prompt("x", guards="bad")["prompt"] == "x")
    check("augment 空 guards 不崩", gp.augment_inspection("p", guards=None, use_llm=False)["ok"] is True)

    # ── 8. 管线已接入（静态断言）──
    src = _read("app", "core", "ai_video_generation_pipeline.py")
    check("管线 execute 有 guards 参数", "guards: Optional[Dict[str, Any]] = None" in src)
    check("管线 _gen_prompts 接收 guards", "def _gen_prompts(self, keywords: Dict[str, List[str]], scene_count: int,\n                     guards: Optional[Dict[str, Any]] = None)" in src)
    check("管线调 enhance_prompt", "_apply_guard_to_prompt" in src and "guard_pipeline import enhance_prompt" in src)
    check("管线 _guard_inspect 存在", "def _guard_inspect" in src)
    check("管线 _revise_prompt 有 guard_hint", "guard_hint" in src)
    check("管线初检后叠加守护质检", "self._guard_inspect(current_prompt, guards)" in src)
    h_src = _read("app", "core", "capability_handlers.py")
    check("handler generate 透传 guards", "guards=g if isinstance(g, dict) else None" in h_src)

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
