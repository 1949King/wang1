"""模块调度器（规格书第二篇 §5-7，V4.38.3 切片⑩）
====================================================================
职责（§5.1）：模块注册/发现、任务拆解下发、**资源配额限流**、
多模块**优先级仲裁**、**依赖 DAG 拓扑调度**、状态上报。

规格 → 桌面单机版的落地映射（诚实边界）：
  - **模块注册中心**（§6.1）：register/deregister + 能力/配额/健康度；
  - **独立优先级队列**（§6.2）：P0–P4，依赖阻塞/暂停/取消/重试/**幂等**；
  - **优先级仲裁**（§6.3）：P0 画布预览 > P1 画布生成 > P2 AI 剪辑 >
    P3 视频音频生成 > P4 后台批量；高优先级可抢占低优先级，
    **视频生成任务不可抢占**（non_preemptible 标记）；
  - **配额管理器**（§6.4）：单模块并发上限，杜绝单模块吃光整机；
  - **依赖调度器**（§6.6）：DAG 拓扑就绪；提交时环检测；
    **动态依赖失效降级**——上游失败/取消，下游标 skipped（不静默照跑）；
  - **进程级沙箱隔离**（§6.5）：桌面单进程应用**不落地**——模块以
    线程内执行体运行，崩溃隔离由任务状态机（failed/重试）兜底。
    这是与规格书的显性偏差，在此声明而非静默省略。

本模块是**纯状态机 + 调度决策**，不开线程：执行由调用方驱动
（``next_runnable`` → 执行 → ``complete/fail``），与 pipeline_jobs 等
既有任务表对接时作其「大脑」。异常不抛（除参数断言）、RLock。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.core.ai.module_scheduler")

# 优先级档位（§6.3，数字越小越高）
P0_CANVAS_PREVIEW = 0   # 画布预览
P1_CANVAS_GEN = 1       # 画布生成
P2_AI_EDIT = 2          # AI 剪辑
P3_MEDIA_GEN = 3        # 视频/音频生成
P4_BACKGROUND = 4       # 后台批量

_STATUSES = ("pending", "blocked", "ready", "running",
             "done", "failed", "cancelled", "skipped")
_TERMINAL = ("done", "failed", "cancelled", "skipped")


class ModuleScheduler:
    """模块级 DAG 调度核心（纯状态机，调用方驱动执行）。"""

    def __init__(self, max_retries: int = 1):
        self._lock = threading.RLock()
        self._max_retries = max(0, int(max_retries))
        # {module_id: {"label","quota","running","healthy","paused",
        #              "non_preemptible"}}
        self._modules: Dict[str, Dict[str, Any]] = {}
        # {task_id: task}
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._idem: Dict[str, str] = {}          # idem_key → task_id
        self._seq = 0

    # ────────────── 模块注册中心（§6.1） ──────────────

    def register_module(self, module_id: str, *, label: str = "",
                        quota: int = 2, non_preemptible: bool = False) -> None:
        """注册/更新模块。quota=并发上限；non_preemptible=任务不可抢占
        （视频/长音频生成按 §13 禁止抢占）。"""
        if not module_id:
            return
        with self._lock:
            m = self._modules.setdefault(module_id, {
                "label": label or module_id, "quota": max(1, int(quota)),
                "running": 0, "healthy": True, "paused": False,
                "non_preemptible": bool(non_preemptible),
                "registered_at": time.time(),
            })
            m["quota"] = max(1, int(quota))
            m["non_preemptible"] = bool(non_preemptible)
            if label:
                m["label"] = label

    def deregister_module(self, module_id: str) -> None:
        with self._lock:
            self._modules.pop(module_id, None)

    def pause_module(self, module_id: str, paused: bool = True) -> None:
        with self._lock:
            if module_id in self._modules:
                self._modules[module_id]["paused"] = bool(paused)

    def set_healthy(self, module_id: str, healthy: bool) -> None:
        with self._lock:
            if module_id in self._modules:
                self._modules[module_id]["healthy"] = bool(healthy)

    # ────────────── 任务提交（§6.2：幂等 + 依赖 + 环检测） ──────────────

    def submit(self, module_id: str, task_id: str,
               payload: Optional[Dict[str, Any]] = None,
               priority: int = P3_MEDIA_GEN,
               depends_on: Optional[List[str]] = None,
               idem_key: str = "") -> Optional[Dict[str, Any]]:
        """提交任务。重复 idem_key → 返回 None（幂等，§6.2）；环 → ValueError。"""
        if not module_id or not task_id:
            return None
        deps = list(depends_on or [])
        with self._lock:
            if idem_key and idem_key in self._idem:
                logger.info("[module_scheduler] 幂等命中：%s 已提交过", idem_key)
                return None
            if task_id in self._tasks:
                return None
            deps = [d for d in deps if d != task_id]
            if self._would_cycle_locked(task_id, deps):
                raise ValueError(f"依赖成环：{task_id} → {deps}")
            self._seq += 1
            task = {
                "task_id": task_id, "module_id": module_id,
                "payload": dict(payload) if isinstance(payload, dict) else {},
                "priority": min(4, max(0, int(priority))),
                "depends_on": deps,
                "status": "pending", "attempts": 0,
                "submitted_at": time.time(), "seq": self._seq,
                "started_at": None, "finished_at": None,
                "result": None, "error": "", "skip_reason": "",
            }
            self._tasks[task_id] = task
            if idem_key:
                self._idem[idem_key] = task_id
            self._refresh_locked(task_id)
            return dict(task)

    def _would_cycle_locked(self, task_id: str, deps: List[str]) -> bool:
        """从 deps 沿既有依赖链能不能走回 task_id（DFS）。"""
        stack = list(deps)
        seen = set()
        while stack:
            cur = stack.pop()
            if cur == task_id:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            t = self._tasks.get(cur)
            if t:
                stack.extend(t["depends_on"])
        return False

    def _refresh_locked(self, task_id: str) -> None:
        """重算单任务状态：依赖就绪 → ready；依赖失效 → skipped（§6.6 降级）。"""
        t = self._tasks.get(task_id)
        if not t or t["status"] not in ("pending", "blocked"):
            return
        dep_failed = []
        for d in t["depends_on"]:
            dt = self._tasks.get(d)
            if dt is None or dt["status"] in ("failed", "cancelled", "skipped"):
                dep_failed.append(d)
        if dep_failed:
            t["status"] = "skipped"
            t["skip_reason"] = f"上游失效降级：{','.join(dep_failed)}"
            t["finished_at"] = time.time()
            logger.info("[module_scheduler] %s 依赖失效 → skipped（%s）",
                        task_id, t["skip_reason"])
            # 下游连锁刷新
            for other in self._tasks.values():
                if task_id in other["depends_on"]:
                    self._refresh_locked(other["task_id"])
            return
        all_done = all(
            (self._tasks.get(d) or {}).get("status") == "done"
            for d in t["depends_on"])
        t["status"] = "ready" if all_done else "blocked"

    # ────────────── 调度决策（§6.3 仲裁 + §6.4 配额） ──────────────

    def next_runnable(self) -> Optional[Dict[str, Any]]:
        """取下一个可运行任务：ready 中优先级最高者（同级按提交序）。

        约束：模块存在、未暂停、健康、并发未超配额。
        """
        with self._lock:
            best: Optional[Dict[str, Any]] = None
            for t in self._tasks.values():
                if t["status"] != "ready":
                    continue
                m = self._modules.get(t["module_id"])
                if m is None or m["paused"] or not m["healthy"]:
                    continue
                if m["running"] >= m["quota"]:
                    continue
                if best is None or (t["priority"], t["seq"]) < (best["priority"],
                                                                best["seq"]):
                    best = t
            return dict(best) if best else None

    def should_preempt(self, running_task_id: str) -> bool:
        """仲裁（§6.3）：有更高优先级的 ready 任务等配额时，
        低优先级运行中任务**可抢占才**让位（视频生成不可抢占，§13）。
        """
        with self._lock:
            rt = self._tasks.get(running_task_id)
            if not rt or rt["status"] != "running":
                return False
            m = self._modules.get(rt["module_id"])
            if m is None or m["non_preemptible"]:
                return False  # 视频/长音频生成禁止抢占
            for t in self._tasks.values():
                if t["status"] == "ready" and t["priority"] < rt["priority"]:
                    return True
            return False

    # ────────────── 生命周期（调用方执行后回报） ──────────────

    def start(self, task_id: str) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
            m = self._modules.get(t["module_id"]) if t else None
            if not t or t["status"] != "ready" or not m:
                return False
            if m["running"] >= m["quota"]:
                return False
            t["status"] = "running"
            t["attempts"] += 1
            t["started_at"] = time.time()
            m["running"] += 1
            return True

    def complete(self, task_id: str, result: Any = None) -> None:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t["status"] != "running":
                return
            t["status"] = "done"
            t["result"] = result
            t["finished_at"] = time.time()
            self._release_locked(t)
            for other in self._tasks.values():  # 解锁下游
                if task_id in other["depends_on"]:
                    self._refresh_locked(other["task_id"])

    def fail(self, task_id: str, error: str = "") -> str:
        """失败回报：可重试 → 回 pending；否则 failed（触发下游失效降级）。

        Returns: "retry" | "failed" | "ignored"
        """
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t["status"] != "running":
                return "ignored"
            t["error"] = str(error)
            self._release_locked(t)
            if t["attempts"] <= self._max_retries:
                t["status"] = "pending"
                self._refresh_locked(t["task_id"])
                logger.info("[module_scheduler] %s 失败重试（attempts=%d）",
                            task_id, t["attempts"])
                return "retry"
            t["status"] = "failed"
            t["finished_at"] = time.time()
            for other in self._tasks.values():  # 下游连锁降级
                if task_id in other["depends_on"]:
                    self._refresh_locked(other["task_id"])
            return "failed"

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t["status"] in _TERMINAL:
                return False
            if t["status"] == "running":
                self._release_locked(t)
            t["status"] = "cancelled"
            t["finished_at"] = time.time()
            for other in self._tasks.values():
                if task_id in other["depends_on"]:
                    self._refresh_locked(other["task_id"])
            return True

    def preempt(self, task_id: str) -> bool:
        """执行抢占（先 should_preempt 判定）：运行中 → 回 pending 待重排。"""
        with self._lock:
            if not self.should_preempt(task_id):
                return False
            t = self._tasks[task_id]
            self._release_locked(t)
            t["status"] = "pending"
            self._refresh_locked(task_id)
            logger.info("[module_scheduler] %s 被高优先级任务抢占，回队列", task_id)
            return True

    def _release_locked(self, t: Dict[str, Any]) -> None:
        m = self._modules.get(t["module_id"])
        if m and m["running"] > 0:
            m["running"] -= 1

    # ────────────── 状态上报（§5.1/§7） ──────────────

    def status(self) -> Dict[str, Any]:
        """整体进度 / 模块状态 / 降级信息（向上层输出）。"""
        with self._lock:
            by_status: Dict[str, int] = {s: 0 for s in _STATUSES}
            for t in self._tasks.values():
                by_status[t["status"]] = by_status.get(t["status"], 0) + 1
            total = len(self._tasks)
            done = by_status.get("done", 0)
            degraded = by_status.get("skipped", 0)
            return {
                "total": total,
                "progress": (done + degraded) / total if total else 1.0,
                "by_status": by_status,
                "degraded_tasks": [
                    {"task_id": t["task_id"], "reason": t["skip_reason"]}
                    for t in self._tasks.values() if t["status"] == "skipped"],
                "modules": {
                    mid: {"label": m["label"], "quota": m["quota"],
                          "running": m["running"], "paused": m["paused"],
                          "healthy": m["healthy"],
                          "non_preemptible": m["non_preemptible"]}
                    for mid, m in self._modules.items()},
            }


# ═══════════════════════════════════════════════════════════
# 单例 + 默认模块清单（§5.2 托管模块）
# ═══════════════════════════════════════════════════════════

_SCHED: Optional[ModuleScheduler] = None
_SCHED_LOCK = threading.Lock()

# §5.2 托管模块清单（module_id → 默认配额/是否不可抢占/默认优先级）
DEFAULT_MODULES = {
    "script_parse": {"label": "脚本解析", "quota": 2,
                     "non_preemptible": False},
    "video_gen": {"label": "视频生成", "quota": 1,
                  "non_preemptible": True},   # §13 禁止抢占
    "audio_gen": {"label": "音频生成", "quota": 1,
                  "non_preemptible": True},
    "ai_edit": {"label": "AI 剪辑", "quota": 1,
                "non_preemptible": False},
    "canvas_gen": {"label": "画布生成", "quota": 2,
                   "non_preemptible": False},
    "fusion": {"label": "融合仲裁", "quota": 1,
               "non_preemptible": False},
    "postprocess": {"label": "后处理转码", "quota": 2,
                    "non_preemptible": False},
}


def get_scheduler() -> ModuleScheduler:
    """进程级单例（默认注册 §5.2 托管模块清单）。"""
    global _SCHED
    if _SCHED is None:
        with _SCHED_LOCK:
            if _SCHED is None:
                s = ModuleScheduler()
                for mid, cfg in DEFAULT_MODULES.items():
                    s.register_module(mid, **cfg)
                _SCHED = s
    return _SCHED
