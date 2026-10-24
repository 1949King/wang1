# -*- coding: utf-8 -*-
"""codeVideo 画布异步任务单测（V4.46）。"""
import time

from app.core import canvas_code_video_jobs as jobs


def _wait(job_id, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        job = jobs.get_job(job_id)
        if job and job["status"] in ("done", "error"):
            return job
        time.sleep(0.02)
    raise AssertionError("job 未在超时内结束")


def test_invalid_params_go_to_error_not_stuck():
    job = jobs.start_job({})
    final = _wait(job["id"])
    assert final["status"] == "error"
    assert "spec" in final["error"]


def test_success_emits_done_and_result(monkeypatch):
    import app.core.code_video.render_host as rh

    monkeypatch.setattr(jobs, "_compile", lambda params: ({}, ""))
    monkeypatch.setattr(
        rh, "render",
        lambda **kw: (kw["on_progress"]({"stage": "done", "percent": 100}),
                      {"ok": True, "url": "http://x/inbox_file/a.mp4"})[1],
    )
    job = jobs.start_job({"spec": {"version": "1.0"}})
    final = _wait(job["id"])
    assert final["status"] == "done"
    assert final["result"]["url"].endswith("a.mp4")


def test_render_failure_keeps_stage_and_error(monkeypatch):
    import app.core.code_video.render_host as rh

    monkeypatch.setattr(jobs, "_compile", lambda params: ({}, ""))
    monkeypatch.setattr(jobs, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(
        rh, "render",
        lambda **kw: {"ok": False, "stage": "qc", "error": "质检未通过"},
    )
    job = jobs.start_job({"spec": {"version": "1.0"}})
    final = _wait(job["id"])
    assert final["status"] == "error"
    assert "qc" in final["error"]


def test_get_job_unknown_returns_none():
    assert jobs.get_job("cv_not_exists") is None
