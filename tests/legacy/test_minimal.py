#!/usr/bin/env python3
"""
最小化测试
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 先测试基础导入
print("测试 1: 基础导入")
try:
    import subprocess
    print("  ✅ subprocess 导入成功")
except Exception as e:
    print(f"  ❌ subprocess 导入失败: {e}")

print("\n测试 2: PySide6")
try:
    from PySide6.QtGui import QPixmap
    from PySide6.QtCore import QByteArray
    print("  ✅ PySide6 导入成功")
except Exception as e:
    print(f"  ❌ PySide6 导入失败: {e}")

print("\n测试 3: ffmpeg_utils")
try:
    from app.core.ffmpeg_utils import find_ffmpeg
    path = find_ffmpeg()
    print(f"  ✅ ffmpeg_utils 导入成功")
    print(f"  FFmpeg路径: {path}")
except Exception as e:
    print(f"  ❌ ffmpeg_utils 导入失败: {e}")

print("\n测试 4: 直接帧提取")
ffmpeg_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffmpeg.exe")
test_video = os.path.join(os.path.dirname(__file__), "素材库", "test_video.mp4")

try:
    cmd = [
        ffmpeg_path, "-ss", "1.0", "-i", test_video,
        "-vframes", "1", "-s", "60x36",
        "-f", "image2pipe", "-vcodec", "png", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=10)
    print(f"  返回码: {result.returncode}")
    print(f"  输出长度: {len(result.stdout)}")
    
    if result.returncode == 0 and result.stdout:
        byte_array = QByteArray(result.stdout)
        pixmap = QPixmap()
        pixmap.loadFromData(byte_array)
        if not pixmap.isNull():
            print(f"  ✅ QPixmap 创建成功: {pixmap.width()}x{pixmap.height()}")
        else:
            print("  ❌ QPixmap 为空")
    else:
        print(f"  ❌ FFmpeg 执行失败")
except Exception as e:
    print(f"  ❌ 异常: {e}")
    import traceback
    traceback.print_exc()

print("\n测试完成!")
