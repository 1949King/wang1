"""评分簿（P0-2 · 评分回写闭环）
==========================================
问题（对照鲸影学到的）：项目已有五维打分卡，但**打完就丢**——
`_render_score_results()` 只渲染到 QListWidget，不写回任何存储；提示词模板也是
静态的。守护/质检已经能「发现问题」，但**学不到任何东西**——同一个坑下次还会踩。

本模块把打分结果沉淀成**风格分评分簿**，形成闭环：

    生成 → 打分（现有五维卡）→ 写回评分簿（record）
                                ↓
    下次同风格生成前 → best_combo() → 自动选用历史高分增益/负面词组合

条目结构::

    {
      "style_dna":   "都市逆袭|冷色调",       # 风格命名空间（隔离，互不污染）
      "dims":        {"画面质量": 0.8, ...},  # 五维分数（0~1 或 0~100 均可）
      "gains":       ["8K", "无阴影"],        # 本次用的增益词组合
      "negatives":   ["三通结构", "多余分支"], # 本次用的负面词组合
      "score":       0.78,                    # 综合分（weighted_score / 100）
      "retake":      False,                   # 是否被用户重拍（重拍 → 降权）
      "time":        1695...,
    }

设计纪律：
  - **纯逻辑、不 import app 包**（同 guard_base / provider_caps / provider_pool）；
  - 持久化 ``~/.shiguang/score_book.json``：**0600 权限 + 原子写**；
  - 重拍降权：``retake=True`` 的条目在聚合时分数按 0.4 折算（而不是删掉——
    失败样本也有参考价值，但被重拍过的组合下次不再优先）；
  - 每个风格命名空间独立（``best_combo`` 只看同 style_dna），不同风格互不污染；
  - 评分簿不可用（读不了/写不了）一律诚实降级，绝不阻断生成主链路。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.core.ai.score_book")

DEFAULT_STORE = ("~", ".shiguang", "score_book.json")

# 重拍条目聚合权重（正常 1.0）
RETAKE_WEIGHT = 0.4

# 每个风格命名空间最多保留条数（防无限膨胀）
MAX_ENTRIES_PER_STYLE = 200

# best_combo 的最低样本综合分（低于它不推荐——样本太少/太差）
MIN_RECOMMEND_SCORE = 0.5


def _norm_combo(items: Any) -> List[str]:
    """增益/负面词组合归一：去空、去重、保序。"""
    seen: List[str] = []
    for it in (items or []):
        s = str(it).strip()
        if s and s not in seen:
            seen.append(s)
    return seen


def _combo_key(gains: List[str], negatives: List[str]) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    return (tuple(sorted(gains)), tuple(sorted(negatives)))


class ScoreBook:
    """风格评分簿（线程安全；懒加载持久化）。"""

    def __init__(self, store_path: str = ""):
        self._lock = threading.RLock()
        self._store = store_path or os.path.join(
            os.path.expanduser(DEFAULT_STORE[0]), *DEFAULT_STORE[1:])
        self._data: Dict[str, List[Dict[str, Any]]] = {}   # style_dna → [entry...]
        self._loaded = False

    # ══════════════════════════════════════════
    # 持久化（0600 + 原子写）
    # ══════════════════════════════════════════

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                with open(self._store, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._data = {
                        str(k): [e for e in v if isinstance(e, dict)]
                        for k, v in data.get("entries", {}).items()
                        if isinstance(v, list)
                    }
            except FileNotFoundError:
                self._data = {}
            except (OSError, ValueError):
                logger.warning("[score_book] 评分簿文件损坏，按空簿启动（%s）",
                               self._store, exc_info=True)
                self._data = {}
            self._loaded = True

    def _save_locked(self) -> None:
        """原子写（调用方须已持锁）。失败只记日志——学习数据丢失可接受。"""
        try:
            d = os.path.dirname(self._store) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="score_book_", suffix=".tmp", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"version": 1, "entries": self._data},
                              f, ensure_ascii=False, indent=2)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self._store)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        except OSError:
            logger.warning("[score_book] 评分簿写盘失败", exc_info=True)

    # ══════════════════════════════════════════
    # 写入
    # ══════════════════════════════════════════

    def record(self, style_dna: str, *, dims: Optional[Dict[str, Any]] = None,
               gains: Any = None, negatives: Any = None, score: float = 0.0,
               retake: bool = False, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """写一条评分记录。

        ``score`` 接受 0~1 或 0~100（>1 自动除以 100 归一）。
        ``retake=True`` 表示这一组合被用户重拍过——聚合时降权，不删除。
        """
        entry = {
            "style_dna": str(style_dna or "default"),
            "dims": {str(k): float(v) for k, v in (dims or {}).items()
                     if isinstance(v, (int, float))},
            "gains": _norm_combo(gains),
            "negatives": _norm_combo(negatives),
            "score": self._norm_score(score),
            "retake": bool(retake),
            "time": time.time(),
        }
        if meta:
            entry["meta"] = {str(k): v for k, v in meta.items()}
        with self._lock:
            self._ensure_loaded()
            entries = self._data.setdefault(entry["style_dna"], [])
            entries.append(entry)
            if len(entries) > MAX_ENTRIES_PER_STYLE:      # 只留最近 N 条
                del entries[:len(entries) - MAX_ENTRIES_PER_STYLE]
            self._save_locked()
        logger.info("[score_book] 记录 %s：score=%.2f gains=%s negatives=%s retake=%s",
                    entry["style_dna"], entry["score"], entry["gains"],
                    entry["negatives"], entry["retake"])
        return entry

    def record_retake(self, style_dna: str, *, gains: Any = None,
                      negatives: Any = None, score: float = 0.0) -> Dict[str, Any]:
        """用户点了「重拍」：把该组合记为 retake 条目（下次不再优先）。"""
        return self.record(style_dna, gains=gains, negatives=negatives,
                           score=score, retake=True)

    @staticmethod
    def _norm_score(score: float) -> float:
        try:
            s = float(score or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if s > 1.0:      # 0~100 → 0~1
            s = s / 100.0
        return max(0.0, min(1.0, s))

    # ══════════════════════════════════════════
    # 查询（闭环的另一半）
    # ══════════════════════════════════════════

    def best_combo(self, style_dna: str, *, dim: str = "",
                   min_score: float = MIN_RECOMMEND_SCORE
                   ) -> Optional[Dict[str, Any]]:
        """查该风格下**历史表现最好**的增益/负面词组合。

        聚合：按 (gains, negatives) 组合分组 → 加权平均分（retake 权重 0.4）
        → 取最高。``dim`` 给定时优先用该维度的分数聚合（如"画面质量"）。

        Returns::
            {"gains": [...], "negatives": [...], "score": 加权分,
             "samples": 样本数, "retake_rate": 重拍率} | None（没有可用样本）
        """
        dna = str(style_dna or "").strip()
        if not dna:
            return None
        with self._lock:
            self._ensure_loaded()
            entries = list(self._data.get(dna) or [])
        if not entries:
            return None

        groups: Dict[Tuple[Tuple[str, ...], Tuple[str, ...]], Dict[str, Any]] = {}
        for e in entries:
            key = _combo_key(e.get("gains") or [], e.get("negatives") or [])
            g = groups.setdefault(key, {
                "gains": e.get("gains") or [], "negatives": e.get("negatives") or [],
                "score_sum": 0.0, "n": 0, "retakes": 0})
            # retake 的分数直接按 RETAKE_WEIGHT 打折计入（而非只降聚合权重）——
            # 否则「只有一条 retake 记录的组合」仍会以原分胜出，降权形同虚设
            w = RETAKE_WEIGHT if e.get("retake") else 1.0
            s = float(e.get("score") or 0.0)
            if dim:   # 指定维度优先（缺维度数据的条目退回综合分）
                dims = e.get("dims") or {}
                s = self._norm_score(dims.get(dim, s * 100 if s <= 1 else s))
            g["score_sum"] += s * w
            g["n"] += 1
            g["retakes"] += 1 if e.get("retake") else 0

        best: Optional[Dict[str, Any]] = None
        for g in groups.values():
            avg = g["score_sum"] / g["n"] if g["n"] else 0.0
            if avg < min_score:
                continue
            cand = {
                "gains": list(g["gains"]),
                "negatives": list(g["negatives"]),
                "score": round(avg, 4),
                "samples": g["n"],
                "retake_rate": round(g["retakes"] / g["n"], 4) if g["n"] else 0.0,
            }
            if best is None or cand["score"] > best["score"]:
                best = cand
        if best is not None:
            logger.info("[score_book] %s 推荐组合：score=%.2f samples=%d（dim=%s）",
                        dna, best["score"], best["samples"], dim or "综合")
        return best

    def stats(self, style_dna: str = "") -> Dict[str, Any]:
        """评分簿概况（供诊断 / UI）。"""
        with self._lock:
            self._ensure_loaded()
            if style_dna:
                entries = self._data.get(style_dna) or []
                return {
                    "style_dna": style_dna, "entries": len(entries),
                    "avg_score": round(
                        sum(float(e.get("score") or 0) for e in entries) / len(entries), 4)
                    if entries else 0.0,
                }
            return {"styles": {k: len(v) for k, v in self._data.items()},
                    "total": sum(len(v) for v in self._data.values())}


# ═══════════════════════════════════════════════════════════
# 模块级单例（懒加载）
# ═══════════════════════════════════════════════════════════

_book_instance: Optional[ScoreBook] = None
_book_lock = threading.Lock()


def get_score_book() -> ScoreBook:
    """全局评分簿单例（路径固定 ~/.shiguang/score_book.json）。"""
    global _book_instance
    if _book_instance is None:
        with _book_lock:
            if _book_instance is None:
                _book_instance = ScoreBook()
    return _book_instance


def reset_book_for_test(store_path: str) -> ScoreBook:
    """测试专用：独立路径的新簿子。"""
    return ScoreBook(store_path=store_path)
