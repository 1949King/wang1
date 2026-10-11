# -*- coding: utf-8 -*-
"""进程内 Agent 会话：模式、预算计数、停止标志、对话历史。

重启语义（重要）
----------------
应用重启后**任务的执行一律视为暂停，绝不自动续跑**（用户须显式「继续」）。
``load_checkpoint()`` 会把磁盘上的检查点读回来，但强制 ``paused=True``；
检查点的用途是「让用户看得见上次在做什么」，不是「偷偷接着跑」。

检查点持久化到 ``user_data_dir/agent_sessions.json``（与 notification_store 同目录约定），
原子写（.tmp + replace）。写盘节流（``_AUTOSAVE_MIN_INTERVAL``），不会拖慢工具调用热路径。
"""
from __future__ import annotations

import json
import logging
import os
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

logger = logging.getLogger("AI短剧编辑器.agent.session")

MAX_HISTORY_TURNS = 20
MAX_HISTORY_CHARS = 12000

#: 检查点文件格式版本
CHECKPOINT_VERSION = 1
#: 自动写盘最小间隔（秒）—— 避免每次工具调用都落盘
_AUTOSAVE_MIN_INTERVAL = 1.5


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
    #: 进行中任务的一句话简述（重启后用于「上次在做什么」提示）
    task_summary: str = ""
    #: 最近一次检查点落盘时间
    checkpoint_saved_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可 JSON 落盘的纯字典。"""
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "model_rounds": int(self.model_rounds),
            "tool_calls": int(self.tool_calls),
            "stopped": bool(self.stopped),
            "paused": bool(self.paused),
            "updated_at": float(self.updated_at),
            "task_summary": str(self.task_summary or ""),
            "checkpoint_saved_at": float(self.checkpoint_saved_at or 0.0),
            "history": [
                {
                    "role": str(m.get("role") or ""),
                    "content": str(m.get("content") or ""),
                    "ts": float(m.get("ts") or 0.0),
                }
                for m in (self.history or [])
                if isinstance(m, dict)
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSessionState":
        """从检查点字典还原（字段缺失/类型异常一律兜底，绝不抛）。"""
        data = data if isinstance(data, dict) else {}
        try:
            mode = normalize_mode(str(data.get("mode") or MODE_COLLABORATIVE))
        except Exception:
            mode = MODE_COLLABORATIVE
        history: List[Dict[str, Any]] = []
        for m in data.get("history") or []:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "")
            if role not in ("user", "assistant"):
                continue
            history.append({
                "role": role,
                "content": str(m.get("content") or ""),
                "ts": float(m.get("ts") or 0.0),
            })
        try:
            model_rounds = max(0, int(data.get("model_rounds") or 0))
        except (TypeError, ValueError):
            model_rounds = 0
        try:
            tool_calls = max(0, int(data.get("tool_calls") or 0))
        except (TypeError, ValueError):
            tool_calls = 0
        return cls(
            session_id=str(data.get("session_id") or "default") or "default",
            mode=mode,
            model_rounds=model_rounds,
            tool_calls=tool_calls,
            stopped=bool(data.get("stopped", False)),
            paused=bool(data.get("paused", False)),
            updated_at=float(data.get("updated_at") or time.time()),
            history=history,
            task_summary=str(data.get("task_summary") or ""),
            checkpoint_saved_at=float(data.get("checkpoint_saved_at") or 0.0),
        )


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
        #: 检查点自动写盘开关（load_checkpoint / enable_checkpointing 后打开）
        self._checkpoint_enabled = False
        self._last_save = 0.0
        self._last_save_ok = True
        self._ckpt_path: Optional[str] = None

    # ─────────── 检查点（跨重启持久化） ───────────

    def _resolve_checkpoint_path(self) -> str:
        """检查点文件路径（与 notification_store 同目录约定）。"""
        if self._ckpt_path:
            return self._ckpt_path
        try:
            from app.core.config_paths import get_user_data_dir

            base = get_user_data_dir()
        except Exception:
            base = os.path.join(os.path.expanduser("~"), ".ai_short_drama_editor")
        try:
            os.makedirs(base, exist_ok=True)
        except OSError as e:
            logger.warning("创建用户数据目录失败，回退到 ~/.ai_short_drama_editor: %s", e)
            base = os.path.join(os.path.expanduser("~"), ".ai_short_drama_editor")
            try:
                os.makedirs(base, exist_ok=True)
            except OSError:
                logger.debug("回退目录同样创建失败，将直接使用该路径: %s", base, exc_info=True)
        self._ckpt_path = os.path.join(base, "agent_sessions.json")
        return self._ckpt_path

    def enable_checkpointing(self) -> None:
        """打开自动写盘（幂等）。"""
        with self._mu:
            self._checkpoint_enabled = True

    def save_checkpoint(self, path: Optional[str] = None, force: bool = False) -> bool:
        """把全部会话状态原子写入检查点文件。返回是否成功。

        ``force=False`` 时受 ``_AUTOSAVE_MIN_INTERVAL`` 节流（热路径无感）。
        """
        target = path or self._resolve_checkpoint_path()
        with self._mu:
            now = time.time()
            if not force and (now - self._last_save) < _AUTOSAVE_MIN_INTERVAL:
                return self._last_save_ok
            payload = {
                "version": CHECKPOINT_VERSION,
                "saved_at": now,
                "sessions": [st.to_dict() for st in self._sessions.values()],
            }
            self._last_save = now
        try:
            tmp = target + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, target)
        except OSError as e:
            logger.warning("写入 Agent 检查点失败: %s", e)
            with self._mu:
                self._last_save_ok = False
            return False
        with self._mu:
            self._last_save_ok = True
            for st in self._sessions.values():
                st.checkpoint_saved_at = now
        return True

    def load_checkpoint(self, path: Optional[str] = None) -> Dict[str, Any]:
        """读取检查点并**以暂停态**恢复会话（绝不允许自动续跑）。

        返回摘要：``{"ok", "restored", "paused", "sessions": [...]}``。
        文件不存在 / 损坏时返回 ``{"ok": False, ...}``，不抛异常。
        """
        target = path or self._resolve_checkpoint_path()
        summary: Dict[str, Any] = {"ok": False, "restored": 0, "paused": 0, "sessions": []}
        if not os.path.isfile(target):
            return summary
        try:
            with open(target, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("读取 Agent 检查点失败，忽略: %s", e)
            return summary
        items = raw.get("sessions") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return summary
        restored = 0
        with self._mu:
            for item in items:
                if not isinstance(item, dict):
                    continue
                st = AgentSessionState.from_dict(item)
                # 重启语义：非「已停止」的会话一律置为暂停
                if not st.stopped:
                    st.paused = True
                self._sessions[st.session_id] = st
                restored += 1
                summary["sessions"].append({
                    "session_id": st.session_id,
                    "mode": st.mode,
                    "paused": st.paused,
                    "stopped": st.stopped,
                    "model_rounds": st.model_rounds,
                    "tool_calls": st.tool_calls,
                    "task_summary": st.task_summary,
                    "history_len": len(st.history),
                })
            summary["restored"] = restored
            summary["paused"] = sum(1 for s in summary["sessions"] if s["paused"])
            summary["ok"] = True
            self._checkpoint_enabled = True
        if restored:
            logger.info("Agent 检查点已恢复：%d 个会话（%d 个暂停待续跑）",
                        restored, summary["paused"])
        return summary

    def checkpoint_summary(self) -> Dict[str, Any]:
        """当前会话的检查点摘要（UI / 诊断用）。"""
        with self._mu:
            sessions = []
            for st in self._sessions.values():
                if not st.history and not st.task_summary:
                    continue
                sessions.append({
                    "session_id": st.session_id,
                    "mode": st.mode,
                    "paused": st.paused,
                    "stopped": st.stopped,
                    "model_rounds": st.model_rounds,
                    "tool_calls": st.tool_calls,
                    "task_summary": st.task_summary,
                    "history_len": len(st.history),
                    "checkpoint_saved_at": st.checkpoint_saved_at,
                })
            return {
                "path": self._resolve_checkpoint_path(),
                "enabled": self._checkpoint_enabled,
                "sessions": sessions,
            }

    def has_resumable(self) -> bool:
        """是否存在「暂停中且未停止」的可续跑会话。"""
        with self._mu:
            return any((not st.stopped) and st.paused and (st.history or st.task_summary)
                       for st in self._sessions.values())

    def set_task_summary(self, session_id: str, summary: str) -> None:
        """记录「当前在做什么」（重启后提示用）。"""
        st = self.get(session_id)
        with self._mu:
            st.task_summary = str(summary or "")[:500]
            st.updated_at = time.time()
        self._maybe_autosave()

    def reset_budget(self, session_id: str) -> None:
        """清零轮次 / 工具调用预算（用户显式「继续」时给一次新预算）。"""
        st = self.get(session_id)
        with self._mu:
            st.model_rounds = 0
            st.tool_calls = 0
            st.updated_at = time.time()
        self._maybe_autosave()

    def _maybe_autosave(self) -> None:
        """状态变更后按节流自动落盘（未启用 / 出错都不影响主流程）。"""
        if not self._checkpoint_enabled:
            return
        try:
            self.save_checkpoint()
        except Exception as e:  # pragma: no cover - 防御
            logger.debug("Agent 检查点自动保存失败: %s", e)

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
        self._maybe_autosave()
        return st

    def stop(self, session_id: str) -> None:
        st = self.get(session_id)
        with self._mu:
            st.stopped = True
            st.paused = True
            st.updated_at = time.time()
        self.save_checkpoint(force=True)

    def pause(self, session_id: str) -> None:
        st = self.get(session_id)
        with self._mu:
            st.paused = True
            st.updated_at = time.time()
        self.save_checkpoint(force=True)

    def resume(self, session_id: str) -> None:
        st = self.get(session_id)
        with self._mu:
            st.paused = False
            st.stopped = False
            st.updated_at = time.time()
        self.save_checkpoint(force=True)

    def mark_restart_paused(self) -> None:
        """应用重启语义：未完成任务一律暂停，禁止自动续跑。"""
        with self._mu:
            for st in self._sessions.values():
                if not st.stopped:
                    st.paused = True
        self._maybe_autosave()

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
        self._maybe_autosave()
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
        self._maybe_autosave()
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
            "task_summary": st.task_summary,
            "history_len": len(st.history),
            "checkpoint_saved_at": st.checkpoint_saved_at,
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
        self._maybe_autosave()

    def push_user_only(self, session_id: str, user_msg: str) -> None:
        """仅追加 user 消息（工具调用等场景）。"""
        st = self.get(session_id)
        with self._mu:
            st.history.append({"role": "user", "content": str(user_msg or ""), "ts": time.time()})
            self._truncate_history(st)
            st.updated_at = time.time()
        self._maybe_autosave()

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
        self._maybe_autosave()

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
