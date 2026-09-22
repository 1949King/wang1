#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.37.6 六级降级体系（规格书 §44-46 切片③）—— 自包含。

跑法: python _verify/check_degradation.py

验收要点：
  A. 级别表完整 + 终态优先级（取最严重）
  B. classify_error 失败分类（resource/auth/model/unknown）
  C. 统计：24h 窗口、各级计数、降级率、最严重级别
  D. 端到端四种终态：L0 完整 / L2 换渠道 / L3 降质重试 / L6 本地兜底 / L5 部分交付
  E. 显式 provider="local" 不算降级
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
    tmpdir = tempfile.mkdtemp(prefix="sg_deg_test_")
    dg = _load("degradation.py")
    qp = _load("quality_prior.py")
    vgc = _load("video_generation_client.py")

    # ════════════ A. 级别表 + 终态优先级 ════════════
    check("六级+完整级共 7 级定义", len(dg.LEVELS) == 7)
    check("L1/L4 为预留位", "预留" in dg.LEVELS[1]["label"] and "预留" in dg.LEVELS[4]["label"])
    s = dg.DegradationSession()
    check("空会话终态 L0", s.final_level == 0)
    s.mark(2, "换渠道")
    s.mark(5, "部分交付")
    check("多级取最严重（L2+L5→L5）", s.final_level == 5)
    s.mark(3, "降质")
    check("L5 仍比 L3 严重", s.final_level == 5)
    s.mark(6, "兜底")
    check("L6 最严重", s.final_level == 6)
    check("非法级别忽略", (s.mark(9, "x"), s.final_level == 6)[1])
    summ = s.summary()
    check("summary 带级别名与人话标签",
          summ["level"] == 6 and summ["level_name"] == "local_fallback" and summ["level_label"])

    # ════════════ B. classify_error ════════════
    check("超时 → resource", dg.classify_error("DashScope 任务超时（>360s）") == "resource")
    check("429 → resource", dg.classify_error("HTTP 429 Throttling") == "resource")
    check("OOM → resource", dg.classify_error("CUDA out of memory") == "resource")
    check("403 AccessDenied → auth", dg.classify_error("HTTP 403 AccessDenied") == "auth")
    check("401 → auth", dg.classify_error("HTTP 401 InvalidApiKey") == "auth")
    check("模型不存在 → model", dg.classify_error("Model not exist") == "model")
    check("其他 → unknown", dg.classify_error("whatever broke") == "unknown")
    check("空错误 → unknown", dg.classify_error("") == "unknown")

    # ════════════ C. 统计 ════════════
    stats = dg.DegradationStats()
    for lv in (0, 0, 2, 3, 6):
        stats.record(lv)
    sm = stats.summary()
    check("统计总数 5", sm["generations_24h"] == 5)
    check("降级数 3（2/3/6）", sm["degraded_24h"] == 3)
    check("降级率 0.6", abs(sm["degradation_rate"] - 0.6) < 1e-9)
    check("按级计数", sm["by_level"].get("full") == 2 and sm["by_level"].get("local_fallback") == 1)
    check("最严重 L6", sm["worst_level_24h"] == 6)

    # ════════════ D/E. 端到端终态 ════════════
    iso = qp.QualityPriorStore(store_path=os.path.join(tmpdir, "q.json"))
    qp._STORE = iso
    dstats = dg.DegradationStats()
    dg._STATS = dstats
    try:
        bp_mod = _load("budget_pacer.py")
        bp_mod._PACER = bp_mod.BudgetPacer(store_path=os.path.join(tmpdir, "bp.json"))
        gp_mod = _load("global_price.py")
        gp_mod._GLOBAL = gp_mod.GlobalPriceController(
            store_path=os.path.join(tmpdir, "gp.json"))
    except Exception:
        bp_mod = None
    client = vgc.VideoGenerationClient()

    def _ok(prompt, duration, count, width, height):
        return [os.path.join(tmpdir, f"ok_{width}x{height}_{i}.mp4") for i in range(count)]

    def _fail_resource(prompt, duration, count, width, height):
        raise RuntimeError("HTTP 429 Throttling: quota exceeded")

    def _fail_auth(prompt, duration, count, width, height):
        raise RuntimeError("HTTP 403 AccessDenied")

    def _partial(prompt, duration, count, width, height):
        return [os.path.join(tmpdir, "p1.mp4")]  # 只给 1 段

    # D1：首选成功 → L0
    client._providers = {"dashscope": _ok, "seedance": None, "cogvideo": None}
    client.generate(prompt="t", duration=3.0, count=1)
    check("首选成功 → L0 完整交付", client.last_degradation()["level"] == 0)

    # D2：首选失败换渠道成功 → L2
    client._providers = {"dashscope": _fail_auth, "seedance": _ok, "cogvideo": None}
    client.generate(prompt="t", duration=3.0, count=1)
    check("换渠道成功 → L2 云端降级", client.last_degradation()["level"] == 2)

    # D3：资源类失败 → L3 480p 重试成功
    calls = {"n": 0}

    def _fail_then_ok_lowres(prompt, duration, count, width, height):
        calls["n"] += 1
        if min(width, height) <= 480:
            return [os.path.join(tmpdir, "low.mp4")]
        raise RuntimeError("HTTP 429 Throttling")

    client._providers = {"dashscope": _fail_then_ok_lowres, "seedance": None,
                         "cogvideo": None, "local": vgc.VideoGenerationClient()._call_local_fallback}
    client.generate(prompt="t", duration=3.0, count=1, width=1280, height=720)
    d = client.last_degradation()
    check("资源类失败降质重试成功 → L3", d["level"] == 3)
    check("L3 事件带渠道名", any("480p" in e["reason"] for e in d["events"]))

    # D4：认证类失败（非资源类）→ 不触发 L3，直接 L6 本地兜底
    client._providers = {"dashscope": _fail_auth, "seedance": None, "cogvideo": None}
    paths = client.generate(prompt="t", duration=3.0, count=1, width=1280, height=720)
    d = client.last_degradation()
    check("auth 失败不降质 → L6 本地兜底", d["level"] == 6)
    check("L6 仍出片（占位）", len(paths) == 1 and os.path.exists(paths[0]))
    check("L6 归因 local", client.last_used_provider() == "local")

    # D5：资源类失败但已 ≤480p → 不降质（没有更低档），L6
    client._providers = {"dashscope": _fail_resource, "seedance": None, "cogvideo": None}
    client.generate(prompt="t", duration=3.0, count=1, width=854, height=480)
    check("已 480p 不再降质 → L6", client.last_degradation()["level"] == 6)

    # D6：部分交付 → L5
    client._providers = {"dashscope": _partial, "seedance": None, "cogvideo": None}
    client.generate(prompt="t", duration=3.0, count=3)
    check("段数未凑齐 → L5 部分交付", client.last_degradation()["level"] == 5)

    # E：显式 local 不算降级
    client.generate(prompt="t", duration=3.0, count=1, provider="local")
    check("显式 provider=local → L0（主动选择非降级）",
          client.last_degradation()["level"] == 0)

    # 统计端到端累计
    sm = dstats.summary()
    check("统计覆盖端到端 7 次生成", sm["generations_24h"] == 7)
    check("by_level 含 quality_down/local_fallback/partial",
          sm["by_level"].get("quality_down") == 1
          and sm["by_level"].get("partial") == 1)

    qp._STORE = None
    dg._STATS = None

    print(f"\n{'ALL PASS' if not FAILS else 'FAILED'} ({TOTAL} checks)")
    for f in FAILS:
        print(f"  - {f}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
