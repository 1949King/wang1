#!/usr/bin/env python3
"""
测试QColor导入和使用
"""

import sys
print(f"Python版本: {sys.version}")
print(f"Python路径: {sys.path}")

try:
    from PyQt6.QtGui import QColor
    print("QColor导入成功")
    
    # 测试QColor使用
    color = QColor("#ff0000")
    print(f"QColor创建成功: {color.name()}")
    
    print("测试通过！")
except Exception as e:
    print(f"测试失败: {e}")
    import traceback
    traceback.print_exc()
