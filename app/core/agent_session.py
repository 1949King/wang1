# -*- coding: utf-8 -*-
"""进程内 Agent 会话：模式、预算计数、停止标志、对话历史。重启后任务视为暂停（不自动续跑）。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.agent_policy import (
    MAX_MODEL_ROUNDS,
    MAX_TOOL_CALLS,
    MODE_COLLABORATIVE,
    normalize_mode,
)

MAX_HISTORY_TURNS = 20
MAX_HISTORY_CHARS = 12000


@dataclass
class AgentSessionState:
    session_id: str
    mode: str = MODE_COLLABORATIVE
    model_rounds: int = 0
    tool_calls: int = 0
    stopped: bool = False
    paused: bool = False
    updated_at: float = field(default_factory=time.time)
    history: List[Dict[str, Any]] = field(default_factory=list)


class AgentSessionStore:
    _instance: Optional["AgentSessionStore"] = None
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
        self._sessions: Dict[str, AgentSessionState] = {}
        self._mu = threading.RLock()

    def get(self, session_id: str) -> AgentSessionState:
        sid = (session_id or "default").strip() or "default"
        with self._mu:
            st = self._sessions.get(sid)
            if st is None:
                st = AgentSessionState(session_id=sid)
                self._sessions[sid] = st
            return st

    def set_mode(self, session_id: str, mode: str) -> AgentSessionState:
        st = self.get(session_id)
        with self._mu:
            st.mode = normalize_mode(mode)
            st.updated_at = time.time()
        return st

    def stop(self, session_id: str) -> None:
        st = self.get(session_id)
        with self._mu:
            st.stopped = True
            st.paused = True
            st.updated_at = time.time()

    def pause(self, session_id: str) -> None:
        st = self.get(session_id)
        with self._mu:
            st.paused = True
            st.updated_at = time.time()

    def resume(self, session_id: str) -> None:
        st = self.get(session_id)
        with self._mu:
            st.paused = False
            st.stopped = False
            st.updated_at = time.time()

    def mark_restart_paused(self) -> None:
        """应用重启语义：未完成任务一律暂停，禁止自动续跑。"""
        with self._mu:
            for st in self._sessions.values():
                if not st.stopped:
                    st.paused = True

    def begin_model_round(self, session_id: str) -> tuple[bool, str]:
        st = self.get(session_id)
        with self._mu:
            if st.stopped:
                return False, "用户已停止"
            if st.paused:
                return False, "任务已暂停，请继续后再发送"
            if st.model_rounds >= MAX_MODEL_ROUNDS:
                return False, f"已达模型轮次预算（{MAX_MODEL_ROUNDS}）"
            st.model_rounds += 1
            st.updated_at = time.time()
        return True, ""

    def begin_tool_call(self, session_id: str) -> tuple[bool, str]:
        st = self.get(session_id)
        with self._mu:
            if st.stopped:
                return False, "用户已停止"
            if st.paused:
                return False, "任务已暂停"
            if st.tool_calls >= MAX_TOOL_CALLS:
                return False, f"已达工具调用预算（{MAX_TOOL_CALLS}）"
            st.tool_calls += 1
            st.updated_at = time.time()
        return True, ""

    def snapshot(self, session_id: str) -> dict:
        st = self.get(session_id)
        return {
            "session_id": st.session_id,
            "mode": st.mode,
            "model_rounds": st.model_rounds,
            "tool_calls": st.tool_calls,
            "stopped": st.stopped,
            "paused": st.paused,
            "max_model_rounds": MAX_MODEL_ROUNDS,
            "max_tool_calls": MAX_TOOL_CALLS,
        }

    def push_history(
        self,
        session_id: str,
        user_msg: str,
        assistant_msg: str = "",
    ) -> None:
        """追加一轮 user/assistant 到历史；超限自动截断最早轮次。"""
        st = self.get(session_id)
        with self._mu:
            st.history.append({"role": "user", "content": str(user_msg or ""), "ts": time.time()})
            if assistant_msg:
                st.history.append({"role": "assistant", "content": str(assistant_msg), "ts": time.time()})
            self._truncate_history(st)
            st.updated_at = time.time()

    def push_user_only(self, session_id: str, user_msg: str) -> None:
        """仅追加 user 消息（工具调用等场景）。"""
        st = self.get(session_id)
        with self._mu:
            st.history.append({"role": "user", "content": str(user_msg or ""), "ts": time.time()})
            self._truncate_history(st)
            st.updated_at = time.time()

    def get_history_messages(self, session_id: str) -> List[Dict[str, str]]:
        """返回 LLM 可直接消费的 messages 列表（不含 system）。"""
        st = self.get(session_id)
        with self._mu:
            return [
                {"role": m["role"], "content": str(m.get("content") or "")}
                for m in st.history
                if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()
            ]

    def clear_history(self, session_id: str) -> None:
        st = self.get(session_id)
        with self._mu:
            st.history = []
            st.updated_at = time.time()

    @staticmethod
    def _truncate_history(st: AgentSessionState) -> None:
        """按轮次数 + 总字符数双重限制截断最早消息。"""
        total_chars = sum(len(str(m.get("content") or "")) for m in st.history)
        while len(st.history) > MAX_HISTORY_TURNS * 2 or total_chars > MAX_HISTORY_CHARS:
            if not st.history:
                break
            dropped = st.history.pop(0)
            total_chars -= len(str(dropped.get("content") or ""))


agent_sessions = AgentSessionStore()
