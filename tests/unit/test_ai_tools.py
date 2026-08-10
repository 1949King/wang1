#!/usr/bin/env python3
# 测试AI工具模块

import sys
sys.path.append('.')

from core.ai_tools import AITools

def test_ai_tools_import():
    """测试AI工具模块导入"""
    print("测试AI工具模块导入...")
    try:
        ai_tools = AITools()
        print("✓ AI工具模块导入成功")
        print(f"✓ AITools类创建成功: {ai_tools}")
        
        # 测试detect_highlights方法是否存在
        if hasattr(ai_tools, 'detect_highlights'):
            print("✓ detect_highlights方法存在")
        else:
            print("✗ detect_highlights方法不存在")
            
        return True
    except Exception as e:
        print(f"✗ AI工具模块导入失败: {e}")
        return False

if __name__ == "__main__":
    print("开始测试AI工具模块...")
    success = test_ai_tools_import()
    if success:
        print("\n测试完成: 所有测试通过！")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)