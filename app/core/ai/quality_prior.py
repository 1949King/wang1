"""质量先验库（Quality Prior Store）
====================================
来源：《异构动态协作引擎规格书》v4.3 §14/§39 思想的最小可行切片——
「分桶 EMA 更新均值方差，作为路由预测 q̂ 的唯一来源」。

在本项目中的定位：
  - 输入：每次云端生成的**结果观测**（成功/失败，或后续 B 模块评分器的 0~1 质量分）；
  - 输出：`predict()` 给出每个 provider 的期望质量 q̂（均值）与不确定度（方差）；
  - 消费：`provider_caps.resolve_order(priors=...)` 用它做收益函数排序
    （V = q̂ − λ_c·price），替代纯 quality_tier 静态排序。

设计纪律：
- **纯模块**（不 import app 包），可独立加载/单测；
- 分桶键 = (provider, kind)：kind 预留给介质/模型版本分桶（默认 "default"）；
- EMA 更新：mean += α·(x−mean)；var = (1−α)·(var + α·δ²)（标准 EMA 方差递推）；
- **冷启动不确定度**（规格 §39）：新桶可 `inherit()` 自旧桶——继承均值、方差 ×4
  （至少 0.25），体现「新版本质量不确定、需要探索」；
- 观测门控思想：本模块只存数据；「断网/暂停时是否记录」由调用方决定
  （video_generation_client 只在真实执行后记录，本地占位不记录）；
- 持久化：JSON + 原子写（临时文件 + os.replace），记录失败绝不抛出——
  先验库是优化项，绝不能拖垮生成主链路。

诚实声明（当前切片边界）：
  现在的观测样本是「执行成败」（1.0/0.0），本质是**可用性先验**；待 B 模块
  评分器（五维分）接入后，同一条 record_outcome 通道直接改喂真值质量分，
  路由无需任何改动。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_ALPHA = 0.3                # EMA 步长（与 affect_model 期望 EWMA 一致）
_COLD_START_VAR = 0.25      # 冷启动初始方差（宽泛不确定）
_INHERIT_VAR_FACTOR = 4.0   # 继承时方差放大倍数（规格 §39 冷启动不确定度）
_MAX_VAR = 1.0

_DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
    "data", "quality_prior.json")

# 测试隔离：QUALITY_PRIOR_PATH 存在时优先使用（缺省仍是 data/quality_prior.json）。
# 与 draw_book 同款纪律：测试不得写入正式先验库。
_STORE_ENV = "QUALITY_PRIOR_PATH"


def _resolve_store_path() -> str:
    """解析先验库路径：环境变量 > 默认（data/quality_prior.json）。"""
    env = os.environ.get(_STORE_ENV)
    return env.strip() if env and env.strip() else _DEFAULT_STORE


def _bucket_key(provider: str, kind: str = "default") -> str:
    return f"{provider}::{kind}"


class QualityPriorStore:
    """分桶 EMA 质量先验库（线程安全，持久化原子写）。"""

    def __init__(self, store_path: str = "", alpha: float = _ALPHA):
        self._path = store_path or _resolve_store_path()
        self._alpha = max(0.01, min(1.0, float(alpha)))
        self._buckets: Dict[str, Dict[str, float]] = {}
        # RLock：record/predict 等公开方法持锁后会再调 _ensure_loaded/_save_locked
        # （同样持锁）——非重入 Lock 会自我死锁（与 _clips_lock 同款约束）
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
                logger.debug("[quality_prior] 加载失败，按空库启动", exc_info=True)
                self._buckets = {}
            self._loaded = True

    def _save_locked(self) -> None:
        try:
            d = os.path.dirname(self._path)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="qp_", suffix=".tmp", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._buckets, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self._path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        logger.debug("忽略异常（原为 pass）: quality_prior.py", exc_info=True)
        except Exception:
            logger.debug("[quality_prior] 持久化失败（不阻断主链路）", exc_info=True)

    # ────────────── 记录 / 查询 ──────────────

    def record(self, provider: str, sample: float, kind: str = "default") -> None:
        """记录一次质量观测（0~1）。异常绝不抛出。"""
        if not provider:
            return
        try:
            x = max(0.0, min(1.0, float(sample)))
        except (TypeError, ValueError):
            return
        with self._lock:
            self._ensure_loaded()
            key = _bucket_key(provider, kind)
            b = self._buckets.get(key)
            if b is None:
                self._buckets[key] = {
                    "mean": x, "var": _COLD_START_VAR, "n": 1.0}
            else:
                a = self._alpha
                delta = x - b["mean"]
                b["mean"] = b["mean"] + a * delta
                b["var"] = min(_MAX_VAR,
                               (1 - a) * (b["var"] + a * delta * delta))
                b["n"] = b.get("n", 0.0) + 1.0
            self._save_locked()

    def record_outcome(self, provider: str, ok: bool,
                       quality: Optional[float] = None,
                       kind: str = "default") -> None:
        """结果观测入口：quality 给了就用真值（0~1），否则用成败 1.0/0.0。"""
        sample = quality if quality is not None else (1.0 if ok else 0.0)
        self.record(provider, sample, kind=kind)

    def predict(self, provider: str, kind: str = "default") -> Optional[Dict[str, float]]:
        """查询先验：{"mean","var","n"}；无数据返回 None（调用方用中性值）。"""
        with self._lock:
            self._ensure_loaded()
            b = self._buckets.get(_bucket_key(provider, kind))
            return dict(b) if b else None

    def mean_of(self, provider: str, kind: str = "default",
                default: float = 0.5) -> float:
        """便捷：取期望质量 q̂，无数据返回 default（中性探索值）。"""
        p = self.predict(provider, kind)
        return float(p["mean"]) if p else default

    def route_mean(self, provider: str) -> float:
        """路由用 q̂（切片②）：**真值桶优先**——有 "quality" 桶（初检/评分器真值）
        用真值，否则退回 "default" 桶（可用性先验），都没有返回中性 0.5。

        规格 §14「分类型分版本分桶」的落地：真值信号一到位就自动接管路由，
        可用性信号兜底，无需改任何路由代码。
        """
        with self._lock:
            self._ensure_loaded()
            q = self._buckets.get(_bucket_key(provider, "quality"))
            if q is not None:
                return float(q["mean"])
            d = self._buckets.get(_bucket_key(provider, "default"))
            if d is not None:
                return float(d["mean"])
            return 0.5

    def inherit(self, provider: str, from_kind: str, to_kind: str) -> None:
        """新桶继承旧桶（规格 §39）：继承均值、方差 ×4 体现冷启动不确定度。"""
        with self._lock:
            self._ensure_loaded()
            src = self._buckets.get(_bucket_key(provider, from_kind))
            if src is None:
                return
            key = _bucket_key(provider, to_kind)
            if key in self._buckets:
                return
            self._buckets[key] = {
                "mean": src["mean"],
                "var": min(_MAX_VAR,
                           max(src["var"] * _INHERIT_VAR_FACTOR, _COLD_START_VAR)),
                "n": 0.0,
            }
            self._save_locked()

    def summary(self) -> Dict[str, Any]:
        """全量快照（诊断/UI 展示用）。"""
        with self._lock:
            self._ensure_loaded()
            return {k: dict(v) for k, v in self._buckets.items()}

    def _reset_for_tests(self) -> None:
        with self._lock:
            self._buckets = {}
            self._loaded = True


_STORE: Optional[QualityPriorStore] = None
_STORE_LOCK = threading.Lock()


def quality_from_inspection(passed: bool, skipped: bool) -> Optional[float]:
    """把初检结论映射为真值质量样本（切片②，纯函数）。

    - passed → 1.0（通过初检+守护质检）
    - 未通过 → 0.3（内容生成出来了但质量不达标，非零——区别于「根本没生成」）
    - skipped → **None（不记录）**：观测门控思想（规格 §35）——
      初检被跳过 = 无有效观测，不污染先验库。
    """
    if skipped:
        return None
    return 1.0 if passed else 0.3


def get_store() -> QualityPriorStore:
    """进程级单例（默认路径 data/quality_prior.json）。"""
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = QualityPriorStore()
    return _STORE
