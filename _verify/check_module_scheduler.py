#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.38.3 模块调度器 DAG 核心（规格书第二篇 §5-7 切片⑩）—— 自包含。

跑法: python _verify/check_module_scheduler.py

验收要点：
  A. 注册与配额：并发超配额不再出任务；暂停/不健康模块不出任务
  B. 优先级仲裁：P0 先于 P3；同级按提交序
  C. 抢占：高优 ready 时低优运行中可抢占让位；non_preemptible 模块免抢占
  D. DAG：依赖未完→blocked；上游 done→ready；上游 failed→下游 skipped
     且连锁降级；环检测拒绝
  E. 幂等：同 idem_key 二次提交返回 None
  F. 重试：fail→retry 回 pending；attempts 用罄→failed
  G. 状态上报：progress/by_status/degraded/modules 齐全；
     默认单例注册 §5.2 七模块且 video_gen 不可抢占
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
    ms = _load("module_scheduler.py")

    # ════════════ A. 注册与配额（§6.1/§6.4） ════════════
    s = ms.ModuleScheduler()
    s.register_module("video_gen", quota=1, non_preemptible=True)
    s.register_module("canvas_gen", quota=2)
    s.submit("video_gen", "a1")
    s.submit("video_gen", "a2")
    nxt = s.next_runnable()
    check("A1 首个任务可运行", nxt and nxt["task_id"] == "a1")
    check("A2 start 成功占额", s.start("a1") is True)
    check("A3 配额=1 占满 → 不再出同模块任务", s.next_runnable() is None)
    check("A4 超配额 start 拒绝", s.start("a2") is False)
    s.submit("canvas_gen", "a3", priority=ms.P3_MEDIA_GEN)
    check("A5 别的模块有独立配额 → 可出", s.next_runnable()["task_id"] == "a3")
    s.pause_module("canvas_gen")
    check("A6 暂停模块不出任务", s.next_runnable() is None)
    s.pause_module("canvas_gen", False)
    s.set_healthy("canvas_gen", False)
    check("A7 不健康模块不出任务", s.next_runnable() is None)
    s.set_healthy("canvas_gen", True)

    # ════════════ B. 优先级仲裁（§6.3） ════════════
    s2 = ms.ModuleScheduler()
    s2.register_module("m", quota=4)
    s2.submit("m", "b_p3a", priority=ms.P3_MEDIA_GEN)
    s2.submit("m", "b_p0", priority=ms.P0_CANVAS_PREVIEW)
    s2.submit("m", "b_p3b", priority=ms.P3_MEDIA_GEN)
    check("B1 P0 优先于 P3", s2.next_runnable()["task_id"] == "b_p0")
    s2.start("b_p0")
    check("B2 同级按提交序（p3a 先于 p3b）",
          s2.next_runnable()["task_id"] == "b_p3a")

    # ════════════ C. 抢占（§6.3/§13） ════════════
    s3 = ms.ModuleScheduler()
    s3.register_module("edit", quota=1, non_preemptible=False)
    s3.register_module("video", quota=1, non_preemptible=True)
    s3.submit("edit", "c_low", priority=ms.P2_AI_EDIT)
    s3.start("c_low")
    check("C1 无高优等待 → 不抢占", s3.should_preempt("c_low") is False)
    s3.submit("edit", "c_high", priority=ms.P0_CANVAS_PREVIEW)
    check("C2 高优 ready → 低优运行中应让位", s3.should_preempt("c_low") is True)
    check("C3 执行抢占 → 回 pending", s3.preempt("c_low") is True)
    check("C4 抢占后高优可 start", s3.start("c_high") is True)
    s3.submit("video", "c_v", priority=ms.P3_MEDIA_GEN)
    s3.start("c_v")
    s3.submit("video", "c_v2", priority=ms.P0_CANVAS_PREVIEW)
    check("C5 视频生成不可抢占（§13）", s3.should_preempt("c_v") is False)
    check("C6 preempt 直接调也被拦", s3.preempt("c_v") is False)

    # ════════════ D. DAG 拓扑 + 失效降级（§6.6） ════════════
    s4 = ms.ModuleScheduler(max_retries=0)
    s4.register_module("m", quota=4)
    s4.submit("m", "d_root")
    s4.submit("m", "d_mid", depends_on=["d_root"])
    s4.submit("m", "d_leaf", depends_on=["d_mid"])
    check("D1 依赖未完 → blocked", s4._tasks["d_mid"]["status"] == "blocked")
    check("D2 blocked 不出任务", s4.next_runnable()["task_id"] == "d_root")
    s4.start("d_root")
    s4.complete("d_root")
    check("D3 上游 done → 下游 ready", s4._tasks["d_mid"]["status"] == "ready")
    s5 = ms.ModuleScheduler(max_retries=0)
    s5.register_module("m", quota=4)
    s5.submit("m", "e_root")
    s5.submit("m", "e_mid", depends_on=["e_root"])
    s5.submit("m", "e_leaf", depends_on=["e_mid"])
    s5.start("e_root")
    s5.fail("e_root", "模拟失败")
    check("D4 上游 failed → 下游 skipped（失效降级）",
          s5._tasks["e_mid"]["status"] == "skipped")
    check("D5 连锁降级到叶", s5._tasks["e_leaf"]["status"] == "skipped")
    check("D6 降级带人话理由",
          "上游失效" in s5._tasks["e_mid"]["skip_reason"])
    s6 = ms.ModuleScheduler()
    s6.register_module("m", quota=4)
    s6.submit("m", "f1", depends_on=["f2"])
    s6.submit("m", "f2", depends_on=["f3"])
    cyc = False
    try:
        s6.submit("m", "f3", depends_on=["f1"])
    except ValueError:
        cyc = True
    check("D7 环检测拒绝", cyc is True)

    # ════════════ E. 幂等（§6.2） ════════════
    s7 = ms.ModuleScheduler()
    s7.register_module("m", quota=1)
    first = s7.submit("m", "g1", idem_key="job-42")
    dup = s7.submit("m", "g2", idem_key="job-42")
    check("E1 首次提交成功", first is not None)
    check("E2 同 idem_key 重复提交返回 None", dup is None)

    # ════════════ F. 重试（§6.2） ════════════
    s8 = ms.ModuleScheduler(max_retries=1)
    s8.register_module("m", quota=1)
    s8.submit("m", "h1")
    s8.start("h1")
    check("F1 首次失败 → retry", s8.fail("h1", "错") == "retry")
    check("F2 重试任务回到 ready", s8._tasks["h1"]["status"] == "ready")
    s8.start("h1")
    check("F3 再失败（用罄）→ failed", s8.fail("h1", "错") == "failed")

    # ════════════ G. 状态上报 + 默认单例 ════════════
    st = s5.status()
    check("G1 progress/by_status/degraded/modules 齐全",
          all(k in st for k in ("progress", "by_status", "degraded_tasks",
                                "modules")))
    check("G2 降级任务入上报", len(st["degraded_tasks"]) == 2)
    check("G3 progress = (done+skipped)/total = 2/3",
          abs(st["progress"] - 2 / 3) < 1e-9)
    sched = ms.get_scheduler()
    mods = sched.status()["modules"]
    check("G4 默认注册 §5.2 七模块", len(mods) == 7)
    check("G5 video_gen/audio_gen 不可抢占",
          mods["video_gen"]["non_preemptible"]
          and mods["audio_gen"]["non_preemptible"])

    print(f"\n{'=' * 50}\n模块调度器检查：{TOTAL - len(FAILS)}/{TOTAL} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("OK 模块调度器 DAG 核心全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
