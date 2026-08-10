#!/usr/bin/env python3
"""
简单测试脚本 - 逐个测试组件
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("测试 1: 导入模块")
try:
    from app.core.ffmpeg_service import ffmpeg_service
    print("  ✅ ffmpeg_service 导入成功")
except Exception as e:
    print(f"  ❌ ffmpeg_service 导入失败: {e}")

print("\n测试 2: FFmpeg 可用性")
ffmpeg_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffmpeg.exe")
print(f"  FFmpeg路径: {ffmpeg_path}")
print(f"  路径存在: {os.path.exists(ffmpeg_path)}")

print("\n测试 3: 测试视频")
test_video = os.path.join(os.path.dirname(__file__), "素材库", "test_video.mp4")
print(f"  测试视频: {test_video}")
print(f"  视频存在: {os.path.exists(test_video)}")

print("\n测试 4: 帧提取")
try:
    pixmap = ffmpeg_service.extract_frame(test_video, timestamp=1.0, width=60, height=36)
    if pixmap and not pixmap.isNull():
        print(f"  ✅ 帧提取成功: {pixmap.width()}x{pixmap.height()}")
    else:
        print("  ❌ 帧提取失败")
except Exception as e:
    print(f"  ❌ 帧提取异常: {e}")
    import traceback
    traceback.print_exc()

print("\n测试 5: 波形生成")
try:
    from app.core.waveform_generator import waveform_generator
    data = waveform_generator.generate(test_video, num_samples=100)
    if data and data.peaks:
        print(f"  ✅ 波形生成成功: {len(data.peaks)} 采样点")
        print(f"  峰值范围: {min(data.peaks):.3f} ~ {max(data.peaks):.3f}")
    else:
        print("  ❌ 波形生成失败")
except Exception as e:
    print(f"  ❌ 波形生成异常: {e}")
    import traceback
    traceback.print_exc()

print("\n测试 6: 视频元数据")
try:
    from app.modules.lego.video_processor import get_video_info
    ffprobe_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffprobe.exe")
    info = get_video_info(test_video, ffprobe_path=ffprobe_path)
    if info:
        print(f"  ✅ 元数据读取成功")
        print(f"  时长: {info.duration}秒")
        print(f"  分辨率: {info.width}x{info.height}")
        print(f"  帧率: {info.fps}")
    else:
        print("  ❌ 元数据读取失败")
except Exception as e:
    print(f"  ❌ 元数据读取异常: {e}")
    import traceback
    traceback.print_exc()

print("\n测试完成!")
