# -*- coding: utf-8 -*-
"""时间线真相源：``TimelineStore``（OTIO 全量迁移 · 刀1，2026-10-18 用户授权解冻）

背景：编辑器历史真相源是 ``EditorModule._clips``（dict 列表），结构性写入散落在
调用点上（整段重赋值 / append / clear），序列化与类型化视图（``timeline_dsl.Timeline``）
各自拼装。本类以 **strangler 模式** 渐进收拢，不推翻现有读路径：

* **列表对象同一性保留**：store 直接 adopt ``EditorModule._clips`` 的**同一个 list 对象**，
  所有结构变更都是**原地突变**（切片赋值 / append / remove），绝不重绑定列表 ——
  既有数百处读点（UI / 渲染 / autosave / 画布桥）零破坏；
* **结构写入收敛**：``add`` / ``remove_by_id`` / ``replace_all`` / ``clear`` 是唯一
  合法的结构写入 API，锁复用外部传入的 ``_clips_lock``（RLock 可重入），不自建第二把锁；
* **canonical 出口**：序列化（``serialize``/``deserialize``）与类型化视图
  （``to_timeline`` 走 ``editor_timeline_bridge`` 确定性构建）由 store 提供单一出口，
  供刀2（撤销/持久化）与刀3（消费端）接入。

Qt 红线：本模块**不得 import PyQt6**（桥接层为纯数据，可被子进程复用）。
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

from app.core.interchange.editor_timeline_bridge import clips_to_timeline
from app.core.timeline_dsl import Timeline

logger = logging.getLogger("AI短剧编辑器.timeline_store")


class TimelineStore:
    """时间线片段列表的唯一所有者（live dict 行数据 + 同一性不变量）。"""

    def __init__(
        self,
        rows: List[Dict[str, Any]],
        lock: Optional[threading.RLock] = None,
    ):
        """adopt 既有列表对象（不复制），保证 ``rows()`` 与宿主 ``_clips`` 永远同一。

        Args:
            rows: 宿主（EditorModule）已存在的 clip dict 列表，store 直接接管它。
            lock: 复用宿主 ``_clips_lock``（RLock）；缺省时自建（仅单测/离线路径）。
        """
        if not isinstance(rows, list):
            raise TypeError("TimelineStore 必须 adopt 既有 list 对象（保持同一性）")
        self._rows = rows
        self._lock = lock if lock is not None else threading.RLock()

    # ── 读 ──────────────────────────────────────────────────────────

    def rows(self) -> List[Dict[str, Any]]:
        """返回 live 列表（同一对象）。宿主 ``_clips`` 读点可直接继续使用。"""
        return self._rows

    def count(self) -> int:
        with self._lock:
            return len(self._rows)

    def snapshot(self) -> List[Dict[str, Any]]:
        """锁内**浅拷贝**快照（元素仍是同一批 dict 引用——工程契约按 id 定位、
        不做深拷贝；序列化/跨线程遍历一律用它，绝不把 live 列表交出去）。"""
        with self._lock:
            return list(self._rows)

    def find_by_id(self, clip_id: Any) -> Optional[Dict[str, Any]]:
        """按 id 查片段（返回 live dict 引用，字段级更新仍由调用方原地改）。"""
        with self._lock:
            for c in self._rows:
                if c.get("id") == clip_id:
                    return c
        return None

    # ── 结构写入（唯一合法入口，全部原地突变、保同一性） ─────────────

    def add(self, clip: Dict[str, Any]) -> None:
        """追加片段（不查重；调用方需要去重时先 ``find_by_id``）。"""
        if not isinstance(clip, dict):
            raise TypeError("clip 必须是 dict")
        with self._lock:
            self._rows.append(clip)

    def remove_by_id(self, clip_id: Any) -> int:
        """按 id 移除（切片赋值，不换列表对象）。返回移除条数。"""
        with self._lock:
            kept = [c for c in self._rows if c.get("id") != clip_id]
            removed = len(self._rows) - len(kept)
            if removed:
                self._rows[:] = kept
        return removed

    def replace_all(self, new_rows: List[Dict[str, Any]]) -> None:
        """整段原子替换（切片赋值保对象同一；非 dict 行被过滤）。"""
        if not isinstance(new_rows, list):
            raise TypeError("new_rows 必须是 list")
        with self._lock:
            self._rows[:] = [c for c in new_rows if isinstance(c, dict)]

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()

    # ── 字段写入（唯一合法入口，OTIO 迁移·刀4） ──────────────────────
    # 语义：锁内按 id 定位 live dict 后原地 update —— 读点拿到的仍是同一对象，
    # 与结构写 API 共享同一把 _clips_lock（RLock 可重入）。transform 系字段
    # （transform/pip_*/scale/rotation/anchor/position 等）仍必须走
    # clip_transform.normalize/apply_normalized 冻结入口，本 API 不实现第二套
    # 变换写入（方案 §3 刀4 风险②）。撤销记账（_record_action）由调用方负责。

    def set_fields(self, clip_id: Any, **fields: Any) -> bool:
        """按 id 更新片段字段（原地突变）。返回是否命中片段。"""
        if not fields:
            return False
        with self._lock:
            for c in self._rows:
                if c.get("id") == clip_id:
                    c.update(fields)
                    return True
        return False

    def update_where(self, predicate, **fields: Any) -> int:
        """按谓词批量更新字段（锁内遍历 live dict 原地 update）。返回命中条数。

        Args:
            predicate: 单参数可调用对象，接收 clip dict，返回 bool。
            fields: 要写入的键值对。
        """
        if not callable(predicate) or not fields:
            return 0
        hit = 0
        with self._lock:
            for c in self._rows:
                try:
                    matched = bool(predicate(c))
                except Exception:
                    logger.debug("update_where 谓词异常，跳过该片段", exc_info=True)
                    continue
                if matched:
                    c.update(fields)
                    hit += 1
        return hit

    # ── canonical 出口：类型化视图 / 序列化 ──────────────────────────

    def to_timeline(
        self,
        *,
        name: str = "",
        fps: float = 30.0,
        width: int = 1920,
        height: int = 1080,
        sample_rate: int = 44100,
        track_types: Optional[Dict[int, str]] = None,
        duration: float = 0.0,
    ) -> Timeline:
        """产出类型化 ``timeline_dsl.Timeline``（锁内取快照，走桥接确定性构建）。"""
        with self._lock:
            snapshot = list(self._rows)
        return clips_to_timeline(
            snapshot,
            name=name,
            fps=fps,
            width=width,
            height=height,
            sample_rate=sample_rate,
            track_types=track_types,
            duration=duration,
        )

    def serialize(self) -> str:
        """canonical 序列化（行列表 JSON 文本）。刀2 持久化统一走这里。"""
        with self._lock:
            return json.dumps(list(self._rows), ensure_ascii=False)

    def deserialize(self, text: str) -> int:
        """canonical 反序列化灌入（整段替换、保持列表同一性）。返回灌入条数。"""
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError("序列化文本不是 clip 数组")
        self.replace_all(rows)
        return len(self._rows)
