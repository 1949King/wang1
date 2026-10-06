"""抽卡账本（Draw Book）
====================================
生成抽卡闭环九层系统 · 第④层「参数沉淀」的核心载体
（方案：`docs/_reports/2026-09-27-生成抽卡闭环方案.md` §3.1，2026-09-27 用户裁定执行）。

定位：
  - 解决的问题：抽卡结果散落在空气里——同一条提示词上次用哪个种子出了好图，
    没有任何地方记得，每次都是从零抽。
  - 键（参数指纹）：``sha1(kind | normalized_prompt | model | style_tag | size)[:16]``
    —— 同一套「提示词+模型+风格+尺寸」归一桶，记录它的历史表现。
    （kind 纳入指纹是对 §3.1 原文键规格的有意扩充：方案 API 本身带 kind 参数，
    同 prompt 的图/视频混在一桶会互相污染，故入键。）
  - 值：EMA 均分 + 方差（保留探索语义）+ **best_seed**（得分最高的种子，
    来自 P0a 种子贯通的回显）+ 最近 20 条样本环形。

纪律（照 quality_prior.py 同款范式）：
- **纯模块**（不 import app 包），可独立加载/单测；
- RLock + 原子写（临时文件 + os.replace），记录失败**绝不抛出**——
  账本是优化项，绝不能拖垮生成主链路；
- 只记 ``seed_sent=True`` 的种子（调用方责任）：渠道没收到的种子记进来
  也是废物（无法复现），见 canvas_aigc 的 seed_sent 约定；
- 桶数上限 500 + LRU 淘汰；samples 环形 20 条 —— 防 JSON 无限增长。
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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ALPHA = 0.3            # EMA 步长（与 quality_prior 一致）
_COLD_START_VAR = 0.25  # 冷启动初始方差
_MAX_VAR = 1.0
_MAX_BUCKETS = 500      # LRU 桶数上限
_MAX_SAMPLES = 20       # 每桶样本环形上限
_PROMPT_HEAD = 60       # 人读用提示词前缀长度
_STALE_DAYS = 60.0      # 推荐新鲜度：last_used 超过此天数的桶**不参与推荐**

# 为什么需要新鲜度而不是只看均值：模型版本、渠道能力、提示词写法都会漂移，
# 60 天前的「这组参数出图 0.9 分」很可能已经不成立。**过期的推荐比没有推荐更糟**
# （它会把用户推向一个已经不成立的参数组合）。注意：过期只影响**推荐**，
# 不删数据（内存上限归 LRU 管），历史仍可用 stats/summary 查看。

_DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
    "data", "draw_book.json")

# 测试隔离：DRAW_BOOK_STORE_PATH 存在时优先使用（缺省仍是 data/draw_book.json）。
# 为什么需要：测试若直连正式账本，会把测试样本写进真相源，污染推荐与路由。
_STORE_ENV = "DRAW_BOOK_STORE_PATH"


def _resolve_store_path() -> str:
    """解析账本路径：环境变量 > 默认（data/draw_book.json）。"""
    env = os.environ.get(_STORE_ENV)
    return env.strip() if env and env.strip() else _DEFAULT_STORE


def normalize_prompt(prompt: str) -> str:
    """提示词归一化：NFKC（全角→半角）+ 小写 + 去除全部空白。

    语义：「一个  女孩」与「一个女孩」与「Ａ 女孩」应归同键——
    空白与全半角差异不改变抽卡意图。不做词级同义归并（那需要 NLP，
    超出确定性账本职责）。
    """
    s = unicodedata.normalize("NFKC", prompt or "").lower()
    return "".join(s.split())


def fingerprint(prompt: str, model: str, *, style_tag: str = "",
                size: str = "", kind: str = "image") -> str:
    """参数指纹：同一套「提示词+模型+风格+尺寸+介质」归一桶。"""
    raw = "|".join([
        str(kind or "image"),
        normalize_prompt(prompt),
        str(model or "").strip().lower(),
        str(style_tag or "").strip().lower(),
        str(size or "").strip().lower(),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


class DrawBookStore:
    """分桶 EMA 抽卡账本（线程安全，持久化原子写）。"""

    def __init__(self, store_path: str = "", alpha: float = _ALPHA,
                 max_buckets: int = _MAX_BUCKETS):
        self._path = store_path or _resolve_store_path()
        self._alpha = max(0.01, min(1.0, float(alpha)))
        self._max_buckets = max(10, int(max_buckets))
        self._buckets: Dict[str, Dict[str, Any]] = {}
        # RLock：公开方法持锁后会再调 _ensure_loaded/_save_locked（同持锁）——
        # 非重入 Lock 会自我死锁（与 _clips_lock 同款约束）
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
                        self._buckets = {
                            k: v for k, v in data.items()
                            if isinstance(v, dict) and "mean" in v}
            except Exception:
                logger.debug("[draw_book] 加载失败，按空库启动", exc_info=True)
                self._buckets = {}
            self._loaded = True

    def _save_locked(self) -> None:
        try:
            d = os.path.dirname(self._path)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="db_", suffix=".tmp", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._buckets, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self._path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        logger.debug("[draw_book] 临时文件清理失败", exc_info=True)
        except Exception:
            logger.debug("[draw_book] 持久化失败（不阻断主链路）", exc_info=True)

    def _evict_lru_locked(self) -> None:
        """桶数超限时淘汰 last_used 最旧的桶。"""
        while len(self._buckets) > self._max_buckets:
            oldest = min(self._buckets,
                         key=lambda k: self._buckets[k].get("last_used", 0.0))
            del self._buckets[oldest]

    # ────────────── 记录 / 查询 ──────────────

    def record_draw(self, prompt: str, model: str, score: float, *,
                    seed: Optional[int] = None, style_tag: str = "",
                    size: str = "", kind: str = "image") -> None:
        """记录一次抽卡结果。异常绝不抛出。

        ``seed`` 只应传「渠道真正收到的种子」（P0a 回显且 seed_sent=True 的）；
        传 None 表示本次无法用种子复现，仅累计均分不竞争 best_seed。
        """
        if not (prompt or "").strip() or not (model or "").strip():
            return
        try:
            x = _clamp01(float(score))
        except (TypeError, ValueError):
            return
        seed_val: Optional[int] = None
        if seed is not None:
            try:
                si = int(seed)
                if si > 0:
                    seed_val = si
            except (TypeError, ValueError):
                seed_val = None
        with self._lock:
            self._ensure_loaded()
            key = fingerprint(prompt, model, style_tag=style_tag,
                              size=size, kind=kind)
            now = time.time()
            b = self._buckets.get(key)
            if b is None:
                b = {
                    "key": key,
                    "prompt_head": (prompt or "").strip()[:_PROMPT_HEAD],
                    "prompt_norm": normalize_prompt(prompt),
                    "model": str(model).strip(),
                    "style_tag": str(style_tag or "").strip(),
                    "size": str(size or "").strip(),
                    "kind": str(kind or "image"),
                    "n": 0.0,
                    "mean": x,
                    "var": _COLD_START_VAR,
                    "best_seed": seed_val,
                    "best_score": x if seed_val is not None else -1.0,
                    "last_used": now,
                    "samples": [],
                }
                self._buckets[key] = b
            else:
                a = self._alpha
                delta = x - b["mean"]
                b["mean"] = b["mean"] + a * delta
                b["var"] = min(_MAX_VAR, (1 - a) * (b["var"] + a * delta * delta))
                b["last_used"] = now
                if seed_val is not None and x > float(b.get("best_score", -1.0)):
                    b["best_seed"] = seed_val
                    b["best_score"] = x
            b["n"] = float(b.get("n", 0.0)) + 1.0
            samples: List[Dict[str, Any]] = b.setdefault("samples", [])
            samples.append({"seed": seed_val, "score": round(x, 4),
                            "ts": round(now, 3)})
            del samples[:max(0, len(samples) - _MAX_SAMPLES)]
            self._evict_lru_locked()
            self._save_locked()

    def recommend(self, prompt: str, model: str, *, style_tag: str = "",
                  size: str = "", kind: str = "image",
                  max_age_days: float = _STALE_DAYS) -> Optional[Dict[str, Any]]:
        """查历史推荐：{"key","mean","n","best_seed","best_score","size","advice"}。

        - 给了 size → 精确指纹命中；没给 → 在同 prompt+model+风格+kind 的
          所有尺寸桶里选「均分最高、观测数决胜」的一桶（advice 注明胜出尺寸）。
        - **过期桶不返回**：last_used 超 ``max_age_days`` 天的桶视为过期
          （模型/提示词空间会漂移，推荐过期参数比不推荐更糟）→ 返回 None。
          ``max_age_days<=0`` 关闭新鲜度检查（调试/历史回看用）。
        - 无任何历史 → None（调用方不得编造推荐）。
        - best_seed 可能为 None（历史全部 seed_sent=False），此时 advice 如实说明
          「有均分无可复现种子」。
        """
        with self._lock:
            self._ensure_loaded()
            cutoff = (time.time() - float(max_age_days) * 86400.0
                      if float(max_age_days) > 0 else 0.0)

            def _fresh(v: Dict[str, Any]) -> bool:
                return float(v.get("last_used", 0.0)) >= cutoff

            b: Optional[Dict[str, Any]] = None
            if size:
                cand = self._buckets.get(fingerprint(
                    prompt, model, style_tag=style_tag, size=size, kind=kind))
                b = cand if (cand is not None and _fresh(cand)) else None
            else:
                pnorm = normalize_prompt(prompt)
                m = str(model or "").strip().lower()
                st = str(style_tag or "").strip().lower()
                cands = [
                    v for v in self._buckets.values()
                    if v.get("prompt_norm") == pnorm
                    and str(v.get("model", "")).lower() == m
                    and str(v.get("style_tag", "")).lower() == st
                    and str(v.get("kind", "image")) == str(kind or "image")
                    and _fresh(v)
                ]
                if cands:
                    b = max(cands, key=lambda v: (float(v.get("mean", 0.0)),
                                                  float(v.get("n", 0.0))))
            if b is None:
                return None
            n = int(b.get("n", 0))
            mean = float(b.get("mean", 0.0))
            best_seed = b.get("best_seed")
            best_score = float(b.get("best_score", -1.0))
            won_size = str(b.get("size", ""))
            if n < 5:
                conf = f"样本尚少（{n} 次），参考性有限"
            else:
                conf = f"历史 {n} 次抽卡均分 {mean:.2f}"
            if best_seed is not None:
                seed_part = f"；最佳种子 {best_seed}（{best_score:.2f}）"
            else:
                seed_part = "；历史均未透传种子，无可复现种子推荐"
            size_part = f"（尺寸 {won_size}）" if (won_size and not size) else ""
            return {
                "key": b.get("key"),
                "mean": round(mean, 4),
                "n": n,
                "best_seed": best_seed,
                "best_score": round(best_score, 4) if best_seed is not None else None,
                "size": won_size,
                "advice": f"{conf}{size_part}{seed_part}",
            }

    def stats(self) -> Dict[str, Any]:
        """总桶数 / 总观测 / 全体均分（诊断用）。"""
        with self._lock:
            self._ensure_loaded()
            total_n = sum(float(v.get("n", 0.0)) for v in self._buckets.values())
            if self._buckets:
                avg = sum(float(v.get("mean", 0.0)) for v in self._buckets.values()) \
                    / len(self._buckets)
            else:
                avg = 0.0
            return {
                "buckets": len(self._buckets),
                "total_draws": int(total_n),
                "mean_score": round(avg, 4),
            }

    def _reset_for_tests(self) -> None:
        with self._lock:
            self._buckets = {}
            self._loaded = True


_STORE: Optional[DrawBookStore] = None
_STORE_LOCK = threading.Lock()


def get_store() -> DrawBookStore:
    """进程级单例（默认路径 data/draw_book.json）。"""
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = DrawBookStore()
    return _STORE
