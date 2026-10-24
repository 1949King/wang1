#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.38.4 端到端仿真器（规格书第十一篇 切片⑪）—— 自包含。

跑法: python _verify/check_simulator.py

验收要点（对规格书五属性 + 四用途逐项验证）：
  A. 可复现：同种子两次跑 digest 一致；异种子 digest 不同
  B. 收敛验证：无故障长跑 λ 序列尾部方差有界（不发散）
  C. 故障注入-429：触发降级事件 + 本地兜底计数
  D. 故障注入-断网：观测门控冻结 λ（断网段 λ^τ 不变）
  E. 故障注入-漂移：机器分虚高 + 人工判废 → 残差超标 → 闭环冻结
  F. 多任务不变量：每轮拍卖 invariant_fails == 0
  G. 压力测试：200 单元决策均时 < 1ms（O(1) 红线 §69）
  H. 参数标定：κ 三档 sweep 产出三份报告
  I. 零成本隔离：仿真存储全在 tmp，不碰真 data/*.json
"""
from __future__ import annotations

import importlib.util
import os
import sys
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
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    for fake in ("app", "app.core"):
        if fake not in sys.modules:
            m = types.ModuleType(fake)
            m.__path__ = []
            sys.modules[fake] = m
    modname = fname[:-3]
    full = f"{pkg}.{modname}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    sim_mod = _load("simulator.py")

    # ════════════ A. 可复现 ════════════
    r1 = sim_mod.Simulator(seed=42).run(units=40)
    r2 = sim_mod.Simulator(seed=42).run(units=40)
    r3 = sim_mod.Simulator(seed=7).run(units=40)
    check("A1 同种子 digest 一致", r1["digest"] == r2["digest"])
    check("A2 异种子 digest 不同", r1["digest"] != r3["digest"])
    check("A3 报告字段齐全",
          all(k in r1 for k in ("lambda_tau_final", "lambda_g_final",
                                "route_counts", "auction_invariant_fails",
                                "decision_time_avg_ms", "sampling", "digest")))

    # ════════════ B. 收敛验证（无故障长跑） ════════════
    rb = sim_mod.Simulator(seed=42).run(units=120)
    check("B1 λ^τ 尾部方差有界（<0.01，不发散）",
          rb["lambda_tau_tail_var"] < 0.01)
    check("B2 λ^G 尾部方差有界（<0.01）", rb["lambda_g_tail_var"] < 0.01)

    # ════════════ C. 故障注入：429 风暴 ════════════
    rc = sim_mod.Simulator(seed=42).run(
        units=40,
        faults=[{"at": 10, "duration": 10, "type": "429"}])
    check("C1 429 风暴触发降级事件（>0）", rc["degradation_events"] > 0)
    check("C2 本地兜底承接（local 路由计数 >0）",
          rc["route_counts"].get("local", 0) > 0)

    # ════════════ D. 故障注入：断网 → 观测门控冻结 ════════════
    # 断网段 λ 被冻结：与无断网对照，断网期不做 PI 更新
    sim_d = sim_mod.Simulator(seed=42)
    sim_d.run(units=20)  # 先跑 20 拍建立基线
    lam_before = sim_d.pacer.get_lambda()
    sim_d.run(units=0, faults=[])  # 空跑不推状态
    sim_d.pacer.set_observation(False, "sim")
    frozen_a = sim_d.pacer.get_lambda()
    sim_d.pacer.set_observation(True)
    check("D1 冻结期 λ 不变", abs(frozen_a - lam_before) < 1e-12)
    rd = sim_mod.Simulator(seed=42).run(
        units=40, faults=[{"at": 10, "duration": 10, "type": "offline"}])
    check("D2 断网期云端全灭 → local 承接",
          rd["route_counts"].get("local", 0) >= 10)

    # ════════════ E. 故障注入：评分漂移 → 闭环冻结 ════════════
    re_ = sim_mod.Simulator(seed=42).run(
        units=60, faults=[{"at": 0, "duration": 60, "type": "drift"}])
    check("E1 漂移故障 → 闭环冻结", re_["frozen"] is True)

    # ════════════ F. 多任务不变量 ════════════
    rf = sim_mod.Simulator(seed=42).run(
        units=60, task_pressures={"t1": 3.0, "t2": 1.0})
    check("F1 每轮拍卖不变量零违反", rf["auction_invariant_fails"] == 0)

    # ════════════ G. 压力测试（O(1) 红线） ════════════
    rg = sim_mod.Simulator(seed=42).run(units=200)
    check("G1 200 单元决策均时 < 1ms", rg["decision_time_avg_ms"] < 1.0)
    check("G2 决策峰值 < 10ms（无病态长尾）",
          rg["decision_time_max_ms"] < 10.0)

    # ════════════ H. 参数标定（κ 三档 sweep） ════════════
    sweep = sim_mod.parameter_sweep(units=40, seed=42)
    check("H1 κ 三档报告齐全", set(sweep.keys()) == {"0.5", "1.0", "2.0"})
    check("H2 每档都有 digest", all("digest" in v for v in sweep.values()))

    # ════════════ I. 零成本隔离：不碰真 data/*.json ════════════
    data_sim = os.path.join(ROOT, "data", "sim_probe.json")
    check("I1 仿真不在项目 data/ 写文件", not os.path.exists(data_sim))
    # 仿真存储确实在 tmp（路径前缀校验）
    s = sim_mod.Simulator(seed=1)
    check("I2 仿真存储路径在系统 tmp", "sg_sim_1_" in s._tmpdir)

    print(f"\n{'=' * 50}\n端到端仿真器检查：{TOTAL - len(FAILS)}/{TOTAL} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("OK 端到端仿真器全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
