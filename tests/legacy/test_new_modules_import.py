#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新增模块导入测试脚本
测试所有新增的核心管理模块和渲染模块是否能够正确导入
"""

import sys
import traceback
from pathlib import Path

# 添加项目路径到系统路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 测试结果记录
test_results = {
    'passed': [],
    'failed': [],
    'errors': []
}

def test_module_import(module_name, description=""):
    """测试单个模块导入"""
    try:
        __import__(module_name)
        test_results['passed'].append({
            'module': module_name,
            'description': description
        })
        print(f"✓ {module_name} - {description}")
        return True
    except Exception as e:
        error_info = {
            'module': module_name,
            'description': description,
            'error': str(e),
            'traceback': traceback.format_exc()
        }
        test_results['failed'].append(error_info)
        print(f"✗ {module_name} - {description}")
        print(f"  错误: {str(e)}")
        return False

def main():
    """主测试函数"""
    print("=" * 60)
    print("新增模块导入测试")
    print("=" * 60)
    
    # 测试核心管理模块
    print("\n1. 核心管理模块测试:")
    print("-" * 60)
    
    core_modules = [
        ("app.core.editor_scheduler", "双内核调度器"),
        ("app.core.project_manager", "项目管理系统"),
        ("app.core.asset_manager", "素材管理系统"),
        ("app.core.timeline_manager", "时间线管理系统"),
        ("app.core.effect_manager", "特效管理系统"),
        ("app.core.transition_manager", "转场管理系统"),
        ("app.core.audio_manager", "音频管理系统"),
        ("app.core.subtitle_manager", "字幕管理系统"),
        ("app.core.history_manager", "历史记录管理"),
        ("app.core.preview_manager", "预览管理"),
        ("app.core.cache_manager", "缓存管理"),
        ("app.core.preset_manager", "预设管理"),
        ("app.core.plugin_manager", "插件管理"),
    ]
    
    for module_name, description in core_modules:
        test_module_import(module_name, description)
    
    # 测试渲染模块
    print("\n2. 渲染模块测试:")
    print("-" * 60)
    
    render_modules = [
        ("app.modules.lego.render", "渲染模块基础"),
    ]
    
    for module_name, description in render_modules:
        test_module_import(module_name, description)
    
    # 测试主模块
    print("\n3. 主模块测试:")
    print("-" * 60)
    
    main_modules = [
        ("app.modules.lego.modules", "视频编辑主模块"),
    ]
    
    for module_name, description in main_modules:
        test_module_import(module_name, description)
    
    # 测试工具模块
    print("\n4. 工具模块测试:")
    print("-" * 60)
    
    utils_modules = [
        ("app.core.config_manager", "配置管理"),
        ("app.core.log_manager", "日志管理"),
        ("app.core.security", "安全模块"),
    ]
    
    for module_name, description in utils_modules:
        test_module_import(module_name, description)
    
    # 打印测试总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"总计: {len(test_results['passed']) + len(test_results['failed'])} 个模块")
    print(f"通过: {len(test_results['passed'])} 个")
    print(f"失败: {len(test_results['failed'])} 个")
    
    if test_results['failed']:
        print("\n失败的模块:")
        for failed in test_results['failed']:
            print(f"  - {failed['module']}: {failed['description']}")
            print(f"    错误: {failed['error']}")
        return False
    else:
        print("\n✓ 所有模块导入测试通过!")
        return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)