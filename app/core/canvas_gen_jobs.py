# -*- coding: utf-8 -*-
"""画布生成任务注册表 —— 生图 / 生视频 / 生音频的异步任务化底座。

为什么单独建这个模块
--------------------
`canvas_bridge.py` 属冻结区（stage3d-core，整文件锁），其中的 `_BATCH_JOBS` /
`_POSTPROCESS_JOBS` / `_MODEL_PRELOAD_JOBS` 无法继续扩容；本模块独立新建，
只在 `canvas_server.py`（非冻结）里挂端点，冻结区零改动。

三条硬约束
----------
1. **诚实进度**：上游 provider 是一次阻塞 HTTP，拿不到真实百分比时
   `progress` 必须保持 ``None``，只报 `stage` + `elapsed_ms`。
   前端据此画「阶段条 + 计时」，**不允许**伪造平滑百分比。
2. **协作式取消**：
   - ``queued`` → 真取消（任务从未发起）
   - ``running`` → 标记 ``cancelling``，关闭已注册的在途 HTTP 响应对象，
     阻塞中的 ``read()`` 随即抛错中断请求
   - 无论何种路径，取消后**结果一律丢弃、不落盘**
3. **并发限流**：FIFO 队列 + 固定线程池，并发数取 ``SG_GEN_CONCURRENCY``（默认 3）。

对外只需 5 个入口：``submit`` / ``get_job`` / ``list_jobs`` / ``cancel`` / ``queue_stats``。
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 状态机 ────────────────────────────────────────────────────────────
ST_QUEUED = "queued"
ST_RUNNING = "running"
ST_CANCELLING = "cancelling"
ST_DONE = "done"
ST_FAILED = "failed"
ST_CANCELLED = "cancelled"

_TERMINAL = (ST_DONE, ST_FAILED, ST_CANCELLED)

#: 阶段 → 中文标签。前端优先取 stage_label，取不到就用 stage 原文。
STAGE_LABELS: Dict[str, str] = {
    "queued": "排队中",
    "dispatch": "提交生成请求",
    "await_provider": "等待模型返回",
    "download": "拉取结果",
    "persist": "保存到本地",
    "postprocess": "后处理（超分/补帧）",
    "retry_wait": "失败重试等待",
    "done": "已完成",
    "cancelled": "已取消",
    "failed": "失败",
}

_MAX_RETAIN = 200
_DEFAULT_CONCURRENCY = 3
_MAX_ATTEMPTS_CAP = 5


def _concurrency() -> int:
    try:
        return max(1, min(16, int(os.environ.get("SG_GEN_CONCURRENCY", "") or _DEFAULT_CONCURRENCY)))
    except (TypeError, ValueError):
        return _DEFAULT_CONCURRENCY


class GenCancelled(Exception):
    """任务被取消时在任务体内抛出，用于快速跳出深层调用栈。"""


# ── 取消令牌 ──────────────────────────────────────────────────────────
class GenCancelToken:
    """协作式取消令牌。

    ``register()`` 把「可中断对象」（通常是 ``http.client.HTTPResponse``）
    登记进来；``cancel()`` 会逐个 ``close()``，让对端阻塞中的 ``read()``
    立刻抛错——这是在不改动深层调用签名的前提下中断在途请求的唯一办法。
    """

    __slots__ = ("_lock", "_closables", "_cancelled", "_reason", "_at")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._closables: List[Any] = []
        self._cancelled = False
        self._reason = ""
        self._at = 0.0

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason or "用户取消"

    @property
    def cancelled_at(self) -> float:
        return self._at

    def register(self, closable: Any) -> None:
        """登记在途对象；若已被取消，立即关闭它（避免竞态漏网）。"""
        with self._lock:
            if self._cancelled:
                _safe_close(closable)
                return
            self._closables.append(closable)

    def unregister(self, closable: Any) -> None:
        with self._lock:
            try:
                self._closables.remove(closable)
            except ValueError:
                logger.debug("忽略异常（原为 pass）: canvas_gen_jobs.py", exc_info=True)

    def cancel(self, reason: str = "用户取消") -> bool:
        with self._lock:
            if self._cancelled:
                return False
            self._cancelled = True
            self._reason = reason or "用户取消"
            self._at = time.time()
            pending, self._closables = self._closables, []
        for obj in pending:
            _safe_close(obj)
        if pending:
            logger.info("[gen-jobs] 取消时中断在途请求 %d 个", len(pending))
        return True

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise GenCancelled(self.reason)


def _safe_close(obj: Any) -> None:
    try:
        close = getattr(obj, "close", None)
        if callable(close):
            close()
    except Exception:
        logger.debug("[gen-jobs] 关闭在途对象失败", exc_info=True)


# ── 线程局部：当前任务令牌 ────────────────────────────────────────────
# 这样 `_json_request` / `open_url` 不必逐层接收 cancel_token 参数，
# 所有既有调用点零改动即可获得可中断能力。
_TLS = threading.local()


def current_token() -> Optional[GenCancelToken]:
    """取当前工作线程正在执行的任务令牌；非任务线程返回 None。"""
    return getattr(_TLS, "token", None)


def open_url(req: Any, timeout: float, **kw: Any) -> Any:
    """``urlopen`` 的取消感知包装。

    位于任务线程内时会把响应对象登记到令牌上，取消即可中断在途读取；
    非任务线程（如旧同步路径）行为与 ``urllib.request.urlopen`` 完全一致。
    """
    import urllib.request

    resp = urllib.request.urlopen(req, timeout=timeout, **kw)  # noqa: S310 - 上游渠道为配置内的 https 地址
    tok = current_token()
    if tok is not None:
        tok.register(resp)
    return resp


# ── 进度上报 ──────────────────────────────────────────────────────────
class StageReporter:
    """任务体内唯一允许的状态出口。线程安全。"""

    __slots__ = ("_job", "_lock")

    def __init__(self, job: Dict[str, Any], lock: threading.RLock) -> None:
        self._job = job
        self._lock = lock

    def stage(self, name: str, label: Optional[str] = None) -> None:
        with self._lock:
            self._job["stage"] = name
            self._job["stage_label"] = label or STAGE_LABELS.get(name, name)
            self._job["updated_at"] = time.time()
            self._job["_touched"] = True

    def progress(self, pct: Optional[float]) -> None:
        """写真实百分比。**拿不到真信号时必须传 None**，不要凭感觉估。"""
        with self._lock:
            if pct is None:
                self._job["progress"] = None
            else:
                try:
                    self._job["progress"] = max(0, min(100, round(float(pct))))
                except (TypeError, ValueError):
                    self._job["progress"] = None
            self._job["updated_at"] = time.time()

    def note(self, text: str) -> None:
        """给用户看的附注，例如「上游未提供进度信号，按阶段提示」。"""
        with self._lock:
            self._job["note"] = str(text or "")


# ── 任务表 ────────────────────────────────────────────────────────────
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.RLock()
_TASKS: Dict[str, Dict[str, Any]] = {}   # job_id -> {fn, token, report}
_QUEUE: "queue.Queue[Optional[str]]" = queue.Queue()
_WORKERS: List[threading.Thread] = []
_WORKERS_LOCK = threading.RLock()
_STATS = {"submitted": 0, "done": 0, "failed": 0, "cancelled": 0, "interrupted": 0}


def _public(job: Dict[str, Any]) -> Dict[str, Any]:
    """对外序列化：补算实时 elapsed_ms，剔除内部字段。"""
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    started = job.get("started_at") or 0.0
    finished = job.get("finished_at") or 0.0
    now = time.time()
    if job.get("status") in _TERMINAL:
        out["elapsed_ms"] = int(max(0.0, finished - started) * 1000) if started else 0
    elif started:
        out["elapsed_ms"] = int(max(0.0, now - started) * 1000)
    else:
        out["elapsed_ms"] = 0
    created = job.get("created_at") or 0.0
    out["queue_ms"] = int(max(0.0, (started or now) - created) * 1000) if created else 0
    out["cancellable"] = job.get("status") in (ST_QUEUED, ST_RUNNING)
    return out


def _prune_locked() -> None:
    """只裁已终结任务；排队/运行中的一个都不动。"""
    terminal = [j for j in _JOBS.values() if j.get("status") in _TERMINAL]
    if len(terminal) <= _MAX_RETAIN:
        return
    terminal.sort(key=lambda j: j.get("finished_at") or j.get("created_at") or 0.0)
    for job in terminal[: len(terminal) - _MAX_RETAIN]:
        jid = job.get("job_id")
        _JOBS.pop(jid, None)
        _TASKS.pop(jid, None)


def submit(
    kind: str,
    fn: Callable[[StageReporter], Dict[str, Any]],
    *,
    label: str = "",
    meta: Optional[Dict[str, Any]] = None,
    max_attempts: int = 1,
    retry_backoff: float = 1.5,
) -> Dict[str, Any]:
    """提交一个生成任务，**立即返回**任务快照（含 job_id）。

    ``fn(report)`` 返回上游结果 dict；``ok=False`` 或抛异常且未达 ``max_attempts``
    时按 ``retry_backoff`` 指数退避重试。取消后不再重试。
    """
    attempts = max(1, min(_MAX_ATTEMPTS_CAP, int(max_attempts or 1)))
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    job: Dict[str, Any] = {
        "job_id": job_id,
        "kind": kind,
        "label": label or kind,
        "status": ST_QUEUED,
        "stage": "queued",
        "stage_label": STAGE_LABELS["queued"],
        "note": "",
        "progress": None,
        "attempts": 0,
        "max_attempts": attempts,
        "error": "",
        "created_at": now,
        "started_at": 0.0,
        "finished_at": 0.0,
        "updated_at": now,
        "result": None,
        "meta": dict(meta or {}),
        "_touched": False,
    }
    token = GenCancelToken()
    with _JOBS_LOCK:
        _JOBS[job_id] = job
        _TASKS[job_id] = {
            "fn": fn,
            "token": token,
            "max_attempts": attempts,
            "retry_backoff": retry_backoff,
        }
        _STATS["submitted"] += 1
        _prune_locked()
    _ensure_workers()
    _QUEUE.put(job_id)
    logger.info("[gen-jobs] 提交 %s kind=%s label=%s", job_id, kind, label)
    return _public(job)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return _public(job) if job else None


def list_jobs(limit: int = 30) -> List[Dict[str, Any]]:
    with _JOBS_LOCK:
        jobs = list(_JOBS.values())
    jobs.sort(key=lambda j: j.get("created_at") or 0.0, reverse=True)
    return [_public(j) for j in jobs[: max(1, min(200, int(limit or 30)))]]


def cancel(job_id: str, reason: str = "用户取消") -> Dict[str, Any]:
    """取消任务。queued 真取消；running 触发在途中断；终态幂等返回。"""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        task = _TASKS.get(job_id)
        if job is None:
            return {"ok": False, "job_id": job_id, "message": "任务不存在或已过期"}
        if job.get("status") in _TERMINAL:
            return {"ok": False, "job_id": job_id, "status": job["status"], "message": "任务已结束，无需取消"}
        prev = job["status"]
        job["status"] = ST_CANCELLED if prev == ST_QUEUED else ST_CANCELLING
        job["stage"] = "cancelled"
        job["stage_label"] = STAGE_LABELS["cancelled"]
        job["error"] = reason
        job["updated_at"] = time.time()
        if prev == ST_QUEUED:
            job["finished_at"] = job["updated_at"]
            _STATS["cancelled"] += 1
    if task:
        task["token"].cancel(reason)
    logger.info("[gen-jobs] 取消 %s（原状态 %s）", job_id, prev)
    return {"ok": True, "job_id": job_id, "status": job["status"], "message": f"已取消（原状态 {prev}）"}


def queue_stats() -> Dict[str, Any]:
    with _JOBS_LOCK:
        running = sum(1 for j in _JOBS.values() if j.get("status") in (ST_RUNNING, ST_CANCELLING))
        queued = sum(1 for j in _JOBS.values() if j.get("status") == ST_QUEUED)
        retained = len(_JOBS)
    return {
        **dict(_STATS),
        "running": running,
        "queued": queued,
        "retained": retained,
        "concurrency": _concurrency(),
        "workers": len(_WORKERS),
    }


# ── 线程池 ────────────────────────────────────────────────────────────
def _ensure_workers() -> None:
    with _WORKERS_LOCK:
        want = _concurrency()
        while len(_WORKERS) < want:
            idx = len(_WORKERS) + 1
            th = threading.Thread(target=_worker_loop, daemon=True, name=f"gen-job-{idx}")
            th.start()
            _WORKERS.append(th)


def _worker_loop() -> None:
    while True:
        job_id = _QUEUE.get()
        if job_id is None:  # 停机哨兵
            return
        try:
            _run_job(job_id)
        except Exception:  # noqa: BLE001 - 工作线程必须永不退出
            logger.exception("[gen-jobs] 工作线程异常 job=%s", job_id)
        finally:
            _QUEUE.task_done()


def _run_job(job_id: str) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        task = _TASKS.get(job_id)
        if job is None or task is None:
            return
        if job.get("status") in _TERMINAL:
            _TASKS.pop(job_id, None)
            return
        job["status"] = ST_RUNNING
        job["started_at"] = time.time()
        job["updated_at"] = job["started_at"]

    token: GenCancelToken = task["token"]
    report = StageReporter(job, _JOBS_LOCK)
    fn = task["fn"]
    max_attempts = task["max_attempts"]
    backoff = task["retry_backoff"]

    prev_token = getattr(_TLS, "token", None)
    _TLS.token = token
    final_status = ST_FAILED
    try:
        for attempt in range(1, max_attempts + 1):
            with _JOBS_LOCK:
                job["attempts"] = attempt
            if token.cancelled:
                break
            report.stage("dispatch")
            try:
                result = fn(report)
                if token.cancelled:
                    break
                if isinstance(result, dict) and result.get("ok") is False:
                    err = str(result.get("message") or result.get("note") or "上游返回失败")
                    with _JOBS_LOCK:
                        job["error"] = err
                    if attempt < max_attempts:
                        report.stage("retry_wait", f"失败重试等待（第 {attempt + 1}/{max_attempts} 次）")
                        if _sleep_cancellable(backoff ** (attempt - 1), token):
                            break
                        continue
                    break
                with _JOBS_LOCK:
                    job["result"] = result if isinstance(result, dict) else {"ok": True, "value": result}
                    job["error"] = ""
                final_status = ST_DONE
                break
            except GenCancelled:
                break
            except Exception as exc:  # noqa: BLE001
                if token.cancelled:
                    break
                logger.warning("[gen-jobs] %s 第 %d 次尝试失败: %s", job_id, attempt, exc)
                with _JOBS_LOCK:
                    job["error"] = str(exc)
                if attempt < max_attempts:
                    report.stage("retry_wait", f"失败重试等待（第 {attempt + 1}/{max_attempts} 次）")
                    if _sleep_cancellable(backoff ** (attempt - 1), token):
                        break
                    continue
                break
    finally:
        _TLS.token = prev_token
        with _JOBS_LOCK:
            now = time.time()
            if token.cancelled:
                job["status"] = ST_CANCELLED
                job["stage"] = "cancelled"
                job["stage_label"] = STAGE_LABELS["cancelled"]
                if not job.get("error"):
                    job["error"] = token.reason
                # 取消必须丢弃结果，绝不落盘
                job["result"] = None
                _STATS["cancelled"] += 1
            else:
                job["status"] = final_status
                job["stage"] = "done" if final_status == ST_DONE else "failed"
                job["stage_label"] = STAGE_LABELS[job["stage"]]
                if final_status == ST_DONE:
                    job["progress"] = 100
                    _STATS["done"] += 1
                else:
                    _STATS["failed"] += 1
            job["finished_at"] = now
            job["updated_at"] = now
            _TASKS.pop(job_id, None)
            _prune_locked()
        logger.info(
            "[gen-jobs] 结束 %s status=%s attempts=%s elapsed=%.1fs",
            job_id,
            job["status"],
            job.get("attempts"),
            max(0.0, job["finished_at"] - (job.get("started_at") or job["finished_at"])),
        )


def _sleep_cancellable(seconds: float, token: GenCancelToken) -> bool:
    """可被取消打断的退避等待。返回 True 表示「已被取消」。"""
    deadline = time.time() + max(0.0, float(seconds))
    while time.time() < deadline:
        if token.cancelled:
            return True
        time.sleep(min(0.2, max(0.0, deadline - time.time())))
    return token.cancelled


def _shutdown_for_tests() -> None:
    """仅供测试：停掉工作线程。"""
    global _WORKERS
    with _WORKERS_LOCK:
        n = len(_WORKERS)
        _WORKERS = []
    for _ in range(n):
        _QUEUE.put(None)
