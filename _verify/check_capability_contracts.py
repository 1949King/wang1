# -*- coding: utf-8 -*-
"""守卫 ①：引擎能力契约（P0 · 2026-10-28）。

守什么
======
`engine_registry` 的 66 条登记必须**全部**带 5 个能力字段，且取值不许编：
  · `loop_owner` 只能是 `shiguang` / `upstream`
  · `verified` 只能是 `verified` / `unverified` / `blocked`（复用 model_family 三态）
  · `offload_tiers` 只能是 `memory_policy` **已实现**的档（不许声明 `layer_disk_offload` 这种预告档）
  · `quant` 必须过 `quant_descriptor.is_admissible()`（主路径推理引擎还必须显式声明）
  · 声称 `loop_owner=shiguang + verified` ⇒ 必须真有 `neural/kernel/loop.py`
  · `role=library-only/retired` 不得声明 `verified`（无入口的能力不算可用）

为什么值得一道门禁
==================
这些字段是「自研引擎自主可控」的**唯一机器可读证词**。它们一旦可以随手填，
`capability_manifest` 的 K5 覆盖率就成了自欺 —— 报 3/4 而实际 0/4，
比不报更糟。所以填错必须当场红灯，而不是等某个报告里被发现。

用法
====
    python _verify/check_capability_contracts.py            # 检查
    python _verify/check_capability_contracts.py --selfcheck  # 注入违约，证明它会红
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _violations() -> list:
    from app.core.neural import capability_manifest as CM

    return CM.violations()


def main() -> int:
    ap = argparse.ArgumentParser(description="引擎能力契约守卫")
    ap.add_argument("--selfcheck", action="store_true",
                    help="注入一条违约，验证守卫真的会红（自证不是摆设）")
    args = ap.parse_args()

    if args.selfcheck:
        from app.core.neural import capability_manifest as CM

        # 注入一个「说循环归自己但没有内核」的假引擎
        orig = CM.registrations

        def _fake():
            rows = orig()
            rows.append({
                "id": "fake.kernel_owner", "family": "inference", "capability": "image",
                "role": "primary", "quant": "fp16", "quant_admissible": True,
                "quant_why": "", "offload_tiers": (), "step_cache": False,
                "verified": "verified", "loop_owner": "shiguang",
                "health": "ready", "missing_deps": [],
            })
            return rows

        CM.registrations = _fake
        bad = _violations()
        CM.registrations = orig
        if not bad:
            print("✗ 自证失败：注入违约后守卫仍然全绿 ⇒ 这道门禁是摆设")
            return 1
        print("✓ 自证通过：注入违约后报出 %d 条（示例：%s）" % (len(bad), bad[0]))
        return 0

    from app.core.neural import capability_manifest as CM

    m = CM.manifest()
    print("引擎能力契约：%d 条登记 ｜ verified %s ｜ loop_owner %s"
          % (m["engines_n"], m["by_verified"], m["by_loop_owner"]))
    cov = m["coverage"]
    print("K5 覆盖率 %s（%s）" % (cov["ratio"], "/".join(cov["target"])))
    bad = m["violations"]
    if bad:
        print("✗ 违约 %d 条：" % len(bad))
        for v in bad:
            print("   - %s" % v)
        return 1
    print("OK 能力契约全部通过（0 违约）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
