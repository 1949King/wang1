#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 provider_pool（P0-1 额度池调度）—— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_provider_pool.py

对照任务清单验收标准：
  1. 必失败假号 + 能成功假号 → 失败后 pick 自动换号
  2. daily_quota=1 → 用过一次后不再被选中
  3. 连续失败 3 次 → cooling，pick 不再返回它；指数退避 60/120/240 封顶 1800
  4. 重启（新实例同路径）→ used_today 保持（持久化）
  5. 审计日志有选号理由
  6. reorder_providers：有健康账号的排前 / local 永远最后 / 空池透传
  7. credential 接口只回掩码
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _load(fname: str):
    """加载 app/core/ai 下的模块（伪包方式，使相对导入可用且不 import app 包）。"""
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    modname = fname[:-3]
    full = f"{pkg}.{modname}"
    spec = importlib.util.spec_from_file_location(full, os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    pp = _load("provider_pool.py")

    tmpdir = tempfile.mkdtemp(prefix="sg_pool_test_")
    store = os.path.join(tmpdir, "accounts.json")

    # ── 1. 换号：必失败 + 能成功 ──
    pool = pp.ProviderPool(store_path=store)
    bad = pool.add_account("seedance", credential="bad_key_ref", daily_quota=100,
                           quality_tier=2)
    good = pool.add_account("seedance", credential="good_key_ref", daily_quota=100,
                            quality_tier=1)
    first = pool.pick("seedance")
    check("tier 高的先被选", first is not None and first["account_id"] == bad["account_id"])
    nxt = pool.pick_next_after_failure("seedance", error="401 unauthorized")
    check("失败后当场换号", nxt is not None and nxt["account_id"] == good["account_id"])
    pool.report_success("seedance", segments=3)
    # 注意：report_success 记到「本轮选中」的 good 上（pick_next 已更新 last_pick）
    rows = {r["account_id"]: r for r in pool.list_accounts("seedance")}
    check("成功记账到换号后的账号",
          rows[good["account_id"]]["used_today"] == 3)
    check("失败号进入 cooling", rows[bad["account_id"]]["health"] == "cooling")

    # ── 2. 退避：指数 60→120→240，封顶 1800 ──
    pool2 = pp.ProviderPool(store_path=os.path.join(tmpdir, "b.json"))
    a = pool2.add_account("cogvideo", daily_quota=100)
    now = 1_000_000.0
    pick1 = pool2.pick("cogvideo", now=now)
    check("能选中", pick1 is not None)
    cds = []
    for i in range(6):
        pool2.report_failure("cogvideo", error="x", now=now + i)
        acct = [r for r in pool2.list_accounts("cogvideo")][0]
        cds.append(acct["cooldown_until"] - now - i)
    check("退避序列 60/120/240/480/960/1800（封顶）",
          [round(c) for c in cds] == [60, 120, 240, 480, 960, 1800])
    check("连续失败 3 次后 pick 不再返回它",
          pool2.pick("cogvideo", now=now + 10) is None)
    check("退避期满自动恢复",
          pool2.pick("cogvideo", now=now + 61 * 60) is not None)

    # ── 3. 配额：daily_quota=1 用一次后不再选 ──
    pool3 = pp.ProviderPool(store_path=os.path.join(tmpdir, "c.json"))
    q1 = pool3.add_account("cogvideo", daily_quota=1)
    pool3.pick("cogvideo", now=now)
    pool3.report_success("cogvideo", segments=1, now=now)
    check("配额=1 用过后 pick 不再选", pool3.pick("cogvideo", now=now + 5) is None)
    h = pool3.health("cogvideo", now=now + 5)
    check("health 反映配额耗尽", h["ok"] is False and h["quota_remaining"] == 0)

    # ── 4. 持久化：新实例同路径 used_today 保持 ──
    pool4 = pp.ProviderPool(store_path=os.path.join(tmpdir, "c.json"))
    rows4 = pool4.list_accounts("cogvideo")
    check("重启后账号仍在", len(rows4) == 1)
    check("重启后 used_today 保持", rows4[0]["used_today"] == 1)
    check("持久化文件存在", os.path.exists(os.path.join(tmpdir, "c.json")))

    # ── 5. 审计日志 ──
    audit = pool3.audit()
    pick_logs = [x for x in audit if x["event"] in ("pick", "pick_miss", "failure")]
    check("审计有选号/失败记录", len(pick_logs) >= 2)
    check("审计有理由字段", all(str(x.get("reason") or "") for x in pick_logs))

    # ── 6. reorder_providers ──
    pool6 = pp.ProviderPool(store_path=os.path.join(tmpdir, "d.json"))
    check("空池 → 透传不改顺序",
          pool6.reorder_providers(["seedance", "cogvideo", "local"])
          == ["seedance", "cogvideo", "local"])
    pool6.add_account("cogvideo", daily_quota=50, quality_tier=2)
    reordered = pool6.reorder_providers(["seedance", "cogvideo", "local"])
    check("有健康账号的 provider 排前 + local 永远最后",
          reordered == ["cogvideo", "seedance", "local"])

    # ── 7. 组合路由（P0-3 + P0-1）──
    # duration=8 双渠道都存活 → 能力筛过后再被池重排（cogvideo 有号 → 排前）
    combined = pool6.resolve_order("auto", spec={"duration": 8.0})
    check("组合路由：能力筛选 + 池内重排",
          combined == ["cogvideo", "seedance", "local"])

    # ── 8. credential 掩码 ──
    masked = pool.list_accounts("seedance")
    check("接口只回掩码", all("bad_key_ref" not in str(r["credential"])
                              and "good_key_ref" not in str(r["credential"])
                              for r in masked))

    # 清理临时目录
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

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
