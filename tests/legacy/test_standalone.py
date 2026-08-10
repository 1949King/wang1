#!/usr/bin/env python3
"""
完全独立的测试脚本 - 不导入项目模块
"""

import os
import sys
import subprocess

ffmpeg_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffmpeg.exe")
ffprobe_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffprobe.exe")
test_video = os.path.join(os.path.dirname(__file__), "素材库", "test_video.mp4")

print("=== 独立测试 ===")
print(f"FFmpeg路径: {ffmpeg_path}")
print(f"存在: {os.path.exists(ffmpeg_path)}")

# 测试 FFmpeg
print("\n--- FFmpeg 版本 ---")
result = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5)
print(f"返回码: {result.returncode}")
if result.returncode == 0:
    print(f"版本: {result.stdout.split()[2]}")

# 测试帧提取
print("\n--- 帧提取 ---")
cmd = [
    ffmpeg_path, "-ss", "1.0", "-i", test_video,
    "-vframes", "1", "-s", "60x36",
    "-f", "image2pipe", "-vcodec", "png", "-"
]
result = subprocess.run(cmd, capture_output=True, timeout=10)
print(f"返回码: {result.returncode}")
print(f"输出长度: {len(result.stdout)}")
print(f"是否成功: {result.returncode == 0 and len(result.stdout) > 0}")

# 测试音频提取
print("\n--- 音频提取 ---")
cmd = [
    ffmpeg_path, "-i", test_video, "-ac", "1", "-ar", "44100",
    "-f", "s16le", "-vcodec", "none", "-"
]
result = subprocess.run(cmd, capture_output=True, timeout=10)
print(f"返回码: {result.returncode}")
print(f"输出长度: {len(result.stdout)}")

# 测试 PyQt6
print("\n--- PyQt6 ---")
try:
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtCore import QByteArray
    print("PyQt6 导入成功")
    
    # 测试 QPixmap
    byte_array = QByteArray(result.stdout[:100])
    pixmap = QPixmap()
    print(f"QPixmap 创建成功")
except Exception as e:
    print(f"PyQt6 导入失败: {e}")

print("\n测试完成!")
