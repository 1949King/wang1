#!/usr/bin/env python3
"""
测试clawhud链接功能
"""

from app.modules.lego.skill_engine import skill_engine

if __name__ == "__main__":
    print("测试获取最新skill...")
    result = skill_engine.get_latest_skills()
    print("\n获取结果:")
    print(f"成功: {result['success']}")
    if 'error' in result:
        print(f"错误: {result['error']}")
    print(f"可用skill数量: {len(result['skills'])}")
    print(f"ClawHUD链接: {result['clawhud_link']}")
    
    print("\n测试完成！")
