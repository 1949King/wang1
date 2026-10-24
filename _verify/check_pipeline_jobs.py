#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 P1-3 异步任务模型（pipeline_jobs：submit/status/fetch/cancel）—— 自包含。

跑法: python _verify/check_pipeline_jobs.py

对照任务清单验收标准：
  * submit → 立即返回任务号（不阻塞）
  * status 轮询 → 阶段/进度/终态可查
  * fetch → done 附完整结果
  * 取消 → 排队真取消；运行中段间生效、结果丢弃不落盘
  * 取消穿透：client.generate / pipeline.execute 深处逐段响应（GenCancelled
    不被 except Exception 吞掉）
  * 复用 canvas_gen_jobs 同一张任务表（Agent 与画布统一任务视图）
  * 四处接线：目录表 / handlers+注册 / 动作表 / 帮助块
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

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
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _wait_job(jid: str, want, timeout: float = 8.0):
    """轮询任务直到满足条件。want 可为状态集合（元组）或谓词函数。"""
    from app.core import canvas_gen_jobs as gj

    def _match(job):
        if callable(want):
            return want(job)
        return job.get("status") in want

    deadline = time.time() + timeout
    while time.time() < deadline:
        job = gj.get_job(jid) or {}
        if _match(job):
            return job
        time.sleep(0.05)
    return gj.get_job(jid) or {}


