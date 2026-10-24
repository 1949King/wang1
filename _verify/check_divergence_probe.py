#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.37.9 A 模块分歧度探针（规格书第四篇 §16-19 切片⑥）—— 自包含。

跑法: python _verify/check_divergence_probe.py

验收要点：
  A. 文本分歧：dict 字段差异率 / 字符串行差异率 / 全同=0 全异=1
  B. 媒体分歧：同文件=0；异文件>0；哈希占主导权
  C. EMA 入库：均值向观测收敛；方差非负；持久化重载恢复
  D. 自适应阈值：质量方差越大阈值越低；钳位在 [0.15, 0.8]
  E. D 候选判定：Δ>τ 才候选；delta=None 走 EMA 估计（抽样探针）
  F. 成本门控：≤2% 放行；超限拒绝并给降级理由；冷启动放行首次
  G. 端到端：client 模式计划带探针裁决；分歧不足时 D 被投影删除且带理由
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types

# 临时目录钉到项目内 .workbuddy/tmp（2026-09-28）：沙箱拦截系统 Temp 写入 ⇒
# tempfile.gettempdir() 回退到 cwd（项目根），直接单跑本脚本会把临时目录漏进仓库根。
# 规范入口 run_all_checks 已用 TMPDIR 传递；此处覆盖「直接单跑」路径。
try:
    _SG_TMP = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if "__file__" in globals() else os.getcwd(),
        ".workbuddy", "tmp",
    )
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

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
    tmpdir = tempfile.mkdtemp(prefix="sg_dp_test_")
    dp = _load("divergence_probe.py")

    # ════════════ A. 文本分歧（§17 结构化指标） ════════════
    d_same = dp.text_divergence({"a": 1, "b": 2}, {"a": 1, "b": 2})
    check("A1 全同字段分歧=0", d_same == 0.0)
    d_half = dp.text_divergence({"a": 1, "b": 2}, {"a": 1, "b": 3})
    check("A2 半数字段不同分歧=0.5", abs(d_half - 0.5) < 1e-12)
    d_all = dp.text_divergence({"a": 1}, {"a": 2, "b": 3})
    check("A3 并集全不同分歧=1", abs(d_all - 1.0) < 1e-12)
    d_str = dp.text_divergence("x\ny", "x\nz")
    check("A4 字符串按行差异率=0.5", abs(d_str - 0.5) < 1e-12)
    check("A5 异常输入不抛（None）", dp.text_divergence(None, None) == 0.0)

    # ════════════ B. 媒体分歧（廉价代理） ════════════
    fa = os.path.join(tmpdir, "a.bin")
    fb = os.path.join(tmpdir, "b.bin")
    with open(fa, "wb") as f:
        f.write(b"same-content" * 100)
    with open(fb, "wb") as f:
        f.write(b"diff-content" * 200)
    check("B1 同文件分歧=0", dp.media_divergence(fa, fa) == 0.0)
    d_diff = dp.media_divergence(fa, fb)
    check("B2 异文件分歧>0.6（哈希主导）", d_diff > 0.6)
    check("B3 时长差计入", dp.media_divergence(fa, fa, 5.0, 10.0) > 0.0)
    check("B4 缺失文件不抛=0", dp.media_divergence(fa, fa + ".none") == 0.0)

    # ════════════ C. EMA 入库 + 持久化 ════════════
    path_c = os.path.join(tmpdir, "c.json")
    pr = dp.DivergenceProbe(store_path=path_c)
    for _ in range(10):
        pr.record("video", 0.9)
    st = pr.summary()["stats"]["video"]
    check("C1 EMA 均值向 0.9 收敛", st["mean"] > 0.8)
    check("C2 方差非负且向 0 收敛", 0.0 <= st["var"] < 0.05)
    check("C3 计数正确", st["n"] == 10)
    pr2 = dp.DivergenceProbe(store_path=path_c)
    check("C4 重载恢复均值", abs(pr2.summary()["stats"]["video"]["mean"]
                                 - st["mean"]) < 1e-9)
    check("C5 未知介质 record 不抛不记", (pr.record("bogus", 0.5) is None)
          and "bogus" not in pr.summary()["stats"])

    # ════════════ D. 自适应阈值（§16.3） ════════════
    pr3 = dp.DivergenceProbe()  # 无统计：var 默认 0.25
    tau_calm = pr3.adaptive_threshold("video", quality_var=0.0)
    tau_uncertain = pr3.adaptive_threshold("video", quality_var=0.3)
    check("D1 质量方差大 → 阈值更低", tau_uncertain < tau_calm)
    check("D2 阈值有下限 0.15", pr3.adaptive_threshold("video", quality_var=99.0) >= 0.15)
    check("D3 阈值有上限 0.8", pr3.adaptive_threshold("video", quality_var=0.0) <= 0.8)

    # ════════════ E. D 候选判定（§16.4） ════════════
    v_low = pr3.is_dual_candidate("video", delta=0.05, quality_var=0.0)
    check("E1 低分歧不候选", v_low["candidate"] is False)
    v_high = pr3.is_dual_candidate("video", delta=0.79, quality_var=0.0)
    check("E2 高分歧候选", v_high["candidate"] is True)
    v_unc = pr3.is_dual_candidate("video", delta=0.3, quality_var=0.3)
    check("E3 高不确定下同 Δ 更易候选（阈值被压低）",
          v_unc["threshold"] < v_low["threshold"])
    v_est = pr3.is_dual_candidate("video")  # delta=None → EMA 估计
    check("E4 delta=None 标记 estimated（抽样探针）", v_est["estimated"] is True)
    check("E5 理由可读", isinstance(v_est["reason"], str) and "τ=" in v_est["reason"])
    check("E6 未知介质永不候选", pr3.is_dual_candidate("bogus")["candidate"] is False)

    # ════════════ F. 成本门控（§16.1 / §18） ════════════
    pr4 = dp.DivergenceProbe(store_path=os.path.join(tmpdir, "f.json"))
    g0 = pr4.cost_gate(0.01)
    check("F1 冷启动（无成本基数）放行", g0["allowed"] is True)
    pr4.note_unit_cost(100.0)          # 单元累计 ¥100 → 探针预算 ¥2
    g1 = pr4.cost_gate(1.5)
    check("F2 预算内放行", g1["allowed"] is True)
    g2 = pr4.cost_gate(5.0)
    check("F3 超 2% 拒绝", g2["allowed"] is False)
    check("F4 拒绝带降级理由（抽样探针）", "抽样探针" in g2["reason"])
    pr4.note_probe_cost(1.5)
    check("F5 探针成本累计", abs(pr4.summary()["probe_cost"] - 1.5) < 1e-9)
    check("F6 占比=1.5%", abs(pr4.summary()["cost_ratio"] - 0.015) < 1e-9)

    # ════════════ G. 端到端：模式计划带探针裁决 ════════════
    vgc = _load("video_generation_client.py")
    client = vgc.VideoGenerationClient.get_instance()
    client._tls.last_mode_plan = None
    client.generate(prompt="探针端到端", duration=1.0, count=1,
                    provider="local", width=320, height=240)
    plan = client.last_mode_plan()
    check("G1 计划含探针裁决字段", isinstance(plan.get("probe"), dict))
    probe = plan.get("probe") or {}
    dropped = dict(plan.get("dropped") or [])
    if probe.get("candidate"):
        check("G2 候选时 D 未被探针删除", "D" not in dropped
              or not str(dropped.get("D", "")).startswith("探针："))
    else:
        check("G2 非候选时 D 被投影删除且理由带「探针：」",
              str(dropped.get("D", "")).startswith("探针："))
    check("G3 探针裁决含 delta/threshold/reason",
          all(k in probe for k in ("delta", "threshold", "reason")))

    print(f"\n{'=' * 50}\n分歧度探针检查：{TOTAL - len(FAILS)}/{TOTAL} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("OK A 模块分歧度探针全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
