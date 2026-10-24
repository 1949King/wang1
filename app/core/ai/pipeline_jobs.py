# -*- coding: utf-8 -*-
"""管线任务化（P1-3）—— submit / status / fetch / cancel 异步任务模型。

把同步阻塞的全链路执行（分流→生成/剪辑→预览→打分→脚本→精剪→成片）包成
可查询、可取消的后台任务：提交立即返回任务号，长视频不再占死一个线程无人知晓。

为什么复用 canvas_gen_jobs 这张任务表
------------------------------------
``app/core/canvas_gen_jobs.py`` 已是生产级任务底座（画布生图/生视频/生音频在用）：
状态机 / 协作式取消 / 诚实进度 / 重试退避 / 并发限流 / 终结裁剪一应俱全。
管线任务化**不另起炉灶**——Agent 与画布看到同一套任务状态，取消/进度/统计语义一致。

取消如何穿透到生成深处
----------------------
canvas_gen_jobs 把 GenCancelToken 放在**线程局部**，_run_job 执行任务体前绑定。
本模块的任务体在**同一线程**里同步执行全链路：
    fn → agent_pipeline_orchestrator.execute → ai_video_generation_pipeline.execute
       → video_generation_client.generate（全程同线程，无再分叉）
因此深处的逐段 ``raise_if_cancelled()`` 天然生效：
- 场景与场景之间、provider 尝试之间、回溯重试之间 → 立即取消
- 正在跑的单段（一次阻塞调用）不打断，跑完即止（诚实降级，不伪造瞬时中断）
- 无论何种路径，取消后**结果一律丢弃、不落盘**（canvas_gen_jobs 硬约束）

进度如何上报
------------
同样走线程局部：任务体把 StageReporter 绑到本模块的 ``_TLS.reporter``，
``ai_video_generation_pipeline.execute`` 深处经 ``pipeline_stage()`` /
``pipeline_progress()`` 便捷函数取用——orchestrator / 管线的签名一个都不用改。
诚实纪律沿用 canvas_gen_jobs：只报真实信号（生成 i/N 完成数），不伪造平滑百分比。

为什么直连 orchestrator 而不走 capability_dispatcher
---------------------------------------------------
① dispatcher.invoke 与 orchestrator.execute 的 catch-all 会把 GenCancelled
   （取消控制流）吞成「执行失败」——两处已加 ``except GenCancelled: raise`` 放行，
   但任务体直连 orchestrator 仍是最短路径（全链路逻辑零重复）；
② 机器续跑（任务体内）无需再过一遍面向人工会话的 policy 门，
   提交动作本身（pipeline.submit）在 Agent 侧已过门。

失败语义（诚实降级）
--------------------
- 全链路 success=False → 任务 failed，**详细 output 不保留**（canvas_gen_jobs 对
  ok=False 的结果按失败丢弃），但 session.error 经 ``message`` 写进任务 error；
  面板/Agent 按任务 error 提示即可，与旧 invoke_async 路径口径一致。
- 预览等待（stage=waiting_for_preview_confirmation）不是失败：任务记 done +
  ``paused=True``，等用户点「确认预览并继续」再提交**新任务**续跑。
- max_attempts 恒为 1：管线级自动重试 = 双倍花钱，重试交给段内回溯与额度池换号。
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 管线任务在 gen-jobs 表里的 kind 标识（画布侧为 image/video/audio）
JOB_KIND = "pipeline"

#: 任务体签名：fn(params, report) -> dict（{"ok": bool, ...}）
_Runner = Callable[[Dict[str, Any], Any], Dict[str, Any]]

# ── 线程局部：阶段上报口（取消令牌由 canvas_gen_jobs 自己的 _TLS 管理）──
_TLS = threading.local()


def current_reporter() -> Optional[Any]:
    """取当前任务线程绑定的 StageReporter；非任务线程返回 None。"""
    return getattr(_TLS, "reporter", None)


def pipeline_stage(stage: str, label: Optional[str] = None) -> None:
    """向当前任务上报阶段；无任务上下文（直连调用）时静默跳过。"""
    rep = current_reporter()
    if rep is None:
        return
    try:
        rep.stage(stage, label)
    except Exception:
        logger.debug("[pipeline-jobs] 阶段上报失败", exc_info=True)


def pipeline_progress(pct: Optional[float]) -> None:
    """向当前任务上报真实完成百分比（拿不到真信号时传 None，不伪造）。"""
    rep = current_reporter()
    if rep is None:
        return
    try:
        rep.progress(pct)
    except Exception:
        logger.debug("[pipeline-jobs] 进度上报失败", exc_info=True)


def raise_if_cancelled() -> None:
    """任务线程内已取消 → 抛 GenCancelled；非任务线程/无底座时静默返回。

    供生成深处（video_generation_client / 管线循环）逐段调用；
    调用方**不要**把本函数包进 catch-all try（会把取消吞掉）。
    """
    try:
        from app.core.canvas_gen_jobs import current_token
    except Exception:
        return  # 伪包/独立加载：无任务底座，不存在取消
    tok = current_token()
    if tok is not None:
        tok.raise_if_cancelled()


# ── 默认任务体：直连 orchestrator（与 run_full 处理器同参透传，零逻辑重复）──

def _default_runner(params: Dict[str, Any], report: Any) -> Dict[str, Any]:
    from app.core.agent_pipeline_orchestrator import agent_pipeline_orchestrator

    session = agent_pipeline_orchestrator.execute(
        materials=params.get("materials") or [],
        creative_brief=str(params.get("creative_brief") or ""),
        platform=str(params.get("platform") or "douyin"),
        target_duration=float(params.get("target_duration") or 30.0),
        clip_duration=float(params.get("clip_duration") or 5.0),
        provider=str(params.get("provider") or "auto"),
        auto_preview_pass=bool(params.get("auto_preview_pass", False)),
    )
    stage = str(getattr(session, "stage", "") or "")
    out = session.to_dict() if hasattr(session, "to_dict") else dict(session or {})
    return {
        # 预览等待是正常暂停，不是失败：任务记 done + paused，由 UI/Agent 决定续跑
        "ok": bool(getattr(session, "success", False))
        or stage == "waiting_for_preview_confirmation",
        "success": bool(getattr(session, "success", False)),
        "paused": stage == "waiting_for_preview_confirmation",
        "stage": stage,
        "output": out,
        "error": str(getattr(session, "error", "") or ""),
        "request_id": str(getattr(session, "session_id", "") or ""),
    }


def submit_full_pipeline(params: Dict[str, Any], *, label: str = "",
                         runner: Optional[_Runner] = None) -> Dict[str, Any]:
    """提交全链路任务，**立即返回**任务快照（含 job_id）。

    params 与 ``pipeline.run_full`` 完全一致：
        materials / creative_brief / platform / target_duration /
        clip_duration / provider / auto_preview_pass

    runner 仅供测试注入；生产恒走 _default_runner（直连 orchestrator）。
    max_attempts 恒 1（管线级重试 = 双倍花钱；重试交给段内回溯 + 额度池换号）。
    """
    from app.core.canvas_gen_jobs import submit as _submit

    run = runner or _default_runner
    brief = str(params.get("creative_brief") or "")
    materials = params.get("materials") or []
    if not label:
        label = (f"生成：{brief[:24]}" if brief
                 else f"剪辑：素材 {len(materials)} 个")

    def fn(report: Any) -> Dict[str, Any]:
        prev = getattr(_TLS, "reporter", None)
        _TLS.reporter = report
        try:
            report.stage("dispatch", "提交全链路请求")
            return run(dict(params), report)
        finally:
            _TLS.reporter = prev

    return _submit(JOB_KIND, fn, label=label,
                   meta={"params": _summarize(params)}, max_attempts=1)


def _summarize(params: Dict[str, Any]) -> Dict[str, Any]:
    """任务 meta 用的参数摘要（不塞大对象进任务表）。"""
    return {
        "creative_brief": str(params.get("creative_brief") or "")[:80],
        "materials": len(params.get("materials") or []),
        "provider": str(params.get("provider") or "auto"),
        "platform": str(params.get("platform") or "douyin"),
        "target_duration": params.get("target_duration", 30.0),
        "clip_duration": params.get("clip_duration", 5.0),
    }


def job_status(job_id: str = "", *, limit: int = 10) -> Dict[str, Any]:
    """查任务状态：给 job_id 查单个（done 附完整结果 = fetch 语义）；
    不给则列近期管线任务 + 队列统计。"""
    from app.core.canvas_gen_jobs import get_job, list_jobs, queue_stats

    jid = str(job_id or "").strip()
    if jid:
        job = get_job(jid)
        if job is None:
            return {"ok": False, "job_id": jid, "message": "任务不存在或已过期"}
        return {"ok": True, **job}
    jobs = [j for j in list_jobs(limit=max(1, min(50, int(limit or 10))))
            if j.get("kind") == JOB_KIND]
    return {"ok": True, "jobs": jobs, "stats": queue_stats()}


def fetch_result(job_id: str) -> Optional[Dict[str, Any]]:
    """fetch 语义：任务 done 时返回完整结果 dict；未完成/失败/取消返回 None。"""
    from app.core.canvas_gen_jobs import get_job

    job = get_job(str(job_id or "").strip()) or {}
    if job.get("status") != "done":
        return None
    return job.get("result") if isinstance(job.get("result"), dict) else None


def cancel_job(job_id: str, reason: str = "用户取消") -> Dict[str, Any]:
    """取消任务。queued 真取消；running 段间生效（结果丢弃不落盘）；终态幂等。"""
    from app.core.canvas_gen_jobs import cancel as _cancel

    return _cancel(str(job_id or "").strip(), reason)
