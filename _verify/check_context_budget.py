#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 context_budget（模型窗口 → 字符预算）+ compress_messages 兼容性（V4.33.4）。

跑法: python _verify/check_context_budget.py

覆盖：
  1. window_for：最长键优先（"gemini-1.5-pro" 不被 "gemini" 抢先）/ 大小写 / provider 参与 / 未知 → None
  2. chars_budget：8K → 6827（比写死 12000 更保守）· 128K → 149333（放大 12 倍）· 300K → 350000
  3. resolve_max_chars：override > 窗口推导 > 保守默认
  4. describe：诊断字段
  5. **compress_messages 向后兼容**（真 import）：
     * 不传 model ≡ 改造前的 12000（逐字一致）；
     * 显式 max_chars 优先；
     * 传大窗口模型 → 长对话不再被压；传小窗口 → 仍被压。
"""

from __future__ import annotations

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _load(name: str, *parts: str):
    import types
    ai_dir = os.path.join(ROOT, "app", "core")
    pkg = "_sg_core_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    fname = parts[-1]
    modname = fname[:-3] if fname.endswith(".py") else fname
    spec = importlib.util.spec_from_file_location(f"{pkg}.{modname}", os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{pkg}.{modname}"] = mod
    spec.loader.exec_module(mod)
    return mod


def _size(msgs) -> int:
    return sum(len(str(m.get("content") or "")) for m in msgs)


def main() -> int:
    cb = _load("_context_budget", "app", "core", "context_budget.py")

    # ── 1. window_for ──
    check("gpt-4o → 128000", cb.window_for("gpt-4o") == 128000)
    check("gpt-4o-mini → 128000（前缀匹配）", cb.window_for("gpt-4o-mini") == 128000)
    check("最长键优先：gemini-1.5-pro 不被 gemini 抢先",
          cb.window_for("gemini-1.5-pro-latest") == 2097152)
    check("裸 gemini → 32768", cb.window_for("gemini") == 32768)
    check("大小写不敏感", cb.window_for("GPT-4O") == 128000)
    check("provider 也参与匹配", cb.window_for("", "anthropic claude-3-5-sonnet") == 200000)
    check("未知模型 → None", cb.window_for("某不存在模型") is None)
    check("空输入 → None", cb.window_for() is None and cb.window_for("", "") is None)

    # ── 2. chars_budget ──
    check(f"8K → {cb.chars_budget(8192)}（应比写死的 12000 更保守）", cb.chars_budget(8192) == 6826)
    check(f"128K → {cb.chars_budget(128000)}（放大约 12 倍）", cb.chars_budget(128000) == 149333)
    check(f"300K → {cb.chars_budget(300000)}", cb.chars_budget(300000) == 350000)
    check("非法窗口 → 保守默认",
          cb.chars_budget(None) == cb.DEFAULT_MAX_CHARS and cb.chars_budget(0) == cb.DEFAULT_MAX_CHARS)
    check("极小窗口不破下限", cb.chars_budget(100) >= cb.MIN_MAX_CHARS)
    check("窗口越大预算越大", cb.chars_budget(8192) < cb.chars_budget(128000) < cb.chars_budget(300000))

    # ── 3. resolve_max_chars ──
    check("无模型 → 保守默认 12000", cb.resolve_max_chars() == 12000)
    check("gpt-4o → 按窗口推导", cb.resolve_max_chars("gpt-4o") == 149333)
    check("override 优先", cb.resolve_max_chars("gpt-4o", override=30000) == 30000)
    check("override 非法 → 回落窗口", cb.resolve_max_chars("gpt-4o", override="bad") == 149333)
    check("override 负数 → 回落窗口", cb.resolve_max_chars("gpt-4o", override=-1) == 149333)

    # ── 4. describe ──
    d = cb.describe("gpt-4o")
    check("describe 字段完整",
          d["window_tokens"] == 128000 and d["max_chars"] == 149333 and d["known"] is True)
    d2 = cb.describe("某未知")
    check("describe 未知模型回落", d2["known"] is False and d2["max_chars"] == 12000)

    # ── 5. compress_messages 向后兼容（真 import）──
    from app.core.agent_context import compress_messages

    msgs = [{"role": "system", "content": "sys"}]
    for i in range(40):
        msgs.append({"role": "user", "content": ("内容 " + str(i)) * 200})
        msgs.append({"role": "assistant", "content": "回复" * 200})
    raw_size = _size(msgs)
    print(f"    测试消息总量 ≈ {raw_size} 字符")

    out_a = compress_messages(msgs)
    out_a2 = compress_messages(msgs, max_chars=12000)
    check("★ 不传 model ≡ 改造前的 12000（逐字一致）", str(out_a) == str(out_a2))
    check("不传 model 时确实压了（12000 < 总量）", str(out_a) != str(msgs))

    out_b = compress_messages(msgs, max_chars=3000)
    check("显式 max_chars 优先（3000 比 12000 压得更狠）", _size(out_b) < _size(out_a))

    out_c = compress_messages(msgs, model="gpt-4o")
    check("★ 传大窗口模型 → 长对话不再被压（原样返回）", str(out_c) == str(msgs))

    out_d = compress_messages(msgs, model="gpt-4")
    check("传小窗口模型（8K）→ 仍被压", _size(out_d) < raw_size)

    check("空消息不崩", compress_messages([], model="gpt-4o") == [])
    check("model 为 None 不崩", str(compress_messages(msgs, model=None)) == str(out_a))

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
