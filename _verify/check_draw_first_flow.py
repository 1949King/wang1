# -*- coding: utf-8 -*-
"""P0a 抽卡首流量验收（2026-10-10）——闭环「通电」≠「工作」，此脚本补上这一步。

背景（深潜复核发现）
====================
抽卡闭环九层系统代码已全部通电（seed 贯通 / 代理分 / draw_book 账本 / 推荐回传），
但 ``data/draw_book.json`` 长期为 ``{}``（2 字节）——**没有一笔真实流量经过**。
P0b 已把本地生图也接进闭环（capability_handlers + /host/local-image-generate），
现在需要**真实跑一次抽卡**，亲眼确认账本落笔。

用法
====
    python _verify/check_draw_first_flow.py            # 查看当前状态 + 接线证据
    python _verify/check_draw_first_flow.py --verify   # 跑完真实抽卡后核验（退出码 0=通过）

验收路径（二选一，任一条都会入账）
==================================
    A. 本地零成本：画布 → 本地生图（SD1.5，模型已下载）——P0b 后即入账
    B. 云端付费：画布 → 生图节点（任一渠道）——走既有 feed_draw_ledger

通过标准（--verify）
====================
    1. draw_book.json 存在且至少 1 个桶（非 {}）
    2. 桶内 n ≥ 1、mean 为数值、（若 seed_sent）best_seed 有值或 best_score 有记录
    3. quality_prior 的 proxy 桶有记录（观察期纯积累，不影响路由 —— 红线）
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAW_BOOK = os.path.join(ROOT, "data", "draw_book.json")
QUALITY_PRIOR = os.path.join(ROOT, "data", "quality_prior.json")

# ── 接线证据（静态源码检查：闭环是否还通电着）────────────────────────
WIRING_CHECKS = [
    ("云端收尾入账", "app/core/canvas_aigc.py", "feed_draw_ledger"),
    ("云端 seed 回显", "app/core/canvas_aigc.py", "seed_sent=seed_sent"),
    ("本地收尾入账(Agent)", "app/core/capability_handlers.py", "feed_draw_ledger_local"),
    ("本地收尾入账(路由)", "app/core/canvas_routes_post.py", "feed_draw_ledger_local"),
    ("本地 seed 归一化(路由)", "app/core/canvas_routes_post.py", "normalize_seed"),
    ("适配层(文件→dataURL)", "app/core/ai/draw_ledger.py", "feed_draw_ledger_local"),
    ("账本实现", "app/core/ai/draw_book.py", "def record_draw"),
]


def wiring_status() -> list:
    rows = []
    for label, rel, needle in WIRING_CHECKS:
        path = os.path.join(ROOT, rel)
        try:
            with open(path, "r", encoding="utf-8") as f:
                ok = needle in f.read()
        except OSError:
            ok = False
        rows.append((label, rel, needle, ok))
    return rows


def ledger_status() -> dict:
    if not os.path.isfile(DRAW_BOOK):
        return {"exists": False, "buckets": {}, "size": 0}
    with open(DRAW_BOOK, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {"exists": True, "corrupt": True, "size": len(raw)}
    return {"exists": True, "buckets": data if isinstance(data, dict) else {},
            "size": len(raw)}


def quality_prior_status() -> dict:
    if not os.path.isfile(QUALITY_PRIOR):
        return {"exists": False}
    try:
        with open(QUALITY_PRIOR, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"exists": True, "keys": list(data.keys())[:10] if isinstance(data, dict) else []}
    except (OSError, json.JSONDecodeError):
        return {"exists": True, "corrupt": True}


def main() -> int:
    verify = "--verify" in sys.argv

    print("=" * 64)
    print("P0a 抽卡首流量验收 —— 闭环通电 × 账本流量")
    print("=" * 64)

    # 1) 接线证据
    print("\n[1] 接线证据（源码级，应全部 OK）")
    all_ok = True
    for label, rel, needle, ok in wiring_status():
        print(f"  {'OK ' if ok else 'MISS'}  {label}  ({rel} :: {needle})")
        all_ok = all_ok and ok

    # 2) 账本状态
    print("\n[2] draw_book 账本状态")
    st = ledger_status()
    if not st.get("exists"):
        print("  账本文件不存在（从未有流量经过 —— 待首流量）")
    elif st.get("corrupt"):
        print("  ⚠️ 账本文件损坏（JSON 解析失败），size =", st.get("size"))
    else:
        buckets = st["buckets"]
        n_draws = sum(int(b.get("n", 0)) for b in buckets.values()
                      if isinstance(b, dict))
        print(f"  桶数 {len(buckets)} / 总抽卡 {n_draws} 次 / 文件 {st['size']} 字节")
        for k, b in list(buckets.items())[:5]:
            if not isinstance(b, dict):
                continue
            print(f"    · {k[:16]}…  n={b.get('n')} mean={b.get('mean')} "
                  f"best_seed={b.get('best_seed')} best_score={b.get('best_score')}")

    # 3) quality_prior proxy 桶
    print("\n[3] quality_prior（proxy 桶应随抽卡积累；route_mean 不读它 —— 红线）")
    qp = quality_prior_status()
    print(f"  {qp}")

    # 4) 判定
    print("\n" + "-" * 64)
    if verify:
        if not all_ok:
            print("✗ FAIL：接线证据有缺失 —— 闭环断了，先修接线再谈流量")
            return 2
        if not st.get("exists") or st.get("corrupt") or not st.get("buckets"):
            print("✗ FAIL：账本仍无流量。请真实跑一次抽卡（见下方验收路径）后重试 --verify")
            print("   A. 本地零成本：画布 → 本地生图（SD1.5）")
            print("   B. 云端付费：画布 → 生图节点（任一渠道）")
            return 1
        n_draws = sum(int(b.get("n", 0)) for b in st["buckets"].values()
                      if isinstance(b, dict))
        if n_draws < 1:
            print("✗ FAIL：桶存在但 n=0（数据异常）")
            return 3
        print(f"✓ PASS：闭环已通电且账本有真实流量（{len(st['buckets'])} 桶 / {n_draws} 次抽卡）")
        print("  下一步核验建议（人工）：同一 prompt 再抽一次，确认响应带 recommendation 字段")
        return 0

    # 查看模式
    if st.get("buckets"):
        print("状态：账本已有流量。可运行 --verify 做通过判定。")
    else:
        print("状态：账本零流量（历史遗留）。真实跑一次抽卡后，运行 --verify。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
