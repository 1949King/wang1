#!/usr/bin/env python3
"""
直接测试 FFmpeg 命令行
"""

import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ffmpeg_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffmpeg.exe")
ffprobe_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffprobe.exe")
test_video = os.path.join(os.path.dirname(__file__), "素材库", "test_video.mp4")

print(f"FFmpeg路径: {ffmpeg_path}")
print(f"ffprobe路径: {ffprobe_path}")
print(f"测试视频: {test_video}")
print(f"FFmpeg存在: {os.path.exists(ffmpeg_path)}")
print(f"ffprobe存在: {os.path.exists(ffprobe_path)}")
print(f"测试视频存在: {os.path.exists(test_video)}")

print("\n--- 测试 1: FFmpeg 版本 ---")
result = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5)
print(f"返回码: {result.returncode}")
if result.returncode == 0:
    print(f"版本: {result.stdout.split()[2]}")
else:
    print(f"错误: {result.stderr}")

print("\n--- 测试 2: ffprobe 元数据 ---")
result = subprocess.run(
    [ffprobe_path, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", test_video],
    capture_output=True, text=True, timeout=10
)
print(f"返回码: {result.returncode}")
if result.returncode == 0:
    import json
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    for stream in streams:
        codec_type = stream.get("codec_type")
        print(f"  流类型: {codec_type}")
        if codec_type == "video":
            print(f"    分辨率: {stream.get('width')}x{stream.get('height')}")
            print(f"    帧率: {stream.get('r_frame_rate')}")
        elif codec_type == "audio":
            print(f"    采样率: {stream.get('sample_rate')}")
            print(f"    声道数: {stream.get('channels')}")
    format_info = data.get("format", {})
    print(f"  时长: {format_info.get('duration', '未知')}秒")
else:
    print(f"错误: {result.stderr}")

print("\n--- 测试 3: 帧提取 ---")
result = subprocess.run(
    [ffmpeg_path, "-ss", "1.0", "-i", test_video, "-vframes", "1", "-s", "60x36", "-f", "image2pipe", "-vcodec", "png", "-"],
    capture_output=True, timeout=10
)
print(f"返回码: {result.returncode}")
print(f"输出数据长度: {len(result.stdout)}")
if len(result.stdout) > 0:
    print("  ✅ 帧提取成功!")
else:
    print(f"  ❌ 帧提取失败，错误: {result.stderr[:200]}")

print("\n--- 测试 4: 音频提取 ---")
result = subprocess.run(
    [ffmpeg_path, "-i", test_video, "-ac", "1", "-ar", "44100", "-f", "s16le", "-vcodec", "none", "-"],
    capture_output=True, timeout=10
)
print(f"返回码: {result.returncode}")
print(f"输出数据长度: {len(result.stdout)}")
if len(result.stdout) > 0:
    num_samples = len(result.stdout) // 2
    print(f"  ✅ 音频提取成功! 采样数: {num_samples}")
    # 解析 PCM
    import struct
    samples = struct.unpack(f"<{num_samples}h", result.stdout)
    max_val = max(abs(min(samples)), abs(max(samples)), 1)
    print(f"  最大采样值: {max_val}")
else:
    print(f"  ❌ 音频提取失败，错误: {result.stderr[:200]}")

print("\n所有测试完成!")
