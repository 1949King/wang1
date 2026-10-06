# -*- coding: utf-8 -*-
"""editor_agent_dock_mixin.py
============================
EditorAgentDockMixin：剪辑 Agent 的**右侧独立竖栏**（LibTV 规格）容器与显隐控制。

背景（V4.40.50）：
    Agent 原先是右侧工具栏 `QTabWidget` 的第 9 个 Tab，被限制在 `top_splitter`
    上半区 → 可用高度只有 ≈390px（对话区憋屈），还要和「属性/调色/角色/AI/导出」
    抢位置，翻找成本高。
    现改为**最右侧独立一列**，从工具栏下方贯穿到窗口底部，宽 360（展开 560），
    与画布 Agent 面板（`AgentPanel.tsx`）统一为同一「LibTV 档」。

为什么单独文件：
    `editor_module.py` 已 9,734 行，size ratchet 上限 9,747（余量仅 13 行）
    ⇒ 新逻辑一律落新文件，`editor_module.py` 只留一行接入。

规格（唯一真源：宽档常量仍定义在 `editor_agent_panel_mixin.py`）：
    默认档 360 / 展开档 560 · 位置=最右一列 · 高度=贯穿
    默认**收起**（用户 2026-10-07 选定）· 入口=工具栏「🤖 剪辑 Agent」/ Ctrl+Shift+A
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

logger = logging.getLogger("AI短剧编辑器.editor")


class EditorAgentDockMixin:
    """剪辑 Agent 的右侧停靠列：构建 / 懒挂载 / 显隐。

    只负责「容器」，面板本体仍由 `EditorAgentPanelMixin._create_edit_agent_panel`
    构建（避免重复实现，也避免动到那 347 行）。
    """

    def _build_agent_dock(self, main_splitter: QWidget) -> QSplitter:
        """把（top / timeline）主体与 Agent 竖栏并排，返回新的根 splitter。

        布局形如：
            root(H) = [ main_splitter(V): [top(H): 左|预览|工具栏 , 时间线] , agentDock ]
        """
        root = QSplitter(Qt.Orientation.Horizontal)
        root.setStyleSheet("QSplitter::handle { background-color: #1a1a1a; width: 4px; }")
        # 主体区（top+时间线）的 minimumWidth 会被子控件（时间线等）顶得很大（实测 >12000），
        # 若不显式压住，展开 Agent 时它会吃掉全部空间，把竖栏挤成最小宽 300。
        main_splitter.setMinimumWidth(400)
        root.setCollapsible(0, False)
        root.setCollapsible(1, False)
        root.addWidget(main_splitter)

        dock = QWidget()
        dock.setObjectName("agentDock")
        dock.setMinimumWidth(300)
        lo = QVBoxLayout(dock)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)
        self._agent_dock = dock
        self._agent_dock_layout = lo

        root.addWidget(dock)
        self._agent_dock_splitter = root

        # 默认收起：空间留给预览/时间线（用户 2026-10-07 选定）
        dock.hide()

        total = self.width() or 1440
        root.setSizes([max(400, total - 360), 360])
        # 拖拽结束 → 记住宽度偏好（V4.34.1 空间策略）
        root.splitterMoved.connect(lambda *_: self._persist_agent_panel_width())
        return root

    def _ensure_agent_dock_built(self) -> bool:
        """懒构建 Agent 面板本体：首次展开时才建，不拖慢首屏。"""
        if getattr(self, "_edit_agent_panel", None) is not None:
            return True
        dock = getattr(self, "_agent_dock", None)
        lo = getattr(self, "_agent_dock_layout", None)
        if dock is None or lo is None:
            return False
        try:
            panel = self._create_edit_agent_panel()
        except Exception:
            logger.exception("构建剪辑 Agent 面板失败")
            return False
        lo.addWidget(panel)
        self._edit_agent_panel = panel
        return True

    def _show_agent_dock(self) -> None:
        """展开右侧 Agent 竖栏（并恢复上次宽度偏好）。"""
        dock = getattr(self, "_agent_dock", None)
        if dock is None or not self._ensure_agent_dock_built():
            return
        dock.show()
        self._restore_agent_panel_width()
        btn = getattr(self, "_edit_agent_toggle_btn", None)
        if btn is not None:
            btn.setChecked(True)
            btn.setText("🤖 Agent")

    def _hide_agent_dock(self) -> None:
        """收起 Agent 竖栏，空间还给预览/时间线。"""
        dock = getattr(self, "_agent_dock", None)
        if dock is None:
            return
        dock.hide()
        btn = getattr(self, "_edit_agent_toggle_btn", None)
        if btn is not None:
            btn.setChecked(False)
            btn.setText("🤖 剪辑 Agent")

    def _is_agent_dock_visible(self) -> bool:
        dock = getattr(self, "_agent_dock", None)
        return dock is not None and bool(dock.isVisible())

    # ── ⛶ 对话优先模式（V4.40.52）──────────────────────────────────────
    # 用户反馈「对话框还是有点小」⇒ 一键把对话区放大到 ≈85% 高度。
    # 做法：隐藏「上下文折叠钮/折叠体、5 张状态卡、Plan 卡、快捷指令、全链路行」，
    # 只留 head + 对话区 + 输入行。进入时**记录各控件原可见性**，退出时按记录恢复
    # （script/plan 等卡本来就隐藏，不能粗暴 setVisible(True) 全量还原）。
    def _toggle_agent_focus_mode(self, checked: bool = False) -> None:
        self._set_agent_focus_mode(bool(checked))

    def _set_agent_focus_mode(self, on: bool) -> None:
        hidable = [
            getattr(self, "_agent_ctx_toggle", None),
            getattr(self, "_agent_ctx_body", None),
            getattr(self, "_agent_plan_card", None),
            getattr(self, "_agent_quick_toggle", None),
            getattr(self, "_agent_quick_body", None),
            getattr(self, "_agent_pipeline_row_w", None),
        ]
        # 5 张状态卡 = 卡片滚动区前 5 项（构建顺序固定：config/progress/preview/score/script）
        sl = getattr(self, "_agent_scroll_layout", None)
        if sl is not None:
            for i in range(min(5, sl.count())):
                item = sl.itemAt(i)
                if item is not None and item.widget() is not None:
                    hidable.append(item.widget())
        saved = getattr(self, "_agent_focus_saved", None) or {}
        if on and not saved:
            saved = {id(w): w.isVisible() for w in hidable if w is not None}
            self._agent_focus_saved = saved
        for w in hidable:
            if w is None:
                continue
            w.setVisible(False if on else bool(saved.get(id(w), True)))
        if not on:
            self._agent_focus_saved = {}

    # ======================================================================
    # 抽取自 editor_module.py L11078-11191
    # ======================================================================
    def _build_agent_config_card(self, parent_layout: QVBoxLayout):
        """构造参数配置卡（平台 / 目标时长 / 单段时长 / Provider 选择）。"""
        card = QFrame()
        card.setObjectName("agentConfigCard")
        S = self._agent_panel_styles()
        card.setStyleSheet(S["card"])
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        t = QLabel("全链路执行参数")
        t.setStyleSheet(S["title"])
        head.addWidget(t)
        head.addStretch()
        toggle = QPushButton("展开")
        toggle.setFixedHeight(24)
        toggle.setStyleSheet(S["btn"])
        head.addWidget(toggle)
        lay.addLayout(head)

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)
        # 默认收起（V4.34.1）：这是唯一常驻展开的卡片，收起后给对话区让出空间
        body.setVisible(False)

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        # Row 1：平台 + 目标时长
        lbl1 = QLabel("平台")
        self._agent_platform_combo = QComboBox()
        self._agent_platform_combo.addItem("抖音", "douyin")
        self._agent_platform_combo.addItem("快手", "kuaishou")
        self._agent_platform_combo.addItem("B站", "bilibili")
        self._agent_platform_combo.addItem("小红书", "xiaohongshu")
        self._agent_platform_combo.setCurrentIndex(0)
        grid.addWidget(lbl1, 0, 0)
        grid.addWidget(self._agent_platform_combo, 0, 1)

        lbl2 = QLabel("目标时长")
        self._agent_duration_combo = QComboBox()
        self._agent_duration_combo.addItem("15秒", 15.0)
        self._agent_duration_combo.addItem("30秒", 30.0)
        self._agent_duration_combo.addItem("60秒", 60.0)
        self._agent_duration_combo.addItem("90秒", 90.0)
        self._agent_duration_combo.setCurrentIndex(1)  # 默认30秒
        grid.addWidget(lbl2, 0, 2)
        grid.addWidget(self._agent_duration_combo, 0, 3)

        # Row 2：单段时长 + Provider
        lbl3 = QLabel("单段时长")
        self._agent_clip_duration_spin = QDoubleSpinBox()
        self._agent_clip_duration_spin.setRange(0.5, 10.0)
        self._agent_clip_duration_spin.setSingleStep(0.5)
        self._agent_clip_duration_spin.setValue(5.0)
        self._agent_clip_duration_spin.setSuffix(" 秒")
        grid.addWidget(lbl3, 1, 0)
        grid.addWidget(self._agent_clip_duration_spin, 1, 1)

        lbl4 = QLabel("Provider")
        self._agent_provider_combo = QComboBox()
        self._agent_provider_combo.addItem("Auto（自动）", "auto")
        self._agent_provider_combo.addItem("Seedance", "seedance")
        self._agent_provider_combo.addItem("CogVideo", "cogvideo")
        self._agent_provider_combo.addItem("本地占位", "local")
        self._agent_provider_combo.setCurrentIndex(0)
        grid.addWidget(lbl4, 1, 2)
        grid.addWidget(self._agent_provider_combo, 1, 3)
        body_lay.addLayout(grid)

        # Provider 状态警告
        self._agent_provider_status_lbl = QLabel("")
        self._agent_provider_status_lbl.setStyleSheet(S["ok_hint"])
        self._agent_provider_status_lbl.setWordWrap(True)
        body_lay.addWidget(self._agent_provider_status_lbl)
        self._agent_provider_combo.currentIndexChanged.connect(self._refresh_provider_status)
        lay.addWidget(body)

        def _toggle_config():
            visible = body.isVisible()
            body.setVisible(not visible)
            toggle.setText("展开" if visible else "收起")

        toggle.clicked.connect(_toggle_config)

        parent_layout.addWidget(card)

        # 首次加载时刷新 provider 状态
        QTimer.singleShot(300, self._refresh_provider_status)
