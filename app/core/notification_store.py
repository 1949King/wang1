"""
通知中心数据存储 (NotificationStore)
====================================

轻量级本地通知存储，持久化到 user_data_dir/notifications.json。
为顶 navbar 🔔 通知中心面板提供数据契约；同时作为系统消息/版本更新/
反馈提交/告警的统一汇聚点。

设计目标（V4.42.1 起）：
- 简单：单例 + JSON 持久化，无外部依赖
- 线程安全：RLock 保护（GUI 主线程 + 工作线程都可能调用）
- 限额：deque(maxlen=500)，老条目按 FIFO 自动淘汰
- 回调：add / mark_read / clear 后触发 callback，便于 UI 实时刷新
- 通知类别：system / update / feedback / alert / info
- 严重级别：info / success / warning / error

与 alert_system.py 关系：
- alert_system 是"基于 metrics 触发的规则告警"（7 通道：EMAIL/SMS/WEBHOOK/...）
- notification_store 是"应用内消息中心"（持久化展示用）
- 告警转发：alert_system 的 add_alert_callback 可把通知写到 notification_store
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.notification")


# ─────────── 类型常量（避免散落字符串） ───────────
TYPE_SYSTEM = "system"
TYPE_UPDATE = "update"
TYPE_FEEDBACK = "feedback"
TYPE_ALERT = "alert"
TYPE_INFO = "info"
VALID_TYPES = {TYPE_SYSTEM, TYPE_UPDATE, TYPE_FEEDBACK, TYPE_ALERT, TYPE_INFO}

LEVEL_INFO = "info"
LEVEL_SUCCESS = "success"
LEVEL_WARNING = "warning"
LEVEL_ERROR = "error"
VALID_LEVELS = {LEVEL_INFO, LEVEL_SUCCESS, LEVEL_WARNING, LEVEL_ERROR}

MAX_NOTIFICATIONS = 500
DEFAULT_LIST_LIMIT = 50
OLD_THRESHOLD_DAYS = 30


@dataclass
class Notification:
    """单条通知"""
    id: str
    type: str          # 类别（TYPE_*）
    level: str         # 严重级别（LEVEL_*）
    title: str
    body: str
    created_at: float  # time.time()
    read: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Notification":
        # 兜底字段缺失
        return cls(
            id=data.get("id") or str(uuid.uuid4()),
            type=data.get("type") or TYPE_INFO,
            level=data.get("level") or LEVEL_INFO,
            title=data.get("title") or "",
            body=data.get("body") or "",
            created_at=float(data.get("created_at") or time.time()),
            read=bool(data.get("read", False)),
            metadata=data.get("metadata") or {},
        )


class NotificationStore:
    """应用内通知中心（单例）"""

    _instance: Optional["NotificationStore"] = None
    _init_lock = threading.Lock()

    # ─────────── 单例 ───────────
    @classmethod
    def instance(cls) -> "NotificationStore":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ─────────── 生命周期 ───────────
    def __init__(self):
        if NotificationStore._instance is not None:
            raise RuntimeError("NotificationStore 是单例，请用 .instance()")
        self._path = self._resolve_path()
        self._notifications: Deque[Notification] = deque(maxlen=MAX_NOTIFICATIONS)
        self._lock = threading.RLock()
        self._callbacks: List[Callable[[str, Notification], None]] = []
        # type: ("add" / "mark_read" / "delete" / "clear")
        self._load()

    @staticmethod
    def _resolve_path() -> str:
        """获取持久化文件路径（与 update_manager 同一目录约定）"""
        try:
            from app.core.config_paths import get_user_data_dir
            base = get_user_data_dir()
        except ImportError:
            base = os.path.join(os.path.expanduser("~"), ".ai_short_drama_editor")
        try:
            os.makedirs(base, exist_ok=True)
        except OSError as e:
            logger.warning("创建用户数据目录失败，回退到 ~/.ai_short_drama_editor: %s", e)
            base = os.path.join(os.path.expanduser("~"), ".ai_short_drama_editor")
            os.makedirs(base, exist_ok=True)
        return os.path.join(base, "notifications.json")

    @property
    def storage_path(self) -> str:
        """对外暴露：UI 显示当前存储位置"""
        return self._path

    # ─────────── 持久化 ───────────
    def _load(self) -> None:
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("加载 notifications.json 失败，使用空列表: %s", e)
            return

        items = raw.get("notifications") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return
        with self._lock:
            self._notifications.clear()
            for item in items:
                if isinstance(item, dict):
                    self._notifications.append(Notification.from_dict(item))

    def _save(self) -> bool:
        """原子写入（先写 .tmp 再 rename），防止半路崩溃损坏文件"""
        try:
            with self._lock:
                data = {
                    "version": 1,
                    "saved_at": time.time(),
                    "notifications": [n.to_dict() for n in self._notifications],
                }
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if os.path.isfile(self._path):
                os.replace(tmp, self._path)
            else:
                os.rename(tmp, self._path)
            return True
        except OSError as e:
            logger.error("保存 notifications.json 失败: %s", e)
            return False

    # ─────────── CRUD ───────────
    def add(self, notification: Notification) -> bool:
        """新增通知；返回是否成功"""
        if notification.type not in VALID_TYPES:
            notification.type = TYPE_INFO
        if notification.level not in VALID_LEVELS:
            notification.level = LEVEL_INFO
        if not notification.id:
            notification.id = str(uuid.uuid4())
        with self._lock:
            self._notifications.appendleft(notification)  # 最新在前
            ok = self._save()
        self._fire_callbacks("add", notification)
        return ok

    def notify(
        self,
        title: str,
        body: str = "",
        type: str = TYPE_INFO,
        level: str = LEVEL_INFO,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Notification:
        """便捷方法：构造并 add 一条通知"""
        n = Notification(
            id=str(uuid.uuid4()),
            type=type,
            level=level,
            title=title,
            body=body,
            created_at=time.time(),
            read=False,
            metadata=metadata or {},
        )
        self.add(n)
        return n

    def list(
        self,
        type: Optional[str] = None,
        only_unread: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> List[Notification]:
        """查询；type=None 表示全部"""
        with self._lock:
            result = list(self._notifications)
        if type:
            result = [n for n in result if n.type == type]
        if only_unread:
            result = [n for n in result if not n.read]
        if limit and limit > 0:
            result = result[:limit]
        return result

    def unread_count(self) -> int:
        with self._lock:
            return sum(1 for n in self._notifications if not n.read)

    def count(self) -> int:
        with self._lock:
            return len(self._notifications)

    def mark_read(self, notification_id: str) -> bool:
        """标记单条为已读"""
        with self._lock:
            for n in self._notifications:
                if n.id == notification_id and not n.read:
                    n.read = True
                    self._save()
                    self._fire_callbacks("mark_read", n)
                    return True
        return False

    def mark_all_read(self) -> int:
        """全部标记已读，返回变更条数"""
        changed = 0
        with self._lock:
            for n in self._notifications:
                if not n.read:
                    n.read = True
                    changed += 1
            if changed:
                self._save()
        if changed:
            # 用占位通知触发回调
            self._fire_callbacks("mark_read", Notification(
                id="__all__", type=TYPE_INFO, level=LEVEL_INFO,
                title="", body="", created_at=time.time(),
            ))
        return changed

    def delete(self, notification_id: str) -> bool:
        """删除单条"""
        with self._lock:
            for i, n in enumerate(self._notifications):
                if n.id == notification_id:
                    del self._notifications[i]
                    self._save()
                    self._fire_callbacks("delete", n)
                    return True
        return False

    def clear(self) -> None:
        """清空所有"""
        with self._lock:
            self._notifications.clear()
            self._save()
        self._fire_callbacks("clear", Notification(
            id="__all__", type=TYPE_INFO, level=LEVEL_INFO,
            title="", body="", created_at=time.time(),
        ))

    def clear_old(self, days: int = OLD_THRESHOLD_DAYS) -> int:
        """清理 days 天前的已读通知，返回清理条数"""
        threshold = time.time() - days * 86400
        removed = 0
        with self._lock:
            kept: Deque[Notification] = deque(maxlen=MAX_NOTIFICATIONS)
            for n in self._notifications:
                if n.read and n.created_at < threshold:
                    removed += 1
                else:
                    kept.append(n)
            if removed:
                self._notifications = kept
                self._save()
        return removed

    # ─────────── 回调（用于 UI 实时刷新）───────────
    def register_callback(self, fn: Callable[[str, Notification], None]) -> None:
        with self._lock:
            if fn not in self._callbacks:
                self._callbacks.append(fn)

    def unregister_callback(self, fn: Callable[[str, Notification], None]) -> None:
        with self._lock:
            try:
                self._callbacks.remove(fn)
            except ValueError:
                pass

    def _fire_callbacks(self, event: str, notification: Notification) -> None:
        with self._lock:
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb(event, notification)
            except Exception as e:
                logger.debug("通知回调失败（已忽略）: %s", e)


__all__ = [
    "Notification",
    "NotificationStore",
    "TYPE_SYSTEM", "TYPE_UPDATE", "TYPE_FEEDBACK", "TYPE_ALERT", "TYPE_INFO",
    "LEVEL_INFO", "LEVEL_SUCCESS", "LEVEL_WARNING", "LEVEL_ERROR",
    "VALID_TYPES", "VALID_LEVELS", "MAX_NOTIFICATIONS",
]


# 便捷单例
def notification_store() -> NotificationStore:
    return NotificationStore.instance()