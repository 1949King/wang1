#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.38.1 L0 全局价格层 + 配额拍卖 + 观测门控（规格书 §2/§33/§35/§39-41
切片⑧）—— 自包含。

跑法: python _verify/check_global_price.py

验收要点：
  A. L0 误差与方向：超支 → λ^G 升；初始 λ^G=0
  B. 变化率限制：单步 |Δλ^G| ≤ 0.1（§41 第三件套）
  C. 积分主导：Kp<Ki 配置 + 撞界冻结积分
  D. 观测门控：冻结期不更新；恢复首拍只建基线（L0 与 L1 两层同语义）
  E. 配额拍卖：高压优先 / 欠账扣款 / 关键任务保底 / 永久不变量 Σ≤剩余
  F. λ_eff 叠加：client 选路用 λ^G+λ^τ（L0 升高直接改变路由排序）
  G. 跨月结转：账单重置 + λ^G 指数回退
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []
TOTAL = 0

# 临时目录钉到项目内 .workbuddy/tmp（2026-09-28）：沙箱拦截系统 Temp 写入 →
# tempfile 回退到 cwd（项目根），直接单跑本脚本会把 sg_gp_test_* 漏进仓库根。
# 规范入口 run_all_checks.py 已通过 TMPDIR 传递修好；此处覆盖「直接单跑」路径。
try:
    _TMP_BASE = os.path.join(ROOT, ".workbuddy", "tmp")
    os.makedirs(_TMP_BASE, exist_ok=True)
    tempfile.tempdir = _TMP_BASE
