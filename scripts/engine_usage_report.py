# -*- coding: utf-8 -*-
"""引擎使用报告（W1）—— 让「谁空着」变成数据，而不是感觉。

用法：
    python scripts/engine_usage_report.py          # 人类可读
    python scripts/engine_usage_report.py --json   # 机器可读

口径：
  · 用量只来自 data/engine_telemetry.json（真实执行计数）；
  · **未埋点的引擎不判 0 调用**（显示「未埋点」），避免冤枉；
  · 退出码恒 0（这是报告不是门禁）；要门禁用 --fail-on-idle。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# 脚本直跑时 sys.path[0] 是 scripts/，需要把仓库根加进来
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import engine_registry as reg


def _fmt_ts(ts: float) -> str:
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def main() -> int:
    parser = argparse.ArgumentParser(description="引擎使用报告")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--fail-on-idle", action="store_true", help="有 0 调用引擎时退出码 1")
    args = parser.parse_args()

    s = reg.status()
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0

    print("== 引擎注册表 ==")
    print("总计 %d · 族 %d" % (s["total"], len(s["families"])))
    print("角色：" + " · ".join("%s=%d" % (k, v) for k, v in s["by_role"].items() if v))
    print("健康：" + " · ".join("%s=%d" % (k, v) for k, v in s["by_health"].items() if v))
    print()
    print("%-28s %-10s %-12s %-8s %-7s %s" % ("id", "family", "role", "health", "calls", "last"))
    for v in s["engines"]:
        u = v.get("usage")
        calls = "—" if u is None else str(u.get("calls") or 0)
        last = "未埋点" if u is None else _fmt_ts(float(u.get("last_ts") or 0.0))
        print("%-28s %-10s %-12s %-8s %-7s %s"
              % (v["id"], v["family"], v["role"], v["health"], calls, last))

    idle = [v for v in s["engines"]
            if v.get("usage") is not None and int(v["usage"].get("calls") or 0) == 0]
    lib = [v for v in s["engines"] if v["role"] == reg.ROLE_LIBRARY]
    retired = [v for v in s["engines"] if v["role"] == reg.ROLE_RETIRED]
    print()
    print("== 空着清单 ==")
    print("0 调用（已埋点）：" + ("、".join(v["id"] for v in idle) or "无"))
    print("库内能力（无入口，不算可用）：" + ("、".join(v["id"] for v in lib) or "无"))
    print("待清理（零调用候选）：" + ("、".join(v["id"] for v in retired) or "无"))

    if args.fail_on_idle and idle:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
