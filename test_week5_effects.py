"""
特效转场插件测试
测试短剧专属特效和转场插件
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.plugin_loader import (
    PluginType, PluginCategory, PluginInfo
)
from app.core.plugin_hotloader import PluginManager


def test_plugin_discovery():
    """测试插件发现"""
    print("\n" + "="*50)
    print("测试插件发现")
    print("="*50)
    
    manager = PluginManager()
    
    print("添加插件目录...")
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    
    print("发现插件...")
    discovered = manager.discover_plugins()
    print(f"发现 {len(discovered)} 个插件")
    
    for plugin_info in discovered:
        print(f"  - {plugin_info.name} ({plugin_info.plugin_type.value})")
    
    assert len(discovered) > 0, "未发现任何插件"
    print("✓ 插件发现测试通过")


def test_effect_plugins():
    """测试特效插件"""
    print("\n" + "="*50)
    print("测试特效插件")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    manager.discover_plugins()
    
    print("加载特效插件...")
    effect_plugins = manager.get_effect_plugins()
    print(f"找到 {len(effect_plugins)} 个特效插件")
    
    for plugin in effect_plugins:
        info = plugin.plugin_info
        print(f"\n特效: {info.name}")
        print(f"  分类: {info.category.value}")
        print(f"  版本: {info.version}")
        print(f"  描述: {info.description}")
        print(f"  标签: {', '.join(info.tags)}")
        
        ui_config = plugin.get_ui_config()
        print(f"  UI配置: {len(ui_config.get('params', []))} 个参数")
        
        params = plugin.get_effect_params()
        print(f"  特效参数: {len(params)} 个")
        
        test_frame = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        result = plugin.apply_effect(test_frame, {"intensity": 0.5})
        print(f"  应用特效: {'成功' if result is not None else '失败'}")
    
    print("✓ 特效插件测试通过")


def test_transition_plugins():
    """测试转场插件"""
    print("\n" + "="*50)
    print("测试转场插件")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    manager.discover_plugins()
    
    print("加载转场插件...")
    transition_plugins = manager.get_transition_plugins()
    print(f"找到 {len(transition_plugins)} 个转场插件")
    
    for plugin in transition_plugins:
        info = plugin.plugin_info
        print(f"\n转场: {info.name}")
        print(f"  分类: {info.category.value}")
        print(f"  版本: {info.version}")
        print(f"  描述: {info.description}")
        print(f"  标签: {', '.join(info.tags)}")
        
        ui_config = plugin.get_ui_config()
        print(f"  UI配置: {len(ui_config.get('params', []))} 个参数")
        
        params = plugin.get_transition_params()
        print(f"  转场参数: {len(params)} 个")
        
        from_frame = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        to_frame = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        
        for progress in [0.0, 0.25, 0.5, 0.75, 1.0]:
            result = plugin.apply_transition(from_frame, to_frame, progress, {})
            print(f"  应用转场 (progress={progress}): {'成功' if result is not None else '失败'}")
    
    print("✓ 转场插件测试通过")


def test_plugin_categories():
    """测试插件分类"""
    print("\n" + "="*50)
    print("测试插件分类")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    manager.discover_plugins()
    
    print("按分类获取插件...")
    categories = [
        PluginCategory.COUNTERATTACK,
        PluginCategory.EMOTION,
        PluginCategory.SUSPENSE,
        PluginCategory.SELLING,
        PluginCategory.GENERAL
    ]
    
    for category in categories:
        plugins = manager.list_plugins(plugin_type=PluginType.EFFECT, category=category)
        print(f"{category.value}: {len(plugins)} 个插件")
        for plugin_info in plugins:
            print(f"  - {plugin_info.name}")
    
    print("✓ 插件分类测试通过")


def test_plugin_statistics():
    """测试插件统计"""
    print("\n" + "="*50)
    print("测试插件统计")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    manager.discover_plugins()
    
    print("获取统计信息...")
    stats = manager.get_statistics()
    
    print(f"  总插件数: {stats['total_plugins']}")
    print(f"  已加载: {stats['loaded_plugins']}")
    print(f"  已初始化: {stats['initialized_plugins']}")
    print(f"  错误: {stats['error_plugins']}")
    
    print("\n按类型统计:")
    for plugin_type, count in stats['by_type'].items():
        print(f"  {plugin_type}: {count}")
    
    print("\n按分类统计:")
    for category, count in stats['by_category'].items():
        print(f"  {category}: {count}")
    
    print("✓ 插件统计测试通过")


def test_shortplay_plugins():
    """测试短剧专属插件"""
    print("\n" + "="*50)
    print("测试短剧专属插件")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    manager.discover_plugins()
    
    print("获取短剧专属插件...")
    shortplay_plugins = manager.get_shortplay_plugins()
    
    for category, plugins in shortplay_plugins.items():
        if plugins:
            print(f"\n{category.value}类插件:")
            for plugin_info in plugins:
                print(f"  - {plugin_info.name}")
                print(f"    描述: {plugin_info.description}")
                print(f"    标签: {', '.join(plugin_info.tags)}")
    
    print("✓ 短剧专属插件测试通过")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("特效转场插件测试套件")
    print("="*60)
    
    try:
        test_plugin_discovery()
        test_effect_plugins()
        test_transition_plugins()
        test_plugin_categories()
        test_plugin_statistics()
        test_shortplay_plugins()
        
        print("\n" + "="*60)
        print("✓ 所有测试通过!")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
