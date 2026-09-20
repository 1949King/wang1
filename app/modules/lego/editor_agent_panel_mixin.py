"""
editor_agent_panel_mixin.py
============================
EditorAgentPanelMixin: 从 editor_module.py 抽出的 Agent 面板 UI 与编排方法。

设计目标（遵循 .trae/rules/2.md §三 架构分层）:
- **最小侵入**: 方法体完全照搬, self 访问不变, 符合 §二.3 不破坏原有功能
- **零回归风险**: 方法签名/实现不变, 只是文件位置改变
- **单一职责**: 本 Mixin 承载 Agent 面板创建、模型刷新、消息构建、流水线编排
- **不独立实例化**: Mixin 模式, 必须混入宿主类使用

迁移的方法（共 17 个, 约 1667 行）:
1. _create_edit_agent_panel (原 L10353-10699, 347 行)
2. _refresh_edit_agent_models (原 L10825-10969, 145 行)
3. _build_agent_config_card (原 L11078-11191, 114 行)
4. _build_agent_script_card (原 L11465-11516, 52 行)
5. _render_editing_script (原 L11518-11571, 54 行)
6. _send_edit_agent_message (原 L11651-11712, 62 行)
7. _build_edit_agent_messages (原 L11793-11877, 85 行)
8. _get_agent_extensions_context (原 L11891-11959, 69 行)
9. _get_agent_timeline_context (原 L11961-12026, 66 行)
10. agent_suggest_canvas_roundtrip (原 L12073-12122, 50 行)
11. agent_suggest_cleanup (原 L12163-12214, 52 行)
12. _handle_pipeline_done (原 L12593-12659, 67 行)
13. _agent_call_extension (原 L12740-12816, 77 行)
14. _on_run_full_pipeline (原 L12819-12946, 128 行)
15. _execute_pipeline_editing (原 L12979-13042, 64 行)
16. _apply_single_clip_ffmpeg (原 L13053-13104, 52 行)
17. _apply_multi_clip_ffmpeg (原 L13106-13288, 183 行)

使用方式:
    class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin):
        ...

迁移后 EditorModule 实例通过 self 访问这些方法, MRO 解析到本 Mixin。
所有 self.xxx 属性访问由 EditorModule.__init__ 提供, 不会断裂。
"""

from typing import Dict, Any, Optional, List
import os
import json
import random
import logging
import subprocess
import threading
import time

from PyQt6.QtCore import Qt, QTimer, QUrl, QEvent
from PyQt6.QtGui import QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QProgressBar, QListWidget,
    QListWidgetItem, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QInputDialog, QTabWidget, QCheckBox, QSlider,
    QTreeWidget, QTreeWidgetItem, QMenu, QToolButton, QApplication, QSizePolicy,
    QFormLayout, QSpacerItem, QToolTip, QStackedLayout
)

logger = logging.getLogger("AI短剧编辑器.editor")


def _with_agent_history(system_prompt: str, user_prompt: str, enabled: bool) -> List[Dict[str, str]]:
    """拼装发给模型的消息：system + （完整档时）多轮历史 + 当前 user。

    轻量档不接历史，省 token；完整档才召回，让 Agent 记得上文。
    """
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if enabled:
        try:
            from app.core.agent_session import agent_sessions
            history = agent_sessions.get_history_messages("editor")
            if history:
                messages.extend(history)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Agent] 召回多轮历史失败: {e}")
    messages.append({"role": "user", "content": user_prompt})
    return messages


