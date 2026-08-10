"""兼容层：DramaWebScraper 已迁入 `app.plugins.drama_finder_plugin.crawler`。"""

from app.plugins.drama_finder_plugin.crawler.drama_web_scraper import *  # noqa: F401,F403
from app.plugins.drama_finder_plugin.crawler.drama_web_scraper import (  # noqa: F401
    DramaWebScraper,
    drama_web_scraper,
)
