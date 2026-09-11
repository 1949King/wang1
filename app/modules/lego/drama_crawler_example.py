"""
短剧数据爬虫模块 v3.0 使用示例
=====================

支持多平台短剧数据爬取，后台静默运行
智能筛选算法 + 多维度评分 + 热度预测 + 个性化推荐

使用方式
=========
通过单例对象 drama_crawler 可以快速获取推荐、热门、高佣金短剧
支持关键词搜索和个性化筛选

示例代码
---------
"""

from drama_crawler import drama_crawler, DramaInfo
from drama_crawler import ScoringEngine, HeatPredictor, Recommender

import time


import logging
logger = logging.getLogger("AI短剧编辑器.modules.lego.drama_crawler_example")

def main():
    logger.info('=' * 60)
    logger.info('短剧数据爬虫模块 v3.0 - 使用示例')
    logger.info('=' * 60)
    
    logger.info('\n' + '=' * 60)
    logger.info('全分类数据采集 - 每个分类20条，筛选前100')
    logger.info('=' * 60)
    
    categories = drama_crawler.get_categories()
    logger.info(f'\n共有 {len(categories)} 个分类')
    
    all_dramas = []
    
    for cat_key, cat_name in categories.items():
        logger.info(f'\n正在获取 [{cat_name}] 分类数据...')
        dramas = drama_crawler.fetch_dramas(
            platform="all",
            category=cat_key,
            sort_by="score",
            page_size=20
        )
        
        for d in dramas:
            d.category = cat_name
        
        all_dramas.extend(dramas)
        logger.info(f'  获取到 {len(dramas)} 条数据')
    
    logger.info(f'\n总共获取到 {len(all_dramas)} 条数据')
    
    all_dramas.sort(key=lambda x: x.score, reverse=True)
    
    top_100 = all_dramas[:100]
    
    logger.info(f'\n筛选出评分前100的短剧:')
    logger.info('-' * 60)
    
    for i, d in enumerate(top_100, 1):
        logger.info(f'{i:3d}. {d.title} | 分类: {d.category} | 评分: {d.score} | 平台: {d.platform}')
        logger.info(f'     播放: {d.views:,} | 佣金: ¥{d.commission:,.0f} | 理由: {d.recommend_reason}')
    
    logger.info('\n' + '=' * 60)
    logger.info('统计信息')
    logger.info('=' * 60)
    
    category_count = {}
    platform_count = {}
    total_commission = 0
    
    for d in top_100:
        category_count[d.category] = category_count.get(d.category, 0) + 1
        platform_count[d.platform] = platform_count.get(d.platform, 0) + 1
        total_commission += d.commission
    
    logger.info(f'\n分类分布:')
    for cat, count in sorted(category_count.items(), key=lambda x: x[1], reverse=True):
        logger.info(f'  {cat}: {count}部')
    
    logger.info(f'\n平台分布:')
    for plat, count in sorted(platform_count.items(), key=lambda x: x[1], reverse=True):
        logger.info(f'  {plat}: {count}部')
    
    logger.info(f'\n总佣金: ¥{total_commission:,.0f}')
    logger.info(f'平均评分: {sum((d.score for d in top_100)) / len(top_100):.2f}')
    
    logger.info('\n' + '=' * 60)
    logger.info('示例完成!')
    logger.info('=' * 60)


if __name__ == "__main__":
    main()
