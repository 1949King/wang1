"""
模型管理模块 (ModelManagement)
==============================
整合本地大模型 (Ollama)、云端 API 和 OpenClaw 自动化运营
提供统一的模型配置、管理和测试界面
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QFrame, QScrollArea, QGridLayout, QComboBox,
    QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QGroupBox, QFormLayout, QMessageBox, QProgressDialog,
    QListWidget, QListWidgetItem, QSplitter, QStatusBar,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor, QIcon

from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass
import threading
import json
import time


@dataclass
class ModelConfig:
    """模型配置"""
    provider: str = ""
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    enabled: bool = True


class OllamaStatusWidget(QWidget):
    """Ollama 状态组件"""
    
    def __init__(self):
        super().__init__()
        self._init_ui()
        QTimer.singleShot(100, self._check_status)
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        header = QHBoxLayout()
        self._status_label = QLabel("● 检测中...")
        self._status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        header.addWidget(self._status_label)
        header.addStretch()
        
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.clicked.connect(self._check_status)
        header.addWidget(self._refresh_btn)
        
        layout.addLayout(header)
        
        self._info_frame = QFrame()
        self._info_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        info_layout = QGridLayout(self._info_frame)
        
        info_layout.addWidget(QLabel("服务地址:"), 0, 0)
        self._url_label = QLabel("http://localhost:11434")
        self._url_label.setStyleSheet("color: #1e6bde;")
        info_layout.addWidget(self._url_label, 0, 1)
        
        info_layout.addWidget(QLabel("已安装模型:"), 1, 0)
        self._model_count_label = QLabel("0 个")
        self._model_count_label.setStyleSheet("color: #ffffff;")
        info_layout.addWidget(self._model_count_label, 1, 1)
        
        layout.addWidget(self._info_frame)
        
        models_group = QGroupBox("已安装模型")
        models_layout = QVBoxLayout(models_group)
        
        self._models_list = QListWidget()
        self._models_list.setMinimumHeight(150)
        self._models_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2a2a2a;
            }
            QListWidget::item:selected {
                background-color: #1e6bde;
            }
        """)
        models_layout.addWidget(self._models_list)
        
        btn_layout = QHBoxLayout()
        
        self._pull_btn = QPushButton("拉取模型")
        self._pull_btn.clicked.connect(self._show_pull_dialog)
        btn_layout.addWidget(self._pull_btn)
        
        self._delete_btn = QPushButton("删除模型")
        self._delete_btn.clicked.connect(self._delete_model)
        btn_layout.addWidget(self._delete_btn)
        
        models_layout.addLayout(btn_layout)
        layout.addWidget(models_group)
    
    def _check_status(self):
        """检查 Ollama 状态"""
        try:
            from .ollama_client import ollama_client
            
            if ollama_client.is_available(force_check=True):
                self._status_label.setText("● Ollama 运行中")
                self._status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #22c55e;")
                
                models = ollama_client.list_models()
                self._model_count_label.setText(f"{len(models)} 个")
                
                self._models_list.clear()
                for model in models:
                    item = QListWidgetItem(f"📦 {model.display_name}")
                    item.setData(Qt.ItemDataRole.UserRole, model.name)
                    self._models_list.addItem(item)
            else:
                self._status_label.setText("● Ollama 未运行")
                self._status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #ef4444;")
                self._model_count_label.setText("0 个")
                self._models_list.clear()
                
        except Exception as e:
            self._status_label.setText(f"● 检测失败: {e}")
            self._status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #f59e0b;")
    
    def _show_pull_dialog(self):
        """显示拉取模型对话框"""
        from PyQt6.QtWidgets import QDialog, QComboBox, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("拉取模型")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("选择要拉取的模型:"))
        
        model_combo = QComboBox()
        model_combo.setEditable(True)
        
        try:
            from .ollama_client import RECOMMENDED_MODELS
            for model in RECOMMENDED_MODELS:
                model_combo.addItem(f"{model['name']} ({model['size']}) - {model['description']}", model['name'])
        except:
            model_combo.addItems(["llama3:8b", "qwen2:7b", "deepseek-coder:6.7b"])
        
        layout.addWidget(model_combo)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            model_name = model_combo.currentData() or model_combo.currentText()
            self._pull_model(model_name)
    
    def _pull_model(self, model_name: str):
        """拉取模型"""
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
                    success = ollama_client.pull_model(self.model_name, lambda s: self.progress_update.emit(s))
                    self.finished.emit(success, "")
                except Exception as e:
                    self.finished.emit(False, str(e))
        
        def on_progress(status: str):
            progress.setLabelText(status)
        
        def on_finished(success: bool, error: str):
            progress.close()
            if success:
                QMessageBox.information(self, "成功", f"模型 {model_name} 拉取成功")
                self._check_status()
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
        """删除选中的模型"""
        current = self._models_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选择要删除的模型")
            return
        
        model_name = current.data(Qt.ItemDataRole.UserRole)
        
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除模型 {model_name} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from .ollama_client import ollama_client
                if ollama_client.delete_model(model_name):
                    QMessageBox.information(self, "成功", f"模型 {model_name} 已删除")
                    self._check_status()
                else:
                    QMessageBox.warning(self, "失败", "删除模型失败")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"删除模型失败: {e}")


