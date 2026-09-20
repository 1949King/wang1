#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 P1-1 报价 + P1-2 健康（quote / health / remember 预演语义）—— 自包含。

跑法: python _verify/check_quote_health.py

对照任务清单验收标准：
  * P1-1：生成前能看到「预计 ¥X」；零额度账号被跳过
  * P1-2：死号可识别（health），报价/路由不再选它
  * 报价是**只读预演**：不占记账位（remember=False）、不消耗配额
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
    if full in sys.modules:      # 已加载过（如 video_generation_client 依赖链）
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    pc = _load("provider_caps.py")
    pp = _load("provider_pool.py")

    # ════════════ 1. caps.quote（纯声明估算）════════════
    q = pc.quote("auto", count=6)
    check("auto 报价取 tier 首位 seedance", q["provider"] == "seedance")
    check("单价×段数", q["price_per_clip"] == 1.0 and q["cost_estimate"] == 6.0)
    check("币种 CNY + 估算声明", q["currency"] == "CNY" and "估算" in q["note"])
    check("回退链包含 local", q["fallback_chain"][-1] == "local")
    q = pc.quote("cogvideo", count=5)
    check("指定渠道按其单价", q["price_per_clip"] == 0.8 and q["cost_estimate"] == 4.0)
    q = pc.quote("auto", count=3, spec={"first_last_frame": True})
    check("首尾帧 spec → cogvideo 被排除仍报 seedance", q["provider"] == "seedance")
    q = pc.quote("cogvideo", count=3, spec={"first_last_frame": True})
    check("指定不支持渠道 → local ¥0", q["provider"] == "local" and q["cost_estimate"] == 0.0)
    q = pc.quote("local", count=4)
    check("local 免费", q["cost_estimate"] == 0.0)
    q = pc.quote("auto", count=0)
    check("count=0 按 1 段报", q["count"] == 1 and q["cost_estimate"] == 1.0)

    # ════════════ 2. pool.quote（账号视角）════════════
    tmpdir = tempfile.mkdtemp(prefix="sg_quote_test_")

    # 2a. 空池：无账号渠道仍可接单（走环境变量 Key 的场景）
    pool = pp.ProviderPool(store_path=os.path.join(tmpdir, "a.json"))
    q = pool.quote("auto", count=5)
    check("空池 auto → 仍报 seedance（无号不等于死号）",
          q["provider"] == "seedance" and q["cost_estimate"] == 5.0)
    check("空池 → 无账号 id / cloud_available", q["account_id"] == "" and q["cloud_available"])

    # 2b. seedance 死号 + cogvideo 健康号 → 死号跳过、报 cogvideo
    now = 1_000_000.0
    pool_b = pp.ProviderPool(store_path=os.path.join(tmpdir, "b.json"))
    pool_b.add_account("seedance", daily_quota=100, quality_tier=2)
    pool_b.add_account("cogvideo", daily_quota=50, quality_tier=1)
    pool_b.pick("seedance", now=now)                     # 选中以便记失败
    pool_b.report_failure("seedance", error="401", now=now)   # 死号（退避中）
    q = pool_b.quote("auto", count=5, now=now + 1)
    check("死号跳过 → 报 cogvideo", q["provider"] == "cogvideo")
    check("dead_providers 标出 seedance", q["dead_providers"] == ["seedance"])
    check("按 cogvideo 单价重算", q["price_per_clip"] == 0.8 and q["cost_estimate"] == 4.0)
    check("健康号带账号与配额", q["account_id"] != "" and q["quota_remaining"] == 50)

    # 2c. 配额尽 = 死号
    pool_c = pp.ProviderPool(store_path=os.path.join(tmpdir, "c.json"))
    pool_c.add_account("seedance", daily_quota=1)
    pool_c.pick("seedance", now=now)
    pool_c.report_success("seedance", segments=1, now=now)  # 用满
    q = pool_c.quote("auto", count=2, now=now + 1)
    check("零额度账号被跳过（验收标准）", q["provider"] != "seedance")

    # 2d. 显式指定全死渠道 → 回退 local ¥0 + 人话原因
    q = pool_c.quote("seedance", count=2, now=now + 1)
    check("指定死渠道 → local ¥0", q["provider"] == "local" and q["cost_estimate"] == 0.0)
    check("回退原因可读", "回退本地" in q["reason"])

    # 2e. 报价 = 只读预演：不占记账位、不消耗配额
    pool_e = pp.ProviderPool(store_path=os.path.join(tmpdir, "e.json"))
    pool_e.add_account("seedance", daily_quota=10)
    pool_e.pick("seedance", now=now)                      # 正常选中（记账位 = 该号）
    before_pick = dict(pool_e._last_pick)
    before_used = pool_e.list_accounts("seedance")[0]["used_today"]
    q = pool_e.quote("auto", count=3, now=now + 1)
    check("报价不动记账位（remember=False）", pool_e._last_pick == before_pick)
    check("报价不消耗配额", pool_e.list_accounts("seedance")[0]["used_today"] == before_used)
    check("报价结果本身正确", q["provider"] == "seedance" and q["cost_estimate"] == 3.0)

    # 2f. health（P1-2）
    h = pool_c.health("seedance", now=now + 1)
    check("health 反映死号", h["ok"] is False and h["healthy"] == 0 and h["quota_remaining"] == 0)

    # ════════════ 3. client.quote（handler 可用性修正）════════════
    # 伪包加载 video_generation_client（模块级只有 stdlib 导入，可脱离 app 包跑）
    vg = _load("video_generation_client.py")
    client = vg.VideoGenerationClient.get_instance()
    q = client.quote("auto", count=5, duration=5.0)
    # 当前仓库 seedance/cogvideo 封装不存在 → handler 全 None → 与 generate 一致回退 local
    check("handler 全不可用 → 报 local ¥0（与 generate 实际行为一致）",
          q.get("provider") == "local" and q.get("cost_estimate") == 0.0)
    q = client.quote("local", count=5)
    check("local 报价免费", q.get("provider") == "local" and q.get("cost_estimate") == 0.0)
    q = client.quote("auto", count=5, duration=5.0, spec={"first_last_frame": True})
    check("spec 透传不崩", isinstance(q, dict) and q.get("cost_estimate") == 0.0)

    # ════════════ 4. 四处接线（pipeline.quote 能力）════════════
    sys.path.insert(0, ROOT)
    import app.core.agent_capability_catalog as cat
    ids = set(cat.registered_capability_ids())
    check("catalog 已登记 pipeline.quote", "pipeline.quote" in ids)
    row = next((r for r in cat.CAPABILITY_ROWS if r[0] == "pipeline.quote"), None)
    check("catalog 行：read / 不付费 / 左脑", row is not None
          and row[2] == "read" and row[3] is False and row[5] == "left")
    import app.core.agent_action_registry as reg
    a2c = dict(reg.ACTION_TO_CAPABILITY)
    check("对话面 action quote_cost → pipeline.quote",
          a2c.get("quote_cost") == "pipeline.quote")
    check("quote_cost 在白名单", "quote_cost" in set(reg.get_allowed_actions()))
    help_block = reg.build_agent_actions_help_block()
    check("帮助文案含 quote_cost 参数说明", "quote_cost 参数" in help_block)

    # 清理
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
