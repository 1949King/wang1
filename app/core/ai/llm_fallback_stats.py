"""LLM 降级统计（A4 · 降级率指标化）。

背景：LLM 优先 + 关键词降级（如剧情理解的 8 维情绪向量）在 LLM 不可用时
静默降级为关键词匹配——功能没断，但**质量在暗处打折**，且没有任何指标
能回答「最近降级了多少次」。本模块把这层暗处变成数字：

- record(site, degraded, reason)：埋点登记一次尝试（降级与否）
- summary()：按站点输出近 24h 尝试数 / 降级数 / 降级率 / 最近原因

设计纪律：
- 纯内存滚动窗口（deque + 锁），不落盘——这是「近期健康指示器」，
  不是审计日志（审计走 gateway_stats 的 SQLite）。
- 不 import 任何 app 包成员，可独立加载/单测。
- 记录失败绝不抛出（指标不能拖垮主链路）。
"""

import threading
import time
from collections import deque
from typing import Any, Dict

_LOCK = threading.Lock()
_SITES: Dict[str, Dict[str, Any]] = {}

_WINDOW_SECONDS = 86400.0   # 滚动窗口：24h
_MAX_EVENTS_PER_SITE = 5000  # 防御性上限（正常远达不到）


def record(site: str, degraded: bool, reason: str = "") -> None:
    """登记一次 LLM 尝试（degraded=True 表示本次走了降级路径）。"""
    try:
        ts = time.time()
        with _LOCK:
            st = _SITES.setdefault(site, {"events": deque()})
            ev = st["events"]
            ev.append((ts, degraded, reason or ""))
            while ev and (ts - ev[0][0] > _WINDOW_SECONDS
                          or len(ev) > _MAX_EVENTS_PER_SITE):
                ev.popleft()
    except Exception:  # pragma: no cover - 指标失败不拖垮主链路
        pass


def summary() -> Dict[str, Dict[str, Any]]:
    """按站点汇总近 24h 降级情况（供 Agent / UI 查询）。"""
    with _LOCK:
        now = time.time()
        out: Dict[str, Dict[str, Any]] = {}
        for site, st in _SITES.items():
            ev = [e for e in st["events"] if now - e[0] <= _WINDOW_SECONDS]
            total = len(ev)
            degraded = sum(1 for e in ev if e[1])
            last = ev[-1] if ev else None
            out[site] = {
                "attempts_24h": total,
                "degraded_24h": degraded,
                "degradation_rate": round(degraded / max(total, 1) * 100, 1),
                "last_reason": (last[2] if last else ""),
                "last_ts": round(last[0], 3) if last else 0.0,
            }
        return out


def _reset_for_tests() -> None:
    """测试专用：清空全部站点统计。"""
    with _LOCK:
        _SITES.clear()
