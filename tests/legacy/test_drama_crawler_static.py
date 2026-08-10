#!/usr/bin/env python3
"""验收：无 Playwright 时短剧爬虫应优先静态 JSON，而非随机假标题。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.plugins.drama_finder_plugin.crawler.drama_crawler import DramaCrawler
from app.plugins.drama_finder_plugin.crawler.drama_web_scraper import DramaWebScraper


KNOWN = "我在八零年代当后妈"


def main():
    ws = DramaWebScraper()
    assert os.path.exists(ws._cache_file), f"missing cache {ws._cache_file}"
    cached = ws.fetch_hot_list(limit=5)
    assert cached, "static cache empty"
    assert any(x.get("title") == KNOWN for x in cached), "known title not in cache"

    DramaCrawler._instance = None
    c = DramaCrawler()
    items = c.fetch_dramas(content_type="drama", platform="all", page=1, page_size=20)
    assert items, "fetch returned empty"
    titles = [d.title for d in items]
    assert KNOWN in titles, (
        f"expected static title in results, got sample={titles[:5]!r} "
        f"sources={getattr(c, '_last_data_source', None)}"
    )
    fresh = c.get_data_freshness()
    kinds = [k for _, k in fresh.get("sources", [])]
    assert fresh.get("has_static") or "static" in kinds, fresh
    assert not fresh.get("is_pure_fallback"), fresh
    print("titles sample:", titles[:3])
    print("freshness:", fresh)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
