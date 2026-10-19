# -*- coding: utf-8 -*-
"""画布 codeVideo 异步渲染任务（V4.46 · 2026-10-20）

为什么独立任务层：
- 渲染是分钟级（Chromium 逐帧 + ffmpeg），不能在 HTTP 线程同步跑；
- 前端节点需要「立刻拿到 job_id + SSE 看进度」；
- 与 `pipeline_jobs` 同纪律：一任务一线程、状态可查、失败带 stage，**不假装成功**。

边界：
- 不做取消（底层 worker 是子进程，强杀会留半成品；V4.46 先只支持状态查询）；
- 任务只保留最近 20 个 / 1 小时，避免内存膨胀；
- 进度是**粗粒度 stage**（compile/security/resolve/page/qc/render/validate/publish/done）。
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_MAX_JOBS = 20
_JOB_TTL = 3600.0
_JOBS: Dict[str, Dict[str, Any]] = {}
_ORDER: list[str] = []
_LOCK = threading.Lock()


def _emit(event: str, payload: Dict[str, Any]) -> None:
    try:
        from app.core.canvas_bridge import broadcast_agent_event, make_agent_event

        broadcast_agent_event(make_agent_event(event, payload))
    except Exception:  # SSE 是旁路，广播失败不影响任务
        logger.debug("code video event broadcast failed", exc_info=True)


def _prune_locked() -> None:
    now = time.time()
    while _ORDER:
        job = _JOBS.get(_ORDER[0])
        if job is None:
            _ORDER.pop(0)
            continue
        finished = job.get("status") in ("done", "error")
        if finished and now - float(job.get("updated_at") or 0) > _JOB_TTL:
            _ORDER.pop(0)
            _JOBS.pop(job["id"], None)
            continue
        if len(_ORDER) > _MAX_JOBS:
            _ORDER.pop(0)
            _JOBS.pop(job["id"], None)
            continue
        break


def _compile(params: Dict[str, Any]):
    """返回 (compiled, error)。spec/storyboard 二选一，与能力层同一套校验。"""
    from app.core.code_video.spec import (
        CodeVideoSpec,
        compile_spec,
        from_storyboard,
        validate_spec,
    )

    spec_data = params.get("spec")
    storyboard = params.get("storyboard")
    warnings = []
    if spec_data is None and storyboard is None:
        return None, "需要 spec（CodeVideoSpec JSON）或 storyboard（分镜表数组）二选一"
    if spec_data is not None:
        if not isinstance(spec_data, dict):
            return None, "spec 必须是对象"
        errors = validate_spec(spec_data)
        if errors:
            return None, "spec 结构校验失败：" + "; ".join(errors)
        try:
            spec = CodeVideoSpec.from_dict(spec_data)
        except (TypeError, ValueError, KeyError) as exc:
            return None, f"spec 无法反序列化：{exc}"
    else:
        if not isinstance(storyboard, list):
            return None, "storyboard 必须是数组"
        spec, warnings = from_storyboard(
            storyboard,
            width=int(params.get("width") or 1080),
            height=int(params.get("height") or 1920),
            fps=int(params.get("fps") or 30),
            spec_id=str(params.get("spec_id") or ""),
        )
        if spec is None:
            return None, "分镜表无法转成 spec：" + "; ".join(warnings or ["未知原因"])
    compiled, errors = compile_spec(spec)
    if compiled is None:
        return None, "spec 未通过契约编译：" + "; ".join(errors)
    return compiled, ""


def _run(job_id: str, params: Dict[str, Any]) -> None:
    from app.core.code_video.render_host import render

    def progress(info: Dict[str, Any]) -> None:
        stage = str(info.get("stage") or "")
        percent = int(info.get("percent") or 0)
        detail = str(info.get("detail") or "")
        with _LOCK:
            job = _JOBS.get(job_id)
            if job is None:
                return
            job.update({
                "status": "running", "stage": stage, "percent": percent,
                "detail": detail, "updated_at": time.time(),
            })
        _emit("code_video.progress", {
            "job_id": job_id, "stage": stage, "percent": percent, "detail": detail,
        })

    try:
        compiled, error = _compile(params)
        if compiled is None:
            raise RuntimeError(error)
        result = render(
            compiled=compiled,
            output_name=str(params.get("output_name") or ""),
            qc=bool(params.get("qc", True)),
            on_progress=progress,
        )
        if not result.get("ok"):
            raise RuntimeError(
                f"{result.get('stage') or 'render'}: {result.get('error') or '未知错误'}"
            )
        with _LOCK:
            job = _JOBS.get(job_id)
            if job is not None:
                job.update({
                    "status": "done", "stage": "done", "percent": 100,
                    "detail": "渲染完成", "result": result,
                    "updated_at": time.time(),
                })
        _emit("code_video.done", {"job_id": job_id, "result": result})
    except Exception as exc:  # 任务失败必须落到状态与 SSE，不吞
        logger.exception("code video job failed: %s", job_id)
        with _LOCK:
            job = _JOBS.get(job_id)
            if job is not None:
                job.update({
                    "status": "error", "stage": "error", "percent": 0,
                    "detail": str(exc)[:500], "error": str(exc),
                    "updated_at": time.time(),
                })
        _emit("code_video.error", {"job_id": job_id, "error": str(exc)})


def start_job(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建任务并立即返回 job 快照；参数校验在后台线程里做（失败也会进状态）。"""
    params = dict(params or {})
    job_id = "cv_" + uuid.uuid4().hex[:12]
    now = time.time()
    with _LOCK:
        _prune_locked()
        _JOBS[job_id] = {
            "id": job_id,
            "status": "queued",
            "stage": "queued",
            "percent": 0,
            "detail": "排队中",
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error": "",
        }
        _ORDER.append(job_id)
        job = dict(_JOBS[job_id])
    threading.Thread(target=_run, args=(job_id, params), name=f"CodeVideoJob-{job_id}",
                     daemon=True).start()
    return job


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None
