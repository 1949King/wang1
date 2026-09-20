# -*- coding: utf-8 -*-
"""模型网关计量 · 持久化 + 聚合统计（SQLite 落盘，重启不丢）。

单次模型调用写入 usage_log，查询接口做「总览 / 按 provider / 趋势 / 缓存命中 /
异常指标」聚合。AIEngine 每次调用后调用 record() 落盘；模型管理「网关统计」tab
调查询接口渲染仪表盘。

设计约定：
- 纯持久化 + 聚合查询，不反向依赖 ai_engine（避免循环 import）。
- 线程安全：单例 + threading.Lock 串行化写；WAL 模式提升读写并发。
- 熔断状态在 AIEngine 内存里维护，本层不重复实现；本层只算「错误率 / P95 / 突增」。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.gateway_stats")

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "gateway_stats.db"

# token 突增告警阈值：今日 token 超过近 7 天日均的 N 倍则标记
_SPIKE_RATIO = 3.0


class GatewayStatsStore:
    """模型网关计量存储（单例）。"""

    _instance: Optional["GatewayStatsStore"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._write_lock = threading.Lock()
        try:
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()
        except Exception as e:  # pragma: no cover - 存储不可用不阻塞主流程
            logger.warning("gateway_stats 初始化失败（统计将不落盘）: %s", e)

    # ── 基础设施 ──────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_schema(self) -> None:
        with self._write_lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS usage_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        provider TEXT NOT NULL,
                        model TEXT DEFAULT '',
                        prompt_tokens INTEGER DEFAULT 0,
                        completion_tokens INTEGER DEFAULT 0,
                        duration_ms REAL DEFAULT 0,
                        success INTEGER DEFAULT 1,
                        error TEXT DEFAULT '',
                        cost REAL DEFAULT 0,
                        cached INTEGER DEFAULT 0
                    );
                    CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_log(ts);
                    CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage_log(provider);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    # ── 写入 ──────────────────────────────────────────────────────
    def record(
        self,
        provider: str,
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: float = 0.0,
        success: bool = True,
        error: str = "",
        cost: float = 0.0,
        cached: bool = False,
    ) -> None:
        """追加一次调用记录。失败仅告警，不抛出（计量不能拖垮主链路）。"""
        try:
            with self._write_lock:
                conn = self._connect()
                try:
                    conn.execute(
                        "INSERT INTO usage_log(ts, provider, model, prompt_tokens,"
                        " completion_tokens, duration_ms, success, error, cost, cached)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            time.time(), provider, model or "",
                            int(prompt_tokens), int(completion_tokens),
                            float(duration_ms), 1 if success else 0,
                            error or "", float(cost), 1 if cached else 0,
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:  # pragma: no cover
            logger.warning("gateway_stats record failed: %s", e)

    # ── 查询 ──────────────────────────────────────────────────────
    def _query(self, sql: str, params: tuple = ()) -> List[tuple]:
        conn = self._connect()
        try:
            cur = conn.execute(sql, params)
            return cur.fetchall()
        finally:
            conn.close()

    def total_summary(self, days: Optional[int] = None) -> Dict[str, Any]:
        """总览：总调用 / 成功 / 失败 / token / 成本 / 耗时 / 缓存命中。"""
        where = ""
        params: tuple = ()
        if days:
            where = "WHERE ts >= ?"
            params = (time.time() - days * 86400,)
        rows = self._query(
            f"SELECT COUNT(*), SUM(success), "
            f"SUM(prompt_tokens), SUM(completion_tokens), "
            f"SUM(cost), SUM(duration_ms), SUM(cached) "
            f"FROM usage_log {where}",
            params,
        )
        r = rows[0] if rows else (0, 0, 0, 0, 0, 0, 0)
        total = int(r[0] or 0)
        success = int(r[1] or 0)
        prompt_tokens = int(r[2] or 0)
        completion_tokens = int(r[3] or 0)
        cached = int(r[6] or 0)
        return {
            "total_calls": total,
            "success_calls": success,
            "failed_calls": total - success,
            "success_rate": round(success / max(total, 1) * 100, 1),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "total_cost": round(float(r[4] or 0), 4),
            "avg_duration_ms": round(float(r[5] or 0) / max(total, 1), 1),
            "cache_hits": cached,
            "cache_hit_rate": round(cached / max(total, 1) * 100, 1),
        }

    def by_provider(self, days: Optional[int] = None) -> List[Dict[str, Any]]:
        """按 provider 聚合（可限定时间窗），按成本降序。"""
        where = ""
        params: tuple = ()
        if days:
            where = "WHERE ts >= ?"
            params = (time.time() - days * 86400,)
        rows = self._query(
            f"SELECT provider, COUNT(*), SUM(success), "
            f"SUM(prompt_tokens + completion_tokens), SUM(cost), "
            f"SUM(duration_ms), SUM(cached) "
            f"FROM usage_log {where} GROUP BY provider",
            params,
        )
        out: List[Dict[str, Any]] = []
        for r in rows:
            total = int(r[1] or 0)
            success = int(r[2] or 0)
            out.append({
                "provider": r[0],
                "total_calls": total,
                "success_rate": round(success / max(total, 1) * 100, 1),
                "total_tokens": int(r[3] or 0),
                "total_cost": round(float(r[4] or 0), 4),
                "avg_duration_ms": round(float(r[5] or 0) / max(total, 1), 1),
                "cache_hits": int(r[6] or 0),
            })
        out.sort(key=lambda x: x["total_cost"], reverse=True)
        return out

    def trend(self, days: int = 14) -> List[Dict[str, Any]]:
        """按天聚合趋势（最近 N 天，含无调用空窗补零）。"""
        since = time.time() - days * 86400
        rows = self._query(
            "SELECT date(ts,'unixepoch','localtime') AS d, COUNT(*), "
            "SUM(prompt_tokens + completion_tokens), SUM(cost) "
            "FROM usage_log WHERE ts >= ? GROUP BY d ORDER BY d",
            (since,),
        )
        by_day = {r[0]: {
            "calls": int(r[1] or 0),
            "tokens": int(r[2] or 0),
            "cost": round(float(r[3] or 0), 4),
        } for r in rows}
        today = datetime.now()
        out: List[Dict[str, Any]] = []
        for i in range(days - 1, -1, -1):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            item = by_day.get(d, {"calls": 0, "tokens": 0, "cost": 0.0})
            out.append({"date": d[5:], **item})
        return out

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """最近 N 次调用明细。"""
        rows = self._query(
            "SELECT provider, model, prompt_tokens, completion_tokens, "
            "duration_ms, success, error, cost, cached, ts "
            "FROM usage_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [{
            "provider": r[0],
            "model": r[1],
            "prompt_tokens": int(r[2] or 0),
            "completion_tokens": int(r[3] or 0),
            "duration_ms": round(float(r[4] or 0), 1),
            "success": bool(r[5]),
            "error": (r[6] or "")[:60],
            "cost": round(float(r[7] or 0), 4),
            "cached": bool(r[8]),
            "ts": r[9],
        } for r in rows]

    def health(self) -> Dict[str, Any]:
        """异常检测：近 24h 失败率 / P95 耗时 / token 突增 / 熔断候选。"""
        since = time.time() - 86400
        rows = self._query(
            "SELECT success, duration_ms, provider, "
            "prompt_tokens + completion_tokens FROM usage_log WHERE ts >= ?",
            (since,),
        )
        total = len(rows)
        failed = sum(1 for r in rows if not r[0])
        durations = sorted(r[1] for r in rows if r[1] is not None)
        p95 = durations[int(len(durations) * 0.95)] if durations else 0.0

        # 今日 token vs 近 7 天日均（突增检测）
        today_start = time.mktime(datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0).timetuple())
        today_tokens = self._query(
            "SELECT SUM(prompt_tokens + completion_tokens) FROM usage_log WHERE ts >= ?",
            (today_start,),
        )[0][0] or 0
        week_avg = self._query(
            "SELECT SUM(prompt_tokens + completion_tokens)/7.0 FROM usage_log "
            "WHERE ts >= ? AND ts < ?",
            (today_start - 7 * 86400, today_start),
        )[0][0] or 0
        spike = bool(week_avg > 0 and today_tokens / week_avg >= _SPIKE_RATIO)

        return {
            "last_24h_calls": total,
            "fail_rate_24h": round(failed / max(total, 1) * 100, 1),
            "p95_duration_ms": round(p95, 1),
            "today_tokens": int(today_tokens),
            "week_daily_avg_tokens": int(week_avg),
            "token_spike": spike,
        }


gateway_stats = GatewayStatsStore()
