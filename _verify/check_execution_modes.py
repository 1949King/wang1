#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.37.8 六种执行模式 + 可行集投影（规格书 §10/§11/§12 切片⑤）—— 自包含。

跑法: python _verify/check_execution_modes.py

验收要点：
  A. 基线锚点：本地模式惩罚恒 0（V_L = q_L，不随 λ 变化）
  B. 收益函数：云端只惩罚增量成本；λ 升高 → 云端相对变差
  C. 融合质量上界：q_D ≥ max(q_L, q_C)，且 ∈ [0,1]
  D. 切换成本：仅 current_mode 非空且不同才扣 κ_sw
  E. 投影正交：只删项、绝不改分；删除带人话理由；全删光回退本地锚点
  F. 硬约束采集：断网删全部含云模式；无 key 删 C/D/L→C/SkipMerge 留 C→L
  G. 端到端：client generate 后 last_mode_plan/last_execution_mode 可查、
     计划 vs 实际一致（云端成功=C；回退本地=C→L；显式 local=L）
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
    for fake in ("app", "app.core"):  # wmic 沙箱黑名单：假包让 app.* 快速失败
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
    em = _load("execution_modes.py")

    # ════════════ A. 基线锚点（§11：本地惩罚恒 0） ════════════
    s1 = em.score_modes(q_local=0.3, q_cloud=0.9,
                        cost_local=0.0, cost_cloud=1.5, lambda_c=0.2)
    check("A1 本地分 = q_L（锚点无惩罚）", abs(s1[em.MODE_L] - 0.3) < 1e-12)
    s2 = em.score_modes(q_local=0.3, q_cloud=0.9,
                        cost_local=0.0, cost_cloud=1.5, lambda_c=0.9)
    check("A2 λ 从 0.2→0.9，本地分不变", abs(s2[em.MODE_L] - 0.3) < 1e-12)
    check("A3 λ 升 → 云端分下降", s2[em.MODE_C] < s1[em.MODE_C])
    check("A4 λ 足够大时本地反超云端（收敛本地，根治 D 泛滥）",
          s2[em.MODE_L] > s2[em.MODE_C])

    # ════════════ B. 增量成本语义 ════════════
    s3 = em.score_modes(q_local=0.5, q_cloud=0.5,
                        cost_local=0.0, cost_cloud=1.0, lambda_c=0.2)
    check("B1 同质量时云端分 = q − λ·Δc（0.5−0.2=0.3）",
          abs(s3[em.MODE_C] - 0.3) < 1e-9)
    s4 = em.score_modes(q_local=0.5, q_cloud=0.5,
                        cost_local=0.4, cost_cloud=1.0, lambda_c=0.2)
    check("B2 本地有成本时只罚增量（Δc=0.6 → 0.5−0.12=0.38）",
          abs(s4[em.MODE_C] - 0.38) < 1e-9)

    # ════════════ C. 融合质量上界 ════════════
    qd = em.fused_quality(0.3, 0.9)
    check("C1 q_D ≥ max(q_L,q_C)", qd >= 0.9)
    check("C2 q_D = 1−(1−.3)(1−.9) = 0.93", abs(qd - 0.93) < 1e-9)
    check("C3 q_D ∈ [0,1]（极端输入钳位）",
          0.0 <= em.fused_quality(-1.0, 2.0) <= 1.0)
    s5 = em.score_modes(q_local=0.3, q_cloud=0.9,
                        cost_local=0.0, cost_cloud=1.5, lambda_c=0.2)
    check("C4 D 模式分 = q_D − λ·(双倍成本)（0.93−0.2×1.5=0.63）",
          abs(s5[em.MODE_D] - 0.63) < 1e-9)

    # ════════════ D. 切换成本 ════════════
    s6 = em.score_modes(q_local=0.3, q_cloud=0.9, cost_local=0.0, cost_cloud=1.5,
                        lambda_c=0.2, kappa_sw=0.1, current_mode=em.MODE_C)
    check("D1 同模式不扣切换成本",
          abs(s6[em.MODE_C] - s1[em.MODE_C]) < 1e-12)
    check("D2 异模式扣 κ_sw",
          abs(s6[em.MODE_L] - (s1[em.MODE_L] - 0.1)) < 1e-12)
    s7 = em.score_modes(q_local=0.3, q_cloud=0.9, cost_local=0.0, cost_cloud=1.5,
                        lambda_c=0.2, kappa_sw=0.1, current_mode="")
    check("D3 current_mode 为空全不扣",
          abs(s7[em.MODE_L] - s1[em.MODE_L]) < 1e-12)

    # ════════════ E. 投影正交（§12：只删不改分） ════════════
    scores = {"L": 0.3, "C": 0.6, "D": 0.63}
    snapshot = dict(scores)
    proj = em.project_feasible(scores, infeasible={"D": "显存不足：双路需同时驻留"})
    check("E1 投影后原字典分未变", scores == snapshot)
    check("E2 被删项带理由", proj["dropped"] == [("D", "显存不足：双路需同时驻留")])
    check("E3 保留项按收益降序", [m for m, _ in proj["kept"]] == ["C", "L"])
    proj2 = em.project_feasible(scores, infeasible={"L": "x", "C": "x", "D": "x"})
    check("E4 全删光 kept 为空", proj2["kept"] == [])
    att = em.choose_mode(q_local=0.3, q_cloud=0.9, cost_local=0.0, cost_cloud=1.5,
                         lambda_c=0.2, infeasible={"L": "a", "C": "b", "D": "c",
                                                   "L→C": "d", "C→L": "e",
                                                   "SkipMerge": "f"})
    check("E5 全删光回退本地锚点 L", att["mode"] == em.MODE_L)
    att2 = em.choose_mode(q_local=0.3, q_cloud=0.9, cost_local=0.0, cost_cloud=1.5,
                          lambda_c=0.2)
    need = {"mode", "label", "scores", "kept", "dropped", "baseline",
            "lambda_c", "lambda_l", "kappa_sw"}
    check("E6 归因字典字段齐全", need.issubset(set(att2.keys())))

    # ════════════ F. 硬约束采集 ════════════
    inf_off = em.collect_infeasible(online=False)
    check("F1 断网删掉全部含云模式",
          all(m in inf_off for m in (em.MODE_C, em.MODE_D, em.MODE_L2C,
                                     em.MODE_C2L, em.MODE_SKIP_MERGE)))
    check("F2 断网保留本地 L", em.MODE_L not in inf_off)
    inf_nokey = em.collect_infeasible(online=True, cloud_available=False)
    check("F3 无云端 key 删 C/D/L→C/SkipMerge",
          all(m in inf_nokey for m in (em.MODE_C, em.MODE_D, em.MODE_L2C,
                                       em.MODE_SKIP_MERGE)))
    check("F4 无云端 key 仍留 C→L（回退语义）", em.MODE_C2L not in inf_nokey)
    inf_vram = em.collect_infeasible(vram_ok=False)
    check("F5 显存不足只删双路 D", list(inf_vram.keys()) == [em.MODE_D])

    # ════════════ G. 端到端：client 归因可查 ════════════
    vgc = _load("video_generation_client.py")
    client = vgc.VideoGenerationClient.get_instance()
    client._tls.last_provider = ""
    client._tls.last_mode_executed = ""
    client._tls.last_mode_plan = None
    # 本地显式生成（真实渠道在无网/无 key 环境会失败回退——两种终态都归因正确）
    paths = client.generate(prompt="模式归因测试", duration=1.0, count=1,
                            provider="local", width=320, height=240)
    check("G1 本地显式生成有产出", len(paths) == 1)
    check("G2 实际执行模式 = L", client.last_execution_mode() == "L")
    plan = client.last_mode_plan()
    check("G3 模式计划已记录（含归因字段）",
          isinstance(plan, dict) and "scores" in plan and "dropped" in plan)
    # 模拟云端失败回退：塞一个必然失败的假 provider 进链
    client2 = vgc.VideoGenerationClient.get_instance()
    orig = client2._providers.get("dashscope", "missing")

    def _boom(**_kw):
        raise RuntimeError("模拟云端 429")

    client2._providers["dashscope"] = _boom
    try:
        client2.generate(prompt="回退归因测试", duration=1.0, count=1,
                         provider="dashscope", width=320, height=240)
    finally:
        if orig == "missing":
            client2._providers.pop("dashscope", None)
        else:
            client2._providers["dashscope"] = orig
    check("G4 云端失败回退后实际模式 = C→L", client2.last_execution_mode() == "C→L")

    print(f"\n{'=' * 50}\n执行模式检查：{TOTAL - len(FAILS)}/{TOTAL} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("OK 六种执行模式 + 可行集投影全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
