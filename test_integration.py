#!/usr/bin/env python3
"""
集成测试脚本 - 验证真实 UI 交互链路
"""

import os
import sys
import time

# 必须先创建 QApplication
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication(sys.argv)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

test_video = os.path.join(os.path.dirname(__file__), "素材库", "test_video.mp4")

print("=== 集成测试 ===")

# 测试 1: VideoProcessor 自动路径检测
print("\n测试 1: VideoProcessor 自动路径检测")
try:
    from app.modules.lego.video_processor import VideoProcessor
    processor = VideoProcessor()
    print(f"  ✅ VideoProcessor 创建成功")
    print(f"  FFmpeg路径: {processor.ffmpeg_path}")
    print(f"  ffprobe路径: {processor.ffprobe_path}")
    print(f"  GPU编码器: {processor.gpu_encoder}")
    print(f"  FFmpeg路径存在: {os.path.exists(processor.ffmpeg_path)}")
except Exception as e:
    print(f"  ❌ VideoProcessor 异常: {e}")
    import traceback
    traceback.print_exc()

# 测试 2: ffmpeg_utils 路径检测
print("\n测试 2: ffmpeg_utils 路径检测")
try:
    from app.core.ffmpeg_utils import find_ffmpeg
    ffmpeg_path = find_ffmpeg()
    print(f"  ✅ find_ffmpeg 返回: {ffmpeg_path}")
    print(f"  路径存在: {os.path.exists(ffmpeg_path)}")
except Exception as e:
    print(f"  ❌ ffmpeg_utils 异常: {e}")

# 测试 3: DependencyChecker 检测
print("\n测试 3: DependencyChecker FFmpeg 检测")
try:
    from app.main_qt6 import DependencyChecker
    result = DependencyChecker.check_ffmpeg()
    print(f"  ✅ check_ffmpeg 返回: {result}")
except Exception as e:
    print(f"  ❌ DependencyChecker 异常: {e}")

# 测试 4: TimelineWidget 完整导入流程
print("\n测试 4: TimelineWidget 完整导入流程")
try:
    from app.modules.lego.timeline_widget import TimelineWidget
    
    timeline = TimelineWidget()
    print("  ✅ TimelineWidget 创建成功")
    
    # 添加轨道 - 需要传入 name 和 track_type
    timeline.add_track("Video Track 1", "video")
    print("  ✅ 添加轨道成功")
    
    # 获取视频信息
    from app.modules.lego.video_processor import get_video_info
    info = get_video_info(test_video)
    duration = info.duration if info else 10.0
    
    # 添加片段
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
        
        # 等待缩略图和波形生成
        print("  等待缩略图和波形生成...")
        for i in range(5):
            time.sleep(0.5)
            
            # 检查缩略图缓存
            if hasattr(widget, '_thumbnail_cache') and widget._thumbnail_cache:
                print(f"  ✅ 缩略图缓存已生成: {len(widget._thumbnail_cache)} 张")
                break
        
        # 检查波形缓存
        if hasattr(widget, '_waveform_peaks') and widget._waveform_peaks:
            print(f"  ✅ 波形缓存已生成: {len(widget._waveform_peaks)} 采样点")
            print(f"  波形峰值范围: {min(widget._waveform_peaks):.3f} ~ {max(widget._waveform_peaks):.3f}")
        else:
            print("  ⚠️ 波形缓存为空或尚未生成")
            
    else:
        print("  ❌ ClipWidget 创建失败")
except Exception as e:
    print(f"  ❌ TimelineWidget 异常: {e}")
    import traceback
    traceback.print_exc()

# 测试 5: EditorModule 初始化
print("\n测试 5: EditorModule 初始化")
try:
    from app.modules.lego.editor_module import EditorModule
    
    editor = EditorModule()
    print("  ✅ EditorModule 创建成功")
    
    # 检查媒体播放器和视频控件
    if hasattr(editor, '_media_player'):
        print("  ✅ 媒体播放器已初始化")
    if hasattr(editor, '_video_widget'):
        print("  ✅ 视频控件已初始化")
    if hasattr(editor, '_audio_output'):
        print("  ✅ 音频输出已初始化")
        
except Exception as e:
    print(f"  ❌ EditorModule 异常: {e}")
    import traceback
    traceback.print_exc()

print("\n所有集成测试完成!")
