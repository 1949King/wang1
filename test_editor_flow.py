#!/usr/bin/env python3
"""
端到端测试脚本 - 验证视频剪辑完整流程

测试环节：
1. FFmpeg 可用性
2. 视频元数据读取
3. 帧提取（缩略图）
4. 音频波形生成
5. clip_data 创建
6. QMediaPlayer 播放
7. TimelineWidget 导入
"""

import os
import sys
import time
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_ffmpeg_availability():
    """测试 FFmpeg 是否可用"""
    print("\n=== 测试 1: FFmpeg 可用性 ===")
    from app.core.ffmpeg_service import ffmpeg_service
    print(f"FFmpeg路径: {ffmpeg_service._ffmpeg_path}")
    print(f"路径存在: {os.path.exists(ffmpeg_service._ffmpeg_path)}")
    
    try:
        result = subprocess.run([ffmpeg_service._ffmpeg_path, "-version"], 
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"FFmpeg版本: {result.stdout.split()[2]}")
            return True
        else:
            print(f"FFmpeg启动失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"FFmpeg测试异常: {e}")
        return False

def test_video_metadata():
    """测试视频元数据读取"""
    print("\n=== 测试 2: 视频元数据读取 ===")
    from app.modules.lego.video_processor import get_video_info
    
    test_video = find_test_video()
    if not test_video:
        print("未找到测试视频")
        return None
    
    ffprobe_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffprobe.exe")
    
    print(f"测试视频: {test_video}")
    print(f"ffprobe路径: {ffprobe_path}")
    try:
        info = get_video_info(test_video, ffprobe_path=ffprobe_path)
        if info:
            print(f"时长: {info.duration}秒")
            print(f"分辨率: {info.width}x{info.height}")
            print(f"帧率: {info.fps}")
            print(f"音频采样率: {info.sample_rate}")
            return info
        else:
            print("元数据读取失败")
            return None
    except Exception as e:
        print(f"元数据读取异常: {e}")
        return None

def test_frame_extraction():
    """测试帧提取（缩略图）"""
    print("\n=== 测试 3: 帧提取（缩略图）===")
    from app.core.ffmpeg_service import ffmpeg_service
    from PySide6.QtGui import QPixmap
    
    test_video = find_test_video()
    if not test_video:
        print("未找到测试视频")
        return False
    
    try:
        pixmap = ffmpeg_service.extract_frame(test_video, timestamp=1.0, width=60, height=36)
        if pixmap and not pixmap.isNull():
            print(f"缩略图尺寸: {pixmap.width()}x{pixmap.height()}")
            print("帧提取成功!")
            return True
        else:
            print("帧提取失败: 返回空 QPixmap")
            return False
    except Exception as e:
        print(f"帧提取异常: {e}")
        return False

def test_waveform_generation():
    """测试音频波形生成"""
    print("\n=== 测试 5: 音频波形生成 ===")
    from app.core.waveform_generator import waveform_generator
    
    test_video = find_test_video()
    if not test_video:
        print("未找到测试视频")
        return False
    
    try:
        data = waveform_generator.generate(test_video, num_samples=100)
        if data and data.peaks:
            print(f"波形采样数: {len(data.peaks)}")
            print(f"波形峰值范围: {min(data.peaks):.3f} ~ {max(data.peaks):.3f}")
            print(f"音频时长: {data.duration:.2f}秒")
            if max(data.peaks) > 0.01:
                print("波形数据有效!")
                return True
            else:
                print("波形数据全零，可能无效")
                return False
        else:
            print("波形生成失败")
            return False
    except Exception as e:
        print(f"波形生成异常: {e}")
        return False

def test_clip_data_creation():
    """测试 clip_data 创建"""
    print("\n=== 测试 6: clip_data 创建 ===")
    test_video = find_test_video()
    if not test_video:
        print("未找到测试视频")
        return None
    
    from app.modules.lego.video_processor import get_video_info
    ffprobe_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffprobe.exe")
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
        "effects": {},
        "transitions": [],
    }
    
    print(f"clip_data 字段: {list(clip_data.keys())}")
    print(f"路径存在: {os.path.exists(clip_data['path'])}")
    print(f"时长: {clip_data['duration']:.2f}秒")
    
    required_fields = ["id", "name", "path", "start_time", "duration", "track"]
    missing_fields = [f for f in required_fields if f not in clip_data]
    if missing_fields:
        print(f"缺少字段: {missing_fields}")
        return None
    
    print("clip_data 创建成功!")
    return clip_data

