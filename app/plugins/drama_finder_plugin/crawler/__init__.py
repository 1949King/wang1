"""
短剧筛选插件 — 爬虫引擎包
========================
DramaCrawler / DramaWebScraper 已从 modules/lego 迁入本插件。
外部代码可继续 `from app.modules.lego.drama_crawler import ...`（兼容 shim）。
"""

from .drama_crawler import (
    DATA_SOURCE_HEALTH,
    DATA_SOURCE_HELP,
    DramaCrawler,
    DramaInfo,
    PlatformAPI,
    ScoringEngine,
    Recommender,
    drama_crawler,
    get_data_source_health,
)
from .drama_web_scraper import DramaWebScraper, drama_web_scraper

__all__ = [
    "DATA_SOURCE_HEALTH",
    "DATA_SOURCE_HELP",
    "DramaCrawler",
    "DramaInfo",
    "PlatformAPI",
    "ScoringEngine",
    "Recommender",
    "drama_crawler",
    "get_data_source_health",
    "DramaWebScraper",
    "drama_web_scraper",
]
