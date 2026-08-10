#!/usr/bin/env python3
# 测试 win32gui 和 win32con 导入

print("测试 win32gui 和 win32con 导入...")
try:
    import win32gui
    import win32con
    print("✓ win32gui 和 win32con 导入成功")
except ImportError as e:
    print(f"✗ win32gui 或 win32con 导入失败: {e}")

print("测试完成！")
