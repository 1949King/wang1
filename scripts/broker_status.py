# -*- coding: utf-8 -*-
"""资源仲裁体检（只读）：`python scripts/broker_status.py [--json]`。

为什么单独成脚本
================
`resource_broker.describe()` 是产品代码，产品代码不许 `print()`（稳定性门禁 ④）；
而"看一眼现在显存/内存多少、谁能让位"又是排查时最常用的动作。
两者不冲突的做法就是：模块只提供 `describe()`（返回 dict），打印留在脚本里。

本脚本**只读**：不触发让位、不卸载任何模型、不改环境变量。
要看真机让位是否成立，用 `python scripts/verify_broker.py`（会真的卸载一次）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.neural import resource_broker as RB


def main() -> int:
    ap = argparse.ArgumentParser(description="资源仲裁体检（只读）")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON（便于喂给别的脚本）")
    args = ap.parse_args()

    snap = RB.describe()
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return 0

    print("=" * 58)
    print("资源仲裁体检（只读，不让位、不卸载）")
    print("=" * 58)
    print("开关        : %s（SHIGUANG_BROKER=off 可关闭）"
          % ("on" if snap["enabled"] else "OFF"))
    print("安全余量    : ×%.2f" % snap["safety"])

    v = snap["vram_readings"]
    print("\n显存")
    print("  决策用值  : %s" % _fmt(snap["vram_free_gb"]))
    print("  torch     : %s   ← 对本进程之外的占用基本无感，偏乐观" % _fmt(v.get("torch")))
    print("  nvidia-smi: %s   ← 更保守，判据取两者较小值" % _fmt(v.get("smi")))
    if v.get("torch") is not None and v.get("smi") is not None:
        print("  两读数差  : %+.2fGB" % (float(v["torch"]) - float(v["smi"])))

    print("\n内存")
    print("  可用      : %s" % _fmt(snap["ram_free_gb"]))

    print("\n让位来源（按代价升序；代价越小越先让）")
    for s in snap["sources"]:
        print("  · %-18s pool=%-4s 重载代价≈%.1fs  预估=%s"
              % (s["name"], s["pool"], s["cost_s"],
                 "有" if s["has_probe"] else "无（诚实留空）"))
    print("\n要看让位是否真成立：python scripts/verify_broker.py（会真卸载一次）")
    return 0


def _fmt(v):
    return "?" if v is None else "%.2fGB" % float(v)


if __name__ == "__main__":
    raise SystemExit(main())
