"""
拓展中心模块 (ExtensionsModule)
================================
升级版的插件中心，整合 Skill 插件和 MCP 服务。

功能:
    - 已安装拓展统一管理（Plugin + Skill + MCP）
    - Skill 工坊：浏览/运行/管理 AI 技能
    - MCP 连接管理：连接 Blender MCP 等服务
    - 拓展商店：浏览和安装新拓展
    - 拓展评分与评价

架构:
    ExtensionsModule (UI 层)
    ├── ExtensionsRegistry (统一注册表)
    ├── McpClientManager (MCP 客户端)
    └── SkillEngine (Skill 执行引擎)
"""

import json
import os
import logging
from typing import Dict, List, Any, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QScrollArea, QFrame, QMessageBox, QFileDialog,
    QDialog, QLineEdit, QListWidget, QListWidgetItem, QGroupBox,
    QTextEdit, QFormLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal

from .base_module import BaseModule
from .mcp_preset_autoconnect import auto_connect_blender_preset

logger = logging.getLogger("AI短剧编辑器.extensions")


class ExtensionsModule(BaseModule):
    """
    拓展中心模块

    统一管理所有扩展类型：Plugin / Skill / MCP Server
    """

    module_id = "extensions"
    module_name = "拓展中心"
    module_icon = "🔌"

    # MCP 预设列表
    MCP_PRESETS = [
        {
            "id": "blender",
            "name": "Blender MCP",
            "icon": "🎨",
            "description": "Blender 3D 建模与渲染服务",
            "command": "uvx",
            "args": ["blender-mcp"],
            "category": "3D建模",
        },
        {
            "id": "filesystem",
            "name": "Filesystem MCP",
            "icon": "📁",
            "description": "文件系统操作服务",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
            "category": "系统工具",
        },
        {
            "id": "github",
            "name": "GitHub MCP",
            "icon": "🐙",
            "description": "GitHub API 操作服务",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "category": "开发工具",
        },
        {
            "id": "weather",
            "name": "Weather MCP",
            "icon": "🌤️",
            "description": "天气查询服务",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-weather"],
            "category": "实用工具",
        },
        {
            "id": "guardvibe",
            "name": "GuardVibe MCP",
            "icon": "🛡️",
            "description": "AI 生成代码安全审计服务（456 条安全规则，CVE 检测，提示注入防护）",
            "command": "npx",
            "args": ["-y", "guardvibe"],
            "category": "安全防护",
        },
    ]

    # 子线程 → 主线程信号（修复 _run_selected_skill 主线程阻塞 + Blender 下载回调）
    # 遵守 .trae/rules/2.md §五.2：UI 更新必须在主线程
    _skill_progress_signal = pyqtSignal(int, str)
    _skill_finished_signal = pyqtSignal(bool, str)
    _blender_download_signal = pyqtSignal(bool, str)

    def _setup_ui(self):
        """设置主界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 初始化管理器
        self._init_managers()

        # 顶部工具栏
        top_bar = self._create_top_bar()
        layout.addLayout(top_bar)

        # 标签页
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(self._tab_style())

        # 创建各个标签页
        self._tabs.addTab(
            self._create_installed_tab(),
            "📦 已安装"
        )
        self._tabs.addTab(
            self._create_skill_tab(),
            "⚡ Skill 工坊"
        )
        self._tabs.addTab(
            self._create_mcp_tab(),
            "🔌 MCP 服务"
        )
        self._tabs.addTab(
            self._create_store_tab(),
            "🛍️ 拓展商店"
        )
        self._tabs.addTab(
            self._create_canvas_plugins_tab(),
            "🎨 画布节点"
        )

        layout.addWidget(self._tabs, 1)

        # 信号槽连接：子线程信号 → 主线程槽（修复 Skill 执行与 Blender 下载的 UI 更新）
        self._skill_progress_signal.connect(self._on_skill_progress_main)
        self._skill_finished_signal.connect(self._on_skill_finished_main)
        self._blender_download_signal.connect(self._on_blender_download_done)

        # 刷新已安装列表
        self._refresh_installed()

    def _init_managers(self):
        """初始化管理器"""
        try:
            from app.core.extension_base import get_extensions_registry
            self._registry = get_extensions_registry()
        except Exception as e:
            logger.warning(f"扩展注册表初始化失败: {e}")
            self._registry = None

        try:
            from app.core.mcp_client import McpClientManager
            self._mcp_client = McpClientManager()
        except Exception as e:
            logger.warning(f"MCP 客户端初始化失败: {e}")
            self._mcp_client = None

        # 兼容旧插件中心：初始化 PluginManager + PluginStore
        self._plugin_mgr = None
        try:
            from app.core.plugin_manager import PluginManager
            self._plugin_mgr = PluginManager()
            self._plugin_mgr.load_plugins()
            errs = getattr(self._plugin_mgr, "format_load_errors", lambda: "")()
            if errs:
                logger.warning("插件加载失败摘要:\n%s", errs)
        except Exception as e:
            logger.warning(f"PluginManager 初始化失败: {e}")

        self._store = None
        try:
            from .plugin_store import PluginStore
            self._store = PluginStore()
            self._store.fetch_store_items()
        except Exception as e:
            logger.warning(f"PluginStore 初始化失败: {e}")

        # 已连接的 MCP 服务器列表
        self._connected_mcps: List[Dict[str, Any]] = []

    def _create_top_bar(self) -> QHBoxLayout:
        """创建顶部工具栏"""
        bar = QHBoxLayout()
        bar.setSpacing(8)

        # 标题
        title = QLabel("🔌 拓展中心")
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#fff;")
        bar.addWidget(title)
        bar.addStretch()

        # 快捷入口：AI 特效工坊（兼容旧插件中心）
        ai_effect_btn = QPushButton("✨ AI特效工坊")
        ai_effect_btn.setStyleSheet(
            "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;"
            "padding:7px 14px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#1557b0;}"
        )
        ai_effect_btn.clicked.connect(self._open_ai_effects_studio)
        bar.addWidget(ai_effect_btn)

        # 状态指示器
        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet(
            "color:#888;font-size:11px;padding:4px 12px;"
            "background:#1a1a1a;border-radius:12px;"
        )
        bar.addWidget(self._status_label)

        # 刷新按钮
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setStyleSheet(self._btn_secondary_style())
        refresh_btn.clicked.connect(self._refresh_all)
        bar.addWidget(refresh_btn)

        # 导入按钮
        import_btn = QPushButton("📥 导入")
        import_btn.setStyleSheet(self._btn_secondary_style())
        import_btn.clicked.connect(self._import_extension)
        bar.addWidget(import_btn)

        return bar





    def _open_ai_effects_studio(self):
        """打开 AI 特效工坊（兼容旧插件中心，绕过通用UI检查直接打开）"""
        plugin = self._find_plugin_by_name("AI特效制作")

        # 获取 AI 特效 widget 类（优先用已加载插件的方法）
        Widget = None
        ai_plugin = plugin

        if plugin is not None:
            try:
                # 从已加载的插件获取 widget
                if callable(getattr(plugin, "get_ui_widget_class", None)):
                    Widget = plugin.get_ui_widget_class()
                # 尝试从 ai_effects_plugin.main 获取
                if Widget is None:
                    from app.plugins.ai_effects_plugin.main import _load_ai_effects_widget
                    Widget = _load_ai_effects_widget()
            except Exception as e:
                logger.warning(f"获取 AI 特效 widget 类失败: {e}")

        if Widget is None:
            # 插件未加载，尝试直接创建实例
            try:
                from app.plugins.ai_effects_plugin.main import Plugin, _load_ai_effects_widget
                ai_plugin = Plugin()
                if not getattr(ai_plugin, "_initialized", False):
                    ai_plugin.initialize({})
                Widget = _load_ai_effects_widget()
            except Exception as e:
                QMessageBox.warning(
                    self, "打开失败",
                    f"AI 特效插件无法加载:\n{e}\n\n"
                    "常见原因：缺依赖（torch / opencv / Pillow）"
                )
                return

        if Widget is None or ai_plugin is None:
            QMessageBox.warning(self, "打开失败", "无法获取 AI 特效界面组件")
            return

        # 弹出 AI 特效工坊对话框
        try:
            dlg = QDialog(self)
            dlg.setWindowTitle("✨ AI 特效工坊")
            dlg.resize(960, 680)
            dlg.setStyleSheet("QDialog{background:#121212;}")
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 0, 0)
            widget = Widget(ai_plugin, dlg)
            lay.addWidget(widget)
            widget.show()
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "打开失败", f"AI 特效工坊启动失败:\n{e}")

    def handle_module_action(self, action: str) -> bool:
        """响应子页跳转（例：首页 MCP 卡片「设置」→ MCP 服务页）。实现见 extensions_module_pages。"""
        from app.modules.lego.extensions_module_pages import switch_extension_tab

        return switch_extension_tab(self._tabs, action)

    def _tab_style(self) -> str:
        """标签页样式"""
        return (
            "QTabWidget::pane{border:none;background:transparent;}"
            "QTabBar::tab{background:transparent;color:#888;border:none;"
            "padding:8px 16px;font-size:12px;}"
            "QTabBar::tab:selected{color:#fff;border-bottom:2px solid #7c3aed;}"
            "QTabBar::tab:hover{color:#ccc;}"
        )

    def _btn_secondary_style(self) -> str:
        """次要按钮样式"""
        return (
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;"
            "border-radius:6px;padding:7px 14px;font-size:11px;}"
            "QPushButton:hover{background:#3a3a3a;}"
        )

    def _btn_primary_style(self) -> str:
        """主要按钮样式"""
        return (
            "QPushButton{background:#7c3aed;color:#fff;border:none;"
            "border-radius:6px;padding:7px 14px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#6d28d9;}"
            "QPushButton:disabled{background:#3a3a3a;color:#666;}"
        )

    def _btn_danger_style(self) -> str:
        """危险按钮样式"""
        return (
            "QPushButton{background:#f44336;color:#fff;border:none;"
            "border-radius:6px;padding:7px 14px;font-size:11px;}"
            "QPushButton:hover{background:#d32f2f;}"
        )

    def _create_card_style(self) -> str:
        """卡片样式"""
        return (
            "QFrame{background:#1a1a1a;border:1px solid #2a2a2a;"
            "border-radius:8px;padding:12px;margin:4px 0;}"
            "QFrame:hover{border-color:#3a3a3a;}"
        )

    def _create_installed_tab(self) -> QWidget:
        """创建已安装拓展标签页"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        # 分类筛选
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_label = QLabel("筛选:")
        filter_label.setStyleSheet("color:#888;font-size:11px;")
        filter_row.addWidget(filter_label)

        self._filter_all = QPushButton("全部")
        self._filter_all.setCheckable(True)
        self._filter_all.setChecked(True)
        self._filter_all.setStyleSheet(self._filter_btn_style(True))
        self._filter_all.clicked.connect(lambda: self._set_filter("all"))
        filter_row.addWidget(self._filter_all)

        self._filter_skill = QPushButton("⚡ 技能")
        self._filter_skill.setCheckable(True)
        self._filter_skill.setStyleSheet(self._filter_btn_style(False))
        self._filter_skill.clicked.connect(lambda: self._set_filter("skill"))
        filter_row.addWidget(self._filter_skill)

        self._filter_mcp = QPushButton("🔌 MCP")
        self._filter_mcp.setCheckable(True)
        self._filter_mcp.setStyleSheet(self._filter_btn_style(False))
        self._filter_mcp.clicked.connect(lambda: self._set_filter("mcp"))
        filter_row.addWidget(self._filter_mcp)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # 拓展列表
        self._installed_container = QWidget()
        self._installed_layout = QVBoxLayout(self._installed_container)
        self._installed_layout.setContentsMargins(0, 0, 0, 0)
        self._installed_layout.setSpacing(8)

        installed_scroll = QScrollArea()
        installed_scroll.setWidgetResizable(True)
        installed_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        installed_scroll.setWidget(self._installed_container)

        layout.addWidget(installed_scroll, 1)

        return container

    def _filter_btn_style(self, checked: bool) -> str:
        """筛选按钮样式"""
        if checked:
            return (
                "QPushButton{background:#7c3aed;color:#fff;border:none;"
                "border-radius:4px;padding:5px 12px;font-size:11px;}"
            )
        return (
            "QPushButton{background:transparent;color:#888;border:1px solid #333;"
            "border-radius:4px;padding:5px 12px;font-size:11px;}"
            "QPushButton:hover{color:#fff;border-color:#555;}"
        )

    def _set_filter(self, filter_type: str):
        """设置筛选类型（插件已并入技能，只有全部/技能/MCP 三种）"""
        self._current_filter = filter_type

        self._filter_all.setChecked(filter_type == "all")
        self._filter_all.setStyleSheet(
            self._filter_btn_style(filter_type == "all")
        )
        self._filter_skill.setChecked(filter_type == "skill")
        self._filter_skill.setStyleSheet(
            self._filter_btn_style(filter_type == "skill")
        )
        self._filter_mcp.setChecked(filter_type == "mcp")
        self._filter_mcp.setStyleSheet(
            self._filter_btn_style(filter_type == "mcp")
        )

        self._refresh_installed()

    def _create_skill_tab(self) -> QWidget:
        """创建 Skill 工坊标签页（含分类过滤 + domain 标签 + AIGC 跳转）"""
        from .skill_engine import Skill

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── 左侧：分类过滤 + 技能列表 ──
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        left_label = QLabel("⚡ 可用技能")
        left_label.setStyleSheet("font-size:14px;font-weight:bold;color:#fff;")
        left_layout.addWidget(left_label)

        # 分类过滤按钮组
        cat_row = QHBoxLayout()
        cat_row.setSpacing(4)

        self._skill_cat_filter = "all"

        cat_btn_style = (
            "QPushButton{{background:{bg};color:{fg};border:1px solid #333;"
            "border-radius:4px;padding:4px 10px;font-size:11px;}}"
            "QPushButton:hover{{border-color:#7c3aed;}}"
        )

        self._skill_cats: Dict[str, QPushButton] = {}
        cats = [("全部", "all", "#7c3aed", "#fff")]
        for cat in Skill.ALL_CATEGORIES:
            cats.append((cat, cat, "transparent", "#888"))

        for label, key, bg, fg in cats:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setStyleSheet(cat_btn_style.format(bg=bg, fg=fg))
            btn.clicked.connect(lambda _=False, k=key: self._filter_skill_category(k))
            cat_row.addWidget(btn)
            self._skill_cats[key] = btn

        cat_row.addStretch()
        left_layout.addLayout(cat_row)

        self._skill_list = QListWidget()
        self._skill_list.setMinimumWidth(280)
        self._skill_list.setStyleSheet(
            "QListWidget{background:#1a1a1a;border:1px solid #2a2a2a;"
            "border-radius:8px;}"
            "QListWidget::item{padding:8px;color:#fff;}"
            "QListWidget::item:selected{background:#7c3aed;}"
        )
        self._skill_list.itemClicked.connect(self._on_skill_selected)
        left_layout.addWidget(self._skill_list, 1)

        skill_btn = QPushButton("🔄 刷新技能列表")
        skill_btn.setStyleSheet(self._btn_secondary_style())
        skill_btn.clicked.connect(self._refresh_skill_list)
        left_layout.addWidget(skill_btn)

        layout.addWidget(left_panel)

        # ── 右侧：技能详情 + 执行 / 跳转 ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._skill_detail = QTextEdit()
        self._skill_detail.setReadOnly(True)
        self._skill_detail.setPlaceholderText("选择左侧技能查看详情...\n\n"
                                              "💡 标注为「🎨 画布域」的 AIGC 技能，请前往 AI 画布使用节点生成。")
        self._skill_detail.setStyleSheet(
            "QTextEdit{background:#1a1a1a;border:1px solid #2a2a2a;"
            "border-radius:8px;padding:12px;color:#ccc;font-size:12px;}"
        )
        right_layout.addWidget(self._skill_detail, 1)

        # Domain 提示栏（动态显示）
        self._skill_domain_bar = QLabel("")
        self._skill_domain_bar.setWordWrap(True)
        self._skill_domain_bar.setStyleSheet(
            "padding:8px;border-radius:6px;font-size:12px;background:#1a2a3a;color:#60a5fa;"
        )
        self._skill_domain_bar.setVisible(False)
        right_layout.addWidget(self._skill_domain_bar)

        # 执行区域（pipeline domain 可见）
        self._skill_exec_group = QGroupBox("执行技能（后端）")
        self._skill_exec_group.setStyleSheet(
            "QGroupBox{color:#888;border:1px solid #2a2a2a;border-radius:8px;"
            "margin-top:12px;padding-top:16px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;}"
        )
        exec_layout = QVBoxLayout(self._skill_exec_group)
        exec_layout.setSpacing(8)

        self._skill_input = QLineEdit()
        self._skill_input.setPlaceholderText('输入技能参数（JSON 格式），例如 {"topic": "30秒科技产品介绍"}')
        self._skill_input.setStyleSheet(
            "QLineEdit{background:#0d0d0d;border:1px solid #2a2a2a;"
            "border-radius:6px;padding:8px;color:#fff;}"
        )
        exec_layout.addWidget(self._skill_input)

        run_btn = QPushButton("▶ 运行技能")
        run_btn.setStyleSheet(self._btn_primary_style())
        run_btn.clicked.connect(self._run_selected_skill)
        exec_layout.addWidget(run_btn)

        self._skill_output = QTextEdit()
        self._skill_output.setReadOnly(True)
        self._skill_output.setMaximumHeight(100)
        self._skill_output.setPlaceholderText("执行结果...")
        self._skill_output.setStyleSheet(
            "QTextEdit{background:#0d0d0d;border:1px solid #2a2a2a;"
            "border-radius:6px;padding:8px;color:#0f0;font-size:11px;font-family:monospace;}"
        )
        exec_layout.addWidget(self._skill_output)

        right_layout.addWidget(self._skill_exec_group)

        # 画布跳转按钮（canvas domain 可见）
        self._skill_canvas_group = QGroupBox("🎨 AI 画布（AIGC 技能）")
        self._skill_canvas_group.setStyleSheet(
            "QGroupBox{color:#888;border:1px solid #2a2a2a;border-radius:8px;"
            "margin-top:12px;padding-top:16px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;color:#22c55e;}"
        )
        canvas_layout = QVBoxLayout(self._skill_canvas_group)
        canvas_layout.setSpacing(8)

        canvas_hint = QLabel(
            "此技能属于 AIGC 生成域，在 Skill 工坊执行会自动委托给 AI 画布的"
            "生图/生视频/音频节点。建议直接前往画布使用专业的节点式编辑面板。"
        )
        canvas_hint.setWordWrap(True)
        canvas_hint.setStyleSheet("color:#aaa;font-size:12px;padding:4px;")
        canvas_layout.addWidget(canvas_hint)

        self._jump_to_canvas_btn = QPushButton("🎨 前往 AI 画布")
        self._jump_to_canvas_btn.setStyleSheet(
            "QPushButton{background:#22c55e;color:#fff;border:none;border-radius:6px;"
            "padding:10px 16px;font-weight:600;}"
            "QPushButton:hover{background:#16a34a;}"
        )
        self._jump_to_canvas_btn.clicked.connect(self._jump_to_canvas)
        canvas_layout.addWidget(self._jump_to_canvas_btn)

        self._skill_canvas_group.setVisible(False)
        right_layout.addWidget(self._skill_canvas_group)

        layout.addWidget(right_panel, 1)

        self._refresh_skill_list()
        return container

    def _filter_skill_category(self, category: str):
        """按 skill_category 过滤左侧列表"""
        self._skill_cat_filter = category
        for key, btn in self._skill_cats.items():
            if key == category:
                btn.setStyleSheet(
                    "QPushButton{background:#7c3aed;color:#fff;border:1px solid #7c3aed;"
                    "border-radius:4px;padding:4px 10px;font-size:11px;}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton{background:transparent;color:#888;border:1px solid #333;"
                    "border-radius:4px;padding:4px 10px;font-size:11px;}"
                    "QPushButton:hover{border-color:#7c3aed;}"
                )
        self._refresh_skill_list()

    def _create_mcp_tab(self) -> QWidget:
        """创建 MCP 服务标签页"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)

        # MCP 预设快捷连接区
        presets_group = QGroupBox("🔌 MCP 预设服务")
        presets_group.setStyleSheet(
            "QGroupBox{color:#888;border:1px solid #2a2a2a;border-radius:8px;"
            "margin-top:8px;padding-top:16px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;color:#fff;}"
        )
        presets_layout = QVBoxLayout(presets_group)
        presets_layout.setSpacing(8)

        # 内置预设 + 外部扫描到的 MCP（如 videocut-skills 的 chengfeng-videocut）
        for preset in self._get_all_mcp_presets():
            preset_card = self._create_mcp_preset_card(preset)
            presets_layout.addWidget(preset_card)

        layout.addWidget(presets_group)

        # ★ V4.46.19（用户需求「系统应该默认配置 Blender MCP 服务」）：
        #   首次进入 MCP 页时自动连接 Blender 预设（幂等：本会话已尝试过就不重复；
        #   连接结果如实进「已连接」列表或状态栏，失败不弹窗打断——只是默认帮你连）。
        if not getattr(self, "_blender_autoconnect_done", False):
            self._blender_autoconnect_done = True
            try:
                from PyQt6.QtCore import QTimer as _QTimer

                # 稍等页面布局完成再连，避免抢首帧
                _QTimer.singleShot(600, self._auto_connect_blender_preset)
            except Exception:
                logger.debug("Blender 自动连接挂载失败（忽略）", exc_info=True)

        # 已连接 MCP 列表
        connected_group = QGroupBox("已连接 MCP 服务")
        connected_group.setStyleSheet(
            "QGroupBox{color:#888;border:1px solid #2a2a2a;border-radius:8px;"
            "margin-top:8px;padding-top:16px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;color:#fff;}"
        )
        connected_layout = QVBoxLayout(connected_group)

        self._connected_list_widget = QListWidget()
        self._connected_list_widget.setStyleSheet(
            "QListWidget{background:#1a1a1a;border:1px solid #2a2a2a;"
            "border-radius:6px;max-height:120px;}"
            "QListWidget::item{padding:8px;color:#fff;}"
        )
        connected_layout.addWidget(self._connected_list_widget)

        # 已连接详情
        self._mcp_tools_detail = QTextEdit()
        self._mcp_tools_detail.setReadOnly(True)
        self._mcp_tools_detail.setMaximumHeight(150)
        self._mcp_tools_detail.setPlaceholderText("点击已连接的 MCP 查看可用工具...")
        self._mcp_tools_detail.setStyleSheet(
            "QTextEdit{background:#0d0d0d;border:1px solid #2a2a2a;"
            "border-radius:6px;padding:8px;color:#ccc;font-size:11px;}"
        )
        connected_layout.addWidget(self._mcp_tools_detail)

        layout.addWidget(connected_group, 1)

        # 手动连接区
        manual_group = QGroupBox("手动连接 MCP Server")
        manual_group.setStyleSheet(
            "QGroupBox{color:#888;border:1px solid #2a2a2a;border-radius:8px;"
            "margin-top:8px;padding-top:16px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;color:#fff;}"
        )
        manual_layout = QFormLayout(manual_group)
        manual_layout.setSpacing(8)

        self._mcp_name_input = QLineEdit()
        self._mcp_name_input.setPlaceholderText("服务名称")
        manual_layout.addRow("名称:", self._mcp_name_input)

        self._mcp_command_input = QLineEdit()
        self._mcp_command_input.setPlaceholderText("命令 (如 uvx, npx)")
        manual_layout.addRow("命令:", self._mcp_command_input)

        self._mcp_args_input = QLineEdit()
        self._mcp_args_input.setPlaceholderText("参数 (空格分隔)")
        manual_layout.addRow("参数:", self._mcp_args_input)

        connect_btn = QPushButton("🔌 连接")
        connect_btn.setStyleSheet(self._btn_primary_style())
        connect_btn.clicked.connect(self._manual_connect_mcp)
        manual_layout.addRow(connect_btn)

        layout.addWidget(manual_group)

        return container

    def _get_all_mcp_presets(self) -> List[Dict[str, Any]]:
        """获取所有 MCP 预设（内置 + 外部 .mcp.json 扫描）

        修复 Agent 无法发现 videocut MCP 的问题：
        原逻辑只展示 MCP_PRESETS 中的 5 个内置预设，
        外部 skill 仓库下的 .mcp.json 配置不会被加载。
        现调用 mcp_client.list_all_mcp_presets_with_external() 合并展示。
        """
        try:
            from app.core.mcp_client import list_all_mcp_presets_with_external
            return list_all_mcp_presets_with_external()
        except Exception as e:
            logger.warning(f"获取 MCP 预设列表失败（回退到内置预设）: {e}")
            return self.MCP_PRESETS

    def _create_mcp_preset_card(self, preset: Dict) -> QFrame:
        """创建 MCP 预设卡片"""
        card = QFrame()
        card.setStyleSheet(self._create_card_style())

        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # 图标
        icon_label = QLabel(preset.get("icon", "🔌"))
        icon_label.setStyleSheet("font-size:24px;")
        layout.addWidget(icon_label)

        # 信息
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        name_label = QLabel(preset.get("name", "Unknown"))
        name_label.setStyleSheet("color:#fff;font-size:13px;font-weight:bold;")
        info_layout.addWidget(name_label)

        desc_label = QLabel(preset.get("description", ""))
        desc_label.setStyleSheet("color:#888;font-size:11px;")
        desc_label.setWordWrap(True)
        info_layout.addWidget(desc_label)

        cat_label = QLabel(f"分类: {preset.get('category', '未分类')}")
        cat_label.setStyleSheet("color:#666;font-size:10px;")
        info_layout.addWidget(cat_label)

        layout.addLayout(info_layout, 1)

        # 连接按钮
        connect_btn = QPushButton("🔌 连接")
        connect_btn.setStyleSheet(self._btn_primary_style())
        connect_btn.clicked.connect(
            lambda _, p=preset: self._connect_mcp_preset(p)
        )
        layout.addWidget(connect_btn)

        # 仅 Blender MCP 预设追加「从 Git 下载」按钮（未下载时才显示）
        if preset.get("id") == "blender":
            blender_mcp_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))))),
                "thirdparty", "blender", "blender-mcp"
            )
            if not os.path.exists(blender_mcp_path):
                download_btn = QPushButton("📥 从 Git 下载")
                download_btn.setStyleSheet(self._btn_secondary_style())
                download_btn.setToolTip(
                    "下载 harveyxiacn/blender-mcp 增强版（359 工具）到 thirdparty/blender/"
                )
                download_btn.clicked.connect(self._download_blender_mcp)
                layout.addWidget(download_btn)

        return card

    def _create_store_tab(self) -> QWidget:
        """创建拓展商店标签页（集成 PluginStore 商店内容）"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        # 分类筛选栏
        cat_row = QHBoxLayout()
        cat_row.setSpacing(4)
        cat_label = QLabel("分类:")
        cat_label.setStyleSheet("color:#888;font-size:11px;")
        cat_row.addWidget(cat_label)

        categories = ["全部", "视频处理", "AI工具", "导出工具", "字幕工具", "音频工具", "特效工具", "运营工具"]
        self._store_cat_buttons = {}
        for cat_text in categories:
            btn = QPushButton(cat_text)
            btn.setCheckable(True)
            if cat_text == "全部":
                btn.setChecked(True)
                btn.setStyleSheet(self._filter_btn_style(True))
            else:
                btn.setStyleSheet(self._filter_btn_style(False))
            btn.clicked.connect(lambda checked, ct=cat_text: self._filter_store(ct))
            cat_row.addWidget(btn)
            self._store_cat_buttons[cat_text] = btn
        cat_row.addStretch()
        layout.addLayout(cat_row)

        # 商店内容容器
        self._store_container = QWidget()
        self._store_layout = QVBoxLayout(self._store_container)
        self._store_layout.setContentsMargins(0, 0, 0, 0)
        self._store_layout.setSpacing(8)

        store_scroll = QScrollArea()
        store_scroll.setWidgetResizable(True)
        store_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        store_scroll.setWidget(self._store_container)

        layout.addWidget(store_scroll, 1)

        # 初始加载商店内容
        self._current_store_category = "全部"
        self._refresh_store()

        return container

    def _filter_store(self, category: str):
        """筛选商店分类"""
        self._current_store_category = category
        # 更新按钮状态
        for cat_text, btn in self._store_cat_buttons.items():
            btn.setChecked(cat_text == category)
            btn.setStyleSheet(self._filter_btn_style(cat_text == category))
        self._refresh_store()

    def _refresh_store(self):
        """刷新商店内容（从 PluginStore 加载）"""
        # 清空现有列表
        while self._store_layout.count():
            item = self._store_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._store:
            hint = QLabel(
                "插件商店未就绪\n\n"
                "目前支持手动导入 .py 插件文件和 .zip 拓展包\n"
                "点击顶部「导入」按钮加载本地插件"
            )
            hint.setStyleSheet("color:#666;font-size:12px;padding:40px;")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setWordWrap(True)
            self._store_layout.addWidget(hint)
            self._store_layout.addStretch()
            return

        category = getattr(self, '_current_store_category', '全部')
        cat_map = {
            "全部": None, "视频处理": "VIDEO_PROCESSING", "AI工具": "AI_TOOLS",
            "导出工具": "EXPORT_TOOLS", "字幕工具": "SUBTITLE_TOOLS",
            "音频工具": "AUDIO_TOOLS", "特效工具": "EFFECT_TOOLS", "运营工具": "OPERATION_TOOLS"
        }
        target_cat = cat_map.get(category)

        has_any = False
        try:
            for it in self._store.get_items():
                # 分类筛选
                if target_cat and it.category and it.category.name != target_cat:
                    continue

                # 判断是否已安装
                installed = it.is_installed
                btn_text = "已安装" if installed else "安装"
                btn_color = "#555" if installed else "#7c3aed"
                callback = (lambda checked, iid=it.id: self._install_store_item(iid)) if not installed \
                    else (lambda checked, iid=it.id: self._uninstall_store_item(iid))

                card = self._create_legacy_plugin_card(
                    it.icon or "📦", it.name, it.description, it.version,
                    btn_text, btn_color, callback, True
                )
                self._store_layout.addWidget(card)
                has_any = True
        except Exception as e:
            logger.warning(f"加载商店内容失败: {e}")

        if not has_any:
            hint = QLabel("该分类暂无拓展\n\n可尝试其他分类或手动导入本地插件")
            hint.setStyleSheet("color:#666;font-size:12px;padding:40px;")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._store_layout.addWidget(hint)

        self._store_layout.addStretch()

    def _install_store_item(self, item_id: str):
        """安装商店插件"""
        if not self._store:
            QMessageBox.warning(self, "安装失败", "插件商店未就绪")
            return
        try:
            ok, msg = self._store.install_item(item_id)
            if ok:
                QMessageBox.information(self, "安装成功", "✅ 插件已安装")
                self._refresh_store()
                self._refresh_installed()
            else:
                QMessageBox.warning(self, "安装失败", msg)
        except Exception as e:
            QMessageBox.warning(self, "安装失败", str(e))

    # ═══════════════════════════════════════════════════════════════
    # 🎨 画布节点插件 Tab（Qt ↔ React 插件生态入口）
    # ═══════════════════════════════════════════════════════════════

    def _create_canvas_plugins_tab(self) -> QWidget:
        """创建「画布节点」标签页
        左侧：官方/社区注册表 + 已安装列表切换
        右侧：插件详情 + 安装/启停/卸载
        """
        try:
            from app.core.canvas_bridge import (
                _BUILTIN_PLUGIN_REGISTRY,
                _load_canvas_plugins_manifest,
                _upsert_canvas_plugin,
                _toggle_canvas_plugin_enabled,
                _remove_canvas_plugin,
            )
            self._cb_plugins_registry = _BUILTIN_PLUGIN_REGISTRY
            self._cb_plugins_load = _load_canvas_plugins_manifest
            self._cb_plugins_upsert = _upsert_canvas_plugin
            self._cb_plugins_toggle = _toggle_canvas_plugin_enabled
            self._cb_plugins_remove = _remove_canvas_plugin
        except Exception as e:
            logger.warning("加载 canvas_bridge 插件函数失败: %s", e)
            self._cb_plugins_registry = []
            self._cb_plugins_load = lambda: []
            self._cb_plugins_upsert = lambda *a, **kw: None
            self._cb_plugins_toggle = lambda *a, **kw: False
            self._cb_plugins_remove = lambda *a, **kw: False

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)

        # ── 左侧面板 ──
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(8)

        # 切换按钮：注册表 / 已安装
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._cb_tab_registry = QPushButton("🛍️ 注册表")
        self._cb_tab_registry.setCheckable(True)
        self._cb_tab_registry.setChecked(True)
        self._cb_tab_registry.setStyleSheet(self._filter_btn_style(True))
        self._cb_tab_registry.clicked.connect(lambda: self._switch_cb_list("registry"))
        btn_row.addWidget(self._cb_tab_registry)
        self._cb_tab_installed = QPushButton("📦 已安装")
        self._cb_tab_installed.setCheckable(True)
        self._cb_tab_installed.setStyleSheet(self._filter_btn_style(False))
        self._cb_tab_installed.clicked.connect(lambda: self._switch_cb_list("installed"))
        btn_row.addWidget(self._cb_tab_installed)
        btn_row.addStretch()
        left_lay.addLayout(btn_row)

        # 搜索框
        self._cb_search = QLineEdit()
        self._cb_search.setPlaceholderText("🔍 搜索插件...")
        self._cb_search.setStyleSheet(
            "QLineEdit{background:#0d0d0d;border:1px solid #2a2a2a;"
            "border-radius:6px;padding:8px;color:#fff;}"
        )
        self._cb_search.textChanged.connect(lambda _: self._refresh_canvas_plugins())
        left_lay.addWidget(self._cb_search)

        # 插件列表
        self._cb_list = QListWidget()
        self._cb_list.setMinimumWidth(280)
        self._cb_list.setStyleSheet(
            "QListWidget{background:#1a1a1a;border:1px solid #2a2a2a;"
            "border-radius:8px;outline:none;}"
            "QListWidget::item{padding:10px;color:#fff;border-bottom:1px solid #222;}"
            "QListWidget::item:selected{background:#7c3aed;color:#fff;}"
            "QListWidget::item:hover{background:#252525;}"
        )
        self._cb_list.itemClicked.connect(self._on_canvas_plugin_selected)
        left_lay.addWidget(self._cb_list, 1)

        # 开发者链接
        dev_btn = QPushButton("📘 插件开发规范")
        dev_btn.setStyleSheet(self._btn_secondary_style())
        dev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dev_btn.clicked.connect(lambda: self._open_url(
            "https://github.com/shiguang-canvas/node-plugin-sdk/blob/main/README.md",
            "节点插件 SDK 开发规范",
        ))
        left_lay.addWidget(dev_btn)

        layout.addWidget(left)

        # ── 右侧详情面板 ──
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(10)

        # 图标 + 标题 + 版本
        self._cb_detail_header = QWidget()
        self._cb_detail_header.setStyleSheet(
            "QWidget{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:16px;}"
        )
        header_lay = QHBoxLayout(self._cb_detail_header)
        header_lay.setContentsMargins(16, 16, 16, 16)
        self._cb_detail_icon = QLabel("🔌")
        self._cb_detail_icon.setStyleSheet("font-size:36px;")
        header_lay.addWidget(self._cb_detail_icon)
        meta_col = QVBoxLayout()
        meta_col.setSpacing(4)
        self._cb_detail_name = QLabel("选择左侧插件查看详情")
        self._cb_detail_name.setStyleSheet("color:#fff;font-size:16px;font-weight:bold;")
        meta_col.addWidget(self._cb_detail_name)
        self._cb_detail_version = QLabel("")
        self._cb_detail_version.setStyleSheet("color:#666;font-size:11px;")
        meta_col.addWidget(self._cb_detail_version)
        self._cb_detail_badge = QLabel("")
        self._cb_detail_badge.setStyleSheet("color:#7c3aed;font-size:10px;padding:2px 6px;background:#2a1e4a;border-radius:4px;")
        meta_col.addWidget(self._cb_detail_badge)
        header_lay.addLayout(meta_col, 1)
        right_lay.addWidget(self._cb_detail_header)

        # 描述
        self._cb_detail_desc = QLabel("")
        self._cb_detail_desc.setStyleSheet("color:#888;font-size:12px;padding:12px;background:#1a1a1a;border-radius:8px;")
        self._cb_detail_desc.setWordWrap(True)
        self._cb_detail_desc.setMinimumHeight(60)
        right_lay.addWidget(self._cb_detail_desc)

        # 节点列表
        self._cb_detail_nodes_label = QLabel("包含节点:")
        self._cb_detail_nodes_label.setStyleSheet("color:#666;font-size:11px;margin-top:8px;")
        right_lay.addWidget(self._cb_detail_nodes_label)
        self._cb_detail_nodes = QListWidget()
        self._cb_detail_nodes.setMaximumHeight(120)
        self._cb_detail_nodes.setStyleSheet(
            "QListWidget{background:#0d0d0d;border:1px solid #2a2a2a;border-radius:6px;}"
            "QListWidget::item{padding:6px;color:#ccc;font-size:11px;}"
        )
        right_lay.addWidget(self._cb_detail_nodes, 1)

        # 操作按钮区
        self._cb_action_bar = QHBoxLayout()
        self._cb_action_bar.setSpacing(8)

        self._cb_btn_install = QPushButton("📥 安装")
        self._cb_btn_install.setStyleSheet(self._btn_primary_style())
        self._cb_btn_install.clicked.connect(self._install_canvas_plugin)
        self._cb_action_bar.addWidget(self._cb_btn_install)

        self._cb_btn_toggle = QPushButton("✅ 启用")
        self._cb_btn_toggle.setStyleSheet(
            "QPushButton{background:#4caf50;color:#fff;border:none;border-radius:6px;"
            "padding:7px 14px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{opacity:0.85;}"
            "QPushButton:disabled{background:#3a3a3a;color:#666;}"
        )
        self._cb_btn_toggle.clicked.connect(self._toggle_canvas_plugin)
        self._cb_action_bar.addWidget(self._cb_btn_toggle)

        self._cb_btn_uninstall = QPushButton("🗑️ 卸载")
        self._cb_btn_uninstall.setStyleSheet(self._btn_danger_style())
        self._cb_btn_uninstall.clicked.connect(self._uninstall_canvas_plugin)
        self._cb_action_bar.addWidget(self._cb_btn_uninstall)

        self._cb_action_bar.addStretch()
        right_lay.addLayout(self._cb_action_bar)

        layout.addWidget(right, 1)

        # 状态变量
        self._cb_selected_plugin: Optional[Dict[str, Any]] = None
        self._cb_current_list = "registry"  # registry | installed

        self._refresh_canvas_plugins()
        return container

    def _switch_cb_list(self, list_type: str):
        """切换注册表/已安装列表"""
        self._cb_current_list = list_type
        self._cb_tab_registry.setChecked(list_type == "registry")
        self._cb_tab_registry.setStyleSheet(self._filter_btn_style(list_type == "registry"))
        self._cb_tab_installed.setChecked(list_type == "installed")
        self._cb_tab_installed.setStyleSheet(self._filter_btn_style(list_type == "installed"))
        self._refresh_canvas_plugins()

    def _refresh_canvas_plugins(self):
        """刷新画布节点插件列表"""
        self._cb_list.clear()
        search = self._cb_search.text().strip().lower() if hasattr(self, "_cb_search") else ""

        if self._cb_current_list == "registry":
            items = self._cb_plugins_registry
        else:
            items = self._cb_plugins_load() or []

        for p in items:
            name = str(p.get("name") or p.get("id") or "")
            desc = str(p.get("description") or "")
            if search and search not in name.lower() and search not in desc.lower():
                continue
            icon = str(p.get("nodes", [{}])[0].get("icon", "🔌")) if p.get("nodes") else "🔌"
            installed_badge = " ✅" if self._is_cb_plugin_installed(p.get("id", "")) else ""
            official_badge = " 🏛️" if p.get("official") else ""
            item_text = f"{icon} {name}{official_badge}{installed_badge}\n   v{p.get('version', '0.0.0')} — {desc[:60]}"
            q_item = QListWidgetItem(item_text)
            q_item.setData(Qt.ItemDataRole.UserRole, p)
            self._cb_list.addItem(q_item)

        if self._cb_list.count() == 0:
            empty = QListWidgetItem("（暂无内容）")
            empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            empty.setForeground(Qt.GlobalColor.gray)
            self._cb_list.addItem(empty)

    def _is_cb_plugin_installed(self, plugin_id: str) -> bool:
        """检查插件是否已安装"""
        if not plugin_id:
            return False
        installed = self._cb_plugins_load() or []
        return any(p.get("id") == plugin_id for p in installed)

    def _on_canvas_plugin_selected(self, q_item: QListWidgetItem):
        """选中左侧列表项 → 刷新右侧详情"""
        plugin = q_item.data(Qt.ItemDataRole.UserRole)
        if not plugin:
            self._cb_selected_plugin = None
            return

        self._cb_selected_plugin = plugin

        icon = "🔌"
        nodes = plugin.get("nodes") or []
        if nodes:
            icon = str(nodes[0].get("icon", "🔌"))
        self._cb_detail_icon.setText(icon)
        self._cb_detail_name.setText(str(plugin.get("name") or plugin.get("id") or "Unknown"))
        self._cb_detail_version.setText(f"版本: {plugin.get('version', '0.0.0')}")
        self._cb_detail_desc.setText(str(plugin.get("description") or ""))

        badge_text = "🏛️ 官方" if plugin.get("official") else "🌐 社区"
        self._cb_detail_badge.setText(badge_text)
        self._cb_detail_badge.setVisible(True)

        # 节点列表
        self._cb_detail_nodes.clear()
        for n in nodes:
            t = str(n.get("title") or n.get("type") or "节点")
            ic = str(n.get("icon", "⬜"))
            self._cb_detail_nodes.addItem(f"{ic}  {t}")

        # 按钮状态
        installed = self._is_cb_plugin_installed(plugin.get("id", ""))
        self._cb_btn_install.setEnabled(not installed)
        self._cb_btn_toggle.setEnabled(installed)
        self._cb_btn_uninstall.setEnabled(installed)

        if installed:
            manifest = self._cb_plugins_load() or []
            manifest_entry = next((m for m in manifest if m.get("id") == plugin.get("id")), None)
            enabled = bool(manifest_entry.get("enabled", True)) if manifest_entry else True
            self._cb_btn_toggle.setText("🚫 禁用" if enabled else "✅ 启用")
            self._cb_btn_toggle.setStyleSheet(
                ("QPushButton{background:#555" if enabled else "QPushButton{background:#4caf50") +
                ";color:#fff;border:none;border-radius:6px;padding:7px 14px;font-size:11px;font-weight:600;}"
                "QPushButton:hover{opacity:0.85;}"
            )

    def _install_canvas_plugin(self):
        """安装画布节点插件 → 调 Qt 端 manifest + 前端 fetch 激活"""
        p = self._cb_selected_plugin
        if not p:
            return
        plugin_id = str(p.get("id") or "")
        if not plugin_id:
            return

        # 1) Qt 端持久化
        try:
            self._cb_plugins_upsert(
                plugin_id,
                name=str(p.get("name") or plugin_id),
                version=str(p.get("version") or "0.0.0"),
                description=str(p.get("description") or ""),
                url=str(p.get("url") or ""),
                nodes=p.get("nodes") or [],
                official=bool(p.get("official", False)),
                enabled=True,
            )
        except Exception as e:
            logger.warning("Qt 端持久化插件失败: %s", e)

        # 2) 通知前端（如果画布 bridge 正在运行）
        self._notify_canvas_plugin_change("install", plugin_id)

        # 3) UI 反馈
        self._set_status(f"✅ 已安装 {p.get('name')}")
        self._refresh_canvas_plugins()
        # 如果当前在注册表列表，刷新后仍然选中
        self._cb_list.setCurrentRow(self._cb_list.count() - 1)

    def _toggle_canvas_plugin(self):
        """切换启用/禁用"""
        p = self._cb_selected_plugin
        if not p:
            return
        plugin_id = str(p.get("id") or "")
        manifest = self._cb_plugins_load() or []
        entry = next((m for m in manifest if m.get("id") == plugin_id), None)
        current_enabled = bool(entry.get("enabled", True)) if entry else True
        new_enabled = not current_enabled

        try:
            self._cb_plugins_toggle(plugin_id, new_enabled)
        except Exception as e:
            logger.warning("切换插件启用失败: %s", e)

        self._notify_canvas_plugin_change("toggle", plugin_id, new_enabled)
        self._set_status(f"{'✅ 已启用' if new_enabled else '🚫 已禁用'} {p.get('name')}")
        # 重新选中触发详情刷新
        row = self._cb_list.currentRow()
        self._refresh_canvas_plugins()
        self._cb_list.setCurrentRow(row)

    def _uninstall_canvas_plugin(self):
        """卸载"""
        p = self._cb_selected_plugin
        if not p:
            return
        reply = QMessageBox.question(
            self, "确认卸载",
            f"确定要卸载「{p.get('name')}」吗？\n"
            "画布中已存在的该类型节点将变为只读（需要手动删除）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        plugin_id = str(p.get("id") or "")
        try:
            self._cb_plugins_remove(plugin_id)
        except Exception as e:
            logger.warning("卸载插件失败: %s", e)

        self._notify_canvas_plugin_change("uninstall", plugin_id)
        self._set_status(f"🗑️ 已卸载 {p.get('name')}")
        self._refresh_canvas_plugins()
        self._cb_selected_plugin = None
        self._cb_detail_name.setText("选择左侧插件查看详情")
        self._cb_detail_desc.setText("")
        self._cb_detail_icon.setText("🔌")
        self._cb_detail_nodes.clear()

    def _notify_canvas_plugin_change(self, action: str, plugin_id: str, extra=None):
        """通过 canvas_bridge HTTP 通知前端刷新插件状态"""
        try:
            import urllib.request
            import urllib.parse
            from app.core.canvas_bridge import DEFAULT_PORT, session_token
            url = f"http://127.0.0.1:{DEFAULT_PORT}/host/plugins/{action}"
            payload = json.dumps({"id": plugin_id, "enabled": extra}).encode("utf-8")
            req = urllib.request.Request(
                url + "?token=" + urllib.parse.quote(session_token()),
                data=payload if action != "uninstall" else None,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # 非阻塞：bridge 可能没启动
            urllib.request.urlopen(req, timeout=2)
        except Exception as e:
            logger.debug("通知前端插件变更失败（bridge 可能未启动）: %s", e)

    def _open_url(self, url: str, title: str = ""):
        """打开外部链接"""
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            QMessageBox.information(
                self, title or "链接", f"请在浏览器中访问:\n{url}"
            )

    # ═══════════════════════════════════════════════════════════════
    # 刷新与数据更新
    # ═══════════════════════════════════════════════════════════════

    def _refresh_all(self):
        """刷新所有内容"""
        self._refresh_installed()
        self._refresh_skill_list()
        self._update_connected_mcp_list()
        self._set_status("已刷新")

    def _refresh_installed(self):
        """刷新已安装拓展列表（合并 ExtensionsRegistry + PluginManager + PluginStore）"""
        # 清空现有列表
        while self._installed_layout.count():
            item = self._installed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        current_filter = getattr(self, '_current_filter', 'all')
        has_any = False

        # ── 1. ExtensionsRegistry 中的扩展（Plugin/Skill/MCP 统一接口）──
        extensions = []
        if self._registry:
            extensions = self._registry.list_all()

        if current_filter in ('all', 'plugin'):
            for ext in extensions:
                if current_filter == 'plugin' and ext.extension_type.value != 'plugin':
                    continue
                card = self._create_extension_card(ext)
                self._installed_layout.addWidget(card)
                has_any = True

        if current_filter in ('all', 'skill'):
            for ext in extensions:
                if ext.extension_type.value != 'skill':
                    continue
                card = self._create_extension_card(ext)
                self._installed_layout.addWidget(card)
                has_any = True

        if current_filter in ('all', 'mcp'):
            for ext in extensions:
                if ext.extension_type.value != 'mcp_server':
                    continue
                card = self._create_extension_card(ext)
                self._installed_layout.addWidget(card)
                has_any = True

        # ── 2. PluginManager 加载的旧插件（兼容旧插件中心）──
        if current_filter in ('all', 'plugin') and self._plugin_mgr:
            mgr_names = set()
            # 收集 PluginStore 已安装项（按 item_id 去重）
            store_installed = {}
            if self._store:
                try:
                    for it in self._store.get_items(installed_only=True):
                        store_installed[it.id] = it
                except Exception as e:
                    logger.debug("加载 PluginStore 已安装项失败: %s", e)

            for p in self._plugin_mgr.list_plugins():
                name = getattr(p, "name", "未知插件")
                mgr_names.add(name)
                enabled = getattr(p, "enabled", False)
                # 特殊插件直接绑定专用方法
                special_map = {
                    "AI特效制作": self._open_ai_effects_studio,
                }
                is_special = name in special_map
                has_ui = is_special or self._plugin_offers_widget_ui(p)
                if enabled and is_special:
                    btn_text = "打开界面"
                    btn_color = "#1e6bde"
                    callback = special_map[name]
                elif enabled and has_ui:
                    btn_text = "打开界面"
                    btn_color = "#1e6bde"
                    callback = lambda checked, n=name: self._open_plugin_ui(n)
                else:
                    btn_text = "已启用" if enabled else "已禁用"
                    btn_color = "#4caf50" if enabled else "#555"
                    callback = lambda checked, n=name: self._toggle_legacy_plugin(n)
                card = self._create_legacy_plugin_card(
                    "🧩", name,
                    getattr(p, "description", ""),
                    getattr(p, "version", "v1.0.0"),
                    btn_text, btn_color, callback, enabled
                )
                self._installed_layout.addWidget(card)
                has_any = True

            # 追加 PluginStore 已安装但未被 PluginManager 加载的项目
            for item_id, it in store_installed.items():
                if it.name not in mgr_names:
                    card = self._create_legacy_plugin_card(
                        "🧩", it.name, it.description, it.version,
                        "已启用", "#4caf50",
                        lambda checked, iid=item_id: self._uninstall_store_item(iid),
                        True
                    )
                    self._installed_layout.addWidget(card)
                    has_any = True
                    mgr_names.add(it.name)

            # 加载失败提示
            if not mgr_names and hasattr(self._plugin_mgr, "format_load_errors"):
                load_hint = self._plugin_mgr.format_load_errors()
                if load_hint:
                    tip = QLabel("插件加载失败（非空目录）：\n" + load_hint)
                    tip.setWordWrap(True)
                    tip.setStyleSheet("color:#ef4444;font-size:11px;padding:8px;")
                    self._installed_layout.addWidget(tip)

        # ── 3. 空状态提示 ──
        if not has_any:
            empty_label = QLabel("暂无已安装的拓展\n\n可前往「拓展商店」安装，或点击顶部「导入」加载本地插件")
            empty_label.setStyleSheet("color:#666;font-size:12px;padding:40px;")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._installed_layout.addWidget(empty_label)

        # 添加弹性空间
        self._installed_layout.addStretch()

    def _create_extension_card(self, ext) -> QFrame:
        """创建拓展卡片"""
        card = QFrame()
        card.setStyleSheet(self._create_card_style())

        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # 类型图标
        type_icons = {
            'plugin': '🧩',
            'skill': '⚡',
            'mcp_server': '🔌',
        }
        type_icon = type_icons.get(ext.extension_type.value, '📦')

        icon_label = QLabel(type_icon)
        icon_label.setStyleSheet("font-size:24px;")
        layout.addWidget(icon_label)

        # 信息
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        name_row = QHBoxLayout()
        name_label = QLabel(ext.info.name)
        name_label.setStyleSheet("color:#fff;font-size:13px;font-weight:bold;")
        name_row.addWidget(name_label)

        version_label = QLabel(f"v{ext.info.version}")
        version_label.setStyleSheet("color:#666;font-size:10px;")
        name_row.addWidget(version_label)
        name_row.addStretch()

        # 状态标签
        if ext.is_enabled:
            status_label = QLabel("● 已启用")
            status_label.setStyleSheet("color:#4caf50;font-size:10px;")
        else:
            status_label = QLabel("○ 已禁用")
            status_label.setStyleSheet("color:#666;font-size:10px;")
        name_row.addWidget(status_label)

        info_layout.addLayout(name_row)

        if ext.info.description:
            desc_label = QLabel(ext.info.description)
            desc_label.setStyleSheet("color:#888;font-size:11px;")
            desc_label.setWordWrap(True)
            info_layout.addWidget(desc_label)

        # 工具数量
        tools = ext.get_tools()
        if tools:
            tools_label = QLabel(f"可用工具: {len(tools)} 个")
            tools_label.setStyleSheet("color:#7c3aed;font-size:10px;")
            info_layout.addWidget(tools_label)

        layout.addLayout(info_layout, 1)

        # 操作按钮
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(6)

        if ext.is_enabled:
            toggle_btn = QPushButton("禁用")
            toggle_btn.setStyleSheet(self._btn_danger_style())
            toggle_btn.clicked.connect(lambda _, e=ext: self._toggle_extension(e))
            btn_layout.addWidget(toggle_btn)

            run_btn = QPushButton("运行")
            run_btn.setStyleSheet(self._btn_primary_style())
            run_btn.clicked.connect(lambda _, e=ext: self._run_extension(e))
            btn_layout.addWidget(run_btn)
        else:
            enable_btn = QPushButton("启用")
            enable_btn.setStyleSheet(self._btn_primary_style())
            enable_btn.clicked.connect(lambda _, e=ext: self._toggle_extension(e))
            btn_layout.addWidget(enable_btn)

        layout.addLayout(btn_layout)

        return card

    # ═══════════════════════════════════════════════════════════════
    # 旧插件兼容方法（从 plugins_module.py 迁移，保持功能不丢失）
    # ═══════════════════════════════════════════════════════════════

    def _create_legacy_plugin_card(self, icon, name, detail, extra, btn_text,
                                    btn_color, callback, enabled=True) -> QFrame:
        """创建旧风格插件卡片（兼容 PluginManager 插件）"""
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#1a1a1a;border:1px solid #2a2a2a;"
            "border-radius:8px;padding:12px;margin:4px 0;}"
            + ("opacity:0.6;" if not enabled else "")
        )
        cl = QHBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(10)

        ic = QLabel(icon)
        ic.setStyleSheet("font-size:24px;")
        ic.setFixedWidth(32)
        cl.addWidget(ic)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        nm = QLabel(name)
        nm.setStyleSheet("color:#fff;font-size:13px;font-weight:bold;")
        mid.addWidget(nm)
        dt = QLabel(detail)
        dt.setStyleSheet("color:#888;font-size:11px;")
        dt.setWordWrap(True)
        mid.addWidget(dt)
        cl.addLayout(mid, 1)

        ex = QLabel(extra)
        ex.setStyleSheet("color:#666;font-size:10px;")
        ex.setFixedWidth(60)
        ex.setAlignment(Qt.AlignmentFlag.AlignRight)
        cl.addWidget(ex)

        btn = QPushButton(btn_text)
        btn.setStyleSheet(
            f"QPushButton{{background:{btn_color};color:#fff;border:none;"
            f"border-radius:6px;padding:7px 14px;font-size:11px;font-weight:600;}}"
            f"QPushButton:hover{{opacity:0.85;}}"
        )
        btn.clicked.connect(callback)
        cl.addWidget(btn)

        return card

    def _plugin_offers_widget_ui(self, plugin) -> bool:
        """是否提供可嵌入的 QWidget 界面"""
        if plugin is None or not callable(getattr(plugin, "run", None)):
            return False
        cfg = {}
        if callable(getattr(plugin, "get_ui_config", None)):
            try:
                cfg = plugin.get_ui_config() or {}
            except Exception:
                cfg = {}
        wc = str(cfg.get("widget_class") or "")
        # 特效管线插件：通用打开会误调 run()→bool
        if callable(getattr(plugin, "apply_effect", None)):
            return False
        if wc:
            return True
        return hasattr(plugin, "_widget")

    def _find_plugin_by_name(self, name: str):
        """按显示名查找已加载插件实例"""
        if not self._plugin_mgr:
            return None
        plugins = self._plugin_mgr.list_plugins()
        if not plugins:
            return None
        if all(isinstance(p, str) for p in plugins):
            return None
        for p in plugins:
            if getattr(p, "name", None) == name:
                return p
        return None

    def _ensure_plugin_initialized(self, plugin) -> None:
        """打开 UI 前补一次 initialize"""
        if not callable(getattr(plugin, "initialize", None)):
            return
        ctx = getattr(plugin, "_context", None) or {}
        if not isinstance(ctx, dict):
            ctx = {}
        ctx = {**ctx, "parent_widget": self}
        need = (not getattr(plugin, "_initialized", False)) or (not hasattr(plugin, "_widget"))
        if need:
            plugin.initialize(ctx)
        else:
            try:
                plugin._context = ctx
            except Exception as e:
                logger.debug("更新插件 _context 失败: %s", e)

    def _toggle_legacy_plugin(self, name: str):
        """切换旧插件启用/禁用状态"""
        if self._plugin_mgr:
            for p in self._plugin_mgr.list_plugins():
                if getattr(p, "name", "") == name:
                    if getattr(p, "enabled", False):
                        self._plugin_mgr.disable_plugin(p.id)
                    else:
                        self._plugin_mgr.enable_plugin(p.id)
                    break
        self._refresh_installed()

    def _open_plugin_ui(self, name: str):
        """打开插件可视化界面"""
        plugin = self._find_plugin_by_name(name)
        if plugin is None:
            QMessageBox.warning(
                self, "无法打开", f"插件「{name}」未加载，请先在已安装列表中启用。"
            )
            return
        if not self._plugin_offers_widget_ui(plugin):
            QMessageBox.information(self, name, "该插件没有可视化界面（可能是特效/批处理插件）。")
            return
        try:
            self._ensure_plugin_initialized(plugin)
            result = plugin.run()
            if not isinstance(result, QWidget):
                QMessageBox.information(self, name, "插件已运行（无可视化界面）。")
                return
            dlg = QDialog(self)
            dlg.setWindowTitle(name)
            dlg.resize(1000, 720)
            dlg.setStyleSheet("QDialog{background:#121212;}")
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 0, 0)
            result.setParent(dlg)
            lay.addWidget(result, 1)
            result.show()


            def _detach(_result=0, w=result):
                try:
                    w.setParent(None)
                    w.hide()
                except Exception as e:
                    logger.debug("分离插件窗口失败: %s", e)

            dlg.finished.connect(_detach)
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "打开插件界面失败", str(e))

    def _uninstall_store_item(self, item_id: str):
        """卸载已安装的商店插件"""
        if not self._store:
            QMessageBox.warning(self, "卸载失败", "插件商店未就绪")
            return
        try:
            ok, msg = self._store.uninstall_item(item_id)
            if ok:
                QMessageBox.information(self, "卸载成功", "✅ 插件已卸载")
            else:
                QMessageBox.warning(self, "卸载失败", msg)
        except Exception as e:
            QMessageBox.warning(self, "卸载失败", str(e))
        self._refresh_installed()

    def _import_legacy_plugin(self):
        """导入本地插件文件（兼容旧插件中心）"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择插件文件", "", "插件文件 (*.py *.zip)"
        )
        if not file_path:
            return

        if self._plugin_mgr:
            try:
                if file_path.endswith(".py"):
                    import shutil
                    dest = os.path.join("plugins", os.path.basename(file_path))
                    os.makedirs("plugins", exist_ok=True)
                    shutil.copy2(file_path, dest)
                    self._plugin_mgr.add_plugin_dir("plugins")
                    self._plugin_mgr.load_plugins()
                    QMessageBox.information(self, "导入成功", f"✅ {os.path.basename(file_path)} 已加载")
                    self._refresh_installed()
                else:
                    QMessageBox.information(self, "导入", f"已选择: {os.path.basename(file_path)}\n\n.zip 包部署暂未实现，请手动解压。")
            except Exception as e:
                QMessageBox.warning(self, "导入失败", str(e))

    def _refresh_skill_list(self):
        """刷新技能列表（按 skill_category 过滤 + domain 标签显示）"""
        self._skill_list.clear()

        cat_filter = getattr(self, "_skill_cat_filter", "all")

        try:
            from .skill_engine import skill_registry
            try:
                from app.skills.external_loader import ensure_external_skills_registered
                ensure_external_skills_registered()
            except Exception as ext_e:
                logger.warning(f"加载外部 skill 失败: {ext_e}")
            if skill_registry:
                skills = skill_registry.list_all()
                for skill in skills:
                    # 分类过滤
                    if cat_filter != "all" and skill.skill_category != cat_filter:
                        continue
                    # domain 标签
                    domain_tag = "🎨" if getattr(skill, "skill_domain", "pipeline") == "canvas" else "⚙️"
                    item_text = f"{domain_tag} {skill.skill_name} ({skill.skill_category})"
                    item = QListWidgetItem(item_text)
                    item.setData(Qt.ItemDataRole.UserRole, skill)
                    self._skill_list.addItem(item)
        except Exception as e:
            logger.warning(f"加载技能列表失败: {e}")

        if self._skill_list.count() == 0:
            defaults = [
                ("自动剪辑", "自动分析视频并执行剪辑"),
                ("去水词", "自动识别并删除口语化表达"),
                ("智能字幕", "自动生成字幕并校对"),
                ("B-Roll 匹配", "自动插入相关辅助镜头"),
                ("自动卡点", "根据音乐节奏自动剪辑"),
            ]
            for name, desc in defaults:
                # 占位项也遵循分类过滤
                if cat_filter != "all":
                    continue
                item = QListWidgetItem(f"⚙️ {name}（占位，未接入）")
                item.setData(Qt.ItemDataRole.UserRole, {
                    "name": name,
                    "description": f"{desc}\n\n⚠️ 暂未接入真实技能引擎，此项目前仅作展示。",
                })
                self._skill_list.addItem(item)

    def _update_connected_mcp_list(self):
        """更新已连接 MCP 列表"""
        self._connected_list_widget.clear()

        for mcp_info in self._connected_mcps:
            item = QListWidgetItem(
                f"🔌 {mcp_info.get('name', 'Unknown')} - {mcp_info.get('state', '未知状态')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, mcp_info)
            self._connected_list_widget.addItem(item)

    # ═══════════════════════════════════════════════════════════════
    # 扩展操作
    # ═══════════════════════════════════════════════════════════════

    def _toggle_extension(self, ext):
        """切换扩展启用状态"""
        if ext.is_enabled:
            ext.disable()
            self._set_status(f"已禁用: {ext.info.name}")
        else:
            if ext.initialize():
                ext.enable()
                self._set_status(f"已启用: {ext.info.name}")
            else:
                self._set_status(f"启用失败: {ext.error}")
                QMessageBox.warning(
                    self, "启用失败",
                    f"无法启用拓展「{ext.info.name}」:\n{ext.error}"
                )

        self._refresh_installed()

    def _run_extension(self, ext):
        """运行扩展"""
        tools = ext.get_tools()
        if not tools:
            QMessageBox.information(
                self, "提示",
                f"拓展「{ext.info.name}」暂无可用工具"
            )
            return

        # 如果只有一个工具，直接运行
        if len(tools) == 1:
            result = ext.run(tools[0].id)
            if result is not None:
                self._set_status(f"运行成功: {ext.info.name}")
            else:
                self._set_status(f"运行失败: {ext.error}")
        else:
            # 显示工具选择对话框
            self._show_tool_selector(ext)

    def _show_tool_selector(self, ext):
        """显示工具选择对话框"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QPushButton

        dialog = QDialog(self)
        dialog.setWindowTitle(f"选择工具 - {ext.info.name}")
        dialog.resize(400, 500)
        dialog.setStyleSheet(
            "QDialog{background:#121212;}"
            "QLabel{color:#fff;font-size:13px;margin-bottom:8px;}"
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel(f"拓展「{ext.info.name}」的可用工具:")
        layout.addWidget(title)

        tool_list = QListWidget()
        tool_list.setStyleSheet(
            "QListWidget{background:#1a1a1a;border:1px solid #2a2a2a;"
            "border-radius:6px;}"
            "QListWidget::item{padding:8px;color:#fff;}"
        )

        for tool in ext.get_tools():
            item_text = f"⚡ {tool.name}\n{tool.description}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, tool.id)
            tool_list.addItem(item)

        layout.addWidget(tool_list)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(self._btn_secondary_style())
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        run_btn = QPushButton("运行")
        run_btn.setStyleSheet(self._btn_primary_style())

        def run_selected_tool():
            current = tool_list.currentItem()
            if current:
                tool_id = current.data(Qt.ItemDataRole.UserRole)
                result = ext.run(tool_id)
                if result is not None:
                    self._set_status(f"运行成功: {tool_id}")
                dialog.accept()

        run_btn.clicked.connect(run_selected_tool)
        btn_layout.addWidget(run_btn)

        layout.addLayout(btn_layout)

        dialog.exec()

    # ═══════════════════════════════════════════════════════════════
    # Skill 操作
    # ═══════════════════════════════════════════════════════════════

    def _on_skill_selected(self, item):
        """技能选中事件：显示详情 + 根据 domain 切换执行域 UI"""
        skill_data = item.data(Qt.ItemDataRole.UserRole)
        if not skill_data:
            return

        if hasattr(skill_data, "skill_name"):
            name = skill_data.skill_name
            desc = getattr(skill_data, "skill_description", "")
            category = getattr(skill_data, "skill_category", "")
            domain = getattr(skill_data, "skill_domain", "pipeline")
        elif isinstance(skill_data, dict):
            name = skill_data.get('name', '')
            desc = skill_data.get('description', '')
            category = ""
            domain = skill_data.get('skill_domain', 'pipeline')
        else:
            name = str(skill_data)
            desc = ""
            category = ""
            domain = "pipeline"

        domain_label = "🎨 画布域（AIGC 生成）" if domain == "canvas" else "⚙️ 后端执行域"
        hint = ("此技能属于 AIGC 生成域，建议前往 AI 画布使用专业的节点编辑面板。"
                if domain == "canvas"
                else "此技能在后端 SkillEngine 中执行，可在下方输入参数直接运行。")

        detail_text = f"【{name}】  [{category}]\n\n{desc}\n\n---\n执行域: {domain_label}\n💡 {hint}"
        self._skill_detail.setPlainText(detail_text)

        # 动态切换 domain 提示栏
        if hasattr(self, "_skill_domain_bar"):
            if domain == "canvas":
                self._skill_domain_bar.setText("🎨 此技能属于画布域，请前往 AI 画布使用节点生成")
                self._skill_domain_bar.setStyleSheet(
                    "padding:8px;border-radius:6px;font-size:12px;background:#1a3a2a;color:#22c55e;"
                )
                self._skill_domain_bar.setVisible(True)
            else:
                self._skill_domain_bar.setText("⚙️ 此技能在后端 SkillEngine 中执行")
                self._skill_domain_bar.setStyleSheet(
                    "padding:8px;border-radius:6px;font-size:12px;background:#1a2a3a;color:#60a5fa;"
                )
                self._skill_domain_bar.setVisible(True)

        # 动态切换执行 / 画布跳转区域
        if hasattr(self, "_skill_exec_group"):
            self._skill_exec_group.setVisible(domain != "canvas")
        if hasattr(self, "_skill_canvas_group"):
            self._skill_canvas_group.setVisible(domain == "canvas")

    def _run_selected_skill(self):
        """运行选中的技能（异步执行，主线程安全）

        修复两个隐藏 bug：
        1. 原实现只拼字符串，根本没调 skill_engine.execute_skill()
        2. 原用 skill_data.get('name') 在真实 Skill 实例上会 AttributeError
           （_refresh_skill_list 存的是 Skill 实例，不是 dict）

        现改为：子线程同步执行 + pyqtSignal 回主线程更新 UI
        """
        current = self._skill_list.currentItem()
        if not current:
            QMessageBox.warning(self, "警告", "请先选择一个技能")
            return

        skill_data = current.data(Qt.ItemDataRole.UserRole)
        # 兼容 Skill 实例和 dict（默认占位项是 dict）
        if hasattr(skill_data, "skill_id"):
            skill_id = skill_data.skill_id
            skill_name = skill_data.skill_name
        elif isinstance(skill_data, dict):
            skill_id = skill_data.get("skill_id") or skill_data.get("name")
            skill_name = skill_data.get("name", "")
        else:
            skill_id = None
            skill_name = str(skill_data)

        if not skill_id:
            QMessageBox.information(self, "提示", f"「{skill_name}」是占位项，暂未实现")
            return

        # 解析输入参数（JSON）
        inputs = {}
        input_text = self._skill_input.text().strip()
        if input_text:
            try:
                inputs = json.loads(input_text)
            except json.JSONDecodeError:
                QMessageBox.warning(self, "参数错误", "输入参数不是合法 JSON")
                return

        self._set_status(f"正在执行技能: {skill_name}")
        self._skill_output.setPlainText("执行中...")

        # 子线程同步执行（BaseModule 已注入 self._skill_engine 单例）
        import threading

        def _run_in_thread():
            try:
                result = self._skill_engine.execute_skill(
                    skill_id, inputs,
                    progress_callback=lambda p, m: self._skill_progress_signal.emit(p, m),
                    async_mode=False,
                )
                success = bool(result.get("success", False))
                outputs = result.get("outputs", {})
                # 格式化输出为可读文本
                try:
                    text = json.dumps(outputs, ensure_ascii=False, indent=2)
                except Exception:
                    text = str(outputs)
                self._skill_finished_signal.emit(success, text)
            except Exception as e:
                self._skill_finished_signal.emit(False, f"执行异常: {e}")

        threading.Thread(target=_run_in_thread, daemon=True).start()

    def _on_skill_progress_main(self, progress: int, message: str):
        """主线程槽：更新技能执行进度"""
        self._skill_output.setPlainText(f"[{progress}%] {message}")
        self._set_status(f"执行中: {progress}%")

    def _on_skill_finished_main(self, success: bool, result_text: str):
        """主线程槽：技能执行完成，更新输出"""
        prefix = "✅ 执行完成\n\n" if success else "❌ 执行失败\n\n"
        self._skill_output.setPlainText(prefix + result_text)
        self._set_status("完成" if success else "失败")

    def _jump_to_canvas(self):
        """跳转至 AI 画布（characters 模块）"""
        try:
            from .core import EventBus, EventType
            event_bus = EventBus.get_instance()
            event_bus.emit(
                EventType.MODULE_ACTIVATED,
                {"target": "characters", "hint": "从 Skill 工坊跳转，前往画布使用 AIGC 节点"},
            )
            self._set_status("已跳转至 AI 画布")
        except Exception as e:
            logger.error(f"跳转 AI 画布失败: {e}")
            QMessageBox.warning(self, "跳转失败", f"无法跳转至 AI 画布:\n{e}")

    def _download_blender_mcp(self):
        """后台线程运行 setup_blender_mcp.ps1，从 Git 下载 harveyxiacn/blender-mcp"""
        import subprocess
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))),
            "scripts", "setup_blender_mcp.ps1"
        )
        if not os.path.exists(script):
            QMessageBox.warning(self, "缺失脚本", f"未找到下载脚本:\n{script}")
            return

        self._set_status("正在从 Git 下载 blender-mcp...")
        import threading

        def _download_in_thread():
            try:
                result = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", script],
                    capture_output=True, text=True, timeout=180,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                ok = result.returncode == 0
                msg = result.stdout if ok else (result.stderr or result.stdout or "下载失败")
                self._blender_download_signal.emit(ok, msg)
            except Exception as e:
                self._blender_download_signal.emit(False, str(e))

        threading.Thread(target=_download_in_thread, daemon=True).start()

    def _on_blender_download_done(self, success: bool, message: str):
        """主线程槽：Blender MCP 下载完成提示"""
        if success:
            QMessageBox.information(
                self, "下载完成",
                f"blender-mcp 已下载到 thirdparty/blender/blender-mcp/\n\n{message}"
            )
            # 刷新已安装列表（下载按钮会因目录已存在而消失）
            self._refresh_installed()
            self._set_status("blender-mcp 下载完成")
        else:
            QMessageBox.warning(self, "下载失败", message)
            self._set_status("blender-mcp 下载失败")

    # ═══════════════════════════════════════════════════════════════
    # MCP 操作
    # ═══════════════════════════════════════════════════════════════

    def _connect_mcp_preset(self, preset: Dict):
        """连接 MCP 预设服务"""
        if not self._mcp_client:
            QMessageBox.warning(self, "警告", "MCP 客户端未初始化")
            return

        config = {
            "type": "stdio",
            "name": preset.get("name", "Unknown"),
            "command": preset.get("command", ""),
            "args": preset.get("args", []),
            # 外部 MCP（如 videocut）的 cwd 字段：已被 mcp_client 解析为绝对路径，
            # 传给 _connect_stdio → subprocess.Popen(cwd=...) 确保子进程工作目录正确
            "cwd": preset.get("cwd"),
        }

        self._set_status(f"正在连接 {config['name']}...")

        # 在后台线程连接
        import threading

        def do_connect():
            success = self._mcp_client.connect(config)
            if success:
                # 获取工具列表
                tools = self._mcp_client.list_tools()
                mcp_info = {
                    "name": config["name"],
                    "state": "已连接",
                    "tools": tools,
                    "config": config,
                }
                self._connected_mcps.append(mcp_info)

                # 更新 UI
                self._update_connected_mcp_list()
                self._show_mcp_tools(mcp_info)
                self._set_status(f"已连接: {config['name']} ({len(tools)} 个工具)")
            else:
                error = self._mcp_client.last_error or "未知错误"
                self._set_status(f"连接失败: {error}")
                # ★ 自动连接（Blender 默认配置）失败时不弹窗打断——只在状态栏如实说；
                #   用户手动点击连接才弹详细错误。
                if not preset.get("_auto"):
                    from PyQt6.QtWidgets import QMessageBox as QMB
                    QMB.warning(self, "连接失败", f"无法连接到「{config['name']}」:\n{error}")

        thread = threading.Thread(target=do_connect, daemon=True)
        thread.start()

    def _auto_connect_blender_preset(self):
        """默认配置 Blender MCP（用户需求，V4.46.19）：首次进 MCP 页自动连接。

        实现已抽到 ``mcp_preset_autoconnect.py``（单文件规模守卫要求）；
        幂等由调用方 ``_blender_autoconnect_done`` 保证。
        """
        auto_connect_blender_preset(self)

    def _manual_connect_mcp(self):
        """手动连接 MCP Server"""
        name = self._mcp_name_input.text().strip()
        command = self._mcp_command_input.text().strip()
        args_str = self._mcp_args_input.text().strip()

        if not name or not command:
            QMessageBox.warning(self, "警告", "请填写名称和命令")
            return

        args = args_str.split() if args_str else []

        preset = {
            "name": name,
            "command": command,
            "args": args,
        }
        self._connect_mcp_preset(preset)

    def _show_mcp_tools(self, mcp_info: Dict):
        """显示 MCP 可用工具"""
        tools = mcp_info.get("tools", [])
        if tools:
            text = f"【{mcp_info['name']}】可用工具 ({len(tools)} 个):\n\n"
            for i, tool in enumerate(tools, 1):
                text += f"{i}. {tool.get('name', 'Unknown')}\n"
                text += f"   {tool.get('description', '')[:80]}\n\n"
            self._mcp_tools_detail.setPlainText(text)

    # ═══════════════════════════════════════════════════════════════
    # 其他操作
    # ═══════════════════════════════════════════════════════════════

    def _import_extension(self):
        """导入拓展（优先走旧插件管理器，兼容 .py/.zip 插件文件）"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择拓展文件", "",
            "Python 文件 (*.py);;ZIP 包 (*.zip);;所有文件 (*.*)"
        )
        if not file_path:
            return

        self._set_status(f"正在导入: {file_path}")

        # 优先走旧插件管理器导入（兼容已有插件生态）
        if self._plugin_mgr and file_path.endswith(".py"):
            try:
                import shutil
                dest = os.path.join("plugins", os.path.basename(file_path))
                os.makedirs("plugins", exist_ok=True)
                shutil.copy2(file_path, dest)
                self._plugin_mgr.add_plugin_dir("plugins")
                self._plugin_mgr.load_plugins()
                QMessageBox.information(self, "导入成功", f"✅ {os.path.basename(file_path)} 已加载")
                self._refresh_installed()
                self._set_status(f"导入成功: {os.path.basename(file_path)}")
                return
            except Exception as e:
                logger.warning(f"旧插件导入失败，尝试新扩展导入: {e}")

        # 回退到新扩展导入逻辑
        self._install_extension_from_file(file_path)

    def _install_extension_from_file(self, file_path: str):
        """从文件安装拓展"""
        try:

            # 这里可以实现动态加载插件
            # 简化版本：直接注册为插件类型
            import importlib.util
            module_name = os.path.splitext(os.path.basename(file_path))[0]
            spec = importlib.util.spec_from_file_location(module_name, file_path)

            if spec:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # 查找 Plugin 类
                plugin_class = None
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and hasattr(attr, 'run'):
                        plugin_class = attr
                        break

                if plugin_class:
                    plugin_instance = plugin_class()
                    from app.core.extension_base import PluginExtension
                    ext = PluginExtension(plugin_instance)
                    if self._registry:
                        self._registry.register(ext)
                        ext.initialize()
                        self._refresh_installed()
                        self._set_status(f"导入成功: {ext.info.name}")
                    else:
                        self._set_status("导入失败: 注册表未初始化")
                else:
                    self._set_status("导入失败: 未找到有效的插件类")
        except Exception as e:
            logger.error(f"导入拓展失败: {e}")
            self._set_status(f"导入失败: {e}")
            QMessageBox.warning(self, "导入失败", f"无法导入:\n{e}")

    def _set_status(self, message: str):
        """更新状态显示"""
        if hasattr(self, '_status_label'):
            self._status_label.setText(message)

    def _unload(self):
        """模块卸载时清理"""
        # 断开所有 MCP 连接
        if self._mcp_client:
            self._mcp_client.disconnect()
        self._connected_mcps.clear()
