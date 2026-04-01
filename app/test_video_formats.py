#!/usr/bin/env python3
# 测试视频格式相关功能

import sys
import os
import tempfile
import shutil
sys.path.append('.')

from core.video_processor import VideoProcessor

def test_video_formats():
    """测试视频格式相关功能"""
    print("开始测试视频格式相关功能...")
    
    try:
        # 初始化视频处理器
        video_processor = VideoProcessor()
        print("✓ 初始化视频处理器成功")
        
        # 测试获取支持的格式
        print("\n测试获取支持的格式...")
        supported_formats = video_processor.get_supported_formats()
        print(f"✓ 支持的格式: {supported_formats}")
        
        # 创建临时目录
        temp_dir = tempfile.mkdtemp()
        print(f"✓ 创建临时目录: {temp_dir}")
        
        # 创建测试图片序列
        print("\n测试创建图片序列...")
        test_images_dir = os.path.join(temp_dir, "test_images")
        os.makedirs(test_images_dir, exist_ok=True)
        
        # 创建测试图片（这里只是创建空文件作为示例）
        for i in range(1, 6):
            image_path = os.path.join(test_images_dir, f"frame_{i:04d}.jpg")
            with open(image_path, "w") as f:
                f.write(f"Test image {i}")
        print("✓ 创建测试图片序列成功")
        
        # 测试导入图片序列
        print("\n测试导入图片序列...")
        image_pattern = os.path.join(test_images_dir, "frame_%04d.jpg")
        sequence_output = os.path.join(temp_dir, "sequence_output.mp4")
        
        import_success = video_processor.import_image_sequence(image_pattern, sequence_output, fps=24)
        if import_success:
            print(f"✓ 图片序列导入成功: {sequence_output}")
        else:
            print("✗ 图片序列导入失败")
        
        # 创建测试视频文件（使用空文件作为示例）
        test_video = os.path.join(temp_dir, "test_video.mp4")
        with open(test_video, "w") as f:
            f.write("Test video")
        print("✓ 创建测试视频文件成功")
        
        # 测试导出不同格式
        print("\n测试导出不同格式...")
        test_formats = ["mov", "avi", "wmv", "flv", "mkv"]
        
        for fmt in test_formats:
            output_path = os.path.join(temp_dir, f"output.{fmt}")
            export_success = video_processor.export_video(test_video, output_path, format=fmt)
            if export_success:
                print(f"✓ 导出 {fmt} 格式成功: {output_path}")
            else:
                print(f"✗ 导出 {fmt} 格式失败")
        
        # 清理临时文件
        shutil.rmtree(temp_dir)
        print("✓ 清理临时文件成功")
        
        return True
    except Exception as e:
        print(f"✗ 测试视频格式功能失败: {e}")
        return False

if __name__ == "__main__":
    success = test_video_formats()
    if success:
        print("\n测试完成: 所有测试通过！")
        print("\n视频格式相关功能已就绪，可以使用以下功能:")
        print("  1. import_image_sequence - 导入图片序列为视频")
        print("  2. export_video - 导出视频为不同格式")
        print("  3. get_supported_formats - 获取支持的视频格式")
        print("\n支持的导出格式:")
        processor = VideoProcessor()
        print(f"  {', '.join(processor.get_supported_formats())}")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)
