'''
模型管理主模块 (ModelManagementModule)
========================================
整合本地大模型 (Ollama)、云端 API
卡片式列表布局，点击展开配置详情，一键切换激活

子模块:
  model_config.py      — 共享配置/常量
  model_card.py        — 模型卡片组件
  openclaw_config.py   — OpenClaw 运营配置
  skill_interface.py   — AI技能管理界面
'''

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QComboBox, QLineEdit,
    QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QStatusBar, QTabWidget, QDialog, QFormLayout,
    QDialogButtonBox, QApplication
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from typing import Optional, Dict, List, Any
import logging
import json
import os
import time

from .model_config import ModelConfig, PROVIDERS, CUSTOM_PROVIDERS_FILE, ACTIVE_PROVIDER_FILE
from .model_card import ModelCardWidget
from .openclaw_config import OpenClawConfigWidget
from .skill_interface import SkillInterfaceWidget

logger = logging.getLogger("AI短剧编辑器.model_mgmt")

class ModelManagementModule(QWidget):
    """模型管理模块 - 模型广场 + OpenClaw + 技能管理"""

    module_id: str = "models"
    module_name: str = "模型广场"
    module_icon: str = "🤖"

    def __init__(self):
        super().__init__()
        self._active_provider: str = self._load_active_provider()
        self._cards: Dict[str, ModelCardWidget] = {}
        self._custom_providers: Dict[str, dict[str, Any]] = self._load_custom_providers()
        self._init_ui()
        self._restore_active_state()

    def _load_custom_providers(self) -> Dict[str, dict[str, Any]]:
        try:
            if os.path.exists(CUSTOM_PROVIDERS_FILE):
                with open(CUSTOM_PROVIDERS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"加载自定义模型配置失败: {e}")
        return {}

    def _load_active_provider(self) -> str:
        try:
            if os.path.exists(ACTIVE_PROVIDER_FILE):
                with open(ACTIVE_PROVIDER_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("active_provider", "")
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"加载活跃模型配置失败: {e}")
        return ""

    def _save_active_provider(self):
        try:
            os.makedirs(os.path.dirname(ACTIVE_PROVIDER_FILE), exist_ok=True)
            with open(ACTIVE_PROVIDER_FILE, 'w', encoding='utf-8') as f:
                json.dump({"active_provider": self._active_provider}, f)
        except (OSError, ValueError) as e:
            logger.warning(f"保存活跃模型配置失败: {e}")

    def _restore_active_state(self):
        if not self._active_provider:
            return
        if self._active_provider in self._cards:
            self._cards[self._active_provider].set_active(True)
            provider_name = (PROVIDERS.get(self._active_provider) or
                           self._custom_providers.get(self._active_provider) or {}).get("name", self._active_provider)
            self._active_label.setText(f"🟢 当前激活: {provider_name}")
            self._active_label.setStyleSheet("font-size: 12px; color: #22c55e; font-weight: 600;")

    def _save_custom_providers(self):
        try:
            os.makedirs(os.path.dirname(CUSTOM_PROVIDERS_FILE), exist_ok=True)
            with open(CUSTOM_PROVIDERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._custom_providers, f, ensure_ascii=False, indent=2)
        except (OSError, ValueError) as e:
            self._status_bar.showMessage(f"保存自定义模型失败: {e}")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)

        title = QLabel(" 模型广场")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._active_label = QLabel("未选择激活模型")
        self._active_label.setStyleSheet("font-size: 12px; color: #888888;")
        header_layout.addWidget(self._active_label)

        header_layout.addSpacing(20)

        save_all_btn = QPushButton("💾 保存全部")
        save_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #22c55e; color: white; border: none;
                border-radius: 6px; padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #16a34a; }
        """)
        save_all_btn.clicked.connect(self._save_all_configs)
        header_layout.addWidget(save_all_btn)

        layout.addWidget(header)

        self._main_tabs = QTabWidget()
        self._main_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none; background-color: #0a0a0a;
            }
            QTabBar::tab {
                background-color: #121212; color: #888888; border: none;
                padding: 10px 20px; font-size: 13px;
                border-bottom: 2px solid transparent;
            }
            QTabBar::tab:selected {
                color: #ffffff; border-bottom: 2px solid #1e6bde;
            }
            QTabBar::tab:hover:!selected {
                color: #cccccc; background-color: #1a1a1a;
            }
        """)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { background-color: #0a0a0a; border: none; }
            QScrollBar:vertical {
                background: #0a0a0a; width: 8px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #333333; border-radius: 4px; min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: #555555; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        container = QWidget()
        container.setStyleSheet("background-color: #0a0a0a;")
        self._cards_layout = QVBoxLayout(container)
        self._cards_layout.setContentsMargins(16, 16, 16, 16)
        self._cards_layout.setSpacing(10)

        for provider_id, provider_info in PROVIDERS.items():
            card = ModelCardWidget(provider_id, provider_info)
            card.activate_requested.connect(self._on_activate_provider)
            card.config_saved.connect(self._on_config_saved)
            self._cards[provider_id] = card
            self._cards_layout.addWidget(card)
        
        for provider_id, provider_info in self._custom_providers.items():
            card = ModelCardWidget(provider_id, provider_info)
            card.activate_requested.connect(self._on_activate_provider)
            card.config_saved.connect(self._on_config_saved)
            self._cards[provider_id] = card
            self._cards_layout.addWidget(card)
        
        self._cards_layout.addStretch()
        
        add_custom_btn = QPushButton("➕ 添加自定义模型")
        add_custom_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #1e6bde; border: 2px dashed #1e6bde;
                border-radius: 10px; padding: 12px; font-size: 13px; font-weight: 600;
            }
            QPushButton:hover { background: #1a1a2e; }
        """)
        add_custom_btn.clicked.connect(self._add_custom_provider_dialog)
        self._cards_layout.addWidget(add_custom_btn)
        scroll.setWidget(container)

        self._main_tabs.addTab(scroll, "🤖 模型广场")
        self._main_tabs.addTab(OpenClawConfigWidget(), " OpenClaw")
        self._main_tabs.addTab(SkillInterfaceWidget(), "🧩 技能管理")
        self._main_tabs.addTab(self._create_usage_tab(), "📊 用量统计")
        self._main_tabs.addTab(self._create_benchmark_tab(), "⏱️ 性能对比")

        layout.addWidget(self._main_tabs)

        self._status_bar = QStatusBar()
        self._status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #0d0d0d; color: #666666;
                border-top: 1px solid #252525; padding: 6px 12px; font-size: 12px;
            }
        """)
        self._status_bar.showMessage("就绪 - 点击卡片展开配置，点击圆形按钮激活模型")
        layout.addWidget(self._status_bar)

    def _create_usage_tab(self) -> QWidget:
        """AI调用用量统计面板"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header = QLabel("📊 AI 调用用量统计")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)

        desc = QLabel("实时追踪各AI模型的调用次数、Token消耗和费用估算")
        desc.setStyleSheet("font-size: 13px; color: #808080;")
        layout.addWidget(desc)

        # 汇总区
        summary_frame = QFrame()
        summary_frame.setStyleSheet("background-color: #121212; border: 1px solid #252525; border-radius: 10px; padding: 15px;")
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setSpacing(30)

        for icon, label in [("🔢", "总调用"), ("✅", "成功"), ("❌", "失败"), ("💎", "Token"), ("💰", "费用¥")]:
            box = QVBoxLayout()
            box.setSpacing(4)
            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet("font-size: 18px; background: transparent;")
            box.addWidget(icon_lbl)
            val = QLabel("0")
            val.setStyleSheet("font-size: 22px; font-weight: bold; color: #ffffff; background: transparent;")
            val.setObjectName(f"summary_{label}")
            box.addWidget(val)
            tag = QLabel(label)
            tag.setStyleSheet("font-size: 11px; color: #808080; background: transparent;")
            box.addWidget(tag)
            summary_layout.addLayout(box)

        summary_layout.addStretch()
        layout.addWidget(summary_frame)

        # Provider 统计表格
        self._usage_table = QTableWidget()
        self._usage_table.setColumnCount(7)
        self._usage_table.setHorizontalHeaderLabels(["Provider", "调用次数", "成功率", "失败", "Token数", "费用(¥)", "状态"])
        self._usage_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 7):
            self._usage_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._usage_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a; border: 1px solid #333333; border-radius: 8px;
                color: #ffffff; gridline-color: #2a2a2a;
            }
            QTableWidget::item { padding: 8px; }
            QTableWidget::item:selected { background-color: #1e6bde; }
            QHeaderView::section {
                background-color: #2a2a2a; color: white; padding: 10px; border: none;
                font-weight: bold;
            }
        """)
        layout.addWidget(self._usage_table, 1)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        refresh_btn = QPushButton("🔄 刷新统计")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde; color: white; border: none;
                border-radius: 6px; padding: 8px 20px; font-size: 13px;
            }
            QPushButton:hover { background-color: #2a7bef; }
        """)
        refresh_btn.clicked.connect(self._refresh_usage)
        btn_row.addWidget(refresh_btn)

        reset_btn = QPushButton("🗑️ 重置统计")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #333333; color: #ffffff; border: none;
                border-radius: 6px; padding: 8px 20px; font-size: 13px;
            }
            QPushButton:hover { background-color: #ef4444; }
        """)
        reset_btn.clicked.connect(self._reset_usage)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        return widget

    def _refresh_usage(self):
        """刷新用量统计显示"""
        try:
            from app.core.ai_engine import ai_engine
            stats = ai_engine.get_stats()

            self._usage_table.setRowCount(0)
            total_calls = total_success = total_failed = total_tokens = total_cost = 0.0

            for provider, s in sorted(stats.items()):
                row = self._usage_table.rowCount()
                self._usage_table.insertRow(row)

                self._usage_table.setItem(row, 0, QTableWidgetItem(provider))
                self._usage_table.setItem(row, 1, QTableWidgetItem(str(s['total_calls'])))
                self._usage_table.setItem(row, 2, QTableWidgetItem(f"{s['success_rate']}%"))

                fail_item = QTableWidgetItem(str(s['failed_calls']))
                if s['failed_calls'] > 0:
                    fail_item.setForeground(QColor("#ef4444"))
                self._usage_table.setItem(row, 3, fail_item)

                self._usage_table.setItem(row, 4, QTableWidgetItem(f"{s['total_tokens']:,}"))
                self._usage_table.setItem(row, 5, QTableWidgetItem(f"¥{s['total_cost_rmb']:.4f}"))

                status = "⛔ 熔断" if s.get('circuit_open') else "🟢 正常"
                status_item = QTableWidgetItem(status)
                if s.get('circuit_open'):
                    status_item.setForeground(QColor("#f59e0b"))
                else:
                    status_item.setForeground(QColor("#22c55e"))
                self._usage_table.setItem(row, 6, status_item)

                total_calls += s['total_calls']
                total_success += s['success_calls']
                total_failed += s['failed_calls']
                total_tokens += s['total_tokens']
                total_cost += s['total_cost_rmb']

            # 更新汇总
            parent = self._usage_table.parent().parent()
            if parent:
                for child in parent.findChildren(QLabel):
                    name = child.objectName()
                    if name == "summary_总调用":
                        child.setText(str(total_calls))
                    elif name == "summary_成功":
                        child.setText(str(total_success))
                    elif name == "summary_失败":
                        child.setText(str(total_failed))
                    elif name == "summary_Token":
                        child.setText(f"{total_tokens:,}")
                    elif name == "summary_费用¥":
                        child.setText(f"¥{total_cost:.2f}")

            if not stats:
                self._usage_table.setRowCount(1)
                self._usage_table.setItem(0, 0, QTableWidgetItem("暂无AI调用记录"))
                self._usage_table.setSpan(0, 0, 1, 7)
        except Exception as e:
            logger.warning(f"刷新用量统计失败: {e}")

    def _reset_usage(self):
        """重置用量统计"""
        reply = QMessageBox.question(
            self, "确认重置", "确定要清除所有AI调用统计吗？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from app.core.ai_engine import ai_engine
                ai_engine.reset_stats()
                self._refresh_usage()
                QMessageBox.information(self, "成功", "统计已重置")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"重置失败: {e}")

    def _create_benchmark_tab(self) -> QWidget:
        """模型性能对比面板 — 展示各 Provider 的响应速度/质量/成本等维度的基准信息"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header = QLabel("⏱️ 模型性能对比")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)

        desc = QLabel("展示各AI模型在响应速度、推理质量、价格等维度的参考数据（数据来源：公开Benchmark & 官方文档，实际表现因网络/负载而异）")
        desc.setStyleSheet("font-size: 13px; color: #808080;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Launcher row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        test_btn = QPushButton("🚀 速度测试")
        test_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde; color: white; border: none;
                border-radius: 6px; padding: 8px 18px; font-size: 13px; font-weight: 600;
            }
            QPushButton:hover { background-color: #2a7bef; }
        """)
        test_btn.clicked.connect(self._run_speed_test)
        btn_row.addWidget(test_btn)

        btn_row.addStretch()

        self._bench_loading = QLabel("")
        self._bench_loading.setStyleSheet("font-size: 12px; color: #f59e0b;")
        btn_row.addWidget(self._bench_loading)
        layout.addLayout(btn_row)

        # ── 对比表格 ──
        self._bench_table = QTableWidget()
        self._bench_table.setColumnCount(8)
        self._bench_table.setHorizontalHeaderLabels([
            "Provider", "模型", "响应速度", "推理质量", "价格($/1M tok)", "上下文窗口", "本地/云端", "综合评价"
        ])
        self._bench_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 8):
            self._bench_table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._bench_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a; border: 1px solid #333333; border-radius: 8px;
                color: #ffffff; gridline-color: #2a2a2a;
            }
            QTableWidget::item { padding: 8px; }
            QTableWidget::item:selected { background-color: #1e6bde; }
            QHeaderView::section {
                background-color: #2a2a2a; color: white; padding: 10px; border: none;
                font-weight: bold; font-size: 12px;
            }
        """)
        layout.addWidget(self._bench_table, 1)

        # 预填基准数据
        self._populate_benchmark_defaults()

        return widget

    def _populate_benchmark_defaults(self):
        """填充模型性能基准的默认参考数据"""
        self._bench_table.setRowCount(0)
        bench_data = [
            # (provider_display, model, speed, quality, price, context, local_cloud, overall)
            ("DeepSeek", "deepseek-chat", "⚡中等 (~2s)", "⭐⭐⭐⭐☆", "$0.14 / $0.28", "64K", "☁️ 云端", "性价比极高"),
            ("DeepSeek", "deepseek-reasoner", "🐢较慢 (~8s)", "⭐⭐⭐⭐⭐", "$0.55 / $2.19", "64K", "☁️ 云端", "深度推理王"),
            ("OpenAI", "gpt-4o", "⚡中等 (~2.5s)", "⭐⭐⭐⭐⭐", "$2.50 / $10.00", "128K", "☁️ 云端", "全能旗舰"),
            ("OpenAI", "gpt-4o-mini", "⚡快速 (~1s)", "⭐⭐⭐⭐☆", "$0.15 / $0.60", "128K", "☁️ 云端", "轻量高效"),
            ("Ollama 本地", "qwen2.5:7b", "⚡快速 (~0.8s)", "⭐⭐⭐☆☆", "免费 (本地)", "32K", "💻 本地", "零延迟零成本"),
            ("Ollama 本地", "llama3.1:8b", "⚡快速 (~0.7s)", "⭐⭐⭐⭐☆", "免费 (本地)", "128K", "💻 本地", "隐私安全"),
            ("豆包", "doubao-pro-32k", "⚡快速 (~1.2s)", "⭐⭐⭐⭐☆", "¥0.80 / ¥2.00", "32K", "☁️ 云端", "国内优选"),
            ("智谱 AI", "glm-4-plus", "⚡中等 (~2s)", "⭐⭐⭐⭐☆", "¥1.00 / ¥1.00", "128K", "☁️ 云端", "国产旗舰"),
            ("通义千问", "qwen-max", "⚡中等 (~2.5s)", "⭐⭐⭐⭐☆", "¥2.00 / ¥6.00", "32K", "☁️ 云端", "阿里系首选"),
            ("通义千问", "qwen-turbo", "⚡快速 (~0.5s)", "⭐⭐⭐☆☆", "¥0.30 / ¥0.60", "8K", "☁️ 云端", "极速响应"),
            ("月之暗面", "moonshot-v1-8k", "⚡中等 (~1.5s)", "⭐⭐⭐⭐☆", "¥12.00 / ¥12.00", "8K", "☁️ 云端", "长文理解强"),
            ("Claude", "claude-3.5-sonnet", "🐢较慢 (~4s)", "⭐⭐⭐⭐⭐", "$3.00 / $15.00", "200K", "☁️ 云端", "代码/写作王"),
            ("硅基流动", "Qwen/Qwen2.5-7B-Instruct", "⚡快速 (~0.6s)", "⭐⭐⭐☆☆", "¥0.70 / ¥1.40", "32K", "☁️ 云端", "低价推理"),
        ]
        for row_data in bench_data:
            row = self._bench_table.rowCount()
            self._bench_table.insertRow(row)
            for col, val in enumerate(row_data):
                item = QTableWidgetItem(val)
                if col == 3:  # speed
                    if "快速" in val:
                        item.setForeground(QColor("#4caf50"))
                    elif "慢" in val:
                        item.setForeground(QColor("#f59e0b"))
                    else:
                        item.setForeground(QColor("#1e6bde"))
                elif col == 4:  # quality
                    item.setForeground(QColor("#f59e0b"))
                elif col == 7:  # overall
                    if any(kw in val for kw in ["极高", "旗舰", "王"]):
                        item.setForeground(QColor("#22c55e"))
                    else:
                        item.setForeground(QColor("#1e6bde"))
                self._bench_table.setItem(row, col, item)

    def _run_speed_test(self):
        """对当前激活的模型进行简单的响应速度测试"""
        if not self._active_provider:
            QMessageBox.information(self, "提示", "请先在模型广场中激活一个模型再进行速度测试")
            return

        self._bench_loading.setText("⏳ 测试中...")
        QApplication.processEvents()

        def _do_test():
            try:
                from app.core.ai_engine import ai_engine
                t0 = time.time()
                resp = ai_engine.chat(
                    provider=self._active_provider,
                    messages=[{"role": "user", "content": "回复：OK"}],
                    max_tokens=5
                )
                elapsed = time.time() - t0
                return elapsed, resp
            except Exception as e:
                return None, str(e)

        elapsed, resp = _do_test()
        if elapsed is not None:
            self._bench_loading.setText(f"✅ 响应时间: {elapsed:.2f}s")
            provider_name = (PROVIDERS.get(self._active_provider) or self._custom_providers.get(self._active_provider) or {}).get("name", self._active_provider)
            QMessageBox.information(self, "速度测试结果",
                f"模型: {provider_name}\n"
                f"响应时间: {elapsed:.2f} 秒\n"
                f"响应内容: {resp[:100] if isinstance(resp, str) else resp}\n\n"
                f"💡 提示: 响应速度受网络、模型负载等因素影响，仅供参考")
        else:
            self._bench_loading.setText("❌ 测试失败")
            QMessageBox.warning(self, "测试失败", f"请求失败: {resp}\n\n请检查模型配置和网络连接")

    def _on_activate_provider(self, provider_id: str):
        if self._active_provider == provider_id:
            self._active_provider = ""
            self._save_active_provider()
            self._cards[provider_id].set_active(False)
            self._active_label.setText("未选择激活模型")
            self._active_label.setStyleSheet("font-size: 12px; color: #888888;")
            self._status_bar.showMessage("已取消激活")
            return

        for pid, card in self._cards.items():
            card.set_active(pid == provider_id)

        self._active_provider = provider_id
        self._save_active_provider()
        provider_name = (PROVIDERS.get(provider_id) or self._custom_providers.get(provider_id) or {}).get("name", provider_id)
        self._active_label.setText(f"🟢 当前激活: {provider_name}")
        self._active_label.setStyleSheet("font-size: 12px; color: #22c55e; font-weight: 600;")
        self._status_bar.showMessage(f"已激活 {provider_name} - 所有AI功能将使用此模型")

    def _on_config_saved(self, provider_id: str, config: dict[str, Any]):
        provider_name = (PROVIDERS.get(provider_id) or self._custom_providers.get(provider_id) or {}).get("name", provider_id)
        self._status_bar.showMessage(f"✅ {provider_name} 配置已保存", 3000)

    def _save_all_configs(self):
        try:
            from .cloud_api import cloud_api_service
            from .ollama_client import ollama_client
            saved_count = 0
            ollama_saved = False
            for provider_id, card in self._cards.items():
                info = PROVIDERS.get(provider_id) or self._custom_providers.get(provider_id) or {}
                if info.get("is_local"):
                    if hasattr(card, '_url_input') and card._url_input.text():
                        url = card._url_input.text().strip()
                        host = url.replace(":11434", "").replace("http://", "").replace("https://", "")
                        ollama_client.save_config(host=host)
                        ollama_saved = True
                    continue
                if hasattr(card, '_api_key_input') and card._api_key_input.text():
                    cloud_api_service.set_config(
                        provider_id,
                        card._api_key_input.text(),
                        card._base_url_input.text(),
                        card._model_combo.currentText()
                    )
                    saved_count += 1
            if saved_count > 0 or ollama_saved:
                msg_parts = []
                if ollama_saved:
                    msg_parts.append("Ollama 本地配置")
                if saved_count > 0:
                    msg_parts.append(f"{saved_count} 个云端配置")
                self._status_bar.showMessage(f"✅ 已保存 {', '.join(msg_parts)}")
                QMessageBox.information(self, "成功", f"已保存 {', '.join(msg_parts)}")
            else:
                QMessageBox.information(self, "提示", "没有需要保存的配置")
        except (ImportError, ConnectionError, OSError, ValueError) as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")

    def _add_custom_provider_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("添加自定义模型")
        dialog.setMinimumSize(440, 380)
        dialog.setStyleSheet("QDialog{background:#121212;}")
        dlo = QVBoxLayout(dialog)
        dlo.setContentsMargins(20, 20, 20, 20)
        dlo.setSpacing(10)
        
        fl = QFormLayout()
        fl.setSpacing(8)
        
        name_input = QLineEdit()
        name_input.setPlaceholderText("如: ChatGPT、OpenRouter...")
        name_input.setStyleSheet("QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:6px;padding:8px 12px;font-size:12px;}")
        fl.addRow("模型名称:", name_input)
        
        url_input = QLineEdit()
        url_input.setPlaceholderText("https://api.openai.com/v1")
        url_input.setStyleSheet("QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:6px;padding:8px 12px;font-size:12px;}")
        fl.addRow("API地址:", url_input)
        
        key_input = QLineEdit()
        key_input.setPlaceholderText("sk-...")
        key_input.setEchoMode(QLineEdit.EchoMode.Password)
        key_input.setStyleSheet("QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:6px;padding:8px 12px;font-size:12px;}")
        fl.addRow("API Key:", key_input)
        
        models_input = QLineEdit()
        models_input.setPlaceholderText("gpt-4o, gpt-4o-mini, o1 (逗号分隔)")
        models_input.setStyleSheet("QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:6px;padding:8px 12px;font-size:12px;}")
        fl.addRow("模型列表:", models_input)
        
        icon_input = QLineEdit()
        icon_input.setText("🔌")
        icon_input.setStyleSheet("QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:6px;padding:8px 12px;font-size:12px;}")
        icon_input.setFixedWidth(60)
        fl.addRow("图标:", icon_input)
        
        dlo.addLayout(fl)
        
        note = QLabel("支持所有兼容 OpenAI API 格式的模型平台")
        note.setStyleSheet("color:#555;font-size:10px;")
        dlo.addWidget(note)
        
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("取消")
        cancel.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:6px;padding:8px 20px;font-size:12px;}QPushButton:hover{background:#3a3a3a;}")
        cancel.clicked.connect(dialog.reject)
        btns.addWidget(cancel)
        ok = QPushButton("✅ 添加")
        ok.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;padding:8px 20px;font-size:12px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        ok.clicked.connect(dialog.accept)
        btns.addWidget(ok)
        dlo.addLayout(btns)
        
        if dialog.exec() == QDialog.DialogCode.Accepted and name_input.text().strip():
            pid = f"custom_{int(time.time() * 1000)}"
            info = {
                "name": name_input.text().strip(),
                "icon": icon_input.text().strip() or "🔌",
                "url": url_input.text().strip() or "https://api.openai.com/v1",
                "models": [m.strip() for m in models_input.text().split(",") if m.strip()],
                "is_local": False,
                "api_key": key_input.text().strip(),
                "is_custom": True,
            }
            if not info["models"]:
                info["models"] = ["gpt-4o-mini"]
            
            self._custom_providers[pid] = info
            self._save_custom_providers()
            
            card = ModelCardWidget(pid, info)
            card.activate_requested.connect(self._on_activate_provider)
            card.config_saved.connect(self._on_config_saved)
            self._cards[pid] = card
            self._cards_layout.insertWidget(self._cards_layout.count() - 2, card)
            
            self._status_bar.showMessage(f"✅ 已添加 {info['name']}")

    def on_activated(self):
        """模块激活时恢复上次选择的模型状态"""
        self._restore_active_state()

    def on_deactivated(self):
        """模块失活时保存当前激活状态，确保重启后恢复"""
        try:
            self._save_active_provider()
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"失活时保存状态失败（非关键）: {e}")
