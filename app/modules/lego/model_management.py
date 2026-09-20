'''
模型管理主模块 (ModelManagementModule)
========================================
整合本地大模型 (Ollama)、云端 API
卡片式列表布局，点击展开配置详情，一键切换激活

子模块:
  model_config.py      — 共享配置/常量
  model_card.py        — 模型卡片组件
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

from .model_config import (
    ModelConfig,
    PROVIDERS,
    CUSTOM_PROVIDERS_FILE,
    ACTIVE_PROVIDER_FILE,
)
from .model_card import ModelCardWidget

logger = logging.getLogger("AI短剧编辑器.model_mgmt")

class ModelManagementModule(QWidget):
    """模型管理模块 - 模型广场"""

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

        # 网关统计 tab：token 消耗 / 成本 / 成功率 / 缓存命中 / 异常告警
        from .gateway_stats_panel import GatewayStatsPanel
        self._main_tabs.addTab(GatewayStatsPanel(), "📊 网关统计")

        layout.addWidget(self._main_tabs)

        self._status_bar = QStatusBar()
        self._status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #0d0d0d; color: #666666;
                border-top: 1px solid #252525; padding: 6px 12px; font-size: 12px;
            }
        """)
        self._status_bar.showMessage("就绪 - 点击卡片展开配置")
        layout.addWidget(self._status_bar)

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
        try:
            from app.modules.lego.model_config import save_active_provider
            save_active_provider(provider_id)
        except Exception:
            pass
        try:
            from .core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.PROVIDER_ACTIVATED,
                {"provider": provider_id, "name": provider_name},
            )
        except Exception:
            pass

    def _on_config_saved(self, provider_id: str, config: dict[str, Any]):
        provider_name = (PROVIDERS.get(provider_id) or self._custom_providers.get(provider_id) or {}).get("name", provider_id)
        # 保存云端配置后自动激活，避免仍停在 ollama 导致 Agent/文案不走 DeepSeek
        info = PROVIDERS.get(provider_id) or self._custom_providers.get(provider_id) or {}
        if not info.get("is_local"):
            if self._active_provider != provider_id:
                # 直接激活（勿走 toggle：已激活再点会取消）
                for pid, card in self._cards.items():
                    card.set_active(pid == provider_id)
                self._active_provider = provider_id
                self._save_active_provider()
                self._active_label.setText(f"🟢 当前激活: {provider_name}")
                self._active_label.setStyleSheet("font-size: 12px; color: #22c55e; font-weight: 600;")
            self._status_bar.showMessage(
                f"✅ {provider_name} 已保存并激活 — Agent / 文案将优先使用此模型", 5000
            )
            try:
                from app.modules.lego.model_config import save_active_provider
                save_active_provider(provider_id)
            except Exception:
                pass
            try:
                from .core import EventBus, EventType
                EventBus.get_instance().emit(
                    EventType.PROVIDER_ACTIVATED,
                    {"provider": provider_id, "name": provider_name},
                )
            except Exception:
                pass
        else:
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
        """模块激活时恢复上次选择的模型状态；必要时从不可用的 Ollama 切到云端。"""
        try:
            from app.modules.lego.model_config import ensure_active_provider_sensible
            switched = ensure_active_provider_sensible()
            if switched:
                self._active_provider = switched
        except Exception:
            pass
        self._restore_active_state()

    def on_deactivated(self):
        """模块失活时保存当前激活状态，确保重启后恢复"""
        try:
            self._save_active_provider()
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"失活时保存状态失败（非关键）: {e}")
