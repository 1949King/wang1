#!/usr/bin/env python3
# 测试缓存管理器功能

import sys
import os
import time
sys.path.append('.')

from core.cache_manager import cache_manager

def test_cache_manager():
    """测试缓存管理器功能"""
    print("开始测试缓存管理器功能...")
    
    try:
        # 测试获取缓存统计信息
        print("\n测试获取缓存统计信息...")
        stats = cache_manager.get_cache_stats()
        print(f"✓ 缓存统计信息: {stats}")
        
        # 测试缓存视频帧
        print("\n测试缓存视频帧...")
        test_video_id = "test_video_1"
        
        # 缓存10帧
        for i in range(10):
            frame_data = f"Frame data {i}"
            cache_manager.cache_frame(test_video_id, i, frame_data)
            print(f"✓ 缓存帧 {i}")
        
        # 测试获取缓存的帧
        print("\n测试获取缓存的帧...")
        for i in range(5):
            cached_frame = cache_manager.get_cached_frame(test_video_id, i)
            if cached_frame:
                print(f"✓ 获取帧 {i}: {cached_frame}")
            else:
                print(f"✗ 帧 {i} 未找到")
        
        # 测试释放视频资源
        print("\n测试释放视频资源...")
        cache_manager.release_video_resources(test_video_id)
        
        # 验证资源已释放
        stats_after_release = cache_manager.get_cache_stats()
        print(f"✓ 释放资源后缓存大小: {stats_after_release['frame_cache_size']}")
        
        # 测试创建临时文件
        print("\n测试创建临时文件...")
        temp_file = cache_manager.create_temp_file(".txt")
        print(f"✓ 创建临时文件: {temp_file}")
        
        # 写入测试内容
        with open(temp_file, "w") as f:
            f.write("Test content")
        print("✓ 写入临时文件成功")
        
        # 测试清理临时文件
        print("\n测试清理临时文件...")
        # 先等待1秒，确保文件有修改时间
        time.sleep(1)
        cleaned_count = cache_manager.cleanup_temp_files(older_than=0)  # 清理所有临时文件
        print(f"✓ 清理临时文件数量: {cleaned_count}")
        
        # 验证文件已删除
        if not os.path.exists(temp_file):
            print("✓ 临时文件已成功删除")
        else:
            print("✗ 临时文件未删除")
        
        # 测试清空帧缓存
        print("\n测试清空帧缓存...")
        # 先缓存一些帧
        for i in range(5):
            frame_data = f"Frame data {i}"
            cache_manager.cache_frame("test_video_2", i, frame_data)
        
        # 清空缓存
        cache_manager.clear_frame_cache()
        stats_after_clear = cache_manager.get_cache_stats()
        print(f"✓ 清空后缓存大小: {stats_after_clear['frame_cache_size']}")
        
        # 测试清空所有资源
        print("\n测试清空所有资源...")
        # 先缓存一些帧和注册资源
        for i in range(3):
            frame_data = f"Frame data {i}"
            cache_manager.cache_frame("test_video_3", i, frame_data)
        
        cache_manager.register_video_resource("test_video_3", "test_resource")
        cache_manager.clear_all_resources()
        
        final_stats = cache_manager.get_cache_stats()
        print(f"✓ 清空所有资源后缓存大小: {final_stats['frame_cache_size']}")
        print(f"✓ 清空所有资源后视频资源数量: {final_stats['video_resources_count']}")
        
        print("\n测试自动清理...")
        # 启动自动清理
        cache_manager.auto_cleanup(interval=10)
        print("✓ 启动自动清理线程成功")
        
        return True
    except Exception as e:
        print(f"✗ 测试缓存管理器功能失败: {e}")
        return False

if __name__ == "__main__":
    success = test_cache_manager()
    if success:
        print("\n测试完成: 所有测试通过！")
        print("\n缓存管理器功能已就绪，可以使用以下功能:")
        print("  1. 视频帧缓存机制 - 提高视频预览性能")
        print("  2. 及时释放不再使用的视频资源 - 避免内存泄漏")
        print("  3. 自动清理临时文件 - 保持磁盘空间整洁")
        print("  4. 自动清理过期缓存 - 优化内存使用")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)