class EditorAgentPanelMixin:
    """编辑 Agent 面板与流水线编排 Mixin。

    本 Mixin 从 editor_module.py 抽出, 承载 Agent 面板创建、模型刷新、
    消息构建、上下文获取、流水线编排、FFmpeg 应用等方法。被 EditorModule
    继承后, 通过 self 访问 EditorModule 的所有属性和其他方法。
    """

    # ======================================================================
    # 抽取自 editor_module.py L10353-10699
    # ======================================================================
    # ── 空间策略常量（V4.34.1）────────────────────────────────────────────
    # 不预设「唯一最佳宽度」，而是提供两档随时切：
    #   默认档 380 = 与右侧工具栏同宽，剪片时**不挤压预览**
    #   展开档 620 = 从预览区借空间，对话区舒展
    # 宽度偏好用 QSettings 记忆（跨会话）。
    _AGENT_PANEL_NORMAL = 380
    _AGENT_PANEL_WIDE = 620

    def _toggle_agent_panel_width(self) -> None:
        """在「默认档 380」与「展开档 620」之间切换右栏宽度。

        **空间策略**（V4.34.1）：Agent 与剪辑的空间矛盾没有「唯一解」——
        剪片时它该窄（让位给预览/时间线），对话时它该宽。故做成**用户随时可切**，
        而不是我替你定死一个宽度。
        """
        sp = getattr(self, "_top_splitter", None)
        if sp is None:
            return
        try:
            sizes = list(sp.sizes())
            if len(sizes) < 3:
                return
            cur = sizes[-1]
            mid = (self._AGENT_PANEL_WIDE + self._AGENT_PANEL_NORMAL) // 2
            target = self._AGENT_PANEL_NORMAL if cur >= mid else self._AGENT_PANEL_WIDE
            delta = target - cur
            # 从「预览区」借/还空间（预览是最大的一栏，伸缩最无痛）
            sp.setSizes([sizes[0], max(240, sizes[1] - delta), target])
            self._persist_agent_panel_width()
            tip = "已回归默认宽度（剪辑优先）" if target == self._AGENT_PANEL_NORMAL else "已展开对话区（对话优先）"
            try:
                self._append_agent_message("系统", f"{tip} · 右栏 {target}px。")
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Agent] 切换面板宽度失败: {e}")

    def _persist_agent_panel_width(self) -> None:
        """记住右栏宽度偏好（QSettings，跨会话）。"""
        try:
            from PyQt6.QtCore import QSettings

            sp = getattr(self, "_top_splitter", None)
            if sp is None:
                return
            sizes = list(sp.sizes())
            if len(sizes) >= 3:
                QSettings("ShiguangEditor", "AgentPanel").setValue("right_width", int(sizes[-1]))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Agent] 保存宽度偏好失败: {e}")

    def _restore_agent_panel_width(self) -> None:
        """恢复上次的右栏宽度（默认 380；夹在 300~760 防记忆值把布局搞坏）。"""
        try:
            from PyQt6.QtCore import QSettings

            sp = getattr(self, "_top_splitter", None)
            if sp is None:
                return
            w = QSettings("ShiguangEditor", "AgentPanel").value("right_width", self._AGENT_PANEL_NORMAL)
            try:
                w = max(300, min(760, int(w)))
            except (TypeError, ValueError):
                w = self._AGENT_PANEL_NORMAL
            sizes = list(sp.sizes())
            if len(sizes) >= 3 and abs(sizes[-1] - w) > 8:
                delta = w - sizes[-1]
                sp.setSizes([sizes[0], max(240, sizes[1] - delta), w])
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Agent] 恢复宽度偏好失败: {e}")

    def _agent_panel_styles(self) -> Dict[str, str]:
        """剪辑 Agent 面板的**主题感知**样式集合（V4.34.0 UI 重设计 · 第一步）。

        **为什么必须这么改**：此前本面板约 30 处 `setStyleSheet` **硬编深色**
        （`#0f1117` / `#21262d` / `#c9d1d9` …），浅色主题下会变成一块「深色孤岛」，
        与周围割裂 —— 正是项目纪律「**内联样式 = 主题盲区**」的典型案例。

        现在所有颜色集中由 `ThemeManager.get_colors()` 提供，深/浅色自动适配。
        控件只需 `setStyleSheet(S["xxx"])`，不再出现任何颜色字面量。

        （根治方案是把规则并入全局 QSS；本步先用「样式工厂」消除硬编码，
        风险最小、见效最快，后续可平滑迁移到全局 QSS。）
        """
        try:
            from .theme_manager import ThemeManager

            c = ThemeManager.instance().get_colors()
        except Exception:  # 兜底：主题不可用时退回深色（保证面板仍可用）
            logger.debug("[Agent] 取主题色板失败，用深色兜底", exc_info=True)
            c = {
                "bg_main": "#070a12", "bg_secondary": "#101621", "bg_tertiary": "#172033",
                "bg_hover": "#1f2b42", "text_primary": "#edf3ff", "text_secondary": "#aab6cc",
                "text_disabled": "#667085", "text_on_accent": "#f8fbff", "border": "#253044",
                "accent": "#2f7bff", "accent_hover": "#4d8dff", "accent_soft": "#102a4d",
                "success": "#2dd4bf", "danger": "#fb7185",
            }
        g = c.get
        return {
            # 容器
            "panel": (
                f"QWidget#editAgentPanel{{background:{g('bg_main')};}}"
                f"QWidget#editAgentPanel QLabel{{color:{g('text_primary')};"
                f"background:transparent;border:none;}}"
            ),
            "title": f"color:{g('text_primary')};font-size:12px;font-weight:700;",
            "muted": f"color:{g('text_secondary')};font-size:11px;",
            "ok_hint": f"color:{g('success')};font-size:11px;",
            # 输入类
            "line_edit": (
                f"QLineEdit{{background:{g('bg_secondary')};color:{g('text_primary')};"
                f"border:1px solid {g('border')};border-radius:6px;padding:4px 8px;font-size:11px;}}"
                f"QLineEdit:focus{{border-color:{g('accent')};}}"
            ),
            "combo": (
                f"QComboBox{{background:{g('bg_secondary')};color:{g('text_primary')};"
                f"border:1px solid {g('border')};border-radius:6px;padding:3px 8px;font-size:11px;}}"
                f"QComboBox:hover{{border-color:{g('accent')};}}"
                f"QComboBox::drop-down{{border:none;width:16px;}}"
                f"QComboBox QAbstractItemView{{background:{g('bg_secondary')};color:{g('text_primary')};"
                f"border:1px solid {g('border')};outline:0;font-size:11px;padding:2px 0;}}"
                f"QComboBox QAbstractItemView::item{{padding:4px 10px;min-height:22px;"
                f"color:{g('text_primary')};}}"
                f"QComboBox QAbstractItemView::item:hover{{background:{g('bg_hover')};}}"
                f"QComboBox QAbstractItemView::item:selected{{background:{g('accent')};"
                f"color:{g('text_on_accent')};}}"
            ),
            "text_readonly": (
                f"QTextEdit{{background:{g('bg_secondary')};color:{g('text_secondary')};"
                f"border:1px solid {g('border')};border-radius:8px;padding:6px;font-size:11px;}}"
            ),
            # 按钮
            "btn": (
                f"QPushButton{{background:{g('bg_tertiary')};color:{g('text_primary')};"
                f"border:1px solid {g('border')};border-radius:6px;padding:4px 10px;font-size:11px;}}"
                f"QPushButton:hover{{background:{g('bg_hover')};}}"
            ),
            "btn_ghost": (
                f"QPushButton{{background:{g('bg_secondary')};color:{g('text_secondary')};"
                f"border:1px solid {g('border')};border-radius:8px;padding:4px 10px;font-size:11px;}}"
                f"QPushButton:hover{{color:{g('text_primary')};border-color:{g('accent')};}}"
            ),
            "btn_primary": (
                f"QPushButton{{background:{g('accent')};color:{g('text_on_accent')};"
                f"border:none;border-radius:8px;padding:8px 16px;font-size:12px;font-weight:600;}}"
                f"QPushButton:hover{{background:{g('accent_hover')};}}"
                f"QPushButton:disabled{{background:{g('bg_tertiary')};color:{g('text_disabled')};}}"
            ),
            "btn_danger": (
                f"QPushButton{{background:transparent;color:{g('danger')};"
                f"border:1px solid {g('danger')};border-radius:8px;padding:8px 16px;"
                f"font-size:12px;font-weight:600;}}"
                f"QPushButton:hover:enabled{{background:{g('danger')};color:{g('text_on_accent')};}}"
                f"QPushButton:disabled{{color:{g('text_disabled')};border-color:{g('border')};}}"
            ),
            "btn_close": (
                f"QPushButton{{background:transparent;color:{g('text_secondary')};"
                f"border:1px solid {g('border')};border-radius:6px;padding:4px 10px;font-size:11px;}}"
                f"QPushButton:hover{{color:{g('danger')};border-color:{g('danger')};}}"
            ),
            "btn_pipeline": (
                f"QPushButton{{background:{g('accent_soft')};color:{g('accent')};"
                f"border:1px solid {g('accent')};border-radius:8px;padding:6px 12px;"
                f"font-size:11px;font-weight:600;}}"
                f"QPushButton:hover{{background:{g('accent')};color:{g('text_on_accent')};}}"
            ),
            # 卡片 / 容器（含卡内控件规则 —— 用后代选择器一次覆盖，免逐个设样式）
            "card": (
                f"QFrame{{background:{g('bg_secondary')};border:1px solid {g('border')};"
                f"border-radius:10px;}}"
                f"QFrame QLabel{{color:{g('text_secondary')};font-size:11px;}}"
                f"QFrame QComboBox{{background:{g('bg_tertiary')};color:{g('text_primary')};"
                f"border:1px solid {g('border')};border-radius:6px;padding:4px 8px;font-size:11px;}}"
                f"QFrame QComboBox::drop-down{{border:none;width:16px;}}"
                f"QFrame QComboBox QAbstractItemView{{background:{g('bg_secondary')};"
                f"color:{g('text_primary')};border:1px solid {g('border')};outline:0;"
                f"font-size:11px;padding:2px 0;}}"
                f"QFrame QComboBox QAbstractItemView::item{{padding:4px 10px;min-height:22px;}}"
                f"QFrame QComboBox QAbstractItemView::item:hover{{background:{g('bg_hover')};}}"
                f"QFrame QComboBox QAbstractItemView::item:selected{{background:{g('accent')};"
                f"color:{g('text_on_accent')};}}"
                f"QFrame QDoubleSpinBox,QFrame QSpinBox{{background:{g('bg_tertiary')};"
                f"color:{g('text_primary')};border:1px solid {g('border')};"
                f"border-radius:6px;padding:4px 8px;font-size:11px;}}"
                f"QFrame QCheckBox{{color:{g('text_secondary')};font-size:11px;}}"
            ),
            "card_ok": (
                f"QFrame{{background:{g('accent_soft')};border:1px solid {g('accent')};"
                f"border-radius:8px;}}"
            ),
            "scroll": (
                f"QScrollArea{{background:transparent;border:none;}}"
                f"QScrollBar:vertical{{background:transparent;width:8px;border:none;}}"
                f"QScrollBar::handle:vertical{{background:{g('border')};border-radius:4px;"
                f"min-height:30px;}}"
                f"QScrollBar::handle:vertical:hover{{background:{g('text_disabled')};}}"
                f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
                f"QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{{background:none;}}"
            ),
            "plan_title": f"color:{g('accent')};font-size:12px;font-weight:700;",
            # 渠道状态灯（P1-2 健康检查 / P1-1 报价）：成功 / 告警 / 次要
            "status_ok": f"color:{g('success')};font-size:10px;",
            "status_warn": f"color:{g('danger')};font-size:10px;font-weight:700;",
            "status_dim": f"color:{g('text_secondary')};font-size:10px;",
            # 带底色的信息条（原「🧠 大脑状态」那种胶囊标签）
            "card_label": (
                f"QLabel{{background:{g('bg_secondary')};color:{g('text_secondary')};"
                f"border:1px solid {g('border')};border-radius:6px;"
                f"padding:6px 10px;font-size:11px;}}"
            ),
        }

    def _create_edit_agent_panel(self) -> QWidget:
        """创建剪辑 Agent 对话面板（嵌入右侧工具栏标签页）。"""
        panel = QWidget()
        panel.setObjectName("editAgentPanel")
        S = self._agent_panel_styles()          # 主题感知样式（不再硬编颜色）
        panel.setStyleSheet(S["panel"])
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # ── 头部：一行紧凑（标题 + 模式 + 弹性留白 + 模型 + 刷新 + 收起）──
        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("剪辑 Agent")
        title.setStyleSheet(S["title"])
        head.addWidget(title)

        # 模式切换：Plan / 协作 B / 自主 C
        # （去掉「模式」文字标签，靠 tooltip 说明 —— 省一列宽度，头部更紧凑）
        self._agent_mode_combo = QComboBox()
        self._agent_mode_combo.addItem("协作 B", "collaborative")
        self._agent_mode_combo.addItem("Plan", "plan")
        self._agent_mode_combo.addItem("自主 C", "autonomous")
        self._agent_mode_combo.setMinimumWidth(88)
        self._agent_mode_combo.setToolTip(
            "Plan：只规划不改时间线；协作 B：建议清单勾选后写入；自主 C：白名单自动执行（付费生成不重试）"
        )
        self._agent_mode_combo.setStyleSheet(S["combo"])
        head.addWidget(self._agent_mode_combo)
        head.addStretch()

        # 模型选择：弹性宽度（原固定 260px，窄面板会把其他按钮挤掉）
        self._edit_agent_model_combo = QComboBox()
        self._edit_agent_model_combo.setToolTip("选择本次对话使用的模型")
        self._edit_agent_model_combo.setStyleSheet(S["combo"])
        head.addWidget(self._edit_agent_model_combo, 1)

        refresh_btn = QPushButton("刷新")
        refresh_btn.setToolTip("重新加载可用模型列表")
        refresh_btn.setStyleSheet(S["btn"])
        refresh_btn.clicked.connect(self._refresh_edit_agent_models)
        head.addWidget(refresh_btn)

        self._agent_active_hint = QLabel("")
        self._agent_active_hint.setStyleSheet(S["ok_hint"])
        head.addWidget(self._agent_active_hint)

        # 展开 / 还原右栏宽度（V4.34.1 空间策略）：剪片时窄、对话时宽，随时切
        self._agent_expand_btn = QPushButton("⤢")
        self._agent_expand_btn.setToolTip(
            f"展开对话区（右栏 {self._AGENT_PANEL_NORMAL} → {self._AGENT_PANEL_WIDE}px）；再点还原"
        )
        self._agent_expand_btn.setFixedWidth(30)
        self._agent_expand_btn.setStyleSheet(S["btn"])
        self._agent_expand_btn.clicked.connect(self._toggle_agent_panel_width)
        head.addWidget(self._agent_expand_btn)

        close_btn = QPushButton("收起")
        close_btn.setStyleSheet(S["btn_close"])
        close_btn.clicked.connect(self._close_agent_tab)
        head.addWidget(close_btn)
        layout.addLayout(head)

        # 多集上下文（Dify 式应用变量，写入 MemoryStore）
        # 紧凑化：去掉「剧名」「集数」「平台」三个文字标签，语义交给 placeholder + tooltip
        proj_row = QHBoxLayout()
        proj_row.setSpacing(6)
        _pe = S["line_edit"]
        self._agent_drama_edit = QLineEdit()
        self._agent_drama_edit.setPlaceholderText("漫剧名（写入多集记忆）")
        self._agent_drama_edit.setToolTip("剧名：多集记忆的归组键")
        self._agent_drama_edit.setStyleSheet(_pe)
        proj_row.addWidget(self._agent_drama_edit, 2)
        self._agent_episode_edit = QLineEdit()
        self._agent_episode_edit.setPlaceholderText("集数 03")
        self._agent_episode_edit.setToolTip("集数：如 03")
        self._agent_episode_edit.setMaximumWidth(80)
        self._agent_episode_edit.setStyleSheet(_pe)
        proj_row.addWidget(self._agent_episode_edit)
        self._agent_platform_edit = QLineEdit()
        self._agent_platform_edit.setPlaceholderText("平台 douyin")
        self._agent_platform_edit.setToolTip("目标平台：如 douyin")
        self._agent_platform_edit.setMaximumWidth(104)
        self._agent_platform_edit.setStyleSheet(_pe)
        proj_row.addWidget(self._agent_platform_edit)
        save_ctx_btn = QPushButton("保存")
        save_ctx_btn.setToolTip("保存多集上下文")
        save_ctx_btn.setStyleSheet(S["btn"])
        save_ctx_btn.clicked.connect(self._save_agent_project_context)
        proj_row.addWidget(save_ctx_btn)
        layout.addLayout(proj_row)
        self._load_agent_project_context_fields()
        self._subscribe_provider_activated()

        # ── 大脑状态条（紧凑一行，放对话区上方）──
        self._agent_brain_status_label = QLabel("大脑初始化中…")
        self._agent_brain_status_label.setStyleSheet(S["card_label"])
        self._agent_brain_status_label.setWordWrap(True)
        layout.addWidget(self._agent_brain_status_label)
        # 启动时首次刷新 + 定时器周期刷新（每 5 秒）
        QTimer.singleShot(0, self._refresh_agent_brain_status)
        self._agent_brain_refresh_timer = QTimer(self)
        self._agent_brain_refresh_timer.setInterval(5000)
        self._agent_brain_refresh_timer.timeout.connect(self._refresh_agent_brain_status)
        self._agent_brain_refresh_timer.start()

        # ── ★ 对话区（主角，弹性占满剩余空间）──
        # 原实现把它塞进滚动区且 setFixedHeight(72) —— 面板叫「Agent」，对话区却最小，
        # 这是「对话体验非常难受」的直接原因。现移出滚动区、由面板布局直接给空间。
        self._edit_agent_chat = QTextEdit()
        self._edit_agent_chat.setReadOnly(True)
        self._edit_agent_chat.setMinimumHeight(220)
        self._edit_agent_chat.setPlaceholderText("在这里和 Agent 对话 —— 结果与状态也会显示在这里。")
        self._edit_agent_chat.setStyleSheet(S["text_readonly"])
        layout.addWidget(self._edit_agent_chat, 1)

        # ── 卡片滚动区（折叠后很矮，不抢对话区的空间）──
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(S["scroll"])
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 4, 0, 4)
        scroll_layout.setSpacing(6)

        # ── 新增 1：执行参数配置卡（P0 痛点1+8）──
        self._build_agent_config_card(scroll_layout)

        # ── 新增 2：进度卡（P0 痛点2）──
        self._build_agent_progress_card(scroll_layout)

        # ── 新增 3：预览问题卡（P1 痛点5）──
        self._build_agent_preview_card(scroll_layout)

        # ── 新增 4：打分结果卡（P1 痛点3）──
        self._build_agent_score_card(scroll_layout)

        # ── 新增 5：剪辑脚本卡（P1 痛点4+6）──
        self._build_agent_script_card(scroll_layout)

        # Plan 模式规划显示区域（默认隐藏）
        self._agent_plan_card = QFrame()
        self._agent_plan_card.setStyleSheet(S["card_ok"])
        self._agent_plan_card.setVisible(False)
        plan_layout = QVBoxLayout(self._agent_plan_card)
        plan_layout.setContentsMargins(10, 8, 10, 10)
        plan_layout.setSpacing(6)

        plan_header = QHBoxLayout()
        plan_title = QLabel("执行规划")
        plan_title.setStyleSheet(S["plan_title"])
        plan_header.addWidget(plan_title)
        plan_header.addStretch()
        plan_layout.addLayout(plan_header)

        self._agent_plan_view = QTextEdit()
        self._agent_plan_view.setReadOnly(True)
        self._agent_plan_view.setMinimumHeight(80)
        self._agent_plan_view.setMaximumHeight(160)
        self._agent_plan_view.setStyleSheet(S["text_readonly"])
        plan_layout.addWidget(self._agent_plan_view)

        plan_btn_row = QHBoxLayout()
        plan_btn_row.setSpacing(6)
        self._agent_plan_confirm_btn = QPushButton("确认执行")
        self._agent_plan_confirm_btn.setStyleSheet(S["btn_primary"])
        self._agent_plan_confirm_btn.clicked.connect(self._confirm_agent_plan)
        plan_btn_row.addWidget(self._agent_plan_confirm_btn)

        self._agent_plan_cancel_btn = QPushButton("取消")
        self._agent_plan_cancel_btn.setStyleSheet(S["btn"])
        self._agent_plan_cancel_btn.clicked.connect(self._cancel_agent_plan)
        plan_btn_row.addWidget(self._agent_plan_cancel_btn)
        plan_btn_row.addStretch()
        plan_layout.addLayout(plan_btn_row)

        scroll_layout.addWidget(self._agent_plan_card)

        interaction_card = QFrame()
        interaction_card.setStyleSheet(S["card"])
        interaction_layout = QVBoxLayout(interaction_card)
        interaction_layout.setContentsMargins(10, 10, 10, 10)
        interaction_layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        interaction_title = QLabel("输入剪辑指令")
        interaction_title.setStyleSheet(S["title"])
        title_row.addWidget(interaction_title)
        title_row.addStretch()

        # 知心秘书温度开关（默认关=轻量；开=完整，多耗 token）
        self._agent_persona_btn = QPushButton(self._persona_btn_label())
        self._agent_persona_btn.setToolTip(
            "开启「知心秘书」后我会记得你、更主动关心，但每次对话会多消耗一些 token；"
            "关闭则保持轻量、几乎不增成本。"
        )
        self._agent_persona_btn.setStyleSheet(S["btn_ghost"])
        self._agent_persona_btn.clicked.connect(self._toggle_agent_persona)
        title_row.addWidget(self._agent_persona_btn)

        # 自定义称呼
        self._agent_nickname_btn = QPushButton("称呼")
        self._agent_nickname_btn.setToolTip("设置希望我怎么称呼你")
        self._agent_nickname_btn.setStyleSheet(S["btn_ghost"])
        self._agent_nickname_btn.clicked.connect(self._set_agent_nickname)
        title_row.addWidget(self._agent_nickname_btn)

        interaction_layout.addLayout(title_row)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        quick_prompts = [
            ("分析当前片段", "分析当前选中片段，给出可执行的剪辑建议"),
            ("一键切分", "把当前片段按播放头位置切成两段"),
            ("电影滤镜", "给当前片段添加电影感滤镜，强度 70%"),
            ("淡入转场", "给当前片段添加 0.5 秒淡入转场"),
        ]
        for label, prompt in quick_prompts:
            btn = QPushButton(label)
            btn.setStyleSheet(S["btn_ghost"])
            btn.clicked.connect(lambda _, text=prompt: self._fill_edit_agent_prompt(text))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        interaction_layout.addLayout(quick_row)

        # 全链路一键执行按钮（Agent 全量双向闭环：生成→预览→打分→精剪→成片）
        pipeline_row = QHBoxLayout()
        pipeline_row.setSpacing(6)
        pipeline_btn = QPushButton("全链路执行（生成→预览→打分→精剪→成片）")
        pipeline_btn.setObjectName("edit_agent_pipeline_btn")
        pipeline_btn.setProperty("waiting_preview", False)
        pipeline_btn.setStyleSheet(S["btn_pipeline"])
        pipeline_btn.clicked.connect(self._on_run_full_pipeline)
        self._edit_agent_pipeline_btn = pipeline_btn  # 保存引用
        pipeline_row.addWidget(pipeline_btn)
        # P1-3 任务化取消按钮：仅在全链路任务运行期间可见（queued/running/cancelling）
        pipeline_cancel_btn = QPushButton("⏹ 取消")
        pipeline_cancel_btn.setObjectName("edit_agent_pipeline_cancel_btn")
        pipeline_cancel_btn.setStyleSheet(S["btn_danger"])
        pipeline_cancel_btn.setVisible(False)
        pipeline_cancel_btn.clicked.connect(self._on_cancel_pipeline_job)
        self._edit_agent_pipeline_cancel_btn = pipeline_cancel_btn
        pipeline_row.addWidget(pipeline_cancel_btn)
        self._pipeline_job_id = ""   # 当前轮询的全链路任务号（空 = 无任务）
        pipeline_row.addStretch()
        interaction_layout.addLayout(pipeline_row)

        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self._edit_agent_input = QLineEdit()
        self._edit_agent_input.setPlaceholderText("例如：把当前片段切成两段，给第一段加电影滤镜，并添加淡入转场")
        self._edit_agent_input.setStyleSheet(S["line_edit"])
        self._edit_agent_input.returnPressed.connect(self._send_edit_agent_message)
        input_row.addWidget(self._edit_agent_input, 1)

        self._edit_agent_send_btn = QPushButton("发送")
        self._edit_agent_send_btn.setStyleSheet(S["btn_primary"])
        self._edit_agent_send_btn.clicked.connect(self._send_edit_agent_message)
        input_row.addWidget(self._edit_agent_send_btn)

        # 终止：只在任务运行时显示（V4.34.1 输入区瘦身：次级动作收进「⋯」）
        self._edit_agent_stop_btn = QPushButton("终止")
        self._edit_agent_stop_btn.setEnabled(False)
        self._edit_agent_stop_btn.setVisible(False)
        self._edit_agent_stop_btn.setStyleSheet(S["btn_danger"])
        self._edit_agent_stop_btn.clicked.connect(self._stop_edit_agent_message)
        input_row.addWidget(self._edit_agent_stop_btn)

        # 暂停 / 继续 / 重规划 → 「⋯」菜单
        # （控件本身保留为不可见宿主，避免别处 setEnabled / setText 调用报错）
        self._edit_agent_pause_btn = QPushButton("暂停")
        self._edit_agent_pause_btn.clicked.connect(self._pause_edit_agent_task)
        self._edit_agent_resume_btn = QPushButton("继续")
        self._edit_agent_resume_btn.clicked.connect(self._resume_edit_agent_task)
        self._edit_agent_replan_btn = QPushButton("重规划")
        self._edit_agent_replan_btn.clicked.connect(self._replan_edit_agent_task)
        for _b in (self._edit_agent_pause_btn, self._edit_agent_resume_btn,
                   self._edit_agent_replan_btn):
            _b.setVisible(False)

        more_btn = QToolButton()
        more_btn.setText("⋯")
        more_btn.setToolTip("更多操作：暂停 / 继续 / 重规划")
        more_btn.setStyleSheet(S["btn"])
        more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(more_btn)
        more_menu.addAction("暂停任务", self._pause_edit_agent_task)
        more_menu.addAction("继续任务", self._resume_edit_agent_task)
        more_menu.addSeparator()
        more_menu.addAction("重规划（切到 Plan 重来）", self._replan_edit_agent_task)
        more_btn.setMenu(more_menu)
        input_row.addWidget(more_btn)
        interaction_layout.addLayout(input_row)
        scroll_layout.addWidget(interaction_card)

        # 设置 scrollArea 的 content 并加入主布局
        # stretch=0：卡片区不抢空间（对话区已拿到 stretch=1）；卡片折叠后只剩标题行
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 0)

        self._edit_agent_worker = None
        self._edit_agent_stream_buffer = ""
        self._edit_agent_inbox = []
        self._refresh_edit_agent_models()
        self._greet_agent_secretary()

        # 空闲关怀：完整档时，长时间无交互主动问候一句（每分钟检查一次）
        self._agent_last_active = time.time()
        self._agent_idle_timer = QTimer(self)
        self._agent_idle_timer.setInterval(60_000)
        self._agent_idle_timer.timeout.connect(self._check_agent_idle)
        self._agent_idle_timer.start()

        # 注册统一调用层 handler，传入 EditorModule lazy 引用
        try:
            from app.core.capability_dispatcher import capability_dispatcher
            from app.core.capability_handlers import register_builtin_handlers
            register_builtin_handlers(capability_dispatcher, editor_module_ref=lambda: self)
        except Exception as e:
            logger.warning(f"[Agent] 注册 CapabilityDispatcher 失败: {e}")

        # 画布 HTTP 共享同一 Agent / 拓展面
        try:
            from app.core.project_agent_host import bind_editor_module
            bind_editor_module(self)
        except Exception as e:
            logger.debug("bind project_agent_host: %s", e)

        # 监听反馈可用事件，刷新面板指示
        try:
            from app.modules.lego.core import EventType
            from app.core.agent_feedback_bridge import agent_feedback_bridge
            agent_feedback_bridge.event_bus  # 触发订阅
            self._event_bus.on(EventType.AGENT_FEEDBACK_AVAILABLE, self._on_agent_feedback)
        except Exception as e:
            logger.warning(f"[Agent] 反馈桥初始化失败: {e}")

        # 监听全链路暂停等待预览确认事件
        try:
            self._event_bus.on(EventType.CUSTOM, self._on_pipeline_event)
        except Exception as e:
            logger.warning(f"[Agent] 全链路事件监听初始化失败: {e}")

        # 恢复上次的右栏宽度偏好（延迟到布局 settle 后，避免启动时跳动）
        QTimer.singleShot(200, self._restore_agent_panel_width)

        # 快捷键直达（V4.34.1 调用体验）：Ctrl+Shift+A 切到 Agent 并聚焦输入框
        try:
            from PyQt6.QtGui import QKeySequence, QShortcut

            self._agent_shortcut = QShortcut(QKeySequence("Ctrl+Shift+A"), self)
            self._agent_shortcut.activated.connect(self._focus_agent_panel)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Agent] 快捷键注册失败: {e}")

        return panel

    def _focus_agent_panel(self) -> None:
        """快捷键 / 独立入口共用：切到 Agent 面板并把焦点交给输入框。"""
        try:
            idx = getattr(self, "_agent_tab_index", -1)
            tabs = getattr(self, "_tools_tabs", None)
            if tabs is not None and idx is not None and idx >= 0:
                tabs.setCurrentIndex(idx)      # 懒加载 Tab 会在此刻构建
            inp = getattr(self, "_edit_agent_input", None)
            if inp is not None:
                inp.setFocus()
                inp.selectAll()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Agent] 聚焦面板失败: {e}")

    # ======================================================================
    # 抽取自 editor_module.py L10825-10969
    # ======================================================================
    def _refresh_edit_agent_models(self):
        """加载可用 Provider 到 Agent 模型框；按 provider 分组 + 可读名 + 激活优先。"""
        combo = getattr(self, '_edit_agent_model_combo', None)
        if combo is None:
            return
        combo.clear()
        try:
            from app.modules.lego.model_config import (
                PROVIDERS,
                ensure_active_provider_sensible,
                load_active_provider,
                model_display_name,
            )
            ensure_active_provider_sensible()
        except Exception:
            PROVIDERS = {}
            model_display_name = lambda p, m: m or "自动"  # noqa: E731
            load_active_provider = lambda: ""  # noqa: E731

        try:
            from app.core.ai_engine import ai_engine
            available = set(ai_engine.get_available_providers() or [])
        except Exception:
            available = set()

        try:
            from app.modules.lego.cloud_api import cloud_api_service
        except Exception:
            cloud_api_service = None

        active = ""
        try:
            active = load_active_provider() or ""
        except Exception:
            active = ""

        # ── 收集所有可用条目 ──
        # 按 provider 分组：provider -> list[(model, configured)]
        groups: dict[str, list[tuple[str, bool]]] = {}
        provider_meta: dict[str, dict] = {}

        for provider, cfg in PROVIDERS.items():
            name = cfg.get("name", provider)
            icon = cfg.get("icon", "")
            is_local = bool(cfg.get("is_local"))
            configured = False
            if is_local:
                configured = provider in available
            elif cloud_api_service is not None:
                try:
                    configured = bool(cloud_api_service.is_configured(provider))
                except Exception:
                    configured = provider in available

            models = list(cfg.get("models") or [])
            if provider == "ollama":
                models = self._list_local_ollama_models() or (["auto"] if configured else [])
            if not configured and not models:
                continue
            if not models:
                models = [""]

            valid_models = []
            for model in models:
                if not is_local and not configured:
                    continue
                valid_models.append((model, configured))

            if valid_models:
                groups[provider] = valid_models
                provider_meta[provider] = {
                    "name": name,
                    "icon": icon,
                    "is_local": is_local,
                    "configured": configured,
                }

        # ── 排序：激活 provider 最前，其余按已配置优先 ──
        provider_order = sorted(
            groups.keys(),
            key=lambda p: (
                0 if p == active else 1,
                0 if provider_meta[p]["configured"] or p in available else 1,
                p,
            ),
        )

        select_idx = 0
        first_item_after_separators = 0

        for pi, provider in enumerate(provider_order):
            meta = provider_meta[provider]
            p_name = meta["name"]
            p_icon = meta["icon"]
            p_local = meta["is_local"]
            p_configured = meta["configured"] or provider in available
            is_active_p = provider == active

            # provider 分组标签（带 icon 和可用性）
            suffix = "✓" if p_configured else "✗"
            local_tag = " 🖥️" if p_local else ""
            header_text = f"{p_icon} {p_name}{local_tag}  [{suffix}]"
            if pi > 0:
                combo.insertSeparator(combo.count())
            # 不可点击的分组标题：用 QComboBox 的 setItemData 标记后在 currentIndexChanged 过滤太麻烦，
            # 简单做法：加一个带灰色样式的条目 + separator
            header_idx = combo.count()
            combo.addItem(header_text, ("__header__", provider))
            cmodel = combo.model()
            if cmodel is not None:
                hitem = cmodel.item(header_idx)
                if hitem is not None:
                    hitem.setEnabled(False)

            for model_id, _cfg in groups[provider]:
                # 用可读名
                mid = "" if model_id == "auto" else model_id
                display = model_display_name(provider, mid) if mid else "自动"
                # 完整 label：[激活星] 可读名  [原始 ID]  [可用标记]
                raw_hint = f"（{mid}）" if mid and mid != display else ""
                active_tag = "★ " if is_active_p and not mid else ""
                ok_tag = " ✓" if p_configured else ""
                label = f"  {active_tag}{display}{raw_hint}{ok_tag}"
                combo.addItem(label, (provider, mid))

                # 选第一个匹配激活项
                if is_active_p and mid == "":
                    if select_idx == 0:
                        select_idx = combo.count() - 1
                elif is_active_p and mid and provider == active:
                    if select_idx == 0:
                        select_idx = combo.count() - 1

        if combo.count() == 0:
            combo.addItem("自动降级 / 可用模型", ("", ""))
        else:
            combo.setCurrentIndex(min(select_idx, combo.count() - 1))

        hint = getattr(self, "_agent_active_hint", None)
        if hint is not None:
            try:
                name = (PROVIDERS.get(active) or {}).get("name") or active or "未激活"
                hint.setText(f"激活:{name}")
            except Exception:
                hint.setText("")

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

    # ======================================================================
    # 抽取自 editor_module.py L11465-11516
    # ======================================================================
    def _build_agent_script_card(self, parent_layout: QVBoxLayout):
        """构造剪辑脚本结果卡（HTML 渲染 + 复制/导出/一键手动精剪）。"""
        card = QFrame()
        card.setObjectName("agentScriptCard")
        S = self._agent_panel_styles()
        card.setStyleSheet(S["card"])
        card.setVisible(False)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        t = QLabel("剪辑创意脚本")
        t.setStyleSheet(S["title"])
        head.addWidget(t)
        head.addStretch()

        self._agent_copy_script_btn = QPushButton("复制")
        self._agent_copy_script_btn.setStyleSheet(S["btn"])
        self._agent_copy_script_btn.clicked.connect(self._on_copy_script_clicked)
        head.addWidget(self._agent_copy_script_btn)

        self._agent_export_script_btn = QPushButton("导出")
        self._agent_export_script_btn.setStyleSheet(S["btn"])
        self._agent_export_script_btn.clicked.connect(self._on_export_script_clicked)
        head.addWidget(self._agent_export_script_btn)
        lay.addLayout(head)

        self._agent_script_view = QTextEdit()
        self._agent_script_view.setReadOnly(True)
        self._agent_script_view.setFixedHeight(130)
        self._agent_script_view.setStyleSheet(S["text_readonly"])
        lay.addWidget(self._agent_script_view)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._agent_manual_edit_btn = QPushButton("一键手动精剪")
        self._agent_manual_edit_btn.setStyleSheet(S["btn_primary"])
        self._agent_manual_edit_btn.clicked.connect(self._on_manual_edit_clicked)
        btn_row.addWidget(self._agent_manual_edit_btn)
        lay.addLayout(btn_row)

        self._agent_script_card = card
        parent_layout.addWidget(card)
        self._last_editing_script: Optional[Dict[str, Any]] = None

    # ======================================================================
    # 抽取自 editor_module.py L11518-11571
    # ======================================================================
    def _render_editing_script(self, script: Optional[Dict[str, Any]]):
        """渲染剪辑脚本到脚本卡。"""
        view = getattr(self, "_agent_script_view", None)
        card = getattr(self, "_agent_script_card", None)
        if view is None or card is None:
            return
        if not script:
            card.setVisible(False)
            return
        self._last_editing_script = script
        platform = script.get("platform", "-")
        target_dur = script.get("target_duration", "-")
        pacing = script.get("pacing", "-")
        clip_order = script.get("clip_order", []) or []
        transitions = script.get("transitions", {}) or {}
        beat_pts = script.get("beat_points", []) or []
        bgm = script.get("bgm_style", script.get("bgm", ""))
        dropped = script.get("dropped_clips", []) or []
        rationale = script.get("rationale", "")

        # HTML 渲染同样要**主题感知**（内联 style 也是主题盲区）
        try:
            from .theme_manager import ThemeManager

            _c = ThemeManager.instance().get_colors()
        except Exception:
            _c = {}
        _tp = _c.get("text_primary") or "#edf3ff"
        _ts = _c.get("text_secondary") or "#aab6cc"
        _acc = _c.get("accent") or "#2f7bff"
        _ok = _c.get("success") or "#2dd4bf"
        _bad = _c.get("danger") or "#fb7185"

        # 镜头序列
        seq_html = []
        for i, item in enumerate(clip_order, 1):
            cid = item.get("clip_id") or item.get("id", f"#{i}")
            dur = item.get("duration", "")
            grade = item.get("grade", "")
            tr = transitions.get(cid, transitions.get(str(i-1), ""))
            # 评分色：S/A → success，B/C → accent，D → danger（不再硬编金色/橙色）
            color = {"S": _ok, "A": _ok, "B": _acc, "C": _acc, "D": _bad}.get(grade, _acc)
            grade_tag = f' <span style="color:{color};font-weight:700;">[{grade}]</span>' if grade else ""
            dur_tag = f' <span style="color:{_ts};">{dur}s</span>' if dur else ""
            tr_tag = f' <span style="color:{_acc};">→ {tr}</span>' if tr and i < len(clip_order) else ""
            seq_html.append(f'<span style="color:{_tp};">{i}. {cid}</span>{grade_tag}{dur_tag}{tr_tag}')
        seq_text = "<br>".join(seq_html) or f'<span style="color:{_ts};">(空)</span>'

        # 卡点
        beat_text = (", ".join([f"{b:.1f}s" for b in beat_pts]) if beat_pts
                     else f'<span style="color:{_ts};">(无)</span>')
        # 剔除
        dropped_text = (", ".join(dropped) if dropped
                        else f'<span style="color:{_ts};">(无)</span>')

        rationale_html = (f'<div><b style="color:{_acc};">创意说明：</b>'
                          f'<span style="color:{_ts};">{rationale}</span></div>'
                          if rationale else "")
        html = f"""
        <div style="font-family:微软雅黑;font-size:11px;line-height:1.5;color:{_tp};">
          <div><b style="color:{_acc};">平台：</b>{platform} &nbsp;
               <b style="color:{_acc};">时长：</b>{target_dur}s &nbsp;
               <b style="color:{_acc};">节奏：</b>{pacing}</div>
          {rationale_html}
          <div><b style="color:{_acc};">镜头顺序（{len(clip_order)}）：</b></div>
          <div style="padding:4px 0;">{seq_text}</div>
          <div><b style="color:{_acc};">卡点：</b><span style="color:{_ts};">{beat_text}</span></div>
          <div><b style="color:{_acc};">配乐风格：</b><span style="color:{_ts};">{bgm or '未选择'}</span></div>
          <div><b style="color:{_bad};">已剔除镜头：</b><span style="color:{_bad};">{dropped_text}</span></div>
        </div>
        """
        view.setHtml(html)
        card.setVisible(True)

    # ======================================================================
    # 抽取自 editor_module.py L11651-11712
    # ======================================================================
    def _send_edit_agent_message(self):
        """发送剪辑 Agent 指令并启动后台模型请求。"""
        if getattr(self, '_edit_agent_worker', None) and self._edit_agent_worker.isRunning():
            user_text = self._edit_agent_input.text().strip()
            if user_text:
                inbox = getattr(self, "_edit_agent_inbox", None)
                if inbox is None:
                    self._edit_agent_inbox = []
                    inbox = self._edit_agent_inbox
                inbox.append(user_text)
                self._edit_agent_input.clear()
                self._append_agent_message("系统", f"已排队（串行）：{user_text[:80]}")
            else:
                QMessageBox.information(self, "剪辑 Agent", "Agent 正在处理中，可点「暂停/终止」或等待完成后自动发送队列。")
            return
        user_text = self._edit_agent_input.text().strip()
        if not user_text:
            QMessageBox.warning(self, "剪辑 Agent", "请输入剪辑指令")
            return

        from app.core.agent_context import compress_messages
        from app.core.agent_session import agent_sessions
        from app.core.agent_task_store import agent_tasks

        ok_round, err_round = agent_sessions.begin_model_round("editor")
        if not ok_round:
            QMessageBox.warning(self, "剪辑 Agent", err_round)
            return

        provider, model = self._get_selected_edit_agent_model()
        self._persist_agent_project_context_silent()
        messages = compress_messages(self._build_edit_agent_messages(user_text),
                                     model=model, provider=provider)
        task = agent_tasks.create(
            session_id="editor",
            goal=user_text,
            mode=self._get_agent_session_mode(),
            source="editor",
        )
        self._edit_agent_task_id = task.get("id")
        try:
            agent_tasks.transition(task["id"], "running")
        except Exception:
            pass
        self._append_agent_message("你", user_text)
        using = provider or "自动降级"
        if model:
            using = f"{using}/{model}"
        self._append_agent_message("Agent", f"正在用 {using} 分析并生成剪辑指令...")
        self._edit_agent_input.clear()

        self._edit_agent_stream_buffer = ""
        self._edit_agent_last_user_text = user_text
        # 局部 import 避免循环导入（editor_module 反向 import 本 Mixin）
        from .editor_module import EditingAgentWorker
        worker = EditingAgentWorker(provider, model, messages, self)
        worker.chunk_ready.connect(self._on_edit_agent_chunk)
        worker.result_ready.connect(lambda raw, text=user_text: self._on_edit_agent_result(text, raw))
        worker.error_ready.connect(self._on_edit_agent_error)
        worker.stopped_ready.connect(self._on_edit_agent_stopped)
        worker.finished.connect(self._on_edit_agent_finished)
        self._edit_agent_worker = worker
        self._edit_agent_send_btn.setEnabled(False)
        self._edit_agent_stop_btn.setEnabled(True)
        # 终止按钮按需显示（V4.34.1 输入区瘦身：空闲时不占位）
        self._edit_agent_stop_btn.setVisible(True)
        worker.start()

    def _record_agent_turn(self, user_text: str, assistant_text: str = ""):
        """完整档：把一轮对话写入多轮历史，供下次构建 prompt 时召回。

        轻量档直接跳过（不接历史，省 token）。放在结果回调里调用，
        保证历史只在「一轮完整结束」后追加，避免与当前 user 重复。
        """
        # 记忆深挖：从用户话里提炼偏好（本地规则、零 token、始终进行）
        self._mine_preference_from_chat(user_text)
        try:
            from app.core.agent_persona import is_persona_enabled
            if not is_persona_enabled():
                return
            from app.core.agent_session import agent_sessions
            agent_sessions.push_history("editor", user_msg=user_text, assistant_msg=assistant_text or "")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Agent] 记录对话历史失败: {e}")

    # ────────────────────────────────────────────────────────────────────
    # 知心秘书：问候 / 温度开关 / 称呼 / 空闲关怀
    # ────────────────────────────────────────────────────────────────────
    _IDLE_REMINDER_MINUTES = 30

    # 偏好信号词：命中即认为用户在表达习惯/喜好，原句归档到长期记忆
    _PREFERENCE_MARKERS = (
        "我喜欢", "我习惯", "我偏好", "我一般", "我通常", "我比较", "我更",
        "我不喜欢", "我讨厌", "我烦", "以后", "下次", "尽量", "最好",
    )

    def _mine_preference_from_chat(self, user_text: str):
        """记忆深挖：从用户话里提炼偏好并归档（本地规则，零 token）。

        命中偏好信号词 + 长度适中 → 原句归档到 user_preference，
        由完整档的 get_agent_context(include_preferences=True) 召回。
        不调模型、不阻塞主链路、去重防刷屏。
        """
        try:
            t = (user_text or "").strip()
            if len(t) < 4 or len(t) > 80:
                return
            if not any(m in t for m in self._PREFERENCE_MARKERS):
                return
            from app.core.memory_store import memory_store
            existing = memory_store.query(category="user_preference", tags=["auto"], limit=20)
            for e in existing:
                if (e.content or {}).get("text") == t:
                    return  # 已归档过，跳过
            memory_store.record(
                category="user_preference",
                content={"key": "auto_note", "text": t},
                tags=["preference", "auto"],
                score=0.55,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Agent] 偏好挖掘失败: {e}")

    def _persona_btn_label(self) -> str:
        try:
            from app.core.agent_persona import is_persona_enabled
            return "🌡 知心秘书：开" if is_persona_enabled() else "🌡 知心秘书：关"
        except Exception:  # noqa: BLE001
            return "🌡 知心秘书：关"

    def _greet_agent_secretary(self):
        """面板打开问候：完整档给秘书问候；轻量档给普通就绪 + 首次成本提示。"""
        try:
            from app.core.agent_persona import (
                build_greeting, is_persona_enabled, has_persona_choice, build_onboard_hint,
            )
            if is_persona_enabled():
                self._append_agent_message("Agent", build_greeting())
            else:
                self._append_agent_message("Agent", "已就绪。下方输入剪辑需求或点击快捷指令。")
                if not has_persona_choice():
                    self._append_agent_message("系统", build_onboard_hint())
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Agent] 秘书问候失败: {e}")
            self._append_agent_message("Agent", "已就绪。下方输入剪辑需求或点击快捷指令。")

    def _toggle_agent_persona(self):
        """切换知心秘书温度开关。"""
        try:
            from app.core.agent_persona import is_persona_enabled, set_persona, build_greeting
            turning_on = not is_persona_enabled()
            set_persona(turning_on)
            btn = getattr(self, '_agent_persona_btn', None)
            if btn is not None:
                btn.setText("🌡 知心秘书：开" if turning_on else "🌡 知心秘书：关")
            if turning_on:
                self._append_agent_message(
                    "系统", "已开启「知心秘书」。以后我会记得你、更主动关心你。"
                )
                g = build_greeting()
                if g:
                    self._append_agent_message("Agent", g)
            else:
                self._append_agent_message(
                    "系统", "已关闭「知心秘书」，回到轻量模式（几乎不增 token）。"
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Agent] 切换知心秘书失败: {e}")

    def _set_agent_nickname(self):
        """自定义 Agent 对我的称呼。"""
        try:
            from app.core.agent_persona import get_nickname, set_nickname
            current = get_nickname()
            name, ok = QInputDialog.getText(
                self, "我的称呼", "你希望我怎么称呼你？", text=current
            )
            if not ok:
                return
            name = (name or "").strip()
            if not name:
                return
            if set_nickname(name):
                self._append_agent_message("系统", f"好嘞，以后我就叫你「{name}」啦。")
            else:
                self._append_agent_message("系统", "称呼保存失败，请重试。")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Agent] 设置称呼失败: {e}")

    def _check_agent_idle(self):
        """完整档：长时间无交互时主动关怀一句（默认 30 分钟）。"""
        try:
            from app.core.agent_persona import is_persona_enabled, get_nickname
            if not is_persona_enabled():
                return
            if getattr(self, '_edit_agent_worker', None) and self._edit_agent_worker.isRunning():
                return
            last = getattr(self, '_agent_last_active', time.time())
            if time.time() - last < self._IDLE_REMINDER_MINUTES * 60:
                return
            name = get_nickname() or "朋友"
            self._append_agent_message(
                "Agent",
                f"（{name}，你有一阵没操作了，累了就歇会儿，我随时待命。）",
            )
            self._agent_last_active = time.time()  # 重置，避免每分钟刷屏
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Agent] 空闲关怀失败: {e}")

    # ======================================================================
    # 抽取自 editor_module.py L11793-11877
    # ======================================================================
    def _build_edit_agent_messages(self, user_text: str) -> List[Dict[str, str]]:
        """构建剪辑 Agent 专用提示词，要求模型返回可执行 JSON 指令。"""
        from app.core.agent_action_registry import (
            build_agent_actions_help_block,
            list_editor_capabilities_for_prompt,
        )

        context = self._get_agent_timeline_context()
        extensions_info = self._get_agent_extensions_context()
        from app.core.agent_policy import mode_prompt_block
        from app.core.agent_persona import build_persona_hint, is_persona_enabled

        is_plan_mode = self._is_agent_plan_mode()
        agent_mode = self._get_agent_session_mode()
        caps_info = list_editor_capabilities_for_prompt()
        persona_hint = build_persona_hint()

        system_prompt = (
            "你是拾光剪影的 AI 剪辑助手，也是一位友善的对话伙伴。"
            "你可以像普通 AI 助手一样自由对话，自然回答剪辑技巧、项目功能、视频创作等任何问题，"
            "文字内容不限格式，直接回复即可，不要套 JSON。\n\n"
            f"{persona_hint}\n\n"
            "只有当用户提出明确的剪辑操作需求（切分、删除、滤镜、转场、特效、字幕、轨等）时，"
            "才输出可执行的 JSON 指令数组，且不要附带多余解释文字。\n"
            f"{build_agent_actions_help_block()}"
            + mode_prompt_block(agent_mode)
            + "时间单位是秒，clip_index 从 0 开始。"
            "add_effect 参数示例: {\"effect_type\":\"filter\",\"params\":{\"filter_name\":\"电影\",\"intensity\":0.7}}。"
            "add_transition 参数示例: {\"transition_type\":\"fade\",\"duration\":0.5,\"clip_index\":0}。"
            "call_extension 用于调用拓展中心的插件/Skill/MCP 工具，参数示例: "
            "{\"extension_id\":\"技能ID\",\"tool_id\":\"工具ID\",\"params\":{\"key\":\"value\"}}。"
            "call_model 参数示例: {\"provider\":\"deepseek\",\"messages\":[{\"role\":\"user\",\"content\":\"...\"}],\"model\":\"...\"}。"
        )

        # Plan 模式要求先规划
        if is_plan_mode:
            system_prompt += (
                "\n\n当前为 Plan 模式：你必须先返回执行规划，格式为 JSON 对象："
                "{\"plan\":[\"步骤1\",\"步骤2\",...],\"commands\":[{...指令...}]}。"
                "plan 是给用户看的人类可读步骤列表，commands 是实际要执行的指令数组。"
                "用户确认后才会执行 commands。"
            )
        else:
            system_prompt += "\n\n直接返回 JSON 指令数组。"

        # 注入长期记忆 + 待处理反馈
        try:
            from app.core.memory_store import memory_store
            from app.core.agent_feedback_bridge import agent_feedback_bridge
            mem_ctx = memory_store.get_agent_context(top_k=5, include_preferences=is_persona_enabled())
            pending = agent_feedback_bridge.get_pending_feedback(limit=3)
            if mem_ctx:
                system_prompt += mem_ctx
            if pending:
                summaries = [f.get("summary", agent_feedback_bridge._brief(f)) for f in pending]
                system_prompt += "\n\n[近期发布反馈]\n" + "\n".join(f"- {s}" for s in summaries)
                system_prompt += "\n请在生成剪辑指令时考虑以上反馈。"
                agent_feedback_bridge.mark_feedback_consumed(
                    [f.get("feedback_id") for f in pending if f.get("feedback_id")]
                )
        except Exception as e:
            logger.debug(f"[Agent] 注入记忆失败: {e}")

        # 注入拓展中心可用工具 + Dispatcher 能力（OpenTake 式「可枚举工具面」）
        ext_prompt = ""
        if extensions_info:
            # 截断过长列表，避免撑爆上下文
            slim = extensions_info[:40]
            ext_prompt = f"\n\n拓展中心可用工具:\n{json.dumps(slim, ensure_ascii=False, indent=2)}"
        caps_prompt = ""
        if caps_info:
            caps_prompt = (
                f"\n\n已注册剪辑相关 capability（供理解，对话仍用上面 action）:\n"
                f"{json.dumps(caps_info, ensure_ascii=False, indent=2)}"
            )

        user_prompt = (
            f"用户剪辑指令: {user_text}\n\n"
            f"当前时间线状态:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
            f"{caps_prompt}"
            f"{ext_prompt}"
        )
        return _with_agent_history(system_prompt, user_prompt, is_persona_enabled())

    # ======================================================================
    # 抽取自 editor_module.py L11891-11959
    # ======================================================================
    def _get_agent_extensions_context(self) -> List[Dict[str, Any]]:
        """收集拓展中心可用工具，供 Agent 调用。"""
        tools = []
        try:
            from app.core.extension_base import get_extensions_registry
            registry = get_extensions_registry()
            for ext in registry.list_all():
                if not ext.is_enabled and not ext.is_available:
                    continue
                ext_tools = ext.get_tools() or []
                for t in ext_tools:
                    tools.append({
                        "extension_id": ext.info.id,
                        "extension_name": ext.info.name,
                        "extension_type": ext.extension_type.value,
                        "tool_id": t.id,
                        "tool_name": t.name,
                        "description": t.description,
                    })
        except Exception as e:
            logger.debug(f"收集拓展中心工具失败: {e}")

        # 补充 SkillEngine 中的技能（兼容直接注册的 Skill）
        try:
            # 触发外部 skill 注册（幂等：仅首次实际扫描 app/skills/external/，
            # 后续调用直接返回 0）。修复 Agent 面板看不到外部 skill 的问题：
            # 外部 skill 注册原本只在 extensions_module._refresh_skill_list 触发，
            # 若用户未打开拓展中心标签页，Agent 调用 list_all() 会拿不到外部 skill。
            try:
                from app.skills.external_loader import ensure_external_skills_registered
                ensure_external_skills_registered()
            except Exception as ext_e:
                logger.debug(f"外部 skill 注册失败（不影响内置 skill）: {ext_e}")
            from .skill_engine import skill_engine
            for skill in skill_engine.list_all():
                tools.append({
                    "extension_id": skill.skill_id,
                    "extension_name": skill.skill_name,
                    "extension_type": "skill",
                    "tool_id": skill.skill_id,
                    "tool_name": skill.skill_name,
                    "description": getattr(skill, "skill_description", ""),
                })
        except Exception as e:
            logger.debug(f"收集 SkillEngine 技能失败: {e}")

        # 补充 PluginManager 管理的传统插件（修复 Agent 看不到传统插件的问题：
        # 原逻辑只收集 ExtensionsRegistry 和 SkillEngine，AI特效等
        # PluginManager 管理的插件对 Agent 不可见，模型无法生成 call_extension 指令）
        try:
            # _ensure_plugin_manager 内置 lazy load（首次调用初始化，后续直接返回）
            plugin_mgr = self._ensure_plugin_manager()
            if plugin_mgr is not None:
                for plugin in plugin_mgr.list_plugins(enabled_only=True):
                    plugin_id = getattr(plugin, "id", None)
                    if not plugin_id:
                        continue
                    tools.append({
                        "extension_id": plugin_id,
                        "extension_name": getattr(plugin, "name", plugin_id),
                        "extension_type": "plugin",
                        "tool_id": plugin_id,
                        "tool_name": getattr(plugin, "name", plugin_id),
                        "description": getattr(plugin, "description", ""),
                    })
        except Exception as e:
            logger.debug(f"收集 PluginManager 插件失败: {e}")

        return tools

    # ======================================================================
    # 抽取自 editor_module.py L11961-12026
    # ======================================================================
    def _get_agent_timeline_context(self) -> Dict[str, Any]:
        """整理当前时间线上下文（OpenTake get_timeline 风格：可自省、可决策）。"""
        clips = []
        track_ids = set()
        total_end = 0.0
        for index, clip in enumerate(getattr(self, '_clips', [])):
            start = float(clip.get("start_time", 0) or 0)
            duration = float(clip.get("duration", 0) or 0)
            end = start + duration
            if end > total_end:
                total_end = end
            track = clip.get("track", 0)
            try:
                track_ids.add(int(track))
            except (TypeError, ValueError):
                track_ids.add(track)
            path = clip.get("path") or ""
            clips.append({
                "clip_index": index,
                "id": clip.get("id"),
                "name": clip.get("name") or (path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""),
                "path": path,
                "start_time": start,
                "duration": duration,
                "end_time": end,
                "in_point": clip.get("in_point", 0),
                "out_point": clip.get("out_point"),
                "track": track,
                "volume": clip.get("volume"),
                "speed": clip.get("speed", 1.0),
                "effects": clip.get("effects", {}),
                "transition": clip.get("transition"),
                "has_keyframes": bool(clip.get("keyframes")),
                "canvas_node_id": clip.get("canvas_node_id") or "",
                "canvas_kind": clip.get("canvas_kind") or "",
            })

        # 同轨空隙摘要（供去静音/吸附决策，不改数据）
        gaps = []
        by_track: Dict[Any, list] = {}
        for c in clips:
            by_track.setdefault(c["track"], []).append(c)
        for track, items in by_track.items():
            items = sorted(items, key=lambda x: x["start_time"])
            for i in range(len(items) - 1):
                gap_start = items[i]["end_time"]
                gap_end = items[i + 1]["start_time"]
                if gap_end - gap_start > 0.05:
                    gaps.append({
                        "track": track,
                        "t_in": round(gap_start, 3),
                        "t_out": round(gap_end, 3),
                        "duration": round(gap_end - gap_start, 3),
                    })

        return {
            "clip_count": len(clips),
            "track_count": len(track_ids),
            "tracks": sorted(track_ids, key=lambda x: (isinstance(x, str), x)),
            "timeline_duration": round(total_end, 3),
            "gap_count": len(gaps),
            "gaps": gaps[:20],
            "selected_clip_id": getattr(self, '_current_clip', None).get("id") if getattr(self, '_current_clip', None) else None,
            "playhead_position": getattr(self, '_playhead_position', 0),
            "clips": clips,
        }

    # ======================================================================
    # 抽取自 editor_module.py L12073-12122
    # ======================================================================
    def agent_suggest_canvas_roundtrip(self, open_ui: bool = False) -> Dict[str, Any]:
        """AI 剪辑建议：哪些片可送到画布做变体。默认只返回清单，勾选后才推送。"""
        try:
            from app.core.editor_canvas_link import suggest_canvas_roundtrip
        except ImportError:
            from core.editor_canvas_link import suggest_canvas_roundtrip  # type: ignore
        ctx = self.agent_get_timeline_context()
        items = suggest_canvas_roundtrip(ctx)
        writes = [x for x in items if x.get("action") in ("send_to_canvas", "refresh_canvas")]
        if open_ui and writes:
            try:
                from app.modules.lego.suggest_checklist import pick_checked_indices
            except ImportError:
                from modules.lego.suggest_checklist import pick_checked_indices  # type: ignore
            labels = [str(x.get("label") or x.get("description") or x.get("action")) for x in writes]
            picked = pick_checked_indices(
                self,
                title="AI 剪辑 ↔ 画布联动",
                hint="勾选后把片段推到画布落成源节点。不改时间线。",
                labels=labels,
                default_checked=True,
                ok_text="推送到画布",
            )
            if picked is None:
                return {"success": True, "suggestions": items, "pushed": 0, "awaiting_confirm": True, "cancelled": True}
            pushed = 0
            messages = []
            for i in picked:
                if i < 0 or i >= len(writes):
                    continue
                row = writes[i]
                if row.get("action") == "info":
                    continue
                r = self.agent_send_selected_to_canvas(str(row.get("clip_id") or ""))
                if r.get("success"):
                    pushed += 1
                messages.append(r.get("message") or "")
            return {
                "success": True,
                "suggestions": items,
                "pushed": pushed,
                "message": f"已推送 {pushed} 条到画布",
                "details": messages,
            }
        return {
            "success": True,
            "suggestions": items,
            "awaiting_confirm": True,
            "message": f"{len(writes)} 条可联动（确认后才推送）",
        }

    # ======================================================================
    # 抽取自 editor_module.py L12163-12214
    # ======================================================================
    def agent_suggest_cleanup(self, *, open_ui: bool = True) -> Dict[str, Any]:
        """
        M5：去水词/静音「建议 + 确认」——默认弹勾选对话框，不静默写 _clips，不走 run_full。

        open_ui=False 时仅返回建议 JSON（供 Agent 展示），不改时间线。
        """
        try:
            from app.modules.lego.editor_subtitle_panel import (
                build_editor_cleanup_plan,
                run_cleanup_checklist_flow,
                suggest_cleanup_intervals_payload,
            )
            plan, err = build_editor_cleanup_plan(self)
            if err:
                return {
                    "action": "suggest_cleanup",
                    "success": False,
                    "message": err,
                    "intervals": [],
                    "awaiting_confirm": False,
                }
            payload = suggest_cleanup_intervals_payload(plan)
            if not open_ui:
                return {
                    "action": "suggest_cleanup",
                    "success": True,
                    "message": f"建议 {len(payload)} 段，待确认后执行（未改时间线）",
                    "intervals": payload,
                    "awaiting_confirm": True,
                    "suggested_count": len(payload),
                    "total_duration": float(plan.total_duration),
                    "is_dense_dialogue": bool(plan.is_dense_dialogue),
                }
            flow = run_cleanup_checklist_flow(self, plan)
            return {
                "action": "suggest_cleanup",
                "success": bool(flow.get("success")),
                "cancelled": bool(flow.get("cancelled")),
                "message": flow.get("message", ""),
                "intervals": flow.get("intervals") or payload,
                "suggested_count": flow.get("suggested_count", len(payload)),
                "selected_count": flow.get("selected_count", 0),
                "awaiting_confirm": False,
            }
        except Exception as e:
            logger.exception(f"[Agent] agent_suggest_cleanup 失败: {e}")
            return {
                "action": "suggest_cleanup",
                "success": False,
                "message": f"建议去水词失败（非假成功）: {e}",
                "intervals": [],
            }

    # ======================================================================
    # 抽取自 editor_module.py L12593-12659
    # ======================================================================
    def _handle_pipeline_done(self, data: Dict):
        """处理全链路完成事件：重置按钮状态 + 渲染打分/脚本卡 + 进度完成。"""
        result = data.get("result", {})
        success = result.get("success", False)
        error = result.get("error", "")

        # ── 新增：进度卡最终状态 ──
        degraded = bool(result.get("degraded")) or (
            result.get("success")
            and not result.get("final_video_path")
            and bool(result.get("editing_script"))
        )
        self._finalize_pipeline_stage(
            bool(result.get("success")),
            result.get("error") or "",
            degraded=degraded,
        )

        # ── 新增：渲染五维打分结果卡（从 session 对象取 scored_results） ──
        try:
            session_id = result.get("session_id", "")
            scored = []
            if session_id:
                from app.core.agent_pipeline_orchestrator import (
                    agent_pipeline_orchestrator
                )
                session = agent_pipeline_orchestrator.get_session(session_id)
                if session is not None and getattr(session, "scored_results", None):
                    scored = session.scored_results
            self._render_score_results(scored)
        except Exception as e:
            logger.debug(f"[Agent] 渲染打分卡失败: {e}")

        # ── 新增：渲染剪辑脚本卡（事件载荷已有 editing_script） ──
        try:
            editing_script = result.get("editing_script") or {}
            self._render_editing_script(editing_script if editing_script else None)
        except Exception as e:
            logger.debug(f"[Agent] 渲染脚本卡失败: {e}")

        if result.get("success"):
            final_path = result.get("final_video_path", "")
            degraded = bool(result.get("degraded")) or (
                not final_path and bool(result.get("editing_script"))
            )
            if final_path and not degraded:
                self._append_agent_message(
                    "Agent", f"🎉 全链路执行成功！成片已输出：\n{final_path}")
            elif degraded:
                reason = result.get("error") or "未产出成片文件"
                self._append_agent_message(
                    "Agent",
                    f"⚠️ 全链路降级完成（非完整成片成功）：{reason}\n"
                    "若有脚本，可点【▶ 一键手动精剪】导出；请勿当作已自动成片。",
                )
            else:
                self._append_agent_message(
                    "Agent",
                    "⚠️ 标记成功但无成片路径（状态异常）。请检查日志，勿当作导出完成。",
                )
        else:
            self._append_agent_message(
                "Agent",
                f"❌ 全链路执行失败（非假成功）：{result.get('error', '未知错误')}",
            )
        # 恢复按钮为初始状态
        self._reset_pipeline_button()

    # ======================================================================
    # 抽取自 editor_module.py L12740-12816
    # ======================================================================
    def _agent_call_extension(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Agent 调用拓展中心 —— 优先走统一调用层，失败时回退原逻辑"""
        # 优先走统一调用层
        try:
            from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest
            result = capability_dispatcher.invoke(CapabilityRequest(
                capability_id="ext.run_extension",
                params=params,
                caller="agent",
                agent_mode=self._get_agent_session_mode() if hasattr(self, "_get_agent_session_mode") else "",
                approved=True,
            ))
            if result.success:
                output = result.output.get("result") if result.output else None
                msg = self._format_extension_result(output)
                return {"action": "call_extension", "success": True,
                        "message": msg if msg else "调用成功"}
            # dispatcher 失败则继续走原逻辑
        except Exception as e:
            logger.debug(f"[Agent] dispatcher 调用失败，回退原逻辑: {e}")

        # 原逻辑 fallback（保留向后兼容）
        ext_id = params.get("extension_id") or params.get("extensionId")
        tool_id = params.get("tool_id") or params.get("toolId") or ext_id
        call_params = params.get("params") or {}
        if not ext_id:
            return {"action": "call_extension", "success": False, "message": "缺少 extension_id 参数"}

        # 优先从 ExtensionsRegistry 查找
        try:
            from app.core.extension_base import get_extensions_registry
            registry = get_extensions_registry()
            ext = registry.get(ext_id)
            if ext is not None:
                if not ext.is_available:
                    if not ext.initialize():
                        return {"action": "call_extension", "success": False,
                                "message": f"扩展 {ext.info.name} 初始化失败: {ext.error}"}
                result = ext.run(tool_id, **call_params)
                msg = self._format_extension_result(result)
                return {"action": "call_extension", "success": True,
                        "message": f"已调用 {ext.info.name}.{tool_id}: {msg}"}
        except Exception as e:
            logger.warning(f"Agent 调用 ExtensionsRegistry 失败: {e}")

        # 回退到 SkillEngine
        try:
            from .skill_engine import skill_engine
            for skill in skill_engine.list_all():
                if skill.skill_id == ext_id:
                    from .extensions_context import ExtensionsContext
                    ctx = ExtensionsContext(inputs=call_params)
                    result = skill.execute(ctx)
                    msg = self._format_extension_result(result)
                    return {"action": "call_extension", "success": True,
                            "message": f"已执行技能 {skill.skill_name}: {msg}"}
        except Exception as e:
            logger.warning(f"Agent 调用 SkillEngine 失败: {e}")

        # 回退到 PluginManager（传统插件：AI特效工坊等）
        # 修复 Agent 看不到 PluginManager 管理的传统插件问题：
        # 原逻辑只走 ExtensionsRegistry + SkillEngine，传统插件无法被调用
        try:
            plugin_mgr = self._ensure_plugin_manager()
            if plugin_mgr is not None:
                plugin = plugin_mgr.get_plugin(ext_id)
                if plugin is not None and getattr(plugin, "enabled", False):
                    # PluginManager.run_plugin 内部已 try/except，失败返回 None
                    result = plugin_mgr.run_plugin(ext_id, **call_params)
                    msg = self._format_extension_result(result)
                    return {"action": "call_extension", "success": True,
                            "message": f"已调用插件 {getattr(plugin, 'name', ext_id)}: {msg}"}
        except Exception as e:
            logger.warning(f"Agent 调用 PluginManager 失败: {e}")

        return {"action": "call_extension", "success": False,
                "message": f"未找到扩展: {ext_id}"}

    # ======================================================================
    # 抽取自 editor_module.py L12819-12946
    # ======================================================================
    def _on_run_full_pipeline(self):
        """
        全链路一键执行入口（按钮点击）。
        根据当前按钮状态决定是「启动新流程」还是「继续等待中的流程」。
        """
        pipeline_btn = getattr(self, "_edit_agent_pipeline_btn", None)
        waiting_preview = False
        if pipeline_btn is not None:
            waiting_preview = pipeline_btn.property("waiting_preview") or False

        if waiting_preview:
            # 场景：预览暂停中，用户点击确认 → 以 auto_preview_pass=True 重新执行，跳过预览阻塞
            self._append_agent_message("Agent", "✅ 用户已确认预览，继续执行后续流程...")
            brief = ""
            inp = getattr(self, "_edit_agent_input", None)
            if inp is not None:
                brief = inp.text().strip()
            try:
                from app.core.ai.pipeline_jobs import submit_full_pipeline

                send_btn = getattr(self, "_edit_agent_send_btn", None)
                if send_btn is not None:
                    send_btn.setEnabled(False)

                job = submit_full_pipeline({
                    "materials": [],  # 已在之前的会话中处理，此处沿用
                    "creative_brief": brief,
                    **self._get_pipeline_params(),
                    "auto_preview_pass": True,  # 关键：跳过预览阻塞
                })
                self._start_pipeline_job_polling(str(job.get("job_id") or ""))
            except Exception as e:
                logger.exception("[Agent] 全链路继续执行失败")
                self._append_agent_message("Agent", f"❌ 继续执行失败: {e}")
                send_btn = getattr(self, "_edit_agent_send_btn", None)
                if send_btn is not None:
                    send_btn.setEnabled(True)
            return

        # ── 正常启动新流程 ──
        # 收集导入栏素材（self._clips）
        materials = []
        for c in getattr(self, "_clips", []):
            path = c.get("path", "")
            if path:
                materials.append({
                    "path": path,
                    "type": c.get("type", "video"),
                    "duration": float(c.get("duration", 5.0) or 5.0),
                    "name": c.get("name", ""),
                })
        # 创意简报：优先取 Agent 输入框文本
        brief = ""
        inp = getattr(self, "_edit_agent_input", None)
        if inp is not None:
            brief = inp.text().strip()

        # ── 前置校验：无素材 + 无简报 → 友好提示 ──
        if not materials and not brief:
            self._append_agent_message(
                "Agent",
                "⚠️ 无法启动全链路执行：\n"
                "• 导入栏没有素材\n"
                "• Agent 输入框为空\n\n"
                "请选择以下任一方式后重试：\n"
                "1. 导入视频/图片素材（走 AI 素材剪辑业务线）\n"
                "2. 在输入框描述创意构思（走 AI 视频生成业务线）"
            )
            return

        # ── P1-1 成本确认：走「AI 视频生成业务线」（无素材、有简报）且预估花费 > 0 时，
        #    生成前弹确认 —— 花钱的事让用户拍板，不再静默扣费。（报价失败不阻断生成）
        if not materials and brief:
            try:
                from app.core.ai.video_generation_client import video_generation_client

                _p = self._get_pipeline_params()
                _seg = max(1, int(float(_p["target_duration"]) // float(_p["clip_duration"])))
                _q = video_generation_client.quote(
                    str(_p["provider"]), count=_seg,
                    duration=float(_p["clip_duration"])) or {}
                _cost = float(_q.get("cost_estimate") or 0.0)
                if _cost > 0:
                    from PyQt6.QtWidgets import QMessageBox

                    ret = QMessageBox.question(
                        self, "生成成本确认",
                        f"本次 AI 视频生成预计：\n\n"
                        f"    {_q.get('count', _seg)} 段 × {_q.get('provider')}"
                        f" ≈ ¥{_cost:.2f}\n\n"
                        f"（估算值：声明单价×段数，实际以渠道账单为准）\n"
                        f"是否开始生成？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if ret != QMessageBox.StandardButton.Yes:
                        self._append_agent_message(
                            "Agent", f"🛑 已取消生成（预估 ¥{_cost:.2f}，未产生任何花费）")
                        return
                    self._append_agent_message(
                        "Agent", f"💰 成本已确认：预计 ¥{_cost:.2f}（{_q.get('count', _seg)} 段）")
            except Exception:
                logger.debug("[Agent] 生成前报价失败，跳过成本确认", exc_info=True)

        # ── P1-3 单任务守卫：同一时刻面板只跟踪一个全链路任务 ──
        active_jid = getattr(self, "_pipeline_job_id", "")
        if active_jid:
            self._append_agent_message(
                "Agent",
                f"⚠️ 已有全链路任务 {active_jid} 在执行，请等它结束或点「⏹ 取消」后再启动。"
            )
            return

        # 左右脑协同联想：此前 correlate()/right_brain_think()/left_brain_think() 只有定义没有
        # 调用方，是完全不影响任何实际决策的死代码。这里在启动前跑一次，把联想到的能力
        # 展示给用户，让「左右脑协同」名副其实（仅展示，不改变实际路由/参数逻辑）。
        if brief:
            try:
                from app.core.agent_brain import agent_brain
                plan = agent_brain.correlate(brief)
                right = plan.get("right_brain_plan") or []
                left = plan.get("left_brain_plan") or []
                if right or left:
                    self._append_agent_message(
                        "Agent",
                        f"🧠 联想：右脑(创意) {right or '无'} · 左脑(逻辑) {left or '无'}",
                    )
            except Exception as e:
                logger.debug(f"[Agent] 左右脑联想失败: {e}")

        try:
            from app.core.ai.pipeline_jobs import submit_full_pipeline
            self._append_agent_message(
                "Agent", f"🚀 启动全链路执行（素材 {len(materials)} 个，简报: {brief[:30] or '无'}）..."
                         f"已转为后台任务，可随时取消")
            # 防重复点击
            send_btn = getattr(self, "_edit_agent_send_btn", None)
            if send_btn is not None:
                send_btn.setEnabled(False)

            job = submit_full_pipeline({
                "materials": materials,
                "creative_brief": brief,
                **self._get_pipeline_params(),
                "auto_preview_pass": False,  # 默认：等待人工确认
            })
            self._start_pipeline_job_polling(str(job.get("job_id") or ""))
        except Exception as e:
            logger.exception("[Agent] 全链路启动失败")
            self._append_agent_message("Agent", f"❌ 全链路启动失败: {e}")
            send_btn = getattr(self, "_edit_agent_send_btn", None)
            if send_btn is not None:
                send_btn.setEnabled(True)

    # ======================================================================
    # P1-3 全链路任务轮询 + 取消（gen-jobs 任务表）
    # ======================================================================
    def _start_pipeline_job_polling(self, job_id: str):
        """启动全链路任务轮询（QTimer 1s）+ 显示取消按钮。"""
        self._pipeline_job_id = job_id
        cancel_btn = getattr(self, "_edit_agent_pipeline_cancel_btn", None)
        if cancel_btn is not None:
            cancel_btn.setEnabled(bool(job_id))
            cancel_btn.setVisible(bool(job_id))
        timer = getattr(self, "_pipeline_job_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(1000)
            timer.timeout.connect(self._poll_pipeline_job_tick)
            self._pipeline_job_timer = timer
        if job_id:
            timer.start()

    def _stop_pipeline_job_polling(self):
        """停轮询 + 撤取消按钮 + 清任务号（终态/启动失败时调用）。"""
        timer = getattr(self, "_pipeline_job_timer", None)
        if timer is not None:
            timer.stop()
        self._pipeline_job_id = ""
        cancel_btn = getattr(self, "_edit_agent_pipeline_cancel_btn", None)
        if cancel_btn is not None:
            cancel_btn.setVisible(False)

    def _poll_pipeline_job_tick(self):
        """轮询全链路任务；终态 → 停轮询、撤取消钮、分发完成/失败/取消 UI。

        进度条/阶段消息不在这里刷——orchestrator 经 EventBus 已实时驱动
        （_handle_pipeline_progress），轮询只负责终态判定，两套信号不打架。
        """
        jid = getattr(self, "_pipeline_job_id", "")
        if not jid:
            self._stop_pipeline_job_polling()
            return
        try:
            from app.core.ai.pipeline_jobs import job_status
            s = job_status(jid)
        except Exception:
            logger.exception("[Agent] 查询全链路任务失败")
            return  # 查询失败不终止轮询，下个 tick 再试
        status = str(s.get("status") or "")
        if status not in ("done", "failed", "cancelled"):
            return  # 排队/运行/取消中：继续等
        self._stop_pipeline_job_polling()
        send_btn = getattr(self, "_edit_agent_send_btn", None)
        if send_btn is not None:
            send_btn.setEnabled(True)
        if status == "cancelled":
            self._append_agent_message(
                "Agent", "🛑 全链路已取消（当前段跑完即止，结果丢弃未落盘）")
            return
        if status == "done":
            payload = s.get("result") or {}
            if payload.get("paused"):
                # 预览等待：⏸️ 消息已由 pipeline_waiting_preview 事件发出、
                # 按钮已切「确认预览并继续」——这里只安静收尾，不报失败
                return
            try:
                from app.core.capability_dispatcher import CapabilityResult

                result = CapabilityResult(
                    jid, bool(payload.get("success")),
                    output=payload.get("output") or {},
                    error=str(payload.get("error") or "") or None)
                self._on_full_pipeline_done(result)
            except Exception:
                logger.exception("[Agent] 全链路任务完成回调失败")
            return
        # failed：结果按 gen-jobs 语义丢弃，错误信息保留在任务 error 里
        try:
            from app.core.capability_dispatcher import CapabilityResult

            result = CapabilityResult(
                jid, False,
                error=str(s.get("error") or "全链路执行失败"))
            self._on_full_pipeline_done(result)
        except Exception:
            logger.exception("[Agent] 全链路任务失败回调失败")

    def _on_cancel_pipeline_job(self):
        """取消当前全链路任务（queued 真取消；running 段间生效，结果丢弃不落盘）。"""
        jid = getattr(self, "_pipeline_job_id", "")
        if not jid:
            return
        ok = False
        msg = ""
        try:
            from app.core.ai.pipeline_jobs import cancel_job
            r = cancel_job(jid, "用户点击取消")
            ok = bool(r.get("ok"))
            msg = str(r.get("message") or "")
        except Exception:
            logger.exception("[Agent] 取消全链路任务失败")
        if ok:
            cancel_btn = getattr(self, "_edit_agent_pipeline_cancel_btn", None)
            if cancel_btn is not None:
                cancel_btn.setEnabled(False)  # 等轮询确认终态后统一隐藏
            self._append_agent_message(
                "Agent", "⏳ 已请求取消：当前段跑完后生效，结果将丢弃不落盘")
        else:
            self._append_agent_message(
                "Agent", f"⚠️ 取消未生效（{msg or '任务可能刚结束'}）")

    # ======================================================================
    # 抽取自 editor_module.py L12979-13042
    # ======================================================================
    def _execute_pipeline_editing(self, editing_script: Dict[str, Any],
                                  session_id: str = "") -> str:
        """
        精剪执行入口：解析剪辑脚本，应用转场、字幕、配乐，输出高质量成片。
        被 pipeline.execute_editing 能力调用（通过 editor_module_ref）。
        返回成片路径，失败返回空串。
        """
        import sys as _sys
        import subprocess as _sp
        import tempfile as _tf
        import json as _json

        clip_order = (editing_script or {}).get("clip_order", []) or []
        transitions = (editing_script or {}).get("transitions", {}) or {}
        bgm_path = (editing_script or {}).get("bgm", "")
        # 从脚本或 _clips 中提取字幕文本（如果脚本生成了的话）
        subtitles = (editing_script or {}).get("subtitles", []) or []
        if not subtitles:
            # 尝试从片段元数据中取
            subtitles = [c.get("dialogue", "") for c in self._clips if c.get("dialogue")]

        if not clip_order:
            logger.warning("[pipeline] 精剪：clip_order 为空")
            return ""

        # 按 clip_order 顺序收集存在的片段路径和时长
        clip_map = {c.get("id"): c for c in getattr(self, "_clips", []) if c.get("id")}
        paths_and_durations = []
        for cid in clip_order:
            clip = clip_map.get(cid)
            if clip and clip.get("path") and os.path.exists(clip["path"]):
                duration = float(clip.get("duration", 5.0) or 5.0)
                paths_and_durations.append({"path": clip["path"], "duration": duration, "id": cid})

        if not paths_and_durations:
            logger.warning("[pipeline] 精剪：clip_order 无可用片段路径")
            return ""

        output_dir = "短剧AI剪辑输出"
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            logger.debug("创建短剧AI剪辑输出目录失败: %s", e)
        out_path = os.path.join(
            output_dir, f"pipeline_{session_id or int(time.time())}_final.mp4")

        # 如果只有一个片段，直接应用字幕并添加静音（以适配后续可能的混音）
        if len(paths_and_durations) == 1:
            p = paths_and_durations[0]
            ffmpeg = self._find_pipeline_ffmpeg()
            if not ffmpeg:
                return ""
            return self._apply_single_clip_ffmpeg(ffmpeg, p["path"], p["duration"],
                                                   subtitles[0] if subtitles else "",
                                                   bgm_path, out_path)

        # 多片段：构建复杂的 filter_complex
        ffmpeg = self._find_pipeline_ffmpeg()
        if not ffmpeg:
            logger.warning("[pipeline] 未找到 ffmpeg，无法拼接成片")
            return ""

        return self._apply_multi_clip_ffmpeg(ffmpeg, paths_and_durations, transitions,
                                              subtitles, bgm_path, out_path)

    # ======================================================================
    # 抽取自 editor_module.py L13053-13104
    # ======================================================================
    def _apply_single_clip_ffmpeg(self, ffmpeg: str, input_path: str, duration: float,
                                   subtitle_text: str, bgm_path: str, out_path: str) -> str:
        """处理单个片段：叠加字幕，如有 BGM 则混音。"""
        import sys as _sys
        import subprocess as _sp

        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", input_path]

        has_bgm = bgm_path and os.path.exists(bgm_path)
        if has_bgm:
            cmd.extend(["-i", bgm_path])

        filter_complex = []
        cmd.extend(["-filter_complex"])

        # 字幕处理
        if subtitle_text:
            safe_text = subtitle_text.replace("'", "'\\''").replace(":", "\\:")
            filter_complex.append(f"drawtext=text='{safe_text}':fontcolor=white:fontsize=40:x=(w-text_w)/2:y=(h-text_h)*0.85:box=1:boxcolor=black@0.5:boxborderw=10[v]")
            video_stream = "[v]"
        else:
            video_stream = "[0:v]"

        # 音频处理（BGM 混音或原声）
        if has_bgm:
            filter_complex.append("[0:a][1:a]amix=inputs=2:duration=shortest[a]")
            audio_stream = "[a]"
        else:
            audio_stream = "[0:a]"

        cmd.append(";".join(filter_complex))
        cmd.extend(["-map", video_stream, "-map", audio_stream])

        cmd.extend([
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", out_path
        ])

        flags = 0x08000000 if _sys.platform == "win32" else 0
        try:
            proc = _sp.run(cmd, capture_output=True, timeout=300, creationflags=flags)
            if proc.returncode == 0 and os.path.exists(out_path) \
               and os.path.getsize(out_path) > 0:
                logger.info(f"[pipeline] 单片段成片已输出: {out_path}")
                return out_path
            else:
                err = proc.stderr.decode("utf-8", "ignore")[:200]
                logger.warning(f"[pipeline] 单片段处理失败: {err}")
                return ""
        except Exception as e:
            logger.warning(f"[pipeline] 单片段处理异常: {e}")
            return ""

    # ======================================================================
    # 抽取自 editor_module.py L13106-13288
    # ======================================================================
    def _apply_multi_clip_ffmpeg(self, ffmpeg: str, clips: List[Dict], transitions: Dict,
                                  subtitles: List[str], bgm_path: str, out_path: str) -> str:
        """处理多个片段：应用 xfade 转场、字幕，并混音。"""
        import sys as _sys
        import subprocess as _sp
        # 局部导入宿主类，运行时 editor_module 已完整加载，避免顶层循环导入
        from .editor_module import EditorModule

        # xfade 有效转场类型映射
        _XFADE_VALID = {
            "fade", "fadeblack", "fadewhite", "smoothleft", "smoothright",
            "circlecrop", "radial", "smthopen", "smthcover",
            "wipeleft", "wiperight", "slideleft", "slideright",
            "dissolve", "overlay",
        }
        _TRANSITION_MAP = {
            "fade": "fade",
            "cut": "fade",
            "zoom": "fadeblack",
            "slide": "smoothleft",
            "dissolve": "dissolve",
        }

        # 查找系统字体 + 转义路径（FFmpeg filter 要求正斜杠 + 冒号转义）
        _font_file = EditorModule._find_system_font()
        if _font_file:
            _font_file = _font_file.replace("\\", "/")
            # FFmpeg filter 语法中冒号是保留字符，需用反斜杠转义
            # C:/Windows/... → C\:/Windows/...
            _font_file = _font_file.replace(":", "\\:")

        def _has_audio_stream(filepath: str) -> bool:
            """用 ffprobe 检测文件是否有音频流"""
            try:
                probe_cmd = [
                    ffmpeg.replace("ffmpeg", "ffprobe"), "-v", "error",
                    "-select_streams", "a", "-show_entries", "stream=codec_type",
                    "-of", "csv=p=0", filepath
                ]
                p = _sp.run(probe_cmd, capture_output=True, timeout=10,
                            creationflags=0x08000000 if _sys.platform == "win32" else 0)
                return b"audio" in p.stdout
            except Exception:
                return False  # 检测失败默认无音频

        def _build_filter_parts(enable_subtitles: bool = True,
                                 has_audio: bool = True) -> List[str]:
            """构建 filter_complex 滤镜链"""
            parts = []
            prev_v = None
            prev_a = None
            cum_dur = 0.0
            prev_has_audio = has_audio  # 第一个片段是否有音频

            for i, clip in enumerate(clips):
                subtitle_text = subtitles[i] if i < len(subtitles) else ""
                current_v = f"[{i}:v]"

                # 检测当前片段是否有音频
                clip_has_audio = clip.get("_has_audio", has_audio)
                current_a = f"[{i}:a]" if clip_has_audio else None

                # 字幕滤镜
                if enable_subtitles and subtitle_text and _font_file:
                    safe_text = subtitle_text.replace("'", "'\\''").replace(":", "\\:")
                    parts.append(
                        f"{current_v}drawtext=fontfile='{_font_file}':"
                        f"text='{safe_text}':fontcolor=white:fontsize=36:"
                        f"x=(w-text_w)/2:y=(h-text_h)*0.9:"
                        f"box=1:boxcolor=black@0.4:boxborderw=8[v{i}]"
                    )
                    current_v = f"[v{i}]"

                # 转场参数
                clip_dur = clip["duration"]
                raw_transition = transitions.get(clip["id"], "fade")
                transition_type = _TRANSITION_MAP.get(raw_transition, raw_transition)
                if transition_type not in _XFADE_VALID:
                    transition_type = "fade"
                transition_duration = min(0.5, clip_dur * 0.2)
                offset = cum_dur - transition_duration if i > 0 else 0

                if i == 0:
                    prev_v = current_v
                    prev_a = current_a if clip_has_audio else None
                    cum_dur += clip_dur
                    prev_has_audio = clip_has_audio
                else:
                    out_v = f"[xf{i}v]"
                    parts.append(
                        f"{prev_v}{current_v}xfade=transition={transition_type}:"
                        f"duration={transition_duration}:offset={max(0, offset)}{out_v}"
                    )
                    # 仅当前后片段都有音频时才做音频转场
                    if prev_has_audio and clip_has_audio:
                        out_a = f"[xf{i}a]"
                        parts.append(
                            f"{prev_a}{current_a}acrossfade=d={transition_duration}:"
                            f"c1=tri:c2=tri{out_a}"
                        )
                        prev_a = out_a
                    elif clip_has_audio:
                        prev_a = current_a
                    # 如果当前片段无音频，prev_a 保持不变

                    prev_v = out_v
                    cum_dur += clip_dur - transition_duration
                    prev_has_audio = clip_has_audio

            # BGM 混音（仅当有音频流时）
            if has_bgm and prev_a:
                parts.append(f"{prev_a}[{len(clips)}:a]amix=inputs=2:duration=shortest[aout]")
                final_a = "[aout]"
            elif prev_a:
                final_a = prev_a
            else:
                final_a = None  # 无音频

            _build_filter_parts._final_v = prev_v
            _build_filter_parts._final_a = final_a
            return parts

        # 输入文件
        cmd_base = [ffmpeg, "-y", "-loglevel", "error"]
        for c in clips:
            cmd_base.extend(["-i", c["path"]])

        has_bgm = bgm_path and os.path.exists(bgm_path)
        if has_bgm:
            cmd_base.extend(["-i", bgm_path])

        flags = 0x08000000 if _sys.platform == "win32" else 0

        # 预检测每个片段是否有音频流
        for c in clips:
            if "_has_audio" not in c:
                c["_has_audio"] = _has_audio_stream(c["path"])

        any_has_audio = any(c.get("_has_audio", False) for c in clips)

        def _try_build(enable_subtitles: bool) -> str:
            """尝试构建并执行 FFmpeg 命令"""
            if not any_has_audio and not has_bgm:
                # 全部无音频 + 无 BGM → 跳过音频处理
                fp = _build_filter_parts(enable_subtitles=enable_subtitles, has_audio=False)
            else:
                fp = _build_filter_parts(enable_subtitles=enable_subtitles, has_audio=True)

            cmd = list(cmd_base)
            cmd.extend(["-filter_complex", ";".join(fp)])
            cmd.extend(["-map", _build_filter_parts._final_v])
            if _build_filter_parts._final_a:
                cmd.extend(["-map", _build_filter_parts._final_a])
            cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", out_path])
            if _build_filter_parts._final_a or has_bgm:
                cmd.extend(["-c:a", "aac"])

            try:
                proc = _sp.run(cmd, capture_output=True, timeout=600, creationflags=flags)
                if proc.returncode == 0 and os.path.exists(out_path) \
                   and os.path.getsize(out_path) > 0:
                    return out_path
                else:
                    err = proc.stderr.decode("utf-8", "ignore")[:300]
                    logger.warning(f"[pipeline] FFmpeg 失败: {err}")
                    return ""
            except Exception as e:
                logger.warning(f"[pipeline] FFmpeg 异常: {e}")
                return ""

        # 第一次尝试：带字幕
        if _font_file and any(s for s in subtitles if s):
            result = _try_build(enable_subtitles=True)
            if result:
                logger.info(f"[pipeline] 精剪成片已输出（带字幕）: {result}")
                return result
            logger.warning("[pipeline] 带字幕精剪失败，降级无字幕")

        # 第二次尝试：无字幕
        result = _try_build(enable_subtitles=False)
        if result:
            logger.info(f"[pipeline] 精剪成片已输出（无字幕降级）: {result}")
        else:
            logger.warning("[pipeline] 精剪合成失败（无字幕也失败）")
        return result

