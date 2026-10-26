# -*- coding: utf-8 -*-
"""打印加速能力报告：python scripts/accel_report.py [--json]"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.neural import accel_status as AS


def main() -> int:
    st = AS.status()
    if "--json" in sys.argv:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    print("=" * 68)
    print("  加速能力报告（本机实测优先；estimated 项未验证）")
    print("=" * 68)
    print(f"设备：{st['device']['arch']} · {st['device']['vram_gb']}GB")
    hints = AS.install_hint()
    for key in ("fp8", "int4", "compile", "tensorrt"):
        it = st[key]
        mark = "✅ 可用" if it["ok"] else "❌ 不可用"
        print(f"\n[{key}] {mark}")
        print(f"  依赖：{it['lib']}")
        if not it["ok"]:
            print(f"  原因：{it['reason']}")
            print(f"  修复：{hints[key]}")
        print(f"  预期：{it['expected']}")
        m = it.get("measured")
        if m:
            print(f"  实测：speedup={m.get('speedup')} —— {m.get('note')}")
    tk = st.get("torch_kernels") or {}
    print("\n[torch 自带低精度 kernel]")
    for k, v in (tk.get("kernels") or {}).items():
        print(f"  {k}: {v}" + ("  ✅" if v == "ok" else "  ❌（该后端未编译）"))
    print("  说明：hasattr 为 True 不代表能用；本项目实测 torch 2.6.0 Windows 轮子均不可执行。")
    print("\n" + st["honesty"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
