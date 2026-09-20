#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 pipeline.tts_polish（TTS 正音守护）—— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_tts_guard.py

覆盖本能力**独有风险面**（不止「函数能跑」）：
  1. 切段不丢字（拼接去空白 == 原文去空白）+ 每段 ≤ 上限
  2. 边界/脏数据（空、纯空白、单字、None、无标点超长）
  3. 多音字注音（假 LLM 注入）+ SSML 产出
  4. LLM 缺失 / 抛错 / 返回非 JSON → 诚实降级不崩
  5. 回读质检能定位需重生成的段（含长度不齐）
  6. 四处接线静态断言（catalog / handler / action 白名单 / 帮助文案）

说明：为保证「真代码」且不拉起 Qt/硬件探测，本脚本按**文件路径**加载
tts_guard（纯标准库模块），接线检查用**源码静态断言**；
真正的 dispatcher 级一致性由 `_verify/run_all_checks.py` 的 AGENTMAP 用例覆盖。
"""

from __future__ import annotations

import importlib.util
import os
import re
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
    """加载 app/core/ai 下的模块。

    用「伪包」方式注册：既让包内相对导入（``from .guard_base import ...``）可用，
    又**不会**把 ``app`` 包拉进来（避免触发 config_manager 的硬件探测）。
    """
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


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main() -> int:
    tg = _load("_tts_guard", "app", "core", "ai", "tts_guard.py")

    # ── 1. 切段：不丢字 + 不超长 ──
    samples = [
        "她走了。他还在等。",
        "他说：\"你到底想怎么样？\"她没有回答，只是转身离开。",
        "银行的行长在重庆考察，顺便去了长江大桥。",
        "我今天很开心！你呢？",
        "无标点超长文本无标点超长文本" * 20,
    ]
    for t in samples:
        segs = tg.segment_text(t)
        tag = t[:10]
        check(f"切段不丢字 [{tag}…]", norm("".join(segs)) == norm(t))
        check(f"每段≤40 [{tag}…]", all(len(s) <= 40 for s in segs))
        check(f"切段非空 [{tag}…]", len(segs) >= 1)

    # ── 2. 边界 / 脏数据 ──
    check("空文本 → []", tg.segment_text("") == [])
    check("纯空白 → []", tg.segment_text("   \n ") == [])
    check("单字不崩", tg.segment_text("好") == ["好"])
    check("None 不崩", tg.segment_text(None) == [])
    check("自定义 max_chars 生效", all(len(s) <= 12 for s in tg.segment_text(samples[4], 12)))

    # ── 3. 注音：假 LLM 注入 ──
    def fake_llm(prompt: str) -> str:
        return '[{"word":"重庆","char":"重","pinyin":"chóng","reason":"地名"}]'

    plan = tg.plan_tts("我们去了重庆。", llm=fake_llm)
    check("plan_tts 非空", plan["ok"] and plan["segment_count"] >= 1)
    check("plan_tts 标注了多音字", plan["polyphone_total"] >= 1)
    check("产出 SSML phoneme", any("<phoneme" in s["annotated"] for s in plan["segments"]))

    # ── 4. LLM 缺失 / 抛错 / 返回非 JSON → 诚实降级 ──
    plan2 = tg.plan_tts("我们去了重庆。", llm=None)
    check("LLM=None 仍可切段", plan2["ok"] and plan2["used_llm"] is False)

    def boom(prompt: str) -> str:
        raise RuntimeError("模拟 LLM 挂掉")

    plan3 = tg.plan_tts("我们去了重庆。", llm=boom)
    check("LLM 抛错 → 降级不崩", plan3["ok"] and plan3["polyphone_total"] == 0)

    def garbage(prompt: str) -> str:
        return "这不是 JSON，随便写的"

    plan4 = tg.plan_tts("我们去了重庆。", llm=garbage)
    check("LLM 返回非 JSON → 降级", plan4["ok"] and plan4["polyphone_total"] == 0)

    # ── 5. 拼音 / SSML 工具 ──
    check("声调符号→SAPI", tg._to_sapi_pinyin("chóng") == "chong2")
    check("数字式原样", tg._to_sapi_pinyin("chong2") == "chong2")
    check("空拼音→空", tg._to_sapi_pinyin("") == "")
    ssml = tg.build_ssml("重庆很美", [{"word": "重庆", "char": "重", "pinyin": "chóng"}])
    check("build_ssml 含 phoneme + speak", "<phoneme" in ssml and ssml.startswith("<speak>"))
    check("build_ssml 空输入原样", tg.build_ssml("abc", []) == "abc")
    check("build_ssml 无匹配项原样", tg.build_ssml("abc", [{"word": "xyz", "pinyin": "x"}]) == "abc")

    # ── 6. 回读质检 ──
    r = tg.diff_readback("她走了他还在等", "她走了，他还在等。")
    check("标点差异不算错（相似度高）", r["ok"] and r["similarity"] >= 0.9)
    r2 = tg.diff_readback("她走了他还在笑", "她走了，他还在等。")
    check("内容不符被判错/降分", (not r2["ok"]) or r2["similarity"] < 1.0)
    r3 = tg.diff_readback("", "原文")
    check("空回读判错不崩", r3["ok"] is False and r3["similarity"] == 0.0)

    vs = tg.verify_segments(["第一句", "第二句错了"], ["第一句", "第二句"])
    check("verify_segments 定位重试段", vs["retry_indices"] == [1] and not vs["ok"])
    vs2 = tg.verify_segments(["甲乙丙"], ["甲乙丙", "丁"])
    check("长度不齐 → 多出的段重试", 1 in vs2["retry_indices"])
    vs3 = tg.verify_segments(["甲", "乙"], ["甲", "乙"])
    check("全对 → ok + 无重试", vs3["ok"] and vs3["retry_indices"] == [])

    # ── 7. 四处接线（静态断言，不 import app）──
    cat_src = _read("app", "core", "agent_capability_catalog.py")
    check("接线1 catalog 含 pipeline.tts_polish", '"pipeline.tts_polish"' in cat_src)
    h_src = _read("app", "core", "capability_handlers.py")
    check("接线2 handlers 含 def tts_polish", "def tts_polish" in h_src)
    check("接线2 handlers 含 register", 'dispatcher.register("pipeline.tts_polish"' in h_src)
    a_src = _read("app", "core", "agent_action_registry.py")
    check("接线3 action 白名单含 tts_polish", '"tts_polish"' in a_src)
    check("接线3 映射到 pipeline.tts_polish", '"pipeline.tts_polish"' in a_src)
    check("接线4 帮助文案含参数说明", "tts_polish 参数" in a_src)

    # ── 汇总 ──
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} / {TOTAL}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print(f"ALL PASS ({TOTAL} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
