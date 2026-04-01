#!/usr/bin/env python3
# 测试优化的视频播放器

import os
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("测试优化的视频播放器...")

# 测试模块导入
try:
    from modules.video_player.optimized_video_player import OptimizedVideoPlayer
    print("✓ 视频播放器模块导入成功")
except Exception as e:
    print(f"✗ 视频播放器模块导入失败: {e}")
    sys.exit(1)

# 测试PyQt5依赖
try:
    from PyQt5.QtWidgets import QApplication
    print("✓ PyQt5依赖检查通过")
except Exception as e:
    print(f"✗ PyQt5依赖检查失败: {e}")
    sys.exit(1)

# 测试win32gui依赖
try:
    import win32gui
    import win32con
    print("✓ win32gui依赖检查通过")
except Exception as e:
    print(f"✗ win32gui依赖检查失败: {e}")
    sys.exit(1)

print("\n所有依赖检查通过！")
print("\n测试完成！")
print("\n注意：")
print("1. 视频播放器需要PyQt5、opencv-python、Pillow和pywin32依赖")
print("2. 如果缺少依赖，请运行以下命令安装：")
print("   pip install PyQt5 opencv-python Pillow pywin32")
print("3. 播放器会在视频剪辑页面的预览区域显示")
print("4. 双击媒体列表中的视频文件即可开始预览")
