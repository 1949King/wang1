#!/usr/bin/env python3
# 测试预览管理器模块

import sys
sys.path.append('.')

from core.preview_manager import PreviewManager

def test_preview_manager_import():
    """测试预览管理器模块导入"""
    print("测试预览管理器模块导入...")
    try:
        preview_manager = PreviewManager()
        print("✓ 预览管理器模块导入成功")
        print(f"✓ PreviewManager类创建成功: {preview_manager}")
        print(f"✓ 初始当前时间: {preview_manager.current_time}")
        print(f"✓ 初始播放状态: {preview_manager.is_playing}")
        print(f"✓ 初始播放速度: {preview_manager.playing_speed}")
        print(f"✓ 初始预览窗口: {preview_manager.preview_window}")
        print(f"✓ 初始时间码可见性: {preview_manager.timecode_visible}")
        
        # 测试update_preview方法是否存在
        if hasattr(preview_manager, 'update_preview'):
            print("✓ update_preview方法存在")
        else:
            print("✗ update_preview方法不存在")
        
        # 测试drag_timeline_preview方法是否存在
        if hasattr(preview_manager, 'drag_timeline_preview'):
            print("✓ drag_timeline_preview方法存在")
        else:
            print("✗ drag_timeline_preview方法不存在")
        
        # 测试format_timecode方法是否存在
        if hasattr(preview_manager, 'format_timecode'):
            print("✓ format_timecode方法存在")
        else:
            print("✗ format_timecode方法不存在")
            
        return True
    except Exception as e:
        print(f"✗ 预览管理器模块导入失败: {e}")
        return False

def test_preview_operations():
    """测试预览操作功能"""
    print("\n测试预览操作功能...")
    
    try:
        preview_manager = PreviewManager()
        
        # 测试时间码格式化
        print("\n测试时间码格式化...")
        test_times = [0, 59.99, 60, 3600, 3661.5]
        for time in test_times:
            timecode = preview_manager.format_timecode(time)
            print(f"✓ 时间 {time:.2f}秒 格式化: {timecode}")
        
        # 测试更新预览
        print("\n测试更新预览...")
        update_success = preview_manager.update_preview(10.5)
        if update_success:
            print("✓ 更新预览成功")
        else:
            print("✗ 更新预览失败")
            return False
        
        # 测试拖拽时间轴预览
        print("\n测试拖拽时间轴预览...")
        drag_success = preview_manager.drag_timeline_preview(0, 30, 15)
        if drag_success:
            print("✓ 拖拽时间轴预览成功")
        else:
            print("✗ 拖拽时间轴预览失败")
            return False
        
        # 测试时间码可见性设置
        print("\n测试时间码可见性设置...")
        visibility_success = preview_manager.set_timecode_visibility(False)
        if visibility_success:
            print("✓ 设置时间码不可见成功")
        else:
            print("✗ 设置时间码可见性失败")
            return False
        
        # 测试播放控制
        print("\n测试播放控制...")
        play_success = preview_manager.play_preview(start_time=5, speed=2.0)
        if play_success:
            print("✓ 开始预览播放成功")
        else:
            print("✗ 开始预览播放失败")
            return False
        
        pause_success = preview_manager.pause_preview()
        if pause_success:
            print("✓ 暂停预览播放成功")
        else:
            print("✗ 暂停预览播放失败")
            return False
        
        stop_success = preview_manager.stop_preview()
        if stop_success:
            print("✓ 停止预览播放成功")
        else:
            print("✗ 停止预览播放失败")
            return False
        
        return True
    except Exception as e:
        print(f"✗ 测试预览操作失败: {e}")
        return False

if __name__ == "__main__":
    print("开始测试预览管理器模块...")
    
    # 测试模块导入
    import_success = test_preview_manager_import()
    
    # 测试预览操作功能
    operations_success = test_preview_operations()
    
    if import_success and operations_success:
        print("\n测试完成: 所有测试通过！")
        print("\n预览管理器模块已就绪，可以使用以下功能:")
        print("  1. update_preview - 实时更新预览窗口")
        print("  2. drag_timeline_preview - 支持拖拽时间轴预览")
        print("  3. format_timecode - 格式化时间码")
        print("  4. set_timecode_visibility - 设置时间码可见性")
        print("  5. play_preview/pause_preview/stop_preview - 播放控制")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)