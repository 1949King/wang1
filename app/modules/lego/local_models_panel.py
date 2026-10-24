# -*- coding: utf-8 -*-
"""「本地模型」页（2026-10-25）。

为什么加这一页
==============
模型管理原有两个页签：🤖 模型广场（云端 provider + Ollama 对话服务）、📊 网关统计。
**本地扩散引擎（SD1.5/SDXL 生图，SVD/Wan 生视频）没有任何入口** —— 权重明明在盘上，
用户在 UI 里看不到、也不知道能不能用。本页补上这个缺口。

口径
====
· 数据只来自注册表 + 落盘校验（neural.local_models_view），不虚构条目；
· 「已下载」与「已验证」分列：权重在盘 ≠ 真机跑过（三态 verified/unverified/blocked）；
· 刷新按钮实时重查（下载完模型不用重启软件）；
· 「打开模型目录」直达 app/models/cache。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.core.neural import local_models_view as LV

logger = logging.getLogger("AI短剧编辑器.local_models_panel")

CAP_LABEL = {"image": "🖼 生图", "video": "🎬 视频"}
VER_LABEL = {"verified": "✅ 已验证", "unverified": "⚠️ 未验证",
             "blocked": "⛔ 环境不满足", "": "— 未登记"}
_COLS = ("类型", "模型", "族", "验证态", "权重", "体积 GB", "显存 GB")


def _fmt(v: Any, unit: str = "") -> str:
    if v in (None, "", 0, 0.0):
        return "—"
    return f"{v}{unit}"


class LocalModelsPanel(QWidget):
    """本地模型清单（生图 / 生视频），带刷新与打开目录。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("🗂 本地模型")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        head.addWidget(title)
        self._summary = QLabel("")
        self._summary.setStyleSheet("color: #8b9bb0;")
        head.addWidget(self._summary)
        head.addStretch(1)
        btn_dir = QPushButton("打开模型目录")
        btn_dir.clicked.connect(self._open_dir)
        head.addWidget(btn_dir)
        btn_ref = QPushButton("刷新")
        btn_ref.clicked.connect(self.refresh)
        head.addWidget(btn_ref)
        lay.addLayout(head)

        hint = QLabel(
            "本地扩散引擎（生图/生视频）。与「模型广场」里的 Ollama 对话服务不是一回事；"
            "「已下载」只代表权重在盘，「已验证」才代表本机真机跑过。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b9bb0; font-size: 12px;")
        lay.addWidget(hint)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(list(_COLS))
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self._table, 1)

        self.refresh()

    # ── 数据 ───────────────────────────────────────
    def refresh(self) -> None:
        try:
            rows = LV.list_local_models()
        except Exception:
            logger.debug("[LocalModelsPanel] 本地模型清单失败", exc_info=True)
            rows = []
        self._rows = rows
        s = LV.summary(rows)
        self._summary.setText(
            "共 %d 项 · 已下载 %d · 已验证 %d（生图 %d / 视频 %d）"
            % (s["total"], s["downloaded"], s["verified"],
               s["by_capability"].get("image", 0), s["by_capability"].get("video", 0)))
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cap = CAP_LABEL.get(str(r.get("capability")), str(r.get("capability")))
            ver = VER_LABEL.get(str(r.get("verification") or ""), "— 未登记")
            weight = "已下载" if r.get("downloaded") else "未下载"
            cells = (cap, str(r.get("label") or r.get("id")), str(r.get("family") or "—"),
                     ver, weight, _fmt(r.get("size_gb")), _fmt(r.get("vram_gb")))
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j == 4:
                    item.setForeground(QColor("#4ade80" if r.get("downloaded") else "#8b9bb0"))
                self._table.setItem(i, j, item)
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)

    # ── 动作 ───────────────────────────────────────
    def _open_dir(self) -> None:
        root = ""
        for r in self._rows:
            d = str(r.get("dir") or "")
            if d:
                root = os.path.dirname(d)
                break
        if not root:
            root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))), "app", "models", "cache")
        if os.path.isdir(root):
            QDesktopServices.openUrl(QUrl.fromLocalFile(root))
