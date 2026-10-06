# -*- coding: utf-8 -*-
"""画布节点增量缓存 —— 「同参数不重抽，改一处只重跑下游」

解决的问题
----------
画布目前是「人逐节点点生成」，**每次点击都从零抽**：
即使提示词、模型、尺寸、上游参考图一个字都没变，也会重新消耗一次云端额度。
ComfyUI 的解法是「按节点 hash 缓存 + 增量执行」，本模块提供同等的**节点级缓存**。

设计要点
--------
1. **指纹必须含上游指纹** —— 否则「改了上游、下游仍命中旧缓存」，得到过期产物。
   这是本模块与 `draw_book.fingerprint` 最本质的区别（后者只看自身参数）。
2. **只对「输入」做指纹，排除「输出」** —— 生成结果（imageUrl/status/proxyScore…）
   是**产物**不是**参数**；若把它们算进指纹，生成一次指纹就变了，缓存永不命中。
   见 `_OUTPUT_KEYS`。
3. **纪律与 draw_book 完全一致**：RLock + 原子写（临时文件 + os.replace）、
   异常绝不抛出（缓存失效不得阻断主链路）、LRU 上限、测试路径隔离。

不做的事（明确边界）
--------------------
- 不做审美判断（那是 `gen_critic` 的代理分与 `five_dimension_scorer` 的职责）；
  本模块只回答「这组输入是否产出过」，不判断产物好坏。
- 不落盘大二进制：只存**产物引用**（URL / 本地路径），产物本体仍由宿主 inbox 管理。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 1000          # LRU 条目上限
_TTL_DAYS = 30.0             # 缓存新鲜度：超过此天数的条目视为过期（不删，但不命中）
_SAFE_HEAD = 80              # 人读用提示词前缀长度

_DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))),
    "data", "canvas_node_cache.json")

# 测试隔离：CANVAS_NODE_CACHE_PATH 存在时优先使用（缺省仍是 data/canvas_node_cache.json）。
# 为什么需要：测试若直连正式缓存，会把测试产物写进真相源，污染真实命中率。
_STORE_ENV = "CANVAS_NODE_CACHE_PATH"

# 输出/易变字段：**不参与指纹**。
# 判据：这些键要么是「生成产物」（写回后不该算作参数变化），
#       要么是「UI 瞬时态」（选中/展开/忙闲）。
# ⚠️ 已知边界：这是黑名单而非白名单——若将来某节点新增一个
#   「既是输入又会频繁自变」的字段，需要补进本表，否则缓存会永远不命中。
_OUTPUT_KEYS = frozenset({
    # 生成产物
    "imageUrl", "videoUrl", "audioUrl", "posterUrl", "thumbUrl", "sheetUrl",
    "firstFrameUrl", "lastFrameUrl", "refVideoUrl", "captureUrls", "sourceUrl",
    "frames", "frameUrls", "outputUrl", "previewUrl",
    # 质量闭环回写（产物性质）
    "proxyScore", "isProxy", "proxyDetail", "recommendation", "repairPlan",
    "lastSeed", "qualityScores", "estimatedDims",
    # 状态/瞬时态
    "status", "progress", "errorMessage", "warnings", "busy", "running",
    "selected", "collapsed", "hovered", "dirty", "loaded",
})

# 归一化时**必须剥离**的键（与 _OUTPUT_KEYS 分开：这些是结构性的，不是产物）
_STRUCTURAL_KEYS = frozenset({"kind"})


def _resolve_store_path() -> str:
    """解析缓存路径：环境变量 > 默认（data/canvas_node_cache.json）。"""
    env = os.environ.get(_STORE_ENV)
    return env.strip() if env and env.strip() else _DEFAULT_STORE


def normalize_params(params: Optional[Dict[str, Any]]) -> str:
    """参数归一：剥掉输出/结构性字段 → 键排序 → 紧凑 JSON。

    语义：「同一组输入」必须得到同一个字符串，与字典插入顺序无关。
    """
    stable = {
        k: v for k, v in (params or {}).items()
        if k not in _OUTPUT_KEYS and k not in _STRUCTURAL_KEYS
    }
    try:
        return json.dumps(stable, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), default=str)
    except Exception:
        # 万一个别值不可序列化 → 退化为其 repr，仍保证确定性
        safe = {k: repr(v) for k, v in stable.items()}
        return json.dumps(safe, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))


def node_fingerprint(kind: str, params: Optional[Dict[str, Any]],
                     upstream: Optional[Iterable[str]] = None) -> str:
    """节点指纹 = sha1(kind | 归一参数 | 排序后的上游指纹)[:16]。

    ``upstream`` 传**上游节点的指纹**（不是 id）——这样：
    - 上游参数变 → 上游指纹变 → 本节点指纹变 → 缓存自然失效
    - 上游只是被拖动了位置（参数没变）→ 指纹不变 → 缓存仍命中

    **这是「增量执行」的地基**：指纹沿边向下游传播，天然实现
    「改一处 → 只有它及其下游失效」。
    """
    ups = sorted(str(u) for u in (upstream or ()) if u)
    raw = "|".join([
        str(kind or ""),
        normalize_params(params),
        ",".join(ups),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class NodeCacheStore:
    """画布节点产物缓存（线程安全，持久化原子写）。"""

    def __init__(self, store_path: str = "", max_entries: int = _MAX_ENTRIES,
                 ttl_days: float = _TTL_DAYS):
        self._path = store_path or _resolve_store_path()
        self._max_entries = max(10, int(max_entries))
        self._ttl_sec = max(0.0, float(ttl_days)) * 86400.0
        self._entries: Dict[str, Dict[str, Any]] = {}
        # RLock：公开方法持锁后会再调 _ensure_loaded/_save_locked（同持锁）
        # ——非重入 Lock 会自我死锁（与 _clips_lock 同款约束）
        self._lock = threading.RLock()
        self._loaded = False
        self._hits = 0
        self._misses = 0
        self._stores = 0

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
                        entries = data.get("entries", data)
                        if isinstance(entries, dict):
                            self._entries = {
                                k: v for k, v in entries.items()
                                if isinstance(v, dict) and "output" in v}
            except Exception:
                logger.debug("[canvas_node_cache] 加载失败，按空缓存启动", exc_info=True)
                self._entries = {}
            self._loaded = True

    def _save_locked(self) -> None:
        try:
            d = os.path.dirname(self._path)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="cnc_", suffix=".tmp", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"version": 1, "entries": self._entries},
                              f, ensure_ascii=False, indent=1)
                os.replace(tmp, self._path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        logger.debug("[canvas_node_cache] 临时文件清理失败", exc_info=True)
        except Exception:
            logger.debug("[canvas_node_cache] 持久化失败（不阻断主链路）", exc_info=True)

    def _evict_lru_locked(self) -> None:
        """条目超限时淘汰 last_used 最旧的。"""
        while len(self._entries) > self._max_entries:
            oldest = min(self._entries,
                         key=lambda k: self._entries[k].get("last_used", 0.0))
            del self._entries[oldest]

    def _fresh(self, entry: Dict[str, Any]) -> bool:
        """TTL 判定：0 表示不过期。"""
        if self._ttl_sec <= 0:
            return True
        return (time.time() - float(entry.get("last_used", 0.0))) <= self._ttl_sec

    # ────────────── 读写 ──────────────

    def lookup(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        """查缓存。命中返回产物 dict 的浅拷贝；未命中/过期返回 None。异常绝不抛出。"""
        fp = str(fingerprint or "").strip()
        if not fp:
            self._misses += 1
            return None
        with self._lock:
            self._ensure_loaded()
            entry = self._entries.get(fp)
            if not entry or not self._fresh(entry):
                self._misses += 1
                return None
            entry["hits"] = int(entry.get("hits", 0)) + 1
            entry["last_used"] = time.time()
            self._hits += 1
            out = entry.get("output")
            return dict(out) if isinstance(out, dict) else (
                {"value": out} if out is not None else None)

    def store(self, fingerprint: str, output: Any, *,
              kind: str = "", head: str = "") -> None:
        """写缓存。异常绝不抛出。``output`` 应为可 JSON 序列化的产物引用。"""
        fp = str(fingerprint or "").strip()
        if not fp or output is None:
            return
        try:
            with self._lock:
                self._ensure_loaded()
                now = time.time()
                self._entries[fp] = {
                    "kind": str(kind or "")[:32],
                    "head": str(head or "")[:_SAFE_HEAD],
                    "output": output,
                    "hits": 0,
                    "created_at": now,
                    "last_used": now,
                }
                self._stores += 1
                self._evict_lru_locked()
                self._save_locked()
        except Exception:
            logger.debug("[canvas_node_cache] 写入失败（不阻断主链路）", exc_info=True)

    def invalidate(self, fingerprint: str) -> bool:
        """显式失效一个条目（返回是否确实删掉了）。"""
        fp = str(fingerprint or "").strip()
        if not fp:
            return False
        with self._lock:
            self._ensure_loaded()
            existed = self._entries.pop(fp, None) is not None
            if existed:
                self._save_locked()
            return existed

    def clear(self) -> int:
        """清空缓存，返回清掉的条目数。"""
        with self._lock:
            self._ensure_loaded()
            n = len(self._entries)
            self._entries = {}
            self._save_locked()
            return n

    def stats(self) -> Dict[str, Any]:
        """只读统计（供 UI 显示命中率 / 诊断）。"""
        with self._lock:
            self._ensure_loaded()
            total = self._hits + self._misses
            return {
                "entries": len(self._entries),
                "max_entries": self._max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "stores": self._stores,
                "hit_rate": round(self._hits / total, 4) if total else 0.0,
                "ttl_days": round(self._ttl_sec / 86400.0, 1),
            }


_store: Optional[NodeCacheStore] = None
_store_lock = threading.Lock()


def get_store() -> NodeCacheStore:
    """进程级单例。"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = NodeCacheStore()
    return _store
