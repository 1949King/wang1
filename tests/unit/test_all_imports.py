#!/usr/bin/env python3
# 测试所有导入

print("测试导入...")

# 测试 win32gui 和 win32con
print("\n1. 测试 win32gui 和 win32con:")
try:
    import win32gui
    import win32con
    print("✓ win32gui 和 win32con 导入成功")
except ImportError as e:
    print(f"✗ win32gui 或 win32con 导入失败: {e}")

# 测试 moviepy.editor
print("\n2. 测试 moviepy.editor:")
try:
    from moviepy.editor import VideoFileClip
    print("✓ moviepy.editor 导入成功")
except ImportError as e:
    print(f"✗ moviepy.editor 导入失败: {e}")

# 测试其他关键模块
print("\n3. 测试其他关键模块:")
try:
    import cv2
    print("✓ cv2 导入成功")
except ImportError as e:
    print(f"✗ cv2 导入失败: {e}")

try:
    from modules.utils.logger import logger
    print("✓ modules.utils.logger 导入成功")
except ImportError as e:
    print(f"✗ modules.utils.logger 导入失败: {e}")

try:
    from config.settings import Config
    print("✓ config.settings 导入成功")
except ImportError as e:
    print(f"✗ config.settings 导入失败: {e}")

try:
    from modules.plugins.plugin_system import plugin_get_video_info
    print("✓ modules.plugins.plugin_system 导入成功")
except ImportError as e:
    print(f"✗ modules.plugins.plugin_system 导入失败: {e}")

print("\n导入测试完成！")