class CloudAPIConfigWidget(QWidget):
    """云端 API 配置组件"""
    
    config_changed = pyqtSignal(str, dict)
    
    PROVIDERS = {
        "deepseek": {"name": "DeepSeek", "url": "https://api.deepseek.com/v1", "models": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"]},
        "doubao": {"name": "豆包", "url": "https://ark.cn-beijing.volces.com/api/v3", "models": ["doubao-pro-4k", "doubao-pro-32k", "doubao-pro-128k"]},
        "openai": {"name": "OpenAI", "url": "https://api.openai.com/v1", "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini"]},
        "zhipu": {"name": "智谱 AI", "url": "https://open.bigmodel.cn/api/paas/v4", "models": ["glm-4", "glm-4-flash", "glm-4v", "glm-4-plus"]},
        "qwen": {"name": "通义千问", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "models": ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-max-longcontext", "qwen-vl-max"]},
        "wenxin": {"name": "文心一言", "url": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat", "models": ["ernie-4.0-8k", "ernie-4.0-turbo-8k", "ernie-3.5-8k"]},
        "spark": {"name": "讯飞星火", "url": "https://spark-api-open.xf-yun.com/v1", "models": ["generalv3.5", "generalv3", "generalv2"]},
        "kimi": {"name": "Kimi", "url": "https://api.moonshot.cn/v1", "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]},
        "baichuan": {"name": "百川", "url": "https://api.baichuan-ai.com/v1", "models": ["Baichuan4", "Baichuan3-Turbo", "Baichuan2-Turbo"]},
        "minimax": {"name": "MiniMax", "url": "https://api.minimax.chat/v1", "models": ["abab6.5s-chat", "abab6.5-chat", "abab5.5-chat"]},
        "claude": {"name": "Claude", "url": "https://api.anthropic.com/v1", "models": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"]},
        "groq": {"name": "Groq", "url": "https://api.groq.com/openai/v1", "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]},
        "siliconflow": {"name": "硅基流动", "url": "https://api.siliconflow.cn/v1", "models": ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3", "meta-llama/Llama-3.3-70B-Instruct"]},
        "stepfun": {"name": "阶跃星辰", "url": "https://api.stepfun.com/v1", "models": ["step-1-8k", "step-1-32k", "step-1-128k", "step-1v-8k"]},
        "yi": {"name": "零一万物", "url": "https://api.lingyiwanwu.com/v1", "models": ["yi-lightning", "yi-large", "yi-medium", "yi-spark"]},
    }
    
    def __init__(self):
        super().__init__()
        self._configs: Dict[str, ModelConfig] = {}
        self._init_ui()
        self._load_configs()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        header = QLabel("☁️ 云端 API 配置")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)
        
        desc = QLabel("配置云端大模型 API，支持 DeepSeek、豆包、OpenAI、智谱、通义千问、文心一言、讯飞星火、Kimi、百川、MiniMax、Claude、Groq、硅基流动、阶跃星辰、零一万物等15个平台")
        desc.setStyleSheet("color: #ffffff;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        self._tabs = QTabWidget()
        # 设置标签页为顶部横向排列
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        # 调整标签页样式
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #333333;
                border-radius: 8px;
                background-color: #1a1a1a;
                margin-top: 2px;
            }
            QTabBar::tab {
                background-color: #2a2a2a;
                color: #ffffff;
                border: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 10px 18px;
                font-size: 13px;
                min-width: 80px;
                height: 36px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                color: #ffffff;
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-bottom: none;
            }
            QTabBar::tab:hover:!selected {
                color: #ffffff;
                background-color: #333333;
            }
        """)
        
        for provider_id, provider_info in self.PROVIDERS.items():
            tab = self._create_provider_tab(provider_id, provider_info)
            self._tabs.addTab(tab, provider_info["name"])
        
        layout.addWidget(self._tabs)
        
        test_layout = QHBoxLayout()
        test_layout.setContentsMargins(0, 10, 0, 0)
        
        self._test_btn = QPushButton("🔍 测试连接")
        self._test_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2a7bef;
            }
        """)
        self._test_btn.clicked.connect(self._test_connection)
        test_layout.addWidget(self._test_btn)
        
        self._save_btn = QPushButton("💾 保存配置")
        self._save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #5cbf60;
            }
        """)
        self._save_btn.clicked.connect(self._save_configs)
        test_layout.addWidget(self._save_btn)
        
        self._save_template_btn = QPushButton("📁 保存模板")
        self._save_template_btn.setStyleSheet("""
            QPushButton {
                background-color: #f59e0b;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #d97706;
            }
        """)
        self._save_template_btn.clicked.connect(self._save_template)
        test_layout.addWidget(self._save_template_btn)
        
        self._load_template_btn = QPushButton("📂 导入模板")
        self._load_template_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
        """)
        self._load_template_btn.clicked.connect(self._load_template)
        test_layout.addWidget(self._load_template_btn)
        
        test_layout.addStretch()
        layout.addLayout(test_layout)
        
        self._status_bar = QStatusBar()
        self._status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #0a0a0a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 10px;
            }
        """)
        self._status_bar.showMessage("就绪")
        layout.addWidget(self._status_bar)
    
    def _create_provider_tab(self, provider_id: str, provider_info: Dict) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # API Key 部分
        api_key_group = QGroupBox("API 认证")
        api_key_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        api_key_layout = QFormLayout(api_key_group)
        
        api_key_input = QLineEdit()
        api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_input.setPlaceholderText("输入 API Key")
        api_key_input.setObjectName(f"{provider_id}_api_key")
        api_key_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 12px;
            }
        """)
        api_key_layout.addRow("API Key:", api_key_input)
        
        base_url_input = QLineEdit()
        base_url_input.setText(provider_info["url"])
        base_url_input.setPlaceholderText("API 基础 URL")
        base_url_input.setObjectName(f"{provider_id}_base_url")
        base_url_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 12px;
            }
        """)
        api_key_layout.addRow("Base URL:", base_url_input)
        
        # 模型配置部分
        model_group = QGroupBox("模型配置")
        model_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        model_layout = QFormLayout(model_group)
        
        model_combo = QComboBox()
        model_combo.addItems(provider_info["models"])
        model_combo.setEditable(True)
        model_combo.setObjectName(f"{provider_id}_model")
        model_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 12px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: white;
                selection-background-color: #1e6bde;
            }
        """)
        model_layout.addRow("模型:", model_combo)
        
        max_tokens_spin = QSpinBox()
        max_tokens_spin.setRange(100, 32000)
        max_tokens_spin.setValue(4096)
        max_tokens_spin.setObjectName(f"{provider_id}_max_tokens")
        max_tokens_spin.setStyleSheet("""
            QSpinBox {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 12px;
            }
        """)
        model_layout.addRow("最大 Tokens:", max_tokens_spin)
        
        temp_spin = QDoubleSpinBox()
        temp_spin.setRange(0.0, 2.0)
        temp_spin.setSingleStep(0.1)
        temp_spin.setValue(0.7)
        temp_spin.setObjectName(f"{provider_id}_temperature")
        temp_spin.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 12px;
            }
        """)
        model_layout.addRow("Temperature:", temp_spin)
        
        # 启用选项
        enable_check = QCheckBox("启用")
        enable_check.setChecked(True)
        enable_check.setObjectName(f"{provider_id}_enabled")
        enable_check.setStyleSheet("color: #ffffff;")
        model_layout.addRow("", enable_check)
        
        # 价格信息
        pricing_label = QLabel(self._get_pricing_info(provider_id))
        pricing_label.setStyleSheet("color: #ffffff; font-size: 12px; margin-top: 10px;")
        pricing_label.setWordWrap(True)
        
        layout.addWidget(api_key_group)
        layout.addWidget(model_group)
        layout.addWidget(pricing_label)
        layout.addStretch()
        
        return tab
    
    def _get_pricing_info(self, provider_id: str) -> str:
        pricing = {
            "deepseek": "💰 DeepSeek 定价: 约 ¥1/百万 tokens，高性价比",
            "doubao": "💰 豆包定价: 约 ¥0.8/百万 tokens，中文优化",
            "openai": "💰 OpenAI 定价: 约 $5/百万 tokens，能力最强",
            "zhipu": "💰 智谱 AI 定价: 约 ¥1/百万 tokens，多模态支持"
        }
        return pricing.get(provider_id, "")
    
    def _load_configs(self):
        """加载配置"""
        try:
            from .cloud_api import cloud_api_service
            
            for provider_id in self.PROVIDERS:
                config = cloud_api_service.get_config(provider_id)
                if config:
                    self._configs[provider_id] = ModelConfig(
                        provider=provider_id,
                        model_name=config.model,
                        api_key=config.api_key,
                        base_url=config.base_url,
                        max_tokens=config.max_tokens,
                        temperature=config.temperature
                    )
                    
                    tab = self._tabs.widget(list(self.PROVIDERS.keys()).index(provider_id))
                    self._set_tab_values(tab, provider_id, self._configs[provider_id])
        except:
            pass
    
    def _set_tab_values(self, tab: QWidget, provider_id: str, config: ModelConfig):
        """设置标签页的值"""
        api_key_input = tab.findChild(QLineEdit, f"{provider_id}_api_key")
        if api_key_input:
            api_key_input.setText(config.api_key)
        
        base_url_input = tab.findChild(QLineEdit, f"{provider_id}_base_url")
        if base_url_input:
            base_url_input.setText(config.base_url)
        
        model_combo = tab.findChild(QComboBox, f"{provider_id}_model")
        if model_combo:
            index = model_combo.findText(config.model_name)
            if index >= 0:
                model_combo.setCurrentIndex(index)
            else:
                model_combo.setEditText(config.model_name)
    
    def _get_current_config(self, provider_id: str) -> ModelConfig:
        """获取当前配置"""
        tab = self._tabs.widget(list(self.PROVIDERS.keys()).index(provider_id))
        
        api_key_input = tab.findChild(QLineEdit, f"{provider_id}_api_key")
        base_url_input = tab.findChild(QLineEdit, f"{provider_id}_base_url")
        model_combo = tab.findChild(QComboBox, f"{provider_id}_model")
        max_tokens_spin = tab.findChild(QSpinBox, f"{provider_id}_max_tokens")
        temp_spin = tab.findChild(QDoubleSpinBox, f"{provider_id}_temperature")
        enable_check = tab.findChild(QCheckBox, f"{provider_id}_enabled")
        
        return ModelConfig(
            provider=provider_id,
            model_name=model_combo.currentText() if model_combo else "",
            api_key=api_key_input.text() if api_key_input else "",
            base_url=base_url_input.text() if base_url_input else "",
            max_tokens=max_tokens_spin.value() if max_tokens_spin else 4096,
            temperature=temp_spin.value() if temp_spin else 0.7,
            enabled=enable_check.isChecked() if enable_check else True
        )
    
    def _test_connection(self):
        """测试连接"""
        provider_id = list(self.PROVIDERS.keys())[self._tabs.currentIndex()]
        config = self._get_current_config(provider_id)
        
        if not config.api_key:
            QMessageBox.warning(self, "提示", "请先输入 API Key")
            return
        
        self._status_bar.showMessage("正在测试连接...")
        
        class TestWorker(QThread):
            finished = pyqtSignal(bool, str)
            
            def __init__(self, provider_id, config):
                super().__init__()
                self.provider_id = provider_id
                self.config = config
            
            def run(self):
                try:
                    from .cloud_api import cloud_api_service
                    
                    cloud_api_service.set_config(
                        self.provider_id,
                        self.config.api_key,
                        self.config.base_url,
                        self.config.model_name
                    )
                    
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
                        
                except Exception as e:
                    self.finished.emit(False, str(e))
        
        def on_finished(success: bool, response: str):
            if success:
                self._status_bar.showMessage("✅ 连接成功")
                QMessageBox.information(self, "成功", f"连接成功！\n响应: {response[:100]}")
            else:
                self._status_bar.showMessage("❌ 连接失败")
                QMessageBox.warning(self, "失败", f"连接失败: {response}")
        
        worker = TestWorker(provider_id, config)
        worker.finished.connect(on_finished)
        worker.start()
        
        self._test_worker = worker
    
    def _save_configs(self):
        """保存配置"""
        try:
            from .cloud_api import cloud_api_service
            
            for provider_id in self.PROVIDERS:
                config = self._get_current_config(provider_id)
                
                if config.api_key:
                    cloud_api_service.set_config(
                        provider_id,
                        config.api_key,
                        config.base_url,
                        config.model_name
                    )
                    self._configs[provider_id] = config
            
            self._status_bar.showMessage("✅ 配置已保存")
            QMessageBox.information(self, "成功", "配置已保存")
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")
    
    def _save_template(self):
        """保存模板"""
        from PyQt6.QtWidgets import QFileDialog
        
        # 获取当前配置
        template_configs = {}
        for provider_id in self.PROVIDERS:
            config = self._get_current_config(provider_id)
            if config.api_key:
                template_configs[provider_id] = {
                    "model_name": config.model_name,
                    "api_key": config.api_key,
                    "base_url": config.base_url,
                    "max_tokens": config.max_tokens,
                    "temperature": config.temperature,
                    "enabled": config.enabled
                }
        
        if not template_configs:
            QMessageBox.warning(self, "提示", "没有配置可保存")
            return
        
        # 保存为JSON文件
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存模板", "", "JSON文件 (*.json)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(template_configs, f, indent=2, ensure_ascii=False)
                QMessageBox.information(self, "成功", "模板已保存")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"保存模板失败: {e}")
    
    def _load_template(self):
        """导入模板"""
        from PyQt6.QtWidgets import QFileDialog
        
        # 选择JSON文件
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入模板", "", "JSON文件 (*.json)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    template_configs = json.load(f)
                
                # 加载配置
                for provider_id, config_data in template_configs.items():
                    if provider_id in self.PROVIDERS:
                        # 找到对应的标签页
                        index = list(self.PROVIDERS.keys()).index(provider_id)
                        tab = self._tabs.widget(index)
                        
                        # 设置配置值
                        api_key_input = tab.findChild(QLineEdit, f"{provider_id}_api_key")
                        if api_key_input:
                            api_key_input.setText(config_data.get('api_key', ''))
                        
                        base_url_input = tab.findChild(QLineEdit, f"{provider_id}_base_url")
                        if base_url_input:
                            base_url_input.setText(config_data.get('base_url', ''))
                        
                        model_combo = tab.findChild(QComboBox, f"{provider_id}_model")
                        if model_combo:
                            model_name = config_data.get('model_name', '')
                            index = model_combo.findText(model_name)
                            if index >= 0:
                                model_combo.setCurrentIndex(index)
                            else:
                                model_combo.setEditText(model_name)
                        
                        max_tokens_spin = tab.findChild(QSpinBox, f"{provider_id}_max_tokens")
                        if max_tokens_spin:
                            max_tokens_spin.setValue(config_data.get('max_tokens', 4096))
                        
                        temp_spin = tab.findChild(QDoubleSpinBox, f"{provider_id}_temperature")
                        if temp_spin:
                            temp_spin.setValue(config_data.get('temperature', 0.7))
                        
                        enable_check = tab.findChild(QCheckBox, f"{provider_id}_enabled")
                        if enable_check:
                            enable_check.setChecked(config_data.get('enabled', True))
                
                QMessageBox.information(self, "成功", "模板已导入")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导入模板失败: {e}")


class OpenClawConfigWidget(QWidget):
    """OpenClaw 自动化运营配置组件"""
    
    def __init__(self):
        super().__init__()
        self._init_ui()
        self._load_accounts()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        header = QLabel("🤖 OpenClaw 自动化运营")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)
        
        desc = QLabel("配置多平台自动化运营，支持抖音、快手、视频号等平台")
        desc.setStyleSheet("color: #ffffff;")
        layout.addWidget(desc)
        
        accounts_group = QGroupBox("已绑定账号")
        accounts_layout = QVBoxLayout(accounts_group)
        
        self._accounts_table = QTableWidget()
        self._accounts_table.setColumnCount(4)
        self._accounts_table.setHorizontalHeaderLabels(["平台", "账号", "状态", "操作"])
        self._accounts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._accounts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._accounts_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._accounts_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._accounts_table.setColumnWidth(0, 100)
        self._accounts_table.setColumnWidth(2, 80)
        self._accounts_table.setColumnWidth(3, 100)
        self._accounts_table.setMinimumHeight(200)
        accounts_layout.addWidget(self._accounts_table)
        
        btn_layout = QHBoxLayout()
        
        self._add_account_btn = QPushButton("添加账号")
        self._add_account_btn.clicked.connect(self._add_account)
        btn_layout.addWidget(self._add_account_btn)
        
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self._load_accounts)
        btn_layout.addWidget(self._refresh_btn)
        
        accounts_layout.addLayout(btn_layout)
        layout.addWidget(accounts_group)
        
        auto_group = QGroupBox("自动化设置")
        auto_layout = QFormLayout(auto_group)
        
        self._auto_publish_check = QCheckBox("启用自动发布")
        auto_layout.addRow(self._auto_publish_check)
        
        self._auto_reply_check = QCheckBox("启用智能回复")
        auto_layout.addRow(self._auto_reply_check)
        
        self._auto_collect_check = QCheckBox("启用数据采集")
        auto_layout.addRow(self._auto_collect_check)
        
        interval_spin = QSpinBox()
        interval_spin.setRange(1, 1440)
        interval_spin.setValue(60)
        interval_spin.setSuffix(" 分钟")
        auto_layout.addRow("采集间隔:", interval_spin)
        
        layout.addWidget(auto_group)
        
        reply_group = QGroupBox("智能回复规则")
        reply_layout = QVBoxLayout(reply_group)
        
        self._reply_rules_table = QTableWidget()
        self._reply_rules_table.setColumnCount(2)
        self._reply_rules_table.setHorizontalHeaderLabels(["关键词", "回复内容"])
        self._reply_rules_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._reply_rules_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._reply_rules_table.setColumnWidth(0, 150)
        self._reply_rules_table.setMinimumHeight(150)
        reply_layout.addWidget(self._reply_rules_table)
        
        rule_btn_layout = QHBoxLayout()
        self._add_rule_btn = QPushButton("添加规则")
        self._add_rule_btn.clicked.connect(self._add_reply_rule)
        rule_btn_layout.addWidget(self._add_rule_btn)
        
        self._del_rule_btn = QPushButton("删除规则")
        self._del_rule_btn.clicked.connect(self._del_reply_rule)
        rule_btn_layout.addWidget(self._del_rule_btn)
        
        reply_layout.addLayout(rule_btn_layout)
        layout.addWidget(reply_group)
        
        layout.addStretch()
    
    def _load_accounts(self):
        """加载账号列表"""
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
                del_btn.clicked.connect(lambda checked, acc=account: self._remove_account(acc))
                self._accounts_table.setCellWidget(i, 3, del_btn)
                
        except Exception as e:
            print(f"加载账号失败: {e}")
    
    def _add_account(self):
        """添加账号"""
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("添加账号")
        dialog.setMinimumWidth(350)
        
        layout = QVBoxLayout(dialog)
        
        form = QFormLayout()
        
        platform_combo = QComboBox()
        platform_combo.addItems(["抖音", "快手", "视频号"])
        form.addRow("平台:", platform_combo)
        
        account_input = QLineEdit()
        account_input.setPlaceholderText("输入账号 ID 或名称")
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
                except Exception as e:
                    QMessageBox.warning(self, "错误", f"添加失败: {e}")
    
    def _remove_account(self, account: Dict):
        """移除账号"""
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
            except Exception as e:
                QMessageBox.warning(self, "错误", f"解绑失败: {e}")
    
    def _add_reply_rule(self):
        """添加回复规则"""
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("添加回复规则")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        form = QFormLayout()
        
        keyword_input = QLineEdit()
        keyword_input.setPlaceholderText("触发关键词")
        form.addRow("关键词:", keyword_input)
        
        reply_input = QTextEdit()
        reply_input.setPlaceholderText("自动回复内容")
        reply_input.setMaximumHeight(100)
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
                except Exception as e:
                    QMessageBox.warning(self, "错误", f"添加失败: {e}")
    
    def _del_reply_rule(self):
        """删除回复规则"""
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
        """加载回复规则"""
        try:
            from .openclow_engine import get_openclow_engine
            engine = get_openclow_engine()
            
            self._reply_rules_table.setRowCount(len(engine.reply_rules))
            
            for i, rule in enumerate(engine.reply_rules):
                self._reply_rules_table.setItem(i, 0, QTableWidgetItem(rule.get("keyword", "")))
                self._reply_rules_table.setItem(i, 1, QTableWidgetItem(rule.get("reply", "")))
                
        except Exception as e:
            print(f"加载回复规则失败: {e}")


class SkillInterfaceWidget(QWidget):
    """AI技能接口组件"""
    
    def __init__(self):
        super().__init__()
        self._init_ui()
        self._load_skills()
        self._load_clawhub_skills()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        header = QLabel("⚡ AI技能接口")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)
        
        desc = QLabel("直接调用AI技能来处理素材，支持自动生成字幕、一键剪辑视频片段、智能生成封面图等功能")
        desc.setStyleSheet("color: #ffffff;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # 技能分类标签页
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #333333;
                border-radius: 8px;
                background-color: #1a1a1a;
                margin-top: 2px;
            }
            QTabBar::tab {
                background-color: #2a2a2a;
                color: #ffffff;
                border: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 10px 18px;
                font-size: 13px;
                min-width: 80px;
                height: 36px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                color: #ffffff;
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-bottom: none;
            }
            QTabBar::tab:hover:!selected {
                color: #ffffff;
                background-color: #333333;
            }
        """)
        
        # 本地技能标签页
        local_tab = QWidget()
        local_layout = QVBoxLayout(local_tab)
        
        self._local_skills_list = QListWidget()
        self._local_skills_list.setMinimumHeight(200)
        self._local_skills_list.setStyleSheet("""
            QListWidget {
                background-color: #2a2a2a;
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #333333;
                color: white;
            }
            QListWidget::item:selected {
                background-color: #1e6bde;
            }
        """)
        self._local_skills_list.itemClicked.connect(self._on_skill_selected)
        local_layout.addWidget(self._local_skills_list)
        
        local_btn_layout = QHBoxLayout()
        self._run_skill_btn = QPushButton("▶ 运行技能")
        self._run_skill_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2a7bef;
            }
        """)
        self._run_skill_btn.clicked.connect(self._run_skill)
        local_btn_layout.addWidget(self._run_skill_btn)
        
        self._refresh_skills_btn = QPushButton("🔄 刷新")
        self._refresh_skills_btn.setStyleSheet("""
            QPushButton {
                background-color: #666666;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #777777;
            }
        """)
        self._refresh_skills_btn.clicked.connect(self._load_skills)
        local_btn_layout.addWidget(self._refresh_skills_btn)
        
        local_btn_layout.addStretch()
        local_layout.addLayout(local_btn_layout)
        
        # ClawHub技能标签页
        clawhub_tab = QWidget()
        clawhub_layout = QVBoxLayout(clawhub_tab)
        
        self._clawhub_skills_list = QListWidget()
        self._clawhub_skills_list.setMinimumHeight(200)
        self._clawhub_skills_list.setStyleSheet("""
            QListWidget {
                background-color: #2a2a2a;
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #333333;
                color: white;
            }
            QListWidget::item:selected {
                background-color: #1e6bde;
            }
        """)
        self._clawhub_skills_list.itemClicked.connect(self._on_clawhub_skill_selected)
        clawhub_layout.addWidget(self._clawhub_skills_list)
        
        clawhub_btn_layout = QHBoxLayout()
        self._install_skill_btn = QPushButton("📥 安装技能")
        self._install_skill_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #5cbf60;
            }
        """)
        self._install_skill_btn.clicked.connect(self._install_clawhub_skill)
        clawhub_btn_layout.addWidget(self._install_skill_btn)
        
        self._refresh_clawhub_btn = QPushButton("🔄 刷新")
        self._refresh_clawhub_btn.setStyleSheet("""
            QPushButton {
                background-color: #666666;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #777777;
            }
        """)
        self._refresh_clawhub_btn.clicked.connect(self._load_clawhub_skills)
        clawhub_btn_layout.addWidget(self._refresh_clawhub_btn)
        
        clawhub_btn_layout.addStretch()
        clawhub_layout.addLayout(clawhub_btn_layout)
        
        # 技能详情区域
        self._skill_details = QGroupBox("技能详情")
        self._skill_details.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        details_layout = QFormLayout(self._skill_details)
        
        self._skill_name_label = QLabel("未选择技能")
        self._skill_name_label.setStyleSheet("color: #ffffff;")
        details_layout.addRow("技能名称:", self._skill_name_label)
        
        self._skill_description_label = QLabel("请选择一个技能查看详情")
        self._skill_description_label.setStyleSheet("color: #ffffff;")
        self._skill_description_label.setWordWrap(True)
        details_layout.addRow("技能描述:", self._skill_description_label)
        
        self._skill_category_label = QLabel("")
        self._skill_category_label.setStyleSheet("color: #ffffff;")
        details_layout.addRow("技能分类:", self._skill_category_label)
        
        self._skill_version_label = QLabel("")
        self._skill_version_label.setStyleSheet("color: #ffffff;")
        details_layout.addRow("版本:", self._skill_version_label)
        
        # 技能参数配置
        self._skill_params = QGroupBox("参数配置")
        self._skill_params.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        params_layout = QFormLayout(self._skill_params)
        
        self._params_container = QWidget()
        self._params_layout = QFormLayout(self._params_container)
        params_layout.addWidget(self._params_container)
        
        # 执行结果区域
        self._execution_result = QGroupBox("执行结果")
        self._execution_result.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        result_layout = QVBoxLayout(self._execution_result)
        
        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setPlaceholderText("执行结果将显示在这里...")
        self._result_text.setMinimumHeight(150)
        self._result_text.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        result_layout.addWidget(self._result_text)
        
        # 添加标签页
        self._tabs.addTab(local_tab, "本地技能")
        self._tabs.addTab(clawhub_tab, "ClawHub技能")
        
        layout.addWidget(self._tabs)
        layout.addWidget(self._skill_details)
        layout.addWidget(self._skill_params)
        layout.addWidget(self._execution_result)
        layout.addStretch()
    
    def _load_skills(self):
        """加载本地技能"""
        try:
            from .skill_engine import skill_engine
            skills = skill_engine.list_available_skills()
            
            self._local_skills_list.clear()
            for skill in skills:
                item = QListWidgetItem(f"{skill['skill_icon']} {skill['skill_name']} - {skill['skill_category']}")
                item.setData(Qt.ItemDataRole.UserRole, skill)
                self._local_skills_list.addItem(item)
        except Exception as e:
            print(f"加载本地技能失败: {e}")
    
    def _load_clawhub_skills(self):
        """加载ClawHub技能"""
        try:
            from .plugin_store import plugin_store
            skills = plugin_store.get_items(item_type=None, category=None, search="", installed_only=False)
            
            self._clawhub_skills_list.clear()
            for skill in skills:
                if skill.type.value == "skill":
                    status = "✅ 已安装" if skill.is_installed else "📥 未安装"
                    item = QListWidgetItem(f"{skill.name} - {skill.category.value} {status}")
                    item.setData(Qt.ItemDataRole.UserRole, skill)
                    self._clawhub_skills_list.addItem(item)
        except Exception as e:
            print(f"加载ClawHub技能失败: {e}")
    
    def _on_skill_selected(self, item):
        """选择本地技能"""
        skill = item.data(Qt.ItemDataRole.UserRole)
        self._show_skill_details(skill)
    
    def _on_clawhub_skill_selected(self, item):
        """选择ClawHub技能"""
        skill = item.data(Qt.ItemDataRole.UserRole)
        self._show_clawhub_skill_details(skill)
    
    def _show_skill_details(self, skill):
        """显示技能详情"""
        self._skill_name_label.setText(skill.get("skill_name", "未知技能"))
        self._skill_description_label.setText(skill.get("skill_description", "无描述"))
        self._skill_category_label.setText(skill.get("skill_category", "未分类"))
        self._skill_version_label.setText(skill.get("skill_version", "1.0.0"))
        
        # 清空参数容器
        for i in reversed(range(self._params_layout.count())):
            widget = self._params_layout.takeAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # 添加默认参数
        input_file = QLineEdit()
        input_file.setPlaceholderText("输入文件路径")
        input_file.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        self._params_layout.addRow("输入文件:", input_file)
        
        output_file = QLineEdit()
        output_file.setPlaceholderText("输出文件路径")
        output_file.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        self._params_layout.addRow("输出文件:", output_file)
    
    def _show_clawhub_skill_details(self, skill):
        """显示ClawHub技能详情"""
        self._skill_name_label.setText(skill.name)
        self._skill_description_label.setText(skill.description)
        self._skill_category_label.setText(skill.category.value)
        self._skill_version_label.setText(skill.version)
        
        # 清空参数容器
        for i in reversed(range(self._params_layout.count())):
            widget = self._params_layout.takeAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # 添加默认参数
        input_file = QLineEdit()
        input_file.setPlaceholderText("输入文件路径")
        input_file.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        self._params_layout.addRow("输入文件:", input_file)
        
        output_file = QLineEdit()
        output_file.setPlaceholderText("输出文件路径")
        output_file.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        self._params_layout.addRow("输出文件:", output_file)
    
    def _run_skill(self):
        """运行技能"""
        current_item = self._local_skills_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先选择一个技能")
            return
        
        skill = current_item.data(Qt.ItemDataRole.UserRole)
        skill_id = skill.get("skill_id")
        
        # 获取参数
        input_file = self._params_layout.itemAt(0).widget()
        output_file = self._params_layout.itemAt(2).widget()
        
        inputs = {
            "input_file": input_file.text() if input_file else "",
            "output_file": output_file.text() if output_file else ""
        }
        
        self._result_text.clear()
        self._result_text.append(f"▶ 开始执行技能: {skill.get('skill_name')}")
        
        def progress_callback(progress, message):
            self._result_text.append(f"[{progress}%] {message}")
        
        try:
            from .skill_engine import skill_engine
            result = skill_engine.execute_skill(skill_id, inputs, progress_callback)
            
            if result.get("success"):
                self._result_text.append("✅ 技能执行成功！")
                if result.get("outputs"):
                    self._result_text.append(f"输出: {result.get('outputs')}")
                if result.get("execution_time"):
                    self._result_text.append(f"执行时间: {result.get('execution_time'):.2f} 秒")
            else:
                self._result_text.append(f"❌ 技能执行失败: {result.get('error')}")
        except Exception as e:
            self._result_text.append(f"❌ 执行技能时出错: {e}")
    
    def _install_clawhub_skill(self):
        """安装ClawHub技能"""
        current_item = self._clawhub_skills_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先选择一个技能")
            return
        
        skill = current_item.data(Qt.ItemDataRole.UserRole)
        
        if skill.is_installed:
            QMessageBox.information(self, "提示", "该技能已经安装")
            return
        
        def progress_callback(progress, message):
            self._result_text.append(f"[{progress}%] {message}")
        
        try:
            from .plugin_store import plugin_store
            success, message = plugin_store.install_item(skill.id, progress_callback)
            
            if success:
                self._result_text.append("✅ 技能安装成功！")
                self._load_clawhub_skills()
            else:
                self._result_text.append(f"❌ 技能安装失败: {message}")
        except Exception as e:
            self._result_text.append(f"❌ 安装技能时出错: {e}")