except OSError:
    pass


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def over_paced_spend(budget: float, month_progress: float, margin: float = 5.0) -> float:
    """返回一个「任何日期都判超支」的花费额。

    为什么需要（2026-09-28 修日期炸弹）：λ^G 的超支判据是
    `left - max(0.02, 1 - 本月已过比例)`，即拿「剩余预算比例」比「本月剩余时间比例」。
    原先用例硬编码 `record_spend(90.0)`（预算 100）——只有当本月已过比例 < 0.90 时
    才判超支；**一过每月约 90% 就必然失败**（实测 09-27 19:00 通过、09-28 01:00 变红）。
    改为按当月进度反推：花掉「本月应花额度 + margin」，任何日期都稳定超支。
    封顶到 budget 仍成立：此时 left=0，而判据下界 max(0.02,·) ≥ 0.02 ⇒ e ≤ −0.02 < 0。
    """
    return min(budget, budget * month_progress + margin)


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
    tmpdir = tempfile.mkdtemp(prefix="sg_gp_test_")
    gp = _load("global_price.py")
    bp = _load("budget_pacer.py")

    # ════════════ A. L0 误差与方向 ════════════
    g = gp.GlobalPriceController(monthly_budget=100.0,
                                 store_path=os.path.join(tmpdir, "a.json"),
                                 update_interval=1)
    check("A1 初始 λ^G=0（无压力不加价）", abs(g.get_lambda()) < 1e-12)
    # 按当月进度反推花费，保证任何日期都判超支（见 over_paced_spend 说明）
    g.record_spend(over_paced_spend(100.0, gp._month_progress()))
    st = g.status()
    check("A2 月误差 e<0（超支趋势）", st["error"] < 0 and st["over_pacing"])
    time.sleep(1.1)
    lam1 = g.get_lambda()
    check("A3 超支 → λ^G 升", lam1 > 0.0)

    # ════════════ B. 变化率限制（§41：|Δλ^G| ≤ 0.1/周期） ════════════
    g2 = gp.GlobalPriceController(monthly_budget=100.0,
                                  store_path=os.path.join(tmpdir, "b.json"),
                                  update_interval=1)
    g2.record_spend(over_paced_spend(100.0, gp._month_progress()))
    time.sleep(1.1)
    l1 = g2.get_lambda()          # 首拍建基线
    time.sleep(1.1)
    l2 = g2.get_lambda()          # 第二拍动作
    check("B1 单步 |Δλ^G| ≤ 0.1", abs(l2 - l1) <= 0.1 + 1e-9)
    time.sleep(1.1)
    l3 = g2.get_lambda()
    check("B2 下一拍仍限幅", abs(l3 - l2) <= 0.1 + 1e-9)

    # ════════════ C. 积分主导 + 撞界冻结 ════════════
    check("C1 积分增益>比例增益（积分主导配置）", gp._KI_G > gp._KP_G)
    g3 = gp.GlobalPriceController(monthly_budget=100.0,
                                  store_path=os.path.join(tmpdir, "c.json"),
                                  update_interval=1)
    g3._lam = 0.5                 # 已在上界
    g3._spent = 99.9              # 仍超支
    g3._i_term = 0.6              # 积分积压：raw 目标持续越界（限幅会把 λ 拉下界，
                                  # 只有目标一直在界外才观测得到冻结）
    g3._pi_ready = True
    g3._e_prev = g3._error_locked()   # 比例项≈0
    time.sleep(1.1)
    lc1 = g3.get_lambda()
    check("C2 λ^G 撞 0.5 上界被钳位", lc1 <= 0.5)
    i_before = g3._i_term
    time.sleep(1.1)
    g3.get_lambda()
    check("C3 撞界后积分冻结（i_term 不累积）", abs(g3._i_term - i_before) < 1e-12)

    # ════════════ D. 观测门控（§35，两层同语义） ════════════
    g4 = gp.GlobalPriceController(monthly_budget=100.0,
                                  store_path=os.path.join(tmpdir, "d.json"),
                                  update_interval=1)
    g4.record_spend(over_paced_spend(100.0, gp._month_progress()))
    g4.set_observation(False, "断网")
    time.sleep(1.1)
    lg_frozen = g4.get_lambda()
    check("D1 冻结期 λ^G 不更新", abs(lg_frozen - 0.0) < 1e-12)
    g4.set_observation(True)
    time.sleep(1.1)
    lg_resume1 = g4.get_lambda()  # 恢复首拍：只建基线
    check("D2 恢复首拍不动作（防阶跃）", abs(lg_resume1 - 0.0) < 1e-12)
    time.sleep(1.1)
    lg_resume2 = g4.get_lambda()  # 第二拍才开始调节
    check("D3 恢复第二拍正常调节", lg_resume2 > 0.0)
    # L1 同语义
    p = bp.BudgetPacer(budget=100.0, store_path=os.path.join(tmpdir, "d2.json"),
                       update_interval=1)
    p.record_spend(90.0)
    p.set_observation(False, "暂停")
    time.sleep(1.1)
    check("D4 L1 冻结期 λ 不动", abs(p.get_lambda() - 0.2) < 1e-12)
    p.set_observation(True)
    time.sleep(1.1)
    check("D5 L1 恢复首拍只建基线", abs(p.get_lambda() - 0.2) < 1e-12)
    time.sleep(1.1)
    check("D6 L1 恢复第二拍调节", p.get_lambda() > 0.2)

    # ════════════ E. 配额拍卖（§39） ════════════
    g5 = gp.GlobalPriceController(monthly_budget=100.0,
                                  store_path=os.path.join(tmpdir, "e.json"))
    g5.record_spend(40.0)         # 剩余 60
    r = g5.auction(pressures={"t1": 3.0, "t2": 1.0})
    check("E1 高压任务拿更多（3:1 → 45:15）",
          abs(r["quotas"]["t1"] - 45.0) < 1e-6
          and abs(r["quotas"]["t2"] - 15.0) < 1e-6)
    check("E2 永久不变量 Σ≤剩余", r["invariant_ok"]
          and sum(r["quotas"].values()) <= 60.0 + 1e-9)
    r2 = g5.auction(pressures={"t1": 3.0, "t2": 1.0},
                    key_tasks={"t2": 0.5})   # t2 保底 50%×60=30
    check("E3 关键任务保底（t2 ≥ 30）", r2["quotas"]["t2"] >= 30.0 - 1e-9)
    check("E4 保底后仍满足不变量", r2["invariant_ok"]
          and sum(r2["quotas"].values()) <= 60.0 + 1e-9)
    g5.report_task_spend("t1", 50.0, 45.0)    # 超支 5 → 欠账
    r3 = g5.auction(pressures={"t1": 3.0, "t2": 1.0})
    check("E5 超支任务下期自动扣款（t1 少拿 5）",
          abs(r3["quotas"]["t1"] - 40.0) < 1e-6)
    check("E6 欠账扣完归零", r3["debts"].get("t1", 0.0) < 1e-9)

    # ════════════ F. λ_eff 叠加改变路由（§2） ════════════
    qp2 = _load("quality_prior.py")
    _load("provider_caps.py")  # 副作用：注册模块供后续 import（勿因「未使用」删除）
    vgc = _load("video_generation_client.py")
    bp._PACER = bp.BudgetPacer(budget=100.0,
                               store_path=os.path.join(tmpdir, "f1.json"))
    gp._GLOBAL = gp.GlobalPriceController(monthly_budget=100.0,
                                          store_path=os.path.join(tmpdir, "f2.json"))
    qp2._STORE = qp2.QualityPriorStore(store_path=os.path.join(tmpdir, "f3.json"))
    # 制造先验：dashscope 质量好但贵（1.5），cogvideo 中等便宜（0.8）
    for _ in range(6):
        qp2._STORE.record("dashscope", 1.0)
        qp2._STORE.record("cogvideo", 0.8)
    client = vgc.VideoGenerationClient.get_instance()
    order_rich = client._resolve_provider_order("auto")
    check("F1 λ^G=0 时 dashscope 排前（质量好）", order_rich[0] == "dashscope")
    # 抬 L0：λ^G=0.5 → λ_eff=0.7 → dashscope U=1.0−1.05=−0.05 < cogvideo 0.8−0.56=0.24
    gp._GLOBAL._lam = 0.5
    gp._GLOBAL._pi_ready = True
    gp._GLOBAL._e_prev = 0.5     # e_prev>当前 e，比例项向下？保守直接锁状态
    gp._GLOBAL._obs_valid = False  # 冻结防回读改写
    order_tight = client._resolve_provider_order("auto")
    check("F2 λ^G=0.5 时 dashscope 被反超（L0 直接改变路由）",
          order_tight[0] != "dashscope")
    gp._GLOBAL._obs_valid = True

    # ════════════ G. 跨月结转 ════════════
    g6 = gp.GlobalPriceController(monthly_budget=100.0,
                                  store_path=os.path.join(tmpdir, "g.json"))
    g6.record_spend(80.0)
    g6._lam = 0.4
    g6._month = "2020-01"        # 伪造上月
    st6 = g6.status()
    check("G1 跨月：账单重置", st6["spent"] == 0.0)
    check("G2 跨月：λ^G 指数回退（0.4→0.2）", abs(st6["lambda_g"] - 0.2) < 1e-9)

    print(f"\n{'=' * 50}\nL0 全局价格层检查：{TOTAL - len(FAILS)}/{TOTAL} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("OK L0 全局价格层 + 配额拍卖 + 观测门控全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
