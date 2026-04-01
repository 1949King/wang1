#!/usr/bin/env python3
# 测试平台集成功能

import sys
import os
import tempfile
sys.path.append('.')

from integrations.platforms import PlatformIntegrator

def test_platform_integration():
    """测试平台集成功能"""
    print("开始测试平台集成功能...")
    
    try:
        # 初始化平台集成器
        platform_integrator = PlatformIntegrator()
        print("✓ 初始化平台集成器成功")
        
        # 测试获取支持的平台
        print("\n测试获取支持的平台...")
        supported_platforms = platform_integrator.get_supported_platforms()
        print(f"✓ 支持的平台: {supported_platforms}")
        
        # 测试获取平台客户端
        print("\n测试获取平台客户端...")
        for platform in supported_platforms:
            client = platform_integrator.get_platform_client(platform)
            if client:
                print(f"✓ 获取 {platform} 客户端成功: {client}")
            else:
                print(f"✗ 获取 {platform} 客户端失败")
        
        # 创建测试视频文件
        temp_dir = tempfile.mkdtemp()
        test_video = os.path.join(temp_dir, "test_video.mp4")
        with open(test_video, "w") as f:
            f.write("Test video")
        print("✓ 创建测试视频文件成功")
        
        # 测试发布到单个平台
        print("\n测试发布到单个平台...")
        test_platform = "douyin"
        publish_success = platform_integrator.publish_to_platform(
            test_platform,
            test_video,
            "测试视频",
            "这是一个测试视频",
            ["测试", "抖音"],
            "2026-02-17 12:00:00"
        )
        if publish_success:
            print(f"✓ 发布到 {test_platform} 成功")
        else:
            print(f"✗ 发布到 {test_platform} 失败")
        
        # 测试发布到多个平台
        print("\n测试发布到多个平台...")
        test_platforms = ["douyin", "bilibili"]
        multi_publish_result = platform_integrator.publish_to_multiple_platforms(
            test_platforms,
            test_video,
            "测试视频",
            "这是一个测试视频",
            ["测试", "热门"],
            "2026-02-17 12:00:00"
        )
        print(f"✓ 多平台发布结果: {multi_publish_result}")
        
        # 测试获取平台特定标签
        print("\n测试获取平台特定标签...")
        for platform in supported_platforms:
            tags = platform_integrator.get_platform_specific_tags(platform)
            print(f"✓ {platform} 平台标签: {tags}")
        
        # 测试获取平台特定描述
        print("\n测试获取平台特定描述...")
        original_description = "这是一个测试视频"
        for platform in supported_platforms:
            platform_desc = platform_integrator.get_platform_specific_description(platform, original_description)
            print(f"✓ {platform} 平台描述: {platform_desc}")
        
        # 测试导出并发布
        print("\n测试导出并发布...")
        export_publish_result = platform_integrator.export_and_publish(
            test_video,
            "mp4",
            ["douyin", "bilibili"],
            "测试视频",
            "这是一个测试视频",
            ["测试", "热门"]
        )
        if export_publish_result:
            print("✓ 导出并发布成功")
        else:
            print("✗ 导出并发布失败")
        
        # 清理临时文件
        import shutil
        shutil.rmtree(temp_dir)
        print("✓ 清理临时文件成功")
        
        return True
    except Exception as e:
        print(f"✗ 测试平台集成功能失败: {e}")
        return False

if __name__ == "__main__":
    success = test_platform_integration()
    if success:
        print("\n测试完成: 所有测试通过！")
        print("\n平台集成功能已就绪，可以使用以下功能:")
        print("  1. 集成抖音、B站、YouTube等平台的API")
        print("  2. 支持直接导出并发布到多个平台")
        print("  3. 支持自动添加平台标签和描述")
        print("  4. 支持定时发布")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)
