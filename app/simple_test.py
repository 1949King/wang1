"""
简单启动脚本 - 用于测试
"""
import sys
import os

print("Python 路径:", sys.executable)
print("当前目录:", os.getcwd())

try:
    from PySide6.QtWidgets import QApplication, QMainWindow, QLabel
    print("PySide6 导入成功")
    
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("测试窗口")
    window.setGeometry(100, 100, 400, 300)
    
    label = QLabel("PySide6 测试成功!", window)
    label.setAlignment(0x84)  # Qt.AlignCenter
    window.setCentralWidget(label)
    
    window.show()
    print("窗口显示成功")
    sys.exit(app.exec())
    
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
