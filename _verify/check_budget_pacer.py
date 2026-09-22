#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.37.7 PI 预算影子价格控制器（规格书第六篇 C 模块切片④）—— 自包含。

跑法: python _verify/check_budget_pacer.py

验收要点：
  A. 剩余法误差：超支趋势 e<0 / 富余 e>0
  B. PI 方向性：超支 → λ 升；富余 → λ 降（不低于下界）
  C. 抗卷绕：λ 撞界后积分冻结（不持续累积）
  D. 观测门控：间隔不足不迭代
  E. 跨日结转：预算重置 + λ 指数回退（不清零）
  F. 持久化 + 损坏容错
  G. 端到端：动态 λ 改变路由排序（贵渠道在 λ 升后被反超）；client 花费记账
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
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    # 沙箱 wmic 黑名单（不变量 #10）：app 假包让 app.* 导入快速失败
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
    tmpdir = tempfile.mkdtemp(prefix="sg_bp_test_")
    bp = _load("budget_pacer.py")
    pc = _load("provider_caps.py")
    qp = _load("quality_prior.py")
    vgc = _load("video_generation_client.py")

    # ════════════ A. 剩余法误差 ════════════
    p = bp.BudgetPacer(budget=100.0, store_path=os.path.join(tmpdir, "a.json"),
                       update_interval=1)
    st = p.status()
    check("零花费：e>0（富余）", st["error"] > 0 and st["over_pacing"] is False)
    # 花掉远超时间进度的预算（当前时间比例必然 < 0.99，花 99% 必超支）
    p.record_spend(99.0)
    st = p.status()
    check("花 99%：e<0（超支趋势）", st["error"] < 0 and st["over_pacing"] is True)
    check("花费记账正确", abs(st["spent"] - 99.0) < 1e-9)
    check("remaining 正确", abs(st["remaining"] - 1.0) < 1e-9)

    # ════════════ B. PI 方向性 ════════════
    p2 = bp.BudgetPacer(budget=100.0, store_path=os.path.join(tmpdir, "b.json"),
                        update_interval=1)
    lam0 = p2.get_lambda()
    check("初始 λ=0.2（接管原静态值）", abs(lam0 - 0.2) < 1e-9)
    p2.record_spend(99.0)           # 制造超支趋势
    import time as _t; _t.sleep(1.1)  # 过更新间隔
    lam1 = p2.get_lambda()
    check("超支趋势 → λ 上调", lam1 > lam0)
    p3 = bp.BudgetPacer(budget=100.0, store_path=os.path.join(tmpdir, "b2.json"),
                        update_interval=1)
    p3._lam = 0.2                   # 先抬高基线看下调
    p3._spent = 0.0                 # 富余
    p3.get_lambda()                 # 首读：建误差基线（不动作）
    _t.sleep(1.1)
    lam2 = p3.get_lambda()          # 第二次读：积分项起作用 → 下调
    check("预算富余 → λ 下调", lam2 < 0.2)
    check("λ 不低于下界 0.05", lam2 >= 0.05)

    # ════════════ C. 抗卷绕：撞界冻结 ════════════
    p4 = bp.BudgetPacer(budget=100.0, store_path=os.path.join(tmpdir, "c.json"),
                        update_interval=1)
    p4._lam = 1.0                   # 已在上界
    p4._spent = 99.9                # 仍超支（积分想继续推）
    _t.sleep(1.1)
    lam_c1 = p4.get_lambda()
    check("λ 撞 1.0 上界被钳位", lam_c1 <= 1.0)
    _t.sleep(1.1)
    lam_c2 = p4.get_lambda()
    check("撞界后不再累积（冻结）", abs(lam_c2 - lam_c1) < 1e-9)

    # ════════════ D. 观测门控 ════════════
    p5 = bp.BudgetPacer(budget=100.0, store_path=os.path.join(tmpdir, "d.json"),
                        update_interval=3600)
    p5.record_spend(99.0)
    lam_d1 = p5.get_lambda()        # 首次触发更新
    lam_d2 = p5.get_lambda()        # 间隔不足 → 不迭代，直接返回
    check("门控：间隔不足两次读一致", abs(lam_d2 - lam_d1) < 1e-12)

    # ════════════ E. 跨日结转 ════════════
    p6 = bp.BudgetPacer(budget=100.0, store_path=os.path.join(tmpdir, "e.json"),
                        update_interval=1)
    p6.record_spend(80.0)
    p6._lam = 0.8                   # 抬高 λ 模拟一天调节结果
    p6._date = "2020-01-01"         # 伪造昨天
    st6 = p6.status()               # status 内含 rollover
    check("跨日：花费重置", st6["spent"] == 0.0)
    check("跨日：λ 指数回退（0.8→0.2+(0.8-0.2)*0.5=0.5）",
          abs(st6["lambda"] - 0.5) < 1e-9)
    check("跨日：不清零（回退非阶跃）", st6["lambda"] > 0.2)

    # ════════════ F. 持久化 ════════════
    path_f = os.path.join(tmpdir, "f.json")
    p7 = bp.BudgetPacer(budget=100.0, store_path=path_f, update_interval=1)
    p7.record_spend(42.5)
    p8 = bp.BudgetPacer(budget=100.0, store_path=path_f, update_interval=1)
    check("重载恢复花费", abs(p8.status()["spent"] - 42.5) < 1e-9)
    with open(path_f, "w", encoding="utf-8") as f:
        f.write("{broken")
    p9 = bp.BudgetPacer(budget=100.0, store_path=path_f, update_interval=1)
    check("损坏文件按初始状态启动", p9.status()["spent"] == 0.0)

    # ════════════ G. 端到端：动态 λ 改变路由 + 花费记账 ════════════
    # G1：λ 低（富余）→ 贵但好的 dashscope 排前；λ 高（紧张）→ 被反超
    priors = {"dashscope": 0.6, "seedance": 0.55}
    order_rich = pc.resolve_order("auto", priors=priors, lambda_price=0.05)
    # utility: dashscope=0.6-0.05*1.5=0.525; seedance=0.55-0.05*1.0=0.5
    check("λ 低（富余）：dashscope（贵但好）排前", order_rich[0] == "dashscope")
    order_tight = pc.resolve_order("auto", priors=priors, lambda_price=1.0)
    # utility: dashscope=0.6-1.5=-0.9; seedance=0.55-1.0=-0.45; cogvideo=0.5-0.8=-0.3
    check("λ 高（紧张）：贵渠道被反超",
          order_tight[0] != "dashscope" and order_tight[-1] == "local")
    # G2：client 花费记账
    iso_bp = bp.BudgetPacer(budget=100.0, store_path=os.path.join(tmpdir, "g.json"),
                            update_interval=1)
    bp._PACER = iso_bp
    iso_qp = qp.QualityPriorStore(store_path=os.path.join(tmpdir, "gq.json"))
    qp._STORE = iso_qp
    client = vgc.VideoGenerationClient()

    def _ok(prompt, duration, count, width, height):
        return [os.path.join(tmpdir, f"g_{i}.mp4") for i in range(count)]

    client._providers = {"dashscope": _ok, "seedance": None, "cogvideo": None}
    client.generate(prompt="t", duration=3.0, count=2)
    st_g = iso_bp.status()
    check("成功生成 2 段 → 记账 2×1.5=3.0 元", abs(st_g["spent"] - 3.0) < 1e-9)
    # local 不记账
    client._providers = {"dashscope": None, "seedance": None, "cogvideo": None}
    client.generate(prompt="t", duration=3.0, count=1)
    check("local 占位不记账", abs(iso_bp.status()["spent"] - 3.0) < 1e-9)
    bp._PACER = None
    qp._STORE = None

    print(f"\n{'ALL PASS' if not FAILS else 'FAILED'} ({TOTAL} checks)")
    for f in FAILS:
        print(f"  - {f}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
