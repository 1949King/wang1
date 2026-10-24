"""六级降级体系（Degradation Levels）
====================================
来源：《异构动态协作引擎规格书》v4.3 §44-46「异常处理与六级降级」的最小落地。

规格六级 → 本项目映射（V4.37.6）：

| 级别 | 规格定义 | 本项目落地 | 状态 |
|---|---|---|---|
| L0 | （观测用）完整交付 | 首选渠道按原 spec 出齐段数 | ✅ |
| L1 | 双路降级（D→单路） | 无双路模式，预留 | 🔲 预留 |
| L2 | 云端降级（换渠道/换模型） | provider 回退链 / 模型降档链 | ✅ |
| L3 | 质量降级（降分辨率/时长） | 资源类失败 → 480p 重试一次 | ✅ 新增真实行为 |
| L4 | 功能降级（砍可选环节） | 暂无可砍环节，预留 | 🔲 预留 |
| L5 | 部分交付 | 返回段数 < 请求段数 | ✅ 检出 |
| L6 | 失败兜底 | 本地占位生成（FFmpeg 色块） | ✅ |

设计纪律：
- **纯模块**（不 import app 包），可独立加载/单测；
- 降级是**可观测状态**不是静默兜底：每次 generate 产生一个 DegradationSession，
  终态进 24h 滚动统计——Agent/用户能回答「最近降级到哪一级、哪级最频繁」；
- classify_error 决定 L3 是否值得重试：只有**资源类**失败（超时/OOM/429/限流）
  降分辨率才可能救回来；认证/模型类失败降质无意义，直接走兜底；
- 统计失败绝不抛出（与 llm_fallback_stats 同一条纪律）。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 级别定义（id, 名称, 人话描述）
# ═══════════════════════════════════════════════════════════

LEVELS: Dict[int, Dict[str, str]] = {
    0: {"name": "full", "label": "完整交付（首选渠道按原规格出齐）"},
    1: {"name": "dual_down", "label": "双路降级（D→单路）【预留：无双路模式】"},
    2: {"name": "cloud_down", "label": "云端降级（换渠道/换模型）"},
    3: {"name": "quality_down", "label": "质量降级（降分辨率/时长重试）"},
    4: {"name": "feature_down", "label": "功能降级（砍可选环节）【预留】"},
    5: {"name": "partial", "label": "部分交付（段数未凑齐）"},
    6: {"name": "local_fallback", "label": "失败兜底（本地占位生成）"},
}

# 终态优先级：一次生成可能触发多级（如换渠道后又部分交付），取**最高级**（最严重）
_FINAL_ORDER = (6, 5, 4, 3, 2, 1, 0)


# ═══════════════════════════════════════════════════════════
# 失败分类（决定 L3 是否值得重试）
# ═══════════════════════════════════════════════════════════

_RESOURCE_PATTERNS = ("timeout", "超时", "oom", "out of memory", "显存",
                      "429", "throttl", "限流", "rate limit", "quota",
                      "connection", "连接", "网络", "502", "503", "504")
_AUTH_PATTERNS = ("401", "403", "unauthorized", "access denied", "accessdenied",
                  "invalidapikey", "无权限", "未开通", "forbidden")
_MODEL_PATTERNS = ("model not found", "not exist", "不存在",
                   "invalid model", "unsupported model")


def classify_error(error: str) -> str:
    """把错误文本分类：resource / auth / model / unknown。

    resource（超时/OOM/429/限流/网络）→ L3 降质重试可能救回来；
    auth / model → 降质无意义，直接走兜底链。
    """
    low = (error or "").lower()
    if any(p in low for p in _RESOURCE_PATTERNS):
        return "resource"
    if any(p in low for p in _AUTH_PATTERNS):
        return "auth"
    if any(p in low for p in _MODEL_PATTERNS):
        return "model"
    return "unknown"


# ═══════════════════════════════════════════════════════════
# 会话（一次 generate 的降级轨迹）
# ═══════════════════════════════════════════════════════════

class DegradationSession:
    """一次生成的降级轨迹：mark 各级事件，final_level 取最严重一级。"""

    def __init__(self) -> None:
        self.events: List[Tuple[int, str]] = []

    def mark(self, level: int, reason: str = "") -> None:
        if level not in LEVELS:
            return
        self.events.append((level, reason))
        logger.info("[degradation] L%d %s：%s", level,
                    LEVELS[level]["name"], reason[:120])

    @property
    def final_level(self) -> int:
        if not self.events:
            return 0
        marked = {lv for lv, _ in self.events}
        for lv in _FINAL_ORDER:
            if lv in marked:
                return lv
        return 0

    def summary(self) -> Dict[str, Any]:
        lv = self.final_level
        return {
            "level": lv,
            "level_name": LEVELS[lv]["name"],
            "level_label": LEVELS[lv]["label"],
            "events": [{"level": l, "reason": r} for l, r in self.events],
        }


# ═══════════════════════════════════════════════════════════
# 全局统计（24h 滚动窗口，与 llm_fallback_stats 同款）
# ═══════════════════════════════════════════════════════════

_WINDOW_S = 24 * 3600
_MAX_ENTRIES = 5000


class DegradationStats:
    """降级终态统计：各级计数 + 最近窗口明细。异常不抛。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: Deque[Tuple[float, int]] = deque()

    def record(self, level: int) -> None:
        try:
            with self._lock:
                self._entries.append((time.time(), int(level)))
                while len(self._entries) > _MAX_ENTRIES:
                    self._entries.popleft()
                self._prune_locked()
        except Exception:
            logger.debug("[degradation] 统计记录失败（不阻断）", exc_info=True)

    def _prune_locked(self) -> None:
        cutoff = time.time() - _WINDOW_S
        while self._entries and self._entries[0][0] < cutoff:
            self._entries.popleft()

    def summary(self) -> Dict[str, Any]:
        try:
            with self._lock:
                self._prune_locked()
                counts: Dict[str, int] = {}
                for _, lv in self._entries:
                    name = LEVELS.get(lv, {}).get("name", f"L{lv}")
                    counts[name] = counts.get(name, 0) + 1
                total = len(self._entries)
                degraded = total - counts.get("full", 0)
                worst = 0
                for _, lv in self._entries:
                    for cand in _FINAL_ORDER:
                        if cand == lv:
                            worst = max(worst, lv)
                            break
                return {
                    "generations_24h": total,
                    "degraded_24h": degraded,
                    "degradation_rate": round(degraded / total, 4) if total else 0.0,
                    "by_level": counts,
                    "worst_level_24h": worst,
                    "worst_label": LEVELS.get(worst, {}).get("label", ""),
                }
        except Exception:
            logger.debug("[degradation] 统计汇总失败", exc_info=True)
            return {"generations_24h": 0, "degraded_24h": 0,
                    "degradation_rate": 0.0, "by_level": {},
                    "worst_level_24h": 0, "worst_label": ""}

    def _reset_for_tests(self) -> None:
        with self._lock:
            self._entries.clear()


_STATS: Optional[DegradationStats] = None
_STATS_LOCK = threading.Lock()


def get_stats() -> DegradationStats:
    global _STATS
    if _STATS is None:
        with _STATS_LOCK:
            if _STATS is None:
                _STATS = DegradationStats()
    return _STATS