def test_mediaplayer():
    """测试 QMediaPlayer 播放"""
    print("\n=== 测试 7: QMediaPlayer 播放 ===")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtCore import QUrl
    
    app = QApplication.instance() or QApplication(sys.argv)
    
    test_video = find_test_video()
    if not test_video:
        print("未找到测试视频")
        return False
    
    try:
        media_player = QMediaPlayer()
        audio_output = QAudioOutput()
        media_player.setAudioOutput(audio_output)
        
        url = QUrl.fromLocalFile(test_video)
        media_player.setSource(url)
        
        # 等待加载
        timeout = 5
        start_time = time.time()
        while time.time() - start_time < timeout:
            if media_player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia:
                duration = media_player.duration() / 1000.0
                print(f"媒体加载成功!")
                print(f"媒体时长: {duration:.2f}秒")
                print("QMediaPlayer 测试通过!")
                return True
            time.sleep(0.1)
        
        print(f"媒体加载超时，状态: {media_player.mediaStatus()}")
        if media_player.error() != QMediaPlayer.Error.NoError:
            print(f"媒体错误: {media_player.error()}")
        return False
    except Exception as e:
        print(f"QMediaPlayer 测试异常: {e}")
        return False

def test_timeline_import():
    """测试 TimelineWidget 导入"""
    print("\n=== 测试 7: TimelineWidget 导入 ===")
    from PySide6.QtWidgets import QApplication
    
    app = QApplication.instance() or QApplication(sys.argv)
    
    from app.modules.lego.timeline_widget import TimelineWidget, ClipWidget
    
    try:
        timeline = TimelineWidget()
        print(f"TimelineWidget 创建成功")
        
        test_video = find_test_video()
        if not test_video:
            print("未找到测试视频")
            return False
        
        from app.modules.lego.video_processor import get_video_info
        ffprobe_path = os.path.join(os.path.dirname(__file__), "thirdparty", "ffmpeg", "bin", "ffprobe.exe")
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
            print(f"ClipWidget 创建成功: {widget.clip_data.get('name')}")
            print(f"Widget 尺寸: {widget.width()}x{widget.height()}")
            print(f"Widget 位置: ({widget.x()}, {widget.y()})")
            
            # 检查缩略图缓存
            if hasattr(widget, '_thumbnail_cache'):
                print(f"缩略图缓存状态: {len(widget._thumbnail_cache)} 张")
            if hasattr(widget, '_waveform_peaks'):
                print(f"波形缓存状态: {len(widget._waveform_peaks) if widget._waveform_peaks else 0}")
            
            return True
        else:
            print("ClipWidget 创建失败")
            return False
    except Exception as e:
        print(f"TimelineWidget 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def find_test_video():
    """查找测试视频文件"""
    test_dirs = [
        "./素材库",
        "./output",
        "./temp_ai_editor",
        os.path.expanduser("~/Videos"),
    ]
    
    extensions = ('.mp4', '.avi', '.mov', '.mkv', '.webm')
    
    for dir_path in test_dirs:
        if not os.path.isdir(dir_path):
            continue
        for filename in os.listdir(dir_path):
            if filename.lower().endswith(extensions):
                return os.path.join(dir_path, filename)
    
    # 查找项目根目录下的视频
    for filename in os.listdir('.'):
        if filename.lower().endswith(extensions):
            return os.path.abspath(filename)
    
    return None

def main():
    print("=" * 60)
    print("视频剪辑端到端测试")
    print("=" * 60)
    
    results = {}
    
    # 测试 FFmpeg
    results["FFmpeg"] = test_ffmpeg_availability()
    
    # 测试元数据
    results["元数据"] = test_video_metadata() is not None
    
    # 测试帧提取
    results["帧提取"] = test_frame_extraction()
    
    # 测试波形生成
    results["波形生成"] = test_waveform_generation()
    
    # 测试 clip_data
    results["clip_data"] = test_clip_data_creation() is not None
    
    # 测试 QMediaPlayer
    results["QMediaPlayer"] = test_mediaplayer()
    
    # 测试 TimelineWidget
    results["TimelineWidget"] = test_timeline_import()
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {name}: {status}")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n🎉 所有测试通过! 剪辑流程完整可用")
    else:
        print("\n⚠️ 存在失败环节，需要修复")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
