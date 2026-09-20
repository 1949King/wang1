import os 
import sys 
import importlib.util 
from PyQt6.QtWidgets import * 
from PyQt6.QtCore import * 
from PyQt6.QtGui import * 
from .plugin_system import BasePlugin, PluginManager, plugins, loaded_plugins

PLUGIN_DIR = "plugins" 
os.makedirs(PLUGIN_DIR, exist_ok=True)

# ==================== PyQt5 插件管理器 ====================
class PyQtPluginManager(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PyQt5 插件管理器")
        self.setGeometry(100, 100, 800, 600)
        self.setStyleSheet("""
            QWidget {
                background-color: #1E1E2E;
                color: #FFFFFF;
            }
            QLabel {
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QListWidget {
                background-color: #2D2D3F;
                border: 1px solid #3D3D4F;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3D3D4F;
            }
            QListWidget::item:hover {
                background-color: #3D3D4F;
            }
            QListWidget::item:selected {
                background-color: #4CAF50;
                color: white;
            }
            QTabWidget::pane {
                border: 1px solid #3D3D4F;
                background-color: #2D2D3F;
            }
            QTabBar::tab {
                background-color: #2D2D3F;
                color: #FFFFFF;
                padding: 8px 16px;
                border-bottom: 1px solid #3D3D4F;
            }
            QTabBar::tab:selected {
                background-color: #4CAF50;
                color: white;
            }
        """)
        
        self.plugin_manager = PluginManager()
        self.init_ui()
        self.load_plugins()
    
    def init_ui(self):
        # 主布局
        main_layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("PyQt5 插件管理器")
        title_label.setFont(QFont("微软雅黑", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 标签页
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # 已安装插件标签页
        self.installed_tab = QWidget()
        self.tab_widget.addTab(self.installed_tab, "已安装插件")
        
        # 已安装插件布局
        installed_layout = QVBoxLayout(self.installed_tab)
        
        # 插件列表
        self.plugin_list = QListWidget()
        installed_layout.addWidget(self.plugin_list)
        
        # 插件信息
        self.plugin_info = QTextEdit()
        self.plugin_info.setReadOnly(True)
        self.plugin_info.setMaximumHeight(150)
        installed_layout.addWidget(self.plugin_info)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 运行插件按钮
        self.run_button = QPushButton("运行插件")
        self.run_button.clicked.connect(self.run_selected_plugin)
        button_layout.addWidget(self.run_button)
        
        # 卸载插件按钮
        self.uninstall_button = QPushButton("卸载插件")
        self.uninstall_button.clicked.connect(self.uninstall_selected_plugin)
        button_layout.addWidget(self.uninstall_button)
        
        # 刷新按钮
        self.refresh_button = QPushButton("刷新列表")
        self.refresh_button.clicked.connect(self.load_plugins)
        button_layout.addWidget(self.refresh_button)
        
        installed_layout.addLayout(button_layout)
        
        # 导入插件标签页
        self.import_tab = QWidget()
        self.tab_widget.addTab(self.import_tab, "导入插件")
        
        # 导入插件布局
        import_layout = QVBoxLayout(self.import_tab)
        
        # 插件文件选择
        file_layout = QHBoxLayout()
        
        self.file_path = QLineEdit()
        file_layout.addWidget(self.file_path)
        
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self.browse_plugin_file)
        file_layout.addWidget(browse_button)
        
        import_layout.addLayout(file_layout)
        
        # 导入按钮
        import_button = QPushButton("导入插件")
        import_button.clicked.connect(self.import_plugin)
        import_layout.addWidget(import_button)
        
        # 导入状态
        self.import_status = QLabel("")
        self.import_status.setAlignment(Qt.AlignCenter)
        import_layout.addWidget(self.import_status)
        
        # 插件列表点击事件
        self.plugin_list.itemClicked.connect(self.on_plugin_selected)
    
    def load_plugins(self):
        """加载插件列表"""
        self.plugin_list.clear()
        
        # 加载基于函数的插件
        for plugin_name in plugins.keys():
            item = QListWidgetItem(plugin_name)
            item.setData(Qt.UserRole, ("function", plugin_name))
            self.plugin_list.addItem(item)
        
        # 加载基于类的插件
        for plugin in loaded_plugins:
            if hasattr(plugin, "get_name"):
                plugin_name = plugin.get_name()
                item = QListWidgetItem(plugin_name)
                item.setData(Qt.UserRole, ("class", plugin))
                self.plugin_list.addItem(item)
    
    def on_plugin_selected(self, item):
        """插件选择事件"""
        plugin_type, plugin_data = item.data(Qt.UserRole)
        info = ""
        
        if plugin_type == "function":
            plugin_name = plugin_data
            info = f"插件名称: {plugin_name}\n"
            info += f"类型: 函数插件\n"
        elif plugin_type == "class":
            plugin = plugin_data
            info = f"插件名称: {plugin.get_name()}\n"
            info += f"类型: 类插件\n"
        
        self.plugin_info.setText(info)
    
    def run_selected_plugin(self):
        """运行选中的插件"""
        selected_items = self.plugin_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "请选择一个插件")
            return
        
        item = selected_items[0]
        plugin_type, plugin_data = item.data(Qt.UserRole)
        
        try:
            if plugin_type == "function":
                plugin_name = plugin_data
                if plugin_name in plugins:
                    result = plugins[plugin_name]()
                    QMessageBox.information(self, "成功", f"插件运行成功: {result}")
                else:
                    QMessageBox.error(self, "错误", "插件不存在")
            elif plugin_type == "class":
                plugin = plugin_data
                result = plugin.run()
                QMessageBox.information(self, "成功", "插件运行成功")
        except Exception as e:
            QMessageBox.error(self, "错误", f"插件运行失败: {str(e)}")
    
    def uninstall_selected_plugin(self):
        """卸载选中的插件"""
        selected_items = self.plugin_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "请选择一个插件")
            return
        
        item = selected_items[0]
        plugin_type, plugin_data = item.data(Qt.UserRole)
        
        if plugin_type == "function":
            plugin_name = plugin_data
            if self.plugin_manager.uninstall_plugin(plugin_name):
                QMessageBox.information(self, "成功", f"插件 '{plugin_name}' 卸载成功")
                self.load_plugins()
            else:
                QMessageBox.error(self, "错误", f"插件 '{plugin_name}' 卸载失败")
        elif plugin_type == "class":
            plugin = plugin_data
            plugin_name = plugin.get_name()
            if self.plugin_manager.uninstall_plugin(plugin_name):
                QMessageBox.information(self, "成功", f"插件 '{plugin_name}' 卸载成功")
                self.load_plugins()
            else:
                QMessageBox.error(self, "错误", f"插件 '{plugin_name}' 卸载失败")
    
    def browse_plugin_file(self):
        """浏览插件文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择插件文件", "", "Python Files (*.py)"
        )
        if file_path:
            self.file_path.setText(file_path)
    
    def import_plugin(self):
        """导入插件"""
        file_path = self.file_path.text().strip()
        if not file_path:
            QMessageBox.warning(self, "警告", "请选择插件文件")
            return
        
        if not os.path.exists(file_path):
            QMessageBox.error(self, "错误", "插件文件不存在")
            return
        
        try:
            success, message = self.plugin_manager.import_plugin(file_path)
            if success:
                self.import_status.setText(f"<font color='green'>{message}</font>")
                self.load_plugins()
            else:
                self.import_status.setText(f"<font color='red'>{message}</font>")
        except Exception as e:
            self.import_status.setText(f"<font color='red'>导入失败: {str(e)}</font>")

# ==================== 测试代码 ====================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    manager = PyQtPluginManager()
    manager.show()
    sys.exit(app.exec_())
