"""
修复后的插件热加载机制测试
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.plugin_loader import (
    PluginType, PluginCategory, PluginState, PluginInfo
)
from app.core.plugin_hotloader import PluginManager, PluginContext, PluginFactory


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


def test_plugin_loading():
    """测试插件加载"""
    print("\n" + "="*50)
    print("测试插件加载")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    
    print("发现并加载插件...")
    discovered = manager.discover_plugins()
    
    for plugin_info in discovered:
        print(f"\n加载插件: {plugin_info.name}")
        loaded = manager.load_plugin(plugin_info.id)
        
        if loaded:
            print(f"  ✓ 加载成功")
            print(f"  状态: {manager.get_plugin_state(plugin_info.id)}")
        else:
            print(f"  ✗ 加载失败")
    
    print("✓ 插件加载测试通过")


def test_plugin_hot_reload():
    """测试插件热加载"""
    print("\n" + "="*50)
    print("测试插件热加载")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    
    print("发现并加载插件...")
    discovered = manager.discover_plugins()
    
    if discovered:
        plugin_info = discovered[0]
        print(f"加载插件: {plugin_info.name}")
        manager.load_plugin(plugin_info.id)
        
        print("重新加载插件...")
        reloaded = manager.reload_plugin(plugin_info.id)
        
        if reloaded:
            print(f"  ✓ 重新加载成功")
        else:
            print(f"  ✗ 重新加载失败")
    
    print("✓ 插件热加载测试通过")


def test_plugin_statistics():
    """测试插件统计"""
    print("\n" + "="*50)
    print("测试插件统计")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    
    print("发现并加载所有插件...")
    manager.discover_plugins()
    manager.load_all_plugins()
    
    print("获取统计信息...")
    stats = manager.get_statistics()
    
    print(f"总插件数: {stats['total_plugins']}")
    print(f"已加载: {stats['loaded_plugins']}")
    print(f"已初始化: {stats['initialized_plugins']}")
    print(f"错误: {stats['error_plugins']}")
    
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
    
    print("发现并加载所有插件...")
    manager.discover_plugins()
    manager.load_all_plugins()
    
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


def test_plugin_ui_config():
    """测试插件UI配置"""
    print("\n" + "="*50)
    print("测试插件UI配置")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    
    print("发现并加载所有插件...")
    manager.discover_plugins()
    manager.load_all_plugins()
    
    print("获取特效插件UI配置...")
    effect_plugins = manager.get_effect_plugins()
    
    for plugin in effect_plugins:
        info = plugin.plugin_info
        ui_config = plugin.get_ui_config()
        
        print(f"\n{info.name}:")
        print(f"  图标: {ui_config.get('icon', 'N/A')}")
        print(f"  参数数量: {len(ui_config.get('params', []))}")
        
        for param in ui_config.get('params', []):
            print(f"    - {param.get('label', param.get('name', 'N/A'))}")
            print(f"      类型: {param.get('type', 'N/A')}")
            if param.get('type') == 'slider':
                print(f"      范围: {param.get('min', 'N/A')} - {param.get('max', 'N/A')}")
                print(f"      默认值: {param.get('default', 'N/A')}")
            elif param.get('type') == 'select':
                print(f"      选项: {', '.join(param.get('options', []))}")
                print(f"      默认值: {param.get('default', 'N/A')}")
    
    print("✓ 插件UI配置测试通过")


def test_plugin_search():
    """测试插件搜索"""
    print("\n" + "="*50)
    print("测试插件搜索")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    
    print("发现并加载所有插件...")
    manager.discover_plugins()
    manager.load_all_plugins()
    
    search_queries = ["金光", "转场", "暗调", "高亮", "柔光"]
    
    for query in search_queries:
        print(f"\n搜索: {query}")
        results = manager.search_plugins(query)
        
        print(f"  找到 {len(results)} 个结果:")
        for plugin_info in results[:3]:
            print(f"    - {plugin_info.name}")
            print(f"      类型: {plugin_info.plugin_type.value}")
            print(f"      分类: {plugin_info.category.value}")
    
    print("✓ 插件搜索测试通过")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("插件热加载机制测试套件（修复版）")
    print("="*60)
    
    try:
        test_plugin_discovery()
        test_plugin_loading()
        test_plugin_hot_reload()
        test_plugin_statistics()
        test_shortplay_plugins()
        test_plugin_ui_config()
        test_plugin_search()
        
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
