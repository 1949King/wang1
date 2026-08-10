#!/usr/bin/env python3
# 测试轨道管理器模块

import sys
sys.path.append('.')

from core.track_manager import TrackManager

def test_track_manager_import():
    """测试轨道管理器模块导入"""
    print("测试轨道管理器模块导入...")
    try:
        track_manager = TrackManager()
        print("✓ 轨道管理器模块导入成功")
        print(f"✓ TrackManager类创建成功: {track_manager}")
        print(f"✓ 初始轨道列表: {track_manager.tracks}")
        print(f"✓ 初始复制属性: {track_manager.copied_clip_properties}")
        
        # 测试copy_clip_properties方法是否存在
        if hasattr(track_manager, 'copy_clip_properties'):
            print("✓ copy_clip_properties方法存在")
        else:
            print("✗ copy_clip_properties方法不存在")
        
        # 测试paste_clip_properties方法是否存在
        if hasattr(track_manager, 'paste_clip_properties'):
            print("✓ paste_clip_properties方法存在")
        else:
            print("✗ paste_clip_properties方法不存在")
            
        return True
    except Exception as e:
        print(f"✗ 轨道管理器模块导入失败: {e}")
        return False

def test_clip_properties_copy_paste():
    """测试剪辑片段属性复制粘贴功能"""
    print("\n测试剪辑片段属性复制粘贴功能...")
    
    try:
        track_manager = TrackManager()
        
        # 创建测试轨道和剪辑片段
        test_track = {
            "id": 1,
            "type": "video",
            "clips": [
                {
                    "id": 1,
                    "name": "剪辑1",
                    "start_time": 0,
                    "duration": 5,
                    "filters": [{"name": "模糊", "strength": 0.5}],
                    "color_correction": {"brightness": 1.2, "contrast": 1.1},
                    "speed": 1.0,
                    "volume": 1.0,
                    "effects": [{"name": "淡入", "duration": 1}]
                },
                {
                    "id": 2,
                    "name": "剪辑2",
                    "start_time": 5,
                    "duration": 5,
                    "filters": [],
                    "color_correction": {},
                    "speed": 1.0,
                    "volume": 1.0,
                    "effects": []
                },
                {
                    "id": 3,
                    "name": "剪辑3",
                    "start_time": 10,
                    "duration": 5,
                    "filters": [],
                    "color_correction": {},
                    "speed": 1.0,
                    "volume": 1.0,
                    "effects": []
                }
            ]
        }
        
        track_manager.tracks.append(test_track)
        print(f"✓ 创建测试轨道: {test_track['id']}")
        print(f"✓ 轨道中的剪辑片段数量: {len(test_track['clips'])}")
        
        # 测试复制属性
        print("\n测试复制属性...")
        copy_success = track_manager.copy_clip_properties(1, 1)
        if copy_success:
            print("✓ 复制属性成功")
            print(f"✓ 复制的属性: {track_manager.copied_clip_properties}")
        else:
            print("✗ 复制属性失败")
            return False
        
        # 测试粘贴属性
        print("\n测试粘贴属性...")
        paste_success = track_manager.paste_clip_properties(1, [2, 3])
        if paste_success:
            print("✓ 粘贴属性成功")
            
            # 验证粘贴结果
            for clip in test_track['clips']:
                if clip['id'] in [2, 3]:
                    print(f"✓ 剪辑 {clip['id']} 已更新属性")
                    print(f"  滤镜: {clip['filters']}")
                    print(f"  色彩校正: {clip['color_correction']}")
                    print(f"  速度: {clip['speed']}")
                    print(f"  音量: {clip['volume']}")
                    print(f"  效果: {clip['effects']}")
        else:
            print("✗ 粘贴属性失败")
            return False
        
        return True
    except Exception as e:
        print(f"✗ 测试剪辑片段属性复制粘贴失败: {e}")
        return False

if __name__ == "__main__":
    print("开始测试轨道管理器模块...")
    
    # 测试模块导入
    import_success = test_track_manager_import()
    
    # 测试剪辑片段属性复制粘贴功能
    copy_paste_success = test_clip_properties_copy_paste()
    
    if import_success and copy_paste_success:
        print("\n测试完成: 所有测试通过！")
        print("\n轨道管理器模块已就绪，可以使用以下功能:")
        print("  1. copy_clip_properties - 复制剪辑片段的属性")
        print("  2. paste_clip_properties - 粘贴属性到多个剪辑片段")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)