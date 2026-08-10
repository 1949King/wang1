#!/usr/bin/env python3
"""
测试LocalAssetManager的新增功能
"""

import os
import sys
import tempfile
from app.core.local_asset_manager import local_asset_manager, AssetInfo


def test_asset_tags_and_filtering():
    """测试素材标签和筛选功能"""
    print("=== 测试素材标签和筛选功能 ===")
    
    # 创建临时测试文件
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
        test_file = f.name
    
    try:
        # 1. 导入素材
        print("1. 导入测试素材...")
        asset = local_asset_manager.import_asset(test_file, category="测试", tags=["测试标签1", "测试标签2"])
        if asset:
            print(f"   导入成功: {asset.name}")
            print(f"   初始标签: {asset.tags}")
        else:
            print("   导入失败")
            return
        
        # 2. 测试添加标签
        print("\n2. 测试添加标签...")
        success = local_asset_manager.add_tag_to_asset(asset.id, "新标签")
        if success:
            updated_asset = local_asset_manager.get_asset(asset.id)
            print(f"   添加标签成功: {updated_asset.tags}")
        else:
            print("   添加标签失败")
        
        # 3. 测试移除标签
        print("\n3. 测试移除标签...")
        success = local_asset_manager.remove_tag_from_asset(asset.id, "测试标签1")
        if success:
            updated_asset = local_asset_manager.get_asset(asset.id)
            print(f"   移除标签成功: {updated_asset.tags}")
        else:
            print("   移除标签失败")
        
        # 4. 测试标记为已使用
        print("\n4. 测试标记为已使用...")
        success = local_asset_manager.mark_asset_used(asset.id, project_id="test_project_1")
        if success:
            updated_asset = local_asset_manager.get_asset(asset.id)
            print(f"   标记成功: used={updated_asset.used}, project_id={updated_asset.project_id}")
            print(f"   最近使用时间: {updated_asset.last_used_time}")
        else:
            print("   标记失败")
        
        # 5. 测试获取最近使用的素材
        print("\n5. 测试获取最近使用的素材...")
        recent_assets = local_asset_manager.get_recently_used()
        print(f"   最近使用的素材数量: {len(recent_assets)}")
        for i, recent_asset in enumerate(recent_assets):
            print(f"   {i+1}. {recent_asset.name} (使用时间: {recent_asset.last_used_time})")
        
        # 6. 测试按使用状态筛选
        print("\n6. 测试按使用状态筛选...")
        used_assets = local_asset_manager.get_assets(used=True)
        print(f"   已使用素材数量: {len(used_assets)}")
        for asset in used_assets:
            print(f"   - {asset.name}")
        
        unused_assets = local_asset_manager.get_assets(used=False)
        print(f"   未使用素材数量: {len(unused_assets)}")
        
        # 7. 测试按项目归属筛选
        print("\n7. 测试按项目归属筛选...")
        project_assets = local_asset_manager.get_assets(project_id="test_project_1")
        print(f"   项目test_project_1的素材数量: {len(project_assets)}")
        for asset in project_assets:
            print(f"   - {asset.name}")
        
        # 8. 测试批量添加标签
        print("\n8. 测试批量添加标签...")
        success = local_asset_manager.add_tags_to_assets([asset.id], ["批量标签1", "批量标签2"])
        if success:
            updated_asset = local_asset_manager.get_asset(asset.id)
            print(f"   批量添加标签成功: {updated_asset.tags}")
        else:
            print("   批量添加标签失败")
        
        # 9. 测试批量移除标签
        print("\n9. 测试批量移除标签...")
        success = local_asset_manager.remove_tags_from_assets([asset.id], ["批量标签1", "测试标签2"])
        if success:
            updated_asset = local_asset_manager.get_asset(asset.id)
            print(f"   批量移除标签成功: {updated_asset.tags}")
        else:
            print("   批量移除标签失败")
        
        # 10. 测试获取所有项目
        print("\n10. 测试获取所有项目...")
        projects = local_asset_manager.get_projects()
        print(f"   所有项目: {projects}")
        
        print("\n=== 测试完成 ===")
        
    finally:
        # 清理测试文件
        if os.path.exists(test_file):
            os.remove(test_file)
        # 删除测试素材
        if 'asset' in locals() and asset:
            local_asset_manager.delete_asset(asset.id)


if __name__ == "__main__":
    test_asset_tags_and_filtering()
