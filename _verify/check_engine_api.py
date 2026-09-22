#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.38.5 引擎对外接口规范 + 错误码体系（规格书第十篇 切片⑫）—— 自包含。

跑法: python _verify/check_engine_api.py

验收要点：
  A. 统一信封：ok/code/message/data 四字段；全部错误码有人话标签
  B. 任务创建：未注册模块 / 暂停模块 / 依赖成环 / 幂等重复 → 各自错误码
  C. 单元提交：空 prompt → INVALID_PARAM；月账单耗尽 → BUDGET_EXHAUSTED；
     成功 → 归因五件套（provider/mode_executed/mode_plan/degradation/fusion）
  D. 路由回调：凭 unit_id 取回同一份归因；未知 id → INVALID_PARAM
  E. 资源上报：L1 预算 / L0 账单 / 调度 / 抽检四视图齐全
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
    tmpdir = tempfile.mkdtemp(prefix="sg_api_test_")
    ea = _load("engine_api.py")
    ms = _load("module_scheduler.py")
    bp = _load("budget_pacer.py")
    gp = _load("global_price.py")
    qp = _load("quality_prior.py")
    srm = _load("sampling_review.py")
    vgc = _load("video_generation_client.py")

    # ════════════ A. 统一信封 + 错误码标签 ════════════
    api = ea.EngineAPI()
    r = api.create_task("", "")
    check("A1 信封四字段齐全",
          all(k in r for k in ("ok", "code", "message", "data")))
    check("A2 空参数 → INVALID_PARAM", r["code"] == ea.ERR_INVALID_PARAM)
    all_codes = [v for k, v in vars(ea).items() if k.startswith("ERR_")]
    check("A3 全部错误码有人话标签",
          all(ea.err_label(c) != c for c in all_codes))

    # ════════════ B. 任务创建（模块调度包装） ════════════
    ms._SCHED = ms.ModuleScheduler()  # 隔离单例
    ms.get_scheduler().register_module("video_gen", quota=1,
                                       non_preemptible=True)
    r1 = api.create_task("no_such_module", "t1")
    check("B1 未注册模块 → INVALID_PARAM", r1["code"] == ea.ERR_INVALID_PARAM)
    r2 = api.create_task("video_gen", "t2", idem_key="k1")
    check("B2 正常创建 → ok", r2["ok"] is True and r2["code"] == ea.ERR_OK)
    r3 = api.create_task("video_gen", "t3", idem_key="k1")
    check("B3 幂等重复 → DUPLICATE_TASK", r3["code"] == ea.ERR_DUPLICATE_TASK)
    ms.get_scheduler().pause_module("video_gen")
    r4 = api.create_task("video_gen", "t4")
    check("B4 暂停模块 → MODULE_UNHEALTHY",
          r4["code"] == ea.ERR_MODULE_UNHEALTHY)
    ms.get_scheduler().pause_module("video_gen", False)
    api.create_task("video_gen", "c1", depends_on=["c2"])
    api.create_task("video_gen", "c2", depends_on=["c3"])
    r5 = api.create_task("video_gen", "c3", depends_on=["c1"])
    check("B5 依赖成环 → DEPENDENCY_CYCLE",
          r5["code"] == ea.ERR_DEPENDENCY_CYCLE)

    # ════════════ C. 单元提交（模型调度包装） ════════════
    bp._PACER = bp.BudgetPacer(budget=100.0,
                               store_path=os.path.join(tmpdir, "bp.json"))
    gp._GLOBAL = gp.GlobalPriceController(
        monthly_budget=100.0, store_path=os.path.join(tmpdir, "gp.json"))
    qp._STORE = qp.QualityPriorStore(store_path=os.path.join(tmpdir, "qp.json"))
    srm._REVIEW = srm.SamplingReview(
        store_path=os.path.join(tmpdir, "sr.json"))
    client = vgc.VideoGenerationClient.get_instance()
    cloud_file = os.path.join(tmpdir, "c.bin")
    with open(cloud_file, "wb") as f:
        f.write(b"cloud" * 4096)
    saved = {}
    for name in ("dashscope", "seedance", "cogvideo"):
        saved[name] = client._providers.get(name, "missing")
        client._providers[name] = lambda **_kw: [cloud_file]
    try:
        rc1 = api.submit_unit("")
        check("C1 空 prompt → INVALID_PARAM", rc1["code"] == ea.ERR_INVALID_PARAM)
        # 月账单耗尽 → 硬拒
        gp._GLOBAL.record_spend(100.0)
        rc2 = api.submit_unit("测试提示词")
        check("C2 月账单耗尽 → BUDGET_EXHAUSTED",
              rc2["code"] == ea.ERR_BUDGET_EXHAUSTED)
        gp._GLOBAL = gp.GlobalPriceController(
            monthly_budget=100.0, store_path=os.path.join(tmpdir, "gp2.json"))
        rc3 = api.submit_unit("山间云雾缭绕，少女独行", duration=1.0,
                              unit_id="u_test_1")
        check("C3 成功提交 → ok", rc3["ok"] is True)
        need = {"provider", "mode_executed", "mode_plan",
                "degradation", "fusion", "paths"}
        check("C4 归因五件套 + paths 齐全",
              need.issubset(set(rc3["data"].keys())))
        check("C5 实际渠道非空", bool(rc3["data"]["provider"]))
    finally:
        for name, orig in saved.items():
            if orig == "missing":
                client._providers.pop(name, None)
            else:
                client._providers[name] = orig

    # ════════════ D. 路由回调 ════════════
    rd1 = api.route_callback("u_test_1")
    check("D1 回调取回同一份归因", rd1["ok"] is True
          and rd1["data"]["provider"] == rc3["data"]["provider"])
    rd2 = api.route_callback("no_such_unit")
    check("D2 未知 unit → INVALID_PARAM", rd2["code"] == ea.ERR_INVALID_PARAM)

    # ════════════ E. 资源上报 ════════════
    rr = api.resource_report()
    check("E1 上报 ok", rr["ok"] is True)
    check("E2 四视图齐全（L1/L0/调度/抽检）",
          all(k in rr["data"] for k in ("budget_l1", "bill_l0",
                                        "scheduler", "review")))
    check("E3 L1 视图含 λ", "lambda" in rr["data"]["budget_l1"])
    check("E4 L0 视图含 λ^G", "lambda_g" in rr["data"]["bill_l0"])

    print(f"\n{'=' * 50}\n引擎接口规范检查：{TOTAL - len(FAILS)}/{TOTAL} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("OK 引擎对外接口规范 + 错误码体系全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