class CustomAPIWidget(QWidget):
    """自定义API接入组件"""
    
    def __init__(self):
        super().__init__()
        self._init_ui()
        self._load_configs()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        header = QLabel("🔌 自定义API接入")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)
        
        desc = QLabel("配置自定义AI模型API，支持灵活的接口地址、请求头和参数映射规则")
        desc.setStyleSheet("color: #ffffff;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # API 基本信息
        api_group = QGroupBox("API 基本信息")
        api_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        api_layout = QFormLayout(api_group)
        
        self._api_name_input = QLineEdit()
        self._api_name_input.setPlaceholderText("API 名称")
        self._api_name_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 12px;
            }
        """)
        api_layout.addRow("API 名称:", self._api_name_input)
        
        self._api_url_input = QLineEdit()
        self._api_url_input.setPlaceholderText("API 接口地址")
        self._api_url_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 12px;
            }
        """)
        api_layout.addRow("接口地址:", self._api_url_input)
        
        self._api_method_combo = QComboBox()
        self._api_method_combo.addItems(["POST", "GET"])
        self._api_method_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 12px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: white;
                selection-background-color: #1e6bde;
            }
        """)
        api_layout.addRow("请求方法:", self._api_method_combo)
        
        # 请求头配置
        headers_group = QGroupBox("请求头配置")
        headers_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        headers_layout = QVBoxLayout(headers_group)
        
        self._headers_table = QTableWidget()
        self._headers_table.setColumnCount(2)
        self._headers_table.setHorizontalHeaderLabels(["键", "值"])
        self._headers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._headers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._headers_table.setColumnWidth(0, 150)
        self._headers_table.setMinimumHeight(100)
        self._headers_table.setStyleSheet("""
            QTableWidget {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #333333;
                border-radius: 4px;
            }
            QTableWidget::item {
                color: white;
            }
        """)
        headers_layout.addWidget(self._headers_table)
        
        headers_btn_layout = QHBoxLayout()
        self._add_header_btn = QPushButton("添加")
        self._add_header_btn.clicked.connect(self._add_header)
        self._add_header_btn.setStyleSheet("color: #ffffff;")
        headers_btn_layout.addWidget(self._add_header_btn)
        
        self._del_header_btn = QPushButton("删除")
        self._del_header_btn.clicked.connect(self._delete_header)
        self._del_header_btn.setStyleSheet("color: #ffffff;")
        headers_btn_layout.addWidget(self._del_header_btn)
        
        headers_btn_layout.addStretch()
        headers_layout.addLayout(headers_btn_layout)
        
        # 参数映射规则
        params_group = QGroupBox("参数映射规则")
        params_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        params_layout = QVBoxLayout(params_group)
        
        self._params_table = QTableWidget()
        self._params_table.setColumnCount(2)
        self._params_table.setHorizontalHeaderLabels(["系统参数", "API 参数"])
        self._params_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._params_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._params_table.setColumnWidth(0, 150)
        self._params_table.setMinimumHeight(100)
        self._params_table.setStyleSheet("""
            QTableWidget {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #333333;
                border-radius: 4px;
            }
            QTableWidget::item {
                color: white;
            }
        """)
        params_layout.addWidget(self._params_table)
        
        params_btn_layout = QHBoxLayout()
        self._add_param_btn = QPushButton("添加")
        self._add_param_btn.clicked.connect(self._add_param)
        self._add_param_btn.setStyleSheet("color: #ffffff;")
        params_btn_layout.addWidget(self._add_param_btn)
        
        self._del_param_btn = QPushButton("删除")
        self._del_param_btn.clicked.connect(self._delete_param)
        self._del_param_btn.setStyleSheet("color: #ffffff;")
        params_btn_layout.addWidget(self._del_param_btn)
        
        params_btn_layout.addStretch()
        params_layout.addLayout(params_btn_layout)
        
        # 测试区域
        test_group = QGroupBox("测试连接")
        test_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        test_layout = QVBoxLayout(test_group)
        
        self._test_prompt = QTextEdit()
        self._test_prompt.setPlaceholderText("输入测试提示词...")
        self._test_prompt.setMinimumHeight(80)
        self._test_prompt.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        test_layout.addWidget(self._test_prompt)
        
        self._test_response = QTextEdit()
        self._test_response.setReadOnly(True)
        self._test_response.setPlaceholderText("测试响应将显示在这里...")
        self._test_response.setMinimumHeight(100)
        self._test_response.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        test_layout.addWidget(self._test_response)
        
        # 按钮布局
        btn_layout = QHBoxLayout()
        
        self._test_btn = QPushButton("🔍 测试连接")
        self._test_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2a7bef;
            }
        """)
        self._test_btn.clicked.connect(self._test_connection)
        btn_layout.addWidget(self._test_btn)
        
        self._save_btn = QPushButton("💾 保存配置")
        self._save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #5cbf60;
            }
        """)
        self._save_btn.clicked.connect(self._save_config)
        btn_layout.addWidget(self._save_btn)
        
        self._reset_btn = QPushButton("🔄 重置")
        self._reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #666666;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #777777;
            }
        """)
        self._reset_btn.clicked.connect(self._reset_config)
        btn_layout.addWidget(self._reset_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # API 模板市场
        template_group = QGroupBox("API 模板市场")
        template_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        template_layout = QVBoxLayout(template_group)
        
        self._templates_list = QListWidget()
        self._templates_list.setMinimumHeight(150)
        self._templates_list.setStyleSheet("""
            QListWidget {
                background-color: #2a2a2a;
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #333333;
                color: white;
            }
            QListWidget::item:selected {
                background-color: #1e6bde;
            }
        """)
        template_layout.addWidget(self._templates_list)
        
        template_btn_layout = QHBoxLayout()
        self._load_template_btn = QPushButton("加载模板")
        self._load_template_btn.clicked.connect(self._load_template)
        self._load_template_btn.setStyleSheet("color: #ffffff;")
        template_btn_layout.addWidget(self._load_template_btn)
        
        self._share_template_btn = QPushButton("分享模板")
        self._share_template_btn.clicked.connect(self._share_template)
        self._share_template_btn.setStyleSheet("color: #ffffff;")
        template_btn_layout.addWidget(self._share_template_btn)
        
        template_btn_layout.addStretch()
        template_layout.addLayout(template_btn_layout)
        
        layout.addWidget(api_group)
        layout.addWidget(headers_group)
        layout.addWidget(params_group)
        layout.addWidget(test_group)
        layout.addWidget(template_group)
        layout.addStretch()
        
        # 加载默认模板
        self._load_default_templates()
    
    def _add_header(self):
        """添加请求头"""
        row = self._headers_table.rowCount()
        self._headers_table.insertRow(row)
        self._headers_table.setItem(row, 0, QTableWidgetItem("Authorization"))
        self._headers_table.setItem(row, 1, QTableWidgetItem("Bearer {api_key}"))
    
    def _delete_header(self):
        """删除请求头"""
        current_row = self._headers_table.currentRow()
        if current_row >= 0:
            self._headers_table.removeRow(current_row)
    
    def _add_param(self):
        """添加参数映射"""
        row = self._params_table.rowCount()
        self._params_table.insertRow(row)
        self._params_table.setItem(row, 0, QTableWidgetItem("prompt"))
        self._params_table.setItem(row, 1, QTableWidgetItem("prompt"))
    
    def _delete_param(self):
        """删除参数映射"""
        current_row = self._params_table.currentRow()
        if current_row >= 0:
            self._params_table.removeRow(current_row)
    
    def _test_connection(self):
        """测试API连接"""
        api_name = self._api_name_input.text()
        api_url = self._api_url_input.text()
        method = self._api_method_combo.currentText()
        prompt = self._test_prompt.toPlainText()
        
        if not api_name or not api_url:
            QMessageBox.warning(self, "提示", "请填写API名称和接口地址")
            return
        
        if not prompt:
            QMessageBox.warning(self, "提示", "请输入测试提示词")
            return
        
        # 构建请求头
        headers = {}
        for row in range(self._headers_table.rowCount()):
            key_item = self._headers_table.item(row, 0)
            value_item = self._headers_table.item(row, 1)
            if key_item and value_item:
                headers[key_item.text()] = value_item.text()
        
        # 构建请求参数
        params = {}
        for row in range(self._params_table.rowCount()):
            sys_param_item = self._params_table.item(row, 0)
            api_param_item = self._params_table.item(row, 1)
            if sys_param_item and api_param_item:
                if sys_param_item.text() == "prompt":
                    params[api_param_item.text()] = prompt
        
        self._test_response.clear()
        self._test_response.append(f"📤 发送测试请求到: {api_url}\n")
        self._test_response.append(f"方法: {method}\n")
        self._test_response.append(f"请求头: {json.dumps(headers, indent=2)}\n")
        self._test_response.append(f"请求参数: {json.dumps(params, indent=2)}\n\n")
        self._test_response.append("📥 响应:\n")
        
        class TestWorker(QThread):
            finished = pyqtSignal(bool, str)
            
            def __init__(self, api_url, method, headers, params):
                super().__init__()
                self.api_url = api_url
                self.method = method
                self.headers = headers
                self.params = params
            
            def run(self):
                try:
                    import requests
                    
                    if self.method == "POST":
                        response = requests.post(self.api_url, json=self.params, headers=self.headers, timeout=10)
                    else:
                        response = requests.get(self.api_url, params=self.params, headers=self.headers, timeout=10)
                    
                    response.raise_for_status()
                    self.finished.emit(True, response.text)
                except Exception as e:
                    self.finished.emit(False, str(e))
        
        def on_finished(success: bool, response: str):
            if success:
                self._test_response.append("✅ 连接成功！\n")
                self._test_response.append(response)
            else:
                self._test_response.append(f"❌ 连接失败: {response}")
        
        worker = TestWorker(api_url, method, headers, params)
        worker.finished.connect(on_finished)
        worker.start()
    
    def _save_config(self):
        """保存配置"""
        api_name = self._api_name_input.text()
        api_url = self._api_url_input.text()
        
        if not api_name or not api_url:
            QMessageBox.warning(self, "提示", "请填写API名称和接口地址")
            return
        
        # 构建配置
        config = {
            "name": api_name,
            "url": api_url,
            "method": self._api_method_combo.currentText(),
            "headers": {},
            "params": {}
        }
        
        # 添加请求头
        for row in range(self._headers_table.rowCount()):
            key_item = self._headers_table.item(row, 0)
            value_item = self._headers_table.item(row, 1)
            if key_item and value_item:
                config["headers"][key_item.text()] = value_item.text()
        
        # 添加参数映射
        for row in range(self._params_table.rowCount()):
            sys_param_item = self._params_table.item(row, 0)
            api_param_item = self._params_table.item(row, 1)
            if sys_param_item and api_param_item:
                config["params"][sys_param_item.text()] = api_param_item.text()
        
        # 保存到文件
        try:
            import os
            config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "api_configs")
            os.makedirs(config_dir, exist_ok=True)
            
            config_file = os.path.join(config_dir, f"{api_name.replace(' ', '_')}.json")
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            QMessageBox.information(self, "成功", f"API 配置已保存到 {config_file}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存配置失败: {e}")
    
    def _reset_config(self):
        """重置配置"""
        self._api_name_input.clear()
        self._api_url_input.clear()
        self._api_method_combo.setCurrentIndex(0)
        self._headers_table.setRowCount(0)
        self._params_table.setRowCount(0)
        self._test_prompt.clear()
        self._test_response.clear()
    
    def _load_configs(self):
        """加载已保存的配置"""
        try:
            import os
            config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "api_configs")
            if os.path.exists(config_dir):
                for file in os.listdir(config_dir):
                    if file.endswith('.json'):
                        file_path = os.path.join(config_dir, file)
                        with open(file_path, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                        # 可以在这里添加到下拉列表或其他地方
        except Exception as e:
            print(f"加载配置失败: {e}")
    
    def _load_default_templates(self):
        """加载默认模板"""
        templates = [
            {"name": "OpenAI API", "description": "OpenAI 官方 API 模板"},
            {"name": "DeepSeek API", "description": "DeepSeek 官方 API 模板"},
            {"name": "豆包 API", "description": "豆包官方 API 模板"},
            {"name": "智谱 AI API", "description": "智谱 AI 官方 API 模板"},
            {"name": "通义千问 API", "description": "通义千问官方 API 模板"}
        ]
        
        for template in templates:
            item = QListWidgetItem(f"{template['name']} - {template['description']}")
            item.setData(Qt.ItemDataRole.UserRole, template)
            self._templates_list.addItem(item)
    
    def _load_template(self):
        """加载模板"""
        current = self._templates_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选择一个模板")
            return
        
        template = current.data(Qt.ItemDataRole.UserRole)
        if template['name'] == "OpenAI API":
            self._api_name_input.setText("OpenAI API")
            self._api_url_input.setText("https://api.openai.com/v1/chat/completions")
            self._api_method_combo.setCurrentText("POST")
            
            # 清空现有数据
            self._headers_table.setRowCount(0)
            self._params_table.setRowCount(0)
            
            # 添加默认请求头
            self._add_header()
            self._headers_table.setItem(0, 1, QTableWidgetItem("Bearer {api_key}"))
            
            # 添加默认参数映射
            self._add_param()
            self._params_table.setItem(0, 1, QTableWidgetItem("messages[0].content"))
            
            # 添加更多参数
            row = self._params_table.rowCount()
            self._params_table.insertRow(row)
            self._params_table.setItem(row, 0, QTableWidgetItem("model"))
            self._params_table.setItem(row, 1, QTableWidgetItem("model"))
        
        QMessageBox.information(self, "成功", f"已加载 {template['name']} 模板")
    
    def _share_template(self):
        """分享模板"""
        api_name = self._api_name_input.text()
        if not api_name:
            QMessageBox.warning(self, "提示", "请先填写API名称")
            return
        
        # 构建配置
        config = {
            "name": api_name,
            "url": self._api_url_input.text(),
            "method": self._api_method_combo.currentText(),
            "headers": {},
            "params": {}
        }
        
        # 添加请求头
        for row in range(self._headers_table.rowCount()):
            key_item = self._headers_table.item(row, 0)
            value_item = self._headers_table.item(row, 1)
            if key_item and value_item:
                config["headers"][key_item.text()] = value_item.text()
        
        # 添加参数映射
        for row in range(self._params_table.rowCount()):
            sys_param_item = self._params_table.item(row, 0)
            api_param_item = self._params_table.item(row, 1)
            if sys_param_item and api_param_item:
                config["params"][sys_param_item.text()] = api_param_item.text()
        
        # 复制到剪贴板
        import json
        config_str = json.dumps(config, indent=2, ensure_ascii=False)
        
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(config_str)
        
        QMessageBox.information(self, "成功", "模板配置已复制到剪贴板，请分享给其他用户")


class ModelTestWidget(QWidget):
    """模型测试组件"""
    
    def __init__(self):
        super().__init__()
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        header = QLabel("🧪 模型测试")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)
        
        config_layout = QHBoxLayout()
        
        label1 = QLabel("模型来源:")
        label1.setStyleSheet("color: #ffffff;")
        config_layout.addWidget(label1)
        self._source_combo = QComboBox()
        self._source_combo.addItems(["Ollama (本地)", "DeepSeek", "豆包", "OpenAI", "智谱 AI", "自定义 API"])
        self._source_combo.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        config_layout.addWidget(self._source_combo)
        
        label2 = QLabel("模型:")
        label2.setStyleSheet("color: #ffffff;")
        config_layout.addWidget(label2)
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        config_layout.addWidget(self._model_combo)
        
        layout.addLayout(config_layout)
        
        self._prompt_input = QTextEdit()
        self._prompt_input.setPlaceholderText("输入测试提示词...")
        self._prompt_input.setMinimumHeight(100)
        self._prompt_input.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        layout.addWidget(self._prompt_input)
        
        btn_layout = QHBoxLayout()
        
        self._test_btn = QPushButton("开始测试")
        self._test_btn.clicked.connect(self._run_test)
        self._test_btn.setStyleSheet("color: #ffffff;")
        btn_layout.addWidget(self._test_btn)
        
        self._clear_btn = QPushButton("清空")
        self._clear_btn.clicked.connect(lambda: self._response_output.clear())
        self._clear_btn.setStyleSheet("color: #ffffff;")
        btn_layout.addWidget(self._clear_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self._response_output = QTextEdit()
        self._response_output.setReadOnly(True)
        self._response_output.setPlaceholderText("模型响应将显示在这里...")
        self._response_output.setMinimumHeight(200)
        self._response_output.setStyleSheet("color: #ffffff; background-color: #2a2a2a;")
        layout.addWidget(self._response_output)
        
        self._on_source_changed(0)
    
    def _on_source_changed(self, index: int):
        """模型来源改变"""
        self._model_combo.clear()
        
        if index == 0:
            try:
                from .ollama_client import ollama_client
                models = ollama_client.list_models()
                for model in models:
                    self._model_combo.addItem(model.display_name, model.name)
            except:
                self._model_combo.addItems(["llama3:8b", "qwen2:7b"])
        elif index == 1:
            self._model_combo.addItems(["deepseek-chat", "deepseek-coder"])
        elif index == 2:
            self._model_combo.addItems(["doubao-pro-4k", "doubao-pro-32k"])
        elif index == 3:
            self._model_combo.addItems(["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"])
        elif index == 4:
            self._model_combo.addItems(["glm-4", "glm-4-flash", "glm-4v"])
        elif index == 5:
            # 加载自定义API
            try:
                import os
                config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "api_configs")
                if os.path.exists(config_dir):
                    for file in os.listdir(config_dir):
                        if file.endswith('.json'):
                            with open(os.path.join(config_dir, file), 'r', encoding='utf-8') as f:
                                config = json.load(f)
                            self._model_combo.addItem(config['name'], config)
            except:
                self._model_combo.addItem("自定义 API")
    
    def _run_test(self):
        """运行测试"""
        prompt = self._prompt_input.toPlainText()
        if not prompt:
            QMessageBox.warning(self, "提示", "请输入测试提示词")
            return
        
        model = self._model_combo.currentData() or self._model_combo.currentText()
        source_index = self._source_combo.currentIndex()
        
        self._response_output.clear()
        self._response_output.append(f"📤 发送: {prompt}\n")
        self._response_output.append("📥 响应:\n")
        
        class GenerateWorker(QThread):
            chunk_received = pyqtSignal(str)
            finished = pyqtSignal(str)
            
            def __init__(self, source_index, model, prompt):
                super().__init__()
                self.source_index = source_index
                self.model = model
                self.prompt = prompt
            
            def run(self):
                try:
                    if self.source_index == 0:
                        from .ollama_client import ollama_client
                        generator = ollama_client.generate(self.model, self.prompt, stream=True)
                    elif self.source_index == 5:
                        # 自定义API处理
                        if isinstance(self.model, dict):
                            import requests
                            
                            # 构建请求头
                            headers = {}
                            for key, value in self.model.get('headers', {}).items():
                                headers[key] = value.replace('{api_key}', 'test_api_key')
                            
                            # 构建请求参数
                            params = {}
                            for sys_param, api_param in self.model.get('params', {}).items():
                                if sys_param == "prompt":
                                    # 处理嵌套参数
                                    if '.' in api_param:
                                        parts = api_param.split('.')
                                        if parts[0] == 'messages':
                                            index = int(parts[1].strip('[]'))
                                            if index not in params:
                                                params[index] = {}
                                            params[index][parts[2]] = self.prompt
                                    else:
                                        params[api_param] = self.prompt
                            
                            # 发送请求
                            if self.model.get('method', 'POST') == 'POST':
                                response = requests.post(self.model['url'], json=params, headers=headers, timeout=10)
                            else:
                                response = requests.get(self.model['url'], params=params, headers=headers, timeout=10)
                            
                            response.raise_for_status()
                            self.finished.emit(f"\n{response.text}\n\n✅ 完成")
                        else:
                            self.finished.emit("\n❌ 错误: 自定义 API 配置无效")
                    else:
                        from .cloud_api import cloud_api_service
                        providers = ["", "deepseek", "doubao", "openai", "zhipu"]
                        provider = providers[self.source_index]
                        
                        if not cloud_api_service.is_configured(provider):
                            self.finished.emit(f"\n❌ 错误: {provider} API 未配置")
                            return
                        
                        generator = cloud_api_service.chat(
                            provider,
                            [{"role": "user", "content": self.prompt}],
                            stream=True
                        )
                        
                        for chunk in generator:
                            self.chunk_received.emit(chunk)
                        
                        self.finished.emit("\n\n✅ 完成")
                    
                except Exception as e:
                    self.finished.emit(f"\n❌ 错误: {e}")
        
        def on_chunk(chunk: str):
            self._response_output.insertPlainText(chunk)
            self._response_output.ensureCursorVisible()
        
        def on_finished(msg: str):
            if msg:
                self._response_output.append(msg)
        
        worker = GenerateWorker(source_index, model, prompt)
        worker.chunk_received.connect(on_chunk)
        worker.finished.connect(on_finished)
        worker.start()
        
        self._generate_worker = worker


