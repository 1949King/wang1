# -*- coding: utf-8 -*-
"""模型网关统计面板 · 「模型管理」里的「网关统计」tab。

只读展示：token 消耗 / 成本 / 成功率 / 缓存命中 / 趋势 / 异常告警。
数据来源 AIEngine.get_gateway_snapshot()（持久化聚合 + 内存缓存命中 + 熔断 + 预算）。

暗色主题，与模型管理其它卡片一致；3s 自动刷新。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _fmt_tokens(n: int) -> str:
    """token 数量人性化：<1万 原样，<100万 用「万」，否则用 M。"""
    n = int(n or 0)
    if n < 10000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 10000:.1f}万"
    return f"{n / 1_000_000:.2f}M"


class GatewayStatsPanel(QWidget):
    """网关统计仪表盘。"""

    def __init__(self):
        super().__init__()
        self._build_ui()
        self._refresh()

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self.setStyleSheet("background-color: #0a0a0a;")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # 告警横幅（预算超支 / 熔断 / token 突增）
        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(
            "background:#3a1d1d;color:#ff9e9e;border:1px solid #7a2e2e;"
            "border-radius:8px;padding:10px 14px;font-size:13px;"
        )
        self._banner.setVisible(False)
        outer.addWidget(self._banner)

        # 总览卡片
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self._cards: dict[str, QLabel] = {}
        for key, label in [
            ("total_calls", "总调用"),
            ("total_tokens", "总 Token"),
            ("total_cost", "总成本 ¥"),
            ("success_rate", "成功率"),
            ("cache_hit_rate", "缓存命中率"),
        ]:
            card = QFrame()
            card.setStyleSheet(
                "background:#151515;border:1px solid #2a2a2a;border-radius:10px;"
            )
            v = QVBoxLayout(card)
            v.setContentsMargins(14, 12, 14, 12)
            v.setSpacing(4)
            title = QLabel(label)
            title.setStyleSheet("color:#888;font-size:11px;border:none;")
            val = QLabel("—")
            val.setStyleSheet("color:#fff;font-size:20px;font-weight:600;border:none;")
            v.addWidget(title)
            v.addWidget(val)
            self._cards[key] = val
            cards.addWidget(card)
        outer.addLayout(cards)

        # 按供应商明细
        outer.addWidget(self._section_label("按模型供应商"))
        self._provider_table = self._make_table(
            ["供应商", "调用", "成功率", "Token", "成本 ¥", "平均耗时", "缓存命中"]
        )
        outer.addWidget(self._provider_table)

        # 趋势
        outer.addWidget(self._section_label("近 14 天趋势"))
        self._trend_table = self._make_table(["日期", "调用", "Token", "成本 ¥"])
        outer.addWidget(self._trend_table)

        # 最近调用
        outer.addWidget(self._section_label("最近调用"))
        self._recent_table = self._make_table(
            ["时间", "供应商", "模型", "Token", "耗时", "成本", "状态"]
        )
        outer.addWidget(self._recent_table)

        # 底部工具条
        btns = QHBoxLayout()
        refresh_btn = QPushButton("🔄 立即刷新")
        refresh_btn.setStyleSheet(
            "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;"
            "padding:8px 16px;font-size:12px;}QPushButton:hover{background:#1557b0;}"
        )
        refresh_btn.clicked.connect(self._refresh)
        btns.addWidget(refresh_btn)
        btns.addStretch()
        self._updated = QLabel("")
        self._updated.setStyleSheet("color:#666;font-size:11px;")
        btns.addWidget(self._updated)
        outer.addLayout(btns)
        outer.addStretch()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(3000)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#aaa;font-size:13px;font-weight:600;")
        return lbl

    def _make_table(self, headers: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.horizontalHeader().setStretchLastSection(True)
        t.setStyleSheet(
            "QTableWidget{background:#111;color:#ddd;border:1px solid #2a2a2a;"
            "border-radius:8px;gridline-color:#222;}"
            "QHeaderView::section{background:#1a1a1a;color:#999;border:none;"
            "padding:6px;font-size:11px;}"
            "QTableWidget::item{padding:4px;}"
        )
        t.setMinimumHeight(120)
        return t

    # ── 刷新 ────────────────────────────────────────────────────────
    def _refresh(self) -> None:
        try:
            from app.core.ai_engine import AIEngine
            snap = AIEngine().get_gateway_snapshot()
        except Exception as e:  # pragma: no cover
            self._updated.setText(f"获取统计失败: {e}")
            return
        if not snap:
            self._updated.setText("暂无统计数据（尚未发起模型调用）")
            return

        s = snap.get("summary", {})
        self._cards["total_calls"].setText(str(s.get("total_calls", 0)))
        self._cards["total_tokens"].setText(_fmt_tokens(s.get("total_tokens", 0)))
        self._cards["total_cost"].setText(f"{s.get('total_cost', 0):.3f}")
        self._cards["success_rate"].setText(f"{s.get('success_rate', 0)}%")
        self._cards["cache_hit_rate"].setText(f"{s.get('cache_hit_rate', 0)}%")

        self._update_banner(snap)
        self._fill_provider_table(snap.get("by_provider", []))
        self._fill_trend_table(snap.get("trend", []))
        self._fill_recent_table(snap.get("recent", []))
        self._updated.setText(f"更新于 {datetime.now().strftime('%H:%M:%S')}")

    def _update_banner(self, snap: dict[str, Any]) -> None:
        budget = snap.get("budget", {})
        circuit = snap.get("circuit_open", [])
        health = snap.get("health", {})
        if budget.get("over_budget"):
            msg = (
                f"⚠️ 已超出预算：累计 ¥{budget.get('total_cost', 0):.3f} "
                f"≥ 上限 ¥{budget.get('budget_limit', 0)}"
            )
        elif circuit:
            msg = f"⚠️ 熔断中的供应商：{', '.join(circuit)}（连续失败自动隔离）"
        elif health.get("token_spike"):
            msg = (
                f"⚠️ 今日 Token 用量突增：{_fmt_tokens(health.get('today_tokens', 0))} "
                f"（近 7 天日均 {_fmt_tokens(health.get('week_daily_avg_tokens', 0))}）"
            )
        else:
            self._banner.setVisible(False)
            return
        self._banner.setText(msg)
        self._banner.setVisible(True)

    # ── 表格填充 ────────────────────────────────────────────────────
    def _fill_provider_table(self, rows: list[dict[str, Any]]) -> None:
        t = self._provider_table
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [
                r.get("provider", ""),
                str(r.get("total_calls", 0)),
                f"{r.get('success_rate', 0)}%",
                _fmt_tokens(r.get("total_tokens", 0)),
                f"{r.get('total_cost', 0):.3f}",
                f"{r.get('avg_duration_ms', 0):.0f}ms",
                str(r.get("cache_hits", 0)),
            ]
            for j, v in enumerate(vals):
                t.setItem(i, j, QTableWidgetItem(v))

    def _fill_trend_table(self, rows: list[dict[str, Any]]) -> None:
        t = self._trend_table
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [
                r.get("date", ""),
                str(r.get("calls", 0)),
                _fmt_tokens(r.get("tokens", 0)),
                f"{r.get('cost', 0):.3f}",
            ]
            for j, v in enumerate(vals):
                t.setItem(i, j, QTableWidgetItem(v))

    def _fill_recent_table(self, rows: list[dict[str, Any]]) -> None:
        t = self._recent_table
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            ts = r.get("ts", 0)
            try:
                time_str = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M:%S")
            except (OSError, ValueError):
                time_str = ""
            status = "命中缓存" if r.get("cached") else ("✓" if r.get("success") else "✗")
            vals = [
                time_str,
                r.get("provider", ""),
                r.get("model", ""),
                _fmt_tokens(r.get("prompt_tokens", 0) + r.get("completion_tokens", 0)),
                f"{r.get('duration_ms', 0):.0f}ms",
                f"{r.get('cost', 0):.4f}",
                status,
            ]
            for j, v in enumerate(vals):
                t.setItem(i, j, QTableWidgetItem(v))
