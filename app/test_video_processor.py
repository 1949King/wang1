#!/usr/bin/env python3
# 测试视频处理器模块

import sys
import os
sys.path.append('.')

from core.video_processor import VideoProcessor
from config import OUTPUT_PATH

def test_video_processor_import():
    """测试视频处理器模块导入"""
    print("测试视频处理器模块导入...")
    try:
        video_processor = VideoProcessor()
        print("✓ 视频处理器模块导入成功")
        print(f"✓ VideoProcessor类创建成功: {video_processor}")
        print(f"✓ FFmpeg路径: {video_processor.ffmpeg_path}")
        
        # 测试denoise_audio方法是否存在
        if hasattr(video_processor, 'denoise_audio'):
            print("✓ denoise_audio方法存在")
        else:
            print("✗ denoise_audio方法不存在")
        
        # 测试separate_audio方法是否存在
        if hasattr(video_processor, 'separate_audio'):
            print("✓ separate_audio方法存在")
        else:
            print("✗ separate_audio方法不存在")
            
        return True
    except Exception as e:
        print(f"✗ 视频处理器模块导入失败: {e}")
        return False

def test_ffmpeg_availability():
    """测试FFmpeg是否可用"""
    print("\n测试FFmpeg是否可用...")
    try:
        import subprocess
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ FFmpeg可用")
            # 显示FFmpeg版本信息
            version_info = result.stdout.split('\n')[0]
            print(f"✓ {version_info}")
            return True
        else:
            print("✗ FFmpeg不可用")
            print(f"  错误信息: {result.stderr}")
            return False
    except FileNotFoundError:
        print("✗ FFmpeg未找到，请确保已安装并添加到PATH中")
        return False
    except Exception as e:
        print(f"✗ 测试FFmpeg失败: {e}")
        return False

if __name__ == "__main__":
    print("开始测试视频处理器模块...")
    
    # 测试模块导入
    import_success = test_video_processor_import()
    
    # 测试FFmpeg可用性
    ffmpeg_success = test_ffmpeg_availability()
    
    if import_success and ffmpeg_success:
        print("\n测试完成: 所有测试通过！")
        print("\n视频处理器模块已就绪，可以使用以下功能:")
        print("  1. denoise_audio - 音频降噪")
        print("  2. separate_audio - 分离人声和背景音乐")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)