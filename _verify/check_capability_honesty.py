# -*- coding: utf-8 -*-
"""守卫 ③：能力声明诚实性（P0 · 2026-10-28）。

为什么单独一道
==============
前两道守的是「字段合法」与「账本口径」，都还是**形式**。这一道守的是**内容**：

    **被声明为可用/已验证的东西，必须真的可用。**

它查四件事：
  1. `role=primary` 的引擎，模块必须真实存在（`health != missing`）；
     声称 `verified` 的引擎，其依赖必须真的装得上（`health == ready`）——
     「模块在」和「能跑」是两件事，缺依赖还标 verified 是最常见的假绿。
  2. `K5` 的分子分母必须自洽：`owned ⊆ target`，且 `ratio` 与 `owned` 长度一致。
  3. 带 `step_cache=True` 的引擎必须真有 `inference_cache` 模块在盘上
     （声明了缓存能力却没有实现文件 = 空头支票）。
  4. 每条 `offload_tiers` 都必须能在 `memory_policy._MEASURED` 或引擎源码里
     找到对应实现痕迹 —— 至少不能是 `layer_disk_offload` 这种预告档
     （该档由 `memory_policy.PLANNED_MODES` 显式列出，永不得被声明）。

反例自证：`--selfcheck` 注入一个「缺依赖却标 verified」的假引擎，验证会红。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _check(rows=None) -> list:
    from app.core.neural import capability_manifest as CM
    from app.core.neural import memory_policy as MP

    rows = rows if rows is not None else CM.registrations()
    bad = []
    for r in rows:
        eid = r["id"]
        # ① 主选引擎模块必须在；verified 的引擎依赖必须齐
        if r["role"] == "primary" and r["health"] == "missing":
            bad.append("%s: role=primary 但模块不存在" % eid)
        if r["verified"] == "verified" and r["health"] != "ready":
            bad.append("%s: 声明 verified 但 health=%s（缺 %s）"
                       % (eid, r["health"], r["missing_deps"] or "?"))
        # ③ 声明步缓存 ⇒ 实现文件必须在
        if r["step_cache"] and not os.path.exists(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "app/core/neural/inference_cache.py")):
            bad.append("%s: 声明 step_cache 但 inference_cache.py 不在盘上" % eid)
        # ④ 不许声明预告档
        planned = set(getattr(MP, "PLANNED_MODES", ()))
        leaked = [t for t in r["offload_tiers"] if t in planned]
        if leaked:
            bad.append("%s: offload_tiers 含预告档 %s（未实现却声明 = 假能力）"
                       % (eid, leaked))
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description="能力声明诚实性守卫")
    ap.add_argument("--selfcheck", action="store_true", help="注入假绿，验证会红")
    args = ap.parse_args()

    from app.core.neural import capability_manifest as CM

    cov = CM.coverage()
    print("能力诚实性：K5 %s（owned=%s）" % (cov["ratio"], cov["owned"] or "无"))

    # ② K5 自洽
    bad = []
    if not set(cov["owned"]) <= set(cov["target"]):
        bad.append("K5 owned 不是 target 的子集：%s" % cov["owned"])
    if cov["ratio"].split("/")[0] != str(len(cov["owned"])):
        bad.append("K5 ratio=%s 与 owned=%d 不一致" % (cov["ratio"], len(cov["owned"])))

    bad += _check()

    if args.selfcheck:
        rows = CM.registrations() + [{
            "id": "fake.fake_green", "family": "inference", "capability": "image",
            "role": "primary", "quant": "fp16", "quant_admissible": True,
            "quant_why": "", "offload_tiers": ("layer_disk_offload",),
            "step_cache": True, "verified": "verified", "loop_owner": "upstream",
            "health": "degraded", "missing_deps": ["nonexistent_pkg_xyz"],
        }]
        injected = _check(rows)
        if injected:
            print("✓ 自证通过：注入假绿后报出 %d 条（示例：%s）" % (len(injected), injected[0]))
            return 0
        print("✗ 自证失败：注入假绿后仍全绿 ⇒ 守卫是摆设")
        return 1

    if bad:
        print("✗ 诚实性违约 %d 条：" % len(bad))
        for b in bad:
            print("   - %s" % b)
        return 1
    print("OK 能力声明诚实（0 违约）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
