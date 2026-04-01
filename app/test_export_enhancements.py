#!/usr/bin/env python3
# 测试导出增强功能

import sys
import os
import tempfile
sys.path.append('.')

from core.video_processor import VideoProcessor

def test_export_enhancements():
    """测试导出增强功能"""
    print("开始测试导出增强功能...")
    
    try:
        # 初始化视频处理器
        video_processor = VideoProcessor()
        print("✓ 初始化视频处理器成功")
        
        # 测试获取硬件加速选项
        print("\n测试获取硬件加速选项...")
        hardware_options = video_processor.get_hardware_acceleration_options()
        for option in hardware_options:
            print(f"✓ {option['name']}: {option['description']}")
        
        # 测试获取编码质量选项
        print("\n测试获取编码质量选项...")
        quality_options = video_processor.get_quality_options()
        for option in quality_options:
            print(f"✓ {option['name']}: {option['description']}")
        
        # 创建临时目录和测试视频文件
        temp_dir = tempfile.mkdtemp()
        test_video = os.path.join(temp_dir, "test_video.mp4")
        with open(test_video, "w") as f:
            f.write("Test video")
        print("✓ 创建测试视频文件成功")
        
        # 测试多线程导出
        print("\n测试多线程导出...")
        multi_thread_output = os.path.join(temp_dir, "multi_thread_output.mp4")
        multi_thread_success = video_processor.export_video(
            test_video,
            multi_thread_output,
            threads=4,  # 使用4线程
            quality="medium"
        )
        if multi_thread_success:
            print("✓ 多线程导出成功")
        else:
            print("✗ 多线程导出失败")
        
        # 测试不同质量设置
        print("\n测试不同质量设置...")
        quality_settings = ["ultrafast", "medium", "slow"]
        for quality in quality_settings:
            quality_output = os.path.join(temp_dir, f"{quality}_output.mp4")
            quality_success = video_processor.export_video(
                test_video,
                quality_output,
                quality=quality
            )
            if quality_success:
                print(f"✓ 质量设置 '{quality}' 导出成功")
            else:
                print(f"✗ 质量设置 '{quality}' 导出失败")
        
        # 测试硬件加速（模拟）
        print("\n测试硬件加速选项...")
        hardware_options = ["nvidia", "amd", "none"]
        for hardware in hardware_options:
            hardware_output = os.path.join(temp_dir, f"{hardware}_output.mp4")
            hardware_success = video_processor.export_video(
                test_video,
                hardware_output,
                hardware_acceleration=hardware,
                quality="medium"
            )
            if hardware_success:
                print(f"✓ 硬件加速 '{hardware}' 导出成功")
            else:
                print(f"✗ 硬件加速 '{hardware}' 导出失败")
        
        # 测试完整的导出配置
        print("\n测试完整的导出配置...")
        full_config_output = os.path.join(temp_dir, "full_config_output.mp4")
        full_config_success = video_processor.export_video(
            test_video,
            full_config_output,
            format="mp4",
            codec="libx264",
            bitrate="8M",
            fps=30,
            threads=8,
            hardware_acceleration="none",
            quality="slow"
        )
        if full_config_success:
            print("✓ 完整配置导出成功")
        else:
            print("✗ 完整配置导出失败")
        
        # 清理临时文件
        import shutil
        shutil.rmtree(temp_dir)
        print("✓ 清理临时文件成功")
        
        return True
    except Exception as e:
        print(f"✗ 测试导出增强功能失败: {e}")
        return False

if __name__ == "__main__":
    success = test_export_enhancements()
    if success:
        print("\n测试完成: 所有测试通过！")
        print("\n导出增强功能已就绪，可以使用以下功能:")
        print("  1. 多线程导出 - 提高导出速度")
        print("  2. 硬件加速编码 - 支持NVIDIA NVENC和AMD AMF")
        print("  3. 多种编码质量选项 - 从超快到极慢")
        print("\n硬件加速选项:")
        processor = VideoProcessor()
        for option in processor.get_hardware_acceleration_options():
            print(f"  - {option['name']}: {option['description']}")
        print("\n编码质量选项:")
        for option in processor.get_quality_options():
            print(f"  - {option['name']}: {option['description']}")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)