class ModelManagementModule(QWidget):
    """模型管理模块"""
    
    def __init__(self):
        super().__init__()
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        header = QFrame()
        header.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 15, 20, 15)
        
        title = QLabel("🤖 模型管理")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        desc = QLabel("管理本地大模型、云端 API 和自动化运营配置")
        desc.setStyleSheet("color: #ffffff;")
        header_layout.addWidget(desc)
        
        layout.addWidget(header)
        
        self._tabs = QTabWidget()
        # 设置标签页为顶部横向排列
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #333333;
                border-radius: 8px;
                background-color: #1a1a1a;
                margin-top: 2px;
            }
            QTabBar::tab {
                background-color: #2a2a2a;
                color: #ffffff;
                border: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 12px 20px;
                font-size: 13px;
                min-width: 120px;
                height: 40px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                color: #ffffff;
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-bottom: none;
            }
            QTabBar::tab:hover:!selected {
                color: #ffffff;
                background-color: #333333;
            }
        """)
        
        scroll1 = QScrollArea()
        scroll1.setWidgetResizable(True)
        scroll1.setWidget(OllamaStatusWidget())
        self._tabs.addTab(scroll1, "🏠 Ollama 本地模型")
        
        scroll2 = QScrollArea()
        scroll2.setWidgetResizable(True)
        scroll2.setWidget(CloudAPIConfigWidget())
        self._tabs.addTab(scroll2, "☁️ 云端 API")
        
        scroll3 = QScrollArea()
        scroll3.setWidgetResizable(True)
        scroll3.setWidget(OpenClawConfigWidget())
        self._tabs.addTab(scroll3, "🤖 OpenClaw 自动化")
        
        scroll4 = QScrollArea()
        scroll4.setWidgetResizable(True)
        scroll4.setWidget(ModelTestWidget())
        self._tabs.addTab(scroll4, "🧪 模型测试")
        
        scroll5 = QScrollArea()
        scroll5.setWidgetResizable(True)
        scroll5.setWidget(CustomAPIWidget())
        self._tabs.addTab(scroll5, "🔌 自定义API")
        
        scroll6 = QScrollArea()
        scroll6.setWidgetResizable(True)
        scroll6.setWidget(SkillInterfaceWidget())
        self._tabs.addTab(scroll6, "⚡ AI技能")
        
        layout.addWidget(self._tabs)
