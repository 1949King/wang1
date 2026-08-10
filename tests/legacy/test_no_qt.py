#!/usr/bin/env python3
"""
不导入 PyQt6 的测试脚本
"""

import os
import sys
import subprocess

ffmpeg_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffmpeg.exe")
ffprobe_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffprobe.exe")
test_video = os.path.join(os.path.dirname(__file__), "素材库", "test_video.mp4")

print("=== 不导入 PyQt6 的测试 ===")
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

# 测试波形数据解析
if result.returncode == 0 and len(result.stdout) > 0:
    import struct
    num_samples = len(result.stdout) // 2
    samples = struct.unpack(f"<{num_samples}h", result.stdout)
    max_val = max(abs(min(samples)), abs(max(samples)), 1)
    print(f"采样数: {num_samples}")
    print(f"最大采样值: {max_val}")
    
    # 降采样
    num_peaks = 100
    bucket_size = max(1, len(samples) // num_peaks)
    peaks = []
    for i in range(0, len(samples), bucket_size):
        bucket = samples[i:i + bucket_size]
        if bucket:
            import math
            rms = math.sqrt(sum(x * x for x in bucket) / len(bucket))
            peaks.append(min(1.0, rms / max_val))
    peaks = peaks[:num_peaks]
    print(f"波形峰值数: {len(peaks)}")
    print(f"峰值范围: {min(peaks):.3f} ~ {max(peaks):.3f}")

print("\n测试完成!")
