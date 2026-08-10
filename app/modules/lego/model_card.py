"""
模型卡片组件 (ModelCardWidget)
==============================
从 model_management.py 拆分出来的可折叠模型卡片。
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox,
    QGroupBox, QFormLayout, QMessageBox, QProgressDialog,
    QListWidget, QListWidgetItem, QDialog, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QApplication,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QColor

from typing import Dict, Any
import threading
import logging

from .model_config import PROVIDERS

logger = logging.getLogger("AI短剧编辑器.model_card")

class ModelCardWidget(QFrame):
    """可折叠模型卡片组件"""
    
    activate_requested = pyqtSignal(str)
    config_saved = pyqtSignal(str, dict)  # type: ignore[reportMissingTypeArgument]
    
    def __init__(self, provider_id: str, provider_info: dict[str, Any], parent=None):
        super().__init__(parent)
        self._provider_id = provider_id
        self._provider_info = provider_info
        self._is_expanded = False
        self._is_active = False
        self._init_ui()
        self._load_saved_config()
    
    def _init_ui(self):
        self.setStyleSheet("""
            ModelCardWidget {
                background-color: #121212;
                border: 1px solid #252525;
                border-radius: 12px;
            }
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)
        
        self._header = self._create_header()
        self._body = self._create_body()
        self._body.setVisible(False)
        
        self._main_layout.addWidget(self._header)
        self._main_layout.addWidget(self._body)
    
    def _create_header(self) -> QFrame:
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: transparent;
                border: none;
            }
        """)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        
        icon_label = QLabel(self._provider_info["icon"])
        icon_label.setStyleSheet("font-size: 22px; background: transparent;")
        icon_label.setFixedWidth(36)
        layout.addWidget(icon_label)
        
        name_label = QLabel(self._provider_info["name"])
        name_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #ffffff; background: transparent;")
        layout.addWidget(name_label)
        
        if self._provider_info.get("is_local"):
            local_badge = QLabel("本地")
            local_badge.setStyleSheet("""
                font-size: 10px; color: #22c55e; background-color: #1a2e1a; 
                border-radius: 4px; padding: 2px 8px;
            """)
            layout.addWidget(local_badge)
        
        self._status_label = QLabel("检测中...")
        self._status_label.setStyleSheet("font-size: 12px; color: #888888; background: transparent;")
        layout.addWidget(self._status_label)
        
        layout.addStretch()
        
        self._active_btn = QPushButton()
        self._active_btn.setFixedSize(32, 32)
        self._active_btn.setStyleSheet("""
            QPushButton {
                background-color: #252525;
                border: 2px solid #444444;
                border-radius: 16px;
            }
            QPushButton:hover {
                border-color: #1e6bde;
            }
        """)
        self._active_btn.clicked.connect(self._on_activate_clicked)
        layout.addWidget(self._active_btn)
        
        self._expand_btn = QPushButton("▶")
        self._expand_btn.setFixedSize(32, 32)
        self._expand_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: none;
                font-size: 12px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self._expand_btn.clicked.connect(self._on_expand_clicked)
        layout.addWidget(self._expand_btn)
        
        def on_header_click(event):
            self._on_expand_clicked()
        header.mousePressEvent = on_header_click
        
        return header
    
    def _create_body(self) -> QFrame:
        body = QFrame()
        body.setStyleSheet("""
            QFrame {
                background-color: #0a0a0a;
                border-top: 1px solid #1e1e1e;
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }
        """)
        
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(14)
        
        if self._provider_info.get("is_local"):
            self._build_ollama_body(layout)
        else:
            self._build_cloud_body(layout)
        
        return body
    
    def _build_ollama_body(self, layout):
        url_layout = QHBoxLayout()
        url_label = QLabel("服务地址")
        url_label.setStyleSheet("color: #888888; font-size: 12px; background: transparent;")
        url_layout.addWidget(url_label)
        
        self._url_input = QLineEdit(self._provider_info["url"])
        self._url_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a; color: #1e90ff; border: 1px solid #252525;
                border-radius: 6px; padding: 8px 12px; font-size: 13px;
            }
            QLineEdit:focus { border-color: #1e6bde; }
        """)
        url_layout.addWidget(self._url_input, 1)
        layout.addLayout(url_layout)
        
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        
        save_btn = QPushButton("💾 保存配置")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #22c55e; color: white; border: none;
                border-radius: 6px; padding: 8px 16px; font-size: 12px;
            }
            QPushButton:hover { background-color: #16a34a; }
        """)
        save_btn.clicked.connect(self._save_ollama_config)
        ctrl_row.addWidget(save_btn)
        
        refresh_btn = QPushButton("🔄 刷新状态")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a; color: #ffffff; border: none;
                border-radius: 6px; padding: 8px 16px; font-size: 12px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        refresh_btn.clicked.connect(self.check_ollama_status)
        ctrl_row.addWidget(refresh_btn)
        
        self._start_ollama_btn = QPushButton("▶ 启动服务")
        self._start_ollama_btn.setStyleSheet("""
            QPushButton {
                background-color: #d97706; color: #ffffff; border: none;
                border-radius: 6px; padding: 8px 16px; font-size: 12px;
            }
            QPushButton:hover { background-color: #b45309; }
        """)
        self._start_ollama_btn.clicked.connect(self._start_ollama_service)
        self._start_ollama_btn.hide()
        ctrl_row.addWidget(self._start_ollama_btn)
        
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)
        
        models_group = QGroupBox("已安装模型")
        models_group.setStyleSheet("""
            QGroupBox {
                font-size: 13px; font-weight: 600; color: #ffffff;
                border: 1px solid #252525; border-radius: 8px;
                margin-top: 8px; padding-top: 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
            }
        """)
        models_layout = QVBoxLayout(models_group)
        
        self._models_list = QListWidget()
        self._models_list.setMinimumHeight(100)
        self._models_list.setMaximumHeight(160)
        self._models_list.setStyleSheet("""
            QListWidget {
                background-color: #0d0d0d; border: 1px solid #252525; border-radius: 6px;
            }
            QListWidget::item {
                padding: 8px 12px; border-bottom: 1px solid #1a1a1a;
                color: #ffffff; font-size: 13px;
            }
            QListWidget::item:hover { background-color: #1a2a3a; }
        """)
        models_layout.addWidget(self._models_list)
        
        model_btn_row = QHBoxLayout()
        model_btn_row.setSpacing(8)
        
        pull_btn = QPushButton("📦 拉取模型")
        pull_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde; color: white; border: none;
                border-radius: 6px; padding: 8px 16px; font-size: 12px;
            }
            QPushButton:hover { background-color: #2a7bef; }
        """)
        pull_btn.clicked.connect(self._show_pull_dialog)
        model_btn_row.addWidget(pull_btn)
        
        del_btn = QPushButton("🗑 删除")
        del_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a; color: #ffffff; border: none;
                border-radius: 6px; padding: 8px 16px; font-size: 12px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        del_btn.clicked.connect(self._delete_model)
        model_btn_row.addWidget(del_btn)
        
        model_btn_row.addStretch()
        models_layout.addLayout(model_btn_row)
        
        layout.addWidget(models_group)
    
    def _save_ollama_config(self):
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入服务地址")
            return
        
        try:
            from .ollama_client import ollama_client
            host = url.replace(":11434", "").replace("http://", "").replace("https://", "")
            ollama_client.save_config(host=host)
            QMessageBox.information(self, "成功", "Ollama 配置已保存")
        except (ImportError, ConnectionError, OSError, ValueError) as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")
    
    def _build_cloud_body(self, layout):
        api_group = QGroupBox("API 认证")
        api_group.setStyleSheet("""
            QGroupBox {
                font-size: 13px; font-weight: 600; color: #ffffff;
                border: 1px solid #252525; border-radius: 8px;
                margin-top: 8px; padding-top: 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
            }
        """)
        api_form = QFormLayout(api_group)
        api_form.setSpacing(10)
        
        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("输入 API Key")
        self._api_key_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a; color: white; border: 1px solid #252525;
                border-radius: 6px; padding: 8px 12px; font-size: 13px;
            }
            QLineEdit:focus { border-color: #1e6bde; }
        """)
        api_form.addRow("API Key:", self._api_key_input)
        
        self._base_url_input = QLineEdit(self._provider_info["url"])
        self._base_url_input.setPlaceholderText("API 基础 URL")
        self._base_url_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a; color: white; border: 1px solid #252525;
                border-radius: 6px; padding: 8px 12px; font-size: 13px;
            }
            QLineEdit:focus { border-color: #1e6bde; }
        """)
        api_form.addRow("Base URL:", self._base_url_input)
        layout.addWidget(api_group)
        
        model_group = QGroupBox("模型配置")
        model_group.setStyleSheet("""
            QGroupBox {
                font-size: 13px; font-weight: 600; color: #ffffff;
                border: 1px solid #252525; border-radius: 8px;
                margin-top: 8px; padding-top: 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
            }
        """)
        model_form = QFormLayout(model_group)
        model_form.setSpacing(10)
        
        self._model_combo = QComboBox()
        self._model_combo.addItems(self._provider_info.get("models", []))
        self._model_combo.setEditable(True)
        self._model_combo.setStyleSheet("""
            QComboBox {
                background-color: #1a1a1a; color: white; border: 1px solid #252525;
                border-radius: 6px; padding: 8px 12px; font-size: 13px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a; color: white;
                selection-background-color: #1e6bde;
            }
        """)
        model_form.addRow("模型:", self._model_combo)
        
        self._max_tokens_spin = QSpinBox()
        self._max_tokens_spin.setRange(100, 32000)
        self._max_tokens_spin.setValue(4096)
        self._max_tokens_spin.setStyleSheet("""
            QSpinBox {
                background-color: #1a1a1a; color: white; border: 1px solid #252525;
                border-radius: 6px; padding: 8px 12px; font-size: 13px;
            }
        """)
        model_form.addRow("最大 Tokens:", self._max_tokens_spin)
        
        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 2.0)
        self._temp_spin.setSingleStep(0.1)
        self._temp_spin.setValue(0.7)
        self._temp_spin.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #1a1a1a; color: white; border: 1px solid #252525;
                border-radius: 6px; padding: 8px 12px; font-size: 13px;
            }
        """)
        model_form.addRow("Temperature:", self._temp_spin)
        
        self._top_p_spin = QDoubleSpinBox()
        self._top_p_spin.setRange(0.0, 1.0)
        self._top_p_spin.setSingleStep(0.05)
        self._top_p_spin.setValue(0.9)
        self._top_p_spin.setToolTip("核采样参数，控制输出的随机性。越低越确定，越高越多变")
        self._top_p_spin.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #1a1a1a; color: white; border: 1px solid #252525;
                border-radius: 6px; padding: 8px 12px; font-size: 13px;
            }
        """)
        model_form.addRow("Top-P:", self._top_p_spin)
        
        layout.addWidget(model_group)
        
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        
        test_btn = QPushButton("🔍 测试连接")
        test_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde; color: white; border: none;
                border-radius: 6px; padding: 8px 16px; font-size: 12px;
            }
            QPushButton:hover { background-color: #2a7bef; }
        """)
        test_btn.clicked.connect(self._test_connection)
        btn_row.addWidget(test_btn)
        
        save_btn = QPushButton("💾 保存配置")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #22c55e; color: white; border: none;
                border-radius: 6px; padding: 8px 16px; font-size: 12px;
            }
            QPushButton:hover { background-color: #16a34a; }
        """)
        save_btn.clicked.connect(self._save_cloud_config)
        btn_row.addWidget(save_btn)
        
        if self._provider_id == "modelscope":
            pull_btn = QPushButton("📦 下载模型")
            pull_btn.setStyleSheet("""
                QPushButton {
                    background-color: #8b5cf6; color: white; border: none;
                    border-radius: 6px; padding: 8px 16px; font-size: 12px;
                }
                QPushButton:hover { background-color: #7c3aed; }
            """)
            pull_btn.clicked.connect(self._show_modelscope_pull_dialog)
            btn_row.addWidget(pull_btn)
        
        btn_row.addStretch()
        layout.addLayout(btn_row)
    
    def _show_modelscope_pull_dialog(self):
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("下载魔搭模型")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("选择要下载的模型:"))
        
        model_combo = QComboBox()
        model_combo.setEditable(True)
        model_combo.addItems([
            "qwen/Qwen2-7B-Instruct",
            "qwen/Qwen2-14B-Instruct",
            "qwen/Qwen1.5-7B-Chat",
            "alibaba-pai/Qwen-VL",
            "ZhipuAI/chatglm3-6b",
            "baichuan-inc/Baichuan2-7B-Chat",
        ])
        model_combo.setStyleSheet("""
            QComboBox {
                background-color: #1a1a1a; color: white; border: 1px solid #252525;
                border-radius: 6px; padding: 8px 12px; font-size: 13px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a; color: white;
                selection-background-color: #8b5cf6;
            }
        """)
        layout.addWidget(model_combo)
        
        layout.addWidget(QLabel("\n提示：模型下载需要安装 modelscope SDK\n运行: pip install modelscope"))
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            model_name = model_combo.currentData() or model_combo.currentText()
            self._download_modelscope_model(model_name)
    
    def _download_modelscope_model(self, model_name: str):
        progress = QProgressDialog(f"正在下载模型: {model_name}", "取消", 0, 100, self)
        progress.setWindowTitle("下载模型")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        
        class DownloadWorker(QThread):
            finished = pyqtSignal(bool, str)
            progress_update = pyqtSignal(str)
            
            def __init__(self, model_name):
                super().__init__()
                self.model_name = model_name
            
            def run(self):
                try:
                    from .modelscope_client import modelscope_client
                    
                    if not modelscope_client.is_sdk_available():
                        self.finished.emit(False, "错误: 未安装 modelscope SDK，请运行 pip install modelscope")
                        return
                    
                    success = modelscope_client.download_model(self.model_name, lambda s: self.progress_update.emit(s))
                    if success:
                        self.finished.emit(True, "")
                    else:
                        self.finished.emit(False, f"下载失败，请检查模型名称是否正确: {self.model_name}")
                except (ImportError, ConnectionError, OSError, RuntimeError) as e:
                    import traceback
                    detail = str(e) or traceback.format_exc()
                    self.finished.emit(False, f"下载出错: {detail[:200]}")
        
        def on_progress(status: str):
            progress.setLabelText(status)
        
        def on_finished(success: bool, error: str):
            progress.close()
            if success:
                QMessageBox.information(self, "成功", f"模型 {model_name} 下载成功\n保存到: data/modelscope_models")
            elif error:
                QMessageBox.warning(self, "错误", f"下载模型失败: {error}")
            else:
                QMessageBox.warning(self, "失败", f"模型 {model_name} 下载失败")
        
        worker = DownloadWorker(model_name)
        worker.progress_update.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.start()
        self._download_worker = worker
    
    def _on_expand_clicked(self):
        self._is_expanded = not self._is_expanded
        self._body.setVisible(self._is_expanded)
        self._expand_btn.setText("▼" if self._is_expanded else "▶")
        
        if self._is_expanded:
            self.setStyleSheet("""
                ModelCardWidget {
                    background-color: #121212;
                    border: 1px solid #1e6bde;
                    border-radius: 12px;
                }
            """)
            if self._provider_info.get("is_local"):
                self.check_ollama_status()
        else:
            self.setStyleSheet("""
                ModelCardWidget {
                    background-color: #121212;
                    border: 1px solid #252525;
                    border-radius: 12px;
                }
            """)
    
    def _on_activate_clicked(self):
        self.activate_requested.emit(self._provider_id)
    
    def set_active(self, active: bool):
        self._is_active = active
        if active:
            self._active_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1e6bde;
                    border: 2px solid #3b82f6;
                    border-radius: 16px;
                }
            """)
        else:
            self._active_btn.setStyleSheet("""
                QPushButton {
                    background-color: #252525;
                    border: 2px solid #444444;
                    border-radius: 16px;
                }
                QPushButton:hover {
                    border-color: #1e6bde;
                }
            """)
    
    def check_ollama_status(self):
        """
        检测 Ollama 状态（含安装诊断和自动启动尝试）

        【完整检测流程】
        ┌──────────────────────────────────────────────────────────┐
        │  1. diagnose()  → 检查 Ollama 是否已安装                │
        │  2. 未安装       → 显示 "📥 安装 Ollama" 按钮           │
        │  3. 已安装未运行 → start_service() 尝试自动启动         │
        │     ├─ 启动成功  → 等 3 秒 → re-diagnose → 刷新模型列表 │
        │     └─ 启动失败  → 显示 "▶ 启动服务" 手动按钮          │
        │  4. 已运行       → 显示绿色 "运行中" → 刷新模型列表     │
        └──────────────────────────────────────────────────────────┘

        【Ollama HTTP 检测改进历程】
        - 旧问题：host 缺少 http:// 前缀 → requests 报 "No connection adapters"
        - 旧问题：系统代理干扰 localhost 连接
        - 修复：_load_config() 自动补全 http:// + session.trust_env=False 忽略代理
        - 详见 app/modules/lego/ollama_client.py 中 is_available() / diagnose()

        【强制重新检测】
        diagnose() 每次都重新发起 HTTP 请求，不使用缓存结果，
        确保用户看到的始终是实时状态。
        """
        try:
            from .ollama_client import ollama_client

            # ── 第1步：强制重新诊断（不用缓存） ──
            # ollama_client.diagnose() 返回 dict:
            #   { installed: bool, service_running: bool, suggestion: str, ... }
            report = ollama_client.diagnose()
            if not report["installed"]:
                # Ollama 可执行文件未找到（ollama.exe / ollama 不在 PATH 中）
                self._status_label.setText("● 未安装")
                sug = report.get("suggestion") or "请安装 Ollama"
                self._status_label.setToolTip(
                    ollama_client.format_diagnose_report(report)
                )
                self._status_label.setStyleSheet(
                    "font-size: 12px; color: #ef4444; background: transparent;")
                self._start_ollama_btn.setText("📥 安装 Ollama")
                self._start_ollama_btn.setToolTip(sug)
                self._start_ollama_btn.show()
                self._models_list.clear()
                self._models_list.addItem(QListWidgetItem("（诊断）" + sug[:60]))
                return

            if not report["service_running"]:
                # ── 第2步：服务未运行，尝试自动启动 ──
                # start_service() 内部会先检查是否已在运行，避免重复启动
                logger.info("Ollama 服务未运行，尝试自动启动...")
                if ollama_client.start_service():
                    import time
                    time.sleep(3)  # 等待服务完成初始化（增加等待时间，确保服务就绪）
                    # 启动后重新诊断，确认服务真正可用
                    report2 = ollama_client.diagnose()
                    if report2["service_running"]:
                        # 自动启动成功
                        self._status_label.setText("● 运行中")
                        self._status_label.setToolTip(
                            ollama_client.format_diagnose_report(report2)
                        )
                        self._status_label.setStyleSheet(
                            "font-size: 12px; color: #22c55e; background: transparent;")
                        self._start_ollama_btn.hide()
                        self._refresh_models()
                        return

                # ── 第3步：自动启动失败，提供手动操作入口 ──
                err = report.get("error") or "服务未运行"
                self._status_label.setText(f"● 未运行 · {err}")
                self._status_label.setToolTip(
                    ollama_client.format_diagnose_report(report)
                )
                self._status_label.setStyleSheet(
                    "font-size: 12px; color: #ef4444; background: transparent;")
                self._start_ollama_btn.setText("▶ 启动服务")
                self._start_ollama_btn.setToolTip(
                    report.get("suggestion")
                    or "点击启动 Ollama 服务\n或手动: 打开 Ollama 桌面应用 / 运行 ollama serve"
                )
                self._start_ollama_btn.show()
                self._models_list.clear()
                sug = (report.get("suggestion") or "").replace("\n", " ")
                if sug:
                    self._models_list.addItem(QListWidgetItem("（诊断）" + sug[:80]))
                return

            # ── 第4步：服务运行中，更新 UI 为正常状态 ──
            self._status_label.setText("● 运行中")
            self._status_label.setToolTip(
                ollama_client.format_diagnose_report(report)
            )
            self._status_label.setStyleSheet(
                "font-size: 12px; color: #22c55e; background: transparent;")
            self._start_ollama_btn.hide()
            self._refresh_models()

        except (ImportError, ConnectionError, OSError, RuntimeError) as e:
            logger.error(f"Ollama 状态检测异常: {e}")
            self._status_label.setText(f"● 检测失败 · {e}")
            self._status_label.setToolTip(str(e))
            self._status_label.setStyleSheet(
                "font-size: 12px; color: #f59e0b; background: transparent;")
            self._start_ollama_btn.hide()

    def _refresh_models(self):
        """刷新已安装模型列表"""
        try:
            from .ollama_client import ollama_client
            models = ollama_client.list_models(force_refresh=True)
            self._models_list.clear()
            if not models:
                self._models_list.addItem(
                    QListWidgetItem("（无模型）请执行: ollama pull qwen2.5:7b")
                )
                return
            for model in models:
                item = QListWidgetItem(f" {model.display_name}")
                item.setData(Qt.ItemDataRole.UserRole, model.name)
                self._models_list.addItem(item)
        except (ImportError, ConnectionError, RuntimeError) as e:
            logger.warning(f"刷新模型列表失败: {e}")
            self._models_list.clear()
            self._models_list.addItem(QListWidgetItem(f"（刷新失败）{e}"))
    
    def _start_ollama_service(self):
        """
        手动触发启动 Ollama 服务（用户点击 "▶ 启动服务" 按钮）

        与 check_ollama_status() 中的自动启动不同：
          - 自动启动：在卡片展开/状态检测时静默触发
          - 手动启动：用户明确点击按钮触发

        流程：
          1. UI 更新为 "启动中..."（黄色状态，按钮禁用防重复点击）
          2. 调用 ollama_client.start_service() 启动进程
          3. 启动后台线程 _retry_check_ollama() 轮询检测
             → 最多等 12 秒（6 次 × 2 秒间隔）
             → 检测到服务就绪后用 QTimer.singleShot 回主线程刷新 UI
        """
        self._status_label.setText("● 启动中...")
        self._status_label.setStyleSheet("font-size: 12px; color: #f59e0b; background: transparent;")
        self._start_ollama_btn.setEnabled(False)
        QApplication.processEvents()
        
        try:
            from .ollama_client import ollama_client
            ollama_client.start_service()
            # 启动后台轮询线程，避免阻塞 UI
            threading.Thread(target=self._retry_check_ollama, daemon=True).start()
        except (ImportError, OSError, RuntimeError, ConnectionError) as e:
            self._status_label.setText("● 启动失败")
            self._status_label.setStyleSheet("font-size: 12px; color: #ef4444; background: transparent;")
            self._start_ollama_btn.setEnabled(True)
    
    def _retry_check_ollama(self):
        """
        Ollama 启动后的轮询检测线程

        设计要点：
          - 后台线程运行，不阻塞 UI 主线程
          - 每 2 秒检测一次，最多 6 次（共 12 秒超时）
          - force_check=True 强制发起 HTTP 请求，忽略缓存
          - 检测到可用后立即跳出循环
          - 无论成功失败，最终用 QTimer.singleShot(0, ...) 回到主线程更新 UI
            （PyQt 要求所有 UI 操作必须在主线程执行）
        """
        import time
        for i in range(6):  # 最多等 12 秒（6 次 × 2 秒）
            time.sleep(2)
            try:
                from .ollama_client import ollama_client
                # force_check=True 确保每次都是真实 HTTP 探测，不走缓存
                if ollama_client.is_available(force_check=True):
                    break
            except (ImportError, ConnectionError, RuntimeError) as e:
                logger.debug(f"Ollama 状态检测重试: {e}")
        # QTimer.singleShot(0, ...) 将回调调度到 Qt 事件循环中执行
        # 参数 0 表示尽快，相当于 "下一个事件循环周期"
        QTimer.singleShot(0, self.check_ollama_status)
        QTimer.singleShot(0, lambda: self._start_ollama_btn.setEnabled(True))
    
    def _show_pull_dialog(self):
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox  # type: ignore[reportMissingImports]
        
        # 先检查 Ollama 服务是否可用
        try:
            from .ollama_client import ollama_client
            if not ollama_client.is_available(force_check=True):
                QMessageBox.warning(
                    self, "Ollama 不可用",
                    "无法连接到 Ollama 服务。\n\n"
                    "请确保:\n"
                    "1. Ollama 已安装并正在运行\n"
                    "2. 在终端运行: ollama serve\n"
                    f"3. 服务地址: {ollama_client.base_url}")
                return
        except ImportError:
            QMessageBox.warning(self, "Ollama 不可用",
                "Ollama 客户端未安装。请运行: pip install ollama")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("拉取模型")
        dialog.setMinimumWidth(420)
        dialog.setStyleSheet("QDialog { background-color: #1a1a1a; }")
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        title_label = QLabel("选择要拉取的模型")
        title_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffffff;")
        layout.addWidget(title_label)
        
        model_combo = QComboBox()
        model_combo.setEditable(True)
        model_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a; color: white; border: 1px solid #333333;
                border-radius: 6px; padding: 10px 12px; font-size: 13px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a; color: white;
                selection-background-color: #1e6bde;
            }
        """)
        try:
            from .ollama_client import RECOMMENDED_MODELS
            for model in RECOMMENDED_MODELS:
                model_combo.addItem(f"{model['name']} ({model['size']}) - {model['description']}", model['name'])
        except ImportError as e:
            logger.warning(f"加载推荐模型列表失败，使用默认列表: {e}")
            model_combo.addItems(["llama3:8b", "qwen2:7b", "deepseek-coder:6.7b", "phi3:3.8b"])
        layout.addWidget(model_combo)
        
        hint = QLabel("提示: 大模型文件约4-8GB, 请确保网络稳定且磁盘空间充足")
        hint.setStyleSheet("color:#888;font-size:10px;")
        layout.addWidget(hint)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            model_name = model_combo.currentData() or model_combo.currentText()
            self._pull_model(model_name)
    
    def _pull_model(self, model_name: str):
        progress = QProgressDialog(f"正在拉取模型: {model_name}", "取消", 0, 100, self)
        progress.setWindowTitle("拉取模型")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        
        class PullWorker(QThread):
            finished = pyqtSignal(bool, str)
            progress_update = pyqtSignal(str)
            
            def __init__(self, model_name):
                super().__init__()
                self.model_name = model_name
            
            def run(self):
                try:
                    from .ollama_client import ollama_client
                    # 二次确认服务可用
                    if not ollama_client.is_available(force_check=True):
                        self.finished.emit(False, f"Ollama 服务未运行 ({ollama_client.base_url})")
                        return
                    success = ollama_client.pull_model(self.model_name, lambda s: self.progress_update.emit(s))
                    if success:
                        self.finished.emit(True, "")
                    else:
                        self.finished.emit(False, f"拉取失败，请检查模型名称是否正确: {self.model_name}")
                except (ImportError, ConnectionError, OSError, RuntimeError) as e:
                    import traceback
                    detail = str(e) or traceback.format_exc()
                    self.finished.emit(False, f"拉取出错: {detail[:200]}")
        
        def on_progress(status: str):
            progress.setLabelText(status)
        
        def on_finished(success: bool, error: str):
            progress.close()
            if success:
                QMessageBox.information(self, "成功", f"模型 {model_name} 拉取成功")
                self.check_ollama_status()
            elif error:
                QMessageBox.warning(self, "错误", f"拉取模型失败: {error}")
            else:
                QMessageBox.warning(self, "失败", f"模型 {model_name} 拉取失败")
        
        worker = PullWorker(model_name)
        worker.progress_update.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.start()
        self._pull_worker = worker
    
    def _delete_model(self):
        current = self._models_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选择要删除的模型")
            return
        
        model_name = current.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除模型 {model_name} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from .ollama_client import ollama_client
                if ollama_client.delete_model(model_name):
                    QMessageBox.information(self, "成功", f"模型 {model_name} 已删除")
                    self.check_ollama_status()
                else:
                    QMessageBox.warning(self, "失败", "删除模型失败")
            except (ImportError, ConnectionError, OSError) as e:
                QMessageBox.warning(self, "错误", f"删除模型失败: {e}")
    
    def _test_connection(self):
        api_key = self._api_key_input.text()
        if not api_key:
            QMessageBox.warning(self, "提示", "请先输入 API Key")
            return
        
        class TestWorker(QThread):
            finished = pyqtSignal(bool, str)
            
            def __init__(self, provider_id, api_key, base_url, model_name):
                super().__init__()
                self.provider_id = provider_id
                self.api_key = api_key
                self.base_url = base_url
                self.model_name = model_name
            
            def run(self):
                try:
                    from .cloud_api import cloud_api_service
                    cloud_api_service.set_config(self.provider_id, self.api_key, self.base_url, self.model_name)
                    response = ""
                    for chunk in cloud_api_service.chat(
                        self.provider_id,
                        [{"role": "user", "content": "Hello"}],
                        max_tokens=10
                    ):
                        response += chunk
                    if response and "错误" not in response:
                        self.finished.emit(True, response)
                    else:
                        self.finished.emit(False, response)
                except (ImportError, ConnectionError, ValueError, RuntimeError) as e:
                    self.finished.emit(False, str(e))
        
        base_url = self._base_url_input.text()
        model_name = self._model_combo.currentText()
        
        self._status_label.setText("测试中...")
        self._status_label.setStyleSheet("font-size: 12px; color: #f59e0b; background: transparent;")
        
        def on_finished(success: bool, response: str):
            if success:
                self._status_label.setText("● 已配置 ✓")
                self._status_label.setStyleSheet("font-size: 12px; color: #22c55e; background: transparent;")
                QMessageBox.information(self, "成功", f"连接成功！\n响应: {response[:100]}")
            else:
                self._status_label.setText("● 连接失败")
                self._status_label.setStyleSheet("font-size: 12px; color: #ef4444; background: transparent;")
                QMessageBox.warning(self, "失败", f"连接失败: {response}")
        
        worker = TestWorker(self._provider_id, api_key, base_url, model_name)
        worker.finished.connect(on_finished)
        # 线程完成后自动清理
        worker.finished.connect(lambda: worker.deleteLater())

        # 10秒超时保护
        timeout_timer = QTimer(self)
        timeout_timer.setSingleShot(True)

        def on_timeout():
            if worker.isRunning():
                logger.warning(f"连接测试超时 (10s): {self._provider_id}")
                worker.terminate()
                worker.wait(2000)
                self._status_label.setText("● 连接超时")
                self._status_label.setStyleSheet(
                    "font-size: 12px; color: #ef4444; background: transparent;"
                )
                QMessageBox.warning(
                    self, "超时",
                    "连接测试超时（10秒），请检查：\n"
                    "1. API Key 是否正确\n"
                    "2. Base URL 是否可访问\n"
                    "3. 网络连接是否正常"
                )

        worker.finished.connect(timeout_timer.stop)
        timeout_timer.timeout.connect(on_timeout)
        timeout_timer.start(10000)  # 10 秒

        worker.start()
        self._test_worker = worker
    
    def _save_cloud_config(self):
        api_key = self._api_key_input.text()
        if not api_key:
            QMessageBox.warning(self, "提示", "请先输入 API Key")
            return
        
        config = {
            "api_key": api_key,
            "base_url": self._base_url_input.text(),
            "model_name": self._model_combo.currentText(),
            "max_tokens": self._max_tokens_spin.value(),
            "temperature": self._temp_spin.value(),
            "top_p": self._top_p_spin.value(),
        }
        
        try:
            from .cloud_api import cloud_api_service
            cloud_api_service.set_config(
                self._provider_id, config["api_key"],
                config["base_url"], config["model_name"],
                max_tokens=config["max_tokens"],
                temperature=config["temperature"],
                top_p=config["top_p"],
            )
            self.config_saved.emit(self._provider_id, config)
            self._status_label.setText("● 已配置 ✓")
            self._status_label.setStyleSheet("font-size: 12px; color: #22c55e; background: transparent;")
            QMessageBox.information(self, "成功", "配置已保存")
        except (ImportError, ConnectionError, ValueError) as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")
    
    def _load_saved_config(self):
        if self._provider_info.get("is_local"):
            self.check_ollama_status()
            return
        try:
            from .cloud_api import cloud_api_service
            config = cloud_api_service.get_config(self._provider_id)
            if config and hasattr(config, 'api_key') and config.api_key:
                self._api_key_input.setText(config.api_key)
                if hasattr(config, 'base_url') and config.base_url:
                    self._base_url_input.setText(config.base_url)
                if hasattr(config, 'model') and config.model:
                    idx = self._model_combo.findText(config.model)
                    if idx >= 0:
                        self._model_combo.setCurrentIndex(idx)
                    else:
                        self._model_combo.setEditText(config.model)
                if hasattr(config, 'max_tokens'):
                    self._max_tokens_spin.setValue(config.max_tokens)
                if hasattr(config, 'temperature'):
                    self._temp_spin.setValue(config.temperature)
                if hasattr(config, 'top_p'):
                    self._top_p_spin.setValue(config.top_p)
                self._status_label.setText("● 已配置 ✓")
                self._status_label.setStyleSheet("font-size: 12px; color: #22c55e; background: transparent;")
            else:
                self._status_label.setText("未配置")
                self._status_label.setStyleSheet("font-size: 12px; color: #888888; background: transparent;")
        except (ImportError, AttributeError, ValueError) as e:
            logger.debug(f"加载模型配置失败: {e}")
            self._status_label.setText("未配置")
            self._status_label.setStyleSheet("font-size: 12px; color: #888888; background: transparent;")
    
    @property
    def provider_id(self):
        return self._provider_id

