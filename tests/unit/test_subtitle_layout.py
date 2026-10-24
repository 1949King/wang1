#!/usr/bin/env python3
# 测试字幕排版功能

import sys
import os
sys.path.append('.')

from core.ai_tools import AITools
from config import OUTPUT_PATH

def create_test_subtitle_file():
    """创建测试字幕文件"""
    test_subtitles = [
        {
            "id": 1,
            "start_time": 0.0,
            "end_time": 2.0,
            "text": "这是第一条测试字幕"
        },
        {
            "id": 2,
            "start_time": 2.5,
            "end_time": 4.5,
            "text": "这是第二条测试字幕，内容稍微长一点"
        },
        {
            "id": 3,
            "start_time": 5.0,
            "end_time": 7.0,
            "text": "这是第三条测试字幕"
        }
    ]
    
    test_file = "test_subtitles.json"
    with open(test_file, "w", encoding="utf-8") as f:
        import json
        json.dump(test_subtitles, f, ensure_ascii=False, indent=2)
    
    return test_file

def test_auto_layout_subtitles():
    """测试自动排版字幕功能"""
    print("测试自动排版字幕功能...")
    
    # 创建测试字幕文件
    test_file = create_test_subtitle_file()
    print(f"✓ 创建测试字幕文件: {test_file}")
    
    try:
        ai_tools = AITools()
        print("✓ 初始化AITools成功")
        
        # 测试自动排版字幕
        success = ai_tools.auto_layout_subtitles(test_file)
        if success:
            print("✓ 字幕排版成功")
            
            # 验证输出文件是否存在
            output_file = os.path.join(OUTPUT_PATH, "auto_layout_subtitles.json")
            if os.path.exists(output_file):
                print(f"✓ 输出文件生成成功: {output_file}")
                
                # 读取并显示排版后的字幕
                with open(output_file, "r", encoding="utf-8") as f:
                    import json
                    result = json.load(f)
                print(f"✓ 排版后字幕数量: {len(result)}")
                print("✓ 排版后的字幕示例:")
                for i, sub in enumerate(result[:2]):
                    print(f"  字幕 {i+1}: {sub['text']}")
                    print(f"    位置: {sub.get('position', '无')}")
                    print(f"    样式: {sub.get('style', '无')}")
            else:
                print("✗ 输出文件不存在")
                success = False
        else:
            print("✗ 字幕排版失败")
            
        return success
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False
    finally:
        # 清理测试文件
        if os.path.exists(test_file):
            os.remove(test_file)
            print(f"✓ 清理测试文件: {test_file}")

if __name__ == "__main__":
    print("开始测试字幕排版功能...")
    success = test_auto_layout_subtitles()
    if success:
        print("\n测试完成: 所有测试通过！")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)