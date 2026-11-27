"""
内置浏览器窗口组件
提供网页浏览功能，支持前进、后退、刷新、地址栏等基本操作
"""

from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QLineEdit, QPushButton,
    QVBoxLayout, QWidget, QProgressBar, QLabel
)
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QAction, QIcon

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
    WEBENGINE_AVAILABLE = True
except ImportError:
    WEBENGINE_AVAILABLE = False
    QWebEngineView = object
    QWebEnginePage = object


class BrowserWindow(QMainWindow):
    def __init__(self, parent=None, url: str = ""):
        super().__init__(parent)
        self.setWindowTitle("拾光剪影 - 内置浏览器")
        self.setMinimumSize(1024, 768)
        self.resize(1200, 800)
        
        if not WEBENGINE_AVAILABLE:
            self._show_webengine_error()
            return
        
        self._init_ui()
        if url:
            self._load_url(url)
    
    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self._toolbar = QToolBar()
        self._toolbar.setStyleSheet("""
            QToolBar {
                background-color: #1e1e1e;
                border-bottom: 1px solid #333;
                spacing: 4px;
                padding: 4px;
            }
            QToolButton {
                background-color: transparent;
                border: none;
                color: #ccc;
                padding: 6px 10px;
                border-radius: 4px;
            }
            QToolButton:hover {
                background-color: #333;
            }
            QToolButton:pressed {
                background-color: #444;
            }
            QToolButton:disabled {
                color: #666;
            }
        """)
        
        self._back_btn = QPushButton("←")
        self._back_btn.setFixedSize(36, 32)
        self._back_btn.clicked.connect(self._go_back)
        self._toolbar.addWidget(self._back_btn)
        
        self._forward_btn = QPushButton("→")
        self._forward_btn.setFixedSize(36, 32)
        self._forward_btn.clicked.connect(self._go_forward)
        self._toolbar.addWidget(self._forward_btn)
        
        self._reload_btn = QPushButton("↻")
        self._reload_btn.setFixedSize(36, 32)
        self._reload_btn.clicked.connect(self._reload_page)
        self._toolbar.addWidget(self._reload_btn)
        
        self._toolbar.addSeparator()
        
        self._url_edit = QLineEdit()
        self._url_edit.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                color: #fff;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #1e6bde;
            }
        """)
        self._url_edit.returnPressed.connect(self._navigate_to_url)
        self._toolbar.addWidget(self._url_edit)
        
        layout.addWidget(self._toolbar)
        
        self._web_view = QWebEngineView()
        self._web_view.page().titleChanged.connect(self._update_title)
        self._web_view.page().urlChanged.connect(self._update_url)
        self._web_view.page().loadStarted.connect(self._on_load_started)
        self._web_view.page().loadFinished.connect(self._on_load_finished)
        self._web_view.page().loadProgress.connect(self._on_load_progress)
        layout.addWidget(self._web_view)
        
        self._progress_bar = QProgressBar()
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #2a2a2a;
                border: none;
                height: 2px;
            }
            QProgressBar::chunk {
                background-color: #1e6bde;
            }
        """)
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)
        
        self._update_navigation_buttons()
    
    def _show_webengine_error(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        error_label = QLabel("""
            <center>
            <p style="font-size: 18px; color: #ff6b6b; margin-bottom: 20px;">WebEngine 组件不可用</p>
            <p style="font-size: 14px; color: #aaa;">请安装 PySide6 Addons 以使用内置浏览器功能</p>
            <p style="font-size: 12px; color: #666; margin-top: 20px;">pip install PySide6==6.10.2 PySide6-Addons==6.10.2</p>
            </center>
        """)
        layout.addWidget(error_label)
    
    def _load_url(self, url: str):
        if not WEBENGINE_AVAILABLE:
            return
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        self._web_view.load(QUrl(url))
    
    def _go_back(self):
        if self._web_view.history().canGoBack():
            self._web_view.back()
    
    def _go_forward(self):
        if self._web_view.history().canGoForward():
            self._web_view.forward()
    
    def _reload_page(self):
        self._web_view.reload()
    
    def _navigate_to_url(self):
        url = self._url_edit.text().strip()
        if url:
            self._load_url(url)
    
    def _update_title(self, title):
        self.setWindowTitle(f"拾光剪影 - {title}")
    
    def _update_url(self, url):
        self._url_edit.setText(url.toString())
        self._update_navigation_buttons()
    
    def _update_navigation_buttons(self):
        if not WEBENGINE_AVAILABLE:
            return
        self._back_btn.setEnabled(self._web_view.history().canGoBack())
        self._forward_btn.setEnabled(self._web_view.history().canGoForward())
    
    def _on_load_started(self):
        self._progress_bar.show()
        self._progress_bar.setValue(0)
    
    def _on_load_finished(self, success):
        self._progress_bar.hide()
        self._update_navigation_buttons()
    
    def _on_load_progress(self, progress):
        self._progress_bar.setValue(progress)
    
    def set_url(self, url: str):
        self._load_url(url)