"""
OpenClaw 自动化运营配置 (OpenClawConfigWidget)
=============================================
从 model_management.py 拆分出来。
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QCheckBox, QSpinBox, QLineEdit, QTextEdit,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QDialogButtonBox, QFormLayout, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from typing import Dict, Any
import logging

logger = logging.getLogger("AI短剧编辑器.openclaw_config")

class OpenClawConfigWidget(QWidget):
    """OpenClaw 自动化运营配置组件"""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._load_accounts()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        accounts_group = QGroupBox("已绑定账号")
        accounts_group.setStyleSheet("""
            QGroupBox {
                font-size: 13px; font-weight: 600; color: #ffffff;
                border: 1px solid #252525; border-radius: 8px;
                margin-top: 8px; padding-top: 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
            }
        """)
        accounts_layout = QVBoxLayout(accounts_group)

        self._accounts_table = QTableWidget()
        self._accounts_table.setColumnCount(4)
        self._accounts_table.setHorizontalHeaderLabels(["平台", "账号", "状态", "操作"])
        self._accounts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._accounts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._accounts_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._accounts_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._accounts_table.setColumnWidth(0, 90)
        self._accounts_table.setColumnWidth(2, 70)
        self._accounts_table.setColumnWidth(3, 90)
        self._accounts_table.setMinimumHeight(180)
        self._accounts_table.setStyleSheet("""
            QTableWidget {
                background-color: #0d0d0d; color: white;
                border: 1px solid #252525; border-radius: 6px;
            }
            QTableWidget::item {
                padding: 8px; border-bottom: 1px solid #1a1a1a;
            }
            QHeaderView::section {
                background-color: #1a1a1a; color: #ffffff;
                padding: 8px; font-size: 12px; font-weight: 600;
                border: none; border-bottom: 1px solid #252525;
            }
        """)
        accounts_layout.addWidget(self._accounts_table)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._add_account_btn = QPushButton("➕ 添加账号")
        self._add_account_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde; color: white; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #2a7bef; }
        """)
        self._add_account_btn.clicked.connect(self._add_account)
        btn_layout.addWidget(self._add_account_btn)

        self._refresh_accounts_btn = QPushButton("🔄 刷新")
        self._refresh_accounts_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a; color: white; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self._refresh_accounts_btn.clicked.connect(self._load_accounts)
        btn_layout.addWidget(self._refresh_accounts_btn)

        btn_layout.addStretch()
        accounts_layout.addLayout(btn_layout)
        layout.addWidget(accounts_group)

        auto_group = QGroupBox("自动化设置")
        auto_group.setStyleSheet("""
            QGroupBox {
                font-size: 13px; font-weight: 600; color: #ffffff;
                border: 1px solid #252525; border-radius: 8px;
                margin-top: 8px; padding-top: 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
            }
        """)
        auto_layout = QFormLayout(auto_group)
        auto_layout.setSpacing(12)

        self._auto_publish_check = QCheckBox("启用自动发布")
        self._auto_publish_check.setStyleSheet("color: #ffffff; font-size: 12px;")
        auto_layout.addRow(self._auto_publish_check)

        self._auto_reply_check = QCheckBox("启用智能回复")
        self._auto_reply_check.setStyleSheet("color: #ffffff; font-size: 12px;")
        auto_layout.addRow(self._auto_reply_check)

        self._auto_collect_check = QCheckBox("启用数据采集")
        self._auto_collect_check.setStyleSheet("color: #ffffff; font-size: 12px;")
        auto_layout.addRow(self._auto_collect_check)

        interval_spin = QSpinBox()
        interval_spin.setRange(1, 1440)
        interval_spin.setValue(60)
        interval_spin.setSuffix(" 分钟")
        interval_spin.setStyleSheet("""
            QSpinBox {
                background-color: #0d0d0d; color: white;
                border: 1px solid #252525; border-radius: 4px;
                padding: 6px 10px; font-size: 12px;
            }
        """)
        auto_layout.addRow("采集间隔:", interval_spin)
        layout.addWidget(auto_group)

        reply_group = QGroupBox("智能回复规则")
        reply_group.setStyleSheet("""
            QGroupBox {
                font-size: 13px; font-weight: 600; color: #ffffff;
                border: 1px solid #252525; border-radius: 8px;
                margin-top: 8px; padding-top: 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
            }
        """)
        reply_layout = QVBoxLayout(reply_group)

        self._reply_rules_table = QTableWidget()
        self._reply_rules_table.setColumnCount(2)
        self._reply_rules_table.setHorizontalHeaderLabels(["关键词", "回复内容"])
        self._reply_rules_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._reply_rules_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._reply_rules_table.setColumnWidth(0, 140)
        self._reply_rules_table.setMinimumHeight(130)
        self._reply_rules_table.setStyleSheet("""
            QTableWidget {
                background-color: #0d0d0d; color: white;
                border: 1px solid #252525; border-radius: 6px;
            }
            QTableWidget::item {
                padding: 8px; border-bottom: 1px solid #1a1a1a;
            }
            QHeaderView::section {
                background-color: #1a1a1a; color: #ffffff;
                padding: 8px; font-size: 12px; font-weight: 600;
                border: none; border-bottom: 1px solid #252525;
            }
        """)
        reply_layout.addWidget(self._reply_rules_table)

        rule_btn_layout = QHBoxLayout()
        rule_btn_layout.setSpacing(8)

        self._add_rule_btn = QPushButton("➕ 添加规则")
        self._add_rule_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50; color: white; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #5cbf60; }
        """)
        self._add_rule_btn.clicked.connect(self._add_reply_rule)
        rule_btn_layout.addWidget(self._add_rule_btn)

        self._del_rule_btn = QPushButton("➖ 删除规则")
        self._del_rule_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a; color: white; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self._del_rule_btn.clicked.connect(self._del_reply_rule)
        rule_btn_layout.addWidget(self._del_rule_btn)

        rule_btn_layout.addStretch()
        reply_layout.addLayout(rule_btn_layout)
        layout.addWidget(reply_group)
        layout.addStretch()

    def _load_accounts(self):
        try:
            from .openclow_engine import get_openclow_engine
            engine = get_openclow_engine()
            accounts = engine.get_accounts()
            self._accounts_table.setRowCount(len(accounts))
            for i, account in enumerate(accounts):
                self._accounts_table.setItem(i, 0, QTableWidgetItem(account.get("platform", "")))
                self._accounts_table.setItem(i, 1, QTableWidgetItem(account.get("account_id", "")))
                status_item = QTableWidgetItem("已绑定")
                status_item.setForeground(QColor("#22c55e"))
                self._accounts_table.setItem(i, 2, status_item)
                del_btn = QPushButton("解绑")
                del_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #ef4444; color: white; border: none;
                        border-radius: 3px; padding: 4px 10px; font-size: 11px;
                    }
                    QPushButton:hover { background-color: #dc2626; }
                """)
                del_btn.clicked.connect(lambda checked, acc=account: self._remove_account(acc))
                self._accounts_table.setCellWidget(i, 3, del_btn)
        except (ImportError, ConnectionError, KeyError, OSError) as e:
            logger.warning(f"加载已绑定账号失败: {e}")
            self._accounts_table.setRowCount(0)

    def _add_account(self):
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox  # type: ignore[reportMissingImports]
        dialog = QDialog(self)
        dialog.setWindowTitle("添加账号")
        dialog.setMinimumWidth(360)
        dialog.setStyleSheet("QDialog { background-color: #1a1a1a; }")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        form = QFormLayout()
        form.setSpacing(10)
        platform_combo = QComboBox()
        platform_combo.addItems(["抖音", "快手", "视频号"])
        platform_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a; color: white;
                border: 1px solid #333333; border-radius: 4px;
                padding: 8px 10px; font-size: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a; color: white;
            }
        """)
        form.addRow("平台:", platform_combo)
        account_input = QLineEdit()
        account_input.setPlaceholderText("输入账号 ID 或名称")
        account_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a; color: white;
                border: 1px solid #333333; border-radius: 4px;
                padding: 8px 10px; font-size: 12px;
            }
        """)
        form.addRow("账号:", account_input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            platform = platform_combo.currentText()
            account_id = account_input.text()
            if account_id:
                try:
                    from .openclow_engine import get_openclow_engine
                    engine = get_openclow_engine()
                    engine.add_account(platform, account_id, {})
                    self._load_accounts()
                    QMessageBox.information(self, "成功", f"账号 {account_id} 添加成功")
                except (ImportError, ConnectionError, KeyError, ValueError) as e:
                    QMessageBox.warning(self, "错误", f"添加失败: {e}")

    def _remove_account(self, account: Dict[str, Any]):
        reply = QMessageBox.question(
            self, "确认解绑",
            f"确定要解绑账号 {account.get('account_id', '')} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from .openclow_engine import get_openclow_engine
                engine = get_openclow_engine()
                engine.remove_account(account.get("platform", ""), account.get("account_id", ""))
                self._load_accounts()
                QMessageBox.information(self, "成功", "账号已解绑")
            except (ImportError, ConnectionError, KeyError, OSError) as e:
                QMessageBox.warning(self, "错误", f"解绑失败: {e}")

    def _add_reply_rule(self):
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox  # type: ignore[reportMissingImports]
        dialog = QDialog(self)
        dialog.setWindowTitle("添加回复规则")
        dialog.setMinimumWidth(400)
        dialog.setStyleSheet("QDialog { background-color: #1a1a1a; }")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        form = QFormLayout()
        form.setSpacing(10)
        keyword_input = QLineEdit()
        keyword_input.setPlaceholderText("触发关键词")
        keyword_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a; color: white;
                border: 1px solid #333333; border-radius: 4px;
                padding: 8px 10px; font-size: 12px;
            }
        """)
        form.addRow("关键词:", keyword_input)
        reply_input = QTextEdit()
        reply_input.setPlaceholderText("自动回复内容")
        reply_input.setMaximumHeight(90)
        reply_input.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a; color: white;
                border: 1px solid #333333; border-radius: 4px;
                padding: 8px 10px; font-size: 12px;
            }
        """)
        form.addRow("回复:", reply_input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            keyword = keyword_input.text()
            reply = reply_input.toPlainText()
            if keyword and reply:
                try:
                    from .openclow_engine import get_openclow_engine
                    engine = get_openclow_engine()
                    engine.add_reply_rule(keyword, reply)
                    self._load_reply_rules()
                    QMessageBox.information(self, "成功", "规则添加成功")
                except (ImportError, ConnectionError, KeyError, ValueError) as e:
                    QMessageBox.warning(self, "错误", f"添加失败: {e}")

    def _del_reply_rule(self):
        current_row = self._reply_rules_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先选择要删除的规则")
            return
        keyword_item = self._reply_rules_table.item(current_row, 0)
        if keyword_item:
            keyword = keyword_item.text()
            reply = QMessageBox.question(
                self, "确认删除",
                f"确定要删除规则 '{keyword}' 吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._reply_rules_table.removeRow(current_row)

    def _load_reply_rules(self):
        try:
            from .openclow_engine import get_openclow_engine
            engine = get_openclow_engine()
            self._reply_rules_table.setRowCount(len(engine.reply_rules))
            for i, rule in enumerate(engine.reply_rules):
                self._reply_rules_table.setItem(i, 0, QTableWidgetItem(rule.get("keyword", "")))
                self._reply_rules_table.setItem(i, 1, QTableWidgetItem(rule.get("reply", "")))
        except (ImportError, ConnectionError, KeyError, OSError) as e:
            logger.warning(f"加载回复规则失败: {e}")
            self._reply_rules_table.setRowCount(0)

