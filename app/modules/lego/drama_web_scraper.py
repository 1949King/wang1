"""兼容层：转发插件内 DramaWebScraper 接口壳（功能已卸）。"""

from app.plugins.drama_finder_plugin.crawler.drama_web_scraper import *  # noqa: F401,F403
from app.plugins.drama_finder_plugin.crawler.drama_web_scraper import (  # noqa: F401
    DramaWebScraper,
    drama_web_scraper,
)
