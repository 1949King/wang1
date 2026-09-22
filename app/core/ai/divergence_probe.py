"""A 模块：分歧度探针（规格书第四篇 §16-19，V4.37.9 切片⑥）
====================================================================
规格书定位（一句话）：**量化本地/云端输出差异 Δ，仅用于筛选 D 模式候选，
不直接决策路由**。

四条规格约束 → 本模块的落点：

1. **轻量预采样**（§16.1）：探针总成本 ≤ 单元生成成本 2%，严格限流——
   ``cost_gate`` 累计探针成本 / 累计单元成本，超 2% 自动降级。
2. **自适应阈值**（§16.3）：质量方差越大、不确定越高，越容易开启双路校验——
   阈值随（质量方差 + 探针自身方差）**下降**：τ = clamp(τ0 − k·(var_q + var_Δ))。
3. **分介质探针**（§17）：文本 / 视频 / 音频独立指标体系，杜绝跨介质混用。
   文本=结构化字段差异率；视频/音频=确定性廉价代理（时长+体积+内容哈希），
   接口留出升级位（换真感知指标不动调用方）。
4. **成本保护与分歧入库**（§18/§19）：超限降级为**抽样探针**（复用历史
   EMA 统计当 Δ 估计）；观测到的 Δ 用 EMA 滑更均值/方差，作为全局阈值
   自适应依据。

设计纪律：纯模块、不 import app 包、RLock（同 quality_prior 教训）、
JSON 原子写、异常不抛。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("AI短剧编辑器.core.ai.divergence_probe")

_ALPHA = 0.3               # EMA 系数（与 quality_prior 一致）
_BASE_THRESHOLD = 0.5      # τ0：无不确定度时的基础阈值
_THRESHOLD_MIN = 0.15      # 阈值下限（不确定再高也不至于逢单元必双路）
_THRESHOLD_MAX = 0.8       # 阈值上限
_VAR_GAIN = 1.0            # k：方差对阈值的压低增益
_COST_RATIO_LIMIT = 0.02   # §16.1：探针总成本 ≤ 单元成本 2%

_VALID_KINDS = ("text", "video", "audio")


# ═══════════════════════════════════════════════════════════
# 分介质分歧度指标（§17：独立指标，禁止跨介质混用）
# ═══════════════════════════════════════════════════════════

def text_divergence(local_fields: Any, cloud_fields: Any) -> float:
    """文本：结构化字段差异率（字段锁域友好的命名空间对齐比较）。

    输入可以是 dict（逐字段比）或字符串（整体比）。返回 ∈ [0,1]：
    dict → 值不同的字段数 / 并集字段数；字符串 → 按行差异率。
    """
    try:
        if isinstance(local_fields, dict) and isinstance(cloud_fields, dict):
            keys = set(local_fields) | set(cloud_fields)
            if not keys:
                return 0.0
            diff = sum(1 for k in keys if local_fields.get(k) != cloud_fields.get(k))
            return diff / len(keys)
        a = str(local_fields or "").splitlines()
        b = str(cloud_fields or "").splitlines()
        n = max(len(a), len(b))
        if n == 0:
            return 0.0
        diff = sum(1 for i in range(n)
                   if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None))
        return diff / n
    except Exception:
        logger.debug("[divergence_probe] 文本分歧计算失败", exc_info=True)
        return 0.0


def _file_signature(path: str) -> Optional[Dict[str, Any]]:
    """廉价确定性文件签名：体积 + 内容哈希（前 64KB 采样，控成本）。"""
    try:
        if not path or not os.path.isfile(path):
            return None
        size = os.path.getsize(path)
        h = hashlib.md5()  # 仅做内容指纹，非安全用途
        with open(path, "rb") as f:
            h.update(f.read(65536))
        return {"size": size, "md5": h.hexdigest()}
    except Exception:
        logger.debug("[divergence_probe] 文件签名失败: %s", path, exc_info=True)
        return None


def media_divergence(path_local: str, path_cloud: str,
                     duration_local: float = 0.0, duration_cloud: float = 0.0
                     ) -> float:
    """视频/音频：确定性廉价代理（§16.1 成本约束下的工程选择）。

    三分量合成 ∈ [0,1]：内容哈希不同(0.6 权) + 体积相对差(0.25) + 时长相对差(0.15)。
    诚实边界：这是**粗代理**——检出「两路明显不同」够用，不做语义级判断；
    升级真感知指标（关键帧 SSIM / 音频谱距）时换本函数即可，调用方零改动。
    """
    sa = _file_signature(path_local)
    sb = _file_signature(path_cloud)
    if sa is None or sb is None:
        return 0.0
    d_hash = 0.0 if sa["md5"] == sb["md5"] else 1.0
    big = max(sa["size"], sb["size"], 1)
    d_size = min(1.0, abs(sa["size"] - sb["size"]) / big)
    d_dur = 0.0
    if duration_local > 0 and duration_cloud > 0:
        d_dur = min(1.0, abs(duration_local - duration_cloud)
                    / max(duration_local, duration_cloud))
    return 0.6 * d_hash + 0.25 * d_size + 0.15 * d_dur


# ═══════════════════════════════════════════════════════════
# 探针本体
# ═══════════════════════════════════════════════════════════

class DivergenceProbe:
    """分歧度探针：EMA 统计 + 自适应阈值 + 成本门控 + D 候选判定。"""

    def __init__(self, store_path: Optional[str] = None,
                 cost_ratio_limit: float = _COST_RATIO_LIMIT):
        self._lock = threading.RLock()
        self._store_path = store_path
        self._ratio = float(cost_ratio_limit)
        # {kind: {"mean":…, "var":…, "n":…}}
        self._stats: Dict[str, Dict[str, float]] = {}
        self._probe_cost = 0.0    # 累计探针成本
        self._unit_cost = 0.0     # 累计单元生成成本
        self._loaded = False
        if store_path:
            self._ensure_loaded()

    # ── 持久化（原子写） ──

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                if self._store_path and os.path.isfile(self._store_path):
                    with open(self._store_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._stats = {k: v for k, v in
                                       (data.get("stats") or {}).items()
                                       if isinstance(v, dict)}
                        self._probe_cost = float(data.get("probe_cost") or 0.0)
                        self._unit_cost = float(data.get("unit_cost") or 0.0)
            except Exception:
                logger.debug("[divergence_probe] 载入失败（从零起步）", exc_info=True)

    def _save_locked(self) -> None:
        if not self._store_path:
            return
        try:
            payload = {"stats": self._stats,
                       "probe_cost": self._probe_cost,
                       "unit_cost": self._unit_cost}
            tmp = self._store_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._store_path)
        except Exception:
            logger.debug("[divergence_probe] 落盘失败（不阻断）", exc_info=True)

    # ── 分歧入库（§19：EMA 滑更，全局阈值自适应依据） ──

    def record(self, kind: str, delta: float) -> None:
        """记录一次实测分歧度（EMA 均值/方差递推，同 quality_prior 形式）。"""
        if kind not in _VALID_KINDS:
            return
        d = min(1.0, max(0.0, float(delta)))
        with self._lock:
            self._ensure_loaded()
            st = self._stats.setdefault(kind, {"mean": 0.5, "var": 0.25, "n": 0})
            delta_err = d - st["mean"]
            st["mean"] += _ALPHA * delta_err
            st["var"] = (1 - _ALPHA) * (st["var"] + _ALPHA * delta_err * delta_err)
            st["n"] = int(st.get("n", 0)) + 1
            self._save_locked()

    # ── 成本门控（§16.1 / §18） ──

    def note_unit_cost(self, cost: float) -> None:
        """每完成一个单元，累计其生成成本（探针预算的分母）。"""
        with self._lock:
            self._ensure_loaded()
            self._unit_cost += max(0.0, float(cost))
            self._save_locked()

    def cost_gate(self, probe_cost: float = 0.0) -> Dict[str, Any]:
        """探针能不能跑：累计探针成本 ≤ 2% 累计单元成本。

        Returns:: {"allowed": bool, "ratio": 当前占比, "reason": 人话}
        """
        with self._lock:
            self._ensure_loaded()
            would = self._probe_cost + max(0.0, float(probe_cost))
            limit = self._ratio * self._unit_cost
            if self._unit_cost <= 0:
                return {"allowed": True, "ratio": 0.0,
                        "reason": "冷启动：尚无成本基数，放行首次探针"}
            allowed = would <= limit
            return {
                "allowed": allowed,
                "ratio": (self._probe_cost / self._unit_cost)
                if self._unit_cost else 0.0,
                "reason": "" if allowed else
                f"探针成本超限（>{self._ratio:.0%} 单元成本），降级抽样探针",
            }

    def note_probe_cost(self, cost: float) -> None:
        with self._lock:
            self._ensure_loaded()
            self._probe_cost += max(0.0, float(cost))
            self._save_locked()

    # ── 自适应阈值 + D 候选判定（§16.3/§16.4） ──

    def adaptive_threshold(self, kind: str, quality_var: float = 0.0) -> float:
        """τ = clamp(τ0 − k·(var_q + var_Δ))：不确定越高 → 阈值越低 → 越易开双路。"""
        with self._lock:
            self._ensure_loaded()
            var_d = float((self._stats.get(kind) or {}).get("var", 0.25))
        raw = _BASE_THRESHOLD - _VAR_GAIN * (max(0.0, float(quality_var)) + var_d)
        return min(_THRESHOLD_MAX, max(_THRESHOLD_MIN, raw))

    def estimate(self, kind: str) -> float:
        """抽样探针（§18）：不跑实测，复用历史 EMA 均值当 Δ 估计。"""
        with self._lock:
            self._ensure_loaded()
            return float((self._stats.get(kind) or {}).get("mean", 0.5))

    def is_dual_candidate(self, kind: str, delta: Optional[float] = None,
                          quality_var: float = 0.0) -> Dict[str, Any]:
        """D 模式开启条件（§16.4）：Δ > 自适应阈值。

        ``delta=None`` → 用 EMA 估计（抽样探针语义）。
        Returns:: {"candidate": bool, "delta":…, "threshold":…,
                   "estimated": bool, "reason": 人话}
        """
        if kind not in _VALID_KINDS:
            return {"candidate": False, "delta": 0.0, "threshold": 1.0,
                    "estimated": False, "reason": f"未知介质 {kind}"}
        estimated = delta is None
        d = self.estimate(kind) if estimated else min(1.0, max(0.0, float(delta)))
        tau = self.adaptive_threshold(kind, quality_var)
        ok = d > tau
        return {
            "candidate": ok,
            "delta": d,
            "threshold": tau,
            "estimated": estimated,
            "reason": (f"Δ={d:.2f} {'>' if ok else '≤'} τ={tau:.2f}"
                       + ("（EMA 估计）" if estimated else "（实测）")),
        }

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            return {
                "stats": {k: dict(v) for k, v in self._stats.items()},
                "probe_cost": self._probe_cost,
                "unit_cost": self._unit_cost,
                "cost_ratio": (self._probe_cost / self._unit_cost)
                if self._unit_cost else 0.0,
            }


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_PROBE: Optional[DivergenceProbe] = None
_PROBE_LOCK = threading.Lock()


def get_probe() -> DivergenceProbe:
    """全局单例（数据落在 data/divergence_probe.json）。"""
    global _PROBE
    with _PROBE_LOCK:
        if _PROBE is None:
            try:
                root = os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__)))))
                path = os.path.join(root, "data", "divergence_probe.json")
            except Exception:
                path = None
            _PROBE = DivergenceProbe(store_path=path)
        return _PROBE