def main() -> int:
    from app.core import canvas_gen_jobs as gj
    from app.core.ai import pipeline_jobs as pj
    from app.core.ai import provider_pool as pp
    from app.core.ai.video_generation_client import video_generation_client as client
    from app.core.ai_video_generation_pipeline import ai_video_generation_pipeline as pipeline

    _TERMINAL = ("done", "failed", "cancelled")

    # ── 池隔离：临时路径，绝不碰 ~/.shiguang/accounts.json ──
    tmpdir = tempfile.mkdtemp(prefix="sg_pipejobs_")
    pp._pool_instance = pp.ProviderPool(store_path=os.path.join(tmpdir, "accounts.json"))

    # ════════════ 1. submit 立即返回 ════════════
    t0 = time.time()

    def _runner_ok(params, report):
        report.stage("generation", "生成片段 1/2")
        report.progress(50)
        time.sleep(0.8)  # 留出轮询窗口抓取中间态（stage/progress 运行中可见）
        return {"ok": True, "success": True, "output": {"x": 1}, "error": ""}

    job = pj.submit_full_pipeline({"creative_brief": "测试简报"},
                                  runner=_runner_ok)
    dt = time.time() - t0
    jid = str(job.get("job_id") or "")
    check("提交立即返回（<1.5s，不阻塞）", dt < 1.5 and bool(jid))
    check("任务入表 kind=pipeline（与画布同一张任务表）", job.get("kind") == "pipeline")
    check("初始状态 queued/running", job.get("status") in ("queued", "running"))
    check("max_attempts 恒 1（管线级重试=双倍花钱）", job.get("max_attempts") == 1)
    check("label 自动取简报摘要", "测试简报" in str(job.get("label") or ""))

    # 运行中抓中间态：阶段标签 + 真实进度对任务层透明可见
    mid = _wait_job(jid, lambda j: j.get("stage_label") == "生成片段 1/2"
                    and j.get("progress") == 50, timeout=5.0)
    check("运行中阶段标签可见（生成片段 1/2）",
          mid.get("stage_label") == "生成片段 1/2")
    check("运行中真实进度可见（progress=50，不伪造平滑条）",
          mid.get("progress") == 50)

    fin = _wait_job(jid, _TERMINAL)
    check("任务完成 → done", fin.get("status") == "done")
    res = fin.get("result") or {}
    check("done 结果保留（output 完整）", res.get("output") == {"x": 1})
    check("终态进度诚实置 100（canvas_gen_jobs 语义）", fin.get("progress") == 100)

    # ════════════ 2. fetch 语义 ════════════
    check("fetch：done 任务返回完整结果", (pj.fetch_result(jid) or {}).get("ok") is True)
    check("fetch：不存在任务返回 None", pj.fetch_result("no_such_job") is None)

    # ════════════ 3. status 查询（单个/列表）════════════
    s = pj.job_status(jid)
    check("status 单查 ok + job_id 匹配", bool(s.get("ok")) and s.get("job_id") == jid)
    s_bad = pj.job_status("no_such_job")
    check("status 单查不存在 → ok=False", s_bad.get("ok") is False)

    def _runner_slow(params, report):
        time.sleep(1.2)
        return {"ok": True, "success": True, "output": {}, "error": ""}

    j2 = pj.submit_full_pipeline({"creative_brief": "列表测试"}, runner=_runner_slow)
    lst = pj.job_status("")
    check("status 列表模式：只列管线任务", all(
        j.get("kind") == "pipeline" for j in lst.get("jobs", [])))
    check("status 列表模式：带队列统计", "running" in lst.get("stats", {})
          and "concurrency" in lst.get("stats", {}))
    check("fetch：运行中任务返回 None", pj.fetch_result(str(j2.get("job_id"))) is None)
    _wait_job(str(j2.get("job_id")), _TERMINAL)

    # ════════════ 4. 失败语义：output 丢弃、error 保留、不重试 ════════════
    def _runner_fail(params, report):
        return {"ok": False, "message": "全链路失败X"}

    j3 = pj.submit_full_pipeline({"creative_brief": "失败测试"}, runner=_runner_fail)
    f3 = _wait_job(str(j3.get("job_id")), _TERMINAL)
    check("失败 → status=failed（不是 done）", f3.get("status") == "failed")
    check("失败 → error 保留（经 message 透传）", f3.get("error") == "全链路失败X")
    check("失败 → 结果丢弃（fetch=None）", pj.fetch_result(str(j3.get("job_id"))) is None)
    check("失败 → 只跑 1 次（attempts=1）", f3.get("attempts") == 1)

    # ════════════ 5. 预览等待 → done + paused（不是失败）════════════
    class _FakeSession:
        success = False
        stage = "waiting_for_preview_confirmation"
        error = None
        session_id = "fake_sess"

        def to_dict(self):
            return {"session_id": self.session_id, "stage": self.stage}

    class _FakeOrch:
        def execute(self, **kw):
            return _FakeSession()

    import app.core.agent_pipeline_orchestrator as orch_mod
    _orig_orch = orch_mod.agent_pipeline_orchestrator
    try:
        orch_mod.agent_pipeline_orchestrator = _FakeOrch()
        j4 = pj.submit_full_pipeline({"creative_brief": "暂停测试"})
        f4 = _wait_job(str(j4.get("job_id")), _TERMINAL)
        check("预览等待 → 任务 done（不是 failed）", f4.get("status") == "done")
        check("预览等待 → paused=True 标记",
              bool((f4.get("result") or {}).get("paused")))
    finally:
        orch_mod.agent_pipeline_orchestrator = _orig_orch

    # ════════════ 6. 运行中取消（真实协作式令牌）════════════
    def _runner_token_loop(params, report):
        # 在任务线程内逐拍检查取消令牌（与生成深处同款 API）
        from app.core.canvas_gen_jobs import current_token
        for _ in range(200):  # 最多 10s
            tok = current_token()
            if tok is not None:
                tok.raise_if_cancelled()
            time.sleep(0.05)
        return {"ok": True, "success": True, "output": {}, "error": ""}

    j5 = pj.submit_full_pipeline({"creative_brief": "取消测试"},
                                 runner=_runner_token_loop)
    r5 = _wait_job(str(j5.get("job_id")), ("running",), timeout=5.0)
    check("任务进入 running（工作线程已认领）", r5.get("status") == "running")
    cr = pj.cancel_job(str(j5.get("job_id")), "测试取消")
    check("cancel 返回 ok（running → cancelling）", bool(cr.get("ok")))
    f5 = _wait_job(str(j5.get("job_id")), _TERMINAL)
    check("运行中取消 → cancelled", f5.get("status") == "cancelled")
    check("取消 → 结果丢弃不落盘", f5.get("result") is None)
    again = pj.cancel_job(str(j5.get("job_id")))
    check("终态再取消 → 幂等 ok=False", again.get("ok") is False)

    # ════════════ 7. 取消穿透 client.generate（provider 尝试之间）════════════
    _orig_gp = client._get_provider

    def _fake_providers(name):
        def _slow_handler(**kw):
            time.sleep(0.8)     # 模拟一次阻塞的云端调用（取消不打断在途段）
            return []           # 返回失败 → 循环走下一候选 → 触发取消检查
        if name == "seedance":
            return _slow_handler
        return None

    client._get_provider = _fake_providers
    try:
        def _runner_gen(params, report):
            client.generate(prompt="取消穿透测试", duration=1.0, count=1,
                            provider="seedance")
            return {"ok": True, "success": True, "output": {}, "error": ""}

        j6 = pj.submit_full_pipeline({"creative_brief": "穿透测试"},
                                     runner=_runner_gen)
        r6 = _wait_job(str(j6.get("job_id")), ("running",), timeout=5.0)
        pj.cancel_job(str(j6.get("job_id")), "穿透取消")
        f6 = _wait_job(str(j6.get("job_id")), _TERMINAL, timeout=10.0)
        check("取消穿透 client.generate → 任务 cancelled（未被吞成 failed）",
              f6.get("status") == "cancelled")
    finally:
        client._get_provider = _orig_gp

    # ════════════ 8. 取消穿透 pipeline.execute（场景之间 + except 顺序）════════════
    _orig_gp2 = client._get_provider

    def _fake_providers2(name):
        def _slow_ok_handler(**kw):
            time.sleep(0.8)
            return [os.path.join(tmpdir, "fake_clip.mp4")]
        if name == "seedance":
            return _slow_ok_handler
        return None

    client._get_provider = _fake_providers2
    pipeline._call_llm = lambda *a, **k: ""   # LLM 不可用 → 占位分支（快且稳）
    try:
        def _runner_pipe(params, report):
            r = pipeline.execute(creative_brief="管线穿透", target_duration=10.0,
                                 clip_duration=5.0, provider="seedance")
            return {"ok": bool(r.success), "success": bool(r.success),
                    "output": {"clips": len(r.clips)}, "error": r.error or ""}

        j7 = pj.submit_full_pipeline({"creative_brief": "管线穿透"},
                                     runner=_runner_pipe)
        r7 = _wait_job(str(j7.get("job_id")), ("running",), timeout=5.0)
        pj.cancel_job(str(j7.get("job_id")), "管线穿透取消")
        f7 = _wait_job(str(j7.get("job_id")), _TERMINAL, timeout=12.0)
        check("取消穿透 pipeline.execute（场景间检查 + except 放行）",
              f7.get("status") == "cancelled")
    finally:
        client._get_provider = _orig_gp2
        try:
            del pipeline._call_llm   # 恢复真实 LLM 调用
        except AttributeError:
            pass

    # ════════════ 9. 与画布同一张任务表 ════════════
    kinds = {j.get("kind") for j in gj.list_jobs(50)}
    check("canvas_gen_jobs.list_jobs 可见管线任务（统一任务表）", "pipeline" in kinds)

    # ════════════ 10. 四处接线 ════════════
    import app.core.agent_action_registry as areg

    check("动作表：submit_pipeline=危险（花钱需确认）",
          "submit_pipeline" in areg.get_dangerous_actions())
    check("动作表：job_status/job_cancel=安全",
          {"job_status", "job_cancel"} <= set(areg.get_safe_actions()))
    check("动作映射：三动作 → 对应 capability",
          areg.ACTION_TO_CAPABILITY.get("submit_pipeline") == "pipeline.submit"
          and areg.ACTION_TO_CAPABILITY.get("job_status") == "pipeline.job_status"
          and areg.ACTION_TO_CAPABILITY.get("job_cancel") == "pipeline.job_cancel")
    help_block = areg.build_agent_actions_help_block()
    check("帮助块：三动作参数行齐全",
          all(k in help_block for k in
              ("submit_pipeline 参数", "job_status 参数", "job_cancel 参数")))

    cat_src = open(os.path.join(ROOT, "app", "core", "agent_capability_catalog.py"),
                   encoding="utf-8").read()
    check("目录表：pipeline.submit（file_write/paid）",
          '("pipeline.submit", "pipeline", "file_write", True' in cat_src)
    check("目录表：pipeline.job_status / job_cancel（read/免费）",
          '("pipeline.job_status", "pipeline", "read", False' in cat_src
          and '("pipeline.job_cancel", "pipeline", "read", False' in cat_src)

    hd_src = open(os.path.join(ROOT, "app", "core", "capability_handlers.py"),
                  encoding="utf-8").read()
    check("handlers：三方法 + 三注册齐全",
          "def submit_pipeline" in hd_src and "def job_status" in hd_src
          and "def job_cancel" in hd_src
          and 'dispatcher.register("pipeline.submit"' in hd_src
          and 'dispatcher.register("pipeline.job_status"' in hd_src
          and 'dispatcher.register("pipeline.job_cancel"' in hd_src)

    # 面板接线：任务化 + 取消按钮 + 轮询
    panel_src = open(os.path.join(ROOT, "app", "modules", "lego",
                                  "editor_agent_panel_mixin.py"),
                     encoding="utf-8").read()
    check("面板：取消按钮 + 轮询/取消方法 + 单任务守卫",
          "_edit_agent_pipeline_cancel_btn" in panel_src
          and "_poll_pipeline_job_tick" in panel_src
          and "_on_cancel_pipeline_job" in panel_src
          and "submit_full_pipeline" in panel_src)

    print(f"\n{'='*50}")
    if FAILS:
        print(f"✗ 失败 {len(FAILS)}/{TOTAL} 项:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print(f"✓ 全部通过（{TOTAL} 项）")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        try:
            from app.core import canvas_gen_jobs as _gj
            _gj._shutdown_for_tests()
        except Exception:
            pass
    sys.exit(code)
