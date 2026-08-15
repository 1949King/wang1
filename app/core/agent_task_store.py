# -*- coding: utf-8 -*-
"""Agent 任务持久化（JSON，非 IndexedDB）。重启后 running/planning 一律 paused。"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_STORAGE = os.path.join("data", "agent_tasks.json")
_MAX_TASKS = 80

_LEGAL = {
    "queued": {"planning", "running", "stopped", "failed"},
    "planning": {"running", "paused", "failed", "stopped", "waiting_approval"},
    "running": {
        "waiting_approval",
        "paused",
        "completed",
        "failed",
        "stopped",
        "planning",
    },
    "waiting_approval": {"running", "paused", "stopped", "failed", "completed"},
    "paused": {"running", "planning", "stopped", "failed"},
    "completed": set(),
    "failed": {"planning", "running"},
    "stopped": set(),
}


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return "t_" + uuid.uuid4().hex[:10]


class AgentTaskStore:
    _instance: Optional["AgentTaskStore"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._mu = threading.RLock()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._load_and_pause_inflight()

    def _load_and_pause_inflight(self) -> None:
        if not os.path.isfile(_STORAGE):
            return
        try:
            raw = json.loads(open(_STORAGE, encoding="utf-8").read() or "[]")
        except Exception as e:
            logger.warning("[AgentTaskStore] 加载失败: %s", e)
            return
        if not isinstance(raw, list):
            return
        with self._mu:
            for row in raw[-_MAX_TASKS:]:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                st = str(row.get("status") or "")
                if st in ("planning", "running", "waiting_approval", "queued"):
                    row["status"] = "paused"
                    row["pausedReason"] = "app_restart"
                    row["updatedAt"] = _now()
                self._tasks[str(row["id"])] = row

    def _flush(self) -> None:
        try:
            os.makedirs(os.path.dirname(_STORAGE), exist_ok=True)
            rows = sorted(self._tasks.values(), key=lambda t: t.get("updatedAt") or 0)
            with open(_STORAGE, "w", encoding="utf-8") as f:
                json.dump(rows[-_MAX_TASKS:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("[AgentTaskStore] flush: %s", e)

    def create(
        self,
        *,
        session_id: str,
        goal: str,
        mode: str,
        source: str = "canvas",
    ) -> Dict[str, Any]:
        task = {
            "id": _new_id(),
            "session_id": session_id,
            "goal": (goal or "")[:500],
            "mode": mode,
            "source": source,
            "status": "planning",
            "steps": [],
            "modelRounds": 0,
            "toolCallCount": 0,
            "createdAt": _now(),
            "updatedAt": _now(),
        }
        with self._mu:
            self._tasks[task["id"]] = task
            self._flush()
        return dict(task)

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._mu:
            t = self._tasks.get(task_id)
            return dict(t) if t else None

    def list_for_session(self, session_id: str, limit: int = 12) -> List[Dict[str, Any]]:
        with self._mu:
            rows = [t for t in self._tasks.values() if t.get("session_id") == session_id]
        rows.sort(key=lambda t: t.get("updatedAt") or 0, reverse=True)
        return [dict(t) for t in rows[:limit]]

    def transition(self, task_id: str, new_status: str, **extra) -> Dict[str, Any]:
        with self._mu:
            t = self._tasks.get(task_id)
            if not t:
                raise KeyError(task_id)
            cur = str(t.get("status") or "queued")
            allowed = _LEGAL.get(cur, set())
            if new_status != cur and new_status not in allowed:
                raise ValueError(f"AGENT_INVALID_TRANSITION:{cur}->{new_status}")
            t["status"] = new_status
            t["updatedAt"] = _now()
            for k, v in extra.items():
                if k == "steps":
                    continue
                t[k] = v
            self._flush()
            return dict(t)

    def add_step(
        self,
        task_id: str,
        *,
        title: str,
        status: str = "running",
        detail: Any = None,
    ) -> Dict[str, Any]:
        step = {
            "id": "s_" + uuid.uuid4().hex[:8],
            "title": title,
            "status": status,
            "detail": detail,
            "ts": _now(),
        }
        with self._mu:
            t = self._tasks.get(task_id)
            if not t:
                raise KeyError(task_id)
            steps = list(t.get("steps") or [])
            steps.append(step)
            t["steps"] = steps[-40:]
            t["updatedAt"] = _now()
            if status == "running":
                t["currentStepId"] = step["id"]
            self._flush()
            return dict(step)

    def bump_tool(self, task_id: str) -> None:
        with self._mu:
            t = self._tasks.get(task_id)
            if t:
                t["toolCallCount"] = int(t.get("toolCallCount") or 0) + 1
                t["updatedAt"] = _now()

    def bump_round(self, task_id: str) -> None:
        with self._mu:
            t = self._tasks.get(task_id)
            if t:
                t["modelRounds"] = int(t.get("modelRounds") or 0) + 1
                t["updatedAt"] = _now()


agent_tasks = AgentTaskStore()
legal_transitions = _LEGAL
