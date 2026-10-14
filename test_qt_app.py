#!/usr/bin/env python3
"""
正确的 PyQt6 测试脚本 - 需要先创建 QApplication
"""

import os
import sys
import subprocess
import time

# 必须先创建 QApplication
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ffmpeg_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffmpeg.exe")
test_video = os.path.join(os.path.dirname(__file__), "素材库", "test_video.mp4")

print("=== PyQt6 测试 ===")

# 测试 1: PyQt6
print("\n测试 1: PyQt6")
try:
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtCore import QByteArray
    print("  ✅ PyQt6 导入成功")
except Exception as e:
    print(f"  ❌ PyQt6 导入失败: {e}")

# 测试 2: ffmpeg_service
print("\n测试 2: ffmpeg_service")
try:
    from app.core.ffmpeg_service import ffmpeg_service
    print("  ✅ ffmpeg_service 导入成功")
    print(f"  FFmpeg路径: {ffmpeg_service._ffmpeg_path}")
except Exception as e:
    print(f"  ❌ ffmpeg_service 导入失败: {e}")

# 测试 3: 帧提取
print("\n测试 3: 帧提取")
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

# 测试 5: 波形生成
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

# 测试 6: 视频元数据
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

# 测试 7: TimelineWidget
print("\n测试 7: TimelineWidget")
try:
    from app.modules.lego.timeline_widget import TimelineWidget
    timeline = TimelineWidget()
    print("  ✅ TimelineWidget 创建成功")
    
    info = get_video_info(test_video, ffprobe_path=ffprobe_path)
    duration = info.duration if info else 10.0
    
    clip_data = {
        "id": f"clip_{int(time.time() * 1000)}",
        "name": os.path.basename(test_video),
        "path": test_video,
        "start_time": 0,
        "duration": duration,
        "in_point": 0,
        "out_point": duration,
        "track": 0,
    }
    
    widget = timeline.add_clip(clip_data, 0)
    if widget:
        print(f"  ✅ ClipWidget 创建成功")
        print(f"  Widget尺寸: {widget.width()}x{widget.height()}")
    else:
        print("  ❌ ClipWidget 创建失败")
except Exception as e:
    print(f"  ❌ TimelineWidget 异常: {e}")
    import traceback
    traceback.print_exc()

print("\n所有测试完成!")
