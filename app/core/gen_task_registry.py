# -*- coding: utf-8 -*-
"""生成任务账本（Gen Task Registry）—— GenerationTask 记账 + AssetNode 正式化 + 幂等查重。

定位（统一数据模型 · §6.9-P1 正式化，2026-10-18）
------------------------------------------------
解决的问题：生成任务只活在 `canvas_gen_jobs` 的**内存态**里——进程一退、
LRU 一裁，「哪条 prompt、哪个种子、产出了哪个文件、落在哪个画布节点」
就全断了；前端重复点击 / 重发同参数请求也没有幂等防线，会重复计费。

本模块是**纯账本**（照 draw_book 纪律：不 import app 包、可独立加载/单测）：
  - tasks 表：GenerationTask 记录（prompt/model/seed/size/duration/channel_id
    + job_id/status/result_paths/asset_id/canvas_node_id）
  - assets 表：AssetNode 记录（path/generation_task_id/canvas_node_id
    + quality_score/consistency_score/perception/timeline_clip_ids）
  - 幂等键：``sha1(kind|norm(prompt)|model|size|seed|duration|channel_id)[:16]``
    —— 跨进程稳定（禁用内置 hash()，归一化语义与 draw_book.normalize_prompt 同款）

三条硬约束
----------
1. **账本绝不拖垮主链路**：所有公开方法内部吞异常（持久化失败只记日志）；
   ``begin`` 的查重是「尽力而为」——账本坏了就当空库，最坏退化成不去重，
   生成照常走。
2. **不重建素材库**：AssetNode 是「在既有文件路径上挂生成链记录」，
   与 local_asset_manager 各司其职；本模块只管血缘，不管文件。
3. **状态机与 canvas_gen_jobs 对齐**：queued/running/cancelling 为活跃，
   done/failed/cancelled 为终态；查重**只命中活跃任务**（终态不查重，
   重拍同参数是合法诉求）。seed 缺省时同参数双击会命中查重——
   这是防重复计费的正解；前端「刻意再抽一张」传 ``force=True`` 绕过。

对外入口：``get_store()`` 单例 + ``idempotency_key`` / ``extract_result_paths``
/ ``TERMINAL_STATUSES`` / ``ACTIVE_STATUSES`` 常量。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
import unicodedata
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 状态机（与 canvas_gen_jobs 对齐；本模块不 import 它，保持纯模块）
ACTIVE_STATUSES = ("queued", "running", "cancelling")
TERMINAL_STATUSES = ("done", "failed", "cancelled")

_MAX_TASKS = 500       # tasks 表上限（只裁终态，活跃任务不动）
_MAX_ASSETS = 1000     # assets 表上限
_PROMPT_HEAD = 80      # 人读用提示词前缀长度

_DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "gen_tasks.json")

# 测试隔离：SG_GEN_TASK_STORE 存在时优先（缺省仍是 data/gen_tasks.json）。
# 为什么需要：守卫/单测若直连正式账本，会把测试记录写进真相源。
_STORE_ENV = "SG_GEN_TASK_STORE"


def _resolve_store_path() -> str:
    """解析账本路径：环境变量 > 默认（data/gen_tasks.json）。"""
    env = os.environ.get(_STORE_ENV)
    return env.strip() if env and env.strip() else _DEFAULT_STORE


def normalize_text(text: str) -> str:
    """归一化：NFKC（全半角）+ 小写 + 去除全部空白。

    与 draw_book.normalize_prompt 同款语义（那边在 app/core/ai/ 包内，
    本模块保持纯模块不跨包 import，3 行逻辑复制优于制造依赖）。
    """
    s = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(s.split())


def _norm_field(text: Any) -> str:
    """普通字段归一：NFKC（全半角）+ strip + lower（保留字段内空白）。

    与 normalize_text 的差别：model/channel 名里的空白有区分度
    （"dall e 3" 不与 "dalle3" 归一），只做全半角与大小写折叠。
    """
    return unicodedata.normalize("NFKC", str(text if text is not None else "")).strip().lower()


def idempotency_key(kind: str, prompt: str, model: str, *,
                    size: str = "", seed: Any = None, duration: Any = None,
                    channel_id: str = "") -> str:
    """幂等键：同一套「介质+提示词+模型+尺寸+种子+时长+渠道」归一桶。

    ``seed``/``duration`` 为 None 时以空串入键（随机种子≠固定种子，
    两者不互相命中）。sha1[:16] 跨进程稳定——**禁用内置 hash()**
    （PYTHONHASHSEED 随机化会让查重在不同启动间失效）。
    """
    raw = "|".join([
        _norm_field(kind),
        normalize_text(prompt),
        _norm_field(model),
        _norm_field(size),
        "" if seed is None else _norm_field(seed),
        "" if duration is None else _norm_field(duration),
        _norm_field(channel_id),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def extract_result_paths(res: Any) -> List[str]:
    """从生成结果 dict 里宽松收集本地落盘路径（诚实：收不到就空列表）。

    只认字符串值；data URL / 远端 URL 不算路径，不硬塞。
    """
    out: List[str] = []
    if not isinstance(res, dict):
        return out
    for key in ("path", "video_path", "image_path", "audio_path",
                "output_path", "file", "file_path"):
        v = res.get(key)
        if isinstance(v, str) and v.strip():
            out.append(v)
    for key in ("paths", "videos", "images", "files"):
        v = res.get(key)
        if isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, str) and item.strip():
                    out.append(item)
                elif isinstance(item, dict):
                    sub = extract_result_paths(item)
                    out.extend(sub)
    # 去重保序
    seen = set()
    uniq = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _clamp01(x: Any) -> Optional[float]:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return None


class GenTaskStore:
    """GenerationTask + AssetNode 双表账本（线程安全，持久化原子写）。"""

    def __init__(self, store_path: str = "") -> None:
        self._path = store_path or _resolve_store_path()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._assets: Dict[str, Dict[str, Any]] = {}
        # RLock：公开方法持锁后再调 _ensure_loaded/_save_locked（同持锁）
        self._lock = threading.RLock()
        self._loaded = False

    # ────────────── 持久化 ──────────────

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                if os.path.exists(self._path):
                    with open(self._path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        tasks = data.get("tasks")
                        assets = data.get("assets")
                        self._tasks = {
                            k: v for k, v in (tasks or {}).items()
                            if isinstance(v, dict) and v.get("task_id")}
                        self._assets = {
                            k: v for k, v in (assets or {}).items()
                            if isinstance(v, dict) and v.get("asset_id")}
            except Exception:
                logger.debug("[gen_task] 加载失败，按空库启动（自愈）", exc_info=True)
                self._tasks = {}
                self._assets = {}
            self._loaded = True

    def _save_locked(self) -> None:
        """原子写（tempfile + os.replace）。失败只记日志，**绝不抛出**。"""
        try:
            d = os.path.dirname(self._path)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="gt_", suffix=".tmp", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"tasks": self._tasks, "assets": self._assets},
                              f, ensure_ascii=False, indent=1)
                os.replace(tmp, self._path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        logger.debug("[gen_task] 临时文件清理失败", exc_info=True)
        except Exception:
            logger.debug("[gen_task] 持久化失败（不阻断生成主链路）", exc_info=True)

    def _evict_locked(self) -> None:
        """LRU 上限：只裁**终态**任务/资产，活跃记录一条都不动。"""
        terminal = [t for t in self._tasks.values()
                    if t.get("status") in TERMINAL_STATUSES]
        if len(terminal) > _MAX_TASKS:
            terminal.sort(key=lambda t: t.get("updated_at") or 0.0)
            for t in terminal[: len(terminal) - _MAX_TASKS]:
                self._tasks.pop(t.get("task_id"), None)
        if len(self._assets) > _MAX_ASSETS:
            items = sorted(self._assets.values(),
                           key=lambda a: a.get("updated_at") or 0.0)
            for a in items[: len(items) - _MAX_ASSETS]:
                self._assets.pop(a.get("asset_id"), None)

    # ────────────── GenerationTask ──────────────

    def begin(self, kind: str, params: Dict[str, Any], *,
              force: bool = False) -> Tuple[Dict[str, Any], bool]:
        """登记一个新任务；同幂等键已有**活跃**任务 ⇒ 返回既有记录（deduped=True）。

        ``force=True`` 绕过查重（前端「刻意再抽一张」）。终态记录不命中查重。
        返回 (记录, 是否去重)；记录一定非空（内存操作不会失败；
        持久化失败已在 _save_locked 内吞掉）。
        """
        params = params if isinstance(params, dict) else {}
        key = idempotency_key(
            kind,
            str(params.get("prompt") or ""),
            str(params.get("model") or ""),
            size=str(params.get("size") or ""),
            seed=params.get("seed"),
            duration=params.get("duration"),
            channel_id=str(params.get("channel_id") or ""),
        )
        with self._lock:
            self._ensure_loaded()
            if not force:
                for rec in self._tasks.values():
                    if (rec.get("idempotency_key") == key
                            and rec.get("status") in ACTIVE_STATUSES):
                        return dict(rec), True
            now = time.time()
            task_id = uuid.uuid4().hex[:12]
            rec = {
                "task_id": task_id,
                "idempotency_key": key,
                "kind": str(kind or "").strip().lower(),
                "prompt": str(params.get("prompt") or ""),
                "prompt_head": str(params.get("prompt") or "")[:_PROMPT_HEAD],
                "model": str(params.get("model") or ""),
                "size": str(params.get("size") or ""),
                "seed": params.get("seed"),
                "duration": params.get("duration"),
                "channel_id": str(params.get("channel_id") or ""),
                "reference": str(params.get("reference") or ""),
                "character_id": str(params.get("character_id") or ""),
                "job_id": "",
                "status": "queued",
                "result_paths": [],
                "asset_id": "",
                "canvas_node_id": "",
                "error": "",
                "created_at": now,
                "updated_at": now,
            }
            self._tasks[task_id] = rec
            self._evict_locked()
            self._save_locked()
            return dict(rec), False

    def set_job_id(self, task_id: str, job_id: str) -> None:
        """绑定 canvas_gen_jobs 的 job_id（提交后回填）。失败绝不抛出。"""
        with self._lock:
            self._ensure_loaded()
            rec = self._tasks.get(task_id)
            if rec is None:
                return
            rec["job_id"] = str(job_id or "")
            rec["updated_at"] = time.time()
            self._save_locked()

    def finish(self, task_id: str, status: str, *,
               result_paths: Optional[List[str]] = None,
               asset_id: str = "", canvas_node_id: str = "",
               error: str = "") -> Optional[Dict[str, Any]]:
        """收尾登记：status 必须为终态（done/failed/cancelled），否则拒改返回 None。

        可被重复调用（重试场景后写覆盖前写），字段空值不覆盖已有。
        """
        if status not in TERMINAL_STATUSES:
            logger.debug("[gen_task] finish 收到非终态 status=%r，忽略", status)
            return None
        with self._lock:
            self._ensure_loaded()
            rec = self._tasks.get(task_id)
            if rec is None:
                return None
            rec["status"] = status
            if result_paths:
                rec["result_paths"] = [str(p) for p in result_paths if p]
            if asset_id:
                rec["asset_id"] = str(asset_id)
            if canvas_node_id:
                rec["canvas_node_id"] = str(canvas_node_id)
            rec["error"] = str(error or "") if status != "done" else ""
            rec["updated_at"] = time.time()
            self._evict_locked()
            self._save_locked()
            return dict(rec)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure_loaded()
            rec = self._tasks.get(task_id)
            return dict(rec) if rec else None

    def latest_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        """按幂等键查最近一条记录（读端点 ?key= 用）。"""
        with self._lock:
            self._ensure_loaded()
            best = None
            for rec in self._tasks.values():
                if rec.get("idempotency_key") == key:
                    if best is None or (rec.get("updated_at") or 0.0) >= (best.get("updated_at") or 0.0):
                        best = rec
            return dict(best) if best else None

    def list_tasks(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            self._ensure_loaded()
            items = sorted(self._tasks.values(),
                           key=lambda t: t.get("created_at") or 0.0, reverse=True)
            return [dict(t) for t in items[: max(1, int(limit))]]

    # ────────────── AssetNode ──────────────

    def record_asset(self, asset_id: str, *, path: str, kind: str = "",
                     generation_task_id: str = "", canvas_node_id: str = "",
                     quality_score: Any = None, consistency_score: Any = None,
                     perception: Optional[Dict[str, Any]] = None,
                     timeline_clip_ids: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """登记/更新 AssetNode 记录（同 asset_id 再调用 = 增量更新，空值不覆盖）。

        asset_id 或 path 为空 ⇒ 拒绝（诚实：不造无主记录）。失败绝不抛出。
        """
        asset_id = str(asset_id or "").strip()
        path = str(path or "").strip()
        if not asset_id or not path:
            return None
        with self._lock:
            self._ensure_loaded()
            now = time.time()
            rec = self._assets.get(asset_id)
            if rec is None:
                rec = {
                    "asset_id": asset_id,
                    "path": path,
                    "kind": str(kind or "").strip().lower(),
                    "generation_task_id": "",
                    "canvas_node_id": "",
                    "quality_score": None,
                    "consistency_score": None,
                    "perception": {},
                    "timeline_clip_ids": [],
                    "created_at": now,
                    "updated_at": now,
                }
                self._assets[asset_id] = rec
            if path:
                rec["path"] = path
            if kind:
                rec["kind"] = str(kind).strip().lower()
            if generation_task_id:
                rec["generation_task_id"] = str(generation_task_id)
            if canvas_node_id:
                rec["canvas_node_id"] = str(canvas_node_id)
            q = _clamp01(quality_score)
            if q is not None:
                rec["quality_score"] = q
            c = _clamp01(consistency_score)
            if c is not None:
                rec["consistency_score"] = c
            if isinstance(perception, dict) and perception:
                merged = dict(rec.get("perception") or {})
                merged.update(perception)
                rec["perception"] = merged
            if isinstance(timeline_clip_ids, (list, tuple)) and timeline_clip_ids:
                ids = list(rec.get("timeline_clip_ids") or [])
                for cid in timeline_clip_ids:
                    cid = str(cid or "")
                    if cid and cid not in ids:
                        ids.append(cid)
                rec["timeline_clip_ids"] = ids
            rec["updated_at"] = now
            self._evict_locked()
            self._save_locked()
            return dict(rec)

    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure_loaded()
            rec = self._assets.get(asset_id)
            return dict(rec) if rec else None

    def find_asset_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        """按文件路径反查资产（clip 无 asset_id 字段时的兜底）。"""
        path = str(path or "").strip()
        if not path:
            return None
        norm = path.replace("\\", "/")
        with self._lock:
            self._ensure_loaded()
            best = None
            for rec in self._assets.values():
                if str(rec.get("path") or "").replace("\\", "/") == norm:
                    if best is None or (rec.get("updated_at") or 0.0) >= (best.get("updated_at") or 0.0):
                        best = rec
            return dict(best) if best else None

    def resolve_lineage(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        """clip → asset → task → canvas_node 链查询（诚实：查不到的槽位为 None）。

        只读，不写账本。clip 认 ``asset_id`` / ``path`` / ``canvas_node_id``
        三个入口字段。
        """
        out: Dict[str, Any] = {
            "clip_id": "", "asset": None, "task": None, "canvas_node_id": "",
        }
        if not isinstance(clip, dict):
            return out
        out["clip_id"] = str(clip.get("id") or "")
        asset = None
        aid = str(clip.get("asset_id") or "").strip()
        if aid:
            asset = self.get_asset(aid)
        if asset is None:
            asset = self.find_asset_by_path(
                str(clip.get("path") or clip.get("file_path") or ""))
        out["asset"] = asset
        if asset:
            tid = str(asset.get("generation_task_id") or "")
            if tid:
                out["task"] = self.get_task(tid)
        if out["task"] is None:
            # 兜底：clip 直接带 canvas_node_id → 反查同节点任务
            nid = str(clip.get("canvas_node_id") or "").strip()
            if nid:
                with self._lock:
                    self._ensure_loaded()
                    best = None
                    for rec in self._tasks.values():
                        if rec.get("canvas_node_id") == nid:
                            if best is None or (rec.get("updated_at") or 0.0) >= (best.get("updated_at") or 0.0):
                                best = rec
                    out["task"] = dict(best) if best else None
        if asset:
            out["canvas_node_id"] = str(asset.get("canvas_node_id") or "")
        if not out["canvas_node_id"] and out["task"]:
            out["canvas_node_id"] = str(out["task"].get("canvas_node_id") or "")
        if not out["canvas_node_id"]:
            out["canvas_node_id"] = str(clip.get("canvas_node_id") or "")
        return out


# ────────────── 模块级单例 ──────────────

_STORE: Optional[GenTaskStore] = None
_STORE_LOCK = threading.Lock()


def get_store() -> GenTaskStore:
    """进程内共享账本单例（路径解析在首次创建时完成，env 覆盖生效于创建前）。"""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = GenTaskStore()
        return _STORE
