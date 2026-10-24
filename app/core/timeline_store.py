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

import copy
import json
import logging
import threading
from typing import Any, Dict, List, Optional

from app.core.interchange.editor_timeline_bridge import (
    clips_to_timeline,
    timeline_to_clips,
)
from app.core.timeline_dsl import Timeline

logger = logging.getLogger("AI短剧编辑器.timeline_store")

#: 工程文件持久化的 canonical 格式标记（OTIO 迁移·刀5，双读单写的「单写」格式）。
TIMELINE_DSL_FORMAT = "timeline-dsl"
#: DSL 文档结构版本（后续字段级演进时递增，加载侧按版本兼容）。
TIMELINE_DSL_SCHEMA_VERSION = 1


class RevisionConflict(Exception):
    """陈旧写入被拒绝（对应 FableCut 的 HTTP 409 语义，刀1 · 2026-10-23）。

    **为什么是异常而不是返回值**：结构写 API（``add``/``remove_by_id``/
    ``set_fields``…）全部返回 None/bool/int 表示「命中与否」，把冲突塞进
    这些返回值会让既有调用方把「冲突」误读成「没命中」，从而**静默跳过写入**
    却不报错——那正是本刀要消除的故障模式。异常是唯一不会被忽略的信号。

    调用方要么显式捕获并转成 409 / CapabilityResult(error=...)，
    要么就让异常向上冒（宁可报错，不可静默丢写）。
    """

    def __init__(self, expected: int, actual: int, op: str = ""):
        self.expected = expected
        self.actual = actual
        self.op = op
        super().__init__(
            f"时间线写入冲突（{op or 'write'}）：基于 revision={expected}，"
            f"当前已是 revision={actual}；请重读后再应用（本次写入未执行）"
        )


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
        #: 单调递增的写入版本号（每成功一次结构/字段写 +1）。粗粒度即可：
        #: 时间线编辑「低频且粗糙」，FableCut 实测 last-writer-wins + 版本校验
        #: 足够，不需要 OT/CRDT（见刀1 决策依据）。
        self._revision = 0

    # ── 版本号（刀1 · 2026-10-23）──────────────────────────────────────

    def revision(self) -> int:
        """当前写入版本号（读操作，不 bump）。"""
        with self._lock:
            return self._revision

    def _bump_locked(self) -> int:
        """**锁内**自增版本号并返回新值（调用方必须已持锁）。"""
        self._revision += 1
        return self._revision

    def _check_base_locked(self, base_revision: Optional[int], op: str) -> None:
        """**锁内**做乐观并发校验（CAS）。

        ``base_revision is None`` ⇒ 不校验（既有的、非 Agent 的调用方保持
        原行为，逐键不变）；传了整数但 ≠ 当前值 ⇒ 抛 ``RevisionConflict``，
        **并且一个字节都不写**（校验在前，写入在后）。
        """
        if base_revision is None:
            return
        if not isinstance(base_revision, int) or isinstance(base_revision, bool):
            raise TypeError(
                f"base_revision 必须是 int 或 None（收到 {type(base_revision).__name__}）"
            )
        if base_revision != self._revision:
            raise RevisionConflict(base_revision, self._revision, op)

    def check_revision(self, base_revision: Optional[int], *, op: str = "") -> None:
        """公开的乐观并发校验（**调用方须已持 ``_clips_lock``**）。

        给宿主（EditorModule）的写入口用：那些入口需要先校验、再走多步
        非 store 的副作用（控件重建、内核同步），故校验与写入必须落在
        同一把锁的作用域内。只有 store 自己持有那把锁，所以把这颗
        「锁内断言」开放出来，而不是让宿主直接碰私有方法。
        """
        with self._lock:
            self._check_base_locked(base_revision, op)

    def conflict_payload(self, base_revision: int) -> Dict[str, Any]:
        """构造**冲突响应**（宿主写入口直接返回它，别在宿主里拼 dict）。

        为什么在这里：宿主文件受单文件规模守卫（只许减不许增）约束，
        把「冲突消息 + 两个 revision 字段」的结构留在 store 里，
        宿主侧只需 ``return store.conflict_payload(base)`` 一行。
        形状对齐能力层的 ``{"ok": False, "code": ...}`` 约定与 HTTP 409。
        """
        current = self.revision()
        return {
            "ok": False,
            "code": "conflict",
            "message": (f"时间线已被其他操作修改（基于 revision={base_revision}，"
                        f"当前 {current}）；本次未写入，请重读后再应用"),
            "expected_revision": base_revision,
            "current_revision": current,
        }

    def stale_or_none(self, base_revision: Optional[int]) -> Optional[Dict[str, Any]]:
        """宿主写入口的**一行式**并发闸：陈旧返回冲突载荷，新鲜/None 返回 None。

        用法（宿主里只多一行）::

            busy = self._timeline_store.stale_or_none(base_revision)
            if busy is not None:
                return busy
        """
        if base_revision is None:
            return None
        with self._lock:
            if base_revision == self._revision:
                return None
        return self.conflict_payload(base_revision)

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

    def add(self, clip: Dict[str, Any], *, base_revision: Optional[int] = None) -> None:
        """追加片段（不查重；调用方需要去重时先 ``find_by_id``）。

        ``base_revision`` 给了就在写前做 CAS 校验：值不匹配抛 ``RevisionConflict``
        且**一个字节都不写**；不给（None）保持既有行为逐键不变。
        """
        if not isinstance(clip, dict):
            raise TypeError("clip 必须是 dict")
        with self._lock:
            self._check_base_locked(base_revision, "add")
            self._rows.append(clip)
            self._bump_locked()

    def remove_by_id(self, clip_id: Any, *, base_revision: Optional[int] = None) -> int:
        """按 id 移除（切片赋值，不换列表对象）。返回移除条数。

        未命中（removed == 0）**不 bump**：没有真实改动就不该让别人的 revision 失效。
        """
        with self._lock:
            self._check_base_locked(base_revision, "remove_by_id")
            kept = [c for c in self._rows if c.get("id") != clip_id]
            removed = len(self._rows) - len(kept)
            if removed:
                self._rows[:] = kept
                self._bump_locked()
        return removed

    def replace_all(self, new_rows: List[Dict[str, Any]],
                    *, base_revision: Optional[int] = None) -> None:
        """整段原子替换（切片赋值保对象同一；非 dict 行被过滤）。"""
        if not isinstance(new_rows, list):
            raise TypeError("new_rows 必须是 list")
        with self._lock:
            self._check_base_locked(base_revision, "replace_all")
            self._rows[:] = [c for c in new_rows if isinstance(c, dict)]
            self._bump_locked()

    def clear(self, *, base_revision: Optional[int] = None) -> None:
        with self._lock:
            self._check_base_locked(base_revision, "clear")
            if not self._rows:
                return  # 空列表再清 = 无改动，不 bump
            self._rows.clear()
            self._bump_locked()

    # ── 字段写入（唯一合法入口，OTIO 迁移·刀4） ──────────────────────
    # 语义：锁内按 id 定位 live dict 后原地 update —— 读点拿到的仍是同一对象，
    # 与结构写 API 共享同一把 _clips_lock（RLock 可重入）。transform 系字段
    # （transform/pip_*/scale/rotation/anchor/position 等）仍必须走
    # clip_transform.normalize/apply_normalized 冻结入口，本 API 不实现第二套
    # 变换写入（方案 §3 刀4 风险②）。撤销记账（_record_action）由调用方负责。

    def set_fields(self, clip_id: Any, *, base_revision: Optional[int] = None,
                   **fields: Any) -> bool:
        """按 id 更新片段字段（原地突变）。返回是否命中片段。

        命中才 bump；未命中不 bump（无真实改动）。
        """
        if not fields:
            return False
        with self._lock:
            self._check_base_locked(base_revision, "set_fields")
            for c in self._rows:
                if c.get("id") == clip_id:
                    c.update(fields)
                    self._bump_locked()
                    return True
        return False

    def update_where(self, predicate, *, base_revision: Optional[int] = None,
                     **fields: Any) -> int:
        """按谓词批量更新字段（锁内遍历 live dict 原地 update）。返回命中条数。

        Args:
            predicate: 单参数可调用对象，接收 clip dict，返回 bool。
            fields: 要写入的键值对。

        命中 ≥1 条才 bump。
        """
        if not callable(predicate) or not fields:
            return 0
        hit = 0
        with self._lock:
            self._check_base_locked(base_revision, "update_where")
            for c in self._rows:
                try:
                    matched = bool(predicate(c))
                except Exception:
                    logger.debug("update_where 谓词异常，跳过该片段", exc_info=True)
                    continue
                if matched:
                    c.update(fields)
                    hit += 1
            if hit:
                self._bump_locked()
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

    def to_dsl_document(
        self,
        *,
        name: str = "",
        fps: float = 30.0,
        width: int = 1920,
        height: int = 1080,
        sample_rate: int = 44100,
        track_types: Optional[Dict[int, str]] = None,
        duration: float = 0.0,
    ) -> Dict[str, Any]:
        """产出**无损**持久化 DSL 文档（dict，JSON 可序列化；OTIO 迁移·刀5 单写格式）。

        桥接的类型化视图是**有损**的（effects dict→list 丢值、transform 子键丢、
        track 跳号归一、合成原不存在的键），工程文件不能靠桥接往返。本方法在
        类型化文档之上，为每个 clip 附**整行备份** ``metadata["editor"]``
        （含原始行序 ``metadata["editor_index"]``）：
          * 外部消费者仍读类型化字段（source/range/transform/metadata.editor extras）；
          * ``rows_from_dsl_document`` 据备份无损回灌真相源。
        锁内取快照后构建，与 live 列表解耦（json 遍历期间画布桥突变不影响本快照）。
        """
        with self._lock:
            snapshot = list(self._rows)
        tl = clips_to_timeline(
            snapshot,
            name=name,
            fps=fps,
            width=width,
            height=height,
            sample_rate=sample_rate,
            track_types=track_types,
            duration=duration,
        )
        doc = tl.to_dict()
        # 桥接内 clip id 统一为 str(c["id"])，按同一口径匹配整行备份。
        by_id = {str(c.get("id")): (c, i) for i, c in enumerate(snapshot)}
        for track in doc.get("tracks", []):
            for clip in track.get("clips", []) or []:
                hit = by_id.pop(str(clip.get("id")), None)
                if hit is None:
                    # 防御：桥接合成的 id（无 id 片段 → clip_xxx）没有备份可挂，
                    # 加载侧会因缺 editor 备份整体走桥接回退（有损但可用）。
                    continue
                row, index = hit
                meta = clip.setdefault("metadata", {})
                meta["editor"] = copy.deepcopy(row)
                meta["editor_index"] = index
        return doc

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


