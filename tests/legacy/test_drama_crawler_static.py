#!/usr/bin/env python3
"""验收：短剧爬虫功能已卸，不得再返回假榜单标题。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.plugins.drama_finder_plugin.crawler.drama_crawler import DramaCrawler
from app.plugins.drama_finder_plugin.crawler.drama_web_scraper import DramaWebScraper


def main():
    ws = DramaWebScraper()
    cached = ws.fetch_hot_list(limit=5)
    assert cached == [], cached

    DramaCrawler._instance = None
    c = DramaCrawler()
    items = c.fetch_dramas(content_type="drama", platform="all", page=1, page_size=20)
    assert items == [], items
    download = c.download_drama(None)
    assert download.get("success") is False
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
