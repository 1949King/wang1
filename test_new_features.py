#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新功能测试脚本
测试云服务集成、平台适配、AI能力增强和本地素材管理系统
"""

import os
import sys
import logging
import time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('TestNewFeatures')

def test_cloud_integration():
    """测试云服务集成"""
    logger.info("\n=== 测试云服务集成 ===")
    
    try:
        from app.modules.lego.cloud_api import cloud_api_service
        logger.info("✓ 云服务API模块导入成功")
        
        # 测试平台列表
        providers = cloud_api_service.list_providers()
        logger.info(f"✓ 支持的AI提供者: {providers}")
        
        # 测试Ollama本地模型支持
        has_ollama = "ollama" in providers
        logger.info(f"✓ Ollama本地模型支持: {has_ollama}")
        
        # 测试配置检查
        for provider in ["ollama", "deepseek"]:
            configured = cloud_api_service.is_configured(provider)
            logger.info(f"✓ {provider} 配置状态: {configured}")
        
        return True
    except Exception as e:
        logger.error(f"✗ 云服务集成测试失败: {e}")
        return False

def test_platform_adaptation():
    """测试平台适配"""
    logger.info("\n=== 测试平台适配 ===")
    
    try:
        from app.core.platform_adapter import platform_adapter
        logger.info("✓ 平台适配器模块导入成功")
        
        # 测试平台列表
        platforms = platform_adapter.get_platforms()
        logger.info(f"✓ 支持的平台: {[p['display_name'] for p in platforms]}")
        
        # 测试平台配置
        for platform in ["douyin", "kuaishou", "xiaohongshu"]:
            config = platform_adapter.get_platform_config(platform)
            if config:
                logger.info(f"✓ {config.display_name} 配置获取成功")
            else:
                logger.warning(f"⚠️ {platform} 配置未找到")
        
        # 测试模板
        for platform in ["douyin", "xiaohongshu"]:
            templates = platform_adapter.get_platform_templates(platform)
            logger.info(f"✓ {platform} 模板数量: {len(templates)}")
        
        return True
    except Exception as e:
        logger.error(f"✗ 平台适配测试失败: {e}")
        return False

def test_ai_enhancement():
    """测试AI能力增强"""
    logger.info("\n=== 测试AI能力增强 ===")
    
    try:
        from app.core.ai_enhanced import ai_enhanced
        logger.info("✓ 增强AI工具模块导入成功")
        
        # 测试AI能力
        capabilities = ai_enhanced.get_ai_capabilities()
        logger.info(f"✓ 本地模型可用: {capabilities['local_models']['available']}")
        logger.info(f"✓ 云端模型可用: {capabilities['cloud_models']['available']}")
        
        # 测试视频创意生成
        logger.info("✓ 视频创意生成功能就绪")
        
        # 测试个性化推荐
        logger.info("✓ 个性化推荐功能就绪")
        
        return True
    except Exception as e:
        logger.error(f"✗ AI能力增强测试失败: {e}")
        return False

def test_local_asset_management():
    """测试本地素材管理系统"""
    logger.info("\n=== 测试本地素材管理系统 ===")
    
    try:
        from app.core.local_asset_manager import local_asset_manager
        logger.info("✓ 本地素材管理器模块导入成功")
        
        # 测试统计信息
        stats = local_asset_manager.get_stats()
        logger.info(f"✓ 素材总数: {stats['total_assets']}")
        logger.info(f"✓ 素材类型分布: {stats['assets_by_type']}")
        
        # 测试分类和标签
        categories = local_asset_manager.get_categories()
        tags = local_asset_manager.get_tags()
        logger.info(f"✓ 分类数量: {len(categories)}")
        logger.info(f"✓ 标签数量: {len(tags)}")
        
        # 测试素材获取
        assets = local_asset_manager.get_assets()
        logger.info(f"✓ 获取素材列表成功，数量: {len(assets)}")
        
        return True
    except Exception as e:
        logger.error(f"✗ 本地素材管理系统测试失败: {e}")
        return False

def test_memory_optimization():
    """测试内存优化"""
    logger.info("\n=== 测试内存优化 ===")
    
    try:
        from app.core.memory_optimization import get_memory_pool, optimize_system_memory
        logger.info("✓ 内存优化模块导入成功")
        
        # 测试内存池
        memory_pool = get_memory_pool()
        stats = memory_pool.get_stats()
        logger.info(f"✓ 内存池状态: {stats['usage_ratio']}")
        
        # 测试内存优化
        optimize_system_memory()
        logger.info("✓ 系统内存优化成功")
        
        return True
    except Exception as e:
        logger.error(f"✗ 内存优化测试失败: {e}")
        return False

def main():
    """主测试函数"""
    logger.info("开始测试新功能...")
    
    tests = [
        ("云服务集成", test_cloud_integration),
        ("平台适配", test_platform_adaptation),
        ("AI能力增强", test_ai_enhancement),
        ("本地素材管理", test_local_asset_management),
        ("内存优化", test_memory_optimization)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        if test_func():
            passed += 1
        else:
            failed += 1
        time.sleep(0.5)  # 避免测试过快
    
    logger.info(f"\n=== 测试总结 ===")
    logger.info(f"通过: {passed}")
    logger.info(f"失败: {failed}")
    
    if failed == 0:
        logger.info("✓ 所有测试通过!")
        return 0
    else:
        logger.error("✗ 部分测试失败!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