# ── DSL 文档回灌（OTIO 迁移·刀5 双读；模块函数，不依赖 store 实例） ────

def rows_from_dsl_document(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 ``to_dsl_document`` 文档回灌真相源行列表（**无损**路径）。

    回灌策略：
      * 全部 clip 均带 ``metadata["editor"]`` 整行备份 → deepcopy 按
        ``editor_index`` 原序回 rows（本软件写出的工程文件必走此路径）；
      * 任一 clip 缺备份（外部手写 DSL 文档）→ 整体回退桥接
        ``timeline_to_clips``（有损但可用），记 warning；
      * doc 非 dict 或缺 tracks → ValueError（调用方给用户清晰提示）。
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("tracks"), list):
        raise ValueError("DSL 文档畸形：缺 tracks 字段")
    clips: List[Dict[str, Any]] = []
    for track in doc["tracks"]:
        if isinstance(track, dict):
            clips.extend(c for c in (track.get("clips") or []) if isinstance(c, dict))
    backed: List[Any] = []
    for pos, clip in enumerate(clips):
        meta = clip.get("metadata")
        editor = meta.get("editor") if isinstance(meta, dict) else None
        if not isinstance(editor, dict):
            logger.warning(
                "DSL 文档缺 editor 整行备份，按桥接回灌（有损路径，仅外部手写文档）"
            )
            return timeline_to_clips(Timeline.from_json(doc))
        idx = meta.get("editor_index")
        backed.append((idx if isinstance(idx, int) else pos, copy.deepcopy(editor)))
    backed.sort(key=lambda pair: pair[0])
    return [row for _, row in backed]
