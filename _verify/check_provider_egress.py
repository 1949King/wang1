#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证「素材不出域」硬约束（SHIGUANG_NO_EGRESS）—— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_provider_egress.py

对照 2026-10-09 补的缺口：
    `provider_caps.resolve_order()` 原本是「优先云端 + local 兜底」，**没有任何
    开关能表达「这一单不许出域」**。客户素材不得离开本机/内网是硬约束，靠
    「记得手工传 provider='local'」是兜不住的。本脚本锁住四件事：

  1. 默认（不设开关）：行为不变（云端优先）——证明**没有**误伤既有链路
  2. SHIGUANG_NO_EGRESS=1：resolve_order() **有且仅有** ["local"]
  3. 开关**优先于显式 provider 参数**（硬约束不可被函数参数绕过）
  4. 显式 provider="local" 只返回一个元素（修掉原来的 ["local","local"] 重复项）
  5. quote() 在开关下报价为 0（不会「锁住不出域却还按云端报价」）
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _load_provider_caps():
    """直接按路径加载 provider_caps.py（它只依赖 stdlib，无相对导入）。"""
    path = os.path.join(ROOT, "app", "core", "ai", "provider_caps.py")
    spec = importlib.util.spec_from_file_location("_sg_provider_caps_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    pc = _load_provider_caps()
    ENV = pc.ENV_NO_EGRESS
    saved = os.environ.pop(ENV, None)

    try:
        # ── 1. 默认行为不变（没有误伤既有链路）──
        check("默认 no_egress() 为 False", pc.no_egress() is False)
        auto_default = pc.resolve_order("auto")
        check("默认 auto 链路包含真实 provider（未误伤）",
              len(auto_default) > 1 and auto_default[-1] == "local")
        check("默认 auto 链路 local 仍在最后", auto_default[-1] == pc.LOCAL_PROVIDER_ID)

        # ── 2. 开关打开 ⇒ 有且仅有 local ──
        os.environ[ENV] = "1"
        check("开开关后 no_egress() 为 True", pc.no_egress() is True)
        auto_ne = pc.resolve_order("auto")
        check("开关下 auto → ['local']", auto_ne == ["local"])

        # ── 3. 开关优先于显式 provider 参数 ──
        for p in ("dashscope", "seedance", "cogvideo", "auto", "local", ""):
            got = pc.resolve_order(p)
            check(f"开关下显式 provider={p!r} 被拦为 ['local']", got == ["local"])

        # 带 priors / lambda_price 也绕不过
        got = pc.resolve_order("seedance", spec={"duration": 5},
                               priors={"seedance": 0.9}, lambda_price=0.0)
        check("开关下带 priors/lambda_price 仍被拦为 ['local']", got == ["local"])

        # 非 load-bearing 但常见的写法：绕开 true/yes/on
        for val in ("true", "TRUE", "yes", "On", " 1 "):
            os.environ[ENV] = val
            check(f"开关值 {val!r} 也识别为开启", pc.no_egress() is True
                  and pc.resolve_order("auto") == ["local"])
        for val in ("0", "false", "", "no", "off", "2"):
            os.environ[ENV] = val
            check(f"开关值 {val!r} 视为关闭", pc.no_egress() is False)

        # ── 4. 修掉 provider='local' 的重复项（回归锁）──
        os.environ.pop(ENV, None)
        got = pc.resolve_order("local")
        check("显式 provider='local' 返回单元素（原为 ['local','local']）",
              got == ["local"])

        # ── 5. 开关下报价为 0（不出域就不该按云端计价）──
        os.environ[ENV] = "1"
        q = pc.quote("auto", count=3, spec={"duration": 5})
        check("开关下 quote() provider 为 local", q.get("provider") == "local")
        check("开关下 quote() 成本为 0", float(q.get("cost_estimate") or 0) == 0.0)
        check("开关下 quote() 降级链只有 local", q.get("fallback_chain") == ["local"])
        check("开关下 quote() tier 为 0", int(q.get("tier") or 0) == 0)

        # ── 6. 默认（关开关）报价仍走云端 —— 证明开关没有把报价一起锁死 ──
        os.environ.pop(ENV, None)
        q2 = pc.quote("auto", count=1, spec={"duration": 5})
        check("默认 quote() 仍按真实 provider 报价（非 local）",
              q2.get("provider") != "local")
    finally:
        os.environ.pop(ENV, None)
        if saved is not None:
            os.environ[ENV] = saved

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
