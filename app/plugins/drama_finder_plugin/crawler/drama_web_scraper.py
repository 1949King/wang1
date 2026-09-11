# -*- coding: utf-8 -*-
"""短剧网页抓取接口壳。功能已卸，不请求、不读榜单缓存。"""
from __future__ import annotations

from typing import Dict, List

class DramaWebScraper:
    def __init__(self, cache_dir: str = None):
        self._cache_dir = cache_dir or ""
        self._cache_file = ""

    def fetch_hot_list(self, platform: str = "all", limit: int = 50) -> List[Dict]:
        return []

    def refresh_cache(self, dramas: List[Dict]):
        return None

    def get_source_health(self) -> Dict[str, bool]:
        return {"unloaded": True}


drama_web_scraper = DramaWebScraper()
