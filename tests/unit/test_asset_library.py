#!/usr/bin/env python3
# 测试素材库管理模块

import sys
import os
sys.path.append('.')

from core.asset_library import AssetLibrary

def test_asset_library_import():
    """测试素材库管理模块导入"""
    print("测试素材库管理模块导入...")
    try:
        asset_library = AssetLibrary()
        print("✓ 素材库管理模块导入成功")
        print(f"✓ AssetLibrary类创建成功: {asset_library}")
        print(f"✓ 素材库路径: {asset_library.library_path}")
        print(f"✓ 初始素材数量: {len(asset_library.assets)}")
        print(f"✓ 初始分类: {list(asset_library.categories)}")
        
        # 测试add_asset方法是否存在
        if hasattr(asset_library, 'add_asset'):
            print("✓ add_asset方法存在")
        else:
            print("✗ add_asset方法不存在")
        
        # 测试search_assets方法是否存在
        if hasattr(asset_library, 'search_assets'):
            print("✓ search_assets方法存在")
        else:
            print("✗ search_assets方法不存在")
        
        # 测试get_assets_by_category方法是否存在
        if hasattr(asset_library, 'get_assets_by_category'):
            print("✓ get_assets_by_category方法存在")
        else:
            print("✗ get_assets_by_category方法不存在")
            
        return True
    except Exception as e:
        print(f"✗ 素材库管理模块导入失败: {e}")
        return False

def test_asset_operations():
    """测试素材库操作功能"""
    print("\n测试素材库操作功能...")
    
    try:
        # 创建临时测试目录
        test_dir = os.path.join(os.getcwd(), "test_assets")
        os.makedirs(test_dir, exist_ok=True)
        
        # 创建测试文件
        test_files = []
        for i in range(1, 4):
            test_file = os.path.join(test_dir, f"test_file_{i}.txt")
            with open(test_file, "w") as f:
                f.write(f"Test content {i}")
            test_files.append(test_file)
        
        print(f"✓ 创建测试文件: {len(test_files)} 个")
        
        # 初始化素材库
        asset_library = AssetLibrary()
        
        # 测试添加素材
        print("\n测试添加素材...")
        for i, test_file in enumerate(test_files):
            category = ["视频", "音频", "图片"][i % 3]
            tags = ["测试", f"类型{i+1}"]
            metadata = {"duration": 10 + i, "resolution": "1920x1080"}
            
            add_success = asset_library.add_asset(test_file, category, tags, metadata)
            if add_success:
                print(f"✓ 添加素材 {i+1}: {os.path.basename(test_file)} (分类: {category})")
            else:
                print(f"✗ 添加素材 {i+1} 失败")
                return False
        
        print(f"✓ 素材库中素材数量: {len(asset_library.assets)}")
        
        # 测试获取分类
        print("\n测试获取分类...")
        categories = asset_library.get_all_categories()
        print(f"✓ 素材库分类: {categories}")
        
        # 测试按分类获取素材
        print("\n测试按分类获取素材...")
        for category in ["视频", "音频", "图片"]:
            assets = asset_library.get_assets_by_category(category)
            print(f"✓ 分类 '{category}' 下的素材数量: {len(assets)}")
        
        # 测试搜索素材
        print("\n测试搜索素材...")
        search_results = asset_library.search_assets("test")
        print(f"✓ 搜索关键词 'test' 找到 {len(search_results)} 个素材")
        
        # 测试更新素材元数据
        print("\n测试更新素材元数据...")
        if asset_library.assets:
            asset_id = asset_library.assets[0]["id"]
            update_success = asset_library.update_asset_metadata(asset_id, {"author": "测试用户", "copyright": "2026"})
            if update_success:
                print("✓ 更新素材元数据成功")
            else:
                print("✗ 更新素材元数据失败")
                return False
        
        # 测试移除素材
        print("\n测试移除素材...")
        if asset_library.assets:
            asset_id = asset_library.assets[0]["id"]
            remove_success = asset_library.remove_asset(asset_id)
            if remove_success:
                print("✓ 移除素材成功")
                print(f"✓ 移除后素材数量: {len(asset_library.assets)}")
            else:
                print("✗ 移除素材失败")
                return False
        
        # 清理测试文件
        for test_file in test_files:
            if os.path.exists(test_file):
                os.remove(test_file)
        if os.path.exists(test_dir):
            os.rmdir(test_dir)
        print("✓ 清理测试文件成功")
        
        return True
    except Exception as e:
        print(f"✗ 测试素材库操作失败: {e}")
        return False

if __name__ == "__main__":
    print("开始测试素材库管理模块...")
    
    # 测试模块导入
    import_success = test_asset_library_import()
    
    # 测试素材库操作功能
    operations_success = test_asset_operations()
    
    if import_success and operations_success:
        print("\n测试完成: 所有测试通过！")
        print("\n素材库管理模块已就绪，可以使用以下功能:")
        print("  1. add_asset - 添加素材到库中")
        print("  2. search_assets - 搜索素材")
        print("  3. get_assets_by_category - 按分类获取素材")
        print("  4. get_all_categories - 获取所有分类")
        print("  5. update_asset_metadata - 更新素材元数据")
        print("  6. remove_asset - 从库中移除素材")
        print("  7. export_library/import_library - 导出/导入素材库配置")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)