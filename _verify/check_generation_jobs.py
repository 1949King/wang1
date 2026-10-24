# -*- coding: utf-8 -*-
"""生成任务表自检 —— 异步 / 真实进度 / 可取消 / 并发限流。

跑法：python _verify/check_generation_jobs.py
不依赖 PyQt、不发真实网络请求，用假任务验证状态机与取消语义。
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import canvas_gen_jobs as gj  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  OK   " if cond else "  FAIL ") + name + (f"  → {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def wait_terminal(job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    job = gj.get_job(job_id) or {}
    while time.time() < deadline:
        job = gj.get_job(job_id) or {}
        if job.get("status") in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    return job


def main() -> int:
    print("=== 生成任务表自检 ===")

    # 1) 提交立即返回，且不是终态
    started = threading.Event()

    def _slow(report):
        report.stage("await_provider", "等待模型返回")
        started.set()
        time.sleep(0.6)
        return {"ok": True, "image_url": "x"}

    job = gj.submit("image", _slow, label="slow")
    check("submit 立即返回 job_id", bool(job.get("job_id")), job.get("job_id"))
    check("submit 返回时状态非终态", job.get("status") in ("queued", "running"), job.get("status"))
    check("submit 返回时 progress 为 None（不伪造）", job.get("progress") is None, repr(job.get("progress")))

    started.wait(timeout=3)
    mid = gj.get_job(job["job_id"]) or {}
    check("运行中 progress 仍为 None（诚实）", mid.get("progress") is None, repr(mid.get("progress")))
    check("运行中报告阶段标签", bool(mid.get("stage_label")), str(mid.get("stage_label")))
    done = wait_terminal(job["job_id"])
    check("成功任务终态 done", done.get("status") == "done", str(done.get("status")))
    check("成功后 progress=100（终态真值）", done.get("progress") == 100, repr(done.get("progress")))
    check("成功结果已保留", bool((done.get("result") or {}).get("ok")), "")

    # 2) 失败重试计数
    calls = {"n": 0}

    def _always_fail(report):
        calls["n"] += 1
        return {"ok": False, "message": "上游 500"}

    job2 = gj.submit("video", _always_fail, label="fail", max_attempts=3, retry_backoff=1.05)
    d2 = wait_terminal(job2["job_id"], timeout=15)
    check("失败任务终态 failed", d2.get("status") == "failed", str(d2.get("status")))
    check("按 max_attempts 重试到 3 次", d2.get("attempts") == 3, str(d2.get("attempts")))
    check("实际调用次数 == 3", calls["n"] == 3, str(calls["n"]))
    check("失败保留错误信息", bool(d2.get("error")), str(d2.get("error")))

    # 3) queued 阶段取消 —— 真取消，任务体不得执行
    gate = threading.Event()
    ran = {"flag": False}

    def _blocked(report):
        ran["flag"] = True
        return {"ok": True}

    # 先占满并发，保证新任务停留在 queued
    conc = gj.queue_stats()["concurrency"]
    blockers = []
    for _ in range(conc):
        blockers.append(gj.submit("image", lambda r: (time.sleep(0.5), {"ok": True})[1], label="block"))
    job3 = gj.submit("image", _blocked, label="queued-cancel")
    st3 = gj.get_job(job3["job_id"]) or {}
    check("并发占满时新任务处于 queued", st3.get("status") == "queued", str(st3.get("status")))
    res3 = gj.cancel(job3["job_id"])
    check("queued 取消返回 ok", bool(res3.get("ok")), str(res3.get("message")))
    d3 = wait_terminal(job3["job_id"], timeout=5)
    check("queued 取消后终态 cancelled", d3.get("status") == "cancelled", str(d3.get("status")))
    check("queued 取消后任务体从未执行", ran["flag"] is False, str(ran["flag"]))
    for b in blockers:
        wait_terminal(b["job_id"], timeout=10)

    # 4) running 阶段取消 —— 结果必须丢弃
    inflight = threading.Event()

    def _long(report):
        report.stage("await_provider", "等待模型返回")
        inflight.set()
        for _ in range(40):
            time.sleep(0.05)
        return {"ok": True, "image_url": "should-be-dropped"}

    job4 = gj.submit("image", _long, label="run-cancel")
    inflight.wait(timeout=5)
    r4 = gj.cancel(job4["job_id"])
    check("running 取消返回 ok", bool(r4.get("ok")), str(r4.get("message")))
    d4 = wait_terminal(job4["job_id"], timeout=10)
    check("running 取消后终态 cancelled", d4.get("status") == "cancelled", str(d4.get("status")))
    check("取消后结果被丢弃（None）", d4.get("result") is None, repr(d4.get("result")))

    # 5) 幂等：终态再取消不报错、不复活
    r5 = gj.cancel(job4["job_id"])
    check("终态再取消返回 ok=False 且不报错", r5.get("ok") is False, str(r5.get("message")))
    check("终态再取消状态不变", (gj.get_job(job4["job_id"]) or {}).get("status") == "cancelled", "")

    # 6) 并发限流：峰值不超过 concurrency
    peak = {"v": 0}
    cur = {"v": 0}
    lock = threading.Lock()

    def _counted(report):
        with lock:
            cur["v"] += 1
            peak["v"] = max(peak["v"], cur["v"])
        time.sleep(0.25)
        with lock:
            cur["v"] -= 1
        return {"ok": True}

    many = [gj.submit("image", _counted, label=f"c{i}") for i in range(conc * 3)]
    for m in many:
        wait_terminal(m["job_id"], timeout=20)
    check(f"并发峰值 ≤ {conc}", peak["v"] <= conc, f"peak={peak['v']}")

    # 7) list / stats
    lst = gj.list_jobs(10)
    check("list_jobs 返回列表", isinstance(lst, list) and len(lst) > 0, f"n={len(lst)}")
    check("list 按创建时间倒序", lst[0].get("created_at") >= lst[-1].get("created_at"), "")
    stats = gj.queue_stats()
    check("stats 统计到已提交总数", stats.get("submitted", 0) > 0, str(stats.get("submitted")))
    check("stats 无残留 running", stats.get("running") == 0, str(stats.get("running")))

    gj._shutdown_for_tests()

    print()
    if FAILS:
        print(f"✗ 失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"   - {f}")
        return 1
    print("OK 生成任务表状态机 / 取消语义 / 并发限流全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
