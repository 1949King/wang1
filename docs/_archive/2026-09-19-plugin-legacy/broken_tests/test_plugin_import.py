#!/usr/bin/env python3
# 测试插件导入

import os
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("测试插件导入...")

# 测试PluginManager导入
try:
    from modules.plugins.plugin_system import PluginManager
    print("✓ PluginManager导入成功")
except Exception as e:
    print(f"✗ PluginManager导入失败: {e}")
    sys.exit(1)

# 测试FullVideoEditorPlugin导入
try:
    from modules.plugins.full_video_editor import FullVideoEditorPlugin
    print("✓ FullVideoEditorPlugin导入成功")
except Exception as e:
    print(f"✗ FullVideoEditorPlugin导入失败: {e}")
    sys.exit(1)

# 测试插件初始化
try:
    plugin = FullVideoEditorPlugin()
    print(f"✓ 插件初始化成功: {plugin.get_name()}")
except Exception as e:
    print(f"✗ 插件初始化失败: {e}")
    sys.exit(1)

# 测试PluginManager的import_plugin方法
try:
    plugin_manager = PluginManager()
    plugin_file = os.path.join(os.path.dirname(__file__), "modules", "plugins", "full_video_editor.py")
    success, message = plugin_manager.import_plugin(plugin_file)
    print(f"✓ PluginManager.import_plugin测试: {message}")
except Exception as e:
    print(f"✗ PluginManager.import_plugin测试失败: {e}")

print("\n所有测试完成！")
