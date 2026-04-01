#!/usr/bin/env python3
# 测试素材库增强功能

import sys
import os
sys.path.append('.')

from core.asset_library import AssetLibrary

def test_enhanced_asset_library():
    """测试增强的素材库功能"""
    print("开始测试素材库增强功能...")
    
    try:
        # 创建临时测试目录
        test_dir = os.path.join(os.getcwd(), "test_assets_enhanced")
        os.makedirs(test_dir, exist_ok=True)
        
        # 创建测试文件
        test_files = []
        file_types = ["mp4", "mp3", "jpg"]
        for i in range(1, 4):
            test_file = os.path.join(test_dir, f"test_file_{i}.{file_types[i-1]}")
            with open(test_file, "w") as f:
                f.write(f"Test content {i}")
            test_files.append(test_file)
        
        print(f"✓ 创建测试文件: {len(test_files)} 个")
        
        # 初始化素材库
        asset_library = AssetLibrary()
        print("✓ 初始化素材库成功")
        
        # 测试添加素材（带标签）
        print("\n测试添加素材（带标签）...")
        tags_list = [["视频", "测试", "高清"], ["音频", "测试", "背景音乐"], ["图片", "测试", "封面"]]
        for i, test_file in enumerate(test_files):
            category = ["视频", "音频", "图片"][i % 3]
            tags = tags_list[i]
            
            add_success = asset_library.add_asset(test_file, category, tags)
            if add_success:
                asset_name = os.path.basename(test_file)
                print(f"✓ 添加素材 {i+1}: {asset_name} (分类: {category}, 标签: {tags})")
            else:
                print(f"✗ 添加素材 {i+1} 失败")
                return False
        
        print(f"✓ 素材库中素材数量: {len(asset_library.assets)}")
        
        # 测试创建自定义分类
        print("\n测试创建自定义分类...")
        custom_category = "我的素材"
        create_success = asset_library.create_category(custom_category)
        if create_success:
            print(f"✓ 创建自定义分类成功: {custom_category}")
        else:
            print(f"✗ 创建自定义分类失败")
            return False
        
        # 测试按文件名搜索
        print("\n测试按文件名搜索...")
        name_results = asset_library.search_assets("test_file_1", search_by="name")
        print(f"✓ 按文件名 'test_file_1' 搜索找到 {len(name_results)} 个素材")
        
        # 测试按标签搜索
        print("\n测试按标签搜索...")
        tag_results = asset_library.search_assets("测试", search_by="tags")
        print(f"✓ 按标签 '测试' 搜索找到 {len(tag_results)} 个素材")
        
        # 测试按类型搜索
        print("\n测试按类型搜索...")
        type_results = asset_library.search_assets("mp4", search_by="type")
        print(f"✓ 按类型 'mp4' 搜索找到 {len(type_results)} 个素材")
        
        # 测试标签管理
        print("\n测试标签管理...")
        if asset_library.assets:
            asset_id = asset_library.assets[0]["id"]
            
            # 添加标签
            add_tag_success = asset_library.add_tag_to_asset(asset_id, "新标签")
            if add_tag_success:
                print("✓ 添加标签成功")
            else:
                print("✗ 添加标签失败")
                return False
            
            # 移除标签
            remove_tag_success = asset_library.remove_tag_from_asset(asset_id, "测试")
            if remove_tag_success:
                print("✓ 移除标签成功")
            else:
                print("✗ 移除标签失败")
                return False
        
        # 测试获取所有标签
        print("\n测试获取所有标签...")
        all_tags = asset_library.get_all_tags()
        print(f"✓ 素材库中所有标签: {all_tags}")
        
        # 测试按标签获取素材
        print("\n测试按标签获取素材...")
        if all_tags:
            tag = all_tags[0]
            tag_assets = asset_library.get_assets_by_tag(tag)
            print(f"✓ 标签 '{tag}' 下的素材数量: {len(tag_assets)}")
        
        # 测试缩略图路径
        print("\n测试缩略图路径...")
        for asset in asset_library.assets:
            if "thumbnail" in asset:
                print(f"✓ 素材 {asset['name']} 的缩略图路径: {asset['thumbnail']}")
            else:
                print(f"✗ 素材 {asset['name']} 没有缩略图路径")
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
        print(f"✗ 测试素材库增强功能失败: {e}")
        return False

if __name__ == "__main__":
    success = test_enhanced_asset_library()
    if success:
        print("\n测试完成: 所有测试通过！")
        print("\n素材库增强功能已就绪，可以使用以下功能:")
        print("  1. 按文件名、标签、类型搜索素材")
        print("  2. 创建和删除自定义分类")
        print("  3. 管理素材标签")
        print("  4. 素材预览缩略图")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)