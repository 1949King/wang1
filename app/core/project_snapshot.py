# -*- coding: utf-8 -*-
"""工程级快照 —— 时间线无损序列化 / 结构 diff / 内存回滚栈。

P1-4（拉开商用差距的关键能力之一）：
把画布 bundle 与剪辑器时间线（``EditorModule._clips``）一起打包成工程快照，
支持「可回滚 / 可 diff / 可直导剪辑器」。

设计原则（与现有机制对齐）：
- **不碰真相源**：本模块只做「读完整 _clips → 序列化 / diff / 存回滚栈」，
  写回由 ``canvas_bridge.set_clips_writer`` 注册的函数落到 EditorModule，避免桥直接 import 上帝类。
- **无损序列化**：与 ``get_timeline_snapshot``（摘要视图，只给画布/AI 决策看）不同，
  这里深拷贝**整条 ``_clips``**，保留 volume/speed/effects/transition/keyframes 等全部字段，
  保证「导出的快照再导回」能 1:1 还原时间线。
- **diff 用稳定键**：id 为主键，path 为兜底，start_time/duration 参与变更判定，
  避免把内存里的运行时对象指针当成差异。
- 纯 Python、无 Qt 依赖，可独立单测。

端点（在 canvas_server.py 走路由表，见 check_canvas_routes.py）：
- GET  /host/project-snapshot/export   → 返回 {ok, timeline:{clips, clip_count}, meta}
- POST /host/project-snapshot/import   → 把 {clips} 写回剪辑器（直导）
- GET  /host/project-snapshot/history  → 回滚栈列表
- POST /host/project-snapshot/restore  → 回滚到某条快照
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

# ── 时间线无损序列化 ──────────────────────────────────────────

# clip 里需要参与 diff 判定的关键字段（缺失按 None/0 处理，保证稳定）
_DIFF_KEYS = ("id", "path", "name", "start_time", "duration", "in_point", "out_point", "track", "type")


def _clip_identity(clip: Mapping[str, Any]) -> str:
    """返回 clip 的稳定主键：优先 id，其次 path@start_time。"""
    cid = clip.get("id")
    if cid is not None and cid != "":
        return str(cid)
    path = str(clip.get("path") or "")
    start = clip.get("start_time") or 0
    return f"{path}@{start}"


def snapshot_timeline(clips: Any) -> Dict[str, Any]:
    """深拷贝整条时间线，返回可 JSON 序列化的快照。

    返回 ``{"clips": [...], "clip_count": N, "taken_at": iso}``。
    拷贝是必要的：否则导出后剪辑器继续编辑，快照里的对象会被原地污染。
    """
    raw = clips if isinstance(clips, (list, tuple)) else []
    safe: List[Dict[str, Any]] = []
    for c in raw:
        if isinstance(c, Mapping):
            safe.append(copy.deepcopy(dict(c)))
    return {
        "clips": safe,
        "clip_count": len(safe),
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def diff_timelines(before: Any, after: Any) -> Dict[str, Any]:
    """对比两份时间线（均为 ``{clips:[...]}`` 或裸 clip 列表），返回结构化 diff。

    结果：
    - added:     after 有、before 无的 clip（按主键）
    - removed:   before 有、after 无的 clip
    - changed:   {key, clip_id, field, before, after} 列表（只列 _DIFF_KEYS 里的变化）
    - unchanged: 主键相同且关键字段一致的 clip 数
    """
    def _as_list(x: Any) -> List[Dict[str, Any]]:
        if isinstance(x, Mapping):
            inner = x.get("clips")
            return [dict(c) for c in inner if isinstance(c, Mapping)] if isinstance(inner, (list, tuple)) else []
        if isinstance(x, (list, tuple)):
            return [dict(c) for c in x if isinstance(c, Mapping)]
        return []

    b_list = _as_list(before)
    a_list = _as_list(after)
    b_map: Dict[str, Dict[str, Any]] = {}
    for c in b_list:
        b_map.setdefault(_clip_identity(c), c)
    a_map: Dict[str, Dict[str, Any]] = {}
    for c in a_list:
        a_map.setdefault(_clip_identity(c), c)

    added = [c for k, c in a_map.items() if k not in b_map]
    removed = [c for k, c in b_map.items() if k not in a_map]
    changed: List[Dict[str, Any]] = []
    unchanged = 0
    for k in b_map:
        if k not in a_map:
            continue
        bc, ac = b_map[k], a_map[k]
        dirty = False
        for f in _DIFF_KEYS:
            bv, av = bc.get(f), ac.get(f)
            if bv != av:
                changed.append({
                    "clip_id": bc.get("id"),
                    "identity": k,
                    "field": f,
                    "before": bv,
                    "after": av,
                })
                dirty = True
        if not dirty:
            unchanged += 1

    return {
        "added": len(added),
        "removed": len(removed),
        "changed": changed,
        "unchanged": unchanged,
        "added_clips": added,
        "removed_clips": removed,
    }


# ── 内存回滚栈 ────────────────────────────────────────────────


class SnapshotStore:
    """线程安全的内存快照回滚栈。

    用途：每次「导出工程快照」自动 push 一条；用户可在画布/剪辑器回滚到历史任一快照。
    只存数据不落盘（磁盘持久化交给现有的 autosave / exportProjectZip 文件），
    栈深受限，避免长会话内存膨胀。
    """

    def __init__(self, max_entries: int = 50) -> None:
        self._lock = threading.Lock()
        self._entries: List[Dict[str, Any]] = []
        self._max = max_entries

    def push(self, timeline: Any, *, label: str = "", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        snap = snapshot_timeline(timeline)
        entry = {
            "id": f"snap_{uuid.uuid4().hex[:12]}",
            "label": label or "未命名快照",
            "meta": dict(meta or {}),
            "taken_at": snap["taken_at"],
            "clip_count": snap["clip_count"],
            "clips": snap["clips"],
        }
        with self._lock:
            self._entries.append(entry)
            # 超深裁旧（保最新 max 条）
            if len(self._entries) > self._max:
                self._entries = self._entries[-self._max:]
        return entry

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {k: e[k] for k in ("id", "label", "taken_at", "clip_count", "meta") if k in e}
                for e in reversed(self._entries)
            ]

    def get(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for e in self._entries:
                if e.get("id") == snapshot_id:
                    return copy.deepcopy(e)
        return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# 模块级单例（供 canvas_server 端点复用）
_default_store: Optional[SnapshotStore] = None
_store_lock = threading.Lock()


def get_snapshot_store() -> SnapshotStore:
    global _default_store
    with _store_lock:
        if _default_store is None:
            _default_store = SnapshotStore()
        return _default_store


# ── 只读/写回 provider（由 EditorModule 注册，避免桥 import 上帝类）──

_FULL_CLIPS_PROVIDER: Optional[Callable[[], List[Dict[str, Any]]]] = None
_CLIPS_WRITER: Optional[Callable[[List[Dict[str, Any]]], Dict[str, Any]]] = None


def set_full_clips_provider(fn: Optional[Callable[[], List[Dict[str, Any]]]]) -> None:
    """EditorModule 注册「返回完整 _clips 副本」的回调。"""
    global _FULL_CLIPS_PROVIDER
    _FULL_CLIPS_PROVIDER = fn


def set_clips_writer(fn: Optional[Callable[[List[Dict[str, Any]]], Dict[str, Any]]]) -> None:
    """EditorModule 注册「把 clips 写回时间线」的回调（直导剪辑器入口）。"""
    global _CLIPS_WRITER
    _CLIPS_WRITER = fn


def get_full_clips() -> Optional[List[Dict[str, Any]]]:
    """拿完整 _clips（深拷贝）；未注册返回 None。"""
    fn = _FULL_CLIPS_PROVIDER
    if not callable(fn):
        return None
    try:
        raw = fn()
        if isinstance(raw, list):
            return [dict(c) for c in raw if isinstance(c, Mapping)]
        return None
    except Exception:
        return None


def write_clips(clips: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """把 clips 写回剪辑器时间线；未注册返回诚实失败（非假成功）。"""
    fn = _CLIPS_WRITER
    if not callable(fn):
        return {"ok": False, "message": "剪辑模块未注册时间线写回回调"}
    try:
        return fn([dict(c) for c in clips if isinstance(c, Mapping)]) or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"写回时间线失败: {e}"}
