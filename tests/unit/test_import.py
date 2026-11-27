"""
测试导入
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("测试导入...")

try:
    print("1. 导入 PySide6...")
    from PySide6.QtWidgets import QApplication
    print("   ✅ PySide6 导入成功")
except Exception as e:
    print(f"   ❌ PySide6 导入失败: {e}")

try:
    print("2. 导入 lego 模块...")
    from modules.lego import MainWindow
    print("   ✅ lego 模块导入成功")
except Exception as e:
    print(f"   ❌ lego 模块导入失败: {e}")

try:
    print("3. 创建 QApplication...")
    app = QApplication(sys.argv)
    print("   ✅ QApplication 创建成功")
except Exception as e:
    print(f"   ❌ QApplication 创建失败: {e}")

try:
    print("4. 创建 MainWindow...")
    window = MainWindow()
    print("   ✅ MainWindow 创建成功")
except Exception as e:
    print(f"   ❌ MainWindow 创建失败: {e}")

print("\n所有测试完成！")
